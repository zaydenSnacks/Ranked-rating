"""Yelp Academic Dataset → credence schema.

Streams the NDJSON business and review files (they are too large to load
whole) and writes restaurants, synthesized users, and rating events.

Scope decisions (see DECISIONS.md):
- Only businesses whose categories map to exactly one existing credence
  cuisine are imported; multi-cuisine matches are skipped.
- Stars are affine-mapped from Yelp's [1, 5] onto credence's [1, 10].
- The import is one-shot: it refuses to run if Yelp users already exist.
"""

import json
from datetime import datetime, timezone

from sqlalchemy import insert, select

from modules.data.models import Cuisine, RatingEvent, Restaurant, User

BUSINESS_FILE = "yelp_academic_dataset_business.json"
REVIEW_FILE = "yelp_academic_dataset_review.json"

YELP_EMAIL_DOMAIN = "import.yelp"

# Yelp category → credence cuisine name. Cuisines must already exist in the
# DB (seed.sql); the importer never invents cuisines because every new
# cuisine would need hand-authored rows in cuisine_distances.
CATEGORY_MAP = {
    "Chinese":                "Chinese",
    "Cantonese":              "Chinese",
    "Dim Sum":                "Chinese",
    "Italian":                "Italian",
    "Pizza":                  "Italian",
    "Japanese":               "Japanese",
    "Ramen":                  "Japanese",
    "Sushi Bars":             "Japanese",
    "Korean":                 "Korean Fusion",
    "American (Traditional)": "American",
    "American (New)":         "American",
    "Diners":                 "American",
}

# Venue types whose identity is not a restaurant even when they carry a
# "Restaurants" tag plus a single mapped cuisine. A food hall, museum café, or
# grocery with one Dim Sum stall otherwise imports as that cuisine and pollutes
# its rating vectors — Reading Terminal Market alone was 10.8% of all Chinese
# ratings, and the Philadelphia Museum of Art imported as American. See
# DECISIONS.md "yelp importer scope" (known accepted noise) and "category
# blocklist". Any business also tagged with one of these is skipped.
NON_RESTAURANT_CATEGORIES = frozenset({
    "Public Markets", "Food Court", "Museums", "Grocery", "Farmers Market",
    "Convenience Stores", "Department Stores", "Wholesale Stores",
    "Shopping Centers", "Stadiums & Arenas", "Gas Stations",
})

MIN_USER_REVIEWS_DEFAULT = 3  # mirrors MIN_RATINGS_FOR_VECTOR
BATCH_SIZE = 5000


def stars_to_score(stars: float) -> float:
    """Affine map [1, 5] → [1, 10] so both endpoints are reachable."""
    return 1.0 + (stars - 1.0) * 2.25


