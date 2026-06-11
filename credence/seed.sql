-- users
INSERT INTO users VALUES (1, 'Sarah Chen',   'sarah.chen@credence.io',  '2024-01-01');
INSERT INTO users VALUES (2, 'Marcus Webb',  'marcus.webb@credence.io', '2024-01-01');
INSERT INTO users VALUES (3, 'Priya Nair',   'priya.nair@gmail.com',    '2024-02-10');
INSERT INTO users VALUES (4, 'Derek Torres', 'derek.torres@gmail.com',  '2024-03-05');
INSERT INTO users VALUES (5, 'Jamie Liu',    'jamie.liu@gmail.com',     '2024-03-20');

-- cuisines
INSERT INTO cuisines VALUES (1, 'Chinese',       'Cantonese, dumplings, HK-style noodles');
INSERT INTO cuisines VALUES (2, 'Italian',       'NY-style pizza, Neapolitan, red sauce');
INSERT INTO cuisines VALUES (3, 'Japanese',      'Ramen, tonkotsu, izakaya');
INSERT INTO cuisines VALUES (4, 'Korean Fusion', 'Korean-Southern American crossover');
INSERT INTO cuisines VALUES (5, 'American',      'Diner food with Asian influence');

-- cuisine_distances (stored both directions so proximity queries always filter on cuisine_a_id)
INSERT INTO cuisine_distances VALUES (1, 2, 0.80); -- Chinese       -> Italian
INSERT INTO cuisine_distances VALUES (2, 1, 0.80); -- Italian       -> Chinese
INSERT INTO cuisine_distances VALUES (1, 3, 0.25); -- Chinese       -> Japanese
INSERT INTO cuisine_distances VALUES (3, 1, 0.25); -- Japanese      -> Chinese
INSERT INTO cuisine_distances VALUES (1, 4, 0.30); -- Chinese       -> Korean Fusion
INSERT INTO cuisine_distances VALUES (4, 1, 0.30); -- Korean Fusion -> Chinese
INSERT INTO cuisine_distances VALUES (1, 5, 0.60); -- Chinese       -> American
INSERT INTO cuisine_distances VALUES (5, 1, 0.60); -- American      -> Chinese
INSERT INTO cuisine_distances VALUES (2, 3, 0.80); -- Italian       -> Japanese
INSERT INTO cuisine_distances VALUES (3, 2, 0.80); -- Japanese      -> Italian
INSERT INTO cuisine_distances VALUES (2, 4, 0.70); -- Italian       -> Korean Fusion
INSERT INTO cuisine_distances VALUES (4, 2, 0.70); -- Korean Fusion -> Italian
INSERT INTO cuisine_distances VALUES (2, 5, 0.35); -- Italian       -> American
INSERT INTO cuisine_distances VALUES (5, 2, 0.35); -- American      -> Italian
INSERT INTO cuisine_distances VALUES (3, 4, 0.20); -- Japanese      -> Korean Fusion
INSERT INTO cuisine_distances VALUES (4, 3, 0.20); -- Korean Fusion -> Japanese
INSERT INTO cuisine_distances VALUES (3, 5, 0.55); -- Japanese      -> American
INSERT INTO cuisine_distances VALUES (5, 3, 0.55); -- American      -> Japanese
INSERT INTO cuisine_distances VALUES (4, 5, 0.40); -- Korean Fusion -> American
INSERT INTO cuisine_distances VALUES (5, 4, 0.40); -- American      -> Korean Fusion

-- restaurants
INSERT INTO restaurants VALUES (1, 'C as in Charlie',       4, '5 Bleecker St, Noho, NY',       '2024-01-01');
INSERT INTO restaurants VALUES (2, 'Golden Diner',           5, '123 Madison St, Chinatown, NY',  '2024-01-01');
INSERT INTO restaurants VALUES (3, 'Jin Mei Dumpling',       1, '25B Henry St, Chinatown, NY',    '2024-01-01');
INSERT INTO restaurants VALUES (4, 'E Noodle Chinatown',     1, '26 Jefferson St, Chinatown, NY', '2024-01-01');
INSERT INTO restaurants VALUES (5, 'Nolita Pizza',           2, '68 Kenmare St, Nolita, NY',      '2024-01-01');
INSERT INTO restaurants VALUES (6, 'TONCHIN New York',       3, '13 W 36th St, Midtown, NY',      '2024-01-01');
INSERT INTO restaurants VALUES (7, 'Joe''s Pizza Broadway',  2, '1435 Broadway, Midtown, NY',     '2024-01-01');

-- trusted_sources
INSERT INTO trusted_sources VALUES (1, 1, '2024-01-01', 'Michelin-aligned palate, broad coverage');
INSERT INTO trusted_sources VALUES (2, 2, '2024-01-01', 'Food writer, strong on Asian and Italian');

-- rating_events (15 rows)
-- Scores are on credence's 1–10 scale. Originally authored on a 5-star scale,
-- converted with the same affine map the Yelp importer uses:
-- score = 1 + (stars − 1) × 2.25   (3.5→6.625, 4.0→7.75, 4.5→8.875, 5.0→10.0)

-- Sarah Chen (trusted)
INSERT INTO rating_events VALUES (1,  1, 3, 8.875,  '2024-01-15'); -- Jin Mei Dumpling
INSERT INTO rating_events VALUES (2,  1, 6, 8.875,  '2024-01-20'); -- TONCHIN
INSERT INTO rating_events VALUES (3,  1, 5, 8.875,  '2024-02-01'); -- Nolita Pizza
INSERT INTO rating_events VALUES (4,  1, 1, 10.0,   '2024-02-10'); -- C as in Charlie

-- Marcus Webb (trusted)
INSERT INTO rating_events VALUES (5,  2, 3, 10.0,   '2024-01-18'); -- Jin Mei Dumpling
INSERT INTO rating_events VALUES (6,  2, 7, 7.75,   '2024-02-05'); -- Joe's Pizza Broadway
INSERT INTO rating_events VALUES (7,  2, 6, 8.875,  '2024-02-15'); -- TONCHIN

-- Priya Nair (Asian expert — high alignment with trusted on Chinese + Japanese)
INSERT INTO rating_events VALUES (8,  3, 3, 10.0,   '2024-03-01'); -- Jin Mei Dumpling
INSERT INTO rating_events VALUES (9,  3, 4, 8.875,  '2024-03-05'); -- E Noodle Chinatown
INSERT INTO rating_events VALUES (10, 3, 6, 8.875,  '2024-03-10'); -- TONCHIN
INSERT INTO rating_events VALUES (11, 3, 2, 7.75,   '2024-03-15'); -- Golden Diner

-- Derek Torres (harsh — diverges from trusted on Italian)
INSERT INTO rating_events VALUES (12, 4, 7, 6.625,  '2024-04-01'); -- Joe's Pizza Broadway
INSERT INTO rating_events VALUES (13, 4, 5, 7.75,   '2024-04-10'); -- Nolita Pizza

-- Jamie Liu (generous but unreliable — mismatches trusted on Korean)
INSERT INTO rating_events VALUES (14, 5, 3, 10.0,   '2024-04-15'); -- Jin Mei Dumpling
INSERT INTO rating_events VALUES (15, 5, 1, 6.625,  '2024-04-20'); -- C as in Charlie
