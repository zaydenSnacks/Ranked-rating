"""
Glicko-inspired credibility update, called synchronously after each rating event.

After a new rating is inserted we compare the user's score to the
credibility-weighted community consensus for that restaurant.
  - Agreement  → credibility_score nudges up, rating_deviation falls
  - Divergence → credibility_score nudges down, volatility rises

Nudge magnitude is proportional to the total effective weight of existing raters
for that restaurant (high-credibility community = stronger signal). A DAMPEN prior
prevents low-sample communities from swinging credibility too fast.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..data.models import CredibilityHistory, RatingEvent, UserCredibility
from .proximity import proximity_score

LEARNING_RATE        = 0.05   # max credibility_score shift per event
RD_DECAY             = 0.05   # fraction by which RD falls on agreement
VOL_BUMP             = 0.01   # amount volatility rises on divergence
RD_FLOOR             = 0.10   # rating_deviation lower bound
VOL_FLOOR            = 0.02   # volatility lower bound
VOL_CAP              = 0.15   # volatility upper bound
SCORE_RANGE          = 9.0    # assumes scores in [1, 10]
DAMPEN               = 3.0    # prior weight; prevents thin communities from dominating
EXPERTISE_BOOST_WT   = 0.20   # matches phase-2 formula coefficient


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _effective_weight(
    session: Session,
    user_id: int,
    cuisine_id: int,
    credibility_score: float,
    rating_deviation: float,
) -> float:
    """Phase-2 effective weight: credibility × (1 − RD) × expertise_boost."""
    prox = proximity_score(session, user_id, cuisine_id)
    expertise_boost = 1 + EXPERTISE_BOOST_WT * prox
    return credibility_score * (1 - rating_deviation) * expertise_boost


def user_effective_weight(session: Session, user_id: int, cuisine_id: int) -> float | None:
    """Effective weight for a (user, cuisine) pair read from stored credibility state.

    Returns None when no user_credibility record exists — callers should fall back
    to the phase-1 credibility_score() formula.
    """
    rec = session.get(UserCredibility, (user_id, cuisine_id))
    if rec is None:
        return None
    return _effective_weight(session, user_id, cuisine_id, rec.credibility_score, rec.rating_deviation)


def _community_consensus(
    session: Session,
    restaurant_id: int,
    exclude_user_id: int,
    cuisine_id: int,
) -> tuple[float | None, float]:
    """Return (weighted_consensus, total_weight) from all other raters.

    Falls back to simple average when all effective weights are zero (e.g. all
    raters are new users with rating_deviation=1.0). Returns (None, 0.0) when
    no other raters exist at all.
    """
    rows = session.execute(
        select(RatingEvent.user_id, RatingEvent.score)
        .where(RatingEvent.restaurant_id == restaurant_id)
        .where(RatingEvent.user_id != exclude_user_id)
    ).all()

    if not rows:
        return None, 0.0

    weighted_sum = 0.0
    total_weight = 0.0
    scores = []

    for row in rows:
        scores.append(row.score)
        rec = session.get(UserCredibility, (row.user_id, cuisine_id))
        cs = rec.credibility_score if rec else 0.5
        rd = rec.rating_deviation  if rec else 1.0
        w = _effective_weight(session, row.user_id, cuisine_id, cs, rd)
        weighted_sum += row.score * w
        total_weight += w

    if total_weight == 0.0:
        return sum(scores) / len(scores), 0.0

    return weighted_sum / total_weight, total_weight


def _get_or_init(session: Session, user_id: int, cuisine_id: int) -> UserCredibility:
    record = session.get(UserCredibility, (user_id, cuisine_id))
    if record is None:
        record = UserCredibility(
            user_id=user_id,
            cuisine_id=cuisine_id,
            credibility_score=0.5,
            rating_deviation=1.0,
            volatility=0.06,
            last_updated=_now_iso(),
        )
        session.add(record)
    return record


def _append_history(session: Session, record: UserCredibility) -> None:
    session.add(CredibilityHistory(
        user_id=record.user_id,
        cuisine_id=record.cuisine_id,
        credibility_score=record.credibility_score,
        rating_deviation=record.rating_deviation,
        recorded_at=_now_iso(),
    ))


def update_user_credibility(
    session: Session,
    user_id: int,
    cuisine_id: int,
    user_score: float,
    restaurant_id: int,
) -> None:
    """Update (user, cuisine) credibility after a new rating is recorded.

    Should be called within the same transaction as the rating_events INSERT
    so both commits or both roll back together.
    """
    consensus, community_weight = _community_consensus(
        session, restaurant_id, user_id, cuisine_id
    )

    record = _get_or_init(session, user_id, cuisine_id)

    if consensus is None:
        # First rater for this restaurant — record exists, no agreement signal yet
        record.last_updated = _now_iso()
        _append_history(session, record)
        return

    # 1 = perfect agreement with consensus, 0 = maximum possible divergence
    agreement = 1.0 - abs(user_score - consensus) / SCORE_RANGE

    # Scales nudge by community credibility; low-weight community gives a weak signal
    nudge_scale = community_weight / (community_weight + DAMPEN)

    if agreement >= 0.5:
        delta = LEARNING_RATE * nudge_scale * (agreement - 0.5) * 2
        record.credibility_score = min(1.0, record.credibility_score + delta)
        record.rating_deviation  = max(RD_FLOOR, record.rating_deviation - RD_DECAY * nudge_scale)
    else:
        delta = LEARNING_RATE * nudge_scale * (0.5 - agreement) * 2
        record.credibility_score = max(0.0, record.credibility_score - delta)
        record.volatility        = min(VOL_CAP, record.volatility + VOL_BUMP * nudge_scale)

    record.last_updated = _now_iso()
    _append_history(session, record)
