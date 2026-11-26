"""Simulated inventory: long-tail stock correlated with popularity (FR-D3).

**SIMULATED DATA.** Amazon Reviews has no stock information; these numbers exist only
to exercise the inventory paths (FR-I*) and must be labeled as simulated everywhere.

Model (all draws from one ``random.Random(seed)``, items processed in sorted order,
so the same seed and input always give identical output):

- Base stock grows with popularity: ``base = min_stock + scale * pop_share ** alpha``,
  where ``pop_share`` is the item's share of the most popular item's count.
- Lognormal noise multiplies the base, giving a long right tail.
- A fixed fraction of items start out of stock (``available = 0``).
- Every item gets a restock rule: a period in days and a restock quantity
  proportional to its base stock. Popular items restock more often.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class InventoryConfig:
    seed: int = 20261122
    min_stock: int = 0
    scale: float = 500.0
    alpha: float = 0.5
    noise_sigma: float = 0.6
    out_of_stock_rate: float = 0.05
    restock_days_popular: int = 3
    restock_days_tail: int = 30
    restock_fraction: float = 0.5

    def __post_init__(self) -> None:
        if not 0.0 <= self.out_of_stock_rate <= 1.0:
            raise ValueError("out_of_stock_rate must be in [0, 1]")
        if self.min_stock < 0 or self.scale < 0 or self.noise_sigma < 0:
            raise ValueError("min_stock, scale and noise_sigma must be >= 0")
        if not 1 <= self.restock_days_popular <= self.restock_days_tail:
            raise ValueError("need 1 <= restock_days_popular <= restock_days_tail")


@dataclass(frozen=True, slots=True)
class SimulatedStock:
    item_id: str
    available: int
    restock_every_days: int
    restock_qty: int


def simulate_inventory(
    popularity: Mapping[str, int], config: InventoryConfig | None = None
) -> list[SimulatedStock]:
    """Return one simulated stock record per item, sorted by ``item_id``."""
    cfg = config or InventoryConfig()
    if not popularity:
        return []
    if any(count < 0 for count in popularity.values()):
        raise ValueError("popularity counts must be >= 0")
    rng = random.Random(cfg.seed)  # noqa: S311 (simulation, not security)
    top = max(popularity.values()) or 1
    span = cfg.restock_days_tail - cfg.restock_days_popular

    out: list[SimulatedStock] = []
    for item_id in sorted(popularity):
        share = popularity[item_id] / top
        base = cfg.min_stock + cfg.scale * share**cfg.alpha
        noisy = base * math.exp(rng.gauss(0.0, cfg.noise_sigma))
        out_of_stock = rng.random() < cfg.out_of_stock_rate
        available = 0 if out_of_stock else max(cfg.min_stock, round(noisy))
        restock_days = cfg.restock_days_tail - round(span * share)
        restock_qty = max(1, round(base * cfg.restock_fraction))
        out.append(SimulatedStock(item_id, available, restock_days, restock_qty))
    return out
