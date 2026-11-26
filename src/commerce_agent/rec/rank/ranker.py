"""Explainable feature-weighted ranker (FR-R3).

Each candidate gets five features in ``[0, 1]``; the score is their weighted sum, so
every score decomposes into per-feature contributions. ``reason_tags`` name the
features that contribute most (see :func:`reason_tags`).

Features (reason tag in brackets):

- ``fusion``: hybrid RRF score / best RRF score among the user's candidates
  [``multi_route_agreement``].
- ``covisit``: co-visitation score / best co-visitation score [``co_visited_with_history``].
- ``content``: cosine similarity to the user's content vector, clipped to [0, 1]
  [``similar_content``].
- ``popularity``: ``log1p(count) / log1p(max count)`` [``popular``].
- ``category``: share of the user's history in the item's category [``preferred_category``].
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

from commerce_agent.rec.data import FloatArray, Histories, IntArray
from commerce_agent.rec.topk import PAD

FEATURES = ("fusion", "covisit", "content", "popularity", "category")
TAGS = {
    "fusion": "multi_route_agreement",
    "covisit": "co_visited_with_history",
    "content": "similar_content",
    "popularity": "popular",
    "category": "preferred_category",
}
DIVERSITY_TAG = "diversity_pick"


@dataclass(frozen=True, slots=True)
class RankerWeights:
    weights: Mapping[str, float] = field(
        default_factory=lambda: {
            "fusion": 1.0,
            "covisit": 1.0,
            "content": 1.0,
            "popularity": 0.5,
            "category": 0.5,
        }
    )

    def vector(self) -> FloatArray:
        unknown = set(self.weights) - set(FEATURES)
        if unknown:
            raise ValueError(f"unknown ranker features: {sorted(unknown)}")
        return np.array([self.weights.get(f, 0.0) for f in FEATURES], dtype=np.float32)


def _row_max_normalize(values: FloatArray) -> FloatArray:
    finite = np.where(np.isfinite(values), values, 0.0).clip(min=0.0)
    top = finite.max(axis=1, keepdims=True)
    top[top == 0] = 1.0
    out: FloatArray = (finite / top).astype(np.float32)
    return out


def category_affinity(hist: Histories, rows: IntArray, categories: IntArray) -> FloatArray:
    """``(B, n_categories)``: share of each user's full history per category."""
    n_cat = int(categories.max()) + 1 if len(categories) else 0
    out = np.zeros((len(rows), n_cat), dtype=np.float32)
    for b, r in enumerate(rows):
        seq = hist.of(int(r))
        if len(seq):
            out[b] = np.bincount(categories[seq], minlength=n_cat) / len(seq)
    return out


def candidate_features(
    candidates: npt.NDArray[np.int64],
    *,
    fusion: FloatArray,
    covisit: FloatArray | None,
    content: FloatArray | None,
    popularity_counts: FloatArray,
    affinity: FloatArray,
    categories: IntArray,
) -> FloatArray:
    """``(B, N, F)`` feature tensor for ``(B, N)`` candidate indices (``PAD`` -> zeros)."""
    safe = np.where(candidates == PAD, 0, candidates)
    rows = np.arange(candidates.shape[0])[:, None]
    n_rows, n_cand = candidates.shape
    feats = np.zeros((n_rows, n_cand, len(FEATURES)), dtype=np.float32)
    feats[:, :, 0] = _row_max_normalize(fusion[rows, safe])
    if covisit is not None:
        feats[:, :, 1] = _row_max_normalize(covisit[rows, safe])
    if content is not None:
        sims = content[rows, safe]
        feats[:, :, 2] = np.where(np.isfinite(sims), sims, 0.0).clip(0.0, 1.0)
    log_pop = np.log1p(popularity_counts)
    denom = float(log_pop.max()) or 1.0
    feats[:, :, 3] = log_pop[safe] / denom
    feats[:, :, 4] = affinity[rows, categories[safe]]
    feats[candidates == PAD] = 0.0
    return feats


def rank(
    candidates: npt.NDArray[np.int64], feats: FloatArray, weights: RankerWeights
) -> tuple[npt.NDArray[np.int64], FloatArray, npt.NDArray[np.int64]]:
    """Order candidates by weighted score (ties: lower item index).

    Returns ``(ordered_items, ordered_scores, order)`` where ``order`` indexes the
    candidate axis, so features can be re-aligned with ``take_along_axis``.
    """
    scores = feats @ weights.vector()
    scores = np.where(candidates == PAD, -np.inf, scores).astype(np.float32)
    keys = np.where(candidates == PAD, np.iinfo(np.int64).max, candidates)
    order = np.lexsort((keys, -scores), axis=-1)
    return (
        np.take_along_axis(candidates, order, axis=1),
        np.take_along_axis(scores, order, axis=1),
        order,
    )


def reason_tags(
    feature_row: FloatArray, weights: RankerWeights, *, min_share: float = 0.2
) -> list[str]:
    """Tags for one item: features contributing at least ``min_share`` of its score,
    largest contribution first; at least one tag is always returned."""
    contrib = feature_row * weights.vector()
    total = float(contrib.sum())
    order = np.lexsort((np.arange(len(FEATURES)), -contrib))
    if total <= 0:
        return [TAGS[FEATURES[int(order[0])]]]
    tags = [TAGS[FEATURES[int(i)]] for i in order if contrib[int(i)] >= min_share * total]
    return tags or [TAGS[FEATURES[int(order[0])]]]
