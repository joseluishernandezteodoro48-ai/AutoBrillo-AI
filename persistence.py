"""Capa de persistencia unificada para AutoBrillo AI.

Usa PostgreSQL cuando DATABASE_URL está resuelta y psycopg está disponible.
Si no, cae de forma segura a SQLite (desarrollo local / fallback).

Tablas:
- events
- permissions
- metrics
- goals
- goal_tasks
- catalog_products
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Generator, Iterable, Optional

try:
    import psycopg
except ImportError:
    psycopg = None  # type: ignore


def _database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    # Evitar referencias no resueltas de Blueprint
    if not url or "${" in url or "{{" in url:
        return ""
    if "sslmode=" not in url.lower():
        url = url + ("&" if "?" in url else "?") + "sslmode=require"
    return url


def postgres_available() -> bool:
    return bool(_database_url() and psycopg)


class Persistence:
    """Abstracción mínima sobre Postgres o SQLite."""

    def __init__(self, sqlite_path: str | None = None):
        self.sqlite_path = sqlite_path or os.getenv("AUTOBRILLO_DB", "autobrillo.db")
        self.use_postgres = postgres_available()
        self._ensure_schema()

    def backend(self) -> str:
        return "postgresql" if self.use_postgres else "sqlite"

    def health(self) -> dict[str, Any]:
        if not self.use_postgres:
            return {
                "configured": False,
                "connected": False,
                "backend": "sqlite",
                "error": "DATABASE_URL no disponible o no resuelta; usando SQLite local.",
            }
        try:
            with self._pg() as conn:
                conn.execute("SELECT 1")
            return {
                "configured": True,
                "connected": True,
                "backend": "postgresql",
                "error": None,
            }
        except Exception as exc:
            return {
                "configured": True,
                "connected": False,
                "backend": "postgresql",
                "error": str(exc)[:300],
            }

    @contextmanager
    def _pg(self) -> Generator[Any, None, None]:
        assert psycopg is not None
        with psycopg.connect(_database_url(), connect_timeout=8) as conn:
            yield conn

    def _sqlite(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.sqlite_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        if self.use_postgres:
            with self._pg() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS events (
                        id BIGSERIAL PRIMARY KEY,
                        ts DOUBLE PRECISION NOT NULL,
                        kind TEXT NOT NULL,
                        data TEXT NOT NULL,
                        outcome TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS permissions (
                        name TEXT PRIMARY KEY,
                        enabled INTEGER NOT NULL DEFAULT 0
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS metrics (
                        id BIGSERIAL PRIMARY KEY,
                        ts DOUBLE PRECISION NOT NULL,
                        product TEXT NOT NULL,
                        event TEXT NOT NULL,
                        value DOUBLE PRECISION DEFAULT 0
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS goals (
                        id BIGSERIAL PRIMARY KEY,
                        text TEXT NOT NULL,
                        target_count INTEGER NOT NULL,
                        action TEXT NOT NULL,
                        status TEXT NOT NULL,
                        created_at DOUBLE PRECISION NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS goal_tasks (
                        id BIGSERIAL PRIMARY KEY,
                        goal_id BIGINT NOT NULL,
                        seq INTEGER NOT NULL,
                        action TEXT NOT NULL,
                        product TEXT,
                        status TEXT NOT NULL,
                        result TEXT,
                        created_at DOUBLE PRECISION NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS catalog_products (
                        name TEXT PRIMARY KEY,
                        payload JSONB NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                conn.commit()
        else:
            with self._sqlite() as c:
                c.execute("PRAGMA journal_mode=WAL")
                c.execute(
                    "CREATE TABLE IF NOT EXISTS events("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, data TEXT, outcome TEXT)"
                )
                c.execute(
                    "CREATE TABLE IF NOT EXISTS permissions("
                    "name TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0)"
                )
                c.execute(
                    "CREATE TABLE IF NOT EXISTS metrics("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, product TEXT, event TEXT, value REAL DEFAULT 0)"
                )
                c.execute(
                    "CREATE TABLE IF NOT EXISTS goals("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, "
                    "target_count INTEGER NOT NULL, action TEXT NOT NULL, "
                    "status TEXT NOT NULL, created_at REAL NOT NULL)"
                )
                c.execute(
                    "CREATE TABLE IF NOT EXISTS goal_tasks("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, goal_id INTEGER NOT NULL, "
                    "seq INTEGER NOT NULL, action TEXT NOT NULL, product TEXT, "
                    "status TEXT NOT NULL, result TEXT, created_at REAL NOT NULL)"
                )
                c.execute(
                    "CREATE TABLE IF NOT EXISTS catalog_products("
                    "name TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at REAL NOT NULL)"
                )
                c.commit()

    # ------------------------------------------------------------------
    # Events / permissions / metrics (Memory)
    # ------------------------------------------------------------------

    def remember(self, kind: str, data: Any, outcome: Optional[str] = None) -> None:
        payload = json.dumps(data, ensure_ascii=False)
        ts = time.time()
        if self.use_postgres:
            with self._pg() as conn:
                conn.execute(
                    "INSERT INTO events(ts, kind, data, outcome) VALUES(%s, %s, %s, %s)",
                    (ts, kind, payload, outcome),
                )
                conn.commit()
        else:
            with self._sqlite() as c:
                c.execute(
                    "INSERT INTO events(ts, kind, data, outcome) VALUES(?,?,?,?)",
                    (ts, kind, payload, outcome),
                )
                c.commit()

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        if self.use_postgres:
            with self._pg() as conn:
                rows = conn.execute(
                    "SELECT ts, kind, data, outcome FROM events ORDER BY id DESC LIMIT %s",
                    (limit,),
                ).fetchall()
        else:
            with self._sqlite() as c:
                rows = c.execute(
                    "SELECT ts, kind, data, outcome FROM events ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        out = []
        for r in rows:
            try:
                data = json.loads(r[2])
            except Exception:
                data = {}
            out.append({"ts": r[0], "kind": r[1], "data": data, "outcome": r[3]})
        return out

    def set_permission(self, name: str, enabled: bool = True) -> None:
        if self.use_postgres:
            with self._pg() as conn:
                conn.execute(
                    "INSERT INTO permissions(name, enabled) VALUES(%s, %s) "
                    "ON CONFLICT(name) DO UPDATE SET enabled=EXCLUDED.enabled",
                    (name, int(enabled)),
                )
                conn.commit()
        else:
            with self._sqlite() as c:
                c.execute(
                    "INSERT INTO permissions(name, enabled) VALUES(?,?) "
                    "ON CONFLICT(name) DO UPDATE SET enabled=excluded.enabled",
                    (name, int(enabled)),
                )
                c.commit()
        self.remember("permission", {"name": name, "enabled": bool(enabled)}, "updated")

    def allowed(self, name: str) -> bool:
        if self.use_postgres:
            with self._pg() as conn:
                row = conn.execute(
                    "SELECT enabled FROM permissions WHERE name=%s", (name,)
                ).fetchone()
        else:
            with self._sqlite() as c:
                row = c.execute(
                    "SELECT enabled FROM permissions WHERE name=?", (name,)
                ).fetchone()
        return bool(row and row[0])

    def metric(self, product: str, event: str, value: float = 0) -> None:
        ts = time.time()
        if self.use_postgres:
            with self._pg() as conn:
                conn.execute(
                    "INSERT INTO metrics(ts, product, event, value) VALUES(%s, %s, %s, %s)",
                    (ts, product, event, float(value)),
                )
                conn.commit()
        else:
            with self._sqlite() as c:
                c.execute(
                    "INSERT INTO metrics(ts, product, event, value) VALUES(?,?,?,?)",
                    (ts, product, event, float(value)),
                )
                c.commit()

    def metrics(self, product: Optional[str] = None) -> dict[str, dict[str, float]]:
        if self.use_postgres:
            with self._pg() as conn:
                if product:
                    rows = conn.execute(
                        "SELECT event, COUNT(*), COALESCE(SUM(value),0) FROM metrics "
                        "WHERE product=%s GROUP BY event",
                        (product,),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT event, COUNT(*), COALESCE(SUM(value),0) FROM metrics GROUP BY event"
                    ).fetchall()
        else:
            with self._sqlite() as c:
                if product:
                    rows = c.execute(
                        "SELECT event, COUNT(*), COALESCE(SUM(value),0) FROM metrics "
                        "WHERE product=? GROUP BY event",
                        (product,),
                    ).fetchall()
                else:
                    rows = c.execute(
                        "SELECT event, COUNT(*), COALESCE(SUM(value),0) FROM metrics GROUP BY event"
                    ).fetchall()
        return {e: {"count": n, "value": v} for e, n, v in rows}

    # ------------------------------------------------------------------
    # Catalog
    # ------------------------------------------------------------------

    def load_catalog(self) -> list[dict[str, Any]]:
        if self.use_postgres:
            with self._pg() as conn:
                rows = conn.execute(
                    "SELECT payload FROM catalog_products ORDER BY name"
                ).fetchall()
            result = []
            for (payload,) in rows:
                if isinstance(payload, dict):
                    result.append(payload)
                else:
                    try:
                        result.append(json.loads(payload))
                    except Exception:
                        pass
            return result
        else:
            with self._sqlite() as c:
                rows = c.execute(
                    "SELECT payload FROM catalog_products ORDER BY name"
                ).fetchall()
            result = []
            for (payload,) in rows:
                try:
                    result.append(json.loads(payload))
                except Exception:
                    pass
            return result

    def save_catalog_product(self, name: str, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False)
        if self.use_postgres:
            with self._pg() as conn:
                conn.execute(
                    "INSERT INTO catalog_products(name, payload, updated_at) "
                    "VALUES(%s, %s::jsonb, NOW()) "
                    "ON CONFLICT(name) DO UPDATE SET payload=EXCLUDED.payload, updated_at=NOW()",
                    (name, raw),
                )
                conn.commit()
        else:
            with self._sqlite() as c:
                c.execute(
                    "INSERT INTO catalog_products(name, payload, updated_at) VALUES(?,?,?) "
                    "ON CONFLICT(name) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at",
                    (name, raw, time.time()),
                )
                c.commit()

    def delete_catalog_product(self, name: str) -> None:
        if self.use_postgres:
            with self._pg() as conn:
                conn.execute("DELETE FROM catalog_products WHERE name=%s", (name,))
                conn.commit()
        else:
            with self._sqlite() as c:
                c.execute("DELETE FROM catalog_products WHERE name=?", (name,))
                c.commit()

    # ------------------------------------------------------------------
    # Goals (usado por GoalAgent)
    # ------------------------------------------------------------------

    def create_goal(
        self, text: str, target_count: int, action: str, status: str = "active"
    ) -> int:
        now = time.time()
        if self.use_postgres:
            with self._pg() as conn:
                row = conn.execute(
                    "INSERT INTO goals(text, target_count, action, status, created_at) "
                    "VALUES(%s, %s, %s, %s, %s) RETURNING id",
                    (text, target_count, action, status, now),
                ).fetchone()
                conn.commit()
                return int(row[0])
        else:
            with self._sqlite() as c:
                cur = c.execute(
                    "INSERT INTO goals(text, target_count, action, status, created_at) "
                    "VALUES(?,?,?,?,?)",
                    (text, target_count, action, status, now),
                )
                c.commit()
                return int(cur.lastrowid)

    def list_active_goals(self) -> list[tuple]:
        if self.use_postgres:
            with self._pg() as conn:
                return conn.execute(
                    "SELECT id, text, target_count, action, status, created_at "
                    "FROM goals WHERE status='active' ORDER BY id DESC"
                ).fetchall()
        else:
            with self._sqlite() as c:
                return c.execute(
                    "SELECT id, text, target_count, action, status, created_at "
                    "FROM goals WHERE status='active' ORDER BY id DESC"
                ).fetchall()

    def replace_goal_tasks(self, goal_id: int, tasks: Iterable[dict[str, Any]]) -> None:
        if self.use_postgres:
            with self._pg() as conn:
                conn.execute("DELETE FROM goal_tasks WHERE goal_id=%s", (goal_id,))
                for seq, task in enumerate(tasks, 1):
                    conn.execute(
                        "INSERT INTO goal_tasks(goal_id, seq, action, product, status, result, created_at) "
                        "VALUES(%s, %s, %s, %s, %s, %s, %s)",
                        (
                            goal_id,
                            seq,
                            task["action"],
                            task.get("product"),
                            task["status"],
                            json.dumps(task, ensure_ascii=False),
                            time.time(),
                        ),
                    )
                conn.commit()
        else:
            with self._sqlite() as c:
                c.execute("DELETE FROM goal_tasks WHERE goal_id=?", (goal_id,))
                for seq, task in enumerate(tasks, 1):
                    c.execute(
                        "INSERT INTO goal_tasks(goal_id, seq, action, product, status, result, created_at) "
                        "VALUES(?,?,?,?,?,?,?)",
                        (
                            goal_id,
                            seq,
                            task["action"],
                            task.get("product"),
                            task["status"],
                            json.dumps(task, ensure_ascii=False),
                            time.time(),
                        ),
                    )
                c.commit()
