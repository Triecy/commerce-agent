"""Hybrid recall by weighted Reciprocal Rank Fusion (FR-R1).

``score(i) = sum_r w_r / (k + rank_r(i))`` over the enabled routes, where ``rank_r`` is
the item's 1-based rank in route ``r``'s top ``depth`` list. Items in no list get
``-inf``. Disabled routes (weight 0 or absent) are not computed at all.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np

from commerce_agent.rec.data import FloatArray
from commerce_agent.rec.topk import ranks_from_topk, topk


@dataclass(frozen=True, slots=True)
class RRFConfig:
    weights: Mapping[str, float] = field(
        default_factory=lambda: {"popularity": 1.0, "covisit": 1.0, "embedding": 1.0}
    )
    k: float = 60.0
    depth: int = 200

    def enabled(self) -> list[str]:
        return sorted(name for name, w in self.weights.items() if w > 0)


def rrf_from_ranks(ranks: Mapping[str, FloatArray], cfg: RRFConfig) -> FloatArray:
    """Fuse dense rank matrices (``inf`` = not ranked)."""
    names = [n for n in cfg.enabled() if n in ranks]
    if not names:
        raise ValueError("RRF needs at least one enabled route")
    fused = np.zeros_like(ranks[names[0]], dtype=np.float32)
    for name in names:
        fused += np.float32(cfg.weights[name]) / (np.float32(cfg.k) + ranks[name])
    fused[fused <= 0] = -np.inf
    return fused


def rrf_fuse(route_scores: Mapping[str, FloatArray], cfg: RRFConfig) -> FloatArray:
    """Fuse dense score matrices (already filtered: ``-inf`` = excluded)."""
    ranks = {
        name: ranks_from_topk(topk(route_scores[name], cfg.depth), route_scores[name].shape[1])
        for name in cfg.enabled()
        if name in route_scores
    }
    return rrf_from_ranks(ranks, cfg)
