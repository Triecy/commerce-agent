"""FR-R1: recall routes, deterministic top-k, hybrid RRF, embedding text and cache."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pytest

from commerce_agent.common.embedding import HashingEncoder, cached_encode
from commerce_agent.data.canonicalize import ItemRow
from commerce_agent.data.split import Interaction
from commerce_agent.rec.data import Histories, history_matrix
from commerce_agent.rec.recall.covisit import CovisitConfig, CovisitRecall, build_covisit_matrix
from commerce_agent.rec.recall.embedding import EmbeddingConfig, EmbeddingRecall, item_text
from commerce_agent.rec.recall.hybrid import RRFConfig, rrf_from_ranks, rrf_fuse
from commerce_agent.rec.recall.popularity import PopularityRecall
from commerce_agent.rec.topk import PAD, ranks_from_topk, topk
from tests.unit.rec_fixtures import make_catalog, make_items, make_split, make_vectors

NEG = -np.inf


def _hist(seqs: Sequence[Sequence[int]], n_items: int) -> Histories:
    rows = [
        Interaction(f"u{u}", f"i{i}", t, 5.0)
        for u, seq in enumerate(seqs)
        for t, i in enumerate(seq)
    ]
    index = {f"i{i}": i for i in range(n_items)}
    return Histories.build(rows, index, [f"u{u}" for u in range(len(seqs))])


def test_FR_R1_topk_breaks_ties_by_lower_item_index() -> None:
    scores = np.array([[1.0, 3.0, 3.0, 2.0, 3.0]], dtype=np.float32)
    assert topk(scores, 2).tolist() == [[1, 2]]
    assert topk(scores, 4).tolist() == [[1, 2, 4, 3]]


def test_FR_R1_topk_skips_excluded_items_and_pads() -> None:
    scores = np.array([[NEG, 0.5, NEG, 0.1], [NEG, NEG, NEG, NEG]], dtype=np.float32)
    assert topk(scores, 3).tolist() == [[1, 3, PAD], [PAD, PAD, PAD]]


def test_FR_R1_topk_matches_full_stable_sort() -> None:
    rng = np.random.default_rng(0)
    scores = rng.integers(0, 5, size=(20, 50)).astype(np.float32)
    expected = np.argsort(-scores, axis=1, kind="stable")[:, :7]
    assert np.array_equal(topk(scores, 7), expected)


def test_FR_R1_ranks_from_topk() -> None:
    ranks = ranks_from_topk(np.array([[2, 0, PAD]]), 4)
    assert ranks.tolist() == [[2.0, np.inf, 1.0, np.inf]]


def test_FR_R1_popularity_counts_fit_histories() -> None:
    hist = _hist([[0, 1], [1, 2], [1]], 4)
    pop = PopularityRecall.fit(hist, 4)
    assert pop.counts.tolist() == [1, 3, 1, 0]
    scores = pop.scores(hist, np.array([0, 1]))
    assert scores.shape == (2, 4)
    assert topk(scores, 4)[0].tolist() == [1, 0, 2, 3]


def test_FR_R1_covisit_counts_pairs_within_window_symmetrically() -> None:
    hist = _hist([[0, 1, 2, 3]], 4)
    cfg = CovisitConfig(window=1, normalize="none")
    m = build_covisit_matrix(hist, 4, cfg).toarray()
    assert np.array_equal(m, m.T)
    assert m[0, 1] == 1 and m[1, 2] == 1 and m[0, 2] == 0
    m2 = build_covisit_matrix(hist, 4, CovisitConfig(window=2, normalize="none")).toarray()
    assert m2[0, 2] == 1 and m2[0, 3] == 0
    assert np.all(np.diag(m2) == 0)


def test_FR_R1_covisit_never_pairs_across_users() -> None:
    hist = _hist([[0, 1], [2, 3]], 4)
    m = build_covisit_matrix(hist, 4, CovisitConfig(window=5, normalize="none")).toarray()
    assert m[1, 2] == 0 and m[0, 3] == 0


def test_FR_R1_covisit_cosine_damps_popular_items_and_prunes() -> None:
    hist = _hist([[0, 1], [0, 2], [0, 3], [1, 2]], 4)
    raw = build_covisit_matrix(hist, 4, CovisitConfig(window=1, normalize="none")).toarray()
    cos = build_covisit_matrix(hist, 4, CovisitConfig(window=1, normalize="cosine")).toarray()
    assert raw[1, 0] == raw[1, 2] == 1
    assert cos[1, 2] > cos[1, 0]  # item 0 is popular, so its co-visits weigh less
    pruned = build_covisit_matrix(hist, 4, CovisitConfig(window=1, neighbors=1)).toarray()
    assert (pruned > 0).sum(axis=1).max() == 1


def test_FR_R1_covisit_scores_no_evidence_is_excluded() -> None:
    hist = _hist([[0, 1], [2, 3]], 5)
    route = CovisitRecall.fit(hist, 5, CovisitConfig(window=1, normalize="none"))
    scores = route.scores(hist, np.array([0]))
    assert scores[0, 1] > 0 and scores[0, 4] == NEG and scores[0, 2] == NEG


def test_FR_R1_history_matrix_recency_decay() -> None:
    hist = _hist([[0, 1, 2]], 3)
    m = history_matrix(hist, np.array([0]), 3, max_len=2, decay=0.5).toarray()[0]
    assert m[0] == 0
    assert m[2] == pytest.approx(2 / 3) and m[1] == pytest.approx(1 / 3)


def test_FR_R1_embedding_text_uses_only_allowed_fields_never_reviews() -> None:
    item = ItemRow(
        item_id="X",
        source="t",
        title="Space Racer",
        description="Fast ships.",
        features={
            "bullets": ["Split screen"],
            "details": {"Platform": "PS5"},
            "reviews": ["REVIEW TEXT MUST NOT LEAK"],
            "top_review": "ALSO NOT ALLOWED",
        },
        category_path=("Video Games",),
        price=None,
        brand="Acme",
        image_url=None,
    )
    text = item_text(item)
    assert "Space Racer" in text and "Split screen" in text and "Platform: PS5" in text
    assert "Fast ships." in text
    assert "REVIEW" not in text and "NOT ALLOWED" not in text
    assert "Acme" not in text  # brand is not one of the allowed fields


def test_FR_R1_embedding_route_prefers_same_cluster() -> None:
    catalog = make_catalog()
    vectors = make_vectors()
    split = make_split()
    hist = Histories.build(split.train, catalog.index())
    route = EmbeddingRecall(vectors, EmbeddingConfig())
    scores = route.scores(hist, np.array([0]))
    first = hist.of(0)
    top = topk(scores, 3)[0]
    assert all(catalog.categories[t] == catalog.categories[first[0]] for t in top)


def test_FR_R1_embedding_user_without_history_has_no_candidates() -> None:
    hist = _hist([[], [0]], 3)
    route = EmbeddingRecall(np.eye(3, dtype=np.float32), EmbeddingConfig())
    scores = route.scores(hist, np.array([0, 1]))
    assert np.all(scores[0] == NEG) and scores[1, 0] == pytest.approx(1.0)


def test_FR_R1_rrf_math_and_disabled_routes() -> None:
    a = {
        "x": np.array([[1.0, 2.0, np.inf]], dtype=np.float32),
        "y": np.array([[np.inf, 1.0, 2.0]], dtype=np.float32),
    }
    fused = rrf_from_ranks(a, RRFConfig(weights={"x": 1.0, "y": 1.0}, k=1))
    assert fused[0, 1] == pytest.approx(1 / 3 + 1 / 2)
    only_x = rrf_from_ranks(a, RRFConfig(weights={"x": 1.0, "y": 0.0}, k=1))
    assert only_x[0, 2] == NEG
    with pytest.raises(ValueError):
        rrf_from_ranks(a, RRFConfig(weights={"x": 0.0}, k=1))


def test_FR_R1_rrf_fuse_is_deterministic() -> None:
    rng = np.random.default_rng(1)
    scores = {
        "a": rng.random((4, 30)).astype(np.float32),
        "b": rng.integers(0, 3, (4, 30)).astype(np.float32),
    }
    cfg = RRFConfig(weights={"a": 1.0, "b": 0.5}, depth=10)
    assert np.array_equal(rrf_fuse(scores, cfg), rrf_fuse(scores, cfg))


class _CountingEncoder(HashingEncoder):
    calls: int = 0

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        type(self).calls += 1
        return HashingEncoder.encode(self, texts)


def test_FR_R1_embeddings_are_cached_on_disk(tmp_path: Path) -> None:
    texts = [item_text(it) for it in make_items(5)]
    enc = _CountingEncoder(dim_=8)
    first = cached_encode(enc, texts, tmp_path)
    second = cached_encode(enc, texts, tmp_path)
    assert _CountingEncoder.calls == 1
    assert np.array_equal(first, second)
    cached_encode(enc, [*texts[:-1], "changed"], tmp_path)
    assert _CountingEncoder.calls == 2  # new texts -> new cache key
    assert np.allclose(np.linalg.norm(first, axis=1), 1.0)
