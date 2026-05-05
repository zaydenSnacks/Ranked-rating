from typing import NamedTuple

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..data.models import RatingEvent, Restaurant, TrustedSource

MIN_OVERLAP = 3


class AlignmentResult(NamedTuple):
    score: float
    sufficient_overlap: bool


def alignment_score(session: Session, user_id: int, cuisine_id: int) -> AlignmentResult:
    trusted_avg_sub = (
        select(
            RatingEvent.restaurant_id,
            func.avg(RatingEvent.score).label("trusted_avg"),
        )
        .join(TrustedSource, RatingEvent.user_id == TrustedSource.user_id)
        .join(Restaurant, RatingEvent.restaurant_id == Restaurant.id)
        .where(Restaurant.cuisine_id == cuisine_id)
        .group_by(RatingEvent.restaurant_id)
        .subquery()
    )

    rows = session.execute(
        select(RatingEvent.score, trusted_avg_sub.c.trusted_avg)
        .join(trusted_avg_sub, RatingEvent.restaurant_id == trusted_avg_sub.c.restaurant_id)
        .join(Restaurant, RatingEvent.restaurant_id == Restaurant.id)
        .where(RatingEvent.user_id == user_id)
        .where(Restaurant.cuisine_id == cuisine_id)
    ).all()

    if len(rows) < MIN_OVERLAP:
        return AlignmentResult(score=0.0, sufficient_overlap=False)

    user_scores = [r.score for r in rows]
    trusted_scores = [r.trusted_avg for r in rows]

    corr = float(np.corrcoef(user_scores, trusted_scores)[0, 1])
    if np.isnan(corr):
        corr = 0.0

    return AlignmentResult(score=corr, sufficient_overlap=True)
