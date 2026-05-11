"""Tests for the Glicko-inspired credibility update logic."""
import pytest

from modules.credibility.dynamic import (
    DAMPEN, LEARNING_RATE, RD_DECAY, RD_FLOOR, VOL_BUMP, VOL_CAP,
    update_user_credibility,
)
from modules.data.models import CredibilityHistory, UserCredibility
from tests.conftest import (
    add_credibility, add_cuisine, add_rating, add_restaurant, add_user,
)


def test_first_rater_creates_record(session):
    """The first rater for a restaurant gets a record created, no score change."""
    u = add_user(session)
    c = add_cuisine(session)
    r = add_restaurant(session, c.id)
    add_rating(session, u.id, r.id, 4.0)

    update_user_credibility(session, u.id, c.id, 4.0, r.id)

    rec = session.get(UserCredibility, (u.id, c.id))
    assert rec is not None
    assert rec.credibility_score == pytest.approx(0.5)  # unchanged — no consensus yet


def test_first_rater_appends_history(session):
    u = add_user(session)
    c = add_cuisine(session)
    r = add_restaurant(session, c.id)
    add_rating(session, u.id, r.id, 4.0)
    update_user_credibility(session, u.id, c.id, 4.0, r.id)

    history = session.query(CredibilityHistory).filter_by(user_id=u.id, cuisine_id=c.id).all()
    assert len(history) == 1


def test_agreement_nudges_credibility_up(session):
    """Second rater agreeing with a credible first rater gains credibility."""
    u1 = add_user(session)
    u2 = add_user(session)
    c  = add_cuisine(session)
    r  = add_restaurant(session, c.id)

    # Give u1 a credibility record so their rating carries weight
    add_credibility(session, u1.id, c.id, cs=0.8, rd=0.2)
    add_rating(session, u1.id, r.id, 7.0)
    add_rating(session, u2.id, r.id, 7.0)  # exact agreement

    update_user_credibility(session, u2.id, c.id, 7.0, r.id)

    rec = session.get(UserCredibility, (u2.id, c.id))
    assert rec.credibility_score > 0.5
    assert rec.rating_deviation < 1.0


def test_divergence_nudges_credibility_down(session):
    """Second rater strongly disagreeing with a credible first rater loses credibility."""
    u1 = add_user(session)
    u2 = add_user(session)
    c  = add_cuisine(session)
    r  = add_restaurant(session, c.id)

    add_credibility(session, u1.id, c.id, cs=0.8, rd=0.2)
    add_rating(session, u1.id, r.id, 2.0)
    add_rating(session, u2.id, r.id, 9.0)  # max divergence from consensus

    update_user_credibility(session, u2.id, c.id, 9.0, r.id)

    rec = session.get(UserCredibility, (u2.id, c.id))
    assert rec.credibility_score < 0.5
    assert rec.volatility > 0.06


def test_low_community_weight_dampens_nudge(session):
    """When the existing rater has no credibility record (weight≈0), DAMPEN prior
    overwhelms the signal and the nudge is near zero."""
    u1 = add_user(session)
    u2 = add_user(session)
    c  = add_cuisine(session)
    r  = add_restaurant(session, c.id)

    # u1 has NO credibility record → effective weight = 0 → community_weight = 0
    add_rating(session, u1.id, r.id, 8.0)
    add_rating(session, u2.id, r.id, 8.0)

    update_user_credibility(session, u2.id, c.id, 8.0, r.id)

    rec = session.get(UserCredibility, (u2.id, c.id))
    # nudge_scale = 0 / (0 + DAMPEN) = 0 → score stays at 0.5
    assert rec.credibility_score == pytest.approx(0.5)


def test_rd_floor_not_breached(session):
    """rating_deviation cannot fall below RD_FLOOR no matter how many agreements."""
    u1 = add_user(session)
    u2 = add_user(session)
    c  = add_cuisine(session)

    add_credibility(session, u1.id, c.id, cs=0.9, rd=0.2)
    # Drive u2's RD toward the floor with repeated agreements
    for _ in range(50):
        r = add_restaurant(session, c.id)
        add_rating(session, u1.id, r.id, 5.0)
        add_rating(session, u2.id, r.id, 5.0)
        update_user_credibility(session, u2.id, c.id, 5.0, r.id)
        session.flush()

    rec = session.get(UserCredibility, (u2.id, c.id))
    assert rec.rating_deviation >= RD_FLOOR


def test_volatility_cap_not_breached(session):
    """volatility cannot exceed VOL_CAP no matter how many disagreements."""
    u1 = add_user(session)
    u2 = add_user(session)
    c  = add_cuisine(session)

    add_credibility(session, u1.id, c.id, cs=0.9, rd=0.2)
    for i in range(50):
        r  = add_restaurant(session, c.id)
        s1 = 2.0 if i % 2 == 0 else 9.0
        s2 = 9.0 if i % 2 == 0 else 2.0  # always opposite
        add_rating(session, u1.id, r.id, s1)
        add_rating(session, u2.id, r.id, s2)
        update_user_credibility(session, u2.id, c.id, s2, r.id)
        session.flush()

    rec = session.get(UserCredibility, (u2.id, c.id))
    assert rec.volatility <= VOL_CAP


def test_history_appended_each_update(session):
    u1 = add_user(session)
    u2 = add_user(session)
    c  = add_cuisine(session)

    add_credibility(session, u1.id, c.id, cs=0.8, rd=0.2)
    for _ in range(3):
        r = add_restaurant(session, c.id)
        add_rating(session, u1.id, r.id, 5.0)
        add_rating(session, u2.id, r.id, 5.0)
        update_user_credibility(session, u2.id, c.id, 5.0, r.id)
        session.flush()

    history = session.query(CredibilityHistory).filter_by(user_id=u2.id, cuisine_id=c.id).all()
    assert len(history) == 3
