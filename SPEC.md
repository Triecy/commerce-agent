# SPEC — Evented Multi-Agent Recommendation & Shopping-Assistant Platform

| Item | Value |
|---|---|
| Version | v0.7.4 (Baseline, approved by the owner; scope refocused on depth, ADR-0011; all ADRs in §12 are Accepted) |
| Date | 2026-11-25 |
| Upstream | `bcefghj/multi-agent-ecommerce-system` @ main (2 commits; cloned, Python implementation reviewed) |
| Project name | Commerce Agent (repository `commerce-agent`; Python package `commerce_agent`) |
| License | MIT, copyright held by the owner |

---

## 0. Source-of-Truth Protocol (read this first)

1. This file is the single source of truth. If the README, code comments or resume wording conflict with it, **this file wins**.
2. Changing the design = changing this file in the **same PR** and adding a row to the changelog in §15. If the spec turns out to be infeasible, revise the spec first; never deviate silently.
3. Every requirement has an ID (`FR-*` / `NFR-*`). PR descriptions and test function names (`test_FR_I2_*`) reference IDs; the "Status" column in the requirement tables is updated with each PR (☐ not started / ◐ in progress / ☑ done and tested).
4. Major technical decisions are recorded as ADRs (`docs/adr/NNNN-*.md`); the index is in §12.
5. **Any numeric claim (latency, throughput, NDCG, cost) must come from a reproducible experiment artifact in `docs/results/`** (§8.4). No artifact, no number in the README or on a resume.
6. Development follows the phases in §11 in order; no skipping. Each phase has exit criteria that must be met.

---

## 1. Project Overview

### 1.1 One sentence
A multi-agent e-commerce system **built on real public data** that does personalized recommendation (Flow R) and evidence-grounded shopping Q&A (Flow Q), evolving from a **modular monolith** into an **event-driven distributed backend**, with every architectural step quantified by benchmarks.

### 1.2 Project narrative (interview / portfolio storyline)
> Start from a multi-agent recommendation prototype that used mock data → build a real data pipeline and an evaluable recommender and RAG system → answer "is multi-agent better than single-agent?" with an experiment → evolve to Kafka event-driven processing → verify consistency and resilience with load tests and failure injection.

Three capability axes: **AI application engineering** (RAG, agent orchestration, evaluation) · **backend engineering** (transactions, idempotency, caching, APIs) · **distributed systems** (event-driven design, consistency, fault tolerance, observability).

### 1.3 Goals
| ID | Goal |
|---|---|
| G1 | Real data pipeline + unified Canonical Schema; all experiments reproducible |
| G2 | Recommendation: several comparable baselines + an offline evaluation framework; conclusions reported with confidence intervals |
| G3 | RAG: hybrid retrieval + grounded answers (with citations, able to abstain), with retrieval and faithfulness evaluation |
| G4 | Orchestration: LangGraph workflows with timeout budgets, degradation, and a single-agent vs multi-agent comparison |
| G5 | Distributed patterns: Outbox + Kafka, idempotent consumers, DLQ, strongly consistent inventory, distributed tracing |
| G6 | Verification: load tests, concurrency correctness tests, failure injection, and result reports |

