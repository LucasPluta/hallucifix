"""Demo 4 models: SQLite-backed job store.

Manages a simple job queue with states: pending → running → done / failed.
This module is CORRECT — the bugs are in worker.py.
"""

import sqlite3
import logging
import os
from pathlib import Path

LOG_FILE = "/tmp/hallucifix_demo4_models.log"

logging.basicConfig(
    filename=LOG_FILE,
    filemode="a",
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s [models] %(message)s",
)
log = logging.getLogger("models")

DB_PATH = os.environ.get("DEMO4_DB", "/tmp/hallucifix_demo4.db")

# ── Schema constants ────────────────────────────────────────────
# Status values are stored as strings in the DB.
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"


def get_connection() -> sqlite3.Connection:
    """Return a new connection to the job database."""
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=3000")
    return conn


def init_db() -> None:
    """Create the jobs table if it doesn't exist."""
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            payload    TEXT    NOT NULL,
            status     TEXT    NOT NULL DEFAULT 'pending',
            result     TEXT,
            retries    INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()
    log.info("Database initialized at %s", DB_PATH)


def enqueue_job(payload: str) -> int:
    """Insert a new job and return its ID."""
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO jobs (payload, status) VALUES (?, ?)",
        (payload, STATUS_PENDING),
    )
    job_id = cur.lastrowid
    conn.commit()
    conn.close()
    log.info("Enqueued job %d: %s", job_id, payload[:80])
    return job_id


def claim_pending_jobs(limit: int = 5) -> list[dict]:
    """Atomically claim up to *limit* pending jobs (set to running)."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, payload FROM jobs WHERE status = ? ORDER BY id LIMIT ?",
        (STATUS_PENDING, limit),
    ).fetchall()
    job_ids = [r["id"] for r in rows]
    if job_ids:
        placeholders = ",".join("?" * len(job_ids))
        conn.execute(
            f"UPDATE jobs SET status = ?, updated_at = CURRENT_TIMESTAMP "
            f"WHERE id IN ({placeholders})",
            [STATUS_RUNNING] + job_ids,
        )
        conn.commit()
    conn.close()
    return [{"id": r["id"], "payload": r["payload"]} for r in rows]


def mark_done(job_id: int, result: str) -> None:
    """Mark a job as done with its result."""
    conn = get_connection()
    conn.execute(
        "UPDATE jobs SET status = ?, result = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (STATUS_DONE, result, job_id),
    )
    conn.commit()
    conn.close()


def mark_failed(job_id: int, retries: int) -> None:
    """Mark a job as failed, updating retry count."""
    conn = get_connection()
    conn.execute(
        "UPDATE jobs SET status = ?, retries = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (STATUS_FAILED, retries, job_id),
    )
    conn.commit()
    conn.close()


def reset_failed_to_pending() -> int:
    """Move all failed jobs back to pending. Returns count."""
    conn = get_connection()
    cur = conn.execute(
        "UPDATE jobs SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE status = ?",
        (STATUS_PENDING, STATUS_FAILED),
    )
    count = cur.rowcount
    conn.commit()
    conn.close()
    return count


def get_job(job_id: int) -> dict | None:
    """Fetch a single job by ID."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    if row is None:
        return None
    return dict(row)


def count_by_status() -> dict[str, int]:
    """Return {status: count} for all jobs."""
    conn = get_connection()
    rows = conn.execute("SELECT status, COUNT(*) as cnt FROM jobs GROUP BY status").fetchall()
    conn.close()
    return {r["status"]: r["cnt"] for r in rows}


def get_all_results() -> list[dict]:
    """Return all completed job results."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, payload, result FROM jobs WHERE status = ?",
        (STATUS_DONE,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
