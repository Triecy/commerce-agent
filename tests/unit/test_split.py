"""FR-D2: deduplication, k-core and leave-last-out split without temporal leakage."""

from __future__ import annotations

import random
from collections import Counter, defaultdict

import pytest

from commerce_agent.data.split import Interaction, dedupe_first, k_core, leave_last_out


def _x(user: str, item: str, ts: int, rating: float = 5.0) -> Interaction:
    return Interaction(user, item, ts, rating)


def _random_log(seed: int, n: int = 2000) -> list[Interaction]:
    rng = random.Random(seed)
    return [
        _x(
            f"u{rng.randrange(150)}",
            f"i{rng.randrange(80)}",
            rng.randrange(1_000),
            rng.choice([1.0, 5.0]),
        )
        for _ in range(n)
    ]


def test_FR_D2_dedupe_keeps_earliest_pair() -> None:
    rows = [_x("u1", "a", 30), _x("u1", "a", 10), _x("u1", "b", 20), _x("u2", "a", 5)]
    assert dedupe_first(rows) == [_x("u1", "a", 10), _x("u1", "b", 20), _x("u2", "a", 5)]


@pytest.mark.parametrize("seed", range(5))
def test_FR_D2_k_core_reaches_fixed_point(seed: int) -> None:
    rows = k_core(dedupe_first(_random_log(seed)), k_user=5, k_item=5)
    assert rows, "fixture too sparse"
    users = Counter(x.user_id for x in rows)
    items = Counter(x.item_id for x in rows)
    assert min(users.values()) >= 5
    assert min(items.values()) >= 5


def test_FR_D2_k_core_cascades() -> None:
    # Dropping item "c" (1 interaction) leaves u3 with 1 interaction, which drops u3 too.
    rows = [_x("u1", "a", 1), _x("u1", "b", 2), _x("u2", "a", 3), _x("u2", "b", 4)]
    rows += [_x("u3", "a", 5), _x("u3", "c", 6)]
    kept = k_core(rows, k_user=2, k_item=2)
    assert {x.user_id for x in kept} == {"u1", "u2"}
    assert {x.item_id for x in kept} == {"a", "b"}


def test_FR_D2_k_core_rejects_invalid_k() -> None:
    with pytest.raises(ValueError):
        k_core([], k_user=0, k_item=5)


@pytest.mark.parametrize("seed", range(10))
def test_FR_D2_split_has_no_temporal_leakage(seed: int) -> None:
    rows = dedupe_first(_random_log(seed))
    split = leave_last_out(rows)

    train_by_user: dict[str, list[Interaction]] = defaultdict(list)
    for x in split.train:
        train_by_user[x.user_id].append(x)
    valid = {x.user_id: x for x in split.valid}
    test = {x.user_id: x for x in split.test}

    assert valid.keys() == test.keys()
    for user, t in test.items():
        v = valid[user]
        assert (v.ts_ms, v.item_id) <= (t.ts_ms, t.item_id)
        assert train_by_user[user], "evaluated user without training history"
        assert all((x.ts_ms, x.item_id) <= (v.ts_ms, v.item_id) for x in train_by_user[user])
    # Nothing lost, nothing duplicated.
    assert Counter(split.train + split.valid + split.test) == Counter(rows)


def test_FR_D2_split_short_histories_go_to_train_only() -> None:
    rows = [
        _x("u1", "a", 1),
        _x("u1", "b", 2),
        _x("u2", "a", 1),
        _x("u2", "b", 2),
        _x("u2", "c", 3),
    ]
    split = leave_last_out(rows)
    assert {x.user_id for x in split.test} == {"u2"}
    assert split.test == (_x("u2", "c", 3),)
    assert split.valid == (_x("u2", "b", 2),)
    assert sorted(split.train) == sorted([_x("u1", "a", 1), _x("u1", "b", 2), _x("u2", "a", 1)])


def test_FR_D2_split_breaks_timestamp_ties_by_item_id() -> None:
    rows = [_x("u", "z", 7), _x("u", "a", 7), _x("u", "m", 7)]
    split = leave_last_out(list(reversed(rows)))
    assert [x.item_id for x in split.train + split.valid + split.test] == ["a", "m", "z"]


def test_FR_D2_split_is_deterministic_under_input_order() -> None:
    rows = dedupe_first(_random_log(42))
    shuffled = rows[:]
    random.Random(1).shuffle(shuffled)
    assert leave_last_out(rows) == leave_last_out(shuffled)
