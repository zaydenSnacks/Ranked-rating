import math
import pytest

from modules.credibility.expertise import MAX_N, expertise_score
from tests.conftest import add_cuisine, add_rating, add_restaurant, add_user


def test_no_ratings_returns_zero(session):
    u = add_user(session)
    c = add_cuisine(session)
    assert expertise_score(session, u.id, c.id) == 0.0


def test_one_rating(session):
    u = add_user(session)
    c = add_cuisine(session)
    r = add_restaurant(session, c.id)
    add_rating(session, u.id, r.id, 4.0)
    assert expertise_score(session, u.id, c.id) == pytest.approx(math.log(2) / math.log(MAX_N + 1))


def test_ratings_in_other_cuisine_not_counted(session):
    u = add_user(session)
    c1 = add_cuisine(session)
    c2 = add_cuisine(session)
    r = add_restaurant(session, c2.id)
    add_rating(session, u.id, r.id, 4.0)
    assert expertise_score(session, u.id, c1.id) == 0.0


def test_at_soft_cap_is_one(session):
    u = add_user(session)
    c = add_cuisine(session)
    for _ in range(MAX_N):
        r = add_restaurant(session, c.id)
        add_rating(session, u.id, r.id, 4.0)
    assert expertise_score(session, u.id, c.id) == pytest.approx(1.0)


def test_above_soft_cap_exceeds_one(session):
    """Expertise has no hard ceiling — the outer credibility_score clamps it."""
    u = add_user(session)
    c = add_cuisine(session)
    for _ in range(MAX_N + 5):
        r = add_restaurant(session, c.id)
        add_rating(session, u.id, r.id, 4.0)
    assert expertise_score(session, u.id, c.id) > 1.0


def test_multiple_users_independent(session):
    u1 = add_user(session)
    u2 = add_user(session)
    c  = add_cuisine(session)
    r  = add_restaurant(session, c.id)
    add_rating(session, u1.id, r.id, 4.0)
    assert expertise_score(session, u1.id, c.id) != expertise_score(session, u2.id, c.id)
