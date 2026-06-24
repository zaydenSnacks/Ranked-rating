"""
Cluster coherence: average pairwise Pearson correlation between members,
computed over the restaurants each pair actually *co-rated* — not over
cuisine-average-filled vectors. High coherence = members agree where they
overlap. This asks "when these people rate the same place, do they agree?"

The earlier version correlated full, fill-imputed rating vectors, so two members
who never co-rated still correlated at ~0; at scale (sparse real data) that made
coherence measure co-rating *density*, not taste agreement, and surfacing never
fired — only 1 cluster in the whole system passed MIN_COHERENCE. See DECISIONS.md
"first full-scale clustering run" / "coherence redefinition".

Coherence is the surfacing criterion — a small high-coherence cluster beats a
large low-coherence one (never member_count). Raw r is used, not the (r+1)/2
remap alignment uses: anti-correlated members should drag coherence negative,
and MIN_COHERENCE then reads as "members genuinely agree".
"""
from __future__ import annotations

import itertools
from collections import defaultdict

import numpy as np

MIN_COHERENCE          = 0.50  # below this a cluster is not "calibrated enough" to surface
MIN_PAIR_OVERLAP       = 3     # co-rated restaurants a member pair needs before their r counts
MIN_CONTRIBUTING_PAIRS = 3     # qualifying pairs a cluster needs before its coherence is trusted


def coherence_score(member_ratings: list[dict[int, float]]) -> float:
    """Average pairwise Pearson r over members' co-rated restaurants.

    `member_ratings[i]` maps restaurant_id → member i's latest real score (no
    fill values). A member pair contributes a correlation only when they share
    at least MIN_PAIR_OVERLAP co-rated restaurants — matching alignment's
    MIN_OVERLAP=3 "enough points to trust a correlation" rule. A zero-variance
    qualifying pair (a member who gave every shared restaurant the same score)
    yields NaN and contributes 0 — no signal, not agreement. When fewer than
    MIN_CONTRIBUTING_PAIRS pairs qualify, agreement is unmeasurable and coherence
    is 0.0 so the cluster cannot surface.

    Pure python/numpy (no DB) so viz can mirror it exactly. The inverted index
    visits only members who actually co-rated, so this is sparse — it replaces
    the old dense n×n np.corrcoef matrix (O(n²·m), ~1.5 GB on the 14k-member
    American cluster) entirely.
    """
    if len(member_ratings) < 2:
        return 0.0

    # restaurant_id → [(member_idx, score), ...]; only members who rated it. Built
    # in ascending member order (enumerate), so each list is already sorted by i.
    by_restaurant: dict[int, list[tuple[int, float]]] = defaultdict(list)
    for i, ratings in enumerate(member_ratings):
        for rid, score in ratings.items():
            by_restaurant[rid].append((i, score))

    # Accumulate each co-rating pair's aligned score lists. Pairs that never share
    # a restaurant never appear here, so the ~88% zero-overlap pairs cost nothing —
    # total work is bounded by Σ C(raters_per_restaurant, 2), not C(members, 2).
    pair_scores: dict[tuple[int, int], tuple[list[float], list[float]]] = defaultdict(
        lambda: ([], [])
    )
    for raters in by_restaurant.values():
        for (i, si), (j, sj) in itertools.combinations(raters, 2):
            xs, ys = pair_scores[(i, j)]
            xs.append(si)
            ys.append(sj)

    corrs: list[float] = []
    for xs, ys in pair_scores.values():
        if len(xs) < MIN_PAIR_OVERLAP:
            continue
        a, b = np.asarray(xs), np.asarray(ys)
        if a.std() == 0 or b.std() == 0:
            corrs.append(0.0)  # zero variance → no signal, not agreement
        else:
            corrs.append(float(np.corrcoef(a, b)[0, 1]))

    if len(corrs) < MIN_CONTRIBUTING_PAIRS:
        return 0.0
    return float(np.mean(corrs))
