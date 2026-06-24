import numpy as np
import pytest
from sqlalchemy import select

from modules.clustering.assign import assignment_confidence
from modules.clustering.coherence import coherence_score
from modules.clustering.discover import (
    build_rating_matrix, kmeans, recluster_all, recluster_cuisine,
)
from modules.data.models import Cluster, ClusterRestaurantScore, UserClusterAssignment
from tests.conftest import (
    NOW, add_cluster, add_cuisine, add_rating, add_restaurant, add_trusted, add_user,
)


def make_cuisine(s, n_restaurants):
    cuisine = add_cuisine(s)
    return cuisine, [add_restaurant(s, cuisine.id) for _ in range(n_restaurants)]


def rate_all(s, user, restaurants, scores):
    for r, score in zip(restaurants, scores):
        add_rating(s, user.id, r.id, score)


# ── kmeans (pure numpy) ───────────────────────────────────────────────────────

def test_kmeans_separates_two_obvious_groups():
    low = np.full((4, 3), 2.0) + np.arange(4)[:, None] * 0.1
    high = np.full((4, 3), 9.0) + np.arange(4)[:, None] * 0.1
    labels, centroids = kmeans(np.vstack([low, high]), k=2)
    assert len(set(labels[:4])) == 1
    assert len(set(labels[4:])) == 1
    assert labels[0] != labels[4]
    assert centroids.shape == (2, 3)


def test_kmeans_caps_k_at_number_of_points():
    X = np.array([[1.0, 1.0], [9.0, 9.0]])
    labels, centroids = kmeans(X, k=4)
    assert len(centroids) == 2
    assert sorted(set(labels.tolist())) == [0, 1]


def test_kmeans_is_deterministic():
    rng = np.random.default_rng(42)
    X = rng.uniform(1, 10, size=(20, 5))
    labels_a, _ = kmeans(X, k=4)
    labels_b, _ = kmeans(X, k=4)
    assert np.array_equal(labels_a, labels_b)


# ── rating matrix ─────────────────────────────────────────────────────────────

def test_matrix_excludes_users_below_min_ratings(session):
    cuisine, rests = make_cuisine(session, 3)
    u1, u2, u3 = add_user(session), add_user(session), add_user(session)
    rate_all(session, u1, rests, [8, 9, 7])
    rate_all(session, u2, rests, [6, 5, 7])
    add_rating(session, u3.id, rests[0].id, 9)  # only 1 rating — ineligible

    m = build_rating_matrix(session, cuisine.id)
    assert m.user_ids == [u1.id, u2.id]
    assert m.X.shape == (2, 3)


def test_matrix_fills_missing_with_cuisine_average(session):
    cuisine, rests = make_cuisine(session, 4)
    u1, u2 = add_user(session), add_user(session)
    rate_all(session, u1, rests, [8, 8, 8, 8])
    rate_all(session, u2, rests[:3], [4, 4, 4])  # never rated rests[3]

    m = build_rating_matrix(session, cuisine.id)
    fill = (8 * 4 + 4 * 3) / 7  # cuisine average
    assert m.X[1, 3] == pytest.approx(fill)


def test_matrix_latest_rating_wins(session):
    cuisine, rests = make_cuisine(session, 3)
    u1, u2 = add_user(session), add_user(session)
    rate_all(session, u1, rests, [5, 5, 5])
    rate_all(session, u2, rests, [5, 5, 5])
    add_rating(session, u1.id, rests[0].id, 9.0)  # changed their mind

    m = build_rating_matrix(session, cuisine.id)
    assert m.ratings[(u1.id, rests[0].id)] == 9.0
    assert m.X[0, 0] == 9.0


def test_matrix_none_when_fewer_than_two_eligible_users(session):
    cuisine, rests = make_cuisine(session, 3)
    u1 = add_user(session)
    rate_all(session, u1, rests, [8, 9, 7])
    assert build_rating_matrix(session, cuisine.id) is None


# ── coherence ─────────────────────────────────────────────────────────────────

def members(*rows):
    """Build the dict-list coherence_score now takes: each row is a member's
    {restaurant_id: score}. A None entry means that member didn't rate that
    restaurant (so it never enters the pair's co-rated set)."""
    return [
        {rid: score for rid, score in enumerate(row) if score is not None}
        for row in rows
    ]


def test_coherence_high_for_agreeing_members():
    # 3 members co-rate the same 3 restaurants in a correlated pattern → 3 pairs
    m = members([2.0, 5.0, 9.0], [2.5, 5.5, 9.5], [2.2, 5.1, 8.8])
    assert coherence_score(m) > 0.95


