# credence — spec

## what it is
A weighted restaurant rating system. A user's rating is weighted by their credibility for that cuisine type. Not all raters are equal — someone who consistently agrees with trusted food critics on Italian food carries more weight when rating Italian restaurants.

## credibility formula (locked)

```
w(u, c) = clamp(α·alignment + β·expertise + γ·proximity, 0, 1)
```

Weights: α=0.50, β=0.30, γ=0.20

### alignment_score
Pearson correlation between user's ratings and the average trusted-source rating per restaurant, on overlapping restaurants in cuisine C. Requires at least 3 overlapping restaurants; returns 0 otherwise.

When overlap is insufficient, α's weight is redistributed proportionally across expertise and proximity so the score stays in [0, 1]:
```
w = (β·expertise + γ·proximity) / (β + γ)   # when alignment unavailable
```

Multiple trusted sources on the same restaurant are averaged before correlating — no single trusted source dominates the signal.

### expertise_score
Log-normalized count of user's ratings in cuisine C:
```
log(n+1) / log(max_n+1)    # max_n = 20 (soft cap)
```

### proximity_score
Expertise borrowed from adjacent cuisines via the cuisine graph:
```
Σ expertise(user, cuisine_j) * (1 - distance(C, cuisine_j))
  for all j ≠ C where distance(C, cuisine_j) < 0.6
```
Normalized to [0,1] by dividing by the max possible sum (all adjacent expertise = 1). Distance threshold is strict (`< 0.6`, not `≤`).

## ranking formula
```
weighted_avg(restaurant) = Σ(score_i * weight_i) / Σ(weight_i)
```
Falls back to simple average if all credibility weights are 0.

## trusted sources
Small set of "trusted" raters whose ratings serve as ground truth. Seeded manually. All alignment scores are anchored to these users.

## data model
- **users** — id, name, email, created_at
- **cuisines** — id, name, description
- **cuisine_distances** — (cuisine_a_id, cuisine_b_id, distance) — symmetric, stored both directions
- **restaurants** — id, name, cuisine_id, location, created_at
- **trusted_sources** — id, user_id, added_at, notes — separate table; trusted users are ground truth, not raters to weight
- **rating_events** — id, user_id, restaurant_id, score, created_at — immutable, append-only

## phase plan

| Phase | Theme | Users | Stack |
|-------|-------|-------|-------|
| 1 | Formula-based credibility, CLI | ~10s | SQLite, Python |
| 2 | Dynamic credibility, seeds replaced by community | ~1000s | Postgres, FastAPI |
| 3 | Real-time inference, caching, UI v1 | ~100k | Redis, async jobs, React |
| 4 | Distributed compute, stream processing, UI v2 | millions | Kafka, FAISS, full product |

- **Phase 1** (now): data model + seed data + credibility formula (hand-tuned α/β/γ) + ranking engine
- **Phase 2**: dynamic credibility via Glicko-inspired model; migrate to Postgres; Bayesian prior on ranking
- **Phase 3**: async credibility jobs, Redis cache, ANN via FAISS, FastAPI layer, React UI v1
- **Phase 4**: Kafka stream processing, PageRank-style credibility network, learned weights, full product UI v2

---

## phase 2 — dynamic credibility

### what changes from phase 1

The fixed trusted source anchor is replaced by an emergent community consensus.
Trusted sources don't disappear — they become high-confidence seeds with a low
initial `rating_deviation`, but their scores can be revised downward if they
consistently diverge from the community as it grows.

### credibility model

Inspired by Glicko-2 (chess rating system). Every user gets three values per
cuisine instead of one:

```
credibility_score    float   starts at 0.5 for all users
rating_deviation     float   starts at 1.0 (high uncertainty), falls with activity
volatility           float   starts at 0.06, rises if user is inconsistent
```

Trusted sources seeded with `rating_deviation = 0.3` (system starts confident in
them) rather than being hardcoded as ground truth.

### how credibility updates

After every new rating event:

1. compute the credibility-weighted community consensus for that restaurant
2. compare the new rating to that consensus
3. if close → `credibility_score` nudges up, `rating_deviation` falls
4. if divergent → `credibility_score` nudges down, `volatility` rises
5. the nudge magnitude is weighted by the credibility of who they're
   agreeing or disagreeing with — agreeing with a highly credible rater
   moves you more than agreeing with a new user

Trusted sources whose ratings consistently diverge from the emerging consensus
will see their `credibility_score` fall automatically. No manual intervention
needed.

### updated credibility formula

```
w(u, c) = f(credibility_score, rating_deviation, expertise, proximity)

effective_weight = credibility_score × (1 - rating_deviation) × expertise_boost

where expertise_boost = 1 + (0.20 × proximity_score)
```

If `credibility_score` is unavailable (new user, no overlap):
```
w = (0.30 × expertise + 0.20 × proximity) / 0.50   [redistributed]
```

