# ADR-0008: At-least-once delivery with idempotent consumers; reservations fail closed

- Status: Accepted
- Date: 2026-11-22
- Spec reference: SPEC.md §12

## Context

Exactly-once delivery across Postgres, Kafka and Redis is not practical here. Losing inventory or behavior events is unacceptable, and duplicates are inevitable after crashes or rebalances.

## Decision

- State changes write an outbox row in the **same transaction** as the change; a publisher moves rows to Kafka (FR-E2, FR-I5).
- Delivery is **at-least-once**. Consumers are **idempotent**, deduplicating by `event_id` (Redis SETNX with TTL or a DB unique constraint) (FR-E3).
- Failing events go to a DLQ after N retries, with a replay tool (FR-E4).
- Read paths fail open (results marked `stock_unknown`). The inventory reservation path fails closed (FR-I6).

## Consequences

- No lost events across crashes, at the cost of consumer-side dedupe state.
- E7 and E8 must show zero lost events and zero duplicate side effects.
- Users may see stale stock on reads during an outage, but never an oversell.
