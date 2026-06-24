# credence — decisions log

## tech stack

**Language: Python**
Go or Rust would win on Phase 3 latency, but Phase 2 requires ML work (sklearn, torch, or Anthropic APIs). Python avoids a rewrite between phases. The Phase 3 inference path can be optimized independently without switching languages.

**Database: SQLite (via SQLAlchemy)**
Zero setup, single file, trivially inspectable. SQLAlchemy ORM means the migration to Postgres for Phase 2/3 is a one-line change to the connection string plus a driver swap. No concurrent write requirements for Phase 1.

**CLI: Typer**
Auto-generates help text from type hints. Much cleaner than argparse for a CLI that will grow over time.

**Math: NumPy**
Pearson correlation via NumPy (no scipy dependency). Keeps the dependency surface small.

**Output: Rich**
Tables and colors in the terminal without manual ANSI codes.

---

## naming: `cuisine-graph` → `cuisine_graph`
The spec uses hyphens in directory names. Python package imports require valid identifiers — hyphens are illegal. Directory is named `cuisine_graph` (underscores). Conceptual name unchanged.

---

## Pearson handling in alignment
*(rewritten 2026-06 — the original entry described an `(r + 1) / 2` remap with a 2-restaurant minimum, which is not what shipped)*

`alignment_score()` returns **raw Pearson r ∈ [−1, 1]**; the credibility formula uses it directly and relies on the final `clamp(…, 0, 1)`. Negative correlation therefore actively drags the whole weighted sum down — an anti-correlated rater can lose the credit earned by expertise and proximity, which is harsher (and more deserved) than the 0 an `(r + 1) / 2` remap would have given them. Uncorrelated raters get 0 alignment, not 0.5.

Minimum overlap is **3 restaurants** (`MIN_OVERLAP`), not 2; below it the function returns `(0.0, sufficient_overlap=False)` and the caller redistributes α's weight across expertise and proximity rather than treating 0 as a measured correlation.

---

## proximity normalization
The raw proximity sum `Σ expertise(j) * (1 - distance(C, j))` can exceed 1 if there are many neighbors. Normalized by dividing by `Σ (1 - distance(C, j))` for all j within threshold — i.e., the maximum possible score if the user had full expertise in every adjacent cuisine. Result ∈ [0, 1]. Returns 0 if no neighbors within threshold.

---

## cuisine distance encoding
Distances stored symmetrically in `cuisine_distances` (both (a,b) and (b,a) rows). Simpler queries, small table. Can switch to a half-matrix + lookup if the cuisine count grows significantly.

---

## rating_events as immutable log
No updates or deletes. Each rating is a timestamped event. Credibility and ranking are always computed from the full event log. This preserves the audit trail and makes Phase 2 feature extraction straightforward — you can replay history.

---

## phase 2b clustering tables (names, keys, indexes)
Three tables, mirroring the SPEC design:

- **`clusters`** — `id, cuisine_id, label, coherence_score, member_count, created_at`. Synthetic PK because clusters are recreated on every re-clustering run and per-cuisine cluster counts vary. `label` is nullable and diagnostic-only — the system discovers groups from rating patterns and never consumes archetype names. `coherence_score` defaults to 0.0 so `discover.py` can insert rows before `coherence.py` fills them in. Index on `cuisine_id` (ranking fetches all clusters for one cuisine, sorted by coherence).
- **`user_cluster_assignments`** — natural PK `(user_id, cuisine_id)`: a user belongs to at most one cluster per cuisine, and re-clustering upserts the row. `confidence` ∈ [0, 1] from assignment distance. Index on `cluster_id` for member listing and `member_count` recomputation.
- **`cluster_restaurant_scores`** — natural PK `(cluster_id, restaurant_id)`, upserted by `consensus.py`. Index on `restaurant_id` because the ranking read path asks "give me every cluster's score for restaurant R" and then picks the highest-coherence one.

Timestamps stay ISO text like every other table (one consistent convention; the lot converts to TIMESTAMPTZ together in the phase 3 Postgres migration). Re-clustering replaces cluster rows rather than versioning them — `rating_events` is the replayable record; cluster state is derived and disposable.

---

## yelp importer scope

