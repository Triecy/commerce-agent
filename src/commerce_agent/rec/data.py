"""In-memory views of the P1 dataset for recommendation (FR-R1..R5).

Items are indexed ``0..n_items-1`` in sorted ``item_id`` order, so "lower index wins"
is the same as "lower item_id wins" in every tie-break (CLAUDE.md §7.4).
"""

from __future__ import annotations

import csv
import gzip
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt
from scipy import sparse

from commerce_agent.data.canonicalize import ItemRow
from commerce_agent.data.split import Interaction

IntArray = npt.NDArray[np.int64]
FloatArray = npt.NDArray[np.float32]

UNKNOWN_CATEGORY = "(none)"


def category_key(path: Sequence[str], main_category: str | None = None) -> str:
    """Coarse item category: levels 2-3 of the category path (level 1 is the store root)."""
    if len(path) >= 2:
        return " > ".join(path[1:3])
    if path:
        return path[0]
    return main_category or UNKNOWN_CATEGORY


@dataclass(frozen=True, slots=True)
class Catalog:
    item_ids: tuple[str, ...]
    category_paths: tuple[tuple[str, ...], ...]
    categories: IntArray  # category code per item
    category_names: tuple[str, ...]
    available: IntArray  # simulated stock per item (FR-D3); -1 when unknown

    @property
    def n_items(self) -> int:
        return len(self.item_ids)

    def index(self) -> dict[str, int]:
        return {item_id: i for i, item_id in enumerate(self.item_ids)}

    @classmethod
    def build(
        cls,
        items: Sequence[ItemRow],
        stock: Mapping[str, int] | None = None,
    ) -> Catalog:
        ordered = sorted(items, key=lambda it: it.item_id)
        keys = [category_key(it.category_path, it.features.get("main_category")) for it in ordered]
        names = tuple(sorted(set(keys)))
        code = {name: i for i, name in enumerate(names)}
        stock = stock or {}
        return cls(
            item_ids=tuple(it.item_id for it in ordered),
            category_paths=tuple(tuple(it.category_path) for it in ordered),
            categories=np.array([code[k] for k in keys], dtype=np.int64),
            category_names=names,
            available=np.array([stock.get(it.item_id, -1) for it in ordered], dtype=np.int64),
        )


@dataclass(frozen=True, slots=True)
class Histories:
    """Per-user chronological item sequences in CSR form (ties ordered by item index)."""

    user_ids: tuple[str, ...]
    indptr: IntArray
    items: IntArray
    ratings: FloatArray

    @property
    def n_users(self) -> int:
        return len(self.user_ids)

    def of(self, row: int) -> IntArray:
        return self.items[self.indptr[row] : self.indptr[row + 1]]

    @classmethod
    def build(
        cls,
        interactions: Iterable[Interaction],
        item_index: Mapping[str, int],
        user_ids: Sequence[str] | None = None,
    ) -> Histories:
        """Group by user. ``user_ids`` fixes the row order (users without rows get none)."""
        by_user: dict[str, list[tuple[int, int, float]]] = {}
        for x in interactions:
            by_user.setdefault(x.user_id, []).append((x.ts_ms, item_index[x.item_id], x.rating))
        users = tuple(user_ids) if user_ids is not None else tuple(sorted(by_user))
        indptr = [0]
        items: list[int] = []
        ratings: list[float] = []
        for user in users:
            seq = sorted(by_user.get(user, ()))
            items.extend(i for _, i, _ in seq)
            ratings.extend(r for _, _, r in seq)
            indptr.append(len(items))
        return cls(
            user_ids=users,
            indptr=np.array(indptr, dtype=np.int64),
            items=np.array(items, dtype=np.int64),
            ratings=np.array(ratings, dtype=np.float32),
        )

    def subset(self, rows: IntArray) -> Histories:
        parts = [self.of(int(r)) for r in rows]
        rparts = [self.ratings[self.indptr[r] : self.indptr[r + 1]] for r in rows]
        lengths = np.array([len(p) for p in parts], dtype=np.int64)
        return Histories(
            user_ids=tuple(self.user_ids[int(r)] for r in rows),
            indptr=np.concatenate([[0], np.cumsum(lengths)]).astype(np.int64),
            items=np.concatenate(parts).astype(np.int64) if parts else np.zeros(0, np.int64),
            ratings=np.concatenate(rparts).astype(np.float32)
            if rparts
            else np.zeros(0, np.float32),
        )


def history_matrix(
    hist: Histories,
    rows: IntArray,
    n_items: int,
    *,
    max_len: int | None = None,
    decay: float = 1.0,
) -> sparse.csr_matrix:
    """Recency-weighted history rows: weight ``decay ** p`` for the item ``p`` steps from the
    end; only the last ``max_len`` items. Weights are L1-normalized per row."""
    data: list[float] = []
    cols: list[int] = []
    indptr = [0]
    for r in rows:
        seq = hist.of(int(r))
        if max_len is not None:
            seq = seq[-max_len:]
        if len(seq):
            weights = decay ** np.arange(len(seq) - 1, -1, -1, dtype=np.float64)
            weights /= weights.sum()
            cols.extend(seq.tolist())
            data.extend(weights.tolist())
        indptr.append(len(cols))
    matrix = sparse.csr_matrix(
        (np.array(data, dtype=np.float32), np.array(cols, dtype=np.int64), np.array(indptr)),
        shape=(len(rows), n_items),
    )
    matrix.sum_duplicates()
    return matrix


def seen_mask(hist: Histories, rows: IntArray, n_items: int) -> npt.NDArray[np.bool_]:
    """Dense boolean matrix: True where the user already interacted with the item."""
    mask = np.zeros((len(rows), n_items), dtype=bool)
    for b, r in enumerate(rows):
        mask[b, hist.of(int(r))] = True
    return mask


def read_split_csv(path: Path) -> list[Interaction]:
    """Read one ``data/processed/<category>/{train,valid,test}.csv.gz`` file (P1 format)."""
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return [
            Interaction(row["user_id"], row["item_id"], int(row["ts_ms"]), float(row["rating"]))
            for row in reader
        ]


def read_stock_csv(path: Path) -> dict[str, int]:
    """Simulated stock (FR-D3) from ``inventory_simulated.csv.gz``: item_id -> available."""
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        return {row["item_id"]: int(row["available"]) for row in csv.DictReader(f)}


def item_counts(hist: Histories, n_items: int) -> FloatArray:
    return np.bincount(hist.items, minlength=n_items).astype(np.float32)
