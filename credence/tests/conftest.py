import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from modules.data.db import Base
from modules.data.models import (
    Cuisine, CuisineDistance, RatingEvent, Restaurant,
    TrustedSource, User, UserCredibility,
)

NOW = "2024-01-01T00:00:00+00:00"

_user_counter = 0
_cuisine_counter = 0
_restaurant_counter = 0


@pytest.fixture(autouse=True)
def _reset_counters():
    global _user_counter, _cuisine_counter, _restaurant_counter
    _user_counter = _cuisine_counter = _restaurant_counter = 0


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as s:
        yield s


# ── helpers ────────────────────────────────────────────────────────────────────

def add_user(s, name=None) -> User:
    global _user_counter
    _user_counter += 1
    n = name or f"user{_user_counter}"
    u = User(name=n, email=f"{n}@test.com", created_at=NOW)
    s.add(u); s.flush()
    return u


def add_cuisine(s, name=None) -> Cuisine:
    global _cuisine_counter
    _cuisine_counter += 1
    c = Cuisine(name=name or f"cuisine{_cuisine_counter}")
    s.add(c); s.flush()
    return c


def add_distance(s, a_id: int, b_id: int, dist: float) -> None:
    s.add(CuisineDistance(cuisine_a_id=a_id, cuisine_b_id=b_id, distance=dist))
    s.add(CuisineDistance(cuisine_a_id=b_id, cuisine_b_id=a_id, distance=dist))
    s.flush()


def add_restaurant(s, cuisine_id: int, name=None) -> Restaurant:
    global _restaurant_counter
    _restaurant_counter += 1
    r = Restaurant(name=name or f"rest{_restaurant_counter}", cuisine_id=cuisine_id, created_at=NOW)
    s.add(r); s.flush()
    return r


def add_trusted(s, user_id: int) -> TrustedSource:
    t = TrustedSource(user_id=user_id, added_at=NOW)
    s.add(t); s.flush()
    return t


def add_rating(s, user_id: int, restaurant_id: int, score: float) -> RatingEvent:
    e = RatingEvent(user_id=user_id, restaurant_id=restaurant_id, score=score, created_at=NOW)
    s.add(e); s.flush()
    return e


def add_credibility(s, user_id: int, cuisine_id: int, cs=0.5, rd=0.3, vol=0.06) -> UserCredibility:
    rec = UserCredibility(
        user_id=user_id, cuisine_id=cuisine_id,
        credibility_score=cs, rating_deviation=rd, volatility=vol,
        last_updated=NOW,
    )
    s.add(rec); s.flush()
    return rec
