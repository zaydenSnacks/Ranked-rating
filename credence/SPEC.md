# credence — spec

## what it is
A weighted restaurant rating system. A user's rating is weighted by their credibility for that cuisine type. Not all raters are equal — someone who consistently agrees with calibrated raters on a cuisine carries more weight when rating restaurants in that cuisine.

## the core insight (added phase 2)

Simple weighted averages — even credibility-weighted ones — eventually drift toward whatever the majority of raters produce. Once casual raters outnumber calibrated ones (which happens on any real platform), the consensus reflects casual taste. Taco Bell ends up at 4.2 on Google Maps and Ichiran at 4.2 on Google Maps because the casual majority pulls everything toward a similar middle ground.

The fix is **cluster-relative credibility**. Instead of one consensus per restaurant, the system discovers multiple taste groups (clusters) from rating patterns alone — no labels, no demographic questions — and computes a separate consensus per cluster. The score surfaced for a restaurant comes from the most internally coherent cluster with sufficient cuisine expertise, not from the global weighted average.

```
Without clustering:                With clustering (credence 1–10 scale):
  Taco Bell  → 4.2 (Google, 1–5)     Taco Bell  → 5.1 (calibrated cluster)
  Ichiran    → 4.2 (Google, 1–5)     Ichiran    → 9.8 (calibrated cluster)
```

This insight reshapes phase 2 onward. The phase 1 formula stays intact as a fallback for sparse data.

## credibility formula — phase 1 (locked)

```
w(u, c) = clamp(α·alignment + β·expertise + γ·proximity, 0, 1)
```

Weights: α=0.50, β=0.30, γ=0.20

### alignment_score (phase 1)
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

**Phase 1:**
```
weighted_avg(restaurant) = Σ(score_i * weight_i) / Σ(weight_i)
```
Falls back to simple average if all credibility weights are 0.

**Phase 2 (Bayesian prior):**
```
final_score = (prior_weight × global_avg + Σ(rating_i × weight_i))
              / (prior_weight + Σ weight_i)

prior_weight = 3.0   [equivalent to 3 ratings at global average]
```

**Phase 2 (cluster-aware, with fallback):**
```
if a cluster has >= MIN_RATERS for this restaurant:
    final_score = consensus(highest_coherence_cluster)
else:
    final_score = bayesian_prior fallback (above)
```

Cluster consensus uses the same Bayesian prior internally — the prior just gets applied within the cluster instead of globally.

## trusted sources

**Phase 1:** small set of "trusted" raters whose ratings serve as ground truth. Seeded manually. All alignment scores are anchored to these users.

**Phase 2:** trusted sources become **cluster seeds**, not anchors. They are placed in what is expected to be the calibrated cluster at initialization with low `rating_deviation` (0.3). Their credibility scores can still rise or fall like anyone else. If a seed consistently diverges from their cluster's consensus, their credibility falls and the seed status becomes irrelevant. The system self-corrects.

## data model

### phase 1 tables
- **users** — id, name, email, created_at
- **cuisines** — id, name, description
- **cuisine_distances** — (cuisine_a_id, cuisine_b_id, distance) — symmetric, stored both directions
- **restaurants** — id, name, cuisine_id, location, created_at
- **trusted_sources** — id, user_id, added_at, notes
- **rating_events** — id, user_id, restaurant_id, score, created_at — immutable, append-only

### phase 2 tables (dynamic credibility)
- **user_credibility** — per-(user, cuisine): credibility_score, rating_deviation, volatility
- **credibility_history** — audit trail of credibility changes

### phase 2 tables (clustering)
- **clusters** — id, cuisine_id, label (optional), coherence_score, member_count, created_at
- **user_cluster_assignments** — (user_id, cuisine_id) → cluster_id, confidence, assigned_at
- **cluster_restaurant_scores** — (cluster_id, restaurant_id) → consensus, rater_count, last_updated

## phase plan

