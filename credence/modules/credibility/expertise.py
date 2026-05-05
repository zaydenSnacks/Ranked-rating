import math

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..data.models import RatingEvent, Restaurant

MAX_N = 20


def expertise_score(session: Session, user_id: int, cuisine_id: int) -> float:
    n = session.scalar(
        select(func.count())
        .select_from(RatingEvent)
        .join(Restaurant, RatingEvent.restaurant_id == Restaurant.id)
        .where(RatingEvent.user_id == user_id)
        .where(Restaurant.cuisine_id == cuisine_id)
    )
    return math.log(n + 1) / math.log(MAX_N + 1)
