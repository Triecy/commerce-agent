# ADR-0001: Python only; LangGraph is the only orchestrator

- Status: Accepted
- Date: 2026-11-22
- Spec reference: SPEC.md §12

## Context

The upstream prototype shipped parallel Python, Java and Go implementations, and two Python orchestrators (a hand-written supervisor and a LangGraph graph) that drifted apart (SPEC §2.2, D3 and D5). Three languages were resume packaging rather than engineering value, and two orchestrators meant two sources of truth for control flow.

## Decision

- The project is implemented in Python 3.12 only. No Java or Go code.
- LangGraph (version pinned in `uv.lock`) is the single orchestrator for both flows (`graph_recommend`, `graph_assistant`). There is no separate supervisor implementation.

## Consequences

- One toolchain (uv, ruff, mypy, pytest) and one dependency lock.
- All orchestration bugs, timeouts and degradation logic live in one place (FR-O1 to FR-O4).
- Python's single-process throughput limits are accepted; the project does not claim high QPS (CLAUDE.md §9). Benchmarks in E6 report what the system actually does.
