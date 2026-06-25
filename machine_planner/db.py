"""SQLite persistence layer for the manufacturing process planner.

Models the shop as machines + work orders + operations (routing steps), so a
part can be planned through a sequence of operations across machines
(e.g. CNC mill -> turn -> grind -> inspect).

Standard library only, so the app runs with zero install.
"""

import sqlite3
import os
from contextlib import contextmanager

DB_PATH = os.environ.get(
    "MACHINE_PLANNER_DB",
    os.path.join(os.path.dirname(__file__), "machine_planner.db"),
)

# Common manufacturing machine categories (used for the UI dropdown / seeds).
MACHINE_TYPES = [
    "CNC Milling", "CNC Turning", "Lathe", "Grinding", "Drilling",
    "EDM", "Sawing", "Deburring", "Inspection / CMM", "Assembly",
]

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

CREATE TABLE IF NOT EXISTS work_orders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    part_name   TEXT NOT NULL,
    part_number TEXT NOT NULL DEFAULT '',
    quantity    INTEGER NOT NULL DEFAULT 1,
    due_date    TEXT NOT NULL DEFAULT '',
    priority    TEXT NOT NULL DEFAULT 'normal',       -- low | normal | high | rush
    status      TEXT NOT NULL DEFAULT 'planned',      -- planned | released | in_progress | done
    notes       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS operations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    work_order_id INTEGER NOT NULL,
    seq           INTEGER NOT NULL DEFAULT 10,         -- routing order: 10, 20, 30...
    name          TEXT NOT NULL,                       -- e.g. "Rough mill", "Finish turn"
    machine_id    INTEGER,                             -- assigned machine (nullable until planned)
    setup_min     INTEGER NOT NULL DEFAULT 0,          -- one-time setup minutes
    cycle_min     REAL NOT NULL DEFAULT 0,             -- minutes per piece
    start_time    TEXT NOT NULL DEFAULT '',            -- ISO 8601 once scheduled
    end_time      TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'pending',     -- pending | scheduled | in_progress | done
    notes         TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (work_order_id) REFERENCES work_orders (id) ON DELETE CASCADE,
    FOREIGN KEY (machine_id)    REFERENCES machines (id)    ON DELETE SET NULL
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
        if conn.execute("SELECT COUNT(*) AS n FROM machines").fetchone()["n"] == 0:
            _seed(conn)


def _seed(conn):
    machines = [
        ("HAAS VF-2", "CNC Milling", "Cell 1", "operational", "3-axis"),
        ("DMG Mori NLX", "CNC Turning", "Cell 1", "operational", "live tooling"),
        ("Okuma Grinder", "Grinding", "Cell 2", "operational", "cylindrical"),
        ("Hardinge Lathe", "Lathe", "Cell 2", "operational", ""),
        ("Zeiss CMM", "Inspection / CMM", "QA Lab", "operational", ""),
        ("Bridgeport Mill", "CNC Milling", "Cell 3", "maintenance", "spindle service"),
    ]
    conn.executemany(
        "INSERT INTO machines (name, type, location, status, notes) VALUES (?,?,?,?,?)",
        machines,
    )
    # A sample work order with a 3-step routing: mill -> turn -> inspect.
    conn.execute(
        "INSERT INTO work_orders (part_name, part_number, quantity, due_date, priority, status) "
        "VALUES (?,?,?,?,?,?)",
        ("Hydraulic Manifold", "HM-4420", 25, "2026-06-27", "high", "released"),
    )
    wo_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    ops = [
        (wo_id, 10, "Rough & finish mill", 1, 45, 12.0, "2026-06-25T08:00", "2026-06-25T13:45", "scheduled"),
        (wo_id, 20, "Turn bore", 2, 30, 6.0, "2026-06-25T14:00", "2026-06-25T17:00", "scheduled"),
        (wo_id, 30, "CMM inspection", 5, 20, 2.0, "2026-06-26T08:00", "2026-06-26T09:30", "pending"),
    ]
    conn.executemany(
        "INSERT INTO operations (work_order_id, seq, name, machine_id, setup_min, cycle_min, "
        "start_time, end_time, status) VALUES (?,?,?,?,?,?,?,?,?)",
        ops,
    )


# ---- Machines ----

def list_machines():
    with get_conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM machines ORDER BY name")]


def create_machine(data):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO machines (name, type, location, status, notes) VALUES (?,?,?,?,?)",
            (data.get("name", "").strip(), data.get("type", "").strip(),
             data.get("location", "").strip(), data.get("status", "operational"),
             data.get("notes", "").strip()),
        )
        return dict(conn.execute("SELECT * FROM machines WHERE id=?", (cur.lastrowid,)).fetchone())


