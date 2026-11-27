"""FR-R5: full-ranking metrics, bootstrap CIs, and the E1 runner on synthetic data."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from commerce_agent.rec.eval import metrics
from commerce_agent.rec.eval.bootstrap import bootstrap_mean, paired_difference
from commerce_agent.rec.eval.e1 import (
    ARMS,
    E1Data,
    E1Params,
    global_timeline_overlap,
    render_report,
    run_e1,
)
from commerce_agent.rec.topk import PAD
from tests.unit.rec_fixtures import make_catalog, make_split, make_vectors


def test_FR_R5_target_rank_recall_and_ndcg() -> None:
    recs = np.array([[3, 1, 2], [0, 4, PAD], [5, 6, 7]])
    targets = np.array([1, 4, 9])
    ranks = metrics.target_rank(recs, targets)
    assert ranks.tolist() == [2, 2, 0]
    assert metrics.recall_at(ranks, 1).tolist() == [0, 0, 0]
    assert metrics.recall_at(ranks, 2).tolist() == [1, 1, 0]
    assert metrics.ndcg_at(ranks, 3)[0] == pytest.approx(1 / np.log2(3))
    assert metrics.ndcg_at(ranks, 1).sum() == 0


def test_FR_R5_coverage_and_diversity() -> None:
    recs = np.array([[0, 1], [1, PAD]])
    assert metrics.coverage(recs, 4, 2) == 0.5
    vecs = np.array([[1, 0], [0, 1]], dtype=np.float32)
    ild = metrics.intra_list_diversity(recs, vecs, 2)
    assert ild.tolist() == [1.0, 0.0]
    cats = np.array([0, 0])
    assert metrics.category_diversity(recs, cats, 2).tolist() == [0.5, 1.0]


def test_FR_R5_bootstrap_ci_is_seeded_and_contains_the_mean() -> None:
    rng = np.random.default_rng(3)
    values = rng.binomial(1, 0.2, 2000).astype(np.float64)
    a = bootstrap_mean(values, n_boot=200, seed=1)
    b = bootstrap_mean(values, n_boot=200, seed=1)
    assert a == b
    assert a.lo < a.mean < a.hi
    assert a.hi - a.lo < 0.05
    with pytest.raises(ValueError):
        bootstrap_mean(np.array([]))


def test_FR_R5_paired_difference_detects_a_shift() -> None:
    rng = np.random.default_rng(4)
    base = rng.random(1000)
    better = base + 0.1
    diff = paired_difference(better, base, n_boot=200, seed=0)
    assert diff.lo > 0.09 and diff.hi < 0.11
    with pytest.raises(ValueError):
        paired_difference(base, base[:10])


def test_FR_R5_global_timeline_overlap() -> None:
    split = make_split()
    out = global_timeline_overlap(split.train, split.test)
    assert 0.0 <= out["median_share_of_train_after_test_event"] <= 1.0


def test_FR_R5_e1_runner_is_deterministic_and_reports_all_arms() -> None:
    split = make_split()
    data = E1Data(make_catalog(), make_vectors(), split.train, split.valid, split.test)
    params = E1Params(tune_users=40, n_boot=50, batch=16, candidates=20, rrf_depth=25)
    first = run_e1(data, params)
    second = run_e1(data, params)
    for res in (first["test"], first["test_rating_ge_4"]):
        assert set(res["arms"]) == set(ARMS)
        for arm in ARMS:
            iv = res["arms"][arm]["ndcg@10"]
            assert iv["ci_low"] <= iv["mean"] <= iv["ci_high"]

    def timeless(r: dict[str, Any]) -> dict[str, Any]:
        out = {k: v for k, v in r.items() if k != "seconds_total"}
        for key in ("test", "test_rating_ge_4"):
            out[key] = {k: v for k, v in r[key].items() if k != "seconds"}
        return out

    assert timeless(first) == timeless(second)
    meta = {
        "git_commit": "abc",
        "git_dirty": True,
        "generated_at": "now",
        "n_items": 30,
        "n_boot": 50,
        "seed": params.seed,
        "candidates": 20,
        "encoder": "hashing:32",
        "vectors_sha256": "0" * 64,
        "machine": {"summary": "test"},
        "did_not_work": ["- x"],
    }
    report = render_report(first, meta)
    assert "## Limitations" in report and "What was tried and did not work" in report
    assert "Global-timeline caveat" in report and "rating >= 4" in report