def test_coherence_negative_when_pairs_disagree():
    # two agreeing camps with opposite tastes: within-camp pairs correlate +,
    # cross-camp pairs correlate −; with 4 members (6 pairs) the mean goes < 0.
    pattern = [2.0, 9.0, 4.0, 8.0, 6.0]
    anti = [12.0 - x for x in pattern]
    m = members(pattern, [x + 0.2 for x in pattern], anti, [x + 0.2 for x in anti])
    assert coherence_score(m) < 0.0


def test_coherence_zero_below_min_pair_overlap():
    # every pair shares only 2 restaurants (< MIN_PAIR_OVERLAP=3): no pair counts
    m = members([2.0, 5.0, None], [2.5, 5.5, None], [2.2, 5.1, None])
    assert coherence_score(m) == 0.0


def test_coherence_zero_below_min_contributing_pairs():
    # a single agreeing pair (1 < MIN_CONTRIBUTING_PAIRS=3) → unmeasurable → 0.0
    m = members([2.0, 5.0, 9.0], [2.5, 5.5, 9.5])
    assert coherence_score(m) == 0.0


def test_coherence_zero_for_singleton():
    assert coherence_score(members([1.0, 2.0, 3.0])) == 0.0


def test_coherence_zero_variance_pair_contributes_zero():
    # the constant member's pairs add 0 (no signal), dragging the mean below the
    # value the three varying members would have on their own.
    flat = [5.0, 5.0, 5.0, 5.0]
    m = members([2.0, 5.0, 4.0, 9.0], [2.2, 5.1, 4.1, 8.8], [1.8, 4.9, 3.9, 9.2], flat)
    varying_only = members([2.0, 5.0, 4.0, 9.0], [2.2, 5.1, 4.1, 8.8], [1.8, 4.9, 3.9, 9.2])
    assert coherence_score(m) < coherence_score(varying_only)


# ── assignment confidence ─────────────────────────────────────────────────────

def test_confidence_high_when_centroid_is_close():
    centroids = np.array([[1.0, 1.0], [9.0, 9.0]])
    assert assignment_confidence(np.array([1.0, 1.1]), centroids, 0) > 0.9


def test_confidence_zero_when_equidistant():
    centroids = np.array([[1.0, 1.0], [9.0, 9.0]])
    assert assignment_confidence(np.array([5.0, 5.0]), centroids, 0) == pytest.approx(0.0)


def test_confidence_one_for_single_cluster():
    assert assignment_confidence(np.array([3.0]), np.array([[5.0]]), 0) == 1.0


# ── recluster_cuisine end-to-end ──────────────────────────────────────────────

@pytest.fixture
def two_taste_groups(session):
    """6 users: 3 'calibrated' agree closely, 3 'casual' rate everything high."""
    cuisine, rests = make_cuisine(session, 4)
    calibrated, casual = [], []
    for offset in (0.0, 0.2, 0.4):
        u = add_user(session)
        rate_all(session, u, rests, [2 + offset, 9 - offset, 4 + offset, 8 - offset])
        calibrated.append(u)
    for offset in (0.0, 0.3, 0.6):
        u = add_user(session)
        rate_all(session, u, rests, [9 - offset, 8 + offset / 2, 9 - offset, 8 + offset / 2])
        casual.append(u)
    return cuisine, rests, calibrated, casual


def test_recluster_separates_taste_groups(session, two_taste_groups):
    cuisine, _, calibrated, casual = two_taste_groups
    stats = recluster_cuisine(session, cuisine.id, k=2)
    assert stats["users"] == 6
    assert stats["clusters"] == 2

    by_user = {
        a.user_id: a.cluster_id
        for a in session.execute(select(UserClusterAssignment)).scalars()
    }
    assert len({by_user[u.id] for u in calibrated}) == 1
    assert len({by_user[u.id] for u in casual}) == 1
    assert by_user[calibrated[0].id] != by_user[casual[0].id]


def test_recluster_coherence_and_member_count_persisted(session, two_taste_groups):
    cuisine, _, calibrated, casual = two_taste_groups
    recluster_cuisine(session, cuisine.id, k=2)

    clusters = session.execute(select(Cluster)).scalars().all()
    assert sorted(c.member_count for c in clusters) == [3, 3]
    # calibrated members rate in a varied, correlated pattern → high coherence
    assert max(c.coherence_score for c in clusters) > 0.9


def test_recluster_writes_consensus_rows(session, two_taste_groups):
    cuisine, rests, calibrated, casual = two_taste_groups
    stats = recluster_cuisine(session, cuisine.id, k=2)
    assert stats["score_rows"] == 8  # 2 clusters × 4 restaurants

    rows = session.execute(select(ClusterRestaurantScore)).scalars().all()
    assert all(r.rater_count == 3 for r in rows)
    assert all(1.0 <= r.consensus <= 10.0 for r in rows)
    # rests[0]: calibrated rate it ~2, casual ~9. The prior (3.0) dampens both
    # toward the global average since phase-1 weights are small here, but the
    # per-cluster consensus must still clearly separate.
    scores = sorted(r.consensus for r in rows if r.restaurant_id == rests[0].id)
    assert scores[1] - scores[0] > 1.0


