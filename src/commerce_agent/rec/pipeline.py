"""The recommendation pipeline: recall -> filters -> hybrid -> ranker -> diversity.

Used both by the offline evaluation (batched, :meth:`RecPipeline.run`) and by the
single-user API path in later phases (:meth:`RecPipeline.recommend`). Every stage is
deterministic; routes are toggled through :class:`RecConfig` (FR-R1).
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

from commerce_agent.rec import filters
from commerce_agent.rec.data import Catalog, FloatArray, Histories, IntArray
from commerce_agent.rec.rank.diversity import mmr
from commerce_agent.rec.rank.ranker import (
    DIVERSITY_TAG,
    RankerWeights,
    candidate_features,
    category_affinity,
    rank,
    reason_tags,
)
from commerce_agent.rec.recall.covisit import CovisitRecall
from commerce_agent.rec.recall.embedding import EmbeddingRecall
from commerce_agent.rec.recall.hybrid import RRFConfig, rrf_fuse
from commerce_agent.rec.recall.popularity import PopularityRecall
from commerce_agent.rec.topk import PAD, topk

ROUTES = ("popularity", "covisit", "embedding")


@dataclass(frozen=True, slots=True)
class RecConfig:
    routes: Collection[str] = ROUTES  # enabled recall routes
    rrf: RRFConfig = field(default_factory=RRFConfig)
    ranker: RankerWeights = field(default_factory=RankerWeights)
    candidates: int = 100  # hybrid candidates passed to the ranker
    mmr_lambda: float = 1.0  # 1.0 = no diversity re-ranking
    filter_unavailable: bool = True

    def __post_init__(self) -> None:
        unknown = set(self.routes) - set(ROUTES)
        if unknown:
            raise ValueError(f"unknown routes: {sorted(unknown)}")
        if not self.routes:
            raise ValueError("at least one recall route must be enabled")


@dataclass(frozen=True, slots=True)
class Recommendation:
    item_id: str
    score: float
    reason_tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BatchResult:
    items: npt.NDArray[np.int64]  # (B, k) final ranked items, PAD-padded
    scores: FloatArray  # (B, k) ranker scores of the final items
    features: FloatArray  # (B, k, F) ranker features of the final items
    diversity_moved: npt.NDArray[np.bool_]  # (B, k) item ranked higher than by the ranker


@dataclass(frozen=True, slots=True)
class RecPipeline:
    catalog: Catalog
    popularity: PopularityRecall
    covisit: CovisitRecall | None
    embedding: EmbeddingRecall | None
    config: RecConfig = field(default_factory=RecConfig)

    def _route(self, name: str) -> PopularityRecall | CovisitRecall | EmbeddingRecall | None:
        return {
            "popularity": self.popularity,
            "covisit": self.covisit,
            "embedding": self.embedding,
        }[name]

    def route_scores(
        self, hist: Histories, rows: IntArray, allowed: npt.NDArray[np.bool_]
    ) -> dict[str, FloatArray]:
        """Filtered dense scores of every enabled route that is available."""
        out: dict[str, FloatArray] = {}
        for name in sorted(self.config.routes):
            route = self._route(name)
            if route is not None:
                out[name] = filters.apply(route.scores(hist, rows), allowed)
        if not out:
            raise ValueError("no enabled recall route is available")
        return out

    def allowed(
        self,
        hist: Histories,
        rows: IntArray,
        *,
        include_categories: Collection[str] | None = None,
        exclude_categories: Collection[str] | None = None,
    ) -> npt.NDArray[np.bool_]:
        mask = filters.not_already_interacted(hist, rows, self.catalog.n_items)
        item_mask = filters.category_constraint(
            self.catalog, include=include_categories, exclude=exclude_categories
        )
        if self.config.filter_unavailable:
            item_mask &= filters.available(self.catalog)
        return mask & item_mask[None, :]

    def run(
        self,
        hist: Histories,
        rows: IntArray,
        k: int,
        *,
        allowed: npt.NDArray[np.bool_] | None = None,
        route_scores: dict[str, FloatArray] | None = None,
    ) -> BatchResult:
        if allowed is None:
            allowed = self.allowed(hist, rows)
        if route_scores is None:
            route_scores = self.route_scores(hist, rows, allowed)
        weights = {n: w for n, w in self.config.rrf.weights.items() if n in route_scores}
        rrf_cfg = RRFConfig(weights=weights, k=self.config.rrf.k, depth=self.config.rrf.depth)
        fused = rrf_fuse(route_scores, rrf_cfg)
        candidates = topk(fused, self.config.candidates)
        feats = candidate_features(
            candidates,
            fusion=fused,
            covisit=route_scores.get("covisit"),
            content=route_scores.get("embedding"),
            popularity_counts=self.popularity.counts,
            affinity=category_affinity(hist, rows, self.catalog.categories),
            categories=self.catalog.categories,
        )
        return self.rerank(candidates, feats, k)

    def rerank(self, candidates: npt.NDArray[np.int64], feats: FloatArray, k: int) -> BatchResult:
        ordered, scores, order = rank(candidates, feats, self.config.ranker)
        feats = np.take_along_axis(feats, order[:, :, None], axis=1)
        lam = self.config.mmr_lambda
        if lam < 1.0 and self.embedding is not None:
            items, positions = mmr(ordered, scores, self.embedding.vectors, k=k, lam=lam)
        else:
            items = ordered[:, :k].copy()
            positions = np.where(items == PAD, PAD, np.arange(items.shape[1])[None, :])
        safe = positions.clip(0)
        moved = (positions != PAD) & (safe > np.arange(positions.shape[1])[None, :])
        return BatchResult(
            items=items,
            scores=np.where(items == PAD, -np.inf, np.take_along_axis(scores, safe, 1)),
            features=np.take_along_axis(feats, safe[:, :, None], axis=1),
            diversity_moved=moved,
        )

    def recommend(
        self,
        history_item_ids: list[str],
        k: int = 10,
        *,
        include_categories: Collection[str] | None = None,
        exclude_categories: Collection[str] | None = None,
    ) -> list[Recommendation]:
        """Single-user path: returns items with scores and ``reason_tags`` (FR-R3)."""
        index = self.catalog.index()
        known = [index[i] for i in history_item_ids if i in index]
        hist = Histories(
            user_ids=("request",),
            indptr=np.array([0, len(known)], dtype=np.int64),
            items=np.array(known, dtype=np.int64),
            ratings=np.ones(len(known), dtype=np.float32),
        )
        rows = np.array([0], dtype=np.int64)
        allowed = self.allowed(
            hist,
            rows,
            include_categories=include_categories,
            exclude_categories=exclude_categories,
        )
        result = self.run(hist, rows, k, allowed=allowed)
        recs: list[Recommendation] = []
        for pos, item in enumerate(result.items[0]):
            if item == PAD:
                break
            tags = reason_tags(result.features[0, pos], self.config.ranker)
            if result.diversity_moved[0, pos]:
                tags.append(DIVERSITY_TAG)
            recs.append(
                Recommendation(
                    item_id=self.catalog.item_ids[int(item)],
                    score=float(result.scores[0, pos]),
                    reason_tags=tuple(tags),
                )
            )
        return recs
