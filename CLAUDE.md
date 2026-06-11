# credence

Credibility-weighted restaurant rating system. A user's rating is weighted by their credibility for that cuisine type — not all raters are equal. Phase 2 adds **cluster-relative credibility**: the system discovers taste groups from rating patterns and computes consensus per cluster, so a calibrated minority isn't drowned out by a casual majority (the "Taco Bell at 4.2" problem).

## project structure

```
ranked-rating/
└── credence/
    ├── SPEC.md          — full product spec (4 phases, cluster-relative credibility)
    ├── DECISIONS.md     — tech decision log (read before proposing alternatives)
    ├── schema.sql       — canonical DB schema (SQLite now, Postgres in phase 3)
    ├── seed.sql         — 5 users, 5 cuisines, 7 restaurants, 15 rating events (scores on the 1–10 scale)
    ├── main.py          — CLI entry point (Typer: init-db, seed, rate, score)
    ├── requirements.txt — runtime deps (matplotlib is dev-only, not listed)
    ├── pytest.ini       — test config (testpaths=tests, pythonpath=.)
    ├── tests/
    │   ├── conftest.py      — in-memory SQLite fixture + shared helpers
    │   ├── test_expertise.py
    │   ├── test_proximity.py
    │   ├── test_alignment.py
    │   ├── test_score.py
    │   ├── test_dynamic.py
    │   ├── test_ranking.py
    │   ├── test_yelp_importer.py
    │   └── test_clustering.py
    ├── modules/
    │   ├── data/
    │   │   ├── db.py        — SQLAlchemy engine + session factory (DATABASE_URL env var)
    │   │   ├── models.py    — ORM models for all 11 tables
    │   │   └── importers/
    │   │       └── yelp.py  — Yelp Academic Dataset → credence schema (one-shot, streaming)
    │   ├── credibility/
    │   │   ├── score.py     — main formula entry point
    │   │   ├── alignment.py — Pearson correlation vs cluster consensus (phase 2: was trusted sources)
    │   │   ├── expertise.py — log-normalized rating count per cuisine
    │   │   ├── proximity.py — transitive expertise from adjacent cuisines
    │   │   ├── dynamic.py   — Glicko-inspired credibility updates (phase 2)
    │   │   └── seeds.py     — seed trusted sources with low rating_deviation (phase 2)
    │   ├── clustering/      — phase 2b
    │   │   ├── discover.py  — k-means on rating vectors + recluster_cuisine/recluster_all orchestration
    │   │   ├── assign.py    — persist assignments with confidence (1 − d1/d2)
    │   │   ├── consensus.py — per-cluster restaurant scores (Bayesian prior within cluster)
    │   │   ├── coherence.py — avg pairwise Pearson between members' rating vectors
    │   │   └── seeds.py     — plant trusted sources into expected calibrated cluster
    │   ├── ranking/
    │   │   └── ranking.py   — surfaces highest-coherence cluster score, falls back to Bayesian prior
    │   ├── actions.py       — submit_rating(): insert event + fire credibility + cluster updates
    │   ├── api/             — empty (phase 3)
    │   └── cuisine_graph/   — empty (phase 3+: learned cuisine distances from embeddings)
    └── viz/
        ├── README.md        — contract: viz must mirror production math exactly
        ├── generate.py      — entry point, writes to viz/output/
        ├── components.py    — phase 1 formula plots
        ├── dynamic.py       — phase 2 Glicko trajectory plots
        ├── ranking.py       — ranking formula plots
        ├── clustering.py    — cluster visualizations (planned)
        └── output/          — committed PNGs (regenerate after any math change)
```

## current phase

**Phase 2 — dynamic credibility done, clustering in progress.**

- Phase 1: fixed formula, SQLite, seed data, ranking engine — done
- Phase 2a: Glicko dynamic credibility + Bayesian ranking prior — done
- Phase 2b: cluster discovery via k-means + Yelp data import + cluster-relative consensus — **in progress** (this is the conceptual upgrade that prevents the system from drifting toward a simple average)
  - done: cluster tables, Yelp importer, clustering module (`discover`/`assign`/`coherence`/`consensus`/`seeds`), `cluster` + `user-clusters` CLI
  - remaining: run the Yelp import, wire `alignment.py` to cluster consensus (step 4), wire `ranking.py` to surface highest-coherence cluster (step 5), Taco-Bell-vs-Ichiran validation
