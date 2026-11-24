# ADR-0002: Amazon Reviews 2023 (one small category) as primary dataset

- Status: Accepted (category to be chosen in P1)
- Date: 2026-11-22
- Spec reference: SPEC.md §12

## Context

Recommendation, RAG, marketing copy and inventory simulation should all operate on the same items, so results connect end to end. Retailrocket offers a real event stream, but its item properties are hashed and have no readable text, so it cannot support RAG or copy and cannot be joined with any text dataset (SPEC §5.1).

## Decision

- The primary dataset is **one small category of Amazon Reviews 2023 (McAuley Lab)**: item metadata (title, description, features), review text, and timestamped user-item interactions.
- **The specific category is chosen in P1 after profiling** and written back into this ADR and `docs/data-card.md`. Selection criteria: English; after k-core roughly 20k-100k items; at least 200k interactions; enough text per item for RAG.
- Retailrocket is Tier 2: event replay, load testing and generalization evaluation only, as a separate tenant. It is never merged with Amazon data.
- License and fields are verified at download time.

## Consequences

- One dataset closes the loop for Flow R and Flow Q on the same item set, which lowers MVP risk.
- Review-derived interactions are a proxy for purchases/views; this bias is documented in the data card and limits what offline metrics mean.
- Inventory is simulated on top of these items and always labeled *simulated*.

**Category decision (P1):** _pending_.
