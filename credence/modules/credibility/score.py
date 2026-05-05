from sqlalchemy.orm import Session

from .alignment import alignment_score
from .expertise import expertise_score

ALPHA = 0.50
BETA = 0.30
GAMMA = 0.20


def credibility_score(
    session: Session,
    user_id: int,
    cuisine_id: int,
    proximity: float = 0.0,
) -> float:
    align, sufficient_overlap = alignment_score(session, user_id, cuisine_id)
    exp = expertise_score(session, user_id, cuisine_id)

    if not sufficient_overlap:
        w = (BETA * exp + GAMMA * proximity) / (BETA + GAMMA)
    else:
        w = ALPHA * align + BETA * exp + GAMMA * proximity

    return max(0.0, min(1.0, w))
