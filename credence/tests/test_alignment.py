import pytest

from modules.credibility.alignment import MIN_OVERLAP, alignment_score
from tests.conftest import add_cuisine, add_rating, add_restaurant, add_trusted, add_user


def test_no_trusted_sources_returns_insufficient(session):
    u = add_user(session)
    c = add_cuisine(session)
    score, sufficient = alignment_score(session, u.id, c.id)
    assert not sufficient
    assert score == pytest.approx(0.0)


def test_below_min_overlap_returns_insufficient(session):
    u       = add_user(session)
    trusted = add_user(session)
    add_trusted(session, trusted.id)
    c = add_cuisine(session)
    for _ in range(MIN_OVERLAP - 1):
        r = add_restaurant(session, c.id)
        add_rating(session, trusted.id, r.id, 4.0)
        add_rating(session, u.id, r.id, 4.0)
    score, sufficient = alignment_score(session, u.id, c.id)
    assert not sufficient
    assert score == pytest.approx(0.0)


def test_perfect_positive_correlation(session):
    u       = add_user(session)
    trusted = add_user(session)
    add_trusted(session, trusted.id)
    c = add_cuisine(session)
    for s in [3.0, 5.0, 7.0, 9.0]:
        r = add_restaurant(session, c.id)
        add_rating(session, trusted.id, r.id, s)
        add_rating(session, u.id, r.id, s)
    score, sufficient = alignment_score(session, u.id, c.id)
    assert sufficient
    assert score == pytest.approx(1.0)


def test_perfect_negative_correlation(session):
    u       = add_user(session)
    trusted = add_user(session)
    add_trusted(session, trusted.id)
    c = add_cuisine(session)
    for ts, us in zip([3.0, 5.0, 7.0, 9.0], [9.0, 7.0, 5.0, 3.0]):
        r = add_restaurant(session, c.id)
        add_rating(session, trusted.id, r.id, ts)
        add_rating(session, u.id, r.id, us)
    score, sufficient = alignment_score(session, u.id, c.id)
    assert sufficient
    assert score == pytest.approx(-1.0)


def test_identical_scores_nan_handled(session):
    """Zero variance in both arrays → corrcoef NaN → score returns 0.0."""
    u       = add_user(session)
    trusted = add_user(session)
    add_trusted(session, trusted.id)
    c = add_cuisine(session)
    for _ in range(MIN_OVERLAP):
        r = add_restaurant(session, c.id)
        add_rating(session, trusted.id, r.id, 4.5)
        add_rating(session, u.id, r.id, 4.5)
    score, sufficient = alignment_score(session, u.id, c.id)
    assert sufficient
    assert score == pytest.approx(0.0)


def test_multiple_trusted_sources_averaged(session):
    """Two trusted sources on the same restaurant are averaged — no single one dominates."""
    u  = add_user(session)
    t1 = add_user(session); add_trusted(session, t1.id)
    t2 = add_user(session); add_trusted(session, t2.id)
    c  = add_cuisine(session)
    # t1 and t2 are mirror opposites → avg = 5.0 for every restaurant
    for s1, s2 in [(1.0, 9.0), (5.0, 5.0), (9.0, 1.0)]:
        r = add_restaurant(session, c.id)
        add_rating(session, t1.id, r.id, s1)
        add_rating(session, t2.id, r.id, s2)
        add_rating(session, u.id, r.id, 5.0)
    # trusted avg = [5, 5, 5] → zero variance → NaN → 0.0
    score, sufficient = alignment_score(session, u.id, c.id)
    assert sufficient
    assert score == pytest.approx(0.0)


def test_user_ratings_outside_cuisine_ignored(session):
    u       = add_user(session)
    trusted = add_user(session)
    add_trusted(session, trusted.id)
    c1 = add_cuisine(session)
    c2 = add_cuisine(session)
    # Ratings in c2 don't count toward alignment in c1
    for s in [3.0, 5.0, 7.0]:
        r = add_restaurant(session, c2.id)
        add_rating(session, trusted.id, r.id, s)
        add_rating(session, u.id, r.id, s)
    score, sufficient = alignment_score(session, u.id, c1.id)
    assert not sufficient
