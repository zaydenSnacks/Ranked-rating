import math

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from ..data.models import CuisineDistance, RatingEvent, Restaurant

THRESHOLD = 0.6
MAX_N = 20  # must match expertise.py


def proximity_score(session: Session, user_id: int, cuisine_id: int) -> float:
    """Expertise borrowed from adjacent cuisines, normalized to [0, 1].

    For each cuisine j within THRESHOLD distance of C:
      contribution = expertise(user, j) * (1 - distance(C, j))
    Normalized by the max possible sum (assuming expertise=1 on all adjacent cuisines).
    """
    rows = session.execute(
        select(
            CuisineDistance.distance,
            func.count(RatingEvent.id).label("n"),
        )
        .join(Restaurant, Restaurant.cuisine_id == CuisineDistance.cuisine_b_id)
        .outerjoin(
            RatingEvent,
            and_(
                RatingEvent.restaurant_id == Restaurant.id,
                RatingEvent.user_id == user_id,
            ),
        )
        .where(CuisineDistance.cuisine_a_id == cuisine_id)
        .where(CuisineDistance.distance < THRESHOLD)
        .group_by(CuisineDistance.cuisine_b_id, CuisineDistance.distance)
    ).all()

    if not rows:
        return 0.0

    max_sum = sum(1 - r.distance for r in rows)
    if max_sum == 0.0:
        return 0.0

    weighted_sum = sum(
        math.log(r.n + 1) / math.log(MAX_N + 1) * (1 - r.distance)
        for r in rows
    )

    return weighted_sum / max_sum
