"""
Persist user → cluster assignments with a confidence value.

Confidence = 1 − d_nearest / d_second_nearest: 0 when the user sits exactly
between two centroids, approaching 1 when the assigned centroid is far closer
than any alternative. Planted trusted sources get confidence 1.0 — their
placement is a prior, not a distance measurement.
"""
from __future__ import annotations

import numpy as np
from sqlalchemy.orm import Session

from ..data.models import UserClusterAssignment


def assignment_confidence(x: np.ndarray, centroids: np.ndarray, label: int) -> float:
    """Confidence in [0, 1] that `label` is the right cluster for vector x."""
    if len(centroids) < 2:
        return 1.0
    dists = np.linalg.norm(centroids - x, axis=1)
    d_assigned = dists[label]
    d_other = np.min(np.delete(dists, label))
    if d_other == 0.0:
        return 0.0  # another centroid matches exactly; no basis for confidence
    # planted users can sit closer to another centroid (d_assigned > d_other);
    # the clamp floors their distance-based confidence at 0 before the
    # caller's planted override applies
    return float(np.clip(1.0 - d_assigned / d_other, 0.0, 1.0))


def assign_users(
    session: Session,
    cuisine_id: int,
    matrix,
    labels: np.ndarray,
    centroids: np.ndarray,
    cluster_id_by_label: dict[int, int],
    planted_user_ids: set[int],
    now: str,
) -> int:
    """Insert one assignment row per clustered user. Returns rows written.

    Callers clear previous assignments for the cuisine before this runs
    (see discover._clear_cluster_state), so plain inserts are safe.
    """
    count = 0
    for i, user_id in enumerate(matrix.user_ids):
        label = int(labels[i])
        confidence = (
            1.0 if user_id in planted_user_ids
            else assignment_confidence(matrix.X[i], centroids, label)
        )
        session.add(UserClusterAssignment(
            user_id=user_id,
            cuisine_id=cuisine_id,
            cluster_id=cluster_id_by_label[label],
            confidence=confidence,
            assigned_at=now,
        ))
        count += 1
    return count
