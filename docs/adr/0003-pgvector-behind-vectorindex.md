# ADR-0003: Vector search with pgvector behind a VectorIndex interface

- Status: Accepted
- Date: 2026-11-22
- Spec reference: SPEC.md §12

## Context

The upstream used Milvus, which adds a stateful component (and its compose service had no start command, SPEC §2.2 D7). The catalog, chunks and inventory already live in Postgres, and retrieval needs SQL filters on category and price (FR-K2).

## Decision

- Vector search uses the **pgvector** extension in PostgreSQL 16.
- Application code accesses it only through a `VectorIndex` interface, so another backend can be swapped in.
- Milvus appears only as a Tier 3 comparison benchmark.

## Consequences

- One fewer stateful service to run and back up; vectors and filters combine in one SQL query.
- At this data scale (tens of thousands of items) pgvector is expected to be adequate; if E3 or E6 shows otherwise, the interface allows a change via a new ADR.
- The compose image is `pgvector/pgvector:pg16`, and the extension is created at init.