### 1.4 Non-goals (explicitly out of scope)
- No Java / Go versions (the upstream's three languages are resume packaging, not engineering value).
- No real payment/order flow, user account system, or frontend polish (the Grafana panels only need to be clear).
- **No claims** of any real online CTR / CVR / GMV improvement (there is no real traffic, only offline metrics and simulation).
- No splitting into services for the sake of "number of microservices" (§4.3 sets admission conditions for splitting).
- No production Kubernetes deployment; Docker Compose is enough (K8s is deferred).
- No independent inventory microservice, no Dashboard app, no LLM-rerank experiment, no Retailrocket tenant, no Thompson-sampling simulator (see §3, Deferred).

### 1.5 Project-level success criteria
1. `make up && make demo` runs end to end on a clean machine in ≤ 15 minutes (including data preparation).
2. The experiments that remain in scope (E1, E3, E4, E5 pilot, E6 V1-vs-V2, E7, E8; see §8.1) have reproducible result artifacts and conclusions (conclusions may be negative, but must be honest).
3. Concurrent inventory test: 0 oversells; under failure injection: 0 lost events and 0 duplicate side effects.
4. Every Tier 1 requirement is ☑ and the core paths have automated tests.

### 1.6 Depth principle and Definition of Done
This project deliberately trades breadth for depth. Five **deep items** carry the project; everything else is kept lean or deferred (§3).

| # | Deep item | What makes it deep | Requirements / experiments |
|---|---|---|---|
| 1 | Data pipeline + recommendation evaluation | Reproducible data, leak-free temporal split, full-ranking metrics with confidence intervals | FR-D*, FR-R1–R3, FR-R5, E1 |
| 2 | RAG grounded Q&A | Retrieval and chunking ablations, cross-encoder arm, verified citations, abstention, judge calibrated on human labels, error taxonomy, prompt-injection robustness | FR-K1–K8, E3, E4 |
| 3 | Inventory consistency + idempotency | Invariants proven under concurrency, replays and crashes | FR-I1–I5, E7 |
| 4 | Outbox → Kafka → idempotent consumers | At-least-once + dedupe, DLQ, ordering per key, consumer-group scale-out and rebalance | FR-E1–E7 |
| 5 | Failure injection and resilience | Enforced timeouts, breakers, bulkheads, measured degradation and recovery | FR-S*, FR-O3, FR-O4, FR-I6, E8 |

Supporting, kept lean: orchestration (FR-O*), marketing copy (FR-M*), experiment framework (FR-X1–X4), observability (FR-B1–B3), the E5 pilot and E6 (V1 vs V2).

**Definition of Done** (applies to every deep item and requirement group; a phase cannot close until it holds):
1. Core paths are covered by automated tests, named with the requirement ID.
2. A result report exists in `docs/results/` with method, numbers, **limitations**, and "what was tried and did not work".
3. Related decisions are recorded as ADRs.
4. One `make` command reproduces the result from a clean checkout.
5. Requirement statuses in this spec are updated (☐ / ◐ / ☑).

---

## 2. Upstream Repository Audit

### 2.1 What the upstream actually is
A Python (LangGraph + FastAPI) Supervisor-style recommendation prototype: 4 agents (profile / recommendation / inventory / copy) + an A/B engine + a Redis Feature Store class. It also has parallel Java and Go implementations (**not reviewed line by line**, since they will be deleted), interview Q&A material and a resume template. The Supervisor's orchestration shape (Phase 1 parallel → Phase 2 parallel → serial copy generation) is a usable skeleton.

### 2.2 Audit findings (with evidence)
| # | Finding | Evidence | Impact |
|---|---|---|---|
| D1 | "Recall" is a hardcoded list of 15 `MOCK_PRODUCTS`; the `vector_store` branch is `pass`; no collaborative filtering or popularity logic; ranking tie-breaks with `random.random()` → **non-deterministic** | `python/agents/product_rec_agent.py` | No real recommendation capability; results not reproducible |
| D2 | `feature_store`, `vector_store` and `db` are all `None` (comment: "injected in Phase 2"), and **nothing in the repo injects them**; the `FeatureStore` class exists but is never instantiated; `main.py` never creates a Redis client | `user_profile_agent.py` / `inventory_agent.py` / `main.py` | Redis/Milvus/DB capabilities described in the README are not actually wired |
| D3 | Supervisor Phase 1 calls the recommendation agent with `user_profile=None` (no rerank); Phase 2 **calls the recommendation agent again as a whole** (re-recall + rerank), while the inventory check runs on Phase 1's `raw_products`. The two recalls return different candidate sets → reranked items may be filtered out by inventory; if the result is empty it falls back to the **unfiltered** list → **can recommend out-of-stock items** | `orchestrator/supervisor.py` | Core business-logic defect |
| D4 | `BaseAgent.timeout` is stored but **never applied** (no `asyncio.wait_for`); 2 retries (README says 3 retries, 1/2/4 s); the fallback returns an empty `success=False` result rather than a reasonable default; no circuit breaker | `agents/base_agent.py` | README's "three layers of protection" is not real; one slow LLM call can stall the whole request |
| D5 | A/B: the `config` returned by `assign()` **does not affect any agent's behavior**, only the group name is echoed; `assign_thompson` is never called; state is in-memory only; no linkage from exposure to outcome by request; README says 60/20/20 + `md5(user_id)` but the code is 50/50 + `md5(user_id:experiment_id)`; `graph.py` builds a separate `ABTestEngine` and agent instances, disconnected from `main.py` | `services/ab_test.py`, `orchestrator/graph.py`, `main.py` | Experiments are decorative; README and code disagree |
| D6 | The profile agent **always calls an LLM** to derive RFM/segments even though `FeatureStore` already has a deterministic RFM; the critical path has 3 LLM calls (profile → rerank → copy) that cannot all be parallelized | `user_profile_agent.py`, `feature_store.py` | Contradicts the README's P99 < 2 s; profiles are non-reproducible and costly |
| D7 | Compose: the API uses `sqlite:///` and the MySQL service is unused; the API does not depend on Milvus; the Milvus service has **no `command`** (standalone usually needs `milvus run standalone`; must be verified by actually starting it); no healthchecks; only the Python version is built | `docker-compose.yml` | Infrastructure is for show |
| D8 | Only 1 test file (5 A/B tests); zero tests for agents / Supervisor; `prometheus-client` is a dependency but `MetricsCollector` is pure in-memory; `plan.md` marks Phase 2/3 as completed | `tests/`, `services/metrics.py`, `plan.md` | Completion is overstated |
| D9 | The README / resume template claims "CTR +15%, copy click rate +23%, P99 < 2 s, inventory-alert accuracy 95%+" have **no supporting experiment in the repo** | `README.md`, `plan.md` | **Must never be copied onto a resume** (see §14) |
| D10 | The README badge says MIT but the repository tree has **no LICENSE file**; the copy-compliance word list is the Chinese advertising law, and violations are replaced with `***` (rewriting copy rather than regenerating/dropping it) | repo root, `marketing_copy_agent.py` | Reuse and attribution risk; this project's data is English so the rules need redoing |

### 2.3 Disposition table (Keep / Refactor / Delete / Add)
| Upstream module | Disposition | Notes |
|---|---|---|
| `models/schemas.py` | **Refactor** | Evolve into the Canonical Schema (§5.2); remove Chinese-category coupling |
| `agents/base_agent.py` | **Refactor** | Keep the "template method + fallback" idea; rewrite as `common/resilience`: enforced timeouts, jittered backoff, circuit breaker, bulkhead (FR-S*) |
| `orchestrator/graph.py` | **Refactor → the only orchestrator** | LangGraph is the sole production orchestrator; fix D3; delete `supervisor.py` to avoid two parallel implementations |
| `orchestrator/supervisor.py` | **Delete** | Logic folded into LangGraph |
| `services/ab_test.py` | **Refactor** | Keep hash bucketing; make `config` actually drive behavior; persist exposure/outcome (FR-X*) |
| `services/feature_store.py` | **Refactor + wire up** | Keep the Redis ZSET sliding-window design; use event-time semantics; written by a Kafka consumer (FR-E*) |
| `agents/user_profile_agent.py` | **Rewrite** | Deterministic features first; the LLM is no longer on the critical path (D6) |
| `agents/product_rec_agent.py` | **Rewrite** | Real recall + ranking (FR-R*); `MOCK_PRODUCTS` becomes a test fixture |
| `agents/inventory_agent.py` | **Rewrite** | Backed by Postgres inventory (FR-I*); thresholds / purchase-limit rules configurable |
| `agents/marketing_copy_agent.py` | **Refactor** | Keep segment-based template selection; add fact verification, English compliance rules, caching (FR-M*) |
| `services/metrics.py` | **Delete → redo** | Replace with Prometheus + OTel (FR-B*) |
| `docker-compose.yml` | **Rewrite** | Multiple profiles (§4.6), healthchecks, drop MySQL |
| `java/`, `go/`, interview/resume docs, README interview sections | **Delete** | Non-goals |
| `main.py` | **Refactor** | Split into an `api/` gateway with dependency injection |
| — | **Add** | Data pipeline, RAG, evaluation framework, Outbox/Kafka, idempotency, caching, tracing, benchmarks |

### 2.4 License and attribution
The upstream has no LICENSE file (D10). Policy: **treat the upstream as a reference implementation, not a redistributable codebase**; the new repository starts blank and borrows only structure and a few ideas; `NOTICE` states it was inspired by the upstream and links to it; none of its docs or resume content is copied. If substantial code reuse is ever wanted, first ask for a license clarification in an upstream issue.

---

## 3. Scope Tiers
| Tier | Content | Rule |
|---|---|---|
| **Tier 1 (must, deep)** | The five deep items in §1.6: data pipeline + recommendation evaluation (E1), RAG grounded Q&A (E3, E4), inventory consistency + idempotency (E7), Outbox + Kafka + idempotent consumers, failure injection + resilience (E8) | The project is complete only when all of this meets the Definition of Done |
| **Tier 2 (supporting, lean)** | LangGraph two-flow orchestration, marketing copy, experiment framework (FR-X1–X4), observability (FR-B1–B3), E5 pilot, E6 (V1 vs V2) | Kept small; cut in the order given in §11.3 if the schedule is tight |
| **Deferred (not planned)** | Independent inventory service and separately deployed consumers (V3 / P6), Retailrocket tenant, Thompson simulator (E9, FR-X5), LLM rerank (FR-R4, E2), Dashboard app (FR-B4), Milvus comparison, K8s, gRPC, online learning | Revisit only after all of Tier 1 meets the Definition of Done (ADR-0011) |

---

## 4. System Design

### 4.1 Two request flows
| | Flow R: recommendation flow | Flow Q: shopping Q&A flow |
|---|---|---|
| Entry | `POST /v1/recommendations` | `POST /v1/assistant/query` |
| Nature | **Deterministic workflow**; the LLM is used only for copy (async / cached where possible) | **Genuinely agentic**: intent routing → retrieval → recommendation → inventory check → grounded answer |
| Latency target* | p95 ≤ 300 ms (cached copy; excluding LLM rerank) | p95 ≤ 8 s (including the real LLM) |
| Degradation | §7.2 degradation ladder | Same; **abstain** when retrieval finds no evidence |

\* Targets are **hypotheses** to be calibrated in P8, not commitments.

### 4.2 Agent definitions
An "agent" = a logical capability with a clear input/output contract; its implementation may be LLM-driven or a deterministic service. **Being honest about which ones are really LLM agents** is part of this project's credibility.

| Agent | Implementation type | Responsibilities / tools | Used in flow |
|---|---|---|---|
| Router (Supervisor) | LLM (structured output) + rule-based fallback | Intent classification, constraint extraction (category / price / needs stock), deciding which sub-agents to call | Q |
| Profile | **Deterministic** (Redis features + rule-based segmentation); the LLM may optionally produce a readable summary, never on the critical path | Real-time features, RFM, segmentation | R, Q |
| Recommendation | Deterministic recall + ranking (LLM rerank deferred) | Recall (popularity / co-visit / vector) → filter → rank | R, Q |
| Knowledge (RAG) | LLM (answer synthesis) + retrieval pipeline | Hybrid retrieval, rerank, grounded answers, abstention | Q |
| Inventory | **Deterministic** (Postgres inventory store) | Query, reserve, release on expiry, purchase-limit suggestions | R, Q |
| Marketing Copy | LLM + fact verification + compliance filter | Segment-based template generation; caching | R |

### 4.3 Architecture evolution (every step needs a benchmark comparison)
**Admission conditions for splitting**: split a module only if (a) it has independent scaling / availability / consistency needs, and (b) the benefit of splitting can be quantified in a benchmark.

```
V1  Modular Monolith (end of Phase 4)
  Client → API Gateway (FastAPI)
              └─ LangGraph Orchestrator ── Agents (in-process modules)
                    ├─ Postgres (catalog / inventory / reservations / experiments / outbox / pgvector)
                    └─ Redis (features / cache / idempotency)

V2  + Event-driven (end of Phase 5)
  Postgres.outbox ──(Publisher)──▶ Kafka ──▶ feature-updater ──▶ Redis
                                       ├──▶ exposure/outcome-logger ──▶ Postgres
                                       └──▶ *.dlq (failed events + replay tool)

V3  + Independent deployment (DEFERRED, not in plan; kept for reference)
  Gateway+Orchestrator ──HTTP──▶ Inventory Service (separate process, sole owner of inventory tables)
  Event consumers in their own containers, independently scalable

V4  Hardened (Phases 7–8)
  Idempotency, caching, circuit breaker / bulkhead, end-to-end OTel tracing, load and failure-injection verification
```

### 4.4 Tech stack (defaults; changes need an ADR)
| Layer | Choice | Notes |
|---|---|---|
| Language / deps | Python 3.12, `uv`, `ruff`, `mypy`, `pytest` | |
| Web | FastAPI + Pydantic v2 | |
| Orchestration | LangGraph (version pinned) | |
| DB | PostgreSQL 16 + `pgvector` (ADR-0003); SQLAlchemy 2 (async) + Alembic | Single transactional store; vector search can be combined with SQL filters |
| Cache / features | Redis 7 | ZSET sliding-window features, cache, idempotency keys |
| Messaging | Apache Kafka (KRaft, single node) (ADR-0005); `aiokafka` | |
| Embedding | Local `sentence-transformers`: `BAAI/bge-small-en-v1.5` (verified in P2: MIT, 384 dims; pinned revision, CPU; optional `ml` dependency group; ADR-0012) | Zero API cost, reproducible |
| LLM | A thin in-house abstraction `LLMClient` (FR-O7); default implementation is the native Claude API (`anthropic` SDK / `langchain-anthropic`); Ollama can be swapped in during development; an on-disk prompt→response cache is enabled for evaluation (ADR-0006) | Never commit any key |
| Observability | OpenTelemetry (traces, incl. Kafka header propagation), Prometheus, Grafana, structured logs | |
| Load testing | k6 (constant-arrival-rate) + a home-built stub LLM service | Isolates architecture effects from LLM-provider variance |
| Failure injection | Toxiproxy + `docker stop/pause` | |
| CI | GitHub Actions: lint, types, unit / contract / integration (testcontainers) | CI never calls a real LLM |

### 4.5 Storage responsibilities
| Store | Source of truth for | Not |
|---|---|---|
| Postgres | Item catalog, text chunks + vectors, inventory and reservations, experiment exposures/outcomes, outbox | — |
| Redis | Nothing (everything is rebuildable) | Behavior feature windows, copy cache, idempotency keys, circuit-breaker state |
| Kafka | The event stream (within retention) | Business state |

### 4.6 Target repository layout
```
commerce-agent/
├── SPEC.md  NOTICE  LICENSE  README.md  Makefile  pyproject.toml
├── docs/  adr/  results/  data-card.md  architecture.md
├── deploy/  compose.yml (profiles: core | events | full | obs)  k6/  toxiproxy/
├── src/commerce_agent/
│   ├── common/        config, logging, otel, schemas, resilience/{deadline,retry,breaker,bulkhead}, llm/{client,claude,ollama,fake,cache}
│   ├── data/          download, canonicalize, split, simulate_inventory
│   ├── rec/           recall/{popularity,covisit,embedding}, rank/, eval/
│   ├── rag/           ingest, chunk, retrieve (hybrid), rerank, answer, eval/
│   ├── agents/        router, profile, recommender, knowledge, inventory_client, marketing, single_agent_baseline
│   ├── orchestrator/  state.py, graph_recommend.py, graph_assistant.py
│   ├── experiments/   bucketing, exposure, analysis
│   ├── inventory/     repo, reservations, service_app (library; separate process deferred)
│   ├── events/        envelope, outbox, publisher, consumers/, dlq_tool
│   └── api/           gateway app
├── tests/  unit  contract  integration  property  e2e
└── bench/  stub_llm  scenarios  reports
```

---

## 5. Data

### 5.1 Datasets and roles
| Dataset | Role | Rules |
|---|---|---|
| **Amazon Reviews 2023 (McAuley Lab), one small category** | **Primary dataset**: item title / description / features (RAG, copy, vectors), reviews (RAG evidence), timestamped user–item interactions (recommendation). One dataset supports both Flow R and Flow Q | Category chosen after profiling in P1; selection criteria: after k-core roughly 20k–100k items, ≥ 200k interactions, English; recorded in ADR-0002 and `data-card.md`. **Verify** license and fields at download time |
| **Retailrocket** (Deferred, not in plan) | Real view / addtocart / transaction **event stream**: used for Kafka event replay, load testing and recommendation generalization evaluation | Its item properties are hashed and have no readable text, so it **does not take part in RAG / copy**; it is **not merged** with Amazon and acts as a separate tenant |
| Inventory | **Simulated** (long-tail distribution correlated with popularity; includes restocking and reservation expiry) | Always labeled "simulated" in documents |
| Shopping Q&A test set | Self-built (§8 E3–E5) | Synthetic + a human-verified subset |

> Difference from the earlier informal plan (approved by the owner): Amazon is promoted to primary dataset and Retailrocket is demoted (now deferred, §3). Reason: the two datasets cannot be joined (Retailrocket has no readable item text), while Amazon reviews carry timestamped interactions, so a single dataset lets recommendation, RAG, copy and inventory simulation close the loop on the **same set of items**, which lowers MVP risk significantly. See ADR-0002.

### 5.2 Canonical Schema (Postgres)
```
items(item_id PK, source, title, description, features jsonb, category_path text[],
      price numeric NULL, brand, image_url NULL, created_at)
item_chunks(chunk_id PK, item_id FK, kind enum[title|desc|feature|review], text, tsv tsvector,
            embedding vector(384), meta jsonb)
users(user_id PK, source)
interactions(user_id, item_id, ts timestamptz, type enum[view|cart|purchase|review], value real,
             PRIMARY KEY (user_id,item_id,ts,type))
inventory(item_id PK FK, available int CHECK(available>=0), reserved int CHECK(reserved>=0),
          version bigint, updated_at)                    -- simulated
reservations(reservation_id PK, idem_key UNIQUE, item_id, qty, status enum[held|committed|released|expired],
             expires_at, created_at)
outbox(id PK, aggregate, aggregate_id, type, payload jsonb, created_at, published_at NULL)
experiment_exposures(request_id, experiment_id, group, user_id, ts)
experiment_outcomes(request_id, event_type, value, ts)
```

### 5.3 Filtering and splitting
- k-core filtering (users / items): decided in P1 as the official Video_Games 5-core file used as is (k = 5, no extra filtering); deduplication; the rating → implicit-feedback rule (every review is a positive interaction, rating kept in `value`) is written into the data card.
- **Temporal split**: each user's last interaction is test, the second-to-last is validation, the rest is train (leave-last-out, avoiding future leakage).
- Evaluation uses **full ranking** (rank over all candidate items); sampled-negative metrics are not used (they are biased).

### 5.4 Reproducibility requirements
Download scripts carry versions and checksums; `make data` is idempotent; every random process has a fixed seed; `data-card.md` records source, license, filtering rules, statistics and known biases.

**Review-text rule.** Public reports (`docs/results/`), the README and other published docs cite items by `item_id` only, with paraphrased summaries; they **never** contain verbatim review text. Evaluation sets, human-labeled files and any other file containing review text live in the git-ignored local directory `data/private/`; only aggregates, IDs and checksums are committed (data card §2, §14).

---

## 6. Functional Requirements

> The Acceptance column states how completion is judged. Status: ☐ / ◐ / ☑.

### 6.1 Data (FR-D)
| ID | Requirement | Acceptance | Status |
|---|---|---|---|
| FR-D1 | Download + normalization scripts producing the Canonical Schema | `make data` succeeds idempotently on an empty DB; row counts match the data card | ☑ |
| FR-D2 | k-core + temporal split | Unit test: the split has no temporal leakage | ☑ |
| FR-D3 | Inventory simulator (long tail, restocking, fixed seed) | Two runs with the same seed produce identical output | ☑ |
| FR-D4 | Data card | `docs/data-card.md` is complete | ☑ |

### 6.2 Recommendation (FR-R)
| ID | Requirement | Acceptance | Status |
|---|---|---|---|
| FR-R1 | Recall: global popularity, item-item co-visitation, embedding similarity (content), hybrid (RRF / weighted) | Each route can be toggled independently; same input → same output (deterministic) | ☑ |
| FR-R2 | Filters: already purchased / unavailable / category constraints | Covered by unit tests | ☑ |
| FR-R3 | Ranking: feature-weighted scoring (explainable), diversity re-ranking | `reason_tags` are output with each ranking | ☑ |
| FR-R4 | **Deferred.** LLM rerank (feature flag, off by default) | Not in plan (ADR-0011) | — |
| FR-R5 | Offline evaluation framework: Recall@K, NDCG@K, HitRate@K, Coverage, diversity | Produces the E1 report with bootstrap 95% CIs | ☑ |

### 6.3 RAG (FR-K)
| ID | Requirement | Acceptance | Status |
|---|---|---|---|
| FR-K1 | Ingestion: chunking strategy (title / description / features / reviews as separate kinds), metadata | Chunking is replayable; chunk counts match the data card | ☐ |
| FR-K2 | Hybrid retrieval: Postgres FTS + vectors, RRF fusion, SQL filters on category / price | E3 ablation runs | ☐ |
| FR-K3 | Cross-encoder rerank stage (local model), evaluated as an ablation arm in E3 | E3 reports the gain (or lack of it) and the latency cost versus hybrid-only | ☐ |
| FR-K4 | Grounded answers: claims must carry `citations[chunk_id]`; `abstained=true` when evidence is insufficient | Contract test: 100% abstention on no-evidence queries (on the test set) | ☐ |
| FR-K5 | Evaluation set (≥ 150 questions, ~20% unanswerable) + metrics: Recall@k, MRR, faithfulness, citation precision, abstention correctness | E3, E4 reports | ☐ |
| FR-K6 | **Citation verification**: after generation, check that every cited `chunk_id` was actually retrieved and that each claim is supported by its cited text (overlap check at serving time, judge in evaluation); unsupported claims are removed, or the answer abstains | Unit + contract tests with injected bad citations; E4 reports citation precision with and without verification | ☐ |
| FR-K7 | **Error analysis**: every failed evaluation item is labeled with a failure type (retrieval miss, correct chunk ranked too low, hallucination, wrong abstention, other) | E4 report contains failure-type counts and at least 5 worked examples | ☐ |
| FR-K8 | **Prompt-injection robustness**: retrieved review text is untrusted data (delimited, never treated as instructions); a small adversarial set of reviews containing instructions is part of the evaluation | Test: answers do not follow injected instructions; E4 reports the pass rate | ☐ |

### 6.4 Orchestration (FR-O)
| ID | Requirement | Acceptance | Status |
|---|---|---|---|
| FR-O1 | Two LangGraph graphs, `graph_recommend` and `graph_assistant`, with typed state | Graph-structure snapshot test | ☐ |
| FR-O2 | **Candidate-set consistency**: the inventory filter applies to the **final ranked candidates** (fixes D3) | Property test: the output contains no unavailable items unless explicitly marked with a `stock_unknown` degradation | ☐ |
| FR-O3 | A request-level deadline budget is propagated downward; each node's timeout = min(its own budget, remaining time) | Unit test: with a slow node injected, total time ≤ deadline | ☐ |
| FR-O4 | The degradation ladder (§7.2) can be triggered by config / faults; `degraded[]` in the response lists the reasons | Verified in E8 | ☐ |
| FR-O5 | A single-agent baseline (same LLM + all tools, no Router) coexists with the multi-agent workflow behind one interface | E5 can compare them | ☐ |
| FR-O6 | Router: structured output + rule-based fallback; constraint-extraction accuracy evaluated on a labeled set | Report includes accuracy | ☐ |
| FR-O7 | `LLMClient` abstraction: unified `complete()` / structured-output interface; implementations for Claude, Ollama and Fake; built-in hooks for timeout / retry / circuit breaker, token and cost metering, and an on-disk response cache; business code must not import vendor SDKs directly | Unit test: the three implementations are interchangeable; CI uses only Fake; re-running an evaluation hits the cache with 0 real calls | ☐ |

### 6.5 Inventory (FR-I)
| ID | Requirement | Acceptance | Status |
|---|---|---|---|
| FR-I1 | Query / reserve / commit / release | Contract tests | ☐ |
| FR-I2 | **No oversell**: atomic statement `UPDATE … SET available=available-q, reserved=reserved+q WHERE available>=q`; DB CHECK as a backstop | E7: with N ≫ stock concurrent requests, `available≥0` always holds | ☐ |
| FR-I3 | **Idempotency**: unique constraint on `Idempotency-Key`; a repeated request returns the first result | E7: replaying the same key → the side effect happens once | ☐ |
| FR-I4 | Reservation TTL with an expiry job that reclaims stock | Integration test (injectable clock) | ☐ |
| FR-I5 | State changes emit `inventory.changes` events through the Outbox, in the **same transaction** as the inventory update | Fault test: after a crash, no event is lost or duplicated (at-least-once + consumer idempotency) | ☐ |
| FR-I6 | Read path fail-open (marked `stock_unknown`), reservation path fail-closed | E8 | ☐ |

### 6.6 Marketing copy (FR-M)
| ID | Requirement | Acceptance | Status |
|---|---|---|---|
| FR-M1 | Template chosen by user segment (new / loyal / price-sensitive / churn-risk / default) | Unit test | ☐ |
| FR-M2 | **Fact verification**: prices / quantities / brands / attributes in the copy must appear in the item record; otherwise discard and regenerate once; if it still fails, use the template copy | Unit test: injected hallucinated copy is blocked | ☐ |
| FR-M3 | English compliance rules (absolute claims, unsubstantiated comparatives, medical-efficacy claims, etc.) with a configurable word list; on a hit, regenerate or fall back to the template; **no `***` masking** | Unit test | ☐ |
| FR-M4 | Cache key `(item_id, segment, template_version, model)`; the LLM is not on Flow R's critical path (on a miss, return template copy first and fill the cache asynchronously) | Load test shows Flow R makes no LLM calls | ☐ |

### 6.7 Experiments (FR-X)
| ID | Requirement | Acceptance | Status |
|---|---|---|---|
| FR-X1 | Deterministic hash bucketing, `salt = experiment_id`, configurable weights | Unit test: consistency, distribution; an A/A test shows no significant difference | ☐ |
| FR-X2 | A group's `config` **actually drives behavior** (e.g. `recall: hybrid|popular`, `diversify: on|off`) | Integration test: different groups take different code paths | ☐ |
| FR-X3 | Exposures and outcomes are persisted and linked by `request_id` | Per-group sample sizes can be queried | ☐ |
| FR-X4 | Analysis: two-proportion z-test / bootstrap CI; explicitly states "no conclusion can be drawn" when the sample is too small | The analysis script produces a table | ☐ |
| FR-X5 | **Deferred.** Thompson Sampling in a simulator (E9) | Not in plan (ADR-0011) | — |

### 6.8 Events (FR-E)
| ID | Requirement | Acceptance | Status |
|---|---|---|---|
| FR-E1 | Unified event envelope + schema version (§9.3) | Contract tests | ☐ |
| FR-E2 | Outbox Publisher: polling (or LISTEN/NOTIFY) → Kafka, marking rows as published; nothing is lost across a crash and restart | Integration test | ☐ |
| FR-E3 | **Idempotent** consumers: dedupe by `event_id`; ordering preserved per key | Duplicate-delivery test: state unchanged | ☐ |
| FR-E4 | After N retries, events go to a DLQ (keeping the original message, the error and the attempt count); a replay tool is provided | Fault test | ☐ |
| FR-E5 | Trace context propagates through Kafka headers; one trace spans HTTP → Kafka → consumer | The full chain is visible in Jaeger/Tempo | ☐ |
| FR-E6 | Behavior-event replayer (replays Amazon interactions at configurable speed) | Used by load tests and E6 | ☐ |
| FR-E7 | Consumer-group scale-out: `events.user_behavior.v1` has ≥ 3 partitions and 3 feature-updater instances run concurrently; randomly kill 1 instance to trigger a rebalance | Verify: 0 lost events; events for the same `user_id` stay ordered in its features; 0 side effects from reprocessing; rebalance recovery time recorded | ☐ |

### 6.9 Resilience (FR-S)
| ID | Requirement | Acceptance | Status |
|---|---|---|---|
| FR-S1 | **Enforced** timeouts on every external call (fixes D4) | Static check + unit tests: no bare calls | ☐ |
| FR-S2 | Retries: idempotent operations only; exponential backoff + jitter; bounded by the deadline and a retry budget | Unit test | ☐ |
| FR-S3 | Circuit breakers (one each for LLM, vector search, Redis, inventory store): closed / open / half-open, with visible metrics | E8 | ☐ |
| FR-S4 | Bulkhead: a concurrency cap on LLM calls (semaphore); beyond it, fail fast and take the degraded path | Load test shows no cascade | ☐ |
| FR-S5 | Graceful shutdown: stop consuming → finish in-flight work → commit offsets | Integration test | ☐ |

### 6.10 Observability (FR-B)
| ID | Requirement | Acceptance | Status |
|---|---|---|---|
| FR-B1 | OTel traces: one span per agent / node, with attributes including `degraded` and `cache_hit` | Visualization screenshots go into the report | ☐ |
| FR-B2 | Prometheus: RED metrics, agent success rate / latency, LLM tokens and estimated cost, circuit-breaker state, Kafka lag, DLQ depth | Grafana dashboards | ☐ |
| FR-B3 | Structured logs containing `request_id` and `trace_id` | | ☐ |
| FR-B4 | **Deferred.** Dashboard app; the Grafana panels from FR-B2 cover experiment status, agent health and degradation counts | Not in plan (ADR-0011) | — |

---

## 7. Non-Functional Requirements and Resilience Design

### 7.1 NFRs
| ID | Requirement | Measure | Status |
|---|---|---|---|
| NFR-1 | Reproducibility | Same commit + seed + data version gives identical evaluation results (LLM evaluations use the response cache) | ☐ |
| NFR-2 | Performance targets (hypotheses, calibrated in P8) | Flow R p95 ≤ 300 ms / p99 ≤ 600 ms (stub LLM, specified machine); Flow Q p95 ≤ 8 s (real LLM) | ☐ |
| NFR-3 | Correctness | 0 oversells; 0 lost events; 0 duplicate side effects on duplicate delivery | ☐ |
| NFR-4 | Cost | Before each evaluation run, estimate LLM cost and compare it with the remaining budget, refusing to run if it would exceed it; initial total evaluation budget is USD 30, recalibrated by actual usage before the end of P2 (ADR-0006) | ☐ |
| NFR-5 | Security baseline | Secrets only via environment variables; CORS allow-list; Pydantic validation on inputs; dependency scanning | ☐ |
| NFR-6 | Quality | Unit coverage ≥ 80% for core modules (resilience, inventory, events, experiments); `ruff` / `mypy` pass | ☐ |
| NFR-7 | Documentation | README, `architecture.md`, `data-card.md`, `results/` reports, ≥ 6 ADRs | ☐ |

### 7.2 Degradation ladder (Flow R; read paths fail-open, reservation path fails closed)
| Level | Trigger | Behavior |
|---|---|---|
| L0 | Normal | Features + hybrid recall + inventory filter + cached copy |
| L1 | LLM slow / unavailable | Use cached / template copy |
| L2 | Redis unavailable | Profile falls back to the default segment / latest snapshot; recall switches to popularity + content |
| L3 | Vector search unavailable | Co-visitation + popularity only |
| L4 | Inventory store unavailable | Return results marked `stock_unknown`, give no purchase-limit advice; **reservation requests fail outright** |
| L5 | Multiple dependencies failing at once | In-process popular-items snapshot (static) |

### 7.3 Default timeout budgets (configurable)
Flow R total deadline 1500 ms: profile 50 · recall 150 · inventory 100 · copy cache read 20 (the rest is slack). Flow Q total deadline 20 s: Router 2 s · retrieval 500 ms · answer synthesis 12 s.

---

## 8. Evaluation and Benchmarks (where the project's substance lies)

### 8.1 Experiment list
| ID | Question | Setup | Metrics | Decision rule |
|---|---|---|---|---|
| **E1** | Which recall / ranking approach works? | Amazon temporal split; popularity / co-visit / embedding / hybrid. Main result on all interactions; robustness variant on rating ≥ 4 only (a limitation, see data card) | Recall@10/20, NDCG@10, HitRate, Coverage | Bootstrap 95% CIs. *Hypothesis*: hybrid > popularity; **if not true, report it as is** |
| **E2** | *Deferred* (LLM rerank) | — | — | Not in plan (ADR-0011) |
| **E3** | Which retrieval is best? | Ablation: BM25 / dense / hybrid RRF / hybrid + cross-encoder; chunking strategy (by kind, by size) and top-k | Recall@5/10, MRR, nDCG@10, latency per stage | Pick and explain the default configuration; report where each stage helps and where it does not |
| **E4** | Are answers grounded? | Evaluation set (≥ 150 questions, 20% unanswerable) + adversarial-review set (FR-K8); with and without citation verification (FR-K6) | Claim-level faithfulness (LLM judge, **agreement calibrated on 50 human-labeled items**), citation precision, abstention P/R, injection pass rate, failure-type counts (FR-K7) | Report judge–human agreement and the error taxonomy |
| **E5** (pilot) | Is multi-agent better than single-agent? | 100 constrained shopping questions (category / price / stock / facts); same model, same seed; 2 runs per variant | Constraint satisfaction rate, groundedness, p50/p95 latency, tokens/cost, tool-call error rate | **"Not better" is an allowed conclusion**, with analysis of why (context isolation vs orchestration overhead); the sample is pilot-sized, so report intervals and say plainly what it cannot show |
| **E6** | Benefits and costs of the architecture evolution? | k6 constant arrival rate; stub LLM (fixed latency distribution); V1 vs V2 | p50/p95/p99, max RPS within SLO (p99 ≤ target and errors < 1%), CPU/memory, event→feature freshness lag | Report machine specs and confidence intervals; **include cases where adding events makes things slower** |
| **E7** | Is inventory strongly consistent? | 200–1000 concurrent reserves competing for S = 50; includes same-key replays and mid-flight process crashes | Oversell count, duplicate side-effect count, invariant violations | All must be 0 |
| **E8** | Behavior under failures? | LLM +5 s latency / 500s; Redis kill; Kafka stop; Postgres restart; consumer crash; kill 1 of 3 instances in the consumer group (FR-E7) | Success rate, degradation rate, MTTR, lost events, duplicate side effects | Lost = 0, duplicate side effects = 0; degradation matches §7.2 |
| **E9** | *Deferred* (Thompson simulator) | — | — | Not in plan (ADR-0011) |

### 8.2 Evaluation harness requirements
- One-command runs: `make eval-e1` … `make bench-e6`; output JSON + Markdown reports to `docs/results/<exp>/<commit>/`.
- LLM call cache: `hash(model, prompt, params) → response`, ensuring identical re-runs and saving cost.
- Record: commit, dependency lock, data version, seed, machine specs, number of runs.

### 8.3 Stub LLM
`bench/stub_llm`: an OpenAI-compatible fake service with configurable latency distribution (e.g. lognormal) and error rate. **Architecture benchmarks (E6/E8) use the stub; quality evaluations (E1–E5) use the real LLM**; the two are never mixed.

### 8.4 Result-report rules
One `docs/results/<exp>.md` per experiment: question → method → results (tables + plots) → limitations → conclusion. Negative results are kept as well. Any number in the README or on a resume must be traceable to a report.

---

## 9. Interface and Event Contracts

### 9.1 Public API
```
POST /v1/recommendations
  req : { user_id, scene?, num_items=10, context? }
  resp: { request_id, trace_id,
          items:[{item_id,title,price,score,reason_tags[],stock_status,copy?}],
          experiment:{id,group}, degraded:[], latency_ms }

POST /v1/assistant/query
  req : { user_id?, session_id?, query, constraints? }
  resp: { request_id, trace_id, answer, abstained,
          citations:[{item_id,chunk_id}], items:[...], degraded:[],
          usage:{tokens_in,tokens_out} }

POST /v1/events           -> 202   (batch behavior events, into outbox/Kafka)
POST /v1/experiments/{id}/outcome  (JSON body, not query parameters)
GET  /healthz  /readyz  /metrics
```
Error format: RFC 7807 problem+json.

### 9.2 Inventory interface (library in V1; the HTTP shape is the contract if V3 is ever revived)
```
POST   /v1/inventory/reservations   Header: Idempotency-Key   { item_id, qty, ttl_s }
        201 created | 200 replay (same key) | 409 insufficient_stock
POST   /v1/inventory/reservations/{id}/commit
DELETE /v1/inventory/reservations/{id}      (release)
GET    /v1/inventory/{item_id}
```

### 9.3 Event envelope and topics
```json
{ "event_id":"uuidv7", "type":"user.behavior.v1", "schema_version":1,
  "occurred_at":"2026-11-22T17:00:00Z", "producer":"gateway",
  "key":"user_123", "traceparent":"00-...", "payload":{ ... } }
```
| Topic | Key | Consumer | Semantics |
|---|---|---|---|
| `events.user_behavior.v1` | user_id | feature-updater | Update Redis sliding-window features |
| `inventory.changes.v1` | item_id | cache-invalidator / metrics | Invalidate cache, display |
| `reco.exposures.v1` | request_id | exposure-logger | Persist experiment exposures |
| `*.dlq` | original key | replay tool | Keep the original message + error |

Delivery semantics: **at-least-once**; the effect is achieved through **consumer-side idempotency** (dedupe by `event_id`, Redis SETNX + TTL or a DB unique constraint).

---

## 10. Testing Strategy
| Layer | Content | Tooling |
|---|---|---|
| Unit | Bucketing, RRF, fact verification, compliance, retry / breaker / deadline | pytest |
| Property / concurrency | Inventory invariants (Hypothesis + concurrent driver), no leakage in splits | hypothesis |
| Contract | API schemas, event schemas, LLM output parsing (malformed JSON / hallucinated ids) | pytest + fixed fixtures |
| Integration | Real Postgres / Redis / Kafka containers | testcontainers |
| E2E smoke | Full chain via `make demo` | compose |
| LLM-related | Fake LLM / recorded responses by default; the real LLM only in evaluation jobs | |

CI must run offline (no LLM key needed).

---

## 11. Roadmap

### 11.1 Phases and exit criteria
Person-days are rough estimates (single developer, full-time; rescale to your actual time).

| Phase | Content | Exit criteria | Est. |
|---|---|---|---|
| **P0** Bootstrap & audit follow-through | New repo, CI skeleton, NOTICE/LICENSE, `compose` running Postgres + Redis, commit this SPEC and ADR-0001~0010 | `make up` passes; CI green | 3 |
| **P1** Data pipeline | FR-D*; category selection (ADR-0002); data card | FR-D1~D4 ☑; statistics recorded in the data card | 4 |
| **P2** Recommendation baselines + evaluation | FR-R1~R3, R5; E1 | E1 report produced | 5 |
| **P3** RAG + evaluation (deep) | FR-O7 (LLMClient, the first thing in P3); FR-K1–K8; E3, E4 | E3, E4 reports produced, including error taxonomy and injection results | 8 |
| **P4** Orchestration (modular monolith V1) | FR-O*, FR-I1~I4, FR-M*, FR-X1~X4; API; single-agent baseline; E5 pilot | Both flows work end to end; E5 pilot report | 6 |
| **P5** Event-driven V2 | FR-E1~E5, FR-I5; feature-updater, exposure-logger, DLQ; topics with ≥ 3 partitions and multi-instance consumption | Event-chain trace visible; duplicate-delivery test passes | 4 |
| **P6** Split V3, **DEFERRED** | Not in plan (phase number kept so references stay stable); FR-I6 moves to P7 | — | 0 |
| **P7** Resilience and observability | FR-S*, FR-I6, FR-B1~B3; wrap up caching and idempotency | Unit + integration tests pass; Grafana panels usable | 4 |
| **P8** Benchmarks and failure injection | E6 (V1 vs V2), E7, E8; FR-E6, FR-E7 | Reports complete; E7/E8 criteria met | 4 |
| **P9** Demo / docs | README, architecture, results summary, demo video | All of §1.5 satisfied | 3 |

Total about 41 person-days ≈ 8 weeks (full-time); scale to your actual weekly hours and treat it as optimistic (R9). Ordering constraint: **P4 (a functionally correct V1) must come before P5**, otherwise there is no "before vs after" to compare.

### 11.2 How each phase is run
Before starting, break the phase's FRs into issues; when done, update the requirement status column, add ADRs and archive result reports; any deviation requires changing the spec first.

### 11.3 Cut order (when the schedule is tight, cut from the bottom up)
Already deferred (§3): P6 / V3, Retailrocket, E9, E2 / FR-R4, Dashboard, Milvus. If still behind, cut in this order: 1. the E5 pilot (keep the single-agent baseline interface, FR-O5) → 2. E6 (keep E7 and E8) → 3. the cross-encoder arm (FR-K3) in E3.
**Never cut**: the five deep items in §1.6 (data + E1, RAG E3/E4 including FR-K6–K8, inventory E7, Outbox + Kafka + idempotent consumers, failure injection E8).

---

## 12. Decision Records (ADR index)
| ADR | Decision | Status |
|---|---|---|
| 0001 | Python only; delete Java/Go; LangGraph is the only orchestrator | Accepted |
| 0002 | A single small Amazon category is the primary dataset; Retailrocket is deferred (ADR-0011). The specific category is chosen after profiling in P1 and written back into this ADR | Accepted |
| 0003 | Vector search uses pgvector (isolated behind a `VectorIndex` interface); Milvus only as a deferred comparison (the upstream uses Milvus; pgvector removes one stateful component and can be combined with SQL filters) | Accepted |
| 0004 | Modular monolith first; admission conditions for splitting are in §4.3 | Accepted |
| 0005 | Apache Kafka KRaft single node + `aiokafka` (Redpanda is an acceptable swap) | Accepted |
| 0006 | LLM: native Claude API behind the `LLMClient` abstraction. Division of labor: Haiku 5.5 → Router / marketing copy / dev debugging; Sonnet 5.5 → RAG answer generation; Opus 5.5 → evaluation judge only (a different tier than the model under test). P0–P2 need no LLM; local Ollama may be used for debugging, but **evaluation results count only if produced with Claude**. Initial total evaluation budget USD 30 | Accepted (model split and budget reviewed against actual usage at the end of P2; the owner must bring their own Console account and API key) |
| 0007 | Recommendation / profile are deterministic first; the LLM is not on Flow R's critical path | Accepted |
| 0008 | At-least-once delivery + consumer-side idempotency; the inventory reservation path fails closed | Accepted |
| 0009 | Evaluation: full-ranking metrics, temporal split, LLM response cache | Accepted |
| 0010 | New empty repository `commerce-agent`, **not a fork of the upstream**; borrow ideas only, credit it in `NOTICE`, copy none of its code or docs (the upstream has no LICENSE file, see §2.4). Re-evaluate if the upstream later adds a license | Accepted (confirmed by the owner) |
| 0011 | Depth over breadth: five deep items (§1.6) carry the project, with a Definition of Done that gates every phase. Backend / distributed patterns are the flagship, and RAG is also deep (FR-K6–K8 added, cross-encoder FR-K3 restored as an E3 arm). Deferred: P6 / V3, Retailrocket, E2 / FR-R4, E9 / FR-X5, Dashboard FR-B4. Reduced: E5 to a pilot, E6 to V1 vs V2 | Accepted (owner confirmed) |
| 0012 | Recommendation baselines and the E1 protocol: popularity / co-visitation / content embedding (title, features, description; never reviews) / weighted RRF; explainable feature-weighted ranker + MMR; embeddings in an on-disk cache (no new table in P2); `ml` dependency group; tune on a validation subsample, test once; availability filter off in evaluation | Accepted |

---

## 13. Risks
| # | Risk | Mitigation |
|---|---|---|
| R1 | Scope creep | Tiering + the §11.3 cut order + phase exit criteria |
| R2 | LLM cost / rate limits | Response cache, subsampled evaluation, stub LLM for architecture experiments, budget cap |
| R3 | Data volume slows iteration | Single category + k-core; profile with a 1% sample during development |
| R4 | LLM-judge bias | Calibrate on 50 human-labeled items and report agreement |
| R5 | Offline metrics ≠ online gains | Limit report and resume wording to offline / simulated results |
| R6 | Kafka / multi-container ops take time | Compose profiles; start with a single node; V1 must be stable before P5 |
| R7 | Unclear upstream license | §2.4: new repo, no copying of its docs or large code blocks |
| R8 | Stub LLM differs from the real distribution | Reports state it "isolates architecture factors", and E5 separately gives end-to-end latency with the real LLM |
| R9 | Optimistic estimates | Cut per §11.3; review against exit criteria weekly |

---

## 14. External Wording Rules (README / resume / interviews)
**May be written** (each needs a matching report in `docs/results/`):
- "On the Amazon <category> temporal split, hybrid recall improves NDCG@10 over the popularity baseline from X to Y (95% CI …)"
- "On <machine specs> with a stub LLM, the V2 architecture sustains N RPS at p99 ≤ M ms; inventory concurrency test with K concurrent requests: 0 oversells"
- "Across N failure-injection scenarios: 0 lost events, degradation rate …"
- "Single-agent vs multi-agent comparison: constraint satisfaction … latency … cost … (including negative findings)"

**Review text**: items are cited by `item_id` with a paraphrased summary only; verbatim review text never appears in reports, the README, slides or resume material (§5.4).

**Must not be written**: any online CTR / CVR / GMV improvement; "production-grade"; a P99 not proven by E6; any number from the upstream README.

---

## 15. Changelog
| Date | Version | Change | Author |
|---|---|---|---|
| 2026-11-22 | v0.1 | First draft: integrates the upstream audit and the earlier plan | — |
| 2026-11-22 | v0.2 | ADR-0006 settled: native Claude API + `LLMClient` abstraction (adds FR-O7); model split and USD 30 initial budget; updated §4.4, §4.6, NFR-4, P3 | — |
| 2026-11-22 | v0.3 | Owner approved ADR-0002 / 0003 / 0005; all ADRs Accepted, P0 can start | — |
| 2026-11-22 | v0.4 | Added FR-E7 (consumer-group scale-out and rebalance verification); updated P5, P8, E8; version header set to v0.4 | — |
| 2026-11-22 | v0.5 | Added ADR-0010 (new repository instead of a fork); synced §2.4 with the repo name and license information | — |
| 2026-11-22 | v0.6 | Translated the whole spec into English; fixed ADR references to the four-digit form (ADR-0001 … ADR-0010); no change to requirements or decisions | — |
| 2026-11-23 | v0.7 | ADR-0011 (depth over breadth): added §1.6 deep items and Definition of Done; deferred P6 / V3, Retailrocket, E2 / FR-R4, E9 / FR-X5, FR-B4; reduced E5 (pilot) and E6 (V1 vs V2); added FR-K6–K8 and restored FR-K3 for RAG depth; re-estimated P3 / P4 / P8 / P9 (total ≈ 41 person-days) | — |
| 2026-11-23 | v0.7.1 | Consistency fixes after ADR-0011, no requirement changes: §1.2 narrative no longer mentions an independent inventory service; §1.3 G6 drops the experiment simulator; §2.3 drops Thompson-in-simulator (`services/ab_test.py`) and optional LLM rerank (`agents/product_rec_agent.py`); §4.2 Inventory is a Postgres inventory store; §4.6 layout drops `rerank_llm.py` and `thompson_sim` | — |
| 2026-11-23 | v0.7.2 | P1 decisions recorded (owner approved): category Video_Games (ADR-0002); §5.3 k = 5 using the official 5-core file as is, every review is a positive interaction; §8.1 E1 adds a rating ≥ 4 robustness variant; FR-D1–D4 ☑ | — |
| 2026-11-25 | v0.7.3 | Review-text rule (owner request): public reports and the README cite items by ID with paraphrased summaries, never verbatim review text; files containing review text (evaluation sets, human labels) live in the git-ignored `data/private/` (§5.4, §14, data card §2) | — |
| 2026-11-25 | v0.7.4 | P2 done: FR-R1–R3, FR-R5 ☑; E1 report in `docs/results/e1/`; ADR-0012 added (§12); §4.4 embedding model verified and pinned. No requirement changes | — |

---

## Appendix A: Glossary
- **Outbox**: the business update and the "event to publish" are written to Postgres in the same transaction, and a separate process publishes them to Kafka, so nothing is lost.
- **RRF**: Reciprocal Rank Fusion, a rank-fusion method for hybrid retrieval.
- **k-core**: keep only users and items with at least k interactions.
- **Degraded**: a response produced at some level of the degradation ladder; it must be explicitly marked in the response and in metrics.
- **stub LLM**: a fake LLM service with controllable latency / error rate, used to isolate architecture effects.
