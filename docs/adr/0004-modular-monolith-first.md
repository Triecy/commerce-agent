# ADR-0004: Modular monolith first; split only by admission conditions

- Status: Accepted
- Date: 2026-11-22
- Spec reference: SPEC.md §12

## Context

Splitting into microservices early adds network hops, deployment work and failure modes without evidence of benefit. The project wants to show architecture evolution, which requires a correct baseline to compare against (SPEC §4.3).

## Decision

- V1 is a modular monolith: one FastAPI gateway process with in-process agent modules.
- A module is split into its own service only if (a) it has independent scaling, availability or consistency needs, and (b) the benefit can be measured in a benchmark.
- P4 (a functionally correct V1) must be finished before P5/P6.

## Consequences

- The inventory service (V3, Tier 2) is the main split candidate: it owns strongly consistent state and fails closed on reservations.
- E6 compares V1, V2 and V3 and must also report cases where splitting makes things slower.
- Module boundaries in `src/commerce_agent/` follow future service boundaries, so a split is a deployment change, not a rewrite.
