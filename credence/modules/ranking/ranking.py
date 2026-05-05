from sqlalchemy import select
from sqlalchemy.orm import Session

from ..credibility.score import credibility_score
from ..data.models import RatingEvent, Restaurant


def restaurant_score(session: Session, restaurant_id: int) -> float:
    """Credibility-weighted average rating for a restaurant.

    Falls back to a simple average when all credibility weights are 0
    (e.g. no rater has any history in the relevant cuisine).
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

    weights = [
        credibility_score(session, r.user_id, restaurant.cuisine_id)
        for r in rows
    ]

    total_weight = sum(weights)

    if total_weight == 0.0:
        return sum(r.score for r in rows) / len(rows)

    return sum(r.score * w for r, w in zip(rows, weights)) / total_weight
