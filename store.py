"""Historisation SQLite des prix observés et des alertes envoyées."""

from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

from sources import Offer

SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    origin        TEXT NOT NULL,
    destination   TEXT NOT NULL,
    depart_date   TEXT NOT NULL,
    return_date   TEXT,
    price         REAL NOT NULL,
    currency      TEXT NOT NULL,
    transfers     INTEGER,
    airline       TEXT,
    source        TEXT,
    trip_class    INTEGER NOT NULL DEFAULT 0,   -- 0 éco, 1 affaires
    observed_on   TEXT NOT NULL,      -- YYYY-MM-DD (granularité jour)
    found_at      TEXT NOT NULL,
    UNIQUE (origin, destination, depart_date, return_date, price,
            trip_class, observed_on)
);

CREATE INDEX IF NOT EXISTS idx_route ON observations (origin, destination, trip_class);
CREATE INDEX IF NOT EXISTS idx_seen  ON observations (observed_on);

CREATE TABLE IF NOT EXISTS alerts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    origin        TEXT NOT NULL,
    destination   TEXT NOT NULL,
    depart_date   TEXT NOT NULL,
    return_date   TEXT,
    price         REAL NOT NULL,
    trip_class    INTEGER NOT NULL DEFAULT 0,
    sent_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_alert_route ON alerts (origin, destination, trip_class);

CREATE TABLE IF NOT EXISTS api_calls (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    provider  TEXT NOT NULL,
    called_on TEXT NOT NULL      -- YYYY-MM-DD
);

CREATE INDEX IF NOT EXISTS idx_api ON api_calls (provider, called_on);

