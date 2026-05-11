# credence

Credibility-weighted restaurant rating system. A user's rating is weighted by their credibility for that cuisine type — not all raters are equal.

## project structure

```
ranked-rating/
└── credence/
    ├── SPEC.md          — full product spec (4 phases)
    ├── DECISIONS.md     — tech decision log (read before proposing alternatives)
    ├── schema.sql       — canonical DB schema (SQLite now, Postgres in phase 2)
    ├── seed.sql         — 5 users, 5 cuisines, 7 restaurants, 15 rating events
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
    │   └── test_ranking.py
    ├── modules/
    │   ├── data/
    │   │   ├── db.py        — SQLAlchemy engine + session factory (DATABASE_URL env var)
    │   │   └── models.py    — ORM models for all 8 tables
    │   ├── credibility/
    │   │   ├── score.py     — main formula entry point
    │   │   ├── alignment.py — Pearson correlation vs trusted sources
    │   │   ├── expertise.py — log-normalized rating count per cuisine
    │   │   ├── proximity.py — transitive expertise from adjacent cuisines
    │   │   ├── dynamic.py   — Glicko-inspired credibility updates (phase 2)
    │   │   └── seeds.py     — seed trusted sources with low rating_deviation (phase 2)
    │   ├── ranking/
    │   │   └── ranking.py   — credibility-weighted restaurant score (phase 2: Bayesian prior)
    │   ├── actions.py       — submit_rating(): insert event + fire credibility update atomically
    │   ├── api/             — empty (phase 3)
    │   └── cuisine_graph/   — empty (future)
    └── viz/
        ├── README.md        — contract: viz must mirror production math exactly
        ├── generate.py      — entry point, writes to viz/output/
        ├── components.py    — phase 1 formula plots
        ├── dynamic.py       — phase 2 Glicko trajectory plots
        ├── ranking.py       — ranking formula plots
        └── output/          — 9 committed PNGs (regenerate after any math change)
```

## current phase

**Phase 2 complete.**

- Phase 1: fixed formula, SQLite, seed data, ranking engine — done
- Phase 2: Glicko dynamic credibility, Bayesian ranking prior, CLI — done (Postgres migration deferred to phase 3)
- Phase 3+: designed in SPEC.md, not started

## credibility formula (locked — do not change weights without updating SPEC.md)

```
w(u, c) = clamp(0.50·alignment + 0.30·expertise + 0.20·proximity, 0, 1)
```

When alignment is unavailable (< 3 overlapping restaurants with trusted sources):
```
w = (0.30·expertise + 0.20·proximity) / 0.50   # redistributed, not capped
```

Phase 2 effective weight:
```
effective_weight = credibility_score × (1 − rating_deviation) × (1 + 0.20·proximity)
```

## key invariants

- `rating_events` is **append-only** — never UPDATE or DELETE rows; this is load-bearing for phase 2/3 replay
- Alignment requires **≥ 3 overlapping restaurants** with trusted sources, or returns `(0.0, False)`
- Proximity distance threshold is **strict** (`< 0.6`, not `≤ 0.6`)
- Cuisine distances are stored **symmetrically** (both directions) in `cuisine_distances`
- Trusted sources in phase 2 are **seeds with low `rating_deviation=0.3`**, not hardcoded ground truth — their scores can move
- The viz module uses **standalone numpy** (no DB, no SQLAlchemy) and must stay in sync with production math

## data model (8 tables)

| Table | Purpose |
|---|---|
| `users` | all raters |
| `cuisines` | cuisine categories |
| `cuisine_distances` | pairwise distances [0=identical, 1=unrelated], symmetric |
| `restaurants` | venues, each has one cuisine |
| `trusted_sources` | subset of users treated as ground truth anchors |
| `rating_events` | immutable append-only log of all ratings (score 1–10) |
| `user_credibility` | per-(user, cuisine): credibility_score, rating_deviation, volatility (phase 2) |
| `credibility_history` | audit trail of credibility changes (phase 2) |

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

### CLI commands

```bash
# submit a rating (user_id, restaurant_id, score 1–10)
python main.py rate 3 5 4.0

# print weighted score + per-rater credibility breakdown for a restaurant
python main.py score 5
```

### tests

```bash
pytest          # run all 38 tests (in-memory SQLite, no credence.db needed)
pytest -v       # verbose output per test
```

### visualization

```bash
python -m viz.generate   # writes 9 PNGs to viz/output/
```

## phase 2 constants (dynamic.py)

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

## known gaps (as of phase 2)

- `matplotlib` is a dev dependency but not in `requirements.txt`
- `credibility_history` does not store `volatility` — can't fully reconstruct Glicko state from history alone
- `_community_consensus` in `dynamic.py` has an N+1 query pattern (acceptable at phase 1 scale)
- `last_updated` stored as ISO text — will need `TIMESTAMP WITH TIME ZONE` in the Postgres migration
