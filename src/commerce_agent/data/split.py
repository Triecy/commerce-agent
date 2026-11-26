"""Deduplication, k-core filtering and leave-last-out temporal split (FR-D2, SPEC §5.3).

All functions are pure and deterministic: equal timestamps are ordered by
``item_id``, never randomly (CLAUDE.md §7.4).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True, order=True)
class Interaction:
    """One implicit-feedback event. ``ts_ms`` is Unix time in milliseconds (UTC)."""

    user_id: str
    item_id: str
    ts_ms: int
    rating: float


@dataclass(frozen=True, slots=True)
class Split:
    train: tuple[Interaction, ...]
    valid: tuple[Interaction, ...]
    test: tuple[Interaction, ...]


def _chrono_key(x: Interaction) -> tuple[int, str]:
    return (x.ts_ms, x.item_id)


def dedupe_first(interactions: Iterable[Interaction]) -> list[Interaction]:
    """Keep only the earliest interaction per (user, item); output sorted by user then time."""
    first: dict[tuple[str, str], Interaction] = {}
    for x in interactions:
        key = (x.user_id, x.item_id)
        current = first.get(key)
        if current is None or _chrono_key(x) < _chrono_key(current):
            first[key] = x
    return sorted(first.values(), key=lambda x: (x.user_id, x.ts_ms, x.item_id))


def k_core(interactions: Sequence[Interaction], *, k_user: int, k_item: int) -> list[Interaction]:
    """Iteratively drop users with < ``k_user`` and items with < ``k_item`` interactions.

    Repeats until a fixed point, so every remaining user and item satisfies its bound.
    Input order is preserved. Expects deduplicated input (one row per user-item pair).
    """
    if k_user < 1 or k_item < 1:
        raise ValueError("k_user and k_item must be >= 1")
    current = list(interactions)
    while True:
        users = Counter(x.user_id for x in current)
        items = Counter(x.item_id for x in current)
        kept = [x for x in current if users[x.user_id] >= k_user and items[x.item_id] >= k_item]
        if len(kept) == len(current):
            return kept
        current = kept


def leave_last_out(interactions: Iterable[Interaction], *, min_history: int = 3) -> Split:
    """Per user: last interaction -> test, second-to-last -> valid, the rest -> train.

    Users with fewer than ``min_history`` interactions contribute to train only, so
    every evaluated user has at least one training interaction.
    """
    if min_history < 3:
        raise ValueError("min_history must be >= 3 (train, valid and test need one each)")
    by_user: dict[str, list[Interaction]] = defaultdict(list)
    for x in interactions:
        by_user[x.user_id].append(x)

    train: list[Interaction] = []
    valid: list[Interaction] = []
    test: list[Interaction] = []
    for user_id in sorted(by_user):
        seq = sorted(by_user[user_id], key=_chrono_key)
        if len(seq) < min_history:
            train.extend(seq)
            continue
        train.extend(seq[:-2])
        valid.append(seq[-2])
        test.append(seq[-1])
    return Split(tuple(train), tuple(valid), tuple(test))
