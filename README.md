# commerce-agent

A single-developer portfolio project: a multi-agent e-commerce system built on real public data
(Amazon Reviews 2023, one category). It has two request flows:

- **Flow R** - personalized recommendations; a mostly deterministic workflow.
- **Flow Q** - a shopping assistant with retrieval-augmented answers, citations and abstention.

It starts as a modular monolith and evolves into an event-driven backend (Postgres outbox, Kafka,
idempotent consumers). Every architectural step is meant to be checked with benchmarks,
concurrency tests and failure injection.

**Status:** Phase P0 (bootstrap). Nothing beyond health endpoints is implemented yet, and there are
no results to report. Any number this README states later will link to a report in `docs/results/`.

The design, requirements and roadmap live in [SPEC.md](SPEC.md), which is the single source of
truth. Decisions are recorded in [docs/adr/](docs/adr/).

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (installs Python 3.12 automatically)
- Docker Desktop (or another Docker engine with Compose v2), needed only for `make up`
- GNU make

## Quickstart

```bash
make install   # create .venv from uv.lock
make test      # unit tests; offline, no API keys needed
make lint      # ruff
make typecheck # mypy
make audit     # pip-audit on uv.lock (known CVEs)

make up        # Postgres 16 + pgvector and Redis 7; waits until both are healthy
make down      # stop (data volumes are kept)
```

`make up` creates `.env` from `.env.example` if it does not exist. Never commit `.env`.

Run the API locally (after `make up`):

```bash
uv run uvicorn commerce_agent.api.main:app --reload
curl localhost:8000/healthz   # liveness
curl localhost:8000/readyz    # 200 only if Postgres and Redis are reachable
```

## Repository layout

See SPEC §4.6. In short, application code lives in `src/commerce_agent/`. Tests are in `tests/`,
the compose stack in `deploy/`, benchmarks in `bench/`, and documentation in `docs/`.

## License

MIT; see [LICENSE](LICENSE). Inspired by an upstream prototype; see [NOTICE](NOTICE).
