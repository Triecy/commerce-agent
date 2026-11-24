"""FR-D1/FR-D2: pipeline artifacts are byte-stable and row counts are enforced."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from commerce_agent.data.pipeline import (
    DataCheckError,
    check_counts,
    review_stats,
    write_split,
)
from commerce_agent.data.sources import VIDEO_GAMES
from commerce_agent.data.split import Interaction, leave_last_out

ROWS = [Interaction(f"u{u}", f"i{i}", 1000 * u + i, 5.0) for u in range(4) for i in range(4)]


def test_FR_D2_split_files_are_byte_stable(tmp_path: Path) -> None:
    split = leave_last_out(ROWS)
    first = write_split(split, tmp_path / "a")
    second = write_split(split, tmp_path / "b")
    assert first == second
    assert set(first) == {"train.csv.gz", "valid.csv.gz", "test.csv.gz"}
    with gzip.open(tmp_path / "a" / "test.csv.gz", "rt") as f:
        lines = f.read().splitlines()
    assert lines[0] == "user_id,item_id,ts_ms,rating"
    assert len(lines) == 1 + 4


def test_FR_D1_check_counts_matches_data_card() -> None:
    good = {
        "users": VIDEO_GAMES.expected_users,
        "items": VIDEO_GAMES.expected_items,
        "interactions": VIDEO_GAMES.expected_interactions,
        "inventory": VIDEO_GAMES.expected_items,
    }
    check_counts(VIDEO_GAMES, good)
    with pytest.raises(DataCheckError, match="interactions"):
        check_counts(VIDEO_GAMES, {**good, "interactions": 1})


def test_review_stats_counts_only_core_items(tmp_path: Path) -> None:
    path = tmp_path / "reviews.jsonl.gz"
    reviews = [
        {"parent_asin": "i0", "user_id": "u0", "text": "great"},
        {"parent_asin": "i0", "user_id": "other", "text": ""},
        {"parent_asin": "not-core", "user_id": "u0", "text": "x"},
    ]
    with gzip.open(path, "wt") as f:
        f.write("\n".join(json.dumps(r) for r in reviews))
    stats = review_stats(path, [Interaction("u0", "i0", 1, 5.0), Interaction("u1", "i1", 2, 4.0)])
    assert stats["reviews_for_5core_items"] == 2
    assert stats["reviews_per_item"]["min"] == 0.0  # i1 has no reviews in the file
    assert stats["reviews_matching_5core_interactions"] == 1
    assert stats["empty_text_share"] == 0.5
