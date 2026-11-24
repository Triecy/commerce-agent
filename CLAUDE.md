# CLAUDE.md — Commerce Agent

Read this file at the start of every session. It summarizes the project context and the decisions already made, so the owner does not have to repeat them. If anything here conflicts with `SPEC.md`, **`SPEC.md` wins**; then fix this file.

## 1. Source of truth

- `SPEC.md` (repo root) is the single source of truth. Current version: v0.6 (baseline, approved by the owner; written in English).
- Work **strictly in the phase order of SPEC §11** (P0 → P9). Do not jump ahead. Each phase has exit criteria; a phase is done only when they are met.
- Every requirement has an ID (`FR-*`, `NFR-*`). Reference IDs in commit messages, PR descriptions and test names (e.g. `test_FR_I2_no_oversell`). Update the status column (☐ / ◐ / ☑) in SPEC when you finish a requirement.
- If the spec turns out to be wrong or infeasible: **stop, propose a spec change, and get the owner's approval.** Change `SPEC.md` in the same PR and add a row to its changelog (§15). Never silently deviate.
- Major technical decisions are recorded as ADRs in `docs/adr/` (index in SPEC §12).

## 2. The project in one paragraph

Commerce Agent is a portfolio-grade, **single-developer** e-commerce system built on real public data (Amazon Reviews 2023, one small category). It has two request flows: **Flow R** (personalized recommendations, mostly deterministic workflow) and **Flow Q** (shopping assistant with RAG, citations and abstention, genuinely agentic). It starts as a modular monolith and evolves into an event-driven backend (Postgres outbox → Kafka → idempotent consumers, later an independent inventory service). Every architectural step is validated with benchmarks, concurrency tests and failure injection. The project narrative: *"Started from a mock-data multi-agent prototype; built a real data pipeline, evaluated recommendation and RAG, tested whether multi-agent beats single-agent, evolved to event-driven architecture, and verified consistency and resilience by experiment."*

## 3. Owner context

- Solo developer building this for learning and a portfolio/resume. Wants engineering depth in three areas: AI application engineering, backend engineering, distributed-systems patterns.
- The owner chats in **Chinese**. Reply to the owner in Chinese unless asked otherwise. **All code, comments, docs, commit messages and file contents are in English.**
- OS is not yet confirmed (detect it). **Docker was NOT installed at the start** — check `docker --version` before any compose work. If missing, do the non-Docker parts first and tell the owner clearly how to install Docker Desktop and what to run to verify (`docker run hello-world`).
- The owner will use the Anthropic Console API key for LLM calls. Never ask the owner to paste a key into the chat; read it from the `ANTHROPIC_API_KEY` environment variable / `.env` (git-ignored).
- Copyright holder name for LICENSE/NOTICE: ask the owner if it is not given. Do not invent one.

## 4. Decisions already made (summary of SPEC §12)

| ADR | Decision |
|---|---|
| 0001 | Python only. No Java/Go. **LangGraph is the only orchestrator.** |
| 0002 | **Amazon Reviews 2023, one small category** is the primary dataset (items + text + reviews + timestamped interactions; supports recsys, RAG, copy, inventory simulation on the same items). Category chosen in P1 after profiling (target: ~20k–100k items after k-core, ≥200k interactions, English); record it in ADR-0002 and `docs/data-card.md`. **Retailrocket is Tier 2** (event replay, load test, generalization eval); it has hashed item properties, no readable text, and must NOT be joined with Amazon. |
| 0003 | Vector search with **pgvector** behind a `VectorIndex` interface. Milvus is only a Tier 3 comparison. |
| 0004 | Modular monolith first; split a service only if (a) it has independent scaling/availability/consistency needs and (b) the benefit can be measured. |
| 0005 | **Apache Kafka (KRaft, single node)** with `aiokafka` (Redpanda is an acceptable swap). |
| 0006 | LLM = **Claude via the native API behind an `LLMClient` abstraction** (FR-O7). Haiku 5.5 → Router, marketing copy, dev/debug; Sonnet 5.5 → RAG answer generation; Opus 5.5 → evaluation judge only (a different tier than the model under test). Local **Ollama** is allowed for early debugging only; **evaluation results count only if produced with Claude.** Initial total evaluation budget **$30 USD**, to be recalibrated at the end of P2. P0–P2 need no LLM. |
| 0007 | Profile/recommendation are deterministic; **LLM is never on the Flow R critical path** (copy is cached; template fallback). |
| 0008 | At-least-once delivery + idempotent consumers; read paths fail-open, inventory reservation fails closed. |
| 0009 | Evaluation: full-ranking metrics (no sampled negatives), temporal split (leave-last-out), LLM response cache for reproducibility. |
| 0010 | **New empty repository `commerce-agent`; NOT a fork of the upstream.** Borrow ideas only, credit the upstream in `NOTICE`, copy no code or docs (the upstream has no LICENSE file). Confirmed by the owner. |

## 5. Scope tiers

