"""Small synthetic catalog and interaction log for recommendation tests."""

from __future__ import annotations

import random

import numpy as np

from commerce_agent.common.embedding import HashingEncoder
from commerce_agent.data.canonicalize import ItemRow
from commerce_agent.data.split import Interaction, Split, leave_last_out
from commerce_agent.rec.data import Catalog
from commerce_agent.rec.recall.embedding import item_text

CLUSTERS = ("racing", "puzzle", "shooter")


def make_items(n: int = 30) -> list[ItemRow]:
    items = []
    for i in range(n):
        cluster = CLUSTERS[i % len(CLUSTERS)]
        items.append(
            ItemRow(
                item_id=f"I{i:03d}",
                source="test",
                title=f"{cluster} game {i}",
                description=f"A {cluster} title with {cluster} levels",
                features={"bullets": [f"{cluster} mode"], "details": {"Platform": "PC"}},
                category_path=("Video Games", cluster.capitalize(), "Games"),
                price=None,
                brand=None,
                image_url=None,
            )
        )
    return items


def make_interactions(n_users: int = 60, seed: int = 7) -> list[Interaction]:
    """Each user mostly interacts with one cluster, in a stable item order."""
    rng = random.Random(seed)
    items = make_items()
    rows = []
    for u in range(n_users):
        cluster = u % len(CLUSTERS)
        pool = [it.item_id for k, it in enumerate(items) if k % len(CLUSTERS) == cluster]
        length = rng.randint(4, 8)
        start = rng.randrange(len(pool))
        seq = [pool[(start + j) % len(pool)] for j in range(length)]
        if rng.random() < 0.3:
            seq.append(items[rng.randrange(len(items))].item_id)
        seen: set[str] = set()
        for t, item in enumerate(seq):
            if item in seen:
                continue
            seen.add(item)
            rating = 5.0 if rng.random() < 0.8 else 2.0
            rows.append(Interaction(f"U{u:03d}", item, 1_000_000 + 1000 * t + u, rating))
    return rows


def make_split() -> Split:
    return leave_last_out(make_interactions())


def make_catalog(stock: dict[str, int] | None = None) -> Catalog:
    return Catalog.build(make_items(), stock)


def make_vectors() -> np.ndarray:
    return HashingEncoder(dim_=32).encode([item_text(it) for it in make_items()])
