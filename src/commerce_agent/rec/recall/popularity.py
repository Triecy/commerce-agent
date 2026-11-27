"""Global popularity recall (FR-R1): the same ranked list for everyone."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from commerce_agent.rec.data import FloatArray, Histories, IntArray, item_counts


@dataclass(frozen=True, slots=True)
class PopularityRecall:
    """Scores every item by ``log1p(interaction count)`` in the fitting histories."""

    counts: FloatArray
    name: str = "popularity"

    @classmethod
    def fit(cls, hist: Histories, n_items: int) -> PopularityRecall:
        return cls(counts=item_counts(hist, n_items))

    def scores(self, hist: Histories, rows: IntArray) -> FloatArray:
        del hist  # not personalized
        base = np.log1p(self.counts).astype(np.float32)
        return np.tile(base, (len(rows), 1))
