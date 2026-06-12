from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..clustering.coherence import MIN_COHERENCE
from ..clustering.consensus import MIN_RATERS_PER_CLUSTER
from ..credibility.dynamic import user_effective_weight
from ..credibility.score import credibility_score
from ..data.models import Cluster, ClusterRestaurantScore, RatingEvent, Restaurant

PRIOR_WEIGHT = 3.0  # equivalent to 3 ratings at global average


class SurfacedScore(NamedTuple):
    consensus:   float
    cluster:     Cluster
    rater_count: int


def surfaced_cluster_score(
    session: Session, restaurant_id: int, cuisine_id: int
) -> SurfacedScore | None:
    """The cluster consensus that should represent this restaurant, if any.

    Among the cuisine's clusters that pass both gates — coherence >=
    MIN_COHERENCE and >= MIN_RATERS_PER_CLUSTER members rating this
    restaurant — the highest-coherence one wins. Coherence, never
    member_count: a small cluster that agrees closely beats a large casual
    one, which is the whole point. Returns None when no cluster qualifies
    (callers fall back to the Bayesian prior).
    """
    row = session.execute(
        select(ClusterRestaurantScore.consensus, ClusterRestaurantScore.rater_count, Cluster)
        .join(Cluster, ClusterRestaurantScore.cluster_id == Cluster.id)
        .where(ClusterRestaurantScore.restaurant_id == restaurant_id)
        .where(ClusterRestaurantScore.rater_count >= MIN_RATERS_PER_CLUSTER)
        .where(Cluster.cuisine_id == cuisine_id)
        .where(Cluster.coherence_score >= MIN_COHERENCE)
        .order_by(Cluster.coherence_score.desc(), Cluster.id)
        .limit(1)
    ).first()
    if row is None:
        return None
    return SurfacedScore(consensus=row.consensus, cluster=row.Cluster, rater_count=row.rater_count)


def _global_average(session: Session) -> float:
    result = session.scalar(select(func.avg(RatingEvent.score)))
    return float(result) if result is not None else 5.0


def _weight(session: Session, user_id: int, cuisine_id: int) -> float:
    w = user_effective_weight(session, user_id, cuisine_id)
    if w is not None:
        return w
    return credibility_score(session, user_id, cuisine_id)


def restaurant_score(session: Session, restaurant_id: int) -> float:
    """Final score for a restaurant.

    Phase 2 cluster-aware path: when a sufficiently coherent cluster has
    enough raters for this restaurant, its consensus IS the score — volume
    doesn't get to outvote calibration. Otherwise: credibility-weighted
    Bayesian average over all raters (phase-2 effective weights when
    user_credibility rows exist, phase-1 credibility_score() for users
    without a record), anchored toward the global average by the prior.
    """
    restaurant = session.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise ValueError(f"Restaurant {restaurant_id} not found")

    surfaced = surfaced_cluster_score(session, restaurant_id, restaurant.cuisine_id)
    if surfaced is not None:
        return surfaced.consensus

    rows = session.execute(
        select(RatingEvent.user_id, RatingEvent.score)
        .where(RatingEvent.restaurant_id == restaurant_id)
    ).all()

    if not rows:
        return 0.0

    global_avg = _global_average(session)
    weights = [_weight(session, r.user_id, restaurant.cuisine_id) for r in rows]

    numerator   = PRIOR_WEIGHT * global_avg + sum(r.score * w for r, w in zip(rows, weights))
    denominator = PRIOR_WEIGHT + sum(weights)

    return numerator / denominator
