"""Deterministic top-k over score matrices (FR-R1: same input, same output).

Order: higher score first; equal scores -> lower item index first (= lower item_id).
Items with score ``-inf`` are never returned; short rows are padded with ``-1``.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

PAD = -1


def topk(scores: npt.NDArray[np.floating], k: int) -> npt.NDArray[np.int64]:
    """Row-wise top-``k`` item indices of a ``(B, n_items)`` score matrix."""
    if scores.ndim != 2:
        raise ValueError("scores must be 2-D")
    n_rows, n_items = scores.shape
    out = np.full((n_rows, k), PAD, dtype=np.int64)
    if n_items == 0 or k <= 0:
        return out
    kk = min(k, n_items)
    # argpartition finds the k-th largest value; every item tied with it is then
    # considered, and the final order is resolved by (score desc, index asc).
    part = np.argpartition(-scores, kk - 1, axis=1)[:, :kk]
    thresholds = np.take_along_axis(scores, part, axis=1).min(axis=1)
    for r in range(n_rows):
        row = scores[r]
        thr = thresholds[r]
        cand = np.flatnonzero((row >= thr) & (row > -np.inf))
        order = np.lexsort((cand, -row[cand]))[:kk]
        chosen = cand[order]
        out[r, : len(chosen)] = chosen
    return out


def ranks_from_topk(top: npt.NDArray[np.int64], n_items: int) -> npt.NDArray[np.float32]:
    """Dense ``(B, n_items)`` matrix of 1-based ranks; ``inf`` for items not in ``top``."""
    ranks = np.full((top.shape[0], n_items), np.inf, dtype=np.float32)
    rows, cols = np.nonzero(top != PAD)
    ranks[rows, top[rows, cols]] = cols + 1
    return ranks
