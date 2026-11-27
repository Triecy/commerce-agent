"""FR-R1 (toggles, determinism), FR-R2 (filters), FR-R3 (ranker, reason_tags, MMR)."""

from __future__ import annotations

import numpy as np
import pytest

from commerce_agent.rec import filters
from commerce_agent.rec.data import Histories
from commerce_agent.rec.pipeline import RecConfig, RecPipeline
from commerce_agent.rec.rank.diversity import mmr
from commerce_agent.rec.rank.ranker import FEATURES, TAGS, RankerWeights, rank, reason_tags
from commerce_agent.rec.recall.covisit import CovisitConfig, CovisitRecall
from commerce_agent.rec.recall.embedding import EmbeddingConfig, EmbeddingRecall
from commerce_agent.rec.recall.popularity import PopularityRecall
from commerce_agent.rec.topk import PAD
from tests.unit.rec_fixtures import make_catalog, make_split, make_vectors


def _pipeline(config: RecConfig | None = None, stock: dict[str, int] | None = None) -> RecPipeline:
    catalog = make_catalog(stock)
    hist = Histories.build(make_split().train, catalog.index())
    return RecPipeline(
        catalog=catalog,
        popularity=PopularityRecall.fit(hist, catalog.n_items),
        covisit=CovisitRecall.fit(hist, catalog.n_items, CovisitConfig()),
        embedding=EmbeddingRecall(make_vectors(), EmbeddingConfig()),
        config=config or RecConfig(),
    )


HISTORY = ["I000", "I003", "I006"]


# ---------------------------------------------------------------- FR-R1


def test_FR_R1_same_input_same_output() -> None:
    a = _pipeline().recommend(HISTORY, 10)
    b = _pipeline().recommend(HISTORY, 10)
    assert a == b and len(a) == 10


def test_FR_R1_routes_can_be_toggled_independently() -> None:
    only_pop = _pipeline(
        RecConfig(routes=["popularity"], ranker=RankerWeights({"fusion": 1.0}))
    ).recommend(HISTORY, 5)
    pipe = _pipeline()
    order = np.lexsort((np.arange(pipe.catalog.n_items), -pipe.popularity.counts))
    expected = [pipe.catalog.item_ids[i] for i in order if pipe.catalog.item_ids[i] not in HISTORY]
    assert [r.item_id for r in only_pop] == expected[:5]
    for routes in (["covisit"], ["embedding"], ["covisit", "embedding"]):
        recs = _pipeline(RecConfig(routes=routes)).recommend(HISTORY, 5)
        assert recs, routes


def test_FR_R1_disabled_route_is_never_computed() -> None:
    pipe = _pipeline(RecConfig(routes=["popularity", "embedding"]))
    hist = Histories.build(make_split().train, pipe.catalog.index())
    rows = np.array([0, 1])
    scores = pipe.route_scores(hist, rows, pipe.allowed(hist, rows))
    assert sorted(scores) == ["embedding", "popularity"]


def test_FR_R1_config_rejects_unknown_or_empty_routes() -> None:
    with pytest.raises(ValueError):
        RecConfig(routes=["llm_rerank"])
    with pytest.raises(ValueError):
        RecConfig(routes=[])


# ---------------------------------------------------------------- FR-R2


def test_FR_R2_already_interacted_items_are_filtered() -> None:
    recs = _pipeline().recommend(HISTORY, 27)
    assert not {r.item_id for r in recs} & set(HISTORY)


def test_FR_R2_unavailable_items_are_filtered() -> None:
    out = {f"I{i:03d}": 0 for i in range(1, 30, 2)}
    stock = {f"I{i:03d}": 5 for i in range(30)} | out
    recs = _pipeline(stock=stock).recommend(HISTORY, 20)
    assert recs and not {r.item_id for r in recs} & set(out)
    off = _pipeline(RecConfig(filter_unavailable=False), stock=stock).recommend(HISTORY, 27)
    assert {r.item_id for r in off} & set(out)


def test_FR_R2_available_mask_unknown_stock_fails_open() -> None:
    catalog = make_catalog({"I000": 0, "I001": 3})
    mask = filters.available(catalog)
    assert not mask[0] and mask[1] and mask[2]  # I002 unknown -> allowed
    assert not filters.available(catalog, allow_unknown=False)[2]


