"""Map Amazon Reviews 2023 metadata and ratings to the Canonical Schema (FR-D1).

Leakage rule: fields that aggregate over *all* reviews (``average_rating``,
``rating_number``, ``Best Sellers Rank``, ``Customer Reviews``) are dropped, because
they include information from the evaluation period (SPEC §5.3, ADR-0009).
"""

from __future__ import annotations

import gzip
import json
import math
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from commerce_agent.data.split import Interaction

# Snapshot aggregates (leak future information) and boilerplate text.
DROPPED_DETAIL_KEYS = frozenset({"Best Sellers Rank", "Customer Reviews", "Pricing"})


@dataclass(frozen=True, slots=True)
class ItemRow:
    item_id: str
    source: str
    title: str
    description: str
    features: dict[str, Any] = field(hash=False)
    category_path: tuple[str, ...]
    price: Decimal | None
    brand: str | None
    image_url: str | None


def parse_price(value: object) -> Decimal | None:
    """Float or numeric string -> Decimal with 2 places; anything else -> None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.replace("$", "").replace(",", "").strip())
        except ValueError:
            return None
    else:
        return None
    if not math.isfinite(number) or number < 0:
        return None
    try:
        return Decimal(f"{number:.2f}")
    except InvalidOperation:
        return None


def _clean_text(parts: object) -> list[str]:
    if not isinstance(parts, list):
        return []
    return [p.strip() for p in parts if isinstance(p, str) and p.strip()]


def _first_image(images: object) -> str | None:
    if not isinstance(images, list):
        return None
    for image in images:
        if isinstance(image, Mapping):
            for key in ("large", "hi_res", "thumb"):
                url = image.get(key)
                if isinstance(url, str) and url.startswith("https://"):
                    return url
    return None


def parse_item(meta: Mapping[str, Any], *, source: str) -> ItemRow:
    details_raw = meta.get("details")
    details = (
        {k: v for k, v in details_raw.items() if k not in DROPPED_DETAIL_KEYS}
        if isinstance(details_raw, Mapping)
        else {}
    )
    brand = details.get("Brand") or meta.get("store")
    features: dict[str, Any] = {"bullets": _clean_text(meta.get("features")), "details": details}
    if isinstance(meta.get("main_category"), str):
        features["main_category"] = meta["main_category"]
    return ItemRow(
        item_id=str(meta["parent_asin"]),
        source=source,
        title=(meta.get("title") or "").strip(),
        description="\n".join(_clean_text(meta.get("description"))),
        features=features,
        category_path=tuple(_clean_text(meta.get("categories"))),
        price=parse_price(meta.get("price")),
        brand=brand.strip() if isinstance(brand, str) and brand.strip() else None,
        image_url=_first_image(meta.get("images")),
    )


def read_items(meta_path: Path, item_ids: set[str], *, source: str) -> list[ItemRow]:
    """Parse metadata for exactly ``item_ids``; sorted by item_id. Missing items raise."""
    items: dict[str, ItemRow] = {}
    with gzip.open(meta_path, "rt", encoding="utf-8") as f:
        for line in f:
            meta = json.loads(line)
            if meta.get("parent_asin") in item_ids and meta["parent_asin"] not in items:
                items[meta["parent_asin"]] = parse_item(meta, source=source)
    missing = item_ids - items.keys()
    if missing:
        raise ValueError(f"{len(missing)} interaction items have no metadata, e.g. {min(missing)}")
    return [items[k] for k in sorted(items)]


def to_utc(ts_ms: int) -> datetime:
    return datetime.fromtimestamp(ts_ms / 1000, UTC)


def interaction_records(
    rows: Iterable[Interaction],
) -> Iterator[tuple[str, str, datetime, str, float]]:
    """Rows for the ``interactions`` table: every review is a positive interaction,
    with the star rating kept in ``value`` (owner decision, P1)."""
    for x in rows:
        yield (x.user_id, x.item_id, to_utc(x.ts_ms), "review", x.rating)
