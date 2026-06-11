"""
Per-cluster restaurant consensus scores.

Same Bayesian-prior formula as ranking.restaurant_score(), applied within the
cluster instead of globally: each member's rating is weighted by their
effective credibility, and the prior anchors thin clusters toward the global
average. Rows are written for every (cluster, restaurant) with at least one
rater; the MIN_RATERS_PER_CLUSTER surfacing threshold is the ranking layer's
job, and storing the thin rows keeps them inspectable.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..credibility.dynamic import user_effective_weight
from ..credibility.score import credibility_score
from ..data.models import ClusterRestaurantScore, RatingEvent

MIN_RATERS_PER_CLUSTER = 5    # members rating a restaurant before its cluster score can surface
PRIOR_WEIGHT           = 3.0  # matches ranking.PRIOR_WEIGHT (not imported: ranking will import us in step 5)


def _rater_weight(session: Session, user_id: int, cuisine_id: int) -> float:
    # same fallback chain as ranking._weight: phase-2 effective weight when
    # credibility state exists, phase-1 formula otherwise
    w = user_effective_weight(session, user_id, cuisine_id)
    if w is not None:
        return w
    return credibility_score(session, user_id, cuisine_id)


def _global_average(session: Session) -> float:
    result = session.scalar(select(func.avg(RatingEvent.score)))
    return float(result) if result is not None else 5.0


def compute_cluster_scores(
    session: Session,
    cuisine_id: int,
    members_by_cluster: dict[int, list[int]],
    ratings: dict[tuple[int, int], float],
    now: str,
) -> int:
    """Write cluster_restaurant_scores rows for one cuisine. Returns row count.

    `ratings` is the latest-rating map from discover.build_rating_matrix, so
    consensus sees exactly the data the clusters were discovered from.
    """
    global_avg = _global_average(session)
    count = 0

    for cluster_id, member_ids in members_by_cluster.items():
        members = set(member_ids)
        by_restaurant: dict[int, list[tuple[int, float]]] = {}
        for (user_id, restaurant_id), score in ratings.items():
            if user_id in members:
                by_restaurant.setdefault(restaurant_id, []).append((user_id, score))

        for restaurant_id, raters in by_restaurant.items():
            weights = [_rater_weight(session, uid, cuisine_id) for uid, _ in raters]
            numerator = PRIOR_WEIGHT * global_avg + sum(
                score * w for (_, score), w in zip(raters, weights)
            )
            denominator = PRIOR_WEIGHT + sum(weights)
            session.add(ClusterRestaurantScore(
                cluster_id=cluster_id,
                restaurant_id=restaurant_id,
                consensus=numerator / denominator,
                rater_count=len(raters),
                last_updated=now,
            ))
            count += 1

    return count
