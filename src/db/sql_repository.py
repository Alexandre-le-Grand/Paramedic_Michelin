"""Persistance SQL (SQLite) — tables relationnelles pour requetes et rapports."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config.settings import ROOT, SQLITE_PATH


def _ensure_db(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    schema = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")
    with sqlite3.connect(path) as conn:
        conn.executescript(schema)
        conn.commit()


class SqlRepository:
    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or SQLITE_PATH
        _ensure_db(self.db_path)

    def insert_trajet(self, record: dict[str, Any]) -> int:
        scraped_at = record.get("scraped_at") or datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO trajets (
                    depart, arrivee, distance_km,
                    source, statut, message_erreur, scraped_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["depart"],
                    record["arrivee"],
                    record.get("distance_km"),
                    record.get("source", "viamichelin"),
                    record.get("statut", "ok"),
                    record.get("message_erreur"),
                    scraped_at,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def existing_ok_pairs(self) -> set[tuple[str, str]]:
        """Couples depart->arrivee deja calcules avec succes."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT depart, arrivee
                FROM trajets
                WHERE statut = 'ok' AND distance_km IS NOT NULL
                """
            ).fetchall()
        return {(r[0], r[1]) for r in rows}

    def list_trajets(self, limit: int = 50) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, depart, arrivee, distance_km,
                       source, statut, message_erreur, scraped_at
                FROM trajets
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]