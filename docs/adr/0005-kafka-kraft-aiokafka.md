# ADR-0005: Apache Kafka (KRaft, single node) with aiokafka

- Status: Accepted
- Date: 2026-11-22
- Spec reference: SPEC.md §12

## Context

The event-driven phase (V2) needs a durable, partitioned log with consumer groups so that at-least-once delivery, per-key ordering and rebalancing (FR-E7) can be demonstrated.

## Decision

- Use **Apache Kafka in KRaft mode, single node**, via Docker Compose (added in P5, not P0).
- Python clients use **aiokafka**.
- Redpanda is an acceptable drop-in swap if Kafka is too heavy locally.

## Consequences

- Consumer groups, partitions and rebalancing are real, so FR-E7 can be tested honestly.
- A single broker gives no replication; the project claims patterns, not cluster-level availability (CLAUDE.md §9).
- Topics: `events.user_behavior.v1` (at least 3 partitions), `inventory.changes.v1`, `reco.exposures.v1`, and `*.dlq` (SPEC §9.3).
