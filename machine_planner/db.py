"""SQLite persistence layer for the machine resources planner.

Uses only the Python standard library so the app runs with zero install.
"""

import sqlite3
import os
from contextlib import contextmanager

DB_PATH = os.environ.get(
    "MACHINE_PLANNER_DB",
    os.path.join(os.path.dirname(__file__), "machine_planner.db"),
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS machines (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    type        TEXT NOT NULL DEFAULT '',
    location    TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'operational',  -- operational | maintenance | down
    notes       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    machine_id  INTEGER NOT NULL,
    start_time  TEXT NOT NULL,   -- ISO 8601, e.g. 2026-06-25T08:00
    end_time    TEXT NOT NULL,
    quantity    INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'scheduled',  -- scheduled | in_progress | done
    notes       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (machine_id) REFERENCES machines (id) ON DELETE CASCADE
);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        # Seed a little sample data the first time so the app isn't empty.
        count = conn.execute("SELECT COUNT(*) AS n FROM machines").fetchone()["n"]
        if count == 0:
            _seed(conn)


def _seed(conn):
    machines = [
        ("CNC Mill #1", "CNC Mill", "Bay A", "operational", "5-axis"),
        ("Lathe #2", "Lathe", "Bay A", "operational", ""),
        ("Laser Cutter", "Laser", "Bay B", "maintenance", "Annual service"),
        ("Press Brake", "Press", "Bay B", "operational", ""),
    ]
    conn.executemany(
        "INSERT INTO machines (name, type, location, status, notes) VALUES (?,?,?,?,?)",
        machines,
    )
    jobs = [
        ("Bracket batch A", 1, "2026-06-25T08:00", "2026-06-25T12:00", 200, "in_progress", ""),
        ("Shaft turning", 2, "2026-06-25T09:00", "2026-06-25T15:00", 50, "scheduled", ""),
        ("Panel cut run", 4, "2026-06-25T13:00", "2026-06-25T17:00", 120, "scheduled", ""),
        ("Bracket batch B", 1, "2026-06-25T13:00", "2026-06-25T16:00", 150, "scheduled", ""),
    ]
    conn.executemany(
        "INSERT INTO jobs (name, machine_id, start_time, end_time, quantity, status, notes) "
        "VALUES (?,?,?,?,?,?,?)",
        jobs,
    )


# ---- Machines ----

def list_machines():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM machines ORDER BY name").fetchall()
        return [dict(r) for r in rows]


def create_machine(data):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO machines (name, type, location, status, notes) VALUES (?,?,?,?,?)",
            (
                data.get("name", "").strip(),
                data.get("type", "").strip(),
                data.get("location", "").strip(),
                data.get("status", "operational"),
                data.get("notes", "").strip(),
            ),
        )
        row = conn.execute("SELECT * FROM machines WHERE id=?", (cur.lastrowid,)).fetchone()
        return dict(row)


def update_machine(machine_id, data):
    with get_conn() as conn:
        existing = conn.execute("SELECT * FROM machines WHERE id=?", (machine_id,)).fetchone()
        if existing is None:
            return None
        merged = {**dict(existing), **data}
        conn.execute(
            "UPDATE machines SET name=?, type=?, location=?, status=?, notes=? WHERE id=?",
            (
                merged["name"], merged["type"], merged["location"],
                merged["status"], merged["notes"], machine_id,
            ),
        )
        row = conn.execute("SELECT * FROM machines WHERE id=?", (machine_id,)).fetchone()
        return dict(row)


def delete_machine(machine_id):
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM machines WHERE id=?", (machine_id,))
        return cur.rowcount > 0


# ---- Jobs ----

def list_jobs():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM jobs ORDER BY start_time").fetchall()
        return [dict(r) for r in rows]


def create_job(data):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO jobs (name, machine_id, start_time, end_time, quantity, status, notes) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                data.get("name", "").strip(),
                int(data["machine_id"]),
                data["start_time"],
                data["end_time"],
                int(data.get("quantity", 0) or 0),
                data.get("status", "scheduled"),
                data.get("notes", "").strip(),
            ),
        )
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (cur.lastrowid,)).fetchone()
        return dict(row)


def update_job(job_id, data):
    with get_conn() as conn:
        existing = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if existing is None:
            return None
        merged = {**dict(existing), **data}
        conn.execute(
            "UPDATE jobs SET name=?, machine_id=?, start_time=?, end_time=?, "
            "quantity=?, status=?, notes=? WHERE id=?",
            (
                merged["name"], int(merged["machine_id"]), merged["start_time"],
                merged["end_time"], int(merged["quantity"] or 0), merged["status"],
                merged["notes"], job_id,
            ),
        )
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row)


def delete_job(job_id):
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
        return cur.rowcount > 0