### new schema additions

```sql
CREATE TABLE user_credibility (
    user_id           INTEGER NOT NULL REFERENCES users(id),
    cuisine_id        INTEGER NOT NULL REFERENCES cuisines(id),
    credibility_score REAL NOT NULL DEFAULT 0.5,
    rating_deviation  REAL NOT NULL DEFAULT 1.0,
    volatility        REAL NOT NULL DEFAULT 0.06,
    last_updated      TEXT NOT NULL,
    PRIMARY KEY (user_id, cuisine_id)
);

CREATE TABLE credibility_history (
    id                INTEGER PRIMARY KEY,
    user_id           INTEGER NOT NULL REFERENCES users(id),
    cuisine_id        INTEGER NOT NULL REFERENCES cuisines(id),
    credibility_score REAL NOT NULL,
    rating_deviation  REAL NOT NULL,
    recorded_at       TEXT NOT NULL
);
```

All phase 1 tables unchanged. `trusted_sources` table is kept — it now seeds
low `rating_deviation` instead of acting as a fixed anchor.

### infrastructure additions

- migrate from SQLite → Postgres (handles concurrent writes, better for jobs)
- add a credibility job that triggers on new `rating_events` rows
- job runs synchronously in phase 2 (blocking), async in phase 3

```
new rating inserted
        ↓
credibility job (updates user_credibility for that user × cuisine)
        ↓
ranking engine reads from user_credibility
```

### new modules

```
modules/
  credibility/
    engine.py          ← updated formula (phase 1)
    dynamic.py         ← glicko-inspired update logic (phase 2 addition)
    seeds.py           ← seed trusted sources with low deviation
```

### ranking formula additions

Bayesian prior introduced (already designed in phase 1, implemented here):

```
final_score = (prior_weight × global_avg + Σ(rating_i × weight_i))
              / (prior_weight + Σ weight_i)

prior_weight = 3.0   [equivalent to 3 ratings at global average]
```

Weight used per rating = cuisine-specific `w(user, cuisine_C)`, not global.

---

## phase 3 — real-time inference + ui v1

### what changes from phase 2

Credibility computation moves fully async. The ranking engine reads from a
fast cache (Redis) rather than computing on the fly. This is the core latency
work — keeping inference fast under real load.

### infrastructure

```
new rating event
        ↓
job queue (e.g. RQ or Celery)
        ↓
async credibility worker (updates affected user × cuisine pairs only)
        ↓
writes to Redis cache (keyed by user_id:cuisine_id)
        ↓
ranking engine reads from Redis at query time (microseconds)
        ↓
falls back to Postgres if cache miss
```

Cache invalidation strategy: TTL of 1 hour on credibility scores. On new
rating event, invalidate only affected keys rather than full cache flush.

### approximate nearest neighbors

As user base grows, full pairwise comparison becomes expensive. Phase 3
introduces ANN (approximate nearest neighbor) search using FAISS (Meta,
open source) to find each user's neighborhood efficiently.

Instead of comparing every user to every other user, compute each user's
approximate top-1000 most similar users. Run credibility computations only
within that neighborhood. Update neighborhoods on a nightly batch job.

```
modules/
  recommendations/
    clustering.py      ← user similarity vectors
    neighbors.py       ← FAISS-based ANN search
    recommend.py       ← surface ratings from similar users
```

### api layer

FastAPI serving layer exposing:

```
POST /ratings                     submit a new rating event
GET  /restaurants/:id/score       weighted score for a restaurant
GET  /restaurants/:id/ratings     all ratings with credibility weights shown
GET  /users/:id/credibility       user's credibility per cuisine
GET  /users/:id/recommendations   restaurants to try based on similar users
GET  /cuisines/:id/leaderboard    top-credibility raters for a cuisine
```

```
modules/
  api/
    main.py            ← FastAPI app
    routes/
      ratings.py
      restaurants.py
      users.py
    middleware/
      cache.py         ← Redis read-through
      auth.py          ← basic auth (phase 3), full auth (phase 4)
```

### ui v1 — web (React)

Goal: a functional, minimal interface for browsing restaurants, seeing
credibility-weighted scores, and submitting ratings. Not polished — focused
on validating the core experience.

Stack: React + TailwindCSS, calls the FastAPI backend.

Key screens:

```
/ (home)
  → list of restaurants sorted by weighted score
  → each card shows: name, cuisine, weighted score, rating count, confidence indicator

/restaurant/:id
  → restaurant detail
  → weighted score prominently
  → breakdown: each rater, their score, their credibility weight for this cuisine
  → submit rating form (authenticated)

/user/:id
  → user profile
  → credibility scores per cuisine shown as a radar/bar chart
  → rating history
  → similar users (from clustering)

/cuisines
  → browse by cuisine
  → leaderboard of top credibility raters per cuisine
```

