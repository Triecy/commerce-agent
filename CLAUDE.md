# CLAUDE.md — Commerce Agent

Read this file at the start of every session. It summarizes the project context and the decisions already made, so the owner does not have to repeat them. If anything here conflicts with `SPEC.md`, **`SPEC.md` wins**; then fix this file.

## 1. Source of truth

- `SPEC.md` (repo root) is the single source of truth. Current version: v0.7.5 (baseline, approved by the owner; scope refocused on depth by ADR-0011; written in English).
- Work **strictly in the phase order of SPEC §11** (P0 → P9). Do not jump ahead. Each phase has exit criteria; a phase is done only when they are met.
- Every requirement has an ID (`FR-*`, `NFR-*`). Reference IDs in commit messages, PR descriptions and test names (e.g. `test_FR_I2_no_oversell`). Update the status column (☐ / ◐ / ☑) in SPEC when you finish a requirement.
- If the spec turns out to be wrong or infeasible: **stop, propose a spec change, and get the owner's approval.** Change `SPEC.md` in the same PR and add a row to its changelog (§15). Never silently deviate.
- Major technical decisions are recorded as ADRs in `docs/adr/` (index in SPEC §12).

## 2. The project in one paragraph

Commerce Agent is a portfolio-grade, **single-developer** e-commerce system built on real public data (Amazon Reviews 2023, one small category). It has two request flows: **Flow R** (personalized recommendations, mostly deterministic workflow) and **Flow Q** (shopping assistant with RAG, citations and abstention, genuinely agentic). It starts as a modular monolith and evolves into an event-driven backend (Postgres outbox → Kafka → idempotent consumers); an independent inventory service is deferred (ADR-0011). Every architectural step is validated with benchmarks, concurrency tests and failure injection. The project narrative: *"Started from a mock-data multi-agent prototype; built a real data pipeline, evaluated recommendation and RAG, tested whether multi-agent beats single-agent, evolved to event-driven architecture, and verified consistency and resilience by experiment."*

## 3. Owner context

- Solo developer building this for learning and a portfolio/resume. Wants engineering depth in three areas: AI application engineering, backend engineering, distributed-systems patterns.
- **Reply to the owner in English.** The owner may write in Chinese, but replies, summaries and checklists are in English unless a specific message explicitly asks for another language. **All code, comments, docs, commit messages and file contents are in English.**
- Owner's machine: **macOS 13 (Apple Silicon)**. The Docker engine is **Colima**, not Docker Desktop (Docker CLI + Compose v2 against the `colima` context). After a reboot, run `colima start` before `make up`; if `docker info` fails, check `colima status` first.
- The owner will use the Anthropic Console API key for LLM calls. Never ask the owner to paste a key into the chat; read it from the `ANTHROPIC_API_KEY` environment variable / `.env` (git-ignored).
- Copyright holder name for LICENSE/NOTICE: ask the owner if it is not given. Do not invent one.

## 4. Decisions already made (summary of SPEC §12)

| ADR | Decision |
|---|---|
| 0001 | Python only. No Java/Go. **LangGraph is the only orchestrator.** |
| 0002 | **Amazon Reviews 2023, one small category** is the primary dataset (items + text + reviews + timestamped interactions; supports recsys, RAG, copy, inventory simulation on the same items). **Category: Video_Games** (chosen in P1; official 5-core file as is, every review is a positive interaction; see ADR-0002 and `docs/data-card.md`). No license is stated for the data: never redistribute it, publish aggregates only, no commercial use. **Retailrocket is deferred (ADR-0011)**: do not build or scaffold it. It has hashed item properties and no readable text; if ever revived it must NOT be joined with Amazon. |
| 0003 | Vector search with **pgvector** behind a `VectorIndex` interface. A Milvus comparison is deferred (ADR-0011). |
| 0004 | Modular monolith first; split a service only if (a) it has independent scaling/availability/consistency needs and (b) the benefit can be measured. |
| 0005 | **Apache Kafka (KRaft, single node)** with `aiokafka` (Redpanda is an acceptable swap). |
| 0006 | LLM = **Claude via the native API behind an `LLMClient` abstraction** (FR-O7). Haiku 5.5 → Router, marketing copy, dev/debug; Sonnet 5.5 → RAG answer generation; Opus 5.5 → evaluation judge only (a different tier than the model under test). Local **Ollama** is allowed for early debugging only; **evaluation results count only if produced with Claude.** Total evaluation budget **$110 USD** (raised from $30 in the P2 budget review) with per-experiment caps: E4 $48, E5 pilot $50, FR-O6 $2, FR-M $2, development $8; next review at the end of P3. P0–P2 need no LLM. |
| 0007 | Profile/recommendation are deterministic; **LLM is never on the Flow R critical path** (copy is cached; template fallback). |
| 0008 | At-least-once delivery + idempotent consumers; read paths fail-open, inventory reservation fails closed. |
| 0009 | Evaluation: full-ranking metrics (no sampled negatives), temporal split (leave-last-out), LLM response cache for reproducibility. |
| 0010 | **New empty repository `commerce-agent`; NOT a fork of the upstream.** Borrow ideas only, credit the upstream in `NOTICE`, copy no code or docs (the upstream has no LICENSE file). Confirmed by the owner. |
| 0011 | **Depth over breadth.** Five deep items (SPEC §1.6) carry the project; a Definition of Done gates every phase. Backend/distributed patterns are the flagship; RAG is also deep (FR-K6–K8 added, FR-K3 cross-encoder restored as an E3 arm). Deferred: P6/V3, Retailrocket, E2/FR-R4, E9/FR-X5, FR-B4. Reduced: E5 to a pilot, E6 to V1 vs V2. Confirmed by the owner. |

