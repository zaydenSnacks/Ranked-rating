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

## Pearson normalization
Raw Pearson r ∈ [-1, 1]. Alignment score needs to be ∈ [0, 1]. Mapping: `(r + 1) / 2`. A perfectly anti-correlated rater gets 0, perfectly correlated gets 1, uncorrelated gets 0.5. Minimum of 2 overlapping restaurants required to compute a meaningful correlation; returns 0 otherwise.

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

---

## seed.sql rescaled to the 1–10 scale
The seed ratings were authored on a 5-star scale (3.5–5.0) while the system math assumes 1–10 (`SCORE_RANGE = 9.0`, CLI help, Bayesian prior). Left alone, the trusted-source seeds would read as harsh outliers ("8.875 means excellent" vs "4.5 means below average") once Yelp data lands at full range — and they anchor the calibrated cluster, so their absolute level matters. Converted with the **same affine map the importer uses** (`1 + (stars − 1) × 2.25`) so seed and Yelp data share one conversion story. Pearson alignment is affine-invariant, but the absolute deltas in `dynamic.py` (agreement threshold) and consensus distances are not — one map everywhere avoids a systematic offset between cohorts.
