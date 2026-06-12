# clustering — discover taste groups, score restaurants per group

Phase 2b's core upgrade. Instead of one global consensus that casual raters
outvote by volume (the "Taco Bell at 4.2" problem), this package discovers
**taste clusters** from rating patterns alone — no labels, no demographic
questions — and computes a separate consensus per cluster. The ranking layer
then surfaces the most *coherent* cluster's score, so calibration beats
volume.

All cluster state is **derived and disposable**: every run deletes a
cuisine's clusters, assignments, and scores and rebuilds them from the
append-only `rating_events` log. Nothing here is the source of truth.

## pipeline (orchestrated by `discover.recluster_cuisine`)

```
build_rating_matrix      one vector per eligible user (≥ 3 ratings in cuisine);
        ↓                latest rating per restaurant, cuisine-average fill
kmeans                   k = K_INITIAL (4), fixed seed → deterministic
        ↓
plant_trusted_seeds      move trusted sources to the centroid nearest their mean vector
        ↓
persist clusters         coherence + member_count computed on planted membership
        ↓
assign_users             confidence = 1 − d_nearest/d_second (planted users: 1.0)
        ↓
compute_cluster_scores   Bayesian-prior consensus per (cluster, restaurant)
```

## files

| file | in charge of |
|---|---|
| `discover.py` | Rating-matrix construction, the k-means implementation (plain Lloyd's in numpy — a deliberate placeholder for phase-3 matrix factorization, don't over-tune it), and the `recluster_cuisine()` / `recluster_all()` orchestration that runs the whole pipeline above. |
| `assign.py` | Persists `user_cluster_assignments` with a confidence value: 0 when a user sits exactly between two centroids, → 1 as the assigned centroid becomes unambiguous. |
| `coherence.py` | The surfacing criterion. Average pairwise **raw** Pearson r between members' rating vectors (pure numpy, mirrored by viz). High coherence = members genuinely agree; a wrongly-merged cluster nets out ≈ 0 and never surfaces. |
| `consensus.py` | Per-(cluster, restaurant) scores: the same Bayesian-prior formula as ranking, applied within the cluster, members weighted by the credibility fallback chain. Stores every row with ≥ 1 rater; the surfacing gate is ranking's job. |
| `seeds.py` | Plants trusted sources into the **expected calibrated cluster** (nearest centroid to their collective mean vector) before anything persists. A soft prior, not ground truth — next recluster recomputes from scratch, so membership can change. |

## constants

| constant | value | lives in | meaning |
|---|---|---|---|
| `K_INITIAL` | 4 | discover.py | starting k per cuisine |
| `MIN_RATINGS_FOR_VECTOR` | 3 | discover.py | user eligibility for a rating vector |
| `KMEANS_SEED` | 0 | discover.py | deterministic clusters for a given event log |
| `MIN_COHERENCE` | 0.50 | coherence.py | gate: cluster "calibrated enough" to surface (unvalidated guess — tune on real data) |
| `MIN_RATERS_PER_CLUSTER` | 5 | consensus.py | gate: members rating a restaurant before its cluster score can surface |

Key invariant: **surfacing uses coherence, never member_count** — a small
cluster that agrees closely beats a large casual one. Implementation choices
(confidence formula, raw-r coherence, within-cluster prior, planting rule)
are logged in `DECISIONS.md`.
