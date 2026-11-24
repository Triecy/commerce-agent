"""Category profiling for the ADR-0002 decision (P1).

Reproduces the statistics in ``docs/results/p1-category-profiling.md``::

    uv run python -m commerce_agent.data.profile --with-meta \
        --out docs/results/p1-category-profiling.json

Inputs are downloaded into ``data/raw/`` (git-ignored); every input's SHA-256 is
written into the output so the report can be traced to exact files.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import statistics
from collections import Counter
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from commerce_agent.data.download import fetch, sha256_of
from commerce_agent.data.sources import CANDIDATE_CATEGORIES, five_core_ratings, item_metadata
from commerce_agent.data.split import Interaction


def read_ratings_csv(path: Path) -> Iterator[Interaction]:
    """Read a McAuley benchmark CSV (user_id, parent_asin, rating, timestamp in ms)."""
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            yield Interaction(
                user_id=row["user_id"],
                item_id=row["parent_asin"],
                ts_ms=int(row["timestamp"]),
                rating=float(row["rating"]),
            )


@dataclass(frozen=True, slots=True)
class InteractionStats:
    users: int
    items: int
    interactions: int
    density: float
    median_user_history: float
    median_item_popularity: float
    top1pct_item_share: float
    positive_share: float
    first_date: str
    last_date: str


@dataclass(frozen=True, slots=True)
class TextStats:
    items_matched: int
    has_description: float
    has_features: float
    has_price: float
    median_text_chars: float
    distinct_top2_categories: int


def _date(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, UTC).date().isoformat()


def interaction_stats(rows: list[Interaction], *, positive_min: float = 4.0) -> InteractionStats:
    if not rows:
        raise ValueError("no interactions")
    users = Counter(x.user_id for x in rows)
    items = Counter(x.item_id for x in rows)
    n = len(rows)
    top = max(1, len(items) // 100)
    return InteractionStats(
        users=len(users),
        items=len(items),
        interactions=n,
        density=round(n / (len(users) * len(items)), 6),
        median_user_history=float(statistics.median(users.values())),
        median_item_popularity=float(statistics.median(items.values())),
        top1pct_item_share=round(sum(c for _, c in items.most_common(top)) / n, 4),
        positive_share=round(sum(x.rating >= positive_min for x in rows) / n, 4),
        first_date=_date(min(x.ts_ms for x in rows)),
        last_date=_date(max(x.ts_ms for x in rows)),
    )


def text_stats(meta_path: Path, item_ids: set[str]) -> TextStats:
    matched = desc = feat = price = 0
    lengths: list[int] = []
    top2: set[tuple[str, ...]] = set()
    with gzip.open(meta_path, "rt", encoding="utf-8") as f:
        for line in f:
            meta = json.loads(line)
            if meta.get("parent_asin") not in item_ids:
                continue
            matched += 1
            description = " ".join(meta.get("description") or [])
            features = " ".join(meta.get("features") or [])
            desc += bool(description.strip())
            feat += bool(features.strip())
            price += meta.get("price") not in (None, "", "None")
            lengths.append(len(f"{meta.get('title') or ''} {description} {features}"))
            if meta.get("categories"):
                top2.add(tuple(meta["categories"][:2]))
    if matched == 0:
        raise ValueError(f"no metadata rows matched in {meta_path}")
    return TextStats(
        items_matched=matched,
        has_description=round(desc / matched, 4),
        has_features=round(feat / matched, 4),
        has_price=round(price / matched, 4),
        median_text_chars=float(statistics.median(lengths)),
        distinct_top2_categories=len(top2),
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--with-meta", action="store_true", help="also profile item text")
    parser.add_argument("--categories", nargs="*", default=list(CANDIDATE_CATEGORIES))
    args = parser.parse_args(argv)

    report: dict[str, object] = {}
    for category in args.categories:
        ratings_path = fetch(five_core_ratings(category), args.raw_dir)
        rows = list(read_ratings_csv(ratings_path))
        inputs = {ratings_path.name: sha256_of(ratings_path)}
        entry: dict[str, object] = {"inputs": inputs, "five_core": asdict(interaction_stats(rows))}
        if args.with_meta:
            meta_path = fetch(item_metadata(category), args.raw_dir, timeout_s=120.0)
            inputs[meta_path.name] = sha256_of(meta_path)
            entry["text"] = asdict(text_stats(meta_path, {x.item_id for x in rows}))
        report[category] = entry
        print(category, json.dumps(entry["five_core"]))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
