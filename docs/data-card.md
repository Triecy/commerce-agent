# Data Card: Amazon Reviews 2023, Video_Games (5-core)

> All numbers below come from [`results/p1-dataset-stats.json`](results/p1-dataset-stats.json)
> (written by `make data`) or [`results/p1-category-profiling.json`](results/p1-category-profiling.json).
> Inventory data is **simulated** and is labeled as such everywhere.

## 1. Source and version

- Dataset: **Amazon Reviews 2023** (McAuley Lab, UC San Diego), category **Video_Games**.
- Project page: <https://amazon-reviews-2023.github.io/>. Mirror used for downloads:
  <https://mcauleylab.ucsd.edu/public_datasets/data/amazon_2023/>.
- Paper: Hou, Li, He, Yan, Chen, McAuley. *Bridging Language and Items for Retrieval and
  Recommendation.* arXiv:2403.03952, 2024.
- Files (pinned in `src/commerce_agent/data/sources.py`, verified by SHA-256 on every run):

| File | Role | Bytes | SHA-256 |
|---|---|---|---|
| `benchmark/5core/rating_only/Video_Games.csv.gz` | Interactions (user, item, rating, timestamp) | 12,801,967 | `a2bde5f3…c6901c` |
| `raw/meta_categories/meta_Video_Games.jsonl.gz` | Item metadata | 103,096,082 | `ced9696b…5fc1fc9` |
| `raw/review_categories/Video_Games.jsonl.gz` | Review text (used from P3) | 814,206,092 | `52d8762c…44bc193` |

The server reported `Last-Modified: Fri, 17 Jan 2025` for the review file at download
time (2026-11-23). Full checksums are in the stats JSON.

## 2. License and terms of use

Checked on 2026-11-23 before the review file was downloaded.

- **No license or terms of use is stated for the data** on any official page:
  - <https://amazon-reviews-2023.github.io/>: the only rights-related line is the footer,
    quoted: *"Copyright © 2024, McAuley Lab"*. The contact line reads: *"For research
    collaborations or other questions, please email yphou AT ucsd.edu."*
  - <https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023>: the dataset card has
    no `license:` field (the Hugging Face API returns `cardData.license = None`) and no
    license section.
  - <https://mcauleylab.ucsd.edu/public_datasets/data/amazon_2023/>: the directory has no
    LICENSE, README or terms file.
  - <https://github.com/hyp1231/AmazonReviews2023> is MIT-licensed, but that repository
    holds processing **code**; it does not say the MIT license covers the data.
- The only attribution guidance is a request to cite the paper above.
- The reviews themselves are user-generated content published on Amazon.

**What this means for this project:**

- Nothing found restricts research or portfolio use, which is the dataset's stated
  purpose. Equally, no explicit license grants rights, so the project takes the
  conservative position:
  - The data is **never redistributed**. Scripts download it from the official source;
    `data/` is git-ignored. Result reports contain aggregates only.
  - **Review text is never quoted in public material.** Result reports, the README and
    other published docs cite items by `item_id` only, with a paraphrased summary written
    by the project (for example "several reviewers say the controller drifts"). They never
    contain verbatim review text, not even short excerpts (SPEC §14).
  - Evaluation sets, human-labeled files and any other file that contains review text
    live in the git-ignored local directory `data/private/` (covered by the `/data/`
    rule in `.gitignore`). Only their aggregates, IDs and checksums are committed.
  - **No commercial use.** The paper is cited in the README and in every report that uses
    the data.
- If the authors publish a license later, re-check this section.

## 3. Category selection (ADR-0002)

**Video_Games**, chosen by the owner in P1 from three profiled candidates
([`results/p1-category-profiling.md`](results/p1-category-profiling.md)). It has the most
interactions and users of the three (more statistical power for E1), the longest item
text, and natural shopping constraints (platform, edition, price, accessory
compatibility) for E5.

## 4. Fields used and canonical schema mapping

