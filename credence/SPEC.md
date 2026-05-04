# credence — spec

## what it is
A weighted restaurant rating system. A user's rating is weighted by their credibility for that cuisine type. Not all raters are equal — someone who consistently agrees with trusted food critics on Italian food carries more weight when rating Italian restaurants.

## credibility formula (locked)

```
w(u, c) = clamp(α·alignment + β·expertise + γ·proximity, 0, 1)
```

Weights: α=0.50, β=0.30, γ=0.20

### alignment_score
Pearson correlation between user's ratings and trusted source ratings on overlapping restaurants in cuisine C. Strongest signal. Falls back to 0 if no overlap with trusted sources.

### expertise_score
Log-normalized count of user's ratings in cuisine C:
```
log(n+1) / log(max_n+1)    # max_n = 20 (soft cap)
```

### proximity_transfer
Expertise borrowed from adjacent cuisines via the cuisine graph:
```
Σ expertise(user, cuisine_j) * (1 - distance(C, cuisine_j))
  for all j ≠ C within distance threshold (0.6)
```
Normalized to [0,1] by dividing by the max possible sum.

## ranking formula
```
weighted_avg(restaurant) = Σ(score_i * w_i) / Σ(w_i)
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
- **Phase 1** (now): data model + seed data + credibility formula (hand-tuned α/β/γ) + ranking engine
- **Phase 2**: replace α/β/γ with a trained model that predicts trusted-source ratings
- **Phase 3**: latency optimization on the credibility inference path