| Phase | Theme | Users | Stack |
|-------|-------|-------|-------|
| 1 | Formula-based credibility, CLI | ~10s | SQLite, Python |
| 2 | Dynamic credibility + cluster discovery (k-means) | ~1000s | Postgres, FastAPI |
| 3 | Real-time inference, matrix factorization, UI v1 | ~100k | Redis, async jobs, React |
| 4 | GNN-based credibility, stream processing, UI v2 | millions | Kafka, FAISS, full product |

- **Phase 1** (done): data model + seed data + credibility formula + ranking engine
- **Phase 2** (in progress): Glicko-inspired dynamic credibility (done), Bayesian ranking prior (done), Yelp dataset importer (done), **cluster discovery via k-means (module done — replaces global consensus with cluster-relative consensus)**, cluster-relative alignment (done), cluster-aware ranking (done); remaining: run the Yelp import, Taco-Bell validation, tune MIN_COHERENCE
- **Phase 3**: async credibility jobs, Redis cache, **matrix factorization replaces k-means for clustering**, FastAPI layer, React UI v1
- **Phase 4**: Kafka stream processing, **graph neural network unifies clustering + credibility + proximity**, learned α/β/γ weights, full product UI v2

---

## phase 2 — dynamic credibility + cluster discovery

### what changes from phase 1

Two layered changes:

**Layer 1 — dynamic credibility (done):** the fixed trusted source anchor is replaced by an emergent community consensus. Trusted sources don't disappear — they become high-confidence seeds with a low initial `rating_deviation`, but their scores can be revised downward if they consistently diverge from the community as it grows.

**Layer 2 — cluster discovery (new):** the consensus itself becomes cluster-relative. Instead of one weighted average per restaurant, the system discovers taste clusters from rating patterns and computes a separate consensus per cluster. This is what prevents the system from collapsing into a simple average over time.

### credibility model (phase 2)

Inspired by Glicko-2 (chess rating system). Every user gets three values per cuisine instead of one:

```
credibility_score    float   starts at 0.5 for all users
rating_deviation     float   starts at 1.0 (high uncertainty), falls with activity
volatility           float   starts at 0.06, rises if user is inconsistent
```

Trusted sources seeded with `rating_deviation = 0.3` (system starts confident in them).

### how credibility updates

After every new rating event:

1. determine the user's cluster for that cuisine (if assigned)
2. compute the credibility-weighted **cluster consensus** for that restaurant (fallback to global consensus if cluster has insufficient data)
3. compare the new rating to that consensus
4. if close → `credibility_score` nudges up, `rating_deviation` falls
5. if divergent → `credibility_score` nudges down, `volatility` rises
6. the nudge magnitude is weighted by the credibility of who they're agreeing or disagreeing with — agreeing with a highly credible rater in your cluster moves you more than agreeing with a new user

Trusted sources whose ratings consistently diverge from their cluster's consensus will see their `credibility_score` fall automatically. No manual intervention needed.

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

### cluster discovery (new in phase 2)

**Algorithm:** k-means on user rating vectors per cuisine. Each user becomes a vector of their scores across restaurants in cuisine C, with missing values filled by the cuisine average.

**Starting k:** 4 (calibrated, casual, inflator, complainer are the natural archetypes — but the system never knows these labels, it just finds the groups).

**Why k-means at this phase:** classical methods are robust on sparse data. ML-based clustering (matrix factorization, GNN) needs volume to learn anything meaningful. With a few thousand users and sparse ratings, ML will produce worse clusters than k-means. K-means is a placeholder that works — phase 3 replaces it with matrix factorization once data volume justifies it.

**Cluster coherence score:** measures how internally consistent a cluster is. High coherence = members agree closely with each other on the same restaurants. Computed as the average pairwise correlation between members' rating vectors within the cluster.

**Cluster recomputation:** nightly batch job in phase 2, online updates in phase 3.

### how a restaurant score gets surfaced