| Canonical column (SPEC §5.2) | Source field | Rule |
|---|---|---|
| `items.item_id` | `parent_asin` | Variants are grouped under the parent ASIN, as in the 5-core file |
| `items.source` | constant | `amazon2023/Video_Games` |
| `items.title` | `title` | Trimmed; 1 item has an empty title |
| `items.description` | `description[]` | Non-empty parts joined with newlines |
| `items.features` (jsonb) | `features[]`, `details{}`, `main_category` | `{"bullets": [...], "details": {...}, "main_category": ...}` |
| `items.category_path` | `categories[]` | As given; empty for 3.4% of items |
| `items.price` | `price` | Float or numeric string to 2 decimals; otherwise NULL |
| `items.brand` | `details.Brand`, else `store` | NULL if both are missing |
| `items.image_url` | first `images[].large` (https) | |
| `users.user_id` | `user_id` | |
| `interactions` | 5-core CSV | `type = 'review'`, `value = rating`, `ts` from milliseconds (UTC) |
| `inventory` | simulated (section 9) | |

**Dropped on purpose (temporal leakage):** `average_rating`, `rating_number`,
`details["Best Sellers Rank"]` and `details["Customer Reviews"]` aggregate over all
reviews, including the test period, so they must not be available as features.
`details["Pricing"]` is dropped because it is boilerplate text.

## 5. Filtering rules

Owner decisions (P1):

- **k-core:** the official 5-core file is used **as is** (k = 5 for users and items, no
  extra filtering). `make data` checks that it is a 5-core fixed point and fails if not.
- **Deduplication:** none needed. The file has no duplicate (user, item, timestamp) rows
  and no repeated (user, item) pairs.
- **Implicit feedback:** every review is a **positive interaction**, whatever its star
  rating; the rating is kept in `interactions.value`.
  - E1's main result uses all interactions.
  - E1 adds a **robustness variant that keeps only rating >= 4** (80.4% of interactions).
    The exact protocol is fixed in the E1 report (P2).

## 6. Temporal split (leave-last-out)

- Per user, sorted by time: last interaction is **test**, second-to-last is **valid**,
  the rest is **train** (SPEC §5.3). Users with fewer than 3 interactions would go to train
  only; after 5-core there are none.
- Ties: 61 (user, timestamp) groups have more than one review. Ties are broken by
  `item_id`, never randomly (`commerce_agent.data.split`).
- Output: `data/processed/video_games/{train,valid,test}.csv.gz`, byte-stable across runs
  (checksums in the stats JSON).
- **Limitation:** the split is per user, not global. A train interaction of one user can be
  later in calendar time than another user's test interaction, so popularity trends from
  the "future" are visible in training. This is the standard leave-last-out trade-off.

## 7. Statistics

| | Value |
|---|---|
| Users | 94,762 |
| Items | 25,612 |
| Interactions | 814,586 |
| Density | 0.000336 |
| Interactions per user (median / p90 / max) | 6 / 14 / 473 |
| Interactions per item (median / p90 / max) | 12 / 64 / 2,955 |
| Date range | 1999-10-22 to 2023-09-02 |
| Split (train / valid / test) | 625,062 / 94,762 / 94,762 |

Ratings:

| 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|
| 52,563 | 36,809 | 70,347 | 134,800 | 520,067 |

Item text coverage: description 73.4%, feature bullets 87.1%, price 66.9%, brand 99.5%,
category path 96.6%, image URL 100%.

## 8. Review text (input to P3)

- The raw review file has 3,955,684 reviews for the 25,612 items. That is far more than the
  5-core interactions, because it includes reviews by users outside the 5-core set.
- Reviews per item: median 50, p90 319, p99 1,780, max 18,105.
- Review length in characters: median 130, p90 716, p99 3,112. 0.07% have empty text.
- 829,104 reviews match a 5-core (user, item) pair, more than the 814,586 interactions.
  Some users reviewed the same item more than once, and the 5-core file keeps one row per
  pair.
