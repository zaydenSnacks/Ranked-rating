# ranking — the final score a restaurant shows

The read path. Combines everything the other packages produce — credibility
weights, cluster state — into one number per restaurant. This package owns
the *decision of whose opinion gets surfaced*; it computes no credibility and
discovers no clusters itself.

## files

| file | in charge of |
|---|---|
| `ranking.py` | Both scoring paths and the choice between them (see below). |

## the two paths in `restaurant_score()`

**1. Cluster surfacing (phase 2b, preferred).** `surfaced_cluster_score()`
looks at the restaurant's cuisine clusters and surfaces the consensus of the
**highest-coherence** cluster that passes both gates:

- `coherence_score >= MIN_COHERENCE` (0.50) — the cluster genuinely agrees internally
- `rater_count >= MIN_RATERS_PER_CLUSTER` (5) — enough members rated *this* restaurant

Member count is deliberately absent from the decision — a small calibrated
cluster beats a huge casual one. A coherent cluster that never rated the
restaurant doesn't block the next qualifying cluster. Ties break by lower
cluster id for determinism.

**2. Bayesian prior fallback.** When no cluster qualifies (sparse data, new
restaurant, incoherent clusters):

```
final_score = (3.0 × global_avg + Σ rating_i × weight_i) / (3.0 + Σ weight_i)
```

where each rater's weight comes from the credibility fallback chain (phase-2
effective weight if `user_credibility` exists, phase-1 formula otherwise).
`PRIOR_WEIGHT = 3.0` behaves like three phantom ratings at the global
average, so one glowing review can't rocket a restaurant up the rankings.

The `score` CLI command reports which path produced the number
(`source: cluster k1 (coherence 0.78, 6 raters)` vs `source: Bayesian prior
over all raters`).
