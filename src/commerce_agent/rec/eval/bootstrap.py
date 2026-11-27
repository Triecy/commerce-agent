"""Bootstrap confidence intervals over users (FR-R5).

Percentile bootstrap of the mean: resample users with replacement ``n_boot`` times
with a fixed seed. Paired comparisons bootstrap the per-user difference, which is
tighter and more honest than comparing two separate intervals.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt


@dataclass(frozen=True, slots=True)
class Interval:
    mean: float
    lo: float
    hi: float

    def as_dict(self) -> dict[str, float]:
        return {"mean": self.mean, "ci_low": self.lo, "ci_high": self.hi}


def bootstrap_mean(
    values: npt.NDArray[np.float64],
    *,
    n_boot: int = 1000,
    seed: int = 0,
    alpha: float = 0.05,
    chunk: int = 50,
) -> Interval:
    values = np.asarray(values, dtype=np.float64)
    n = len(values)
    if n == 0:
        raise ValueError("cannot bootstrap an empty sample")
    rng = np.random.default_rng(seed)
    means = np.empty(n_boot, dtype=np.float64)
    for start in range(0, n_boot, chunk):
        size = min(chunk, n_boot - start)
        idx = rng.integers(0, n, size=(size, n))
        means[start : start + size] = values[idx].mean(axis=1)
    lo, hi = np.quantile(means, [alpha / 2, 1 - alpha / 2])
    return Interval(float(values.mean()), float(lo), float(hi))


def paired_difference(
    a: npt.NDArray[np.float64],
    b: npt.NDArray[np.float64],
    *,
    n_boot: int = 1000,
    seed: int = 0,
    alpha: float = 0.05,
) -> Interval:
    """CI of ``mean(a - b)`` over the same users."""
    if a.shape != b.shape:
        raise ValueError("paired samples must have the same shape")
    return bootstrap_mean(a - b, n_boot=n_boot, seed=seed, alpha=alpha)