- Phase 3+: matrix factorization, real-time inference, UI v1 — designed in SPEC.md, not started
- Phase 4: GNN, stream processing, UI v2 — designed in SPEC.md, not started

## credibility formula

**Phase 1 (locked — do not change weights without updating SPEC.md):**
```
w(u, c) = clamp(0.50·alignment + 0.30·expertise + 0.20·proximity, 0, 1)
```

When alignment is unavailable (< 3 overlapping restaurants):
```
w = (0.30·expertise + 0.20·proximity) / 0.50   # redistributed, not capped
```

**Phase 2 effective weight (Glicko + cluster-aware):**
```
effective_weight = credibility_score × (1 − rating_deviation) × (1 + 0.20·proximity)
```

Phase 2 alignment correlates against **cluster consensus**, not the global trusted-source average. Falls back to phase 1 alignment when the user's cluster has insufficient data.

## ranking formula

**Phase 1:** straight credibility-weighted average.

**Phase 2 (Bayesian prior — done):**
```
final_score = (3.0 × global_avg + Σ(rating_i × weight_i)) / (3.0 + Σ weight_i)
```

**Phase 2 (cluster-aware — in progress):**
```
if highest-coherence cluster has >= MIN_RATERS for this restaurant:
    final_score = cluster_restaurant_scores[surfaced_cluster.id][R.id].consensus
else:
    final_score = Bayesian prior fallback (above)
```

## key invariants

- `rating_events` is **append-only** — never UPDATE or DELETE rows; this is load-bearing for phase 2/3 replay
- Alignment requires **≥ 3 overlapping restaurants** with the comparison set (trusted sources in phase 1, cluster consensus in phase 2), or returns `(0.0, False)`
- Proximity distance threshold is **strict** (`< 0.6`, not `≤ 0.6`)
- Cuisine distances are stored **symmetrically** (both directions) in `cuisine_distances`
- Trusted sources in phase 2 are **seeds with low `rating_deviation=0.3`** AND **seeds planted into expected calibrated cluster** — their scores can move; their cluster membership can change
- **Cluster surfacing uses coherence_score, not member_count** — a small high-coherence cluster beats a large low-coherence one
- **K-means is a placeholder, not the destination** — phase 3 replaces it with matrix factorization. Don't over-tune k-means; it's expected to be rough
- The viz module uses **standalone numpy** (no DB, no SQLAlchemy) and must stay in sync with production math
- Coherence score is computed as **average pairwise correlation between cluster members' rating vectors** — high coherence = members agree closely

## data model (11 tables)

### phase 1 (6 tables)
| Table | Purpose |
|---|---|
| `users` | all raters |
| `cuisines` | cuisine categories |
| `cuisine_distances` | pairwise distances [0=identical, 1=unrelated], symmetric |
| `restaurants` | venues, each has one cuisine |
| `trusted_sources` | subset of users seeded into expected calibrated cluster |
| `rating_events` | immutable append-only log of all ratings (score 1–10) |

### phase 2 dynamic credibility (2 tables — done)
| Table | Purpose |
|---|---|
| `user_credibility` | per-(user, cuisine): credibility_score, rating_deviation, volatility |
| `credibility_history` | audit trail of credibility changes |

### phase 2 clustering (3 tables — created; clustering module in progress)
| Table | Purpose |
|---|---|
| `clusters` | id, cuisine_id, label, coherence_score, member_count |
| `user_cluster_assignments` | (user_id, cuisine_id) → cluster_id, confidence |
| `cluster_restaurant_scores` | (cluster_id, restaurant_id) → consensus, rater_count |

## running things

```bash
cd credence
pip install -r requirements.txt
# DATABASE_URL defaults to credence.db (SQLite); set it to a postgres:// URL for Postgres
```

### first-time setup

```bash
# create tables
python main.py init-db

# load seed data (users, cuisines, restaurants, ratings)
sqlite3 credence.db < seed.sql

# seed trusted sources with low rating_deviation
python main.py seed
```

### data bootstrapping (phase 2)

