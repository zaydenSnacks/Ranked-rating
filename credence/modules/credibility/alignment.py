from typing import NamedTuple

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..data.models import (
    ClusterRestaurantScore, RatingEvent, Restaurant, TrustedSource,
    UserClusterAssignment,
)

MIN_OVERLAP = 3
MIN_CONSENSUS_RATERS = 2  # a 1-rater consensus is mostly the user's own rating + prior


class AlignmentResult(NamedTuple):
    score: float
    sufficient_overlap: bool


def alignment_score(session: Session, user_id: int, cuisine_id: int) -> AlignmentResult:
    """Pearson correlation between the user's ratings and avg trusted-source ratings.

    Requires at least MIN_OVERLAP restaurants rated by both the user and at least
    one trusted source. Returns (0.0, sufficient_overlap=False) when that threshold
    isn't met — callers should redistribute weight rather than treating 0 as a
    real correlation score.
    """
    # Average all trusted-source ratings per restaurant before correlating.
    # This collapses multiple trusted sources on the same restaurant to one value
    # so no single trusted source dominates the signal.
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

    # Restrict to restaurants the user also rated in this cuisine.
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

    # corrcoef returns a 2x2 correlation matrix; [0, 1] is the off-diagonal
    # element, which is the correlation between the two input arrays.
    corr = float(np.corrcoef(user_scores, trusted_scores)[0, 1])
    # Zero variance in either array (all identical scores) produces NaN.
    if np.isnan(corr):
        corr = 0.0

    return AlignmentResult(score=corr, sufficient_overlap=True)


def cluster_alignment_score(session: Session, user_id: int, cuisine_id: int) -> AlignmentResult:
    """Phase 2: Pearson correlation against the user's cluster consensus.

    The comparison set is the consensus of the user's own taste cluster —
    agreement with people who rate like you, not with a global anchor. Falls
    back to phase-1 alignment_score() (trusted-source average) whenever the
    cluster data is insufficient: no assignment, or fewer than MIN_OVERLAP
    restaurants shared with usable consensus rows.

    Consensus rows need >= MIN_CONSENSUS_RATERS raters: the user's own rating
    is part of their cluster's consensus, and against a 1-rater row they would
    mostly be correlating with themselves.
    """
    assignment = session.get(UserClusterAssignment, (user_id, cuisine_id))
    if assignment is None:
        return alignment_score(session, user_id, cuisine_id)

    consensus = {
        row.restaurant_id: row.consensus
        for row in session.execute(
            select(ClusterRestaurantScore.restaurant_id, ClusterRestaurantScore.consensus)
            .where(ClusterRestaurantScore.cluster_id == assignment.cluster_id)
            .where(ClusterRestaurantScore.rater_count >= MIN_CONSENSUS_RATERS)
        )
    }

    # latest rating per restaurant — same convention as the clustering module
    rows = session.execute(
        select(RatingEvent.restaurant_id, RatingEvent.score)
        .join(Restaurant, RatingEvent.restaurant_id == Restaurant.id)
        .where(RatingEvent.user_id == user_id)
        .where(Restaurant.cuisine_id == cuisine_id)
        .order_by(RatingEvent.id)
    ).all()
    latest = {r.restaurant_id: r.score for r in rows}

    overlap = sorted(rid for rid in latest if rid in consensus)
    if len(overlap) < MIN_OVERLAP:
        return alignment_score(session, user_id, cuisine_id)

    corr = float(np.corrcoef(
        [latest[rid] for rid in overlap],
        [consensus[rid] for rid in overlap],
    )[0, 1])
    if np.isnan(corr):
        corr = 0.0

    return AlignmentResult(score=corr, sufficient_overlap=True)