**Category mapping: existing 5 cuisines only.** `CATEGORY_MAP` in `yelp.py` maps Yelp categories (Chinese/Cantonese/Dim Sum, Italian/Pizza, Japanese/Ramen/Sushi Bars, Korean, American (Traditional)/(New)/Diners) onto the seed cuisines. The importer never creates cuisines, because each new cuisine would need hand-authored `cuisine_distances` rows. Compromise: plain Korean restaurants map to "Korean Fusion" — taxonomically loose, but it gives that cuisine volume; revisit when the cuisine graph is learned (phase 3+). Businesses matching categories for **more than one** cuisine are skipped — multi-cuisine restaurants are an open SPEC question; better to exclude than to mislabel training data for clustering.

**Stars → score: affine map [1,5] → [1,10].** `score = 1 + (stars − 1) × 2.25`, so 1★→1.0 and 5★→10.0 (both endpoints reachable). The naive `stars × 2` can never produce a score below 2.

**Raw events only — no credibility updates during import.** The importer inserts `rating_events` directly instead of going through `submit_rating()`. Running millions of events through the Glicko path would be slow and would interleave with import order; credibility and clusters are derived state, recomputed from the event log afterwards (this is what append-only buys us).

**One-shot import.** `rating_events` has no natural key for Yelp reviews, so a re-run would silently duplicate events. Rather than half-hearted idempotency, the importer refuses to run if Yelp users (detected by the `@import.yelp` email domain) already exist. Real external-ID tracking can come with the phase 3 Postgres migration if needed.

**Sparse users dropped at import.** Users with fewer than `min_user_reviews` (default 3 = `MIN_RATINGS_FOR_VECTOR`) qualifying reviews are not imported — they could never get a rating vector, so they'd only bloat the users table. Two streaming passes over the review file (count, then insert) keep memory at one small dict; the NDJSON files are too large to load whole.

**Known accepted noise: category misrepresentation (revisit before tuning MIN_COHERENCE).** Yelp's `categories` field is flat with no "primary" marker, so a venue whose identity isn't a restaurant can still import cleanly if it carries exactly one mapped cuisine tag. Measured on the Philadelphia import (2026-06): Reading Terminal Market — an 80-stall food hall with a Dim Sum tag — imported as Chinese and holds **10.8% of all Chinese-cuisine ratings** (3,043 of 28,137); the Philadelphia Museum of Art imported as American via its café. Every other cuisine's top venue is legitimate (Bonchon, Terakawa Ramen, Barbuzzo, Parc), so the distortion is concentrated in roughly one venue.

Why accepted for now: restaurant-level scores stay honest (the score measures the venue; only its cuisine shelf is wrong); rating-vector dilution from one noisy column among 382 Chinese restaurants degrades clustering gracefully; and phase 3 matrix factorization learns from co-rating patterns, not category labels, shrinking the blast radius. Effects that DO accumulate: cuisine leaderboards (food hall tops "best Chinese"), modest expertise/alignment inflation, and downward pressure on Chinese-cluster coherence.

Revisit triggers — do the fix when any of these arrive: (1) before empirically tuning `MIN_COHERENCE`, since 10.8% label noise in Chinese could skew the threshold; (2) before phase 3 ships cuisine leaderboards; (3) if Chinese clusters look degenerate vs other cuisines. The fix is a category blocklist in the importer (skip businesses also tagged `Public Markets`, `Museums`, `Grocery`, `Food Court`, etc.) — ~10 lines, but requires a fresh import and cluster rebuild since the importer is one-shot.

**Category blocklist implemented (2026-06-19, code only — re-import pending).** `yelp.py` now carries `NON_RESTAURANT_CATEGORIES` (`Public Markets`, `Food Court`, `Museums`, `Grocery`, `Farmers Market`, `Convenience Stores`, `Department Stores`, `Wholesale Stores`, `Shopping Centers`, `Stadiums & Arenas`, `Gas Stations`). `_map_cuisine` skips any business also tagged with one of these (reason `blocklisted_venue`, counted in stats), checked *after* the single-cuisine test so the counter reflects venues that would otherwise have imported. Conservative on purpose — only venue types whose identity clearly isn't a restaurant; `Food Trucks`/`Caterers` are left in as legitimately restaurant-like. Note this catches Reading Terminal Market and the museum café but **not** in-market vendor stalls listed as their own business (e.g. "Meltkraft At Reading Terminal Market", 210 ratings) when they don't themselves carry a blocklisted tag — accepted; the bulk of the noise is the umbrella venue. The code+test ship now; the actual fresh import + recluster (which this enables) is a separate, heavier step because the importer is one-shot.

