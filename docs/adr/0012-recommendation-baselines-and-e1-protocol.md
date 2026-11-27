# ADR-0012: Recommendation baselines and the E1 evaluation protocol

- Status: Accepted
- Date: 2026-11-25
- Spec reference: SPEC.md §6.2 (FR-R1–R3, FR-R5), §8.1 (E1), §12

## Context

P2 needs comparable recall/ranking baselines and an evaluation whose numbers can be
defended in a portfolio. ADR-0009 fixes the general method (full ranking, leave-last-out,
bootstrap CIs). Several P2-specific choices were open: which routes, what text the
content embeddings see, where embeddings live, how tuning is kept away from the test
set, and how the simulated inventory interacts with evaluation.

## Decision

1. **Routes.** Popularity (train counts), item-item co-visitation (window over each
   user's chronological sequence, optional cosine normalization, top-200 neighbors per
   item), content embedding (recency-weighted mean of history vectors), and hybrid
   weighted RRF. Each route can be switched off in `RecConfig`; disabled routes are not
   computed.
2. **Determinism.** Items are indexed in sorted `item_id` order; every top-k breaks
   score ties by lower index. No randomness anywhere in recommendation.
3. **Content embeddings** use title, feature bullets, item details and description only.
   **Review text is never embedded**: reviews are dated, so they would leak test-period
   information into item vectors. Model: `BAAI/bge-small-en-v1.5` (MIT, 384 dims),
   pinned to revision `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a`, run on CPU,
   `max_seq_length = 256`, L2-normalized.
4. **Embeddings live in an on-disk cache** (`data/cache/embeddings/`, keyed by
   model identity + SHA-256 of the texts). P2 needs no vector database: E1 scores the
   whole catalog with one matrix product. pgvector behind `VectorIndex` (ADR-0003)
   arrives in P3 with `item_chunks`. No new table is added in P2, so the Canonical
   Schema is unchanged.
5. **Heavy ML dependencies are optional.** `sentence-transformers` and `torch` are in
   the `ml` dependency group, used only by `make eval-e1` (and later P3 ingestion).
   CI and unit tests use a deterministic hashing encoder. On Linux, torch comes from the
   CPU-only index. torch is capped `< 2.12` because 2.12+ ships no macOS 13 wheel (the
   owner's machine). The resulting audit findings (one torch advisory affecting
   `torch.jit.script`, two setuptools packaging advisories via torch's `setuptools<82`
   pin) are listed with reasons in the Makefile's `AUDIT_IGNORE` and removed when the
   cap is lifted.
6. **Ranker.** A weighted sum of five features in [0, 1] (RRF fusion, co-visitation,
   content similarity, popularity, category affinity) over the top 100 hybrid
   candidates. Each score decomposes into contributions, which become `reason_tags`.
   Diversity re-ranking is MMR over embedding cosine similarity.
7. **Tuning vs test.** All choices are made on a seeded 20,000-user subsample of the
   validation targets (history = train). The test set is evaluated once per run with
   the frozen configuration, after refitting on train + valid. MMR lambda rule: the most
   diverse lambda whose validation NDCG@10 is within 2% of the best.
8. **Availability filter is off in evaluation.** Stock is simulated (FR-D3); filtering
   it would delete real held-out items and make metrics depend on a simulation. The
   filter is unit-tested and on by default in serving (unknown stock fails open,
   ADR-0008).
9. **Reporting.** `make eval-e1` writes `results.json` and `report.md` to
   `docs/results/e1/<commit>/` (suffix `-dirty` when code differs from the commit),
   with paired bootstrap CIs against popularity and a rating ≥ 4 robustness variant.

## Consequences

- E1 runs without Postgres; it depends only on `make data` outputs and the model cache.
- Recall@K equals HitRate@K under leave-one-out; both are reported, and the report says
  so.
- A pure route can return fewer than K items (for example co-visitation for users whose
  history has no neighbors); the report counts such users instead of padding silently.
- Tuning grids are small. Larger searches might change the ranking of learned arms;
  the report states this as a limitation.
