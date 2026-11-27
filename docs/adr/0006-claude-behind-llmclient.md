# ADR-0006: LLM: Claude via the native API behind an LLMClient abstraction

- Status: Accepted (budget revised in the P2 budget review, 2026-11-25: USD 110 with per-experiment caps)
- Date: 2026-11-22
- Spec reference: SPEC.md §12

## Context

Router, RAG answer synthesis and marketing copy need an LLM. Evaluations must be reproducible and affordable, CI must run offline, and business code should not be tied to one vendor SDK. The upstream's LLM calls had no enforced timeout (SPEC §2.2 D4).

## Decision

- All LLM access goes through an in-house `LLMClient` (FR-O7) with Claude, Ollama and Fake implementations. Business code never imports a vendor SDK.
- Model split: Haiku 5.5 for Router, marketing copy and debugging; Sonnet 5.5 for RAG answer generation; Opus 5.5 as evaluation judge only, a different tier than the model under test.
- Ollama is allowed for early debugging; **evaluation results count only if produced with Claude**.
- An on-disk prompt-to-response cache is used for all evaluations. Cost is estimated before each run, and the run is refused if it would exceed the remaining budget.
- Initial total evaluation budget: **USD 30**, recalibrated at the end of P2. P0-P2 need no LLM. *Superseded by the P2 budget review below: USD 110 with per-experiment caps.*
- The API key is read from `ANTHROPIC_API_KEY` (environment or git-ignored `.env`) and is never committed. The owner brings their own Console account.

## Consequences

- CI uses only the Fake client and needs no key.
- Re-running an evaluation hits the cache with zero real calls (NFR-1).
- `LLMClient` is the single place for timeouts, retries, circuit breaking and token/cost metering.

## P2 budget review (2026-11-25)

Required by this ADR and NFR-4 at the end of P2. **Actual LLM spend through P2: USD 0**
(P0-P2 use no LLM).

### Prices used

Source: <https://platform.claude.com/docs/en/about-claude/pricing>, checked 2026-11-25
(the page shows no "last updated" date). USD per million tokens, default `global`
inference geography:

| Model | Input | Output | 5-min cache write | Cache read | Batch input / output |
|---|---|---|---|---|---|
| Haiku 5.5 (prompts ≤ 100k tokens) | 0.10 | 0.50 | 0.125 | 0.01 | 0.05 / 0.25 |
| Sonnet 5.5 | 2.00 | 10.00 | 2.50 | 0.10 | 1.00 / 5.00 |
| Opus 5.5 | 4.00 | 20.00 | 5.00 | 0.20 | 2.00 / 10.00 |

Not used: Haiku's > 100k-token tier (no prompt here comes close), `inference_geo: "us"`
(+10%), fast mode.

### Assumptions

- Token counts per call are planning estimates in current-tokenizer tokens. **Output
  includes thinking tokens**, because thinking cannot be disabled on Opus 5.5 and is on by
  default on Sonnet 5.5 and Haiku 5.5. RAG context: about 8 chunks × 400 tokens.
- **Batch API** (50% off) for every non-interactive job: E4 eval-set drafting, answer
  generation and judging; the E5 groundedness judge; the copy-cache fill. E5 runs and
  Router evaluation are run interactively at list price.
- **Cache hits:** batch calls get **no cache credit** (batch cache hits are best effort).
  Interactive E5 runs write the ~3k-token system+tools prefix once per run, and later turns
  read about 12k tokens (single-agent) or 1.5k tokens (multi-agent) from cache.
- The on-disk prompt→response cache makes re-runs free, so only **first runs** are
  counted. Each item includes its development and prompt-iteration runs.
- Judge = one Opus call per answer that extracts claims and checks their citations.
- Copy cache: top 1,000 items × 5 segments only, not the whole catalog. A full-catalog
  fill (about 128k combinations) would need its own budget line.
- **Margin: +30%** on every item.

### Estimate (first runs)

