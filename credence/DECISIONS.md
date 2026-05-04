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
