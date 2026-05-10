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

-- phase 2: per-(user, cuisine) Glicko-inspired state
CREATE TABLE user_credibility (
    user_id           INTEGER NOT NULL REFERENCES users(id),
    cuisine_id        INTEGER NOT NULL REFERENCES cuisines(id),
    credibility_score REAL    NOT NULL DEFAULT 0.5,
    rating_deviation  REAL    NOT NULL DEFAULT 1.0,   -- falls with activity
    volatility        REAL    NOT NULL DEFAULT 0.06,  -- rises if user is inconsistent
    last_updated      TEXT    NOT NULL,
    PRIMARY KEY (user_id, cuisine_id)
);

-- phase 2: append-only log of credibility state changes
CREATE TABLE credibility_history (
    id                INTEGER PRIMARY KEY,
    user_id           INTEGER NOT NULL REFERENCES users(id),
    cuisine_id        INTEGER NOT NULL REFERENCES cuisines(id),
    credibility_score REAL    NOT NULL,
    rating_deviation  REAL    NOT NULL,
    recorded_at       TEXT    NOT NULL
);
