"""Content-embedding recall (FR-R1).

Item text is built from **title, feature bullets, item details and description only**.
Review text is never used: reviews are dated, and embedding them would let test-period
information into the item vectors (SPEC §5.3, data card §8). :func:`item_text` takes an
:class:`ItemRow`, which has no review field, so reviews cannot leak in by construction.

A user vector is the recency-weighted mean of the last ``history_len`` item vectors;
every item is scored by cosine similarity (full ranking, no ``-inf`` except seen items).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from commerce_agent.data.canonicalize import ItemRow
from commerce_agent.rec.data import FloatArray, Histories, IntArray, history_matrix

MAX_TEXT_CHARS = 2000
MAX_DETAILS = 12


def item_text(item: ItemRow) -> str:
    """The text that is embedded for an item (fields allowed by FR-R1; no reviews)."""
    parts = [item.title]
    bullets = item.features.get("bullets") or []
    parts.extend(str(b) for b in bullets)
    details = item.features.get("details") or {}
    if isinstance(details, Mapping):
        for key in sorted(details)[:MAX_DETAILS]:
            value = details[key]
            if isinstance(value, str | int | float):
                parts.append(f"{key}: {value}")
    if item.description:
        parts.append(item.description)
    text = "\n".join(p.strip() for p in parts if p and p.strip())
    return text[:MAX_TEXT_CHARS]


@dataclass(frozen=True, slots=True)
class EmbeddingConfig:
    history_len: int = 20
    decay: float = 1.0

    def __post_init__(self) -> None:
        if self.history_len < 1 or not 0.0 < self.decay <= 1.0:
            raise ValueError("history_len >= 1 and decay in (0, 1] required")


@dataclass(frozen=True, slots=True)
class EmbeddingRecall:
    vectors: FloatArray  # (n_items, dim), L2-normalized
    config: EmbeddingConfig
    name: str = "embedding"

    def user_vectors(self, hist: Histories, rows: IntArray) -> FloatArray:
        h = history_matrix(
            hist,
            rows,
            self.vectors.shape[0],
            max_len=self.config.history_len,
            decay=self.config.decay,
        )
        users = np.asarray(h @ self.vectors, dtype=np.float32)
        norms = np.linalg.norm(users, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        out: FloatArray = (users / norms).astype(np.float32)
        return out

    def scores(self, hist: Histories, rows: IntArray) -> FloatArray:
        users = self.user_vectors(hist, rows)
        out = users @ self.vectors.T
        empty = np.diff(hist.indptr)[rows] == 0
        out[empty] = -np.inf  # no history, no content signal
        return out.astype(np.float32)