| Use | Model | Calls | Input / call | Output / call | Cached / call | Batch | USD |
|---|---|---|---|---|---|---|---|
| E4 eval-set drafting (350 drafts → ≥150 + 50 adversarial) | Sonnet | 350 | 3,000 | 1,400 | 0 | yes | 3.50 |
| E4 answers: 200 questions × 2 configs (FR-K6 on/off), +20% regeneration | Sonnet | 480 | 4,800 | 1,400 | 0 | yes | 5.66 |
| E4 answer-prompt development (3 × 50) | Sonnet | 150 | 4,800 | 1,400 | 0 | yes | 1.77 |
| E4 judge, final answers (claims + citations) | Opus | 480 | 5,700 | 2,300 | 0 | yes | 16.51 |
| E4 judge, development answers | Opus | 150 | 5,700 | 2,300 | 0 | yes | 5.16 |
| E4 judge calibration (50 human-labeled × 2 prompt versions) | Opus | 100 | 5,700 | 2,300 | 0 | yes | 3.44 |
| E5 single-agent runs (100 questions × 2 runs) | Sonnet | 200 | 24,000 | 4,000 | 12,000 | no | 13.34 |
| E5 multi-agent: Router | Haiku | 200 | 1,500 | 600 | 0 | no | 0.09 |
| E5 multi-agent: Knowledge + compose (2 calls per run) | Sonnet | 400 | 5,000 | 1,400 | 1,500 | no | 8.46 |
| E5 groundedness judge (all 400 answers) | Opus | 400 | 5,700 | 2,300 | 0 | yes | 13.76 |
| E5 development runs (20 questions × 2 variants × 3) | Sonnet | 120 | 6,000 | 1,400 | 1,500 | no | 2.78 |
| FR-O6 Router accuracy (200 labeled queries × 3 prompt versions) | Haiku | 600 | 1,200 | 500 | 0 | no | 0.22 |
| FR-O6 label-set drafting | Sonnet | 20 | 1,500 | 3,000 | 0 | no | 0.66 |
| FR-M copy-cache fill (1,000 items × 5 segments, +20% regeneration) | Haiku | 6,000 | 800 | 450 | 0 | yes | 0.91 |
| Ad-hoc debugging allowance | Haiku / Sonnet | — | — | — | — | — | 5.00 |

The single-agent E5 row's 24,000 input tokens per run include the 3,000-token cache write.
Cost per call = (uncached input × input price + cached × read price + cache write × write
price + output × output price) / 10⁶, halved for batch.

| Group | Estimate | With 30% margin |
|---|---|---|
| E4 (P3) | 36.05 | 46.86 |
| E5 pilot (P4) | 38.43 | 49.96 |
| FR-O6 Router (P4) | 0.88 | 1.15 |
| FR-M copy (P4) | 0.91 | 1.19 |
| Debugging | 5.00 | 6.50 |
| **Total** | **81.27** | **105.65** |

Without the Batch API the total with margin would be about USD 171, so batching is part
of the plan, not an option.

### Decision

- **USD 30 is not enough.** The Opus judge alone (E4 + E5) is about USD 39 before margin.
- **New total evaluation budget: USD 110**, with hard per-experiment caps that
  `LLMClient` enforces (NFR-4: estimate before each run, refuse if the run would exceed its
  cap or the remaining total):

| Cap | USD |
|---|---|
| E4 (incl. eval-set drafting and judge calibration) | 48 |
| E5 pilot (incl. its judge) | 50 |
| FR-O6 Router accuracy | 2 |
| FR-M copy cache | 2 |
| Development / debugging | 8 |
| **Total** | **110** |

- Moving money between caps needs a changelog row in SPEC §15.
- **If E5 runs over:** judge groundedness on one of the two runs only (saves about
  USD 7). This follows the cut order (SPEC §11.3), where the E5 pilot is cut first.
- **Next review:** at the end of P3, against actual E4 spend (`LLMClient` meters tokens
  and cost per run).
- The model split above is unchanged.
