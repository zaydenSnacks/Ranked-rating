import json

import pytest
from sqlalchemy import select

from modules.data.importers.yelp import import_yelp, stars_to_score
from modules.data.models import RatingEvent, Restaurant, User
from tests.conftest import add_cuisine

CUISINE_NAMES = ["Chinese", "Italian", "Japanese", "Korean Fusion", "American"]


def write_ndjson(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows))
    return path


def business(business_id, name, categories, city="Philadelphia"):
    return {
        "business_id": business_id, "name": name, "categories": categories,
        "address": "1 Main St", "city": city, "state": "PA",
    }


def review(user_id, business_id, stars, date="2019-06-01 12:00:00"):
    return {"user_id": user_id, "business_id": business_id, "stars": stars, "date": date}


@pytest.fixture
def cuisines(session):
    return {name: add_cuisine(session, name) for name in CUISINE_NAMES}


def run(session, tmp_path, businesses, reviews, **kwargs):
    bp = write_ndjson(tmp_path / "business.json", businesses)
    rp = write_ndjson(tmp_path / "review.json", reviews)
    return import_yelp(session, bp, rp, **kwargs)


# ── star conversion ───────────────────────────────────────────────────────────

def test_stars_map_to_full_credence_range():
    assert stars_to_score(1) == 1.0
    assert stars_to_score(3) == 5.5
    assert stars_to_score(5) == 10.0


# ── happy path ────────────────────────────────────────────────────────────────

def test_imports_restaurants_users_and_events(session, cuisines, tmp_path):
    stats = run(
        session, tmp_path,
        [business("b1", "Dumpling House", "Restaurants, Chinese")],
        [review("u1", "b1", 4), review("u1", "b1", 5), review("u1", "b1", 2)],
        min_user_reviews=3,
    )
    assert stats == {
        **stats, "restaurants": 1, "users": 1, "events": 3, "skipped_sparse_user": 0,
    }

    r = session.execute(select(Restaurant)).scalar_one()
    assert r.name == "Dumpling House"
    assert r.cuisine_id == cuisines["Chinese"].id
    assert r.location == "1 Main St, Philadelphia, PA"

    u = session.execute(select(User)).scalar_one()
    assert u.email == "u1@import.yelp"

    events = session.execute(select(RatingEvent)).scalars().all()
    assert sorted(e.score for e in events) == [3.25, 7.75, 10.0]
    assert events[0].created_at == "2019-06-01T12:00:00"


# ── business filtering ────────────────────────────────────────────────────────

def test_skips_non_restaurants_unmapped_and_multi_cuisine(session, cuisines, tmp_path):
    stats = run(
        session, tmp_path,
        [
            business("b1", "Nail Salon", "Nail Salons, Beauty & Spas"),
            business("b2", "Mystery Grill", "Restaurants, Burmese"),
            business("b3", "Fusion Spot", "Restaurants, Chinese, Italian"),
            business("b4", "Null Cats", None),
        ],
        [],
    )
    assert stats["restaurants"] == 0
    assert stats["skipped_not_restaurant"] == 2  # b1 and b4
    assert stats["skipped_unmapped_cuisine"] == 1
    assert stats["skipped_multi_cuisine"] == 1


def test_same_cuisine_categories_do_not_count_as_multi(session, cuisines, tmp_path):
    stats = run(
        session, tmp_path,
        [business("b1", "Ramen-Ya", "Restaurants, Japanese, Ramen, Sushi Bars")],
        [],
    )
    assert stats["restaurants"] == 1
    assert stats["skipped_multi_cuisine"] == 0


def test_city_filter(session, cuisines, tmp_path):
    stats = run(
        session, tmp_path,
        [
            business("b1", "Philly Pizza", "Restaurants, Pizza", city="Philadelphia"),
            business("b2", "Tampa Pizza", "Restaurants, Pizza", city="Tampa"),
        ],
        [],
        city="philadelphia",  # case-insensitive
    )
    assert stats["restaurants"] == 1
    assert stats["skipped_city"] == 1


# ── review filtering ──────────────────────────────────────────────────────────

def test_drops_users_below_min_user_reviews(session, cuisines, tmp_path):
    stats = run(
        session, tmp_path,
        [business("b1", "Dumpling House", "Restaurants, Chinese")],
        [
            review("u1", "b1", 4), review("u1", "b1", 5), review("u1", "b1", 3),
            review("u2", "b1", 1),
        ],
        min_user_reviews=3,
    )
    assert stats["users"] == 1
    assert stats["events"] == 3
    assert stats["skipped_sparse_user"] == 1


def test_reviews_for_unimported_businesses_ignored(session, cuisines, tmp_path):
    stats = run(
        session, tmp_path,
        [business("b1", "Dumpling House", "Restaurants, Chinese")],
        [review("u1", "b1", 4), review("u1", "b-unknown", 5)],
        min_user_reviews=1,
    )
    assert stats["events"] == 1


def test_max_reviews_caps_consistently_across_passes(session, cuisines, tmp_path):
    # u1's third review falls past the cap, so u1 has 2 qualifying reviews
    # in BOTH passes and survives min_user_reviews=2 deterministically.
    stats = run(
        session, tmp_path,
        [business("b1", "Dumpling House", "Restaurants, Chinese")],
        [review("u1", "b1", 4), review("u1", "b1", 5), review("u1", "b1", 3)],
        max_reviews=2, min_user_reviews=2,
    )
    assert stats["events"] == 2


# ── guards ────────────────────────────────────────────────────────────────────

def test_import_is_one_shot(session, cuisines, tmp_path):
    args = (
        [business("b1", "Dumpling House", "Restaurants, Chinese")],
        [review("u1", "b1", 4)],
    )
    run(session, tmp_path, *args, min_user_reviews=1)
    with pytest.raises(RuntimeError, match="one-shot"):
        run(session, tmp_path, *args, min_user_reviews=1)


def test_missing_cuisines_raise(session, tmp_path):
    add_cuisine(session, "Chinese")  # the other four are absent
    with pytest.raises(ValueError, match="load seed.sql"):
        run(session, tmp_path, [], [])
