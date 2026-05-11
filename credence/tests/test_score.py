"""Tests for the combined phase-1 credibility_score formula."""
import math
import pytest

from modules.credibility.alignment import MIN_OVERLAP
from modules.credibility.expertise import MAX_N
from modules.credibility.score import W_EXPERTISE, W_PROXIMITY, credibility_score
from tests.conftest import add_cuisine, add_rating, add_restaurant, add_trusted, add_user


def test_new_user_returns_zero(session):
    u = add_user(session)
    c = add_cuisine(session)
    assert credibility_score(session, u.id, c.id) == pytest.approx(0.0)


def test_no_alignment_overlap_uses_redistributed_formula(session):
    """Insufficient trusted-source overlap → (β·exp + γ·prox) / (β+γ)."""
    u = add_user(session)
    c = add_cuisine(session)
    r = add_restaurant(session, c.id)
    add_rating(session, u.id, r.id, 4.0)  # 1 rating, below MIN_OVERLAP

    exp_val  = math.log(2) / math.log(MAX_N + 1)
    expected = (W_EXPERTISE * exp_val) / (W_EXPERTISE + W_PROXIMITY)
    assert credibility_score(session, u.id, c.id) == pytest.approx(expected)


def test_full_formula_with_perfect_alignment(session):
    """With MIN_OVERLAP trusted restaurants and perfect correlation, score is high."""
    u       = add_user(session)
    trusted = add_user(session)
    add_trusted(session, trusted.id)
    c = add_cuisine(session)
    for s in [3.0, 5.0, 7.0, 9.0]:
        r = add_restaurant(session, c.id)
        add_rating(session, trusted.id, r.id, s)
        add_rating(session, u.id, r.id, s)

    score = credibility_score(session, u.id, c.id)
    assert score > 0.5
    assert score <= 1.0


def test_negative_alignment_clamped_to_zero(session):
    """Perfect anti-correlation → raw score goes negative → clamped to 0."""
    u       = add_user(session)
    trusted = add_user(session)
    add_trusted(session, trusted.id)
    c = add_cuisine(session)
    for ts, us in zip([3.0, 5.0, 7.0, 9.0], [9.0, 7.0, 5.0, 3.0]):
        r = add_restaurant(session, c.id)
        add_rating(session, trusted.id, r.id, ts)
        add_rating(session, u.id, r.id, us)

    assert credibility_score(session, u.id, c.id) == pytest.approx(0.0)


def test_score_always_in_unit_interval(session):
    """Credibility score is always in [0, 1] regardless of inputs."""
    u       = add_user(session)
    trusted = add_user(session)
    add_trusted(session, trusted.id)
    c = add_cuisine(session)
    # MAX_N ratings in cuisine, perfect alignment → maximum possible score
    for s in [float(i) for i in range(1, MAX_N + 1)]:
        r = add_restaurant(session, c.id)
        add_rating(session, trusted.id, r.id, s)
        add_rating(session, u.id, r.id, s)

    score = credibility_score(session, u.id, c.id)
    assert 0.0 <= score <= 1.0
