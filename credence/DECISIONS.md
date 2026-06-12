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