Confidence indicator on restaurant cards: low rating count or high variance
among raters shows a visual flag (e.g. "early" badge) so users understand
a score of 4.8 from 2 raters means less than 4.8 from 40.

```
modules/
  ui/                  ← or separate repo: credence-web
    src/
      components/
        RestaurantCard.jsx
        RatingBreakdown.jsx
        CredibilityBadge.jsx
        CuisineRadar.jsx
      pages/
        Home.jsx
        Restaurant.jsx
        User.jsx
        Cuisines.jsx
      api/
        client.js      ← wraps fetch calls to FastAPI
```

### latency targets

```
GET /restaurants/:id/score     < 50ms   (cache hit)
GET /restaurants/:id/score     < 200ms  (cache miss, recompute)
POST /ratings                  < 100ms  (write + async job enqueue)
credibility worker job         < 2s     (per user × cuisine update)
```

Measuring and hitting these targets is the core ML/infra work for phase 3.
Profile the credibility computation, identify bottlenecks, optimize the
SQL queries and cache strategy.

---

## phase 4 — distributed compute + ui v2

### what changes from phase 3

Scale to millions of users. Move from async jobs to stream processing.
Move from approximate batch neighborhoods to real-time similarity updates.
UI becomes a full product.

### infrastructure

```
rating event
        ↓
Kafka topic: rating_events
        ↓
stream processor (Flink or Spark Streaming)
  → credibility update consumer
  → neighborhood update consumer
  → recommendation refresh consumer
        ↓
Redis cluster (credibility cache, sharded)
Postgres (source of truth, read replicas for API)
FAISS index (rebuilt nightly, served via dedicated service)
```

### pagerank-style credibility network

Phase 4 introduces network-level credibility propagation. Agreement from a
highly credible rater gives you more credibility than agreement from an
unknown rater — equivalent to PageRank applied to raters.

```
for each new rating:
  agreement_signal = similarity(user_score, consensus_score)
  credibility_delta = agreement_signal × creditor_weight × learning_rate
  user.credibility_score += credibility_delta
  propagate partial delta to users in neighborhood
```

This converges to stable values the same way PageRank converges. No circular
reasoning problem — the algorithm settles naturally.

### learned weights (replacing hand-tuned α β γ)

In phase 1/2 the formula uses fixed weights: α=0.50, β=0.30, γ=0.20.
Phase 4 replaces these with a model that learns optimal weights from data.

Training signal: cases where trusted source ratings exist and we can
measure how well the weighted score predicted them. Treat it as a regression
problem — the model predicts what a trusted source would rate a restaurant,
given a user's history. The model's confidence in that prediction becomes
the weight.

Model options (start simple):
- logistic regression on alignment, expertise, proximity features
- gradient boosted trees if more signal is available
- small neural net if data is rich enough

```
ml/
  training/
    dataset.py         ← build training set from rating_events + trusted_sources
    features.py        ← alignment, expertise, proximity feature extraction
    train.py           ← model training loop
    evaluate.py        ← holdout evaluation, avoid data leakage
  serving/
    model.py           ← load trained model, run inference
    latency_bench.py   ← benchmark inference time, compare to formula baseline
```

### ui v2 — full product

Polished mobile-first web app (or native iOS via React Native).

Additional screens and features beyond v1:

```
/discover
  → personalized feed based on clustering + credibility
  → "people like you rated this highly" surface
  → filter by neighborhood, price, cuisine

/restaurant/:id (enhanced)
  → credibility breakdown now visual — bar chart per rater
  → show how score changed over time as more ratings came in
  → "your predicted score" based on user's taste profile
  → map + basic info pulled from external API (Google Places)

/profile (own profile)
  → full taste profile: radar chart of credibility per cuisine
  → rating streak, consistency score
  → leaderboard position per cuisine
  → notification when a restaurant you rated gets enough ratings to stabilize

/leaderboards
  → top raters per cuisine city-wide
  → incentive layer: credible raters get "verified palate" badge per cuisine

onboarding
  → new user rates 5-10 restaurants they've been to
  → system bootstraps their taste profile immediately
  → shown restaurants where similar users have high credibility
```

Authentication: full user accounts with OAuth (Google login at minimum).
Rating history tied to account, credibility score persists across sessions.

---

## open questions (carry into each phase)

- What is the floor for `credibility_score`? Can a user go to 0 or is there a minimum?
- Should cuisine distances be static (manual table) or learned from rating patterns?
- How do you handle a restaurant that spans two cuisines (e.g. Korean-Mexican fusion)?
- Moderation: what happens when a coordinated group tries to game the credibility system?
- Should users be able to see their own credibility score? Transparent or hidden?
- External data: when does it make sense to pull in Google Places / Yelp data to
  supplement the seed restaurant metadata?