def _iter_ndjson(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def _map_cuisine(categories: str | None) -> tuple[str | None, str]:
    """Return (cuisine_name, reason). cuisine_name is None when skipped."""
    cats = [c.strip() for c in (categories or "").split(",") if c.strip()]
    if "Restaurants" not in cats:
        return None, "not_restaurant"
    mapped = {CATEGORY_MAP[c] for c in cats if c in CATEGORY_MAP}
    if not mapped:
        return None, "unmapped_cuisine"
    if len(mapped) > 1:
        return None, "multi_cuisine"  # fusion handling is an open SPEC question
    if any(c in NON_RESTAURANT_CATEGORIES for c in cats):
        return None, "blocklisted_venue"  # food hall / museum café / grocery stall
    return mapped.pop(), "ok"


def import_yelp(
    session,
    business_path,
    review_path,
    *,
    city: str | None = None,
    max_reviews: int | None = None,
    min_user_reviews: int = MIN_USER_REVIEWS_DEFAULT,
) -> dict:
    """Import the dataset. Returns counters for reporting.

    Two passes over the review file: the first counts qualifying reviews per
    user, the second inserts events only for users meeting min_user_reviews,
    so the DB never holds users too sparse to ever get a rating vector.
    """
    already = session.execute(
        select(User.id).where(User.email.like(f"%@{YELP_EMAIL_DOMAIN}")).limit(1)
    ).first()
    if already:
        raise RuntimeError(
            "Yelp data already imported — the importer is one-shot. "
            "Start from a fresh database to re-import."
        )

    cuisine_ids = {
        name: cid for cid, name in session.execute(select(Cuisine.id, Cuisine.name))
    }
    missing = sorted(set(CATEGORY_MAP.values()) - set(cuisine_ids))
    if missing:
        raise ValueError(f"cuisines not found in DB (load seed.sql first): {missing}")

    now = datetime.now(timezone.utc).isoformat()
    stats = {
        "restaurants": 0, "users": 0, "events": 0,
        "skipped_not_restaurant": 0, "skipped_unmapped_cuisine": 0,
        "skipped_multi_cuisine": 0, "skipped_blocklisted_venue": 0,
        "skipped_city": 0, "skipped_sparse_user": 0,
    }

    # pass over businesses: build yelp business_id → restaurant id
    restaurant_ids: dict[str, int] = {}
    pending: list[tuple[str, Restaurant]] = []
    for biz in _iter_ndjson(business_path):
        if city and (biz.get("city") or "").lower() != city.lower():
            stats["skipped_city"] += 1
            continue
        cuisine_name, reason = _map_cuisine(biz.get("categories"))
        if cuisine_name is None:
            stats[f"skipped_{reason}"] += 1
            continue
        location = ", ".join(
            p for p in (biz.get("address"), biz.get("city"), biz.get("state")) if p
        )
        r = Restaurant(
            name=biz["name"], cuisine_id=cuisine_ids[cuisine_name],
            location=location or None, created_at=now,
        )
        session.add(r)
        pending.append((biz["business_id"], r))
        if len(pending) >= BATCH_SIZE:
            session.flush()
            restaurant_ids.update((bid, r.id) for bid, r in pending)
            pending.clear()
    session.flush()
    restaurant_ids.update((bid, r.id) for bid, r in pending)
    stats["restaurants"] = len(restaurant_ids)

    def qualifying_reviews():
        """Reviews on imported restaurants, in file order, capped at max_reviews."""
        taken = 0
        for rev in _iter_ndjson(review_path):
            if rev["business_id"] not in restaurant_ids:
                continue
            if max_reviews is not None and taken >= max_reviews:
                return
            taken += 1
            yield rev

    # review pass 1: count qualifying reviews per user
    review_counts: dict[str, int] = {}
    for rev in qualifying_reviews():
        review_counts[rev["user_id"]] = review_counts.get(rev["user_id"], 0) + 1

    kept_users = sorted(
        uid for uid, n in review_counts.items() if n >= min_user_reviews
    )
    stats["skipped_sparse_user"] = len(review_counts) - len(kept_users)

    # create all kept users up front, flushing in batches
    user_ids: dict[str, int] = {}
    for start in range(0, len(kept_users), BATCH_SIZE):
        batch = [
            (uid, User(name=f"yelp:{uid}", email=f"{uid}@{YELP_EMAIL_DOMAIN}", created_at=now))
            for uid in kept_users[start:start + BATCH_SIZE]
        ]
        session.add_all(u for _, u in batch)
        session.flush()
        user_ids.update((uid, u.id) for uid, u in batch)
    stats["users"] = len(user_ids)

    # review pass 2: bulk-insert events for kept users
    events: list[dict] = []
    for rev in qualifying_reviews():
        yelp_uid = rev["user_id"]
        if yelp_uid not in user_ids:
            continue
        events.append({
            "user_id": user_ids[yelp_uid],
            "restaurant_id": restaurant_ids[rev["business_id"]],
            "score": stars_to_score(rev["stars"]),
            "created_at": rev["date"].replace(" ", "T"),
        })
        if len(events) >= BATCH_SIZE:
            session.execute(insert(RatingEvent), events)
            stats["events"] += len(events)
            events.clear()
    if events:
        session.execute(insert(RatingEvent), events)
        stats["events"] += len(events)

    return stats
