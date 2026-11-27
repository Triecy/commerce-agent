- **Cosine-normalized co-visitation.** Expected to help by damping popular items; it was
  worse in every validation cell (NDCG@10 0.034-0.043 vs 0.045-0.053 for raw counts).
  On this 5-core data, popular neighbors are usually the right answer. Raw counts are kept.
- **Popularity as an RRF route.** Every non-zero popularity weight lowered validation
  NDCG@10 (best with weight 0: 0.0543; 0.25: 0.0532; 0.5: 0.0505). The tuned hybrid
  fuses co-visitation and content only. Popularity still enters as a weak ranker feature
  (weight 0.25).
- **Heavier content weight in RRF.** Embedding weights 1.0 and 2.0 were worse than 0.5.
  On its own the content route is weak: NDCG@10 0.0167 vs 0.0127 for popularity on test,
  and in the rating >= 4 variant its Recall@10 gain over popularity is not significant.
- **Long content profiles.** A mean over the last 20 items without decay was the worst
  embedding setting (0.0121). Strong recency (decay 0.5) helps, and then 5 vs 20 items
  makes no difference: users' next item resembles their last one or two, not their
  history.
- **MMR diversity.** The gain is small. On validation, lambda 0.5 raises ILD@10 from 0.309
  to 0.334 for about 0.5% NDCG@10. On test, the MMR arm is slightly below the
  non-diversified ranker on NDCG@10 (0.0529 vs 0.0533; the intervals overlap) and
  recovers about half of the category diversity the ranker loses (0.415 -> 0.465, vs
  0.500 for plain RRF).
- **Reason tags are skewed by weights.** With the tuned content weight of 2.0,
  `similar_content` is 71% of all tags, while `co_visited_with_history` is under 1%, even
  though co-visitation drives most of the candidates. Tags explain the *score
  decomposition*; they are not causal evidence. Normalizing contributions per feature
  before tagging is a possible fix and was not tried.
- **Environment.** The newest torch (2.12+) has no macOS 13 wheel. torch is capped
  at < 2.12, which brings three accepted audit findings (ADR-0012).