Clusters need volume to converge. With only seed data (15 ratings) k-means produces noise. Use the Yelp Academic Dataset (one-shot — refuses to re-run; see DECISIONS.md):

```bash
python main.py import-yelp --path /path/to/yelp_academic_dataset

# iterate on a slice first
python main.py import-yelp --path ... --city Philadelphia --max-reviews 50000
```

Maps Yelp categories onto the 5 seed cuisines (skips multi-cuisine matches), converts stars 1–5 → scores 1–10, drops users with < 3 qualifying reviews, and inserts raw `rating_events` only — credibility and clusters are recomputed afterwards.

The dataset covers 11 metros: Philadelphia, Tampa, Tucson, Indianapolis, Nashville, New Orleans, Reno, Edmonton, St. Louis, Santa Barbara, Boise. **New York is not in the dataset** (the seed restaurants are NYC, but seed and Yelp raters share no restaurants anyway). Philadelphia is the largest slice — use it for the first import.

### CLI commands

```bash
# submit a rating (user_id, restaurant_id, score 1–10)
python main.py rate 3 5 4.0

# print weighted score + per-rater credibility breakdown for a restaurant
python main.py score 5

# run k-means clustering across all cuisines (rebuilds all cluster state)
python main.py cluster

# show user's cluster per cuisine
python main.py user-clusters 3
```

### tests

```bash
pytest          # run all tests (in-memory SQLite, no credence.db needed)
pytest -v       # verbose output per test
```

### visualization

```bash
python -m viz.generate   # writes PNGs to viz/output/
```

## phase 2 constants

### dynamic.py (Glicko-inspired)
| Constant | Value | Meaning |
|---|---|---|
| `LEARNING_RATE` | 0.05 | max credibility shift per rating event |
| `RD_DECAY` | 0.05 | fraction RD falls on agreement |
| `RD_FLOOR` | 0.10 | minimum rating_deviation |
| `VOL_BUMP` | 0.01 | volatility increase on divergence |
| `VOL_CAP` | 0.15 | maximum volatility |
| `DAMPEN` | 3.0 | Bayesian prior weight on community signal |
| `SCORE_RANGE` | 9.0 | normalization denominator for 1–10 scores |

Agreement threshold: `|user_score − consensus| < 4.5` (i.e., `agreement >= 0.5`).

### clustering
| Constant | Value | Lives in | Meaning |
|---|---|---|---|
| `K_INITIAL` | 4 | discover.py | starting k for k-means per cuisine (calibrated/casual/inflator/complainer archetypes) |
| `MIN_RATERS_PER_CLUSTER` | 5 | consensus.py | minimum cluster members rating a restaurant before its cluster score can surface |
| `MIN_COHERENCE` | 0.50 | coherence.py | minimum coherence for a cluster to be considered "calibrated enough" to surface scores |
| `MIN_RATINGS_FOR_VECTOR` | 3 | discover.py | minimum user ratings in a cuisine before they get a meaningful rating vector |
| `KMEANS_SEED` | 0 | discover.py | fixed RNG seed — clusters are deterministic for a given event log |

Missing vector entries are filled with the cuisine average (`MISSING_VALUE_FILL = cuisine_avg`, implemented inline in `build_rating_matrix`). Rating vectors use the **latest rating per (user, restaurant)**.

## known gaps

- `matplotlib` is a dev dependency but not in `requirements.txt`
- `credibility_history` does not store `volatility` — can't fully reconstruct Glicko state from history alone
- `_community_consensus` in `dynamic.py` has an N+1 query pattern (acceptable at phase 1 scale)
- `last_updated` stored as ISO text — will need `TIMESTAMP WITH TIME ZONE` in the Postgres migration
- Cluster coherence threshold (`MIN_COHERENCE`) is a guess — needs empirical tuning once Yelp data is loaded
- Clustering is built but not yet wired into `alignment.py` (step 4) or `ranking.py` (step 5) — cluster state is computed and stored, nothing reads it yet
- Seed data alone can't produce clusters: no seed user has ≥ 3 ratings in a single cuisine, so `cluster` is a no-op until the Yelp import runs
- No story yet for handling restaurants that span two cuisines (e.g., Korean-Mexican fusion) — open question in SPEC.md