CREATE TABLE IF NOT EXISTS kv_cache (
    key       TEXT PRIMARY KEY,
    value     TEXT NOT NULL,
    stored_on TEXT NOT NULL      -- YYYY-MM-DD
);
"""


class Store:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._migrate()
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def _migrate(self) -> None:
        """Ajoute la colonne trip_class aux bases créées avant son
        introduction. Les données existantes sont de l'économique."""
        for table in ("observations", "alerts"):
            exists = self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,)).fetchone()
            if not exists:
                continue
            cols = [r[1] for r in self.conn.execute(
                f"PRAGMA table_info({table})")]
            if "trip_class" not in cols:
                self.conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN trip_class "
                    "INTEGER NOT NULL DEFAULT 0")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # -- écriture -----------------------------------------------------------
    def record(self, offers: list[Offer]) -> int:
        today = dt.date.today().isoformat()
        rows = [(o.origin, o.destination, o.depart_date, o.return_date,
                 o.price, o.currency, o.transfers, o.airline, o.source,
                 o.trip_class, today, o.found_at) for o in offers]
        cur = self.conn.executemany(
            """INSERT OR IGNORE INTO observations
               (origin, destination, depart_date, return_date, price, currency,
                transfers, airline, source, trip_class, observed_on, found_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
        self.conn.commit()
        return cur.rowcount

    def log_alert(self, offer: Offer) -> None:
        self.conn.execute(
            """INSERT INTO alerts
               (origin, destination, depart_date, return_date, price,
                trip_class, sent_at)
               VALUES (?,?,?,?,?,?,?)""",
            (offer.origin, offer.destination, offer.depart_date,
             offer.return_date, offer.price, offer.trip_class,
             dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")))
        self.conn.commit()

    def log_api_call(self, provider: str) -> None:
        self.conn.execute("INSERT INTO api_calls (provider, called_on) VALUES (?,?)",
                          (provider, dt.date.today().isoformat()))
        self.conn.commit()

    # -- lecture ------------------------------------------------------------
    def route_history(self, origin: str, destination: str,
                      trip_class: int = 0,
                      exclude_today: bool = True) -> list[float]:
        """Tous les prix déjà observés sur cette route, dans cette classe."""
        sql = ("SELECT price FROM observations "
               "WHERE origin = ? AND destination = ? AND trip_class = ?")
        params: list = [origin, destination, trip_class]
        if exclude_today:
            sql += " AND observed_on < ?"
            params.append(dt.date.today().isoformat())
        return [r["price"] for r in self.conn.execute(sql, params)]

    def price_series(self, origin: str, destination: str, trip_class: int = 0,
                     days: int = 30) -> list[tuple[str, float]]:
        """Meilleur prix observé chaque jour, du plus ancien au plus récent.
        C'est ce qui permet de distinguer une baisse progressive d'un
        décrochage brutal — les deux n'appellent pas la même décision."""
        rows = self.conn.execute(
            """SELECT observed_on, MIN(price) AS p FROM observations
               WHERE origin = ? AND destination = ? AND trip_class = ?
               GROUP BY observed_on ORDER BY observed_on DESC LIMIT ?""",
            (origin, destination, trip_class, days)).fetchall()
        return [(r["observed_on"], r["p"]) for r in reversed(rows)]

    def last_alert(self, origin: str, destination: str, depart_date: str,
                   trip_class: int = 0) -> sqlite3.Row | None:
        return self.conn.execute(
            """SELECT price, sent_at FROM alerts
               WHERE origin = ? AND destination = ? AND depart_date = ?
                 AND trip_class = ?
               ORDER BY sent_at DESC LIMIT 1""",
            (origin, destination, depart_date, trip_class)).fetchone()

    def cache_get(self, key: str, ttl_days: int) -> str | None:
        row = self.conn.execute(
            "SELECT value, stored_on FROM kv_cache WHERE key = ?",
            (key,)).fetchone()
        if not row:
            return None
        try:
            age = (dt.date.today()
                   - dt.date.fromisoformat(row["stored_on"])).days
        except ValueError:
            return None
        return row["value"] if age <= ttl_days else None

    def cache_set(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO kv_cache (key, value, stored_on) "
            "VALUES (?,?,?)", (key, value, dt.date.today().isoformat()))
        self.conn.commit()

    def count_api_calls(self, provider: str, since: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) c FROM api_calls WHERE provider = ? AND called_on >= ?",
            (provider, since)).fetchone()
        return row["c"]

    def routes(self) -> list[dict]:
        """Toutes les routes suivies, avec leur état courant."""
        rows = self.conn.execute("""
            SELECT origin, destination, trip_class, currency,
                   COUNT(*) AS n,
                   COUNT(DISTINCT observed_on) AS jours,
                   MIN(price) AS bas, MAX(price) AS haut,
                   MAX(observed_on) AS dernier_jour
            FROM observations
            GROUP BY origin, destination, trip_class
            ORDER BY destination, trip_class""")
        return [dict(r) for r in rows]

    def alerts_log(self, limit: int = 200) -> list[dict]:
        rows = self.conn.execute(
            """SELECT origin, destination, depart_date, return_date, price,
                      trip_class, sent_at FROM alerts
               ORDER BY sent_at DESC LIMIT ?""", (limit,))
        return [dict(r) for r in rows]

    def stats(self) -> dict:
        obs = self.conn.execute(
            "SELECT COUNT(*) c, COUNT(DISTINCT destination) d FROM observations"
        ).fetchone()
        alerts = self.conn.execute("SELECT COUNT(*) c FROM alerts").fetchone()
        days = self.conn.execute(
            "SELECT COUNT(DISTINCT observed_on) c FROM observations").fetchone()
        month_start = dt.date.today().replace(day=1).isoformat()
        biz = self.conn.execute(
            "SELECT COUNT(*) c FROM observations WHERE trip_class = 1"
        ).fetchone()
        return {"observations": obs["c"], "destinations": obs["d"],
                "business": biz["c"],
                "alerts": alerts["c"], "days_of_history": days["c"],
                "serpapi_this_month": self.count_api_calls("serpapi", month_start)}

    def prune(self, keep_days: int = 400) -> int:
        cutoff = (dt.date.today() - dt.timedelta(days=keep_days)).isoformat()
        cur = self.conn.execute(
            "DELETE FROM observations WHERE observed_on < ?", (cutoff,))
        self.conn.commit()
        return cur.rowcount