- **Tier 1 (must):** data pipeline, recsys baselines + offline eval, RAG + eval, LangGraph two-flow orchestration, Postgres inventory + idempotency, outbox + Kafka + consumers, observability, experiments E1–E8.
- **Tier 2 (cuttable, cut in this order if behind):** E9/Thompson simulator → cross-encoder rerank → Retailrocket tenant → P6 service extraction (keep the V1-vs-V2 comparison) → shrink E2.
- **Tier 3 (stretch):** Milvus comparison, K8s, gRPC, online learning.
- **Never cut:** data pipeline, E1, RAG evaluation, E5, outbox+Kafka+idempotency, E7, E8.
- **Added after discussion:** FR-E7 — Kafka topic with ≥3 partitions, 3 consumer instances, kill one, verify no loss, per-key ordering, no duplicate side effects, record rebalance time.

## 6. Agents: be honest about what is an LLM

Only **Router, Knowledge (RAG answer synthesis) and Marketing Copy** are LLM-driven. **Profile, Recommendation (LLM rerank is a feature flag, default off) and Inventory are deterministic services.** Experiment E5 compares a single-agent baseline (one Claude with all tools) against the multi-agent workflow. **The result is allowed to be "multi-agent is not better"** — report it honestly; the two implementations share one interface (FR-O5), so the default can be switched.

## 7. Engineering rules

1. **No numbers without evidence.** Any latency/throughput/NDCG/cost figure must come from a reproducible artifact in `docs/results/`. Never claim real-world CTR/CVR/GMV improvement (there is no real traffic). Never claim "production-grade", and do not reuse any number from the upstream README.
2. **LLM access only through `LLMClient`** (Claude / Ollama / Fake implementations). No vendor SDK imports in business code. CI uses only the Fake client and must run offline without any API key. Use the on-disk prompt→response cache for all evaluations; estimate cost before an eval run and refuse to run if it exceeds the remaining budget.
3. **Every external call has an enforced timeout** (the upstream's `timeout` was stored but never applied). Retries only for idempotent operations, with exponential backoff + jitter and a retry budget. Propagate a request-level deadline.
4. **Determinism and reproducibility:** fixed seeds, pinned dependencies (`uv.lock`), dataset versions + checksums, `make data` idempotent. No `random` tie-breaking in ranking.
5. **Correctness invariants:** no oversell (`available >= 0` always; atomic `UPDATE ... WHERE available >= qty`; DB CHECK as backstop); idempotency via `Idempotency-Key` unique constraint; outbox written in the same transaction as the state change; consumers dedupe by `event_id`.
6. **Degradation is explicit:** follow the SPEC §7.2 ladder; always return a `degraded[]` list and emit metrics.
7. **Security baseline:** secrets only via environment variables; `.env` git-ignored; `.env.example` committed; CORS allow-list; Pydantic validation on every input.
8. **Quality bar:** `ruff` + `mypy` clean; core modules (resilience, inventory, events, experiments) ≥ 80% unit coverage; integration tests use real containers (testcontainers).
9. **Simulated things are labeled as simulated** (inventory, Thompson sampling results).
10. Keep PRs small and phase-scoped. Don't refactor unrelated code. Don't push to a remote or open PRs unless the owner asks.

## 8. Notes about the upstream repo (reference only)

Upstream: `bcefghj/multi-agent-ecommerce-system` (no LICENSE file despite an MIT badge). **Do not copy its code or docs.** The new repo starts from blank; credit the upstream as inspiration in `NOTICE`. Audited defects (do not reproduce them): hardcoded 15-item `MOCK_PRODUCTS`; feature store / vector store / DB never wired; supervisor inventory check ran on a different candidate set than the reranked list (could recommend out-of-stock items); agent timeouts never enforced; A/B `config` never changed behavior and Thompson sampling was never called; profile agent always called an LLM; compose had unused MySQL and a Milvus service without a start command; one test file; unsupported README claims (CTR +15%, P99 < 2s, etc.).

## 9. What this project is NOT

No real payments/orders/accounts, no polished frontend (dashboard only needs to be clear), no Java/Go versions, no K8s in the main plan, no claim of large-scale distribution. Everything runs on one machine via Docker Compose; describe it as "distributed-systems patterns (outbox, at-least-once + idempotency, eventual consistency, partial failure handling, consumer-group rebalance) implemented and verified", not as a high-QPS distributed system.

## 10. Target layout and commands

Layout: see SPEC §4.6 (`src/commerce_agent/...`, `tests/`, `bench/`, `deploy/`, `docs/`). Repo name `commerce-agent`, Python package `commerce_agent`, license MIT.

Commands (created in P0; keep this list current): `make up`, `make down`, `make test`, `make lint`, `make data` (P1), `make eval-e1` … `make bench-e6` (later phases).

## 11. Working agreement

- Start each phase by turning that phase's requirements into a short checklist and showing it to the owner.
- At the end of each phase: run the tests, check the exit criteria, update requirement statuses in SPEC, write/refresh ADRs and result reports, then summarize in a few sentences and name the next step.
- When a decision needs the owner (e.g. dataset category in P1, LLM budget recalibration at the end of P2), ask once, clearly, with a recommendation.