## 5. Scope tiers (SPEC §3, ADR-0011)

- **Tier 1 (must, deep): the five deep items of SPEC §1.6.**
  1. Data pipeline + recommendation evaluation (FR-D*, FR-R1–R3, FR-R5, E1).
  2. RAG grounded Q&A (FR-K1–K8, E3, E4).
  3. Inventory consistency + idempotency (FR-I1–I5, E7).
  4. Outbox → Kafka → idempotent consumers (FR-E1–E7, including the FR-E7 consumer-group kill/rebalance test).
  5. Failure injection and resilience (FR-S*, FR-O3, FR-O4, FR-I6, E8).
- **Tier 2 (supporting, lean):** LangGraph two-flow orchestration (FR-O*), marketing copy (FR-M*), experiment framework (FR-X1–X4), observability (FR-B1–B3), E5 pilot, E6 (V1 vs V2). Keep these small. If behind, cut in this order: **E5 pilot** (keep the FR-O5 interface) → **E6** (keep E7 and E8) → **FR-K3** cross-encoder arm in E3.
- **Deferred (do not build, do not scaffold):** P6 / V3 independent inventory service and separately deployed consumers, Retailrocket tenant, FR-R4 / E2 (LLM rerank), FR-X5 / E9 (Thompson simulator), FR-B4 (dashboard app; Grafana panels cover it), Milvus comparison, K8s, gRPC, online learning. No placeholder files, modules, flags or compose services for these. Revisit only after all of Tier 1 meets the Definition of Done, and only through a spec change.
- **Never cut:** the five deep items above.

## 6. Agents: be honest about what is an LLM

Only **Router, Knowledge (RAG answer synthesis) and Marketing Copy** are LLM-driven. **Profile, Recommendation and Inventory are deterministic services.** LLM rerank (FR-R4 / E2) is deferred (ADR-0011), so recommendation has no LLM at all. Experiment E5 compares a single-agent baseline (one Claude with all tools) against the multi-agent workflow. **The result is allowed to be "multi-agent is not better"** — report it honestly; the two implementations share one interface (FR-O5), so the default can be switched.

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
10. Keep PRs small and phase-scoped. Don't refactor unrelated code. Don't open PRs unless the owner asks. Git writes are covered by rule 12.
11. **Depth over breadth (ADR-0011).** Prefer taking a deep item further over adding a new feature. A phase cannot close until this **Definition of Done** (SPEC §1.6) holds for each of its deep items and requirement groups:
    1. Core paths are covered by automated tests, named with the requirement ID.
    2. A result report exists in `docs/results/` with method, numbers, **limitations**, and "what was tried and did not work".
    3. Related decisions are recorded as ADRs.
    4. One `make` command reproduces the result from a clean checkout.
    5. Requirement statuses in SPEC are updated (☐ / ◐ / ☑).
12. **The owner commits; Claude never does.** Never run `git add`, `git commit` or `git push`, including amend, rebase, cherry-pick, merge or any history rewrite that creates commits. Leave every change in the working tree. Read-only git commands (`status`, `diff`, `log`, `show`) are fine. At the end of each task, hand over the commit plan described in §11.

## 8. Notes about the upstream repo (reference only)

Upstream: `bcefghj/multi-agent-ecommerce-system` (no LICENSE file despite an MIT badge). **Do not copy its code or docs.** The new repo starts from blank; credit the upstream as inspiration in `NOTICE`. Audited defects (do not reproduce them): hardcoded 15-item `MOCK_PRODUCTS`; feature store / vector store / DB never wired; supervisor inventory check ran on a different candidate set than the reranked list (could recommend out-of-stock items); agent timeouts never enforced; A/B `config` never changed behavior and Thompson sampling was never called; profile agent always called an LLM; compose had unused MySQL and a Milvus service without a start command; one test file; unsupported README claims (CTR +15%, P99 < 2s, etc.).

## 9. What this project is NOT

No real payments/orders/accounts, no polished frontend and no dashboard app (Grafana panels only need to be clear), no Java/Go versions, no K8s in the main plan, no claim of large-scale distribution. Everything runs on one machine via Docker Compose; describe it as "distributed-systems patterns (outbox, at-least-once + idempotency, eventual consistency, partial failure handling, consumer-group rebalance) implemented and verified", not as a high-QPS distributed system.

## 10. Target layout and commands

Layout: see SPEC §4.6 (`src/commerce_agent/...`, `tests/`, `bench/`, `deploy/`, `docs/`). Repo name `commerce-agent`, Python package `commerce_agent`, license MIT.

Commands (created in P0; keep this list current): `make install`, `make up`, `make down`, `make test`, `make lint`, `make typecheck`, `make fmt`, `make audit`, `make test-integration`, `make migrate`, `make data`, `make data-reset`, `make profile-categories`, `make eval-e1` … `make bench-e6` (later phases).

## 11. Working agreement

- Start each phase by turning that phase's requirements into a short checklist and showing it to the owner.
- At the end of each phase: run the tests, check the exit criteria, update requirement statuses in SPEC, write/refresh ADRs and result reports, then summarize in a few sentences and name the next step.
- When a decision needs the owner (e.g. dataset category in P1, LLM budget recalibration at the end of P2), ask once, clearly, with a recommendation.
- **End of every task: commit plan for the owner** (rule 12; Claude never stages, commits or pushes). Print:
  1. The output of `git status --short`.
  2. A suggested grouping of the changed files into small, logical commits.
  3. For each group, the exact `git add <paths>` command and a one-line English commit message in the imperative mood, with no attribution trailers (no `Co-Authored-By`, no `Claude-Session`).
