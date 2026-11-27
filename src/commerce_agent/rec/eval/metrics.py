"""Full-ranking offline metrics (FR-R5, ADR-0009).

Every list is ranked over the **whole catalog** (minus the user's seen items); no
sampled negatives. Each evaluated user has exactly one held-out item (leave-last-out),
so ``Recall@K`` and ``HitRate@K`` coincide; both are reported because SPEC names both.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from commerce_agent.rec.topk import PAD

IntMatrix = npt.NDArray[np.int64]
FloatVector = npt.NDArray[np.float64]


def target_rank(recs: IntMatrix, targets: npt.NDArray[np.int64]) -> npt.NDArray[np.int64]:
    """1-based rank of each user's target in its list, 0 when absent."""
    hits = recs == targets[:, None]
    found = hits.any(axis=1)
    return np.where(found, hits.argmax(axis=1) + 1, 0).astype(np.int64)


def recall_at(ranks: npt.NDArray[np.int64], k: int) -> FloatVector:
    return ((ranks >= 1) & (ranks <= k)).astype(np.float64)


def ndcg_at(ranks: npt.NDArray[np.int64], k: int) -> FloatVector:
    hit = (ranks >= 1) & (ranks <= k)
    out = np.zeros(len(ranks), dtype=np.float64)
    out[hit] = 1.0 / np.log2(ranks[hit] + 1.0)
    return out


def coverage(recs: IntMatrix, n_items: int, k: int) -> float:
    """Share of the catalog that appears in at least one top-``k`` list."""
    top = recs[:, :k]
    return float(len(np.unique(top[top != PAD]))) / n_items


def intra_list_diversity(recs: IntMatrix, vectors: npt.NDArray[np.float32], k: int) -> FloatVector:
    """Per user: mean pairwise ``1 - cosine`` between the top-``k`` items' embeddings."""
    top = recs[:, :k]
    valid = top != PAD
    vecs = vectors[np.where(valid, top, 0)] * valid[:, :, None]
    gram = np.einsum("bnd,bmd->bnm", vecs, vecs)
    n = valid.sum(axis=1)
    pairs = n * (n - 1)
    off_diag_sum = gram.sum(axis=(1, 2)) - np.einsum("bnn->b", gram)
    out = np.zeros(len(top), dtype=np.float64)
    ok = pairs > 0
    out[ok] = 1.0 - off_diag_sum[ok] / pairs[ok]
    return out


def category_diversity(recs: IntMatrix, categories: npt.NDArray[np.int64], k: int) -> FloatVector:
    """Per user: distinct categories in the top-``k`` list divided by its length."""
    top = recs[:, :k]
    out = np.zeros(len(top), dtype=np.float64)
    for b, row in enumerate(top):
        row = row[row != PAD]
        if len(row):
            out[b] = len(np.unique(categories[row])) / len(row)
    return out
