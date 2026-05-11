import pytest

from modules.credibility.proximity import THRESHOLD, proximity_score
from modules.credibility.expertise import MAX_N
from tests.conftest import (
    add_cuisine, add_distance, add_rating, add_restaurant, add_user,
)


def test_no_adjacent_cuisines_returns_zero(session):
    u = add_user(session)
    c = add_cuisine(session)
    assert proximity_score(session, u.id, c.id) == 0.0


def test_adjacent_cuisine_with_no_ratings_returns_zero(session):
    u  = add_user(session)
    c1 = add_cuisine(session)
    c2 = add_cuisine(session)
    add_distance(session, c1.id, c2.id, 0.3)
    add_restaurant(session, c2.id)  # restaurant exists; user hasn't rated it
    assert proximity_score(session, u.id, c1.id) == 0.0


def test_distance_at_threshold_excluded(session):
    """distance == THRESHOLD (0.6) must be excluded — strict < not ≤."""
    u  = add_user(session)
    c1 = add_cuisine(session)
    c2 = add_cuisine(session)
    add_distance(session, c1.id, c2.id, THRESHOLD)
    r = add_restaurant(session, c2.id)
    add_rating(session, u.id, r.id, 4.0)
    assert proximity_score(session, u.id, c1.id) == 0.0


def test_distance_just_below_threshold_included(session):
    u  = add_user(session)
    c1 = add_cuisine(session)
    c2 = add_cuisine(session)
    add_distance(session, c1.id, c2.id, THRESHOLD - 0.01)
    r = add_restaurant(session, c2.id)
    add_rating(session, u.id, r.id, 4.0)
    assert proximity_score(session, u.id, c1.id) > 0.0


def test_full_adjacent_expertise_returns_one(session):
    """MAX_N ratings in the only adjacent cuisine → proximity = 1.0."""
    u  = add_user(session)
    c1 = add_cuisine(session)
    c2 = add_cuisine(session)
    add_distance(session, c1.id, c2.id, 0.3)
    for _ in range(MAX_N):
        r = add_restaurant(session, c2.id)
        add_rating(session, u.id, r.id, 4.0)
    assert proximity_score(session, u.id, c1.id) == pytest.approx(1.0)


def test_closer_adjacent_cuisine_weighted_higher(session):
    """With two adjacent cuisines, having ratings only in the closer one scores higher
    than having ratings only in the farther one — distance weights the contribution."""
    u    = add_user(session)
    c    = add_cuisine(session)
    near = add_cuisine(session)
    far  = add_cuisine(session)
    add_distance(session, c.id, near.id, 0.1)
    add_distance(session, c.id, far.id,  0.5)
    r_near = add_restaurant(session, near.id)
    r_far  = add_restaurant(session, far.id)

    # u2 rates only the near adjacent cuisine
    u2 = add_user(session)
    add_rating(session, u2.id, r_near.id, 4.0)

    # u3 rates only the far adjacent cuisine
    u3 = add_user(session)
    add_rating(session, u3.id, r_far.id, 4.0)

    # Both share the same max_sum (near+far adjacents exist for cuisine c).
    # u2's contribution = expertise * (1 - 0.1) > u3's = expertise * (1 - 0.5)
    assert proximity_score(session, u2.id, c.id) > proximity_score(session, u3.id, c.id)
