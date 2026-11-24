"""FR-D3: simulated inventory is deterministic, long-tailed and popularity-correlated."""

from __future__ import annotations

import statistics

import pytest

from commerce_agent.data.simulate_inventory import InventoryConfig, simulate_inventory

POP = {f"i{n:04d}": max(1, 5000 // (n + 1)) for n in range(2000)}  # Zipf-like


def test_FR_D3_same_seed_same_output() -> None:
    assert simulate_inventory(POP) == simulate_inventory(dict(reversed(list(POP.items()))))


def test_FR_D3_different_seed_different_output() -> None:
    assert simulate_inventory(POP) != simulate_inventory(POP, InventoryConfig(seed=7))


def test_FR_D3_invariants() -> None:
    stock = simulate_inventory(POP)
    assert [s.item_id for s in stock] == sorted(POP)
    assert all(s.available >= 0 and s.restock_qty >= 1 for s in stock)
    assert all(3 <= s.restock_every_days <= 30 for s in stock)


def test_FR_D3_out_of_stock_rate_close_to_config() -> None:
    stock = simulate_inventory(POP, InventoryConfig(out_of_stock_rate=0.1))
    rate = sum(s.available == 0 for s in stock) / len(stock)
    assert 0.07 < rate < 0.13


def test_FR_D3_popular_items_have_more_stock_and_restock_faster() -> None:
    stock = {s.item_id: s for s in simulate_inventory(POP, InventoryConfig(out_of_stock_rate=0))}
    head = [stock[f"i{n:04d}"] for n in range(20)]
    tail = [stock[f"i{n:04d}"] for n in range(1800, 2000)]
    assert statistics.median(s.available for s in head) > statistics.median(
        s.available for s in tail
    )
    assert max(s.restock_every_days for s in head) < min(s.restock_every_days for s in tail)


def test_FR_D3_long_tail() -> None:
    avail = sorted((s.available for s in simulate_inventory(POP)), reverse=True)
    top_decile = sum(avail[: len(avail) // 10])
    assert top_decile / sum(avail) > 0.2  # head holds well over its 10% share


def test_FR_D3_edge_cases() -> None:
    assert simulate_inventory({}) == []
    with pytest.raises(ValueError):
        simulate_inventory({"a": -1})
    with pytest.raises(ValueError):
        InventoryConfig(out_of_stock_rate=1.5)
