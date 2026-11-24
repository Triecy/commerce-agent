# P1: Amazon Reviews 2023 category profiling (input to ADR-0002)

## Question

Which single Amazon Reviews 2023 category should be the primary dataset? ADR-0002 and
SPEC §5.1 set the criteria: English; roughly 20k-100k items after k-core; at least 200k
interactions; enough item text for RAG and marketing copy.

## Method

- Inputs: the official McAuley Lab **5-core rating-only benchmark** file and the **raw
  item metadata** file of each candidate category. SHA-256 of every input is recorded in
  [`p1-category-profiling.json`](p1-category-profiling.json) and pinned in
  `src/commerce_agent/data/sources.py`.
- The 5-core files are used only for this comparison. The project pipeline will apply its
  own deduplication and k-core to the raw reviews (FR-D2), so final counts can differ.
- Text statistics cover only items that are in the 5-core set.
- Reproduce (downloads about 570 MB into the git-ignored `data/raw/`):

```bash
make profile-categories
```

## Results

5-core interaction statistics:

| Category | Users | Items | Interactions | Median user history | Top-1% items' share | Rating >= 4 | Date span |
|---|---|---|---|---|---|---|---|
| Video_Games | 94,762 | 25,612 | 814,586 | 6 | 18.6% | 80.4% | 1999-10 to 2023-09 |
| Musical_Instruments | 57,439 | 24,587 | 511,836 | 7 | 18.1% | 85.5% | 2003-05 to 2023-09 |
| Industrial_and_Scientific | 50,985 | 25,848 | 412,947 | 6 | 13.7% | 86.0% | 2001-07 to 2023-08 |

Item text coverage (5-core items):

| Category | Has description | Has features | Has price | Median text length (chars) | Distinct top-2 category paths |
|---|---|---|---|---|---|
| Video_Games | 73.4% | 87.1% | 66.9% | 1,138 | 46 |
| Musical_Instruments | 71.8% | 94.6% | 67.0% | 848 | 30 |
| Industrial_and_Scientific | 57.5% | 92.2% | 74.7% | 991 | 54 |

## Limitations

- These are 5-core counts from the official benchmark files, not from this project's
  pipeline. The pipeline's own k-core choice is made in P1 and recorded in the data card.
- "Has price" means the metadata field is non-empty. About a third of items have no
  price in all three categories, which affects price-constrained questions in Flow Q (E5).
- Text length is a coarse proxy for RAG usefulness; it says nothing about quality.
- Review text volume per item was not profiled here (raw review files are 0.46-0.81 GB).

## Conclusion

All three candidates meet the ADR-0002 size criteria. **Recommendation: Video_Games.** It
has the most interactions and users (more statistical power for E1 confidence intervals),
the longest item text, and natural shopping constraints (platform, edition, price,
accessory compatibility) for the E5 constrained-question set. Musical_Instruments is the
fallback: smaller, but with the best feature coverage. The final decision belongs to the
owner and will be written back into ADR-0002 and `docs/data-card.md`.
