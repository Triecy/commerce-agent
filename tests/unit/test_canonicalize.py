"""FR-D1: metadata and ratings map to the Canonical Schema without leaking aggregates."""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from commerce_agent.data.canonicalize import (
    interaction_records,
    parse_item,
    parse_price,
    read_items,
)
from commerce_agent.data.split import Interaction

META = {
    "parent_asin": "B01",
    "title": "  Game X - PlayStation 4 ",
    "description": ["First.", "  ", "Second."],
    "features": ["Online play", ""],
    "categories": ["Video Games", "PlayStation 4", "Games"],
    "price": 19.991,
    "store": "Studio",
    "main_category": "Video Games",
    "average_rating": 4.4,
    "rating_number": 1200,
    "images": [{"thumb": "http://insecure", "large": "https://img/large.jpg"}],
    "details": {
        "Hardware Platform": "PlayStation 4",
        "Best Sellers Rank": {"Video Games": 120},
        "Customer Reviews": "4.4 out of 5",
        "Pricing": "The strikethrough price is the List Price.",
    },
}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (19.991, Decimal("19.99")),
        (0, Decimal("0.00")),
        ("$1,299.5", Decimal("1299.50")),
        ("from 12.99", None),
        (None, None),
        (True, None),
        (-1.0, None),
        (float("nan"), None),
        ([], None),
    ],
)
def test_FR_D1_parse_price(raw: object, expected: Decimal | None) -> None:
    assert parse_price(raw) == expected


def test_FR_D1_parse_item_maps_fields() -> None:
    item = parse_item(META, source="amazon2023/Video_Games")
    assert item.item_id == "B01"
    assert item.title == "Game X - PlayStation 4"
    assert item.description == "First.\nSecond."
    assert item.category_path == ("Video Games", "PlayStation 4", "Games")
    assert item.price == Decimal("19.99")
    assert item.brand == "Studio"
    assert item.image_url == "https://img/large.jpg"
    assert item.features["bullets"] == ["Online play"]
    assert item.features["main_category"] == "Video Games"


def test_FR_D1_parse_item_drops_leaky_aggregates() -> None:
    item = parse_item(META, source="s")
    flat = json.dumps(item.features)
    assert "average_rating" not in flat and "rating_number" not in flat
    assert item.features["details"] == {"Hardware Platform": "PlayStation 4"}


def test_FR_D1_brand_prefers_details_and_handles_missing() -> None:
    assert parse_item({**META, "details": {"Brand": "Sony"}}, source="s").brand == "Sony"
    bare = parse_item({"parent_asin": "B02"}, source="s")
    assert (bare.title, bare.brand, bare.price, bare.image_url) == ("", None, None, None)
    assert bare.features == {"bullets": [], "details": {}}


def test_FR_D1_read_items_selects_and_requires_all(tmp_path: Path) -> None:
    path = tmp_path / "meta.jsonl.gz"
    with gzip.open(path, "wt") as f:
        for asin in ("B03", "B01", "B99"):
            f.write(json.dumps({**META, "parent_asin": asin}) + "\n")
    assert [i.item_id for i in read_items(path, {"B01", "B03"}, source="s")] == ["B01", "B03"]
    with pytest.raises(ValueError, match="no metadata"):
        read_items(path, {"B01", "MISSING"}, source="s")


def test_FR_D1_every_review_is_a_positive_interaction_with_rating_value() -> None:
    rows = [Interaction("u", "i", 1_600_000_000_000, 2.0)]
    assert list(interaction_records(rows)) == [
        ("u", "i", datetime(2020, 9, 13, 12, 26, 40, tzinfo=UTC), "review", 2.0)
    ]
