"""Diversity re-ranking by Maximal Marginal Relevance (FR-R3).

Greedy: at each step pick the candidate maximizing
``lam * relevance - (1 - lam) * max cosine similarity to the items already picked``.
``lam = 1`` keeps the ranker order. Relevance is the ranker score min-max scaled per
user; ties go to the earlier candidate (which is the higher-ranked, lower-index item).
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from commerce_agent.rec.data import FloatArray
from commerce_agent.rec.topk import PAD


def mmr(
    candidates: npt.NDArray[np.int64],
    relevance: FloatArray,
    vectors: FloatArray,
    *,
    k: int,
    lam: float,
) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.int64]]:
    """Return ``(items, positions)``: the ``(B, k)`` picks and their candidate positions.

    ``candidates`` must already be in ranker order; ``PAD`` entries are never picked.
    """
    if not 0.0 <= lam <= 1.0:
        raise ValueError("lam must be in [0, 1]")
    n_rows, n_cand = candidates.shape
    k = min(k, n_cand)
    valid = candidates != PAD
    rel = np.where(valid, relevance, np.nan)
    lo = np.nanmin(np.where(valid, rel, np.inf), axis=1, keepdims=True)
    hi = np.nanmax(np.where(valid, rel, -np.inf), axis=1, keepdims=True)
    span = np.where(hi - lo > 0, hi - lo, 1.0)
    rel = np.where(valid, (relevance - lo) / span, 0.0).astype(np.float32)

    if lam == 1.0:
        positions = np.tile(np.arange(k), (n_rows, 1))
        items = candidates[:, :k].copy()
        return items, np.where(items == PAD, PAD, positions)

    vecs = vectors[np.where(valid, candidates, 0)]
    sims = np.einsum("bnd,bmd->bnm", vecs, vecs)
    max_sim = np.zeros((n_rows, n_cand), dtype=np.float32)
    picked = np.zeros((n_rows, n_cand), dtype=bool)
    positions = np.full((n_rows, k), PAD, dtype=np.int64)
    rows = np.arange(n_rows)
    for step in range(k):
        utility = lam * rel - (1.0 - lam) * max_sim
        utility = np.where(valid & ~picked, utility, -np.inf)
        best = np.argmax(utility, axis=1)
        ok = np.isfinite(utility[rows, best])
        positions[ok, step] = best[ok]
        picked[rows[ok], best[ok]] = True
        if step == 0:
            max_sim[ok] = sims[rows[ok], best[ok]]
        else:
            max_sim[ok] = np.maximum(max_sim[ok], sims[rows[ok], best[ok]])
    items = np.where(positions == PAD, PAD, np.take_along_axis(candidates, positions.clip(0), 1))
    return items, positions
