# credibility — how much does this rater's opinion count?

Computes a weight per **(user, cuisine)** pair. Nothing here is global: a
user can be highly credible on Japanese and noise on Italian. Every other
part of the system (ranking, cluster consensus) consumes these weights; this
package never decides a restaurant's score itself.

Two generations coexist:

- **Phase 1 (locked formula):** `w = clamp(0.50·alignment + 0.30·expertise + 0.20·proximity, 0, 1)`
  — recomputed from the event log on every call, no stored state.
- **Phase 2 (Glicko-inspired):** stored per-(user, cuisine) state
  (`credibility_score`, `rating_deviation`, `volatility`) updated after every
  rating event. Effective weight = `credibility_score × (1 − RD) × (1 + 0.20·proximity)`.

Callers use the fallback chain: phase-2 effective weight when a
`user_credibility` row exists, phase-1 formula otherwise.

## files

| file | in charge of |
|---|---|
| `score.py` | Phase-1 formula entry point. Holds the locked α/β/γ weights and the redistribution rule: when alignment has insufficient overlap, α's weight is split proportionally across expertise and proximity instead of capping the score. |
| `alignment.py` | "Does this user agree with people worth agreeing with?" Two comparison sets: `cluster_alignment_score()` (phase 2) correlates the user's latest ratings against **their own cluster's consensus**; it falls back to `alignment_score()` (phase 1), which correlates against the trusted-source average. Raw Pearson r, not remapped; both require ≥ 3 overlapping restaurants (`MIN_OVERLAP`) or return `(0.0, False)`. |
| `expertise.py` | "How much evidence do we have about this user in this cuisine?" Log-normalized rating count: `log(n+1) / log(21)`, soft-capped at `MAX_N = 20` ratings. |
| `proximity.py` | "Does adjacent-cuisine experience count for anything?" Expertise borrowed from cuisines within `THRESHOLD` distance (strict `< 0.6`), each discounted by `1 − distance`, normalized to [0, 1]. |
| `dynamic.py` | The phase-2 Glicko-inspired update, fired synchronously by `actions.submit_rating()`. Compares the new rating to the credibility-weighted community consensus: agreement nudges credibility up and RD down; divergence nudges credibility down and volatility up. All tuning constants (`LEARNING_RATE`, `RD_DECAY`, `DAMPEN`, …) live at the top of this file. Also exports `user_effective_weight()`, the phase-2 half of the fallback chain. |
| `seeds.py` | Bootstraps trusted sources as **high-confidence seeds, not ground truth**: writes their `user_credibility` rows with `rating_deviation = 0.3` (vs 1.0 default) so their ratings carry weight from day one. Their scores can still fall; never raises an earned-lower RD. |

## invariants enforced here

- Alignment needs ≥ 3 overlapping restaurants with its comparison set, else `(0.0, False)`.
- Proximity's distance threshold is strict (`< 0.6`, not `≤`).
- Cluster-consensus rows used for alignment need ≥ 2 raters (`MIN_CONSENSUS_RATERS`) so a user doesn't correlate against their own rating.

See `DECISIONS.md` for why raw r (not `(r+1)/2`) and the full fallback semantics.
