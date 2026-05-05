from sqlalchemy.orm import Session

from .alignment import alignment_score
from .expertise import expertise_score
from .proximity import proximity_score

W_ALIGNMENT = 0.50  # α
W_EXPERTISE  = 0.30  # β
W_PROXIMITY  = 0.20  # γ


def credibility_score(
    session: Session,
    user_id: int,
    cuisine_id: int,
) -> float:
    """Weighted credibility of a user for a given cuisine, clamped to [0, 1].

    Implements: clamp(α·alignment + β·expertise + γ·proximity, 0, 1)

    When alignment has insufficient trusted-source overlap, α's weight is
    redistributed proportionally across expertise and proximity so the score
    stays in [0, 1] rather than being artificially capped at 0.5.
    """
    align, sufficient_overlap = alignment_score(session, user_id, cuisine_id)
    exp = expertise_score(session, user_id, cuisine_id)
    prox = proximity_score(session, user_id, cuisine_id)

    if not sufficient_overlap:
        # Divide by the sum of remaining weights (not 1.0) so the result is
        # still a weighted average in [0, 1] rather than a raw partial sum.
        w = (W_EXPERTISE * exp + W_PROXIMITY * prox) / (W_EXPERTISE + W_PROXIMITY)
    else:
        w = W_ALIGNMENT * align + W_EXPERTISE * exp + W_PROXIMITY * prox

    return max(0.0, min(1.0, w))
