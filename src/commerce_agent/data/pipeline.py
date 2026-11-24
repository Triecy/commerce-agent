"""``make data``: build the Video_Games dataset end to end (FR-D1..FR-D4).

Steps (each is idempotent):

1. Fetch the pinned 5-core ratings, item metadata and raw reviews (checksums verified).
2. Check the 5-core file is a k-core fixed point; leave-last-out split (FR-D2), written
   to ``data/processed/<category>/`` as gzip files with stable bytes.
3. Simulate inventory from **train-split** popularity (FR-D3), so test interactions
   never shape a simulated feature.
4. Load users, items, interactions and inventory in one transaction. Rows are staged
   with COPY and inserted with ``ON CONFLICT DO NOTHING``: a second run inserts nothing
   and never overwrites inventory that later phases have changed.
5. Verify database row counts against :data:`VIDEO_GAMES` and write the statistics used
   by ``docs/data-card.md`` to ``docs/results/p1-dataset-stats.json``.

Requires the schema: ``make data`` runs ``alembic upgrade head`` first.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import gzip
import io
import json
import logging
import statistics
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

import asyncpg

from commerce_agent.common.config import get_settings
from commerce_agent.common.logging import configure_logging
from commerce_agent.data.canonicalize import ItemRow, interaction_records, read_items
from commerce_agent.data.download import fetch, sha256_of
from commerce_agent.data.profile import read_ratings_csv
from commerce_agent.data.simulate_inventory import (
    InventoryConfig,
    SimulatedStock,
    simulate_inventory,
)
from commerce_agent.data.sources import VIDEO_GAMES, DatasetSpec
from commerce_agent.data.split import Interaction, Split, k_core, leave_last_out

logger = logging.getLogger(__name__)

SCHEMA_REVISION = "0001"


class DataCheckError(RuntimeError):
    """A built artifact or loaded table does not match the dataset spec."""


# --------------------------------------------------------------------------- files


def _write_gz_csv(path: Path, header: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    """Write a gzip CSV with stable bytes (mtime=0, no filename) and return its SHA-256."""
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    with path.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as gz:
        gz.write(buffer.getvalue().encode("utf-8"))
    return sha256_of(path)


def write_split(split: Split, out_dir: Path) -> dict[str, str]:
    header = ("user_id", "item_id", "ts_ms", "rating")
    checksums = {}
    for name, part in (("train", split.train), ("valid", split.valid), ("test", split.test)):
        path = out_dir / f"{name}.csv.gz"
        checksums[path.name] = _write_gz_csv(
            path, header, ((x.user_id, x.item_id, x.ts_ms, x.rating) for x in part)
        )
    return checksums


def write_restock_rules(stock: Sequence[SimulatedStock], out_dir: Path) -> dict[str, str]:
    path = out_dir / "inventory_simulated.csv.gz"
    rows = ((s.item_id, s.available, s.restock_every_days, s.restock_qty) for s in stock)
    header = ("item_id", "available", "restock_every_days", "restock_qty")
    return {path.name: _write_gz_csv(path, header, rows)}


# --------------------------------------------------------------------------- stats


def _quantiles(values: Sequence[int]) -> dict[str, float]:
    ordered = sorted(values)

    def q(p: float) -> float:
        return float(ordered[min(len(ordered) - 1, int(p * len(ordered)))])

    return {
        "min": float(ordered[0]),
        "median": float(statistics.median(ordered)),
        "p90": q(0.90),
        "p99": q(0.99),
        "max": float(ordered[-1]),
    }


def review_stats(reviews_path: Path, rows: Sequence[Interaction]) -> dict[str, Any]:
    """Reviews available per 5-core item: input to the P3 per-item embedding cap."""
    item_ids = {x.item_id for x in rows}
    pairs = {(x.user_id, x.item_id) for x in rows}
    per_item: Counter[str] = Counter()
    text_chars: list[int] = []
    empty_text = matched_pairs = 0
    with gzip.open(reviews_path, "rt", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            item = r.get("parent_asin")
            if item not in item_ids:
                continue
            per_item[item] += 1
            text = (r.get("text") or "").strip()
            text_chars.append(len(text))
            empty_text += not text
            matched_pairs += (r.get("user_id"), item) in pairs
    counts = [per_item.get(i, 0) for i in sorted(item_ids)]
    return {
        "reviews_for_5core_items": sum(counts),
        "reviews_per_item": _quantiles(counts),
        "review_text_chars": _quantiles(text_chars),
        "empty_text_share": round(empty_text / max(1, len(text_chars)), 4),
        "reviews_matching_5core_interactions": matched_pairs,
    }


def item_stats(items: Sequence[ItemRow]) -> dict[str, Any]:
    n = len(items)
    return {
        "items": n,
        "has_title": round(sum(bool(i.title) for i in items) / n, 4),
        "has_description": round(sum(bool(i.description) for i in items) / n, 4),
        "has_feature_bullets": round(sum(bool(i.features["bullets"]) for i in items) / n, 4),
        "has_price": round(sum(i.price is not None for i in items) / n, 4),
        "has_brand": round(sum(i.brand is not None for i in items) / n, 4),
        "has_image_url": round(sum(i.image_url is not None for i in items) / n, 4),
        "has_category_path": round(sum(bool(i.category_path) for i in items) / n, 4),
        "empty_title_count": sum(not i.title for i in items),
        "main_category_top": _top(i.features.get("main_category", "(missing)") for i in items),
        "category_level2_top": _top(
            i.category_path[1] if len(i.category_path) > 1 else "(none)" for i in items
        ),
    }


def _top(values: Iterable[str], k: int = 10) -> dict[str, int]:
    counts = Counter(values)
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:k]
    return dict(ranked)


def inventory_stats(stock: Sequence[SimulatedStock]) -> dict[str, Any]:
    available = [s.available for s in stock]
    top = sorted(available, reverse=True)
    return {
        "simulated": True,
        "items": len(stock),
        "out_of_stock_share": round(sum(a == 0 for a in available) / len(stock), 4),
        "available": _quantiles(available),
        "top_decile_share_of_units": round(sum(top[: len(top) // 10]) / max(1, sum(top)), 4),
        "restock_every_days": _quantiles([s.restock_every_days for s in stock]),
    }


def interaction_stats(rows: Sequence[Interaction], split: Split) -> dict[str, Any]:
    ratings = Counter(x.rating for x in rows)
    per_user = Counter(x.user_id for x in rows)
    per_item = Counter(x.item_id for x in rows)
    same_ts = Counter((x.user_id, x.ts_ms) for x in rows)
    return {
        "users": len(per_user),
        "items": len(per_item),
        "interactions": len(rows),
        "density": round(len(rows) / (len(per_user) * len(per_item)), 6),
        "interactions_per_user": _quantiles(list(per_user.values())),
        "interactions_per_item": _quantiles(list(per_item.values())),
        "rating_distribution": {str(k): ratings[k] for k in sorted(ratings)},
        "rating_ge_4_share": round(sum(v for k, v in ratings.items() if k >= 4) / len(rows), 4),
        "same_user_same_timestamp_groups": sum(1 for c in same_ts.values() if c > 1),
        "split": {"train": len(split.train), "valid": len(split.valid), "test": len(split.test)},
        "split_rating_ge_4": {
            "train": sum(x.rating >= 4 for x in split.train),
            "valid": sum(x.rating >= 4 for x in split.valid),
            "test": sum(x.rating >= 4 for x in split.test),
        },
    }


# --------------------------------------------------------------------------- database


async def _stage_and_insert(
    conn: asyncpg.Connection,
    table: str,
    columns: Sequence[str],
    records: Iterable[Sequence[object]],
) -> int:
    stage = f"_stage_{table}"
    await conn.execute(
        f"CREATE TEMP TABLE {stage} (LIKE {table} INCLUDING DEFAULTS) ON COMMIT DROP"
    )
    await conn.copy_records_to_table(stage, records=list(records), columns=list(columns))
    cols = ", ".join(columns)
    status = await conn.execute(
        f"INSERT INTO {table} ({cols}) SELECT {cols} FROM {stage} ON CONFLICT DO NOTHING"  # noqa: S608 (fixed identifiers)
    )
    return int(status.rsplit(" ", 1)[-1])


async def load_database(
    dsn: str,
    spec: DatasetSpec,
    items: Sequence[ItemRow],
    rows: Sequence[Interaction],
    stock: Sequence[SimulatedStock],
    *,
    connect_timeout_s: float,
    command_timeout_s: float,
) -> dict[str, dict[str, int]]:
    conn = await asyncpg.connect(dsn, timeout=connect_timeout_s, command_timeout=command_timeout_s)
    try:
        revision = None
        if await conn.fetchval("SELECT to_regclass('alembic_version')") is not None:
            revision = await conn.fetchval("SELECT version_num FROM alembic_version")
        if revision != SCHEMA_REVISION:
            raise DataCheckError(
                f"schema revision is {revision!r}, expected {SCHEMA_REVISION!r}; run `make migrate`"
            )
        inserted: dict[str, int] = {}
        async with conn.transaction():
            users = sorted({x.user_id for x in rows})
            inserted["users"] = await _stage_and_insert(
                conn, "users", ("user_id", "source"), ((u, spec.source) for u in users)
            )
            inserted["items"] = await _stage_and_insert(
                conn,
                "items",
                (
                    "item_id",
                    "source",
                    "title",
                    "description",
                    "features",
                    "category_path",
                    "price",
                    "brand",
                    "image_url",
                ),
                (
                    (
                        i.item_id,
                        i.source,
                        i.title,
                        i.description,
                        json.dumps(i.features, sort_keys=True, ensure_ascii=False),
                        list(i.category_path),
                        i.price,
                        i.brand,
                        i.image_url,
                    )
                    for i in items
                ),
            )
            inserted["interactions"] = await _stage_and_insert(
                conn,
                "interactions",
                ("user_id", "item_id", "ts", "type", "value"),
                interaction_records(rows),
            )
            inserted["inventory"] = await _stage_and_insert(
                conn,
                "inventory",
                ("item_id", "available"),
                ((s.item_id, s.available) for s in stock),
            )
        counts = {
            table: int(await conn.fetchval(f"SELECT count(*) FROM {table}"))  # noqa: S608
            for table in ("users", "items", "interactions", "inventory")
        }
    finally:
        await conn.close()
    return {"inserted": inserted, "row_counts": counts}


def check_counts(spec: DatasetSpec, counts: dict[str, int]) -> None:
    expected = {
        "users": spec.expected_users,
        "items": spec.expected_items,
        "interactions": spec.expected_interactions,
        "inventory": spec.expected_items,
    }
    wrong = {t: (counts.get(t), n) for t, n in expected.items() if counts.get(t) != n}
    if wrong:
        raise DataCheckError(f"row counts differ from the data card (actual, expected): {wrong}")


# --------------------------------------------------------------------------- main


def build(
    spec: DatasetSpec, raw_dir: Path, processed_dir: Path
) -> tuple[list[ItemRow], list[Interaction], list[SimulatedStock], dict[str, Any]]:
    inputs = {s.name: s for s in (spec.ratings, spec.metadata, spec.reviews)}
    paths = {name: fetch(src, raw_dir, timeout_s=120.0) for name, src in inputs.items()}
    ratings_path = paths[spec.ratings.name]

    rows = list(read_ratings_csv(ratings_path))
    if len(k_core(rows, k_user=spec.k_core, k_item=spec.k_core)) != len(rows):
        raise DataCheckError(f"{ratings_path.name} is not a {spec.k_core}-core fixed point")
    if len(rows) != spec.expected_interactions:
        raise DataCheckError(f"expected {spec.expected_interactions} interactions, got {len(rows)}")

    split = leave_last_out(rows)
    outputs = write_split(split, processed_dir)

    items = read_items(paths[spec.metadata.name], {x.item_id for x in rows}, source=spec.source)
    train_pop = Counter(x.item_id for x in split.train)
    config = InventoryConfig()
    stock = simulate_inventory({i.item_id: train_pop.get(i.item_id, 0) for i in items}, config)
    outputs |= write_restock_rules(stock, processed_dir)

    stats: dict[str, Any] = {
        "dataset": {"category": spec.category, "source": spec.source, "k_core": spec.k_core},
        "inputs_sha256": {p.name: inputs[n].sha256 for n, p in paths.items()},
        "outputs_sha256": outputs,
        "interactions": interaction_stats(rows, split),
        "items": item_stats(items),
        "reviews": review_stats(paths[spec.reviews.name], rows),
        "inventory": inventory_stats(stock) | {"config": asdict(config)},
    }
    return items, rows, stock, stats


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build and load the P1 dataset (make data).")
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--processed-dir", type=Path, default=Path("data/processed/video_games"))
    parser.add_argument(
        "--stats-out", type=Path, default=Path("docs/results/p1-dataset-stats.json")
    )
    parser.add_argument("--skip-db", action="store_true", help="build files and stats only")
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level, "console")
    spec = VIDEO_GAMES

    items, rows, stock, stats = build(spec, args.raw_dir, args.processed_dir)
    args.stats_out.parent.mkdir(parents=True, exist_ok=True)
    args.stats_out.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    logger.info("files and stats written", extra={"stats": str(args.stats_out)})

    if args.skip_db:
        return
    result = asyncio.run(
        load_database(
            settings.postgres_dsn_asyncpg,
            spec,
            items,
            rows,
            stock,
            connect_timeout_s=settings.db_connect_timeout_s,
            command_timeout_s=settings.db_bulk_timeout_s,
        )
    )
    check_counts(spec, result["row_counts"])
    logger.info("database loaded", extra=result)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
