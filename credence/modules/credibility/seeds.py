"""
Seed user_credibility for trusted sources with a low initial rating_deviation.

Trusted sources aren't hardcoded ground truth in phase 2 — they're high-confidence
seeds. Their credibility_score can rise or fall like any user's, but they start with
rating_deviation=0.3 (vs 1.0 for regular users), so the system trusts its estimate
of them earlier and their ratings carry meaningful weight from day one.

Run once during phase 2 migration, then again whenever a new trusted source is added.
Idempotent: existing records are only updated if their current RD is above TRUSTED_RD.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..data.models import CredibilityHistory, RatingEvent, Restaurant, TrustedSource, UserCredibility

TRUSTED_RD    = 0.3   # starting rating_deviation for trusted sources
DEFAULT_CS    = 0.5   # starting credibility_score (same as any user)
DEFAULT_VOL   = 0.06  # starting volatility


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def seed_trusted_sources(session: Session) -> int:
    """Write user_credibility rows for every (trusted_source, cuisine) pair.

    Returns the number of rows created or updated.
    """
    trusted_user_ids = list(session.scalars(select(TrustedSource.user_id)))
    if not trusted_user_ids:
        return 0

    # Every cuisine a trusted source has rated — these are the cuisines
    # where they should carry authority from day one.
    pairs = session.execute(
        select(RatingEvent.user_id, Restaurant.cuisine_id)
        .join(Restaurant, RatingEvent.restaurant_id == Restaurant.id)
        .where(RatingEvent.user_id.in_(trusted_user_ids))
        .distinct()
    ).all()

    count = 0
    now = _now_iso()

    for user_id, cuisine_id in pairs:
        existing = session.get(UserCredibility, (user_id, cuisine_id))

        if existing is None:
            record = UserCredibility(
                user_id=user_id,
                cuisine_id=cuisine_id,
                credibility_score=DEFAULT_CS,
                rating_deviation=TRUSTED_RD,
                volatility=DEFAULT_VOL,
                last_updated=now,
            )
            session.add(record)
            session.add(CredibilityHistory(
                user_id=user_id,
                cuisine_id=cuisine_id,
                credibility_score=DEFAULT_CS,
                rating_deviation=TRUSTED_RD,
                recorded_at=now,
            ))
            count += 1

        elif existing.rating_deviation > TRUSTED_RD:
            # Already tracked but not yet marked as trusted — lower the RD.
            # Never raise RD: if they've earned below TRUSTED_RD through
            # consistent agreement, that should be preserved.
            existing.rating_deviation = TRUSTED_RD
            existing.last_updated = now
            session.add(CredibilityHistory(
                user_id=user_id,
                cuisine_id=cuisine_id,
                credibility_score=existing.credibility_score,
                rating_deviation=TRUSTED_RD,
                recorded_at=now,
            ))
            count += 1

    return count
