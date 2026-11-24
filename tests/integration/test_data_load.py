"""FR-D1/FR-D3 against a real Postgres (testcontainers): migrations, idempotent load,
inventory invariants. Run with `make test-integration` (needs Docker)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from testcontainers.community.postgres import PostgresContainer

from commerce_agent.data.canonicalize import ItemRow
from commerce_agent.data.pipeline import DataCheckError, load_database
from commerce_agent.data.simulate_inventory import simulate_inventory
from commerce_agent.data.sources import DatasetSpec
from commerce_agent.data.split import Interaction

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[2]
SPEC = DatasetSpec("Test", "test/source", 1, 2, 2, 3)
ITEMS = [
    ItemRow(
        "i1",
        "test/source",
        "One",
        "",
        {"bullets": [], "details": {}},
        ("A",),
        Decimal("9.99"),
        "B",
        None,
    ),
    ItemRow(
        "i2", "test/source", "Two", "d", {"bullets": ["x"], "details": {}}, (), None, None, None
    ),
]
ROWS = [
    Interaction("u1", "i1", 1, 5.0),
    Interaction("u1", "i2", 2, 1.0),
    Interaction("u2", "i1", 3, 4.0),
]


@pytest.fixture(scope="module")
def dsn() -> Iterator[str]:
    with PostgresContainer("pgvector/pgvector:pg16", driver=None) as pg:
        yield pg.get_connection_url()


def _alembic(dsn: str) -> Config:
    cfg = Config(str(REPO / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", dsn.replace("postgresql://", "postgresql+asyncpg://", 1))
    return cfg


def _load(dsn: str) -> dict[str, dict[str, int]]:
    stock = simulate_inventory({"i1": 2, "i2": 1})
    return asyncio.run(
        load_database(dsn, SPEC, ITEMS, ROWS, stock, connect_timeout_s=10, command_timeout_s=60)
    )


async def _fetch(dsn: str, sql: str) -> object:
    conn = await asyncpg.connect(dsn, timeout=10, command_timeout=10)
    try:
        return await conn.fetchval(sql)
    finally:
        await conn.close()


def test_FR_D1_migrations_match_models_and_round_trip(dsn: str) -> None:
    cfg = _alembic(dsn)
    command.upgrade(cfg, "head")
    command.check(cfg)  # raises if the SQLAlchemy models drift from the migrations
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


def test_FR_D1_load_is_idempotent(dsn: str) -> None:
    command.upgrade(_alembic(dsn), "head")
    first = _load(dsn)
    second = _load(dsn)
    assert first["inserted"] == {"users": 2, "items": 2, "interactions": 3, "inventory": 2}
    assert second["inserted"] == {"users": 0, "items": 0, "interactions": 0, "inventory": 0}
    assert first["row_counts"] == second["row_counts"]
    assert asyncio.run(_fetch(dsn, "SELECT value FROM interactions WHERE item_id='i2'")) == 1.0


def test_FR_D3_db_rejects_negative_inventory(dsn: str) -> None:
    command.upgrade(_alembic(dsn), "head")
    _load(dsn)
    with pytest.raises(asyncpg.CheckViolationError):
        asyncio.run(_fetch(dsn, "UPDATE inventory SET available = -1 WHERE item_id = 'i1'"))
    comment = asyncio.run(_fetch(dsn, "SELECT obj_description('inventory'::regclass)"))
    assert isinstance(comment, str) and comment.startswith("SIMULATED")


def test_FR_D1_load_refuses_wrong_schema_revision(dsn: str) -> None:
    command.downgrade(_alembic(dsn), "base")  # alembic_version exists but is empty
    with pytest.raises(DataCheckError, match="make migrate"):
        _load(dsn)
    asyncio.run(_fetch(dsn, "DROP TABLE alembic_version"))  # a never-migrated database
    with pytest.raises(DataCheckError, match="make migrate"):
        _load(dsn)
    command.upgrade(_alembic(dsn), "head")
