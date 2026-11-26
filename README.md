# commerce-agent

A single-developer portfolio project: a multi-agent e-commerce system built on real public data
(Amazon Reviews 2023, one category). It has two request flows:

- **Flow R** - personalized recommendations; a mostly deterministic workflow.
- **Flow Q** - a shopping assistant with retrieval-augmented answers, citations and abstention.

It starts as a modular monolith and evolves into an event-driven backend (Postgres outbox, Kafka,
idempotent consumers). Every architectural step is meant to be checked with benchmarks,
concurrency tests and failure injection.

**Status:** Phase P2 (recommendation baselines and offline evaluation) done. `make data`
loads the Video_Games dataset; `make eval-e1` reproduces experiment E1 (popularity,
co-visitation, content embedding, hybrid RRF, explainable ranker with diversity
re-ranking). Results and their limitations are in [docs/results/e1/](docs/results/e1/).
Every number this README states links to a report in `docs/results/`.

E1 headline (offline, Amazon Video_Games leave-last-out split, full ranking over 25,612
items, 94,762 test users, bootstrap 95% CI): NDCG@10 rises from 0.0127 [0.0122, 0.0132]
for popularity to 0.0529 [0.0518, 0.0541] for the full pipeline (hybrid RRF + ranker +
MMR). The full pipeline also beats the strongest single route, co-visitation, but only
narrowly: ΔNDCG@10 +0.0029 [0.0024, 0.0033]. Details, caveats and negative results:
[E1 report](docs/results/e1/).

The design, requirements and roadmap live in [SPEC.md](SPEC.md), which is the single source of
truth. Decisions are recorded in [docs/adr/](docs/adr/).

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (installs Python 3.12 automatically)
- A Docker engine with Compose v2 (Docker Desktop, or Colima on macOS), needed only for `make up`
- GNU make

## Quickstart

```bash
make install   # create .venv from uv.lock
make test      # unit tests; offline, no API keys needed
make lint      # ruff
make typecheck # mypy
make audit     # pip-audit on uv.lock (known CVEs)

make up        # Postgres 16 + pgvector and Redis 7; waits until both are healthy
make data      # download (pinned, ~0.9 GB), split, simulated inventory, load; idempotent
make test-integration  # migrations and loader against a real Postgres (testcontainers)
make eval-e1   # E1: tune on validation, test once; needs the optional ml group (torch, ~1 GB)
make down      # stop (data volumes are kept)
```

`make up` creates `.env` from `.env.example` if it does not exist. Never commit `.env`.

Run the API locally (after `make up`):

```bash
uv run uvicorn commerce_agent.api.main:app --reload
curl localhost:8000/healthz   # liveness
curl localhost:8000/readyz    # 200 only if Postgres and Redis are reachable
```

## Data

Amazon Reviews 2023, Video_Games category (McAuley Lab). The data is downloaded from the
official source and never redistributed in this repository. No license is stated for the
data; see [docs/data-card.md](docs/data-card.md) for the terms that were checked, the
usage rules this project follows, the statistics and the known biases. Inventory is
**simulated**.

Reports and this README cite items by ID with paraphrased summaries only; they never quote
review text. Files that contain review text (evaluation sets, labels) live in the git-ignored
`data/private/`.

If you use this data, cite: Hou, Li, He, Yan, Chen, McAuley. *Bridging Language and Items
for Retrieval and Recommendation.* arXiv:2403.03952, 2024.

## Repository layout

See SPEC §4.6. In short, application code lives in `src/commerce_agent/`. Tests are in `tests/`,
the compose stack in `deploy/`, benchmarks in `bench/`, and documentation in `docs/`.

## License

MIT; see [LICENSE](LICENSE). Inspired by an upstream prototype; see [NOTICE](NOTICE).
