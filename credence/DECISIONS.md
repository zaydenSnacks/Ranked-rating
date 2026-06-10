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
