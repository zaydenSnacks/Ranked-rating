CREATE TABLE users (
    id         INTEGER PRIMARY KEY,
    name       TEXT    NOT NULL,
    email      TEXT    NOT NULL UNIQUE,
    created_at TEXT    NOT NULL
);

CREATE TABLE cuisines (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL UNIQUE,
    description TEXT
);

CREATE TABLE cuisine_distances (
    cuisine_a_id INTEGER NOT NULL REFERENCES cuisines(id),
    cuisine_b_id INTEGER NOT NULL REFERENCES cuisines(id),
    distance     REAL    NOT NULL,  -- 0.0 = identical, 1.0 = completely unrelated
    PRIMARY KEY (cuisine_a_id, cuisine_b_id)
);

CREATE TABLE restaurants (
    id         INTEGER PRIMARY KEY,
    name       TEXT    NOT NULL,
    cuisine_id INTEGER NOT NULL REFERENCES cuisines(id),
    location   TEXT,
    created_at TEXT    NOT NULL
);

CREATE TABLE trusted_sources (
    id       INTEGER PRIMARY KEY,
    user_id  INTEGER NOT NULL UNIQUE REFERENCES users(id),
    added_at TEXT    NOT NULL,
    notes    TEXT
);

CREATE TABLE rating_events (
    id            INTEGER PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(id),
    restaurant_id INTEGER NOT NULL REFERENCES restaurants(id),
    score         REAL    NOT NULL,
    created_at    TEXT    NOT NULL
);
