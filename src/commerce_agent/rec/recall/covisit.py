"""Item-item co-visitation recall (FR-R1).

Two items co-occur when the same user interacted with both within ``window`` positions
of their chronological sequence. The symmetric count matrix is optionally normalized
(``cosine``: ``c_ij / sqrt(n_i * n_j)``, which damps popular items) and pruned to the
top ``neighbors`` entries per item. A user's score for item ``j`` is the recency-weighted
sum of ``C[h, j]`` over the history items ``h``. Items with no co-visitation evidence
get ``-inf`` (they are not candidates of this route).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from scipy import sparse

from commerce_agent.rec.data import FloatArray, Histories, IntArray, history_matrix


@dataclass(frozen=True, slots=True)
class CovisitConfig:
    window: int = 5
    normalize: Literal["none", "cosine"] = "cosine"
    neighbors: int = 200
    history_len: int = 20
    decay: float = 1.0

    def __post_init__(self) -> None:
        if self.window < 1 or self.neighbors < 1 or self.history_len < 1:
            raise ValueError("window, neighbors and history_len must be >= 1")
        if not 0.0 < self.decay <= 1.0:
            raise ValueError("decay must be in (0, 1]")


def build_covisit_matrix(hist: Histories, n_items: int, cfg: CovisitConfig) -> sparse.csr_matrix:
    user_of = np.repeat(np.arange(hist.n_users), np.diff(hist.indptr))
    items = hist.items
    src: list[np.ndarray] = []
    dst: list[np.ndarray] = []
    for d in range(1, cfg.window + 1):
        if d >= len(items):
            break
        same = user_of[:-d] == user_of[d:]
        a, b = items[:-d][same], items[d:][same]
        keep = a != b
        src.extend((a[keep], b[keep]))
        dst.extend((b[keep], a[keep]))
    if src:
        rows = np.concatenate(src)
        cols = np.concatenate(dst)
    else:
        rows = cols = np.zeros(0, dtype=np.int64)
    counts = sparse.coo_matrix(
        (np.ones(len(rows), dtype=np.float32), (rows, cols)), shape=(n_items, n_items)
    ).tocsr()
    counts.sum_duplicates()
    if cfg.normalize == "cosine":
        n = np.bincount(items, minlength=n_items).astype(np.float64)
        coo = counts.tocoo()
        denom = np.sqrt(n[coo.row] * n[coo.col])
        coo.data = (coo.data / denom).astype(np.float32)
        counts = coo.tocsr()
    return _prune_rows(counts, cfg.neighbors)


def _prune_rows(matrix: sparse.csr_matrix, keep: int) -> sparse.csr_matrix:
    """Keep the ``keep`` largest entries per row (ties: lower column first)."""
    indptr = [0]
    indices: list[np.ndarray] = []
    data: list[np.ndarray] = []
    for r in range(matrix.shape[0]):
        start, end = matrix.indptr[r], matrix.indptr[r + 1]
        cols = matrix.indices[start:end]
        vals = matrix.data[start:end]
        if len(cols) > keep:
            order = np.lexsort((cols, -vals))[:keep]
            cols, vals = cols[order], vals[order]
        order = np.argsort(cols, kind="stable")
        indices.append(cols[order])
        data.append(vals[order])
        indptr.append(indptr[-1] + len(cols))
    return sparse.csr_matrix(
        (
            np.concatenate(data) if data else np.zeros(0, np.float32),
            np.concatenate(indices) if indices else np.zeros(0, np.int32),
            np.array(indptr),
        ),
        shape=matrix.shape,
    )


@dataclass(frozen=True, slots=True)
class CovisitRecall:
    matrix: sparse.csr_matrix
    config: CovisitConfig
    name: str = "covisit"

    @classmethod
    def fit(cls, hist: Histories, n_items: int, config: CovisitConfig) -> CovisitRecall:
        return cls(matrix=build_covisit_matrix(hist, n_items, config), config=config)

    def scores(self, hist: Histories, rows: IntArray) -> FloatArray:
        h = history_matrix(
            hist,
            rows,
            self.matrix.shape[0],
            max_len=self.config.history_len,
            decay=self.config.decay,
        )
        dense = np.asarray((h @ self.matrix).toarray(), dtype=np.float32)
        dense[dense <= 0] = -np.inf
        return dense
