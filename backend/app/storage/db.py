"""Persistência local em SQLite para execuções (live e backtest).

Só o processo principal do FastAPI toca este arquivo; os processos filhos de
análise (backend/app/execution/worker.py) só se comunicam por fila e nunca
abrem o banco diretamente, evitando contenção entre processos do SQLite.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

_lock = threading.Lock()
_connection: sqlite3.Connection | None = None


def _sqlite_path(database_url: str) -> Path:
    prefix = "sqlite:///"
    raw = database_url[len(prefix):] if database_url.startswith(prefix) else database_url
    path = Path(raw)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def init_db(database_url: str) -> None:
    global _connection
    path = _sqlite_path(database_url)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            backtest_job_id TEXT,
            symbol TEXT NOT NULL,
            trade_date TEXT,
            status TEXT NOT NULL,
            decision TEXT,
            rating_5tier TEXT,
            summary TEXT,
            model TEXT,
            provider TEXT,
            started_at TEXT,
            finished_at TEXT,
            error TEXT,
            quote_json TEXT,
            logs_json TEXT,
            raw_return REAL,
            alpha_return REAL,
            benchmark TEXT,
            holding_days INTEGER,
            resolution_date TEXT,
            pid INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS backtest_jobs (
            id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            holding_days INTEGER NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            total_dates INTEGER,
            completed_dates INTEGER DEFAULT 0,
            current_date TEXT,
            cancel_requested INTEGER DEFAULT 0,
            error TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_kind ON runs(kind, started_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_job ON runs(backtest_job_id)")
    conn.commit()
    _connection = conn


def _conn() -> sqlite3.Connection:
    if _connection is None:
        raise RuntimeError("Banco de dados não inicializado; chame init_db() no startup")
    return _connection


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    if data.get("quote_json"):
        try:
            data["quote"] = json.loads(data["quote_json"])
        except (json.JSONDecodeError, TypeError):
            data["quote"] = None
    else:
        data["quote"] = None
    if data.get("logs_json"):
        try:
            data["logs"] = json.loads(data["logs_json"])
        except (json.JSONDecodeError, TypeError):
            data["logs"] = []
    else:
        data["logs"] = []
    return data


_RUN_FIELDS = [
    "id", "kind", "backtest_job_id", "symbol", "trade_date", "status", "decision",
    "rating_5tier", "summary", "model", "provider", "started_at", "finished_at",
    "error", "quote_json", "logs_json", "raw_return", "alpha_return", "benchmark",
    "holding_days", "resolution_date", "pid",
]


def upsert_run(run: dict[str, Any]) -> None:
    """Insert a new run or patch an existing one with only the given fields.

    Partial calls (e.g. an event handler updating just ``logs``) must never
    clobber columns they don't mention — an earlier version rebuilt the whole
    row from ``run.get(key)`` on every call, which silently NULLed out
    ``kind``/``symbol``/``status`` on every incremental log update and could
    violate the NOT NULL constraints outright.
    """
    run = dict(run)
    if "quote" in run:
        run["quote_json"] = json.dumps(run.pop("quote"), ensure_ascii=False)
    if "logs" in run:
        run["logs_json"] = json.dumps(run.pop("logs"), ensure_ascii=False)
    run_id = run["id"]
    columns = [key for key in run if key != "id" and key in _RUN_FIELDS]
    with _lock:
        updated = 0
        if columns:
            assignments = ", ".join(f"{col} = :{col}" for col in columns)
            cursor = _conn().execute(f"UPDATE runs SET {assignments} WHERE id = :id", run)
            updated = cursor.rowcount
        if updated == 0:
            values = {field: run.get(field) for field in _RUN_FIELDS}
            values["id"] = run_id
            placeholders = ", ".join(f":{field}" for field in _RUN_FIELDS)
            _conn().execute(
                f"INSERT INTO runs ({', '.join(_RUN_FIELDS)}) VALUES ({placeholders})",
                values,
            )
        _conn().commit()


def get_run(run_id: str) -> dict[str, Any] | None:
    with _lock:
        row = _conn().execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    return _row_to_dict(row)


def get_last_run(kind: str = "live") -> dict[str, Any] | None:
    with _lock:
        row = _conn().execute(
            "SELECT * FROM runs WHERE kind = ? ORDER BY started_at DESC LIMIT 1", (kind,)
        ).fetchone()
    return _row_to_dict(row)


def list_runs(kind: str | None = None, backtest_job_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    query = "SELECT * FROM runs WHERE 1=1"
    params: list[Any] = []
    if kind:
        query += " AND kind = ?"
        params.append(kind)
    if backtest_job_id:
        query += " AND backtest_job_id = ?"
        params.append(backtest_job_id)
    query += " ORDER BY started_at ASC LIMIT ?"
    params.append(limit)
    with _lock:
        rows = _conn().execute(query, params).fetchall()
    return [_row_to_dict(row) for row in rows]


def _kill_pid_best_effort(pid: int) -> None:
    """Best-effort termination of a leftover analysis child process left behind
    by a killed/reloaded parent (uvicorn --reload, crash, Ctrl+C). The parent
    process dying does not stop a spawned multiprocessing.Process on Windows —
    there is no parent-death signal — so this startup sweep is the backstop.
    """
    import subprocess
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/F", "/T"],
            capture_output=True, timeout=5, check=False,
        )
    except Exception:
        pass


def reconcile_orphan_runs(message: str) -> list[str]:
    """Mark any run left RUNNING from a previous process as ERROR, and try to
    kill its recorded child PID (if any) so it stops burning GPU/CPU in the
    background. Returns affected ids."""
    with _lock:
        rows = _conn().execute("SELECT id, pid FROM runs WHERE status = 'RUNNING'").fetchall()
        ids = [row["id"] for row in rows]
        pids = [row["pid"] for row in rows if row["pid"]]
        if ids:
            _conn().executemany(
                "UPDATE runs SET status = 'ERROR', error = ?, finished_at = COALESCE(finished_at, started_at) WHERE id = ?",
                [(message, run_id) for run_id in ids],
            )
            _conn().commit()
    for pid in pids:
        _kill_pid_best_effort(pid)
    return ids


def create_backtest_job(job: dict[str, Any]) -> None:
    fields = ["id", "symbol", "start_date", "end_date", "holding_days", "status", "created_at", "total_dates"]
    values = {key: job.get(key) for key in fields}
    with _lock:
        _conn().execute(
            f"INSERT INTO backtest_jobs ({', '.join(fields)}) VALUES ({', '.join(':' + f for f in fields)})",
            values,
        )
        _conn().commit()


def update_backtest_job(job_id: str, **fields: Any) -> None:
    if not fields:
        return
    assignments = ", ".join(f"{key} = :{key}" for key in fields)
    fields["id"] = job_id
    with _lock:
        _conn().execute(f"UPDATE backtest_jobs SET {assignments} WHERE id = :id", fields)
        _conn().commit()


def get_backtest_job(job_id: str) -> dict[str, Any] | None:
    with _lock:
        row = _conn().execute("SELECT * FROM backtest_jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def list_backtest_jobs(limit: int = 50) -> list[dict[str, Any]]:
    with _lock:
        rows = _conn().execute(
            "SELECT * FROM backtest_jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(row) for row in rows]


def reconcile_orphan_backtest_jobs(message: str) -> list[str]:
    with _lock:
        rows = _conn().execute("SELECT id FROM backtest_jobs WHERE status = 'RUNNING'").fetchall()
        ids = [row["id"] for row in rows]
        if ids:
            _conn().executemany(
                "UPDATE backtest_jobs SET status = 'ERROR', error = ? WHERE id = ?",
                [(message, job_id) for job_id in ids],
            )
            _conn().commit()
    return ids