---

## clustering implementation choices

**Hand-rolled k-means (numpy), fixed seed.** No sklearn dependency for an algorithm that phase 3 deletes — plain Lloyd's in ~25 lines, `seed=0` so clusters are deterministic for a given event log (re-runs and tests reproduce exactly). Empty clusters are reseeded with the farthest point. k is capped at the user count.

**Rating vectors: latest rating wins, cuisine-average fill.** A user's vector takes their most recent rating per restaurant (append-only log → latest = current opinion). Missing entries fill with the cuisine average per `MISSING_VALUE_FILL` — a neutral value that neither inflates nor deflates correlation against other members.

**Assignment confidence: `1 − d_nearest/d_second_nearest`.** 0 when a user sits exactly between two centroids, → 1 when the assigned centroid is far closer than any alternative. Planted trusted sources get confidence 1.0 outright — their placement is a prior, not a distance measurement.

**Coherence: average pairwise raw Pearson r (not remapped).** Anti-correlated members should drag coherence negative rather than land at 0.25 the way alignment's `(r+1)/2` remap would; `MIN_COHERENCE = 0.50` then reads as "members genuinely agree". Zero-variance vectors produce NaN pairs which contribute 0 (no signal ≠ agreement). Singleton clusters score 0.

**Consensus: ranking's Bayesian prior, applied within the cluster.** Same formula and `PRIOR_WEIGHT = 3.0` as `ranking.restaurant_score()`, with member ratings weighted by the same effective-weight fallback chain. The constant and the 4-line weight helper are duplicated in `consensus.py` rather than imported from `ranking.py`, because ranking will import consensus in build step 5 — importing both ways would be circular. Rows are stored for every (cluster, restaurant) with ≥ 1 rater; the `MIN_RATERS_PER_CLUSTER` surfacing threshold belongs to the ranking layer.

**Seed planting: nearest centroid to the trusted sources' mean vector.** The "expected calibrated cluster" is wherever the trusted palate collectively points. Planting rewrites this run's labels before anything persists (so coherence, member_count, and consensus all see the planted membership) and is recomputed from scratch each run — membership can change, per the invariant.

**Re-clustering deletes and rebuilds.** `recluster_cuisine()` clears the cuisine's clusters, assignments, and scores first, even when the cuisine turns out too sparse to recluster — stale clusters are worse than none.

---

## cluster-relative alignment (phase 2 step 4)

`cluster_alignment_score()` correlates the user's latest ratings against their own cluster's stored consensus instead of the trusted-source average. The phase-1 `alignment_score()` is untouched and serves as the fallback, triggered when the user has no cluster assignment or fewer than `MIN_OVERLAP` restaurants overlap with usable consensus rows. `credibility_score()` now calls the cluster version; the fallback chain bottoms out in the existing weight-redistribution path.

**Cluster surfacing (step 5): among qualifying clusters, highest coherence wins.** The SPEC pseudocode reads as "the highest-coherence cluster with >= MIN_RATERS for this restaurant" — implemented as: filter the cuisine's clusters to those passing both gates (`coherence_score >= MIN_COHERENCE` and a score row with `rater_count >= MIN_RATERS_PER_CLUSTER` for this restaurant), surface the most coherent, ties broken by lower cluster id for determinism. A very coherent cluster that simply never rated the restaurant doesn't block a qualifying second cluster — falling back to the global Bayesian average when usable cluster signal exists would reintroduce exactly the volume-wins failure mode. When no cluster qualifies, `restaurant_score()` continues into the unchanged Bayesian-prior path, and the `score` CLI prints which source produced the number.

