"""
Plant trusted sources into the expected calibrated cluster.

The expected calibrated cluster is the one whose centroid is nearest to the
trusted sources' mean rating vector — they were hand-picked for calibrated
taste, so where their collective palate points is the best prior for "the
calibrated group". All trusted sources with a vector in the cuisine are moved
there before assignments persist.

This is a soft prior, not ground truth: planting only adjusts this run's
labels. The next recluster recomputes everything from the event log, so a
trusted source whose ratings drift away from the calibrated group will be
planted into a centroid that has drifted with the group — and their
credibility falls independently via the Glicko updates.
"""
from __future__ import annotations

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..data.models import TrustedSource


def plant_trusted_seeds(
    session: Session,
    matrix,
    labels: np.ndarray,
    centroids: np.ndarray,
) -> tuple[np.ndarray, set[int]]:
    """Move trusted sources to the centroid nearest their mean vector.

    Returns (updated labels, planted user ids). No-op when no trusted source
    has a rating vector in this cuisine.
    """
    trusted_ids = set(session.scalars(select(TrustedSource.user_id)))
    rows = [i for i, uid in enumerate(matrix.user_ids) if uid in trusted_ids]
    if not rows:
        return labels, set()

    mean_vector = matrix.X[rows].mean(axis=0)
    target = int(np.linalg.norm(centroids - mean_vector, axis=1).argmin())

    labels = labels.copy()
    labels[rows] = target
    return labels, {matrix.user_ids[i] for i in rows}