def test_recluster_plants_trusted_sources_together(session, two_taste_groups):
    cuisine, rests, calibrated, casual = two_taste_groups
    # two trusted sources whose ratings sit with the calibrated pattern
    for offset in (0.1, 0.3):
        t = add_user(session)
        rate_all(session, t, rests, [2 + offset, 9 - offset, 4 + offset, 8 - offset])
        add_trusted(session, t.id)
        trusted_last = t

    stats = recluster_cuisine(session, cuisine.id, k=2)
    assert stats["planted"] == 2

    assignments = {
        a.user_id: a
        for a in session.execute(select(UserClusterAssignment)).scalars()
    }
    planted = assignments[trusted_last.id]
    assert planted.confidence == 1.0
    # planted into the cluster the calibrated users occupy
    assert planted.cluster_id == assignments[calibrated[0].id].cluster_id


def test_recluster_replaces_previous_state(session, two_taste_groups):
    cuisine, _, _, _ = two_taste_groups
    recluster_cuisine(session, cuisine.id, k=2)
    recluster_cuisine(session, cuisine.id, k=2)

    # no accumulation across runs: exactly one generation of derived state
    clusters = session.execute(select(Cluster)).scalars().all()
    assert len(clusters) == 2
    assignments = session.execute(select(UserClusterAssignment)).scalars().all()
    assert len(assignments) == 6
    live_ids = {c.id for c in clusters}
    assert all(a.cluster_id in live_ids for a in assignments)
    scores = session.execute(select(ClusterRestaurantScore)).scalars().all()
    assert all(r.cluster_id in live_ids for r in scores)


def test_recluster_skips_sparse_cuisine_but_clears_state(session, two_taste_groups):
    cuisine, _, _, _ = two_taste_groups
    recluster_cuisine(session, cuisine.id, k=2)

    sparse = add_cuisine(session)
    assert recluster_cuisine(session, sparse.id) is None  # nothing to cluster

    # re-running the populated cuisine after its events thin out clears state:
    # simulate by reclustering a cuisine with no events
    empty = add_cuisine(session)
    assert recluster_cuisine(session, empty.id) is None
    assert session.execute(
        select(Cluster).where(Cluster.cuisine_id == empty.id)
    ).first() is None


def test_recluster_all_covers_every_cuisine(session, two_taste_groups):
    cuisine, _, _, _ = two_taste_groups
    other = add_cuisine(session)
    results = recluster_all(session, k=2)
    assert results[cuisine.id]["clusters"] == 2
    assert results[other.id] is None


# ── consensus weight cache (perf fix — must not change outputs) ────────────────

def test_consensus_cache_matches_uncached(session, monkeypatch):
    """The per-user weight cache must produce identical consensus values, and
    call the underlying weight function once per member, not once per rating."""
    from modules.clustering import consensus as consensus_mod
    from modules.clustering.consensus import compute_cluster_scores

    cuisine, rests = make_cuisine(session, 3)
    # one cluster, 2 members who each rated all 3 restaurants (6 ratings, 2 members)
    members, ratings = [], {}
    for scores in ([8.0, 6.0, 9.0], [7.0, 5.0, 8.0]):
        u = add_user(session)
        members.append(u.id)
        for r, sc in zip(rests, scores):
            add_rating(session, u.id, r.id, sc)
            ratings[(u.id, r.id)] = sc
    cluster = add_cluster(session, cuisine.id, member_count=2)

    calls = {"n": 0}
    real = consensus_mod._rater_weight
    def counting(sess, uid, cid):
        calls["n"] += 1
        return real(sess, uid, cid)
    monkeypatch.setattr(consensus_mod, "_rater_weight", counting)

    rows = compute_cluster_scores(
        session, cuisine.id, {cluster.id: members}, ratings, NOW
    )
    assert rows == 3                       # 3 restaurants scored
    assert calls["n"] == 2                 # one weight call per member, not per rating (would be 6)

    stored = {
        s.restaurant_id: s.consensus
        for s in session.execute(select(ClusterRestaurantScore)).scalars()
    }
    # recompute the expected Bayesian-within-cluster value by hand for one restaurant
    g = consensus_mod._global_average(session)
    w = real(session, members[0], cuisine.id), real(session, members[1], cuisine.id)
    expected_r0 = (consensus_mod.PRIOR_WEIGHT * g + 8.0 * w[0] + 7.0 * w[1]) / (
        consensus_mod.PRIOR_WEIGHT + w[0] + w[1]
    )
    assert stored[rests[0].id] == pytest.approx(expected_r0)