**Self-correlation guard: `MIN_CONSENSUS_RATERS = 2`.** A user's own rating is baked into their cluster's consensus, so against a 1-rater consensus row they would mostly be correlating with themselves — those rows are excluded from the comparison set. Residual self-influence remains in multi-rater rows (the user is one of N raters, further dampened by the Bayesian prior); proper leave-one-out consensus is deferred until there's evidence it matters at real data volume.

---

## seed.sql rescaled to the 1–10 scale
The seed ratings were authored on a 5-star scale (3.5–5.0) while the system math assumes 1–10 (`SCORE_RANGE = 9.0`, CLI help, Bayesian prior). Left alone, the trusted-source seeds would read as harsh outliers ("8.875 means excellent" vs "4.5 means below average") once Yelp data lands at full range — and they anchor the calibrated cluster, so their absolute level matters. Converted with the **same affine map the importer uses** (`1 + (stars − 1) × 2.25`) so seed and Yelp data share one conversion story. Pearson alignment is affine-invariant, but the absolute deltas in `dynamic.py` (agreement threshold) and consensus distances are not — one map everywhere avoids a systematic offset between cohorts.

---

## first full-scale clustering run — findings (Philadelphia import, 2026-06-14)

First `cluster` run over real volume (24,644 eligible users across 5 cuisines, 230,143 rating events). Mechanically clean — deterministic, single transaction, validation pairs ordered correctly (Domino's 3.98 vs Vetri Cucina 9.10; Applebee's 4.42 vs Middle Child 9.06). Two problems surfaced. They are coupled: the perf fix is the prerequisite for iterating on the coherence fix.

### finding 1 — clustering takes ~1.5 h (performance, fix decided below)
Wall time 1h29m. Root cause is an **N+1 query over an unindexed table**, two factors multiplying:
- `consensus.compute_cluster_scores()` calls `_rater_weight()` once per **(cluster member × restaurant they rated)** — ~90,500 calls for Philadelphia. The weight depends only on `(user_id, cuisine_id)`, so this recomputes the same value many times (a user is recomputed once per restaurant they rated).
- Each `credibility_score()` call fires ~6–7 SQL queries (alignment, expertise, one proximity count per adjacent cuisine), and `rating_events` has **only its primary key — no secondary indexes**. So every query full-scans 230k rows. Measured: **~29 ms/call → ~45 min in consensus alone**, plus coherence matrices and ~25k ORM assignment-row flushes.

