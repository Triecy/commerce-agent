# ADR-0011: Depth over breadth

- Status: Accepted (owner confirmed)
- Date: 2026-11-23
- Spec reference: SPEC.md §1.6, §3, §8.1, §11, §12

## Context

SPEC v0.6 planned a wide system for one developer: nine experiments (E1-E9), an
independent inventory service (V3 / P6), a second dataset tenant (Retailrocket), an LLM
rerank experiment, a Thompson-sampling simulator and a dashboard app. At about 45
person-days with optimistic estimates (SPEC §13, R9), the likely outcome was many
features each built to a shallow level. Shallow breadth is weak portfolio evidence. A few
items taken to the point where invariants are proven, ablations are reported and
failures are analyzed honestly show more engineering depth.

## Decision

- Five **deep items** carry the project (SPEC §1.6):
  1. Data pipeline + recommendation evaluation (FR-D*, FR-R1-R3, FR-R5, E1).
  2. RAG grounded Q&A (FR-K1-K8, E3, E4).
  3. Inventory consistency + idempotency (FR-I1-I5, E7).
  4. Outbox -> Kafka -> idempotent consumers (FR-E1-E7).
  5. Failure injection and resilience (FR-S*, FR-O3, FR-O4, FR-I6, E8).
- Backend and distributed-systems patterns are the flagship. RAG is also deep: citation
  verification (FR-K6), error analysis (FR-K7) and prompt-injection robustness (FR-K8)
  are added, and the cross-encoder rerank (FR-K3) is restored as an E3 ablation arm.
- **Supporting, kept lean (Tier 2):** orchestration (FR-O*), marketing copy (FR-M*),
  experiment framework (FR-X1-X4), observability (FR-B1-B3), the E5 pilot and E6.
- **Reduced:** E5 becomes a pilot (100 questions, 2 runs per variant). E6 compares only
  V1 vs V2.
- **Deferred (not planned, not scaffolded):** P6 / V3 independent inventory service and
  separately deployed consumers, the Retailrocket tenant, LLM rerank (FR-R4, E2), the
  Thompson simulator (FR-X5, E9), the dashboard app (FR-B4; Grafana panels from FR-B2
  cover it), Milvus comparison, K8s, gRPC and online learning. These are revisited only
  after all of Tier 1 meets the Definition of Done.
- A **Definition of Done** gates every phase. Each deep item and requirement group needs:
  1. Core paths covered by automated tests named with the requirement ID.
  2. A result report in `docs/results/` with method, numbers, limitations, and "what was
     tried and did not work".
  3. Related decisions recorded as ADRs.
  4. One `make` command that reproduces the result from a clean checkout.
  5. Updated requirement statuses in SPEC.
- If the schedule still slips, the cut order is: the E5 pilot (keep the FR-O5 interface),
  then E6 (keep E7 and E8), then the FR-K3 arm in E3. The five deep items are never cut.

## Consequences

- Estimated effort drops to about 41 person-days. P3 grows (RAG depth), P4, P8 and P9
  shrink, and P6 is kept as a numbered but empty phase so references stay stable.
  FR-I6 moves from P6 to P7.
- The project narrative changes: there is no "independent inventory service" step.
  The architecture story ends at V2 (event-driven) plus hardening, and E6 must still
  report cases where adding events makes things slower.
- The `dashboard/` directory is removed from the repository layout.
- This ADR supersedes the following statements in earlier ADRs, which are left
  unchanged as historical records:
  - ADR-0002: Retailrocket as Tier 2 is now **deferred**. ADR-0002's text was updated to
    match because its category decision is still open.
  - ADR-0003: Milvus as a "Tier 3 comparison" is now **deferred**.
  - ADR-0004: the V3 inventory-service split and the V1/V2/V3 comparison in E6 are
    **deferred**. E6 compares V1 and V2 only.
  - ADR-0007: LLM rerank (FR-R4) and its evaluation (E2) are **deferred**. Recommendation
    stays fully deterministic.
- Risk: a deferred item may turn out to matter for the narrative. Mitigation: deferral
  is reversible, but only through a spec change with owner approval after Tier 1 is done.