```
for restaurant R in cuisine C:
    candidate_clusters = clusters in cuisine C where:
        - cluster has >= MIN_RATERS ratings for R (e.g., 5)
        - cluster's coherence_score above threshold

    if no candidate_clusters:
        return phase 1 bayesian prior fallback

    surfaced_cluster = candidate with highest coherence_score
                       (tiebreak: highest average member expertise in C)

    return cluster_restaurant_scores[surfaced_cluster.id][R.id].consensus
```

The "calibrated cluster" is never declared. It emerges as the cluster whose members happen to agree consistently with each other and have the most cuisine-specific expertise.

### the Taco Bell problem (worked example)

Without clustering, a restaurant's score is dominated by whoever rates most. Taco Bell at 4.2 (on Google's 5-star scale) reflects casual-rater volume.

With clustering (scores below on credence's 1–10 scale):
```
Taco Bell ratings (hypothetical at scale):
  Cluster A (casual):      8.4 from 8000 raters, coherence 0.42
  Cluster B (calibrated):  5.1 from  400 raters, coherence 0.78

Ichiran ratings (hypothetical at scale):
  Cluster A (casual):      7.5 from 2000 raters, coherence 0.42
  Cluster B (calibrated):  9.8 from  600 raters, coherence 0.78
```

Cluster B wins both surfacing decisions because its coherence is higher. Taco Bell scores 5.1, Ichiran scores 9.8. The volume advantage of casual raters is neutralized entirely. No user was labeled. No demographic question was asked.

### data bootstrapping (new in phase 2)

Clusters need volume to converge. The Yelp Academic Dataset provides millions of real reviews with real restaurant metadata, free for research use. A one-time import script maps Yelp JSON to the credence schema. The dataset covers 11 metros (Philadelphia, Tampa, Tucson, Indianapolis, Nashville, New Orleans, Reno, Edmonton, St. Louis, Santa Barbara, Boise) — New York is not among them, so the seed NYC restaurants and the imported corpus never overlap; Philadelphia is the largest slice and the default target for the first import.

```
modules/
  data/
    importers/
      yelp.py     ← maps Yelp JSON fields to credence schema
```

The same importer pattern is reusable in phase 3/4 for live Google Places / Yelp API ingestion.

### new schema (phase 2)

```sql
-- dynamic credibility (already implemented)
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

-- clustering (new)
CREATE TABLE clusters (
    id              INTEGER PRIMARY KEY,
    cuisine_id      INTEGER NOT NULL REFERENCES cuisines(id),
    label           TEXT,                  -- optional human label added later
    coherence_score REAL NOT NULL,         -- internal consistency, higher = more calibrated
    member_count    INTEGER NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE user_cluster_assignments (
    user_id       INTEGER NOT NULL REFERENCES users(id),
    cuisine_id    INTEGER NOT NULL REFERENCES cuisines(id),
    cluster_id    INTEGER NOT NULL REFERENCES clusters(id),
    confidence    REAL NOT NULL,           -- how strongly they belong to this cluster
    assigned_at   TEXT NOT NULL,
    PRIMARY KEY (user_id, cuisine_id)
);

CREATE TABLE cluster_restaurant_scores (
    cluster_id    INTEGER NOT NULL REFERENCES clusters(id),
    restaurant_id INTEGER NOT NULL REFERENCES restaurants(id),
    consensus     REAL NOT NULL,
    rater_count   INTEGER NOT NULL,
    last_updated  TEXT NOT NULL,
    PRIMARY KEY (cluster_id, restaurant_id)
);
```

All phase 1 tables unchanged. `trusted_sources` table is kept — it now seeds low `rating_deviation` and plants seeds into the expected calibrated cluster at initialization.

### infrastructure additions

- migrate from SQLite → Postgres (handles concurrent writes, better for jobs)
- add a credibility job that triggers on new `rating_events` rows
- add a nightly clustering job that recomputes cluster assignments and coherence
- jobs run synchronously in phase 2, async in phase 3

```
new rating inserted
        ↓
credibility job (updates user_credibility for that user × cuisine)
        ↓
update cluster_restaurant_scores for that user's cluster × restaurant
        ↓
ranking engine reads cluster consensus

nightly:
  cluster discovery job (rerun k-means, update assignments, recompute coherence)
```

### new modules

```
modules/
  credibility/
    score.py           ← phase 1 formula (done)
    dynamic.py         ← Glicko-inspired updates (done)
    seeds.py           ← seed trusted sources with low rating_deviation (done)
  clustering/
    discover.py        ← k-means on rating vectors per cuisine
    assign.py          ← assign users to clusters, store confidence
    consensus.py       ← compute cluster_restaurant_scores
    coherence.py       ← measure intra-cluster consistency
    seeds.py           ← plant trusted sources into expected calibrated cluster
  data/
    importers/
      yelp.py          ← bootstrap from Yelp Academic Dataset
```

### phase 2 build order (revised)

```
1. (done) Phase 1 formula + Glicko dynamic credibility + Bayesian ranking prior
2. Add cluster schema (3 new tables)
3. Write Yelp dataset importer → load volume needed for clusters to converge
4. Build cluster discovery (discover.py, assign.py) — k-means, k=4 starting point
5. Build coherence scoring (coherence.py)
6. Build cluster consensus computation (consensus.py)
7. Update alignment score to correlate against cluster consensus, not global
8. Update ranking to surface highest-coherence cluster consensus, with Bayesian fallback
9. Validate: equivalent of Taco Bell should score lower than equivalent of Ichiran
```

---

## phase 3 — real-time inference + ml-based clustering + ui v1

### what changes from phase 2

Two simultaneous evolutions:

**Infrastructure:** credibility computation moves fully async. The ranking engine reads cluster consensus scores from a fast cache (Redis) rather than computing on the fly. This is the core latency work.

**Algorithms:** k-means is replaced with **matrix factorization**. This is the first real ML in the system — it learns latent user and restaurant embeddings rather than working in raw rating space. Clusters emerge naturally without specifying k upfront.

### matrix factorization (replaces k-means)

```
rating matrix (users × restaurants)
        ↓
matrix factorization (e.g., ALS or SGD-based)
        ↓
user_embedding (users × latent_dims)        ← cluster space
restaurant_embedding (restaurants × latent_dims)
```

Latent dimensions are unlabeled but capture things like "appreciation for authenticity" or "sensitivity to price vs quality" — emergent properties of the data, not hand-coded features.

Clusters in phase 3 are computed in embedding space (still using something like k-means or HDBSCAN on top), but the embedding space itself is learned. This solves k-means' weaknesses:

```
k-means (phase 2):                  matrix factorization (phase 3):
  fixed k                             k emerges from embedding structure
  treats restaurants equally          weights restaurants by signal density
  hard cluster assignment             soft membership via embedding distance
  no cuisine-relationship awareness   relationships learned across cuisines
```

Cuisine graph distances can also be **learned** from rating patterns in phase 3 instead of manually curated — two cuisines whose ratings correlate in embedding space have low distance, regardless of what their hand-coded distance was.

### infrastructure

```
new rating event
        ↓
job queue (e.g. RQ or Celery)
        ↓
async credibility worker (updates affected user × cuisine pairs only)
        ↓
writes to Redis cache (keyed by user_id:cuisine_id and cluster_id:restaurant_id)
        ↓
ranking engine reads from Redis at query time (microseconds)
        ↓
falls back to Postgres if cache miss
```

Cache invalidation: TTL of 1 hour on credibility and cluster consensus scores. On new rating event, invalidate only affected keys.

### approximate nearest neighbors

As user base grows, full pairwise comparison for cluster assignment becomes expensive. FAISS (Meta, open source) provides efficient ANN search in embedding space. Instead of comparing every user to every other user, compute each user's approximate top-1000 most similar users and run credibility computations only within that neighborhood. Neighborhoods refresh nightly.

```
modules/
  recommendations/
    embeddings.py      ← matrix factorization training + storage
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
GET  /users/:id/cluster           which cluster user belongs to per cuisine (optional surface)
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

Functional, minimal interface for browsing restaurants, seeing credibility-weighted scores, and submitting ratings. Not polished — focused on validating the core experience.

Stack: React + TailwindCSS, calls the FastAPI backend.

Key screens:

```
/ (home)
  → list of restaurants sorted by weighted score
  → each card shows: name, cuisine, weighted score, rating count, confidence indicator

/restaurant/:id
  → restaurant detail
  → weighted score prominently (from surfaced cluster)
  → optional: show cluster breakdown — "casual cluster: 8.4, calibrated: 5.1"
    (transparency about why score differs from naive average)
  → per-rater breakdown: score, credibility weight for this cuisine
  → submit rating form (authenticated)

/user/:id
  → user profile
  → credibility scores per cuisine shown as a radar/bar chart
  → rating history
  → similar users (from embedding neighborhood)

/cuisines
  → browse by cuisine
  → leaderboard of top credibility raters per cuisine
```

Confidence indicator on restaurant cards: low rating count or low surfaced-cluster coherence shows a visual flag (e.g. "early" badge) so users understand the signal quality.

```
modules/
  ui/                  ← or separate repo: credence-web
    src/
      components/
        RestaurantCard.jsx
        RatingBreakdown.jsx
        ClusterBreakdown.jsx       ← optional, shows per-cluster scores
        CredibilityBadge.jsx
        CuisineRadar.jsx
      pages/
        Home.jsx
        Restaurant.jsx
        User.jsx
        Cuisines.jsx
      api/
        client.js
```

### latency targets

```
GET /restaurants/:id/score     < 50ms   (cache hit)
GET /restaurants/:id/score     < 200ms  (cache miss, recompute)
POST /ratings                  < 100ms  (write + async job enqueue)
credibility worker job         < 2s     (per user × cuisine update)
cluster assignment update      < 5s     (single user, single cuisine)
nightly embedding retrain      < 30min  (full population)
```

Measuring and hitting these targets is the core latency/infra work for phase 3.

---

## phase 4 — gnn-based credibility + stream processing + ui v2

### what changes from phase 3

Scale to millions of users. Move from async jobs to stream processing. Replace matrix factorization with a **graph neural network** that unifies clustering, credibility, and proximity into a single learned model. UI becomes a full product.

### graph neural network (replaces matrix factorization)

The entire user-restaurant-rating graph is fed to a GNN. Nodes: users and restaurants. Edges: rating events with score as edge weight. The model learns node embeddings by propagating information through the graph — essentially a learnable, differentiable version of PageRank.

```
input graph:
  user nodes — feature vector (cuisine experience, history length, etc.)
  restaurant nodes — feature vector (cuisine, location, price)
  edges — rating events with weights

GNN training:
  predict held-out ratings from graph structure
  learn embeddings that minimize prediction error

emergent properties:
  - clusters emerge as regions of embedding space
  - credibility emerges as embedding strength in cuisine-relevant region
  - proximity emerges as inter-cuisine embedding similarity
  - alignment emerges as agreement with high-density embedding regions
```

The hand-crafted α/β/γ weights from phases 1–2 disappear entirely. The GNN learns whatever weighting produces the best predictions of trusted-source-aligned ratings.

### pagerank-style credibility network

Network-level credibility propagation. Agreement from a highly credible rater gives you more credibility than agreement from an unknown rater.

```
for each new rating:
  agreement_signal = similarity(user_score, cluster_consensus_score)
  credibility_delta = agreement_signal × creditor_weight × learning_rate
  user.credibility_score += credibility_delta
  propagate partial delta to users in embedding neighborhood
```

In the GNN formulation, this propagation is the natural behavior of message passing across the graph — not a separate algorithm.

### infrastructure

```
rating event
        ↓
Kafka topic: rating_events
        ↓
stream processor (Flink or Spark Streaming)
  → credibility update consumer
  → cluster reassignment consumer (on significant embedding drift)
  → recommendation refresh consumer
        ↓
Redis cluster (credibility + cluster consensus cache, sharded)
Postgres (source of truth, read replicas for API)
GNN serving (online inference, embeddings updated incrementally)
FAISS index (rebuilt nightly from latest embeddings)
```

### ml infrastructure

```
ml/
  models/
    matrix_fact.py     ← phase 3 baseline, kept for benchmarking
    gnn.py             ← phase 4 model
  training/
    dataset.py         ← build graph from rating_events + trusted_sources
    train.py           ← training loop
    evaluate.py        ← holdout evaluation, prevent data leakage
  serving/
    inference.py       ← online inference for new ratings
    latency_bench.py   ← benchmark vs phase 3 baseline
    embedding_store.py ← serve learned embeddings to API
```

### ui v2 — full product

Polished mobile-first web app (or native iOS via React Native).

Additional screens and features beyond v1:

```
/discover
  → personalized feed based on embedding neighborhood + cluster coherence
  → "people like you rated this highly" surface (cluster-grounded)
  → filter by neighborhood, price, cuisine

/restaurant/:id (enhanced)
  → cluster breakdown with visual bar chart per cluster
  → show how score evolved over time as ratings accumulated
  → "your predicted score" using GNN inference on user's embedding
  → map + basic info from external API (Google Places)

/profile (own profile)
  → full taste profile: radar chart of credibility per cuisine
  → which cluster you belong to per cuisine (optional, transparent UX)
  → rating streak, consistency score
  → leaderboard position per cluster per cuisine

/leaderboards
  → top raters per cluster per cuisine, citywide
  → "verified palate" badge for users in high-coherence clusters

onboarding
  → new user rates 5-10 restaurants they've been to
  → embedding bootstraps immediately, cluster assignment within minutes
  → shown restaurants where their predicted cluster has high credibility
```

Authentication: full user accounts with OAuth (Google login at minimum). Rating history tied to account, credibility and cluster assignments persist across sessions.

---

## what makes credence different from standard collaborative filtering

Standard recommendation systems (Netflix, Spotify, Yelp) find users similar to you and recommend based on their behavior. They don't filter for **quality of taste** — they assume all user preferences are equally valid signal.

Credence's contribution on top of standard collaborative filtering:

```
ML handles:        finding the clusters (who rates similarly)
Credence adds:     weighting by cluster coherence (who rates correctly)
```

A high-coherence cluster — one where members consistently agree with each other on the same restaurants — is a strong signal of calibrated taste. Surfacing that cluster's consensus is what makes credence resistant to the "Taco Bell at 4.2" failure mode. ML alone doesn't give you this. The credibility layer is the novel intellectual contribution.

---

## open questions (carry into each phase)

- What is the floor for `credibility_score`? Can a user go to 0 or is there a minimum?
- Should cuisine distances be static (manual table) or learned from rating patterns? (Phase 3 learns them.)
- How do you handle a restaurant that spans two cuisines (e.g. Korean-Mexican fusion)?
- Moderation: what happens when a coordinated group tries to game the credibility system? (Cluster coherence helps — coordinated groups form a low-coherence cluster on real restaurants.)
- Should users be able to see their own credibility score and cluster assignment? Transparent or hidden?
- External data: when does it make sense to pull in Google Places / Yelp data to supplement seed restaurant metadata?
- For Phase 2 clustering: how do we evaluate cluster quality without ground truth labels? (Coherence score is one signal — others?)
- For Phase 3 embeddings: how often is "nightly retrain" enough? When does online learning become necessary?