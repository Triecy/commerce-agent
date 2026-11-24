# ADR-0007: Deterministic profile and recommendation; no LLM on Flow R critical path

- Status: Accepted
- Date: 2026-11-22
- Spec reference: SPEC.md §12

## Context

The upstream profile agent always called an LLM, even though a deterministic RFM implementation existed, and Flow R had three serial LLM calls (SPEC §2.2 D6). That makes results non-reproducible, slow and costly.

## Decision

- Profile (features, RFM, segments) and recommendation (recall, filtering, ranking) are deterministic services. Ties are broken deterministically, never with `random`.
- LLM rerank is a feature flag, off by default (FR-R4).
- Marketing copy is cached; on a cache miss Flow R returns template copy and fills the cache asynchronously (FR-M4).

## Consequences

- Flow R latency does not depend on an LLM provider, so its target is testable with a stub.
- Only Router, Knowledge and Marketing Copy are LLM-driven, and documentation says so (CLAUDE.md §6).
- E2 decides with evidence whether LLM rerank is worth enabling.