This is the `_community_consensus` N+1 noted in CLAUDE.md known gaps since phase 1 ("acceptable at phase 1 scale") finally coming due — except the hot path at scale is `consensus.py`, not `dynamic.py`. Note also: during a rebuild, `cluster_alignment_score` always misses (consensus rows don't exist yet) and falls through to the phase-1 path, so the most expensive query path runs precisely when it can't yet produce a cluster-relative answer.

### finding 2 — coherence measures sparsity, not disagreement (RESOLVED — see "coherence redefinition" below)
Only **one** cluster in the entire system passed `MIN_COHERENCE = 0.50` (Japanese k0: 7 members, coherence 0.623 — a genuine sushi-regular group that correctly surfaced 3 sushi spots at 8.5–8.7). Every large cluster scored ≈ 0 (American k0: 0.003, Italian k1: 0.004), so **cluster surfacing never fired** — every validation score came from the Bayesian fallback.

Cause: in the 13,772-member American k0, **88.6% of sampled member pairs share zero co-rated restaurants** (mean overlap 0.14). The current coherence metric correlates full, fill-imputed rating vectors; two members who never co-rated correlate at ≈ 0 regardless of whether they'd agree. So coherence currently measures **co-rating density, not taste agreement**, and at 2,771 restaurants with ~4 ratings/user that density is near-zero for everyone. Lowering `MIN_COHERENCE` is the wrong fix — it would just surface the biggest blob, i.e. the volume-wins failure mode the design exists to prevent.

**Proposed redefinition (needs sign-off before implementing):** compute coherence as average pairwise Pearson **over co-rated restaurants only**, counting only member pairs with overlap ≥ 2–3, and require a minimum number of contributing pairs before trusting the number. This asks "when these people rate the same place, do they agree?" The k=4 giant-blob clustering (`K_INITIAL` on 14k users) is a secondary contributor. Do not tune `MIN_COHERENCE` until coherence is redefined and the data re-clustered.

*(signed off 2026-06-16 — implemented as below.)*

---

## phase 2b performance fix: index rating_events + cache rater weights (decided)
Two independent changes, both prerequisites for re-clustering at an iterable speed (and for the queued category-blocklist re-import):

1. **Add secondary indexes on `rating_events(user_id)` and `rating_events(restaurant_id)`** (schema.sql + ORM). Every credibility read filters by `user_id` and joins on `restaurant_id`; today both full-scan. This is the 50–100× lever and it speeds up *every* read path, not just clustering. Single-column indexes match the existing convention (`ix_clusters_cuisine_id`, etc.); `(user_id)` is the primary win, `(restaurant_id)` covers the "all ratings for restaurant R" path in ranking/consensus.
2. **Cache `_rater_weight` per `(user, cuisine)` inside `compute_cluster_scores`.** A member's weight is constant across the restaurants they rated, so a dict cache collapses ~90,500 calls → ~24,600 (one per eligible member). Pure in-function memoization, no behavior change.

Expected: consensus step from ~45 min to well under a minute; full recluster from ~1.5 h to a few minutes. Deeper structural fixes (batch the weight queries, precompute all weights in one pass) are deferred — these two are small and sufficient. This also confirms the SPEC's phase-3 call that a full recluster is a **batch job, never request-path**, even when fast.

**Measured (2026-06-15 recluster) — partly wrong projection, corrected here.** Cluster outputs were byte-identical (deterministic; confirms the fix changed nothing but speed). The consensus step *did* collapse as expected (~52 min of user-CPU eliminated: 4596.77s → 1453.78s user). But the **full recluster did NOT drop to minutes — total CPU went ~89 min → ~40 min (≈2.2×), not near-zero.** (Ignore wall clock: the machine slept mid-run, 3% avg CPU utilization over a 17 h window.) The projection was wrong because it treated consensus as the whole cost and ignored a second, independent bottleneck: **`coherence_score` runs `np.corrcoef` on each cluster's full member set — the ~13.7k-member American cluster builds a ~14k×14k dense correlation matrix (~1.5 GB, O(n²·m))**, untouched by the indexes/cache (rising system-CPU 750s → 924s corroborates the memory pressure). This is now the dominant cost. **Good news:** the proposed coherence redefinition (Pearson over co-rated restaurants only, sparse pairwise) replaces this dense matrix entirely, so it should remove the remaining slowness as a side effect — do NOT separately optimize the dense `corrcoef` path; it's about to be deleted.

---

## coherence redefinition: Pearson over co-rated restaurants only (decided + implemented 2026-06-16)

Resolves finding 2 above. `coherence_score()` no longer correlates fill-imputed rating vectors with `np.corrcoef`; it averages **pairwise Pearson r computed only over the restaurants each member pair actually co-rated**. This measures taste *agreement* ("when these people rate the same place, do they agree?") instead of co-rating *density*, which is what the old metric collapsed to at scale (88.6% of big-cluster pairs never co-rated, so they correlated at ~0 and dragged every large cluster's coherence to ≈0).

**Chosen parameters (owner sign-off):**
- `MIN_PAIR_OVERLAP = 3` — a member pair contributes a correlation only if they share ≥ 3 co-rated restaurants. Matches alignment's existing `MIN_OVERLAP = 3` ("enough points to trust a correlation"); rejected ≥ 2 because a 2-point Pearson is always exactly ±1 and biases coherence to the extremes.
- `MIN_CONTRIBUTING_PAIRS = 3` — a cluster needs ≥ 3 qualifying pairs or its coherence is **0.0** (unmeasurable ⇒ can't surface). Prevents a thin cluster from surfacing on one or two lucky pairs. Note this means a 2-member cluster (1 possible pair) always scores 0.0 — coherence is now a property you can only establish with several overlapping members.
- Zero-variance qualifying pairs (a member who gave every shared restaurant the same score) contribute **0**, not agreement — unchanged semantics, "no signal ≠ agreement".

**Signature change:** `coherence_score` now takes `list[dict[int, float]]` (per-member `{restaurant_id: real score}`) instead of a dense `np.ndarray`. `discover.recluster_cuisine` builds these sparse dicts once from `matrix.ratings` (real scores, not `matrix.X`'s fill values) and reuses them per cluster. Implementation uses an inverted index (restaurant → raters) so work is bounded by Σ C(raters_per_restaurant, 2), not C(members, 2) — the ~88% zero-overlap pairs cost nothing, and the ~14k×14k dense `corrcoef` matrix (the remaining perf bottleneck from the 2026-06-15 measurement) is gone.

**viz parity:** `viz/clustering.py` mirrors the new metric. Its illustrative members are dense (everyone rates everything), so every pair has full overlap and the gates always pass — the rendered plots are numerically identical to before, so `viz/output/` is unchanged.

**Still pending (unblocked by this, in order):** re-cluster + re-validate (Domino's 1274 vs Vetri Cucina 227; Applebee's 371 vs Middle Child 2173) and confirm coherent clusters now surface; the category-blocklist re-import; then empirically tune `MIN_COHERENCE` (still a guess at 0.50 — do not tune until after the re-cluster on real data).

### validation run (2026-06-19 recluster on the Philadelphia import) — PASSES, with two findings

Re-clustered all 5 cuisines on the live 230k-event DB with the new metric. **Cluster surfacing fired on real data for the first time.**

Coherence now behaves as designed — small genuinely-agreeing clusters beat giant casual blobs (old metric had every large cluster ≈0 and only one 7-member cluster passing):

| cuisine | passing clusters (≥0.50) | the casual blob |
|---|---|---|
| Italian | k2 0.886 (19 mem), k0 0.685 (41) | k1 5,632 mem → 0.10 |
| Korean Fusion | k0 0.608 (21) | — |
| Chinese | k1 0.545 (69) | k0 2,188 mem → 0.15 |
| Japanese | none (best 0.333) | k2 1,778 mem → 0.10 |
| American | none (best k2 0.368, 337 mem) | k0 13,772 mem → 0.10 |

Validation pairs both separate correctly (chain low, calibrated high):
- **Domino's 3.99 (Bayesian) vs Vetri Cucina 8.61 — surfaced from Italian cluster k0 (coherence 0.69, 7 raters).** This is the headline: a calibrated cluster's consensus, not raw volume, now produces the score.
- Applebee's 4.41 vs Middle Child 9.06 — both Bayesian fallback (see finding 1).

**Finding 1 — American (and Japanese) surface nothing because k-means makes one mega-blob.** American is 13,772 members in k0 (coherence 0.10) plus tiny fragments; the most coherent American cluster is only 0.368. This is the *secondary* contributor flagged in finding 2 — `K_INITIAL = 4` on 14k users can't split the casual majority into calibrated sub-groups — **not** a coherence-metric problem. Per the invariants, k-means is a throwaway placeholder phase 3 replaces with matrix factorization; do **not** over-tune it. Lowering `MIN_COHERENCE` toward ~0.35 would let American k2 surface, but that is exactly the tuning that must wait until after the category-blocklist re-import (Reading Terminal Market noise pressures Chinese coherence and could skew the threshold). Middle Child still scores correctly (9.06) via Bayesian fallback, so nothing is broken — American just doesn't yet get the cluster-relative treatment.

**Finding 2 — the redefinition did NOT speed up the recluster (earlier projection wrong again).** Measured: user CPU 1474.79s vs the 2026-06-15 run's 1453.78s, sys 924.01s vs 924s — essentially identical total CPU (~40 min); peak memory footprint 4.04 GB, *higher* than the old dense matrix's ~1.5 GB. Removing the dense `np.corrcoef` did not reduce cost because the sparse inverted-index `pair_scores` dict (one entry per co-rating member pair, holding both aligned score lists) is itself the dominant memory+CPU consumer on the 14k-member American cluster. **Correction to the redefinition note above: it is a correctness fix, not a perf fix — the "removes the remaining slowness as a side effect" claim was wrong.** The recluster remains a ~40-min batch job. If recluster speed ever needs to drop, the real lever is reducing the American cluster's size before coherence runs (i.e. the k-means granularity fix / matrix factorization), not the coherence math. Deferred — a 40-min batch job is acceptable.
