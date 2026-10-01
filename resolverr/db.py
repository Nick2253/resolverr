import sqlite3
import json
import time
from contextlib import contextmanager
from enum import Enum

from .config import Config


class JobStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    BLACKLISTING = "blacklisting"
    DELETING = "deleting"
    SEARCHING = "searching"
    WAITING_IMPORT = "waiting_import"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                seerr_issue_id INTEGER NOT NULL,
                media_type TEXT NOT NULL,
                media_title TEXT NOT NULL,
                arr_id INTEGER,
                file_id INTEGER,
                file_path TEXT,
                release_name TEXT,
                issue_type TEXT,
                reporter TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                error TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                completed_at REAL,
                metadata TEXT DEFAULT '{}'
            )
        """)
        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)
        """)
        db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_issue
            ON jobs(seerr_issue_id)
        """)
        db.commit()


@contextmanager
def get_db():
    conn = sqlite3.connect(Config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def create_job(job_id, seerr_issue_id, media_type, media_title, issue_type,
               reporter, arr_id=None, file_id=None, file_path=None,
               release_name=None):
    now = time.time()
    with get_db() as db:
        db.execute(
            """INSERT OR IGNORE INTO jobs
               (id, seerr_issue_id, media_type, media_title, arr_id, file_id,
                file_path, release_name, issue_type, reporter, status,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (job_id, seerr_issue_id, media_type, media_title, arr_id, file_id,
             file_path, release_name, issue_type, reporter, JobStatus.PENDING,
             now, now)
        )
        db.commit()
        return db.total_changes > 0


def update_job_status(job_id, status, error=None):
    now = time.time()
    completed = now if status in (JobStatus.COMPLETED, JobStatus.FAILED,
                                  JobStatus.REJECTED) else None
    with get_db() as db:
        db.execute(
            """UPDATE jobs SET status = ?, error = ?, updated_at = ?,
               completed_at = COALESCE(?, completed_at) WHERE id = ?""",
            (status, error, now, completed, job_id)
        )
        db.commit()


def update_job_arr_info(job_id, arr_id, file_id, file_path, release_name):
    with get_db() as db:
        db.execute(
            """UPDATE jobs SET arr_id = ?, file_id = ?, file_path = ?,
               release_name = ?, updated_at = ? WHERE id = ?""",
            (arr_id, file_id, file_path, release_name, time.time(), job_id)
        )
        db.commit()


def get_job(job_id):
    with get_db() as db:
        row = db.execute("SELECT * FROM jobs WHERE id = ?",
                         (job_id,)).fetchone()
        return dict(row) if row else None


def get_job_by_issue(seerr_issue_id):
    with get_db() as db:
        row = db.execute("SELECT * FROM jobs WHERE seerr_issue_id = ?",
                         (seerr_issue_id,)).fetchone()
        return dict(row) if row else None


def get_jobs_by_status(status):
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC",
            (status,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_recent_jobs(limit=50):
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
