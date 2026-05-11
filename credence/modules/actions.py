"""
Entry point for submitting a rating. Atomically inserts the rating event and
fires the credibility update in the same transaction, matching the phase-2
job flow from the spec:

  new rating inserted
        ↓
  credibility job (same transaction)
        ↓
  ranking engine reads from user_credibility
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .credibility.dynamic import update_user_credibility
from .data.models import RatingEvent, Restaurant


def submit_rating(
    session: Session,
    user_id: int,
    restaurant_id: int,
    score: float,
) -> RatingEvent:
    """Insert a rating event and update (user, cuisine) credibility atomically.

    Caller is responsible for committing or rolling back the session.
    """
    restaurant = session.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise ValueError(f"Restaurant {restaurant_id} not found")

    event = RatingEvent(
        user_id=user_id,
        restaurant_id=restaurant_id,
        score=score,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    session.add(event)
    session.flush()  # assign PK without committing; keeps both ops in one transaction

    update_user_credibility(
        session=session,
        user_id=user_id,
        cuisine_id=restaurant.cuisine_id,
        user_score=score,
        restaurant_id=restaurant_id,
    )

    return event
