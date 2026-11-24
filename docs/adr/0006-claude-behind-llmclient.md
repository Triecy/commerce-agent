# ADR-0006: LLM: Claude via the native API behind an LLMClient abstraction

- Status: Accepted (model split and budget reviewed at the end of P2)
- Date: 2026-11-22
- Spec reference: SPEC.md §12

## Context

Router, RAG answer synthesis and marketing copy need an LLM. Evaluations must be reproducible and affordable, CI must run offline, and business code should not be tied to one vendor SDK. The upstream's LLM calls had no enforced timeout (SPEC §2.2 D4).

## Decision

- All LLM access goes through an in-house `LLMClient` (FR-O7) with Claude, Ollama and Fake implementations. Business code never imports a vendor SDK.
- Model split: Haiku 5.5 for Router, marketing copy and debugging; Sonnet 5.5 for RAG answer generation; Opus 5.5 as evaluation judge only, a different tier than the model under test.
- Ollama is allowed for early debugging; **evaluation results count only if produced with Claude**.
- An on-disk prompt-to-response cache is used for all evaluations. Cost is estimated before each run, and the run is refused if it would exceed the remaining budget.
- Initial total evaluation budget: **USD 30**, recalibrated at the end of P2. P0-P2 need no LLM.
- The API key is read from `ANTHROPIC_API_KEY` (environment or git-ignored `.env`) and is never committed. The owner brings their own Console account.

## Consequences

- CI uses only the Fake client and needs no key.
- Re-running an evaluation hits the cache with zero real calls (NFR-1).
- `LLMClient` is the single place for timeouts, retries, circuit breaking and token/cost metering.
