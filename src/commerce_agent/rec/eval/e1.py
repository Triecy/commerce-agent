"""Experiment E1: which recall / ranking approach works? (FR-R5, SPEC §8.1)

Protocol (ADR-0009, ADR-0012):

1. **Tune on validation.** History = train, target = each user's validation item.
   Every choice (co-visitation and embedding settings, RRF weights, ranker weights, MMR
   lambda) is made on a fixed, seeded subsample of validation users.
2. **Test once.** Models are refit on train + valid, history = train + valid, target =
   each user's test item. The frozen configuration is evaluated on **all** users; test
   numbers are never used to make a choice.
3. Full ranking over the catalog minus seen items; bootstrap 95% CIs over users;
   paired differences against the popularity baseline.
4. Robustness variant: only interactions with rating >= 4 count (fitting, history and
   targets), same frozen configuration.

``make eval-e1`` writes ``results.json`` and ``report.md`` to
``docs/results/e1/<commit>/``. No LLM is used.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import logging
import os
import platform
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from commerce_agent.common.embedding import (
    HashingEncoder,
    SentenceTransformerEncoder,
    TextEncoder,
    cached_encode,
)
from commerce_agent.common.logging import configure_logging
from commerce_agent.data.canonicalize import ItemRow, read_items
from commerce_agent.data.split import Interaction
from commerce_agent.rec.data import (
    Catalog,
    FloatArray,
    Histories,
    IntArray,
    read_split_csv,
    read_stock_csv,
)
from commerce_agent.rec.eval import metrics
from commerce_agent.rec.eval.bootstrap import bootstrap_mean, paired_difference
from commerce_agent.rec.pipeline import RecConfig, RecPipeline
from commerce_agent.rec.rank.ranker import (
    DIVERSITY_TAG,
    FEATURES,
    RankerWeights,
    candidate_features,
    category_affinity,
    reason_tags,
)
from commerce_agent.rec.recall.covisit import CovisitConfig, CovisitRecall
from commerce_agent.rec.recall.embedding import EmbeddingConfig, EmbeddingRecall, item_text
from commerce_agent.rec.recall.hybrid import RRFConfig, rrf_from_ranks
from commerce_agent.rec.recall.popularity import PopularityRecall
from commerce_agent.rec.topk import PAD, ranks_from_topk, topk

logger = logging.getLogger(__name__)

K_MAX = 20
ROUTE_ARMS = ("popularity", "covisit", "embedding")
ARMS = (
    "popularity",
    "covisit",
    "embedding",
    "hybrid_rrf",
    "hybrid_rrf_ranker",
    "hybrid_rrf_ranker_mmr",
)
BASELINE = "popularity"
PRIMARY = "ndcg@10"

# Tuning grids (validation only). Kept small on purpose; see the report.
COVISIT_GRID: tuple[CovisitConfig, ...] = tuple(
    CovisitConfig(window=w, normalize=n, decay=d)
    for w in (2, 5, 10)
    for n in ("none", "cosine")
    for d in (1.0, 0.7)
)
EMBEDDING_GRID: tuple[EmbeddingConfig, ...] = tuple(
    EmbeddingConfig(history_len=h, decay=d) for h in (5, 20) for d in (1.0, 0.8, 0.5)
)
RRF_GRID: tuple[tuple[float, float, float], ...] = tuple(
    itertools.product((0.0, 0.25, 0.5, 1.0), (0.5, 1.0, 2.0), (10.0, 60.0))
)  # (w_popularity, w_embedding, k); w_covisit fixed at 1
RANKER_VALUES = (0.0, 0.25, 0.5, 1.0, 2.0)
MMR_LAMBDAS = (1.0, 0.95, 0.9, 0.8, 0.7, 0.5)
MMR_MAX_RELATIVE_LOSS = 0.02  # most diverse lambda within 2% of the best NDCG@10


@dataclass(frozen=True, slots=True)
class E1Params:
    seed: int = 20261125
    tune_users: int = 20_000
    n_boot: int = 1000
    batch: int = 512
    candidates: int = 100
    rrf_depth: int = 200


@dataclass(frozen=True, slots=True)
class E1Data:
    catalog: Catalog
    vectors: FloatArray
    train: Sequence[Interaction]
    valid: Sequence[Interaction]
    test: Sequence[Interaction]


@dataclass(slots=True)
class Tuned:
    covisit: CovisitConfig = field(default_factory=CovisitConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    rrf: RRFConfig = field(default_factory=RRFConfig)
    ranker: RankerWeights = field(default_factory=RankerWeights)
    mmr_lambda: float = 1.0
    log: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- helpers


def _batches(n: int, size: int) -> Iterator[IntArray]:
    for start in range(0, n, size):
        yield np.arange(start, min(start + size, n), dtype=np.int64)


def _targets(rows: Sequence[Interaction], users: Sequence[str], index: dict[str, int]) -> IntArray:
    by_user = {x.user_id: index[x.item_id] for x in rows}
    return np.array([by_user.get(u, PAD) for u in users], dtype=np.int64)


def _seen_allowed(hist: Histories, rows: IntArray, n_items: int) -> npt.NDArray[np.bool_]:
    allowed = np.ones((len(rows), n_items), dtype=bool)
    for b, r in enumerate(rows):
        allowed[b, hist.of(int(r))] = False
    return allowed


def _ndcg10(recs: npt.NDArray[np.int64], targets: IntArray) -> float:
    return float(metrics.ndcg_at(metrics.target_rank(recs, targets), 10).mean())


def _filtered(scores: FloatArray, allowed: npt.NDArray[np.bool_]) -> FloatArray:
    scores[~allowed] = -np.inf
    return scores


# --------------------------------------------------------------------------- tuning


def _score_route(
    route: PopularityRecall | CovisitRecall | EmbeddingRecall,
    hist: Histories,
    targets: IntArray,
    n_items: int,
    batch: int,
) -> float:
    recs = np.full((hist.n_users, 10), PAD, dtype=np.int64)
    for rows in _batches(hist.n_users, batch):
        scores = _filtered(route.scores(hist, rows), _seen_allowed(hist, rows, n_items))
        recs[rows] = topk(scores, 10)
    return _ndcg10(recs, targets)


def tune(data: E1Data, params: E1Params) -> Tuned:
    """All choices on the validation subsample (history = train)."""
    cat = data.catalog
    n_items = cat.n_items
    index = cat.index()
    users = sorted({x.user_id for x in data.valid})
    rng = np.random.default_rng(params.seed)
    pick = np.sort(rng.choice(len(users), size=min(params.tune_users, len(users)), replace=False))
    tune_users = [users[int(i)] for i in pick]
    fit_hist = Histories.build(data.train, index)
    hist = Histories.build(data.train, index, tune_users)
    targets = _targets(data.valid, tune_users, index)
    tuned = Tuned()
    log: dict[str, Any] = {"users": len(tune_users), "seed": params.seed}

    pop = PopularityRecall.fit(fit_hist, n_items)
    log["popularity_ndcg@10"] = _score_route(pop, hist, targets, n_items, params.batch)

    rows_cov = []
    for cfg in COVISIT_GRID:
        t0 = time.perf_counter()
        score = _score_route(
            CovisitRecall.fit(fit_hist, n_items, cfg), hist, targets, n_items, params.batch
        )
        rows_cov.append({**asdict(cfg), "ndcg@10": score})
        logger.info(
            "tune covisit",
            extra={"cfg": asdict(cfg), "ndcg10": score, "s": round(time.perf_counter() - t0, 1)},
        )
    tuned.covisit = COVISIT_GRID[int(np.argmax([r["ndcg@10"] for r in rows_cov]))]
    log["covisit"] = rows_cov

    rows_emb = []
    for ecfg in EMBEDDING_GRID:
        score = _score_route(
            EmbeddingRecall(data.vectors, ecfg), hist, targets, n_items, params.batch
        )
        rows_emb.append({**asdict(ecfg), "ndcg@10": score})
        logger.info("tune embedding", extra={"cfg": asdict(ecfg), "ndcg10": score})
    tuned.embedding = EMBEDDING_GRID[int(np.argmax([r["ndcg@10"] for r in rows_emb]))]
    log["embedding"] = rows_emb
    single = {
        "popularity": log["popularity_ndcg@10"],
        "covisit": max(r["ndcg@10"] for r in rows_cov),
        "embedding": max(r["ndcg@10"] for r in rows_emb),
    }
    log["best_single_route"] = max(sorted(single), key=lambda n: single[n])

    covisit = CovisitRecall.fit(fit_hist, n_items, tuned.covisit)
    emb = EmbeddingRecall(data.vectors, tuned.embedding)
    routes: dict[str, PopularityRecall | CovisitRecall | EmbeddingRecall] = {
        "popularity": pop,
        "covisit": covisit,
        "embedding": emb,
    }
    # Cache each route's top-depth list once; RRF tuning only re-fuses ranks.
    tops: dict[str, npt.NDArray[np.int64]] = {
        name: np.full((hist.n_users, params.rrf_depth), PAD, dtype=np.int64) for name in routes
    }
    for rows in _batches(hist.n_users, params.batch):
        allowed = _seen_allowed(hist, rows, n_items)
        for name, route in routes.items():
            tops[name][rows] = topk(_filtered(route.scores(hist, rows), allowed), params.rrf_depth)

    def fused_for(cfg: RRFConfig, rows: IntArray) -> FloatArray:
        ranks = {n: ranks_from_topk(tops[n][rows], n_items) for n in cfg.enabled()}
        return rrf_from_ranks(ranks, cfg)

    rows_rrf = []
    for w_pop, w_emb, k in RRF_GRID:
        rcfg = RRFConfig(
            weights={"popularity": w_pop, "covisit": 1.0, "embedding": w_emb},
            k=k,
            depth=params.rrf_depth,
        )
        recs = np.full((hist.n_users, 10), PAD, dtype=np.int64)
        for rows in _batches(hist.n_users, params.batch):
            recs[rows] = topk(fused_for(rcfg, rows), 10)
        score = _ndcg10(recs, targets)
        rows_rrf.append(
            {
                "w_popularity": w_pop,
                "w_covisit": 1.0,
                "w_embedding": w_emb,
                "k": k,
                "ndcg@10": score,
            }
        )
    best = max(rows_rrf, key=lambda r: r["ndcg@10"])
    tuned.rrf = RRFConfig(
        weights={
            "popularity": best["w_popularity"],
            "covisit": 1.0,
            "embedding": best["w_embedding"],
        },
        k=best["k"],
        depth=params.rrf_depth,
    )
    log["rrf"] = rows_rrf

    # Candidate features once for the tuned fusion; ranker/MMR tuning reuses them.
    cand = np.full((hist.n_users, params.candidates), PAD, dtype=np.int64)
    feats = np.zeros((hist.n_users, params.candidates, len(FEATURES)), dtype=np.float32)
    for rows in _batches(hist.n_users, params.batch):
        allowed = _seen_allowed(hist, rows, n_items)
        fused = fused_for(tuned.rrf, rows)
        cand[rows] = topk(fused, params.candidates)
        feats[rows] = candidate_features(
            cand[rows],
            fusion=fused,
            covisit=_filtered(covisit.scores(hist, rows), allowed),
            content=_filtered(emb.scores(hist, rows), allowed),
            popularity_counts=pop.counts,
            affinity=category_affinity(hist, rows, cat.categories),
            categories=cat.categories,
        )

    pipe = RecPipeline(
        catalog=cat,
        popularity=pop,
        covisit=covisit,
        embedding=emb,
    )

    def ranked_ndcg(weights: dict[str, float], lam: float = 1.0) -> tuple[float, float]:
        cfg = RecConfig(ranker=RankerWeights(weights), mmr_lambda=lam)
        p = replace(pipe, config=cfg)
        recs = np.full((hist.n_users, 10), PAD, dtype=np.int64)
        for rows in _batches(hist.n_users, params.batch):
            recs[rows] = p.rerank(cand[rows], feats[rows], 10).items
        ild = float(metrics.intra_list_diversity(recs, data.vectors, 10).mean())
        return _ndcg10(recs, targets), ild

    weights = dict.fromkeys(FEATURES, 0.0) | {"fusion": 1.0}
    best_score = ranked_ndcg(weights)[0]
    rows_rank = [{"weights": dict(weights), "ndcg@10": best_score}]
    for _round in range(2):
        for feat in FEATURES:
            for value in RANKER_VALUES:
                trial = weights | {feat: value}
                if trial == weights or not any(trial.values()):
                    continue
                score = ranked_ndcg(trial)[0]
                rows_rank.append({"weights": dict(trial), "ndcg@10": score})
                if score > best_score:
                    best_score, weights = score, trial
    tuned.ranker = RankerWeights(weights)
    log["ranker"] = {"best": weights, "best_ndcg@10": best_score, "trials": rows_rank}

    rows_mmr = []
    for lam in MMR_LAMBDAS:
        score, ild = ranked_ndcg(weights, lam)
        rows_mmr.append({"lambda": lam, "ndcg@10": score, "ild@10": ild})
    top = max(r["ndcg@10"] for r in rows_mmr)
    eligible = [r for r in rows_mmr if r["ndcg@10"] >= (1 - MMR_MAX_RELATIVE_LOSS) * top]
    tuned.mmr_lambda = min(eligible, key=lambda r: r["lambda"])["lambda"]
    log["mmr"] = {
        "rule": f"smallest lambda with NDCG@10 >= {1 - MMR_MAX_RELATIVE_LOSS} x best",
        "trials": rows_mmr,
        "chosen": tuned.mmr_lambda,
    }
    tuned.log = log
    return tuned


# --------------------------------------------------------------------------- evaluation


def evaluate(
    data: E1Data,
    tuned: Tuned,
    params: E1Params,
    *,
    fit: Sequence[Interaction],
    targets_rows: Sequence[Interaction],
) -> dict[str, Any]:
    """Run every arm once on all users in ``targets_rows`` (history = ``fit``)."""
    cat = data.catalog
    n_items = cat.n_items
    index = cat.index()
    users = sorted({x.user_id for x in targets_rows})
    fit_hist = Histories.build(fit, index)
    hist = Histories.build(fit, index, users)
    targets = _targets(targets_rows, users, index)
    pop = PopularityRecall.fit(fit_hist, n_items)
    covisit = CovisitRecall.fit(fit_hist, n_items, tuned.covisit)
    emb = EmbeddingRecall(data.vectors, tuned.embedding)
    base_cfg = RecConfig(
        rrf=tuned.rrf,
        ranker=tuned.ranker,
        candidates=params.candidates,
        filter_unavailable=False,  # simulated stock must not remove ground truth (ADR-0012)
    )
    pipe = RecPipeline(catalog=cat, popularity=pop, covisit=covisit, embedding=emb, config=base_cfg)
    pipe_mmr = replace(pipe, config=replace(base_cfg, mmr_lambda=tuned.mmr_lambda))

    recs = {arm: np.full((len(users), K_MAX), PAD, dtype=np.int64) for arm in ARMS}
    tag_counts: Counter[str] = Counter()
    t0 = time.perf_counter()
    for rows in _batches(len(users), params.batch):
        allowed = _seen_allowed(hist, rows, n_items)
        scores = pipe.route_scores(hist, rows, allowed)
        tops = {n: topk(s, params.rrf_depth) for n, s in scores.items()}
        for name in ROUTE_ARMS:
            recs[name][rows] = tops[name][:, :K_MAX]
        ranks = {n: ranks_from_topk(t, n_items) for n, t in tops.items()}
        fused = rrf_from_ranks(ranks, tuned.rrf)
        recs["hybrid_rrf"][rows] = topk(fused, K_MAX)
        cand = topk(fused, params.candidates)
        feats = candidate_features(
            cand,
            fusion=fused,
            covisit=scores["covisit"],
            content=scores["embedding"],
            popularity_counts=pop.counts,
            affinity=category_affinity(hist, rows, cat.categories),
            categories=cat.categories,
        )
        recs["hybrid_rrf_ranker"][rows] = pipe.rerank(cand, feats, K_MAX).items
        final = pipe_mmr.rerank(cand, feats, K_MAX)
        recs["hybrid_rrf_ranker_mmr"][rows] = final.items
        for b in range(len(rows)):
            for pos in range(10):
                if final.items[b, pos] == PAD:
                    break
                tags = reason_tags(final.features[b, pos], tuned.ranker)
                if final.diversity_moved[b, pos]:
                    tags.append(DIVERSITY_TAG)
                tag_counts.update(tags)
    elapsed = time.perf_counter() - t0

    per_user: dict[str, dict[str, npt.NDArray[np.float64]]] = {}
    lists: dict[str, dict[str, float]] = {}
    for arm, r in recs.items():
        ranks_ = metrics.target_rank(r, targets)
        per_user[arm] = {
            "recall@10": metrics.recall_at(ranks_, 10),
            "recall@20": metrics.recall_at(ranks_, 20),
            "ndcg@10": metrics.ndcg_at(ranks_, 10),
            "hitrate@10": metrics.recall_at(ranks_, 10),
            "ild@10": metrics.intra_list_diversity(r, data.vectors, 10),
            "category_diversity@10": metrics.category_diversity(r, cat.categories, 10),
        }
        lists[arm] = {
            "coverage@10": metrics.coverage(r, n_items, 10),
            "coverage@20": metrics.coverage(r, n_items, 20),
            "users_with_short_list": int((r[:, 9] == PAD).sum()),
        }

    seed = params.seed
    best_single = tuned.log.get("best_single_route", "covisit")
    results: dict[str, Any] = {
        "arms": {},
        "vs_popularity": {},
        "best_single_route": best_single,
        "vs_best_single_route": {},
    }
    for arm in ARMS:
        results["arms"][arm] = {
            m: bootstrap_mean(v, n_boot=params.n_boot, seed=seed).as_dict()
            for m, v in per_user[arm].items()
        } | lists[arm]
        if arm != BASELINE:
            results["vs_popularity"][arm] = {
                m: paired_difference(
                    per_user[arm][m], per_user[BASELINE][m], n_boot=params.n_boot, seed=seed
                ).as_dict()
                for m in ("recall@10", "recall@20", "ndcg@10")
            }
    for arm in ARMS[3:]:
        results["vs_best_single_route"][arm] = {
            m: paired_difference(
                per_user[arm][m], per_user[best_single][m], n_boot=params.n_boot, seed=seed
            ).as_dict()
            for m in ("recall@10", "recall@20", "ndcg@10")
        }
    total_tags = sum(tag_counts.values()) or 1
    results["reason_tags_top10"] = {
        t: {"count": c, "share_of_tags": c / total_tags} for t, c in sorted(tag_counts.items())
    }
    results["users"] = len(users)
    results["users_without_history"] = int((np.diff(hist.indptr) == 0).sum())
    results["seconds"] = round(elapsed, 1)
    return results


def global_timeline_overlap(
    train: Sequence[Interaction], test: Sequence[Interaction]
) -> dict[str, float]:
    """How much of the training data is later in calendar time than each test event."""
    train_ts = np.sort(np.array([x.ts_ms for x in train], dtype=np.int64))
    test_ts = np.array([x.ts_ms for x in test], dtype=np.int64)
    later = 1.0 - np.searchsorted(train_ts, test_ts, side="right") / len(train_ts)
    return {
        "median_share_of_train_after_test_event": float(np.median(later)),
        "share_of_test_events_with_any_later_train": float((later > 0).mean()),
    }


def run_e1(data: E1Data, params: E1Params) -> dict[str, Any]:
    t0 = time.perf_counter()
    tuned = tune(data, params)
    logger.info("tuning done", extra={"s": round(time.perf_counter() - t0, 1)})
    fit_main = [*data.train, *data.valid]
    main = evaluate(data, tuned, params, fit=fit_main, targets_rows=data.test)
    pos = [x for x in fit_main if x.rating >= 4]
    robust = evaluate(
        data, tuned, params, fit=pos, targets_rows=[x for x in data.test if x.rating >= 4]
    )
    return {
        "tuned": {
            "covisit": asdict(tuned.covisit),
            "embedding": asdict(tuned.embedding),
            "rrf": {"weights": dict(tuned.rrf.weights), "k": tuned.rrf.k, "depth": tuned.rrf.depth},
            "ranker": dict(tuned.ranker.weights),
            "mmr_lambda": tuned.mmr_lambda,
        },
        "tuning": tuned.log,
        "test": main,
        "test_rating_ge_4": robust,
        "global_timeline": global_timeline_overlap(data.train, data.test),
        "seconds_total": round(time.perf_counter() - t0, 1),
    }


# --------------------------------------------------------------------------- report


def _fmt(iv: dict[str, float], scale: float = 1.0, digits: int = 4) -> str:
    return (
        f"{iv['mean'] * scale:.{digits}f} "
        f"[{iv['ci_low'] * scale:.{digits}f}, {iv['ci_high'] * scale:.{digits}f}]"
    )


def _arm_table(res: dict[str, Any]) -> list[str]:
    lines = [
        "| Arm | Recall@10 | Recall@20 | NDCG@10 | Coverage@10 | ILD@10 | Cat. div.@10 |",
        "|---|---|---|---|---|---|---|",
    ]
    for arm in ARMS:
        a = res["arms"][arm]
        lines.append(
            f"| `{arm}` | {_fmt(a['recall@10'])} | {_fmt(a['recall@20'])} | {_fmt(a['ndcg@10'])}"
            f" | {a['coverage@10']:.3f} | {a['ild@10']['mean']:.3f}"
            f" | {a['category_diversity@10']['mean']:.3f} |"
        )
    return lines


def _diff_table(
    res: dict[str, Any], key: str = "vs_popularity", label: str = "popularity"
) -> list[str]:
    lines = [
        f"| Arm - {label} | ΔRecall@10 | ΔRecall@20 | ΔNDCG@10 | Significant (NDCG@10)? |",
        "|---|---|---|---|---|",
    ]
    for arm in res[key]:
        d = res[key][arm]
        nd = d["ndcg@10"]
        verdict = (
            "better" if nd["ci_low"] > 0 else "worse" if nd["ci_high"] < 0 else "no difference"
        )
        lines.append(
            f"| `{arm}` | {_fmt(d['recall@10'])} | {_fmt(d['recall@20'])} | {_fmt(nd)}"
            f" | {verdict} |"
        )
    return lines


def _verdict(res: dict[str, Any], arm: str) -> str:
    nd = res["vs_popularity"][arm]["ndcg@10"]
    if nd["ci_low"] > 0:
        return "beats"
    if nd["ci_high"] < 0:
        return "is worse than"
    return "does not differ significantly from"


def render_report(result: dict[str, Any], meta: dict[str, Any]) -> str:
    main = result["test"]
    robust = result["test_rating_ge_4"]
    tl = result["global_timeline"]
    tuned = result["tuned"]
    tuning = result["tuning"]
    best_arm = max(ARMS, key=lambda a: main["arms"][a]["ndcg@10"]["mean"])
    lines = [
        "# E1: Recall and ranking baselines on Amazon Reviews 2023 Video_Games",
        "",
        f"Commit `{meta['git_commit']}`{' (uncommitted changes)' if meta['git_dirty'] else ''}"
        f" · generated by `make eval-e1` · {meta['generated_at']}",
        "",
        "Data: Hou et al., *Bridging Language and Items for Retrieval and Recommendation*,"
        " arXiv:2403.03952, 2024 (see `docs/data-card.md`). Aggregates only; no review text.",
        "",
        "## Question",
        "",
        "Which recall / ranking approach works on a leave-last-out temporal split?"
        " Hypothesis (SPEC §8.1): hybrid > popularity.",
        "",
        "## Answer",
        "",
        f"- On the test set ({main['users']:,} users, full ranking over"
        f" {meta['n_items']:,} items), `hybrid_rrf` **{_verdict(main, 'hybrid_rrf')}** the"
        " popularity baseline on NDCG@10, and the full pipeline (`hybrid_rrf_ranker_mmr`)"
        f" **{_verdict(main, 'hybrid_rrf_ranker_mmr')}** it (paired bootstrap 95% CI).",
        f"- Best arm by NDCG@10: `{best_arm}` ({_fmt(main['arms'][best_arm]['ndcg@10'])}).",
        f"- Rating >= 4 robustness variant ({robust['users']:,} users): `hybrid_rrf`"
        f" {_verdict(robust, 'hybrid_rrf')} popularity; full pipeline"
        f" {_verdict(robust, 'hybrid_rrf_ranker_mmr')} popularity.",
        "",
        "## Method",
        "",
        "- **Split** (P1, data card §6): per user, last interaction = test, second-to-last ="
        " validation, rest = train. Every review counts as a positive interaction.",
        "- **Tuning** on a seeded subsample of"
        f" {tuning['users']:,} validation users (history = train). Grids are in"
        " `results.json`. Choices are frozen before the test run.",
        "- **Test, once:** models refit on train + valid; history = train + valid; one"
        " held-out item per user; all users.",
        "- **Full ranking:** each list is ranked over the whole catalog minus the user's"
        " seen items; no sampled negatives (ADR-0009). Ties: lower item_id first.",
        "- **Availability filter is off in evaluation**: the stock is simulated (FR-D3), and"
        " removing out-of-stock items would delete real ground truth. The filter is unit"
        " tested (FR-R2) and on by default in the serving pipeline.",
        f"- **Statistics:** percentile bootstrap over users, {meta['n_boot']} resamples,"
        f" seed {meta['seed']}; differences vs popularity are paired. Recall@K equals"
        " HitRate@K here because each user has exactly one target. Coverage is a"
        " catalog-level number and has no CI.",
        "- **Arms:** `popularity` (train counts); `covisit` (item-item co-occurrence within a"
        " window of each user's sequence); `embedding` (content vectors from title,"
        " features, details and description; never reviews); `hybrid_rrf` (weighted RRF of"
        " the three); `hybrid_rrf_ranker` (explainable feature-weighted ranker over the top"
        f" {meta['candidates']} RRF candidates); `hybrid_rrf_ranker_mmr` (plus MMR diversity"
        " re-ranking).",
        f"- **Embedding model:** `{meta['encoder']}` on CPU; vectors cached on disk"
        f" (sha256 `{meta['vectors_sha256'][:16]}…`).",
        "",
        "### Frozen configuration (chosen on validation)",
        "",
        "```json",
        json.dumps(tuned, indent=2),
        "```",
        "",
        "## Results: test set, all interactions (main result)",
        "",
        "Mean [95% CI].",
        "",
        *_arm_table(main),
        "",
        "Paired differences against popularity:",
        "",
        *_diff_table(main),
        "",
        f"Paired differences against the best single route on validation"
        f" (`{main['best_single_route']}`):",
        "",
        *_diff_table(main, "vs_best_single_route", main["best_single_route"]),
        "",
        "Users whose top-10 list is shorter than 10 (a pure route had too few candidates): "
        + ", ".join(f"`{a}` {main['arms'][a]['users_with_short_list']:,}" for a in ARMS)
        + ".",
        "",
        "Reason tags on the final top-10 lists (share of all tags emitted):",
        "",
        "| Tag | Share |",
        "|---|---|",
        *[f"| `{t}` | {v['share_of_tags']:.3f} |" for t, v in main["reason_tags_top10"].items()],
        "",
        "## Robustness variant: rating >= 4 only",
        "",
        "Interactions with rating < 4 are removed from fitting and history; only users whose"
        f" test item is rated >= 4 are evaluated ({robust['users']:,} users,"
        f" {robust['users_without_history']:,} of them with no remaining history). The"
        " configuration is the one tuned on the main setting.",
        "",
        *_arm_table(robust),
        "",
        *_diff_table(robust),
        "",
        "## Validation tuning summary",
        "",
        f"- Popularity NDCG@10 on the tuning users: {tuning['popularity_ndcg@10']:.4f}.",
        "- Co-visitation (window, normalization, recency decay):",
        "",
        "| window | normalize | decay | NDCG@10 |",
        "|---|---|---|---|",
        *[
            f"| {r['window']} | {r['normalize']} | {r['decay']} | {r['ndcg@10']:.4f} |"
            for r in tuning["covisit"]
        ],
        "",
        "- Embedding user profile (history length, recency decay):",
        "",
        "| history_len | decay | NDCG@10 |",
        "|---|---|---|",
        *[
            f"| {r['history_len']} | {r['decay']} | {r['ndcg@10']:.4f} |"
            for r in tuning["embedding"]
        ],
        "",
        "- RRF: best of the grid (covisit weight fixed at 1):",
        "",
        "| w_popularity | w_embedding | k | NDCG@10 |",
        "|---|---|---|---|",
        *[
            f"| {r['w_popularity']} | {r['w_embedding']} | {r['k']} | {r['ndcg@10']:.4f} |"
            for r in sorted(tuning["rrf"], key=lambda r: -r["ndcg@10"])[:8]
        ],
        "",
        f"- Ranker (coordinate ascent, 2 rounds): best NDCG@10"
        f" {tuning['ranker']['best_ndcg@10']:.4f} with weights"
        f" `{json.dumps(tuning['ranker']['best'])}`.",
        f"- MMR ({tuning['mmr']['rule']}):",
        "",
        "| lambda | NDCG@10 | ILD@10 |",
        "|---|---|---|",
        *[
            f"| {r['lambda']} | {r['ndcg@10']:.4f} | {r['ild@10']:.3f} |"
            for r in tuning["mmr"]["trials"]
        ],
        "",
        "## Limitations",
        "",
        "- **Global-timeline caveat.** Leave-last-out splits per user, not at one global"
        " cut-off date. For the median test event,"
        f" {tl['median_share_of_train_after_test_event']:.1%} of training interactions"
        " happen later in calendar time"
        f" ({tl['share_of_test_events_with_any_later_train']:.1%} of test events have at"
        " least one later training interaction). Popularity and co-visitation therefore"
        ' see some "future" trends; absolute numbers are optimistic compared with a'
        " global temporal split, and popularity benefits most.",
        "- **Rating >= 4 variant.** The main result counts 1-3 star reviews as positive"
        " signals (owner decision, data card §10). The variant shows how the ranking of arms"
        " changes when they are excluded; it is not tuned separately, and its user set is"
        " smaller and different, so its numbers are not directly comparable with the main"
        " table.",
        "- **Reviews are a proxy for purchases**; 5-core filtering keeps active users and"
        " popular items. Offline metrics only; no claim about online CTR/CVR (SPEC §14).",
        "- **One held-out item per user** makes per-user metrics binary and noisy; the CIs"
        " reflect that. Coverage has no CI.",
        "- **Small tuning grids** on a 20k-user validation subsample; a larger search could"
        " move every learned arm. Popularity has nothing to tune, so the comparison"
        " slightly favors the tuned arms on validation, but test numbers are untouched by"
        " tuning.",
        "- **Simulated inventory** is not used in evaluation (see Method).",
        "- **Embedding text** truncated to 256 tokens (title, bullets and details come"
        " first); description tails are not embedded.",
        "",
        "## What was tried and did not work",
        "",
        *meta["did_not_work"],
        "",
        "## Reproduce",
        "",
        "```bash",
        "make data      # P1 outputs (once)",
        "make eval-e1   # this report; embeddings are cached in data/cache/embeddings/",
        "```",
        "",
        f"Total runtime {result['seconds_total']:.0f} s on {meta['machine']['summary']}.",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- CLI


def _git(*args: str) -> str:
    try:
        out = subprocess.run(  # noqa: S603
            ["git", *args],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip()


def _machine() -> dict[str, Any]:
    cpu = platform.processor()
    if sys.platform == "darwin":
        cpu = _sysctl("machdep.cpu.brand_string") or cpu
        mem = int(_sysctl("hw.memsize") or 0)
    else:
        mem = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    summary = f"{cpu}, {os.cpu_count()} cores, {mem / 2**30:.0f} GiB RAM, {platform.platform()}"
    return {
        "cpu": cpu,
        "cores": os.cpu_count(),
        "memory_bytes": mem,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "summary": summary,
    }


def _sysctl(name: str) -> str:
    try:
        out = subprocess.run(  # noqa: S603
            ["/usr/sbin/sysctl", "-n", name],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


DID_NOT_WORK_PATH = Path("docs/results/e1/did-not-work.md")


def _did_not_work() -> list[str]:
    if DID_NOT_WORK_PATH.exists():
        return DID_NOT_WORK_PATH.read_text(encoding="utf-8").strip().splitlines()
    return ["- (none recorded)"]


def load_data(
    processed_dir: Path, raw_dir: Path, cache_dir: Path, encoder: TextEncoder
) -> tuple[E1Data, list[ItemRow]]:
    train = read_split_csv(processed_dir / "train.csv.gz")
    valid = read_split_csv(processed_dir / "valid.csv.gz")
    test = read_split_csv(processed_dir / "test.csv.gz")
    item_ids = {x.item_id for x in (*train, *valid, *test)}
    items = read_items(raw_dir / "meta_Video_Games.jsonl.gz", item_ids, source="amazon2023")
    stock = read_stock_csv(processed_dir / "inventory_simulated.csv.gz")
    catalog = Catalog.build(items, stock)
    vectors = cached_encode(encoder, [item_text(it) for it in items], cache_dir)
    return E1Data(catalog, vectors, train, valid, test), items


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--processed-dir", type=Path, default=Path("data/processed/video_games"))
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--cache-dir", type=Path, default=Path("data/cache/embeddings"))
    parser.add_argument("--out-root", type=Path, default=Path("docs/results/e1"))
    parser.add_argument("--encoder", choices=("bge", "hashing"), default="bge")
    parser.add_argument("--tune-users", type=int, default=E1Params().tune_users)
    parser.add_argument("--n-boot", type=int, default=E1Params().n_boot)
    parser.add_argument(
        "--render-only",
        type=Path,
        default=None,
        help="re-render report.md from an existing results.json directory (no re-run)",
    )
    args = parser.parse_args(argv)
    configure_logging()
    if args.render_only is not None:
        stored = json.loads((args.render_only / "results.json").read_text(encoding="utf-8"))
        stored_meta = stored.pop("meta")
        stored_meta["did_not_work"] = _did_not_work()
        (args.render_only / "report.md").write_text(
            render_report(stored, stored_meta), encoding="utf-8"
        )
        print(f"E1 report re-rendered in {args.render_only}")
        return

    encoder: TextEncoder = (
        SentenceTransformerEncoder() if args.encoder == "bge" else HashingEncoder()
    )
    params = E1Params(tune_users=args.tune_users, n_boot=args.n_boot)
    data, items = load_data(args.processed_dir, args.raw_dir, args.cache_dir, encoder)
    result = run_e1(data, params)

    commit = _git("rev-parse", "--short=12", "HEAD") or "unknown"
    dirty = bool(_git("status", "--porcelain", "--", ".", ":(exclude)docs/results"))
    meta: dict[str, Any] = {
        "experiment": "E1",
        "git_commit": commit,
        "git_dirty": dirty,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "uv_lock_sha256": _sha256(Path("uv.lock")) if Path("uv.lock").exists() else None,
        "data_files_sha256": {
            p.name: _sha256(p) for p in sorted(args.processed_dir.glob("*.csv.gz"))
        },
        "n_items": data.catalog.n_items,
        "encoder": encoder.identity,
        "vectors_sha256": hashlib.sha256(data.vectors.tobytes()).hexdigest(),
        "seed": params.seed,
        "n_boot": params.n_boot,
        "tune_users": params.tune_users,
        "candidates": params.candidates,
        "rrf_depth": params.rrf_depth,
        "runs": 1,
        "llm_used": False,
        "machine": _machine(),
        "did_not_work": _did_not_work(),
    }
    out_dir = args.out_root / (commit + ("-dirty" if dirty else ""))
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(
        json.dumps({"meta": meta, **result}, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out_dir / "report.md").write_text(render_report(result, meta), encoding="utf-8")
    del items
    print(f"E1 written to {out_dir}")


if __name__ == "__main__":
    main()
