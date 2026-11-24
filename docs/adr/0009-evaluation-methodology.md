# ADR-0009: Evaluation: full ranking, temporal split, LLM response cache

- Status: Accepted
- Date: 2026-11-22
- Spec reference: SPEC.md §12

## Context

Sampled-negative recommendation metrics are biased, and random splits leak future information. LLM-based evaluations are non-deterministic and cost money on every re-run.

## Decision

- Recommendation metrics use **full ranking** over all candidate items; no sampled negatives.
- Splits are **temporal, leave-last-out**: each user's last interaction is test, second-to-last is validation, the rest is train.
- Results carry bootstrap 95% confidence intervals.
- LLM calls in evaluations go through a prompt-to-response cache keyed on `hash(model, prompt, params)`.
- Each run records commit, dependency lock, data version, seed, machine specs and number of runs.

## Consequences

- Metrics are lower and more honest than sampled-metric numbers often seen elsewhere.
- Evaluations are reproducible (NFR-1), and re-runs are free once cached.
- Any number in README or resume text must trace to a report in `docs/results/` (SPEC §8.4).
