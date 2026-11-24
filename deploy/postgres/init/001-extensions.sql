-- Runs once, on first initialization of the pgdata volume.
-- pgvector (ADR-0003). The schema itself is managed by Alembic from P1 onward.
CREATE EXTENSION IF NOT EXISTS vector;
