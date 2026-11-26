"""Category profiling statistics (ADR-0002 evidence)."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

from commerce_agent.data.profile import interaction_stats, read_ratings_csv, text_stats
from commerce_agent.data.split import Interaction


def test_read_ratings_csv(tmp_path: Path) -> None:
    p = tmp_path / "r.csv.gz"
    with gzip.open(p, "wt") as f:
        f.write("user_id,parent_asin,rating,timestamp\nU1,A1,4.0,1611459666223\n")
    assert list(read_ratings_csv(p)) == [Interaction("U1", "A1", 1611459666223, 4.0)]


def test_interaction_stats() -> None:
    rows = [
        Interaction("u1", "a", 0, 5.0),
        Interaction("u1", "b", 0, 1.0),
        Interaction("u2", "a", 0, 4.0),
    ]
    s = interaction_stats(rows)
    assert (s.users, s.items, s.interactions) == (2, 2, 3)
    assert s.positive_share == round(2 / 3, 4)
    assert s.first_date == s.last_date == "1970-01-01"


def test_text_stats_only_counts_core_items(tmp_path: Path) -> None:
    p = tmp_path / "m.jsonl.gz"
    lines = [
        {
            "parent_asin": "a",
            "title": "T",
            "description": ["d"],
            "features": [],
            "price": 9.9,
            "categories": ["Video Games", "PC"],
        },
        {"parent_asin": "b", "title": "T", "description": [], "features": ["f"], "price": None},
        {"parent_asin": "zzz", "title": "not in core"},
    ]
    with gzip.open(p, "wt") as f:
        f.write("\n".join(json.dumps(x) for x in lines))
    s = text_stats(p, {"a", "b"})
    assert s.items_matched == 2
    assert (s.has_description, s.has_features, s.has_price) == (0.5, 0.5, 0.5)
    assert s.distinct_top2_categories == 1