def update_machine(machine_id, data):
    with get_conn() as conn:
        existing = conn.execute("SELECT * FROM machines WHERE id=?", (machine_id,)).fetchone()
        if existing is None:
            return None
        m = {**dict(existing), **data}
        conn.execute(
            "UPDATE machines SET name=?, type=?, location=?, status=?, notes=? WHERE id=?",
            (m["name"], m["type"], m["location"], m["status"], m["notes"], machine_id),
        )
        return dict(conn.execute("SELECT * FROM machines WHERE id=?", (machine_id,)).fetchone())


def delete_machine(machine_id):
    with get_conn() as conn:
        return conn.execute("DELETE FROM machines WHERE id=?", (machine_id,)).rowcount > 0


# ---- Work orders ----

def list_work_orders():
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM work_orders ORDER BY "
            "CASE priority WHEN 'rush' THEN 0 WHEN 'high' THEN 1 "
            "WHEN 'normal' THEN 2 ELSE 3 END, due_date")]


def create_work_order(data):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO work_orders (part_name, part_number, quantity, due_date, priority, status, notes) "
            "VALUES (?,?,?,?,?,?,?)",
            (data.get("part_name", "").strip(), data.get("part_number", "").strip(),
             int(data.get("quantity", 1) or 1), data.get("due_date", ""),
             data.get("priority", "normal"), data.get("status", "planned"),
             data.get("notes", "").strip()),
        )
        return dict(conn.execute("SELECT * FROM work_orders WHERE id=?", (cur.lastrowid,)).fetchone())


def update_work_order(wo_id, data):
    with get_conn() as conn:
        existing = conn.execute("SELECT * FROM work_orders WHERE id=?", (wo_id,)).fetchone()
        if existing is None:
            return None
        w = {**dict(existing), **data}
        conn.execute(
            "UPDATE work_orders SET part_name=?, part_number=?, quantity=?, due_date=?, "
            "priority=?, status=?, notes=? WHERE id=?",
            (w["part_name"], w["part_number"], int(w["quantity"] or 1), w["due_date"],
             w["priority"], w["status"], w["notes"], wo_id),
        )
        return dict(conn.execute("SELECT * FROM work_orders WHERE id=?", (wo_id,)).fetchone())


def delete_work_order(wo_id):
    with get_conn() as conn:
        return conn.execute("DELETE FROM work_orders WHERE id=?", (wo_id,)).rowcount > 0


# ---- Operations ----

def list_operations():
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM operations ORDER BY work_order_id, seq")]


def list_operations_for(wo_id):
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM operations WHERE work_order_id=? ORDER BY seq", (wo_id,))]


def create_operation(data):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO operations (work_order_id, seq, name, machine_id, setup_min, cycle_min, "
            "start_time, end_time, status, notes) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (int(data["work_order_id"]), int(data.get("seq", 10) or 10),
             data.get("name", "").strip(), _int_or_none(data.get("machine_id")),
             int(data.get("setup_min", 0) or 0), float(data.get("cycle_min", 0) or 0),
             data.get("start_time", ""), data.get("end_time", ""),
             data.get("status", "pending"), data.get("notes", "").strip()),
        )
        return dict(conn.execute("SELECT * FROM operations WHERE id=?", (cur.lastrowid,)).fetchone())


def update_operation(op_id, data):
    with get_conn() as conn:
        existing = conn.execute("SELECT * FROM operations WHERE id=?", (op_id,)).fetchone()
        if existing is None:
            return None
        o = {**dict(existing), **data}
        conn.execute(
            "UPDATE operations SET seq=?, name=?, machine_id=?, setup_min=?, cycle_min=?, "
            "start_time=?, end_time=?, status=?, notes=? WHERE id=?",
            (int(o["seq"] or 10), o["name"], _int_or_none(o["machine_id"]),
             int(o["setup_min"] or 0), float(o["cycle_min"] or 0), o["start_time"],
             o["end_time"], o["status"], o["notes"], op_id),
        )
        return dict(conn.execute("SELECT * FROM operations WHERE id=?", (op_id,)).fetchone())


def delete_operation(op_id):
    with get_conn() as conn:
        return conn.execute("DELETE FROM operations WHERE id=?", (op_id,)).rowcount > 0


def _int_or_none(v):
    try:
        return int(v) if v not in (None, "", "null") else None
    except (ValueError, TypeError):
        return None
