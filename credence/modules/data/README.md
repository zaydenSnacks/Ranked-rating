# data — persistence layer and external data ingestion

Owns the database connection, the ORM models for all 11 tables, and bulk
imports from external datasets. No scoring logic lives here — this package
defines *what the data is*, the other packages define what it means.

The canonical schema is `credence/schema.sql`; `models.py` mirrors it and the
two must be kept in sync by hand (`init-db` creates tables from the ORM, the
.sql file is the reviewable reference).

## files

| file | in charge of |
|---|---|
| `db.py` | SQLAlchemy engine + session factory + declarative `Base`. Reads `DATABASE_URL` (defaults to `sqlite:///credence/credence.db`); the planned phase-3 Postgres migration is a URL swap plus driver. |
| `models.py` | ORM classes for all 11 tables: phase 1 (`users`, `cuisines`, `cuisine_distances`, `restaurants`, `trusted_sources`, `rating_events`), phase 2a (`user_credibility`, `credibility_history`), phase 2b (`clusters`, `user_cluster_assignments`, `cluster_restaurant_scores`). |
| `importers/yelp.py` | Yelp Academic Dataset → credence schema. Streams the NDJSON business/review files (too large to load), maps Yelp categories onto the 5 seed cuisines (skips multi-cuisine matches), converts stars 1–5 → scores 1–10 via `1 + (stars−1)×2.25`, drops users with < 3 qualifying reviews (two passes), and inserts **raw `rating_events` only** — credibility and clusters are recomputed afterwards, which is what append-only buys. **One-shot:** refuses to re-run; re-import means a fresh DB. |

## the one rule that matters

`rating_events` is **append-only** — never UPDATE or DELETE a row. Every
derived table (credibility state, clusters, consensus scores) can be rebuilt
from this log; nothing else in the system is a source of truth. This is
load-bearing for phase 2/3 replay and for the import strategy above.

Known accepted noise in the Yelp category mapping (a food hall importing as
Chinese, etc.) is quantified and tracked in `DECISIONS.md` under "known
accepted noise", with explicit revisit triggers.
