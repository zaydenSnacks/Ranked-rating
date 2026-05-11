from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..credibility.dynamic import user_effective_weight
from ..credibility.score import credibility_score
from ..data.models import RatingEvent, Restaurant

PRIOR_WEIGHT = 3.0  # equivalent to 3 ratings at global average


def _global_average(session: Session) -> float:
    result = session.scalar(select(func.avg(RatingEvent.score)))
    return float(result) if result is not None else 5.0


def _weight(session: Session, user_id: int, cuisine_id: int) -> float:
    w = user_effective_weight(session, user_id, cuisine_id)
    if w is not None:
        return w
    return credibility_score(session, user_id, cuisine_id)


def restaurant_score(session: Session, restaurant_id: int) -> float:
    """Credibility-weighted Bayesian average rating for a restaurant.

    Uses phase-2 effective weights when user_credibility rows exist, falls
    back to phase-1 credibility_score() for users without a record.
    Prior anchors the score toward the global average until enough credible
    ratings accumulate.
    """
    restaurant = session.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise ValueError(f"Restaurant {restaurant_id} not found")

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
