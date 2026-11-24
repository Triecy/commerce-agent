# ADR-0010: New repository, not a fork of the upstream

- Status: Accepted (confirmed by the owner)
- Date: 2026-11-22
- Spec reference: SPEC.md §12

## Context

The project was inspired by `bcefghj/multi-agent-ecommerce-system`. That repository shows an MIT badge but has **no LICENSE file** (SPEC §2.2 D10), so its code and docs cannot be assumed redistributable. Most of its implementation is also being replaced (SPEC §2.3).

## Decision

- `commerce-agent` is a **new, empty repository**, not a fork of the upstream.
- Ideas and overall structure may be borrowed; **no code and no documentation are copied**.
- `NOTICE` credits the upstream as inspiration and links to it.
- This repository is MIT-licensed, with copyright held by the owner.

## Consequences

- No licensing ambiguity for this repository.
- No upstream README numbers or resume claims are reused (SPEC §14).
- If the upstream later adds a license and substantial reuse becomes desirable, this ADR is re-evaluated first.