def test_FR_R2_category_constraints() -> None:
    pipe = _pipeline()
    recs = pipe.recommend(HISTORY, 10, include_categories=["Puzzle"])
    assert recs and all(
        "Puzzle" in pipe.catalog.category_paths[pipe.catalog.index()[r.item_id]] for r in recs
    )
    recs = pipe.recommend(HISTORY, 30, exclude_categories=["Racing"])
    assert all(
        "Racing" not in pipe.catalog.category_paths[pipe.catalog.index()[r.item_id]] for r in recs
    )
    both = filters.category_constraint(pipe.catalog, include=["Racing"], exclude=["Racing"])
    assert not both.any()  # exclusion wins


def test_FR_R2_apply_sets_disallowed_to_neg_inf_without_mutating_input() -> None:
    scores = np.ones((2, 3), dtype=np.float32)
    out = filters.apply(scores, np.array([True, False, True]))
    assert out[0, 1] == -np.inf and scores[0, 1] == 1.0
    out2 = filters.apply(scores, np.array([[True, True, False], [False, True, True]]))
    assert out2[0, 2] == -np.inf and out2[1, 0] == -np.inf


# ---------------------------------------------------------------- FR-R3


def test_FR_R3_every_recommendation_has_reason_tags() -> None:
    recs = _pipeline(RecConfig(mmr_lambda=0.7)).recommend(HISTORY, 10)
    known = set(TAGS.values()) | {"diversity_pick"}
    assert recs
    for r in recs:
        assert r.reason_tags and set(r.reason_tags) <= known
    scores = [r.score for r in _pipeline().recommend(HISTORY, 10)]
    assert scores == sorted(scores, reverse=True)


def test_FR_R3_ranker_is_weighted_sum_with_index_tie_break() -> None:
    cand = np.array([[5, 2, 9, PAD]])
    feats = np.zeros((1, 4, len(FEATURES)), dtype=np.float32)
    feats[0, :3, FEATURES.index("covisit")] = [0.5, 0.5, 1.0]
    weights = RankerWeights({"covisit": 2.0})
    items, scores, order = rank(cand, feats, weights)
    assert items.tolist() == [[9, 2, 5, PAD]]
    assert scores[0, :3].tolist() == [2.0, 1.0, 1.0]
    assert order[0, 0] == 2
    with pytest.raises(ValueError):
        RankerWeights({"bogus": 1.0}).vector()


def test_FR_R3_reason_tags_follow_contributions() -> None:
    w = RankerWeights({"covisit": 1.0, "popularity": 1.0, "content": 1.0})
    row = np.zeros(len(FEATURES), dtype=np.float32)
    row[FEATURES.index("covisit")] = 0.9
    row[FEATURES.index("popularity")] = 0.05
    row[FEATURES.index("content")] = 0.3
    assert reason_tags(row, w) == ["co_visited_with_history", "similar_content"]
    assert reason_tags(np.zeros(len(FEATURES), dtype=np.float32), w)  # never empty


def test_FR_R3_mmr_lambda_one_keeps_order_and_lower_lambda_diversifies() -> None:
    vectors = np.array([[1, 0], [1, 0], [0, 1], [0.99, 0.141]], dtype=np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    cand = np.array([[0, 1, 3, 2]])
    rel = np.array([[1.0, 0.95, 0.9, 0.5]], dtype=np.float32)
    keep, _ = mmr(cand, rel, vectors, k=3, lam=1.0)
    assert keep.tolist() == [[0, 1, 3]]
    div, pos = mmr(cand, rel, vectors, k=3, lam=0.5)
    assert div[0, 0] == 0 and 2 in div[0].tolist()
    assert pos[0].tolist().index(3) == div[0].tolist().index(2)
    with pytest.raises(ValueError):
        mmr(cand, rel, vectors, k=2, lam=1.5)


def test_FR_R3_mmr_increases_intra_list_diversity() -> None:
    from commerce_agent.rec.eval.metrics import intra_list_diversity

    pipe = _pipeline()
    hist = Histories.build(make_split().train, pipe.catalog.index())
    rows = np.arange(hist.n_users)
    plain = pipe.run(hist, rows, 5).items
    diverse = (
        RecPipeline(
            pipe.catalog, pipe.popularity, pipe.covisit, pipe.embedding, RecConfig(mmr_lambda=0.3)
        )
        .run(hist, rows, 5)
        .items
    )
    vecs = make_vectors()
    assert (
        intra_list_diversity(diverse, vecs, 5).mean() >= intra_list_diversity(plain, vecs, 5).mean()
    )
