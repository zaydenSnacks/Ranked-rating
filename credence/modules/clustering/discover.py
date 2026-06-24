"""
Cluster discovery: k-means on per-cuisine rating vectors.

Each eligible user (>= MIN_RATINGS_FOR_VECTOR ratings in the cuisine) gets a
vector over the cuisine's rated restaurants; missing entries are filled with
the cuisine average. K-means here is a deliberate placeholder — phase 3
replaces it with matrix factorization, so it stays simple and untuned.

This module also hosts recluster_cuisine()/recluster_all(), the orchestration
that ties discovery, seed planting, assignment, coherence, and consensus
together. Cluster state is derived and disposable: every run deletes the
cuisine's previous clusters and rebuilds from the rating_events log.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import NamedTuple

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..data.models import (
    Cluster, ClusterRestaurantScore, Cuisine, RatingEvent, Restaurant,
    UserClusterAssignment,
)
from .assign import assign_users
from .coherence import coherence_score
from .consensus import compute_cluster_scores
from .seeds import plant_trusted_seeds

K_INITIAL               = 4    # casual/calibrated/inflator/complainer archetypes, roughly
MIN_RATINGS_FOR_VECTOR  = 3    # below this a user's vector is mostly fill values
KMEANS_MAX_ITER         = 100
KMEANS_SEED             = 0    # fixed seed → deterministic clusters for a given event log


class RatingMatrix(NamedTuple):
    user_ids:       list[int]
    restaurant_ids: list[int]
    X:              np.ndarray                    # (n_users, n_restaurants), filled
    ratings:        dict[tuple[int, int], float]  # (user_id, restaurant_id) → latest score


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_rating_matrix(session: Session, cuisine_id: int) -> RatingMatrix | None:
    """Latest-rating-per-(user, restaurant) matrix for one cuisine.

    rating_events is append-only, so a user may have rated the same restaurant
    multiple times — the latest event is their current opinion. Missing entries
    are filled with the cuisine average (MISSING_VALUE_FILL). Returns None when
    fewer than 2 users are eligible: there is nothing to cluster.
    """
    rows = session.execute(
        select(RatingEvent.user_id, RatingEvent.restaurant_id, RatingEvent.score)
        .join(Restaurant, RatingEvent.restaurant_id == Restaurant.id)
        .where(Restaurant.cuisine_id == cuisine_id)
        .order_by(RatingEvent.id)
    ).all()

    # later events overwrite earlier ones → latest rating wins
    ratings = {(r.user_id, r.restaurant_id): r.score for r in rows}
    if not ratings:
        return None

    counts: dict[int, int] = {}
    for user_id, _ in ratings:
        counts[user_id] = counts.get(user_id, 0) + 1
    user_ids = sorted(uid for uid, n in counts.items() if n >= MIN_RATINGS_FOR_VECTOR)
    if len(user_ids) < 2:
        return None

    restaurant_ids = sorted({rid for _, rid in ratings})
    fill = sum(ratings.values()) / len(ratings)  # cuisine average

    X = np.full((len(user_ids), len(restaurant_ids)), fill)
    for i, uid in enumerate(user_ids):
        for j, rid in enumerate(restaurant_ids):
            if (uid, rid) in ratings:
                X[i, j] = ratings[(uid, rid)]

    return RatingMatrix(user_ids, restaurant_ids, X, ratings)


def kmeans(
    X: np.ndarray,
    k: int,
    seed: int = KMEANS_SEED,
    max_iter: int = KMEANS_MAX_ITER,
) -> tuple[np.ndarray, np.ndarray]:
    """Plain Lloyd's algorithm. Returns (labels, centroids).

    k is capped at the number of points. Empty clusters are reseeded with the
    point farthest from its current centroid so all k clusters stay populated.
    """
    n = X.shape[0]
    k = min(k, n)
    rng = np.random.default_rng(seed)
    centroids = X[rng.choice(n, size=k, replace=False)].astype(float)

    labels: np.ndarray | None = None
    for _ in range(max_iter):
        dists = np.linalg.norm(X[:, None, :] - centroids[None, :, :], axis=2)
        new_labels = dists.argmin(axis=1)
        for j in range(k):
            if not np.any(new_labels == j):
                farthest = dists[np.arange(n), new_labels].argmax()
                new_labels[farthest] = j
        if labels is not None and np.array_equal(new_labels, labels):
            break
        labels = new_labels
        for j in range(k):
            centroids[j] = X[labels == j].mean(axis=0)

    return labels, centroids


def _clear_cluster_state(session: Session, cuisine_id: int) -> None:
    cluster_ids = select(Cluster.id).where(Cluster.cuisine_id == cuisine_id)
    session.execute(
        delete(ClusterRestaurantScore).where(ClusterRestaurantScore.cluster_id.in_(cluster_ids))
    )
    session.execute(
        delete(UserClusterAssignment).where(UserClusterAssignment.cuisine_id == cuisine_id)
    )
    session.execute(delete(Cluster).where(Cluster.cuisine_id == cuisine_id))


def recluster_cuisine(session: Session, cuisine_id: int, k: int = K_INITIAL) -> dict | None:
    """Full clustering pass for one cuisine. Returns run stats, or None when
    the cuisine lacks enough eligible users (previous cluster state is still
    cleared — stale clusters are worse than none)."""
    _clear_cluster_state(session, cuisine_id)

    matrix = build_rating_matrix(session, cuisine_id)
    if matrix is None:
        return None

    # member user_id → {restaurant_id: real score}, no fill values. Coherence
    # correlates only co-rated restaurants, so it needs the sparse real ratings,
    # not matrix.X (which is fill-imputed). Built once, reused per cluster.
    ratings_by_user: dict[int, dict[int, float]] = {}
    for (uid, rid), score in matrix.ratings.items():
        ratings_by_user.setdefault(uid, {})[rid] = score

    labels, centroids = kmeans(matrix.X, k)
    labels, planted_user_ids = plant_trusted_seeds(session, matrix, labels, centroids)

    now = _now_iso()
    cluster_id_by_label: dict[int, int] = {}
    members_by_cluster: dict[int, list[int]] = {}
    for j in sorted(set(labels.tolist())):  # planting can empty a cluster; skip those
        member_idx = np.where(labels == j)[0]
        cluster = Cluster(
            cuisine_id=cuisine_id,
            label=f"k{j}",
            coherence_score=coherence_score(
                [ratings_by_user[matrix.user_ids[i]] for i in member_idx]
            ),
            member_count=len(member_idx),
            created_at=now,
        )
        session.add(cluster)
        session.flush()
        cluster_id_by_label[j] = cluster.id
        members_by_cluster[cluster.id] = [matrix.user_ids[i] for i in member_idx]

    assign_users(
        session, cuisine_id, matrix, labels, centroids,
        cluster_id_by_label, planted_user_ids, now,
    )
    score_rows = compute_cluster_scores(
        session, cuisine_id, members_by_cluster, matrix.ratings, now
    )

    return {
        "users": len(matrix.user_ids),
        "clusters": len(cluster_id_by_label),
        "planted": len(planted_user_ids),
        "score_rows": score_rows,
    }


def recluster_all(session: Session, k: int = K_INITIAL) -> dict[int, dict | None]:
    """Run clustering for every cuisine. Returns {cuisine_id: stats | None}."""
    cuisine_ids = list(session.scalars(select(Cuisine.id).order_by(Cuisine.id)))
    return {cid: recluster_cuisine(session, cid, k) for cid in cuisine_ids}
