# ADR-0002: Amazon Reviews 2023 (one small category) as primary dataset

- Status: Accepted (category chosen in P1: Video_Games)
- Date: 2026-11-22
- Spec reference: SPEC.md §12

## Context

Recommendation, RAG, marketing copy and inventory simulation should all operate on the same items, so results connect end to end. Retailrocket offers a real event stream, but its item properties are hashed and have no readable text, so it cannot support RAG or copy and cannot be joined with any text dataset (SPEC §5.1).

## Decision

- The primary dataset is **one small category of Amazon Reviews 2023 (McAuley Lab)**: item metadata (title, description, features), review text, and timestamped user-item interactions.
- **The specific category is chosen in P1 after profiling** and written back into this ADR and `docs/data-card.md`. Selection criteria: English; after k-core roughly 20k-100k items; at least 200k interactions; enough text per item for RAG.
- Retailrocket is deferred (ADR-0011): not planned and not scaffolded. If it is ever revived, it is a separate tenant for event replay, load testing and generalization evaluation only, and it is never merged with Amazon data.
- License and fields are verified at download time.

## Consequences

- One dataset closes the loop for Flow R and Flow Q on the same item set, which lowers MVP risk.
- Review-derived interactions are a proxy for purchases/views; this bias is documented in the data card and limits what offline metrics mean.
- Inventory is simulated on top of these items and always labeled *simulated*.

## Category decision (P1, 2026-11-23)

**Video_Games**, approved by the owner after profiling three candidates
(`docs/results/p1-category-profiling.md`). On the official 5-core file it has 94,762 users,
25,612 items and 814,586 interactions, which meets the selection criteria. It also has the
most interactions of the three candidates (more statistical power for E1), the longest item
text, and natural shopping constraints for E5.

Owner decisions that go with it:

- The official 5-core file is used as is: k = 5, no extra filtering.
- Every review is a positive implicit interaction, with the star rating stored in
  `interactions.value`. E1's main result uses all interactions; a robustness variant keeps
  only rating >= 4, and this is documented as a limitation.
- P3 caps the number of reviews per item that get embedded.

Rejected alternatives: Musical_Instruments (smaller, fewer interactions; best feature
coverage) and Industrial_and_Scientific (fewest interactions; least description coverage).

No license is stated for the data; see `docs/data-card.md` section 2 for what was checked
and the conservative usage rules (no redistribution, aggregates only, no commercial use).
