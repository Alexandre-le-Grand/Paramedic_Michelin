-- Schema SQLite pour les trajets (SQL relationnel)
CREATE TABLE IF NOT EXISTS trajets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    depart TEXT NOT NULL,
    arrivee TEXT NOT NULL,
    distance_km REAL,
    source TEXT NOT NULL DEFAULT 'viamichelin',
    statut TEXT NOT NULL DEFAULT 'ok',
    message_erreur TEXT,
    scraped_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_trajets_depart_arrivee ON trajets(depart, arrivee);