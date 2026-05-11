"""Tests for the phase-2 ranking formula (Bayesian prior + effective weights)."""
import pytest

from modules.ranking.ranking import PRIOR_WEIGHT, restaurant_score
from tests.conftest import (
    add_credibility, add_cuisine, add_rating, add_restaurant, add_user,
)


def test_no_ratings_returns_zero(session):
    c = add_cuisine(session)
    r = add_restaurant(session, c.id)
    assert restaurant_score(session, r.id) == 0.0


def test_unknown_restaurant_raises(session):
    with pytest.raises(ValueError, match="not found"):
        restaurant_score(session, 9999)


def test_single_rating_anchored_toward_global_avg(session):
    """One extreme rating should be pulled toward the global average by the prior."""
    u  = add_user(session)
    c  = add_cuisine(session)
    r1 = add_restaurant(session, c.id)
    r2 = add_restaurant(session, c.id)

    # Seed a few baseline ratings so global avg ≈ 5.0
    for _ in range(5):
        u_base = add_user(session)
        add_rating(session, u_base.id, r1.id, 5.0)

    add_rating(session, u.id, r2.id, 10.0)  # extreme single rating
    score = restaurant_score(session, r2.id)
    assert score < 10.0   # pulled down by prior
    assert score > 5.0    # but still above global avg


def test_more_ratings_reduce_prior_influence(session):
    """As ratings accumulate the prior matters less — score converges to the ratings."""
    c   = add_cuisine(session)
    r   = add_restaurant(session, c.id)

    # Add many high-weight ratings
    for _ in range(20):
        u = add_user(session)
        add_credibility(session, u.id, c.id, cs=0.9, rd=0.1)
        add_rating(session, u.id, r.id, 9.0)

    score = restaurant_score(session, r.id)
    # With PRIOR_WEIGHT=3 and sum(weights) >> 3, score should be close to 9.0
    assert score > 8.0


def test_phase2_weights_used_when_record_exists(session):
    """Users with a user_credibility record use effective_weight, not phase-1 score."""
    u_high = add_user(session)
    u_low  = add_user(session)
    c      = add_cuisine(session)
    r      = add_restaurant(session, c.id)

    # u_high is credible (low RD), u_low is not (high RD → weight ≈ 0)
    add_credibility(session, u_high.id, c.id, cs=0.9, rd=0.1)
    add_credibility(session, u_low.id,  c.id, cs=0.5, rd=0.99)

    add_rating(session, u_high.id, r.id, 9.0)
    add_rating(session, u_low.id,  r.id, 1.0)

    score = restaurant_score(session, r.id)
    # u_high's 9.0 should dominate over u_low's 1.0 — score above midpoint
    # (prior anchors toward global avg ~5.0, so threshold is conservative)
    assert score > 5.5


def test_all_zero_weights_falls_back_to_prior_only(session):
    """If all raters have RD=1.0 (new users), effective weight = 0 → score ≈ global avg."""
    c = add_cuisine(session)
    r = add_restaurant(session, c.id)

    # Seed global avg with known ratings on another restaurant
    r_seed = add_restaurant(session, c.id)
    for _ in range(10):
        u = add_user(session)
        add_rating(session, u.id, r_seed.id, 5.0)

    # Rate r with new users (no credibility records, effective weight = 0)
    for score in [1.0, 10.0]:
        u = add_user(session)
        add_rating(session, u.id, r.id, score)

    result = restaurant_score(session, r.id)
    # Prior (global avg ≈ 5) dominates since all weights are 0
    assert result == pytest.approx(5.0, abs=0.5)