- **P3 will cap the number of reviews per item that get embedded.** Without a cap, a few
  head items would dominate the index and the embedding cost (the top 1% of items have at
  least 1,780 reviews each). The cap value and the selection rule (for example, most
  helpful votes with a recency tie-break) are chosen and justified in P3. The selection
  must be deterministic, and it must be recorded in this card.

## 9. Simulated inventory

**SIMULATED.** Amazon data has no stock levels. `commerce_agent.data.simulate_inventory`
generates them, seed `20261122`:

- Base stock grows with **train-split popularity** (`500 * share^0.5`), so test
  interactions never shape it. Lognormal noise (sigma 0.6) adds a long tail.
- 5% of items start out of stock (actual: 5.24%, 1,343 items).
- Available units: median 34, p90 103, max 2,101. The top 10% of items hold 35.8% of units.
- Restock rule per item: every 3 to 30 days, faster for popular items. Because the speed
  scales with popularity relative to the single most popular item, most items (median)
  restock every 30 days.
- Loaded into `inventory` (`reserved = 0`, `version = 0`; the table comment says
  SIMULATED). Restock rules are in `data/processed/video_games/inventory_simulated.csv.gz`;
  the restock job that applies them belongs to P4.

## 10. Known biases and limitations

- **Reviews are a proxy for purchases.** Only users who wrote reviews appear, and the
  5-core filter keeps active reviewers and popular items. Offline metrics therefore
  describe "who reviews what", not purchase behavior.
- **Positive skew.** 80.4% of ratings are 4 or 5. Treating every review as positive also
  counts 1- and 2-star reviews (11.0%) as positive signals. The rating >= 4 robustness
  variant in E1 measures how much this matters.
- **Off-category items.** Only 70.0% of items have `main_category = "Video Games"`. The rest
  are mostly computers (3,263), electronics (2,645) and phone accessories (414), plus a few
  books and toys. 514 items have no main category.
- **Category tree.** "Legacy Systems" (11,708 items) is the largest level-2 category, so
  older platforms dominate. Current consoles (PlayStation 5: 292, Xbox Series X & S: 135)
  are a small share.
- **Missing prices.** One third of items have no price, which limits price-constrained
  questions in Flow Q (E5).
- **Popularity concentration.** The top 1% of items receive 18.6% of interactions.
- **Long time span.** Items from 1999 to 2023 share one catalog; there is no notion of an
  item being unavailable for sale at a given time beyond the simulated stock.

## 11. Reproducibility

```bash
make up      # Postgres + Redis
make data    # migrate, download (pinned), split, simulate inventory, load; idempotent
```

- Every download is verified against its pinned SHA-256; a mismatch stops the run.
- Running `make data` twice inserts nothing the second time and rewrites byte-identical
  outputs and statistics (verified on 2026-11-23).
- The run fails if row counts differ from this card: users 94,762, items 25,612,
  interactions 814,586, inventory 25,612.
- To rebuild from scratch: `make data-reset` (drops the P1 tables).

## 12. Decisions, alternatives and what did not work (P1)

- **Own k-core on raw reviews instead of the official 5-core file.** Considered, because it
  would allow other k values. Rejected by the owner: the official file is a published,
  checksummed benchmark that other work can compare against, and it already meets the
  ADR-0002 size criteria.
- **Leaky metadata found during inspection.** The first draft of the item mapping kept all
  metadata. Inspection showed that `average_rating`, `rating_number` and
  `Best Sellers Rank` are snapshot aggregates that include the test period, so they were
  removed (section 4). A loader test and a database query confirm that no item carries them.
- **Inventory popularity from all interactions.** Rejected in favor of train-split
  popularity, so the simulated stock of an item does not encode its test interactions.
- **Fixed schema check.** The loader first failed with a raw database error on a
  never-migrated database. It now checks the Alembic revision and stops with a clear
  "run `make migrate`" message (integration test).
- **Restock rules are not in the database.** The SPEC §5.2 `inventory` table has no restock
  columns, so the simulated rules live in a processed file. Whether to add a table is
  decided in P4 together with the restock job, through a spec change.
