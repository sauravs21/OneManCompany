"""Smoke tests for the Machine Resources Planner — stdlib only.

Run: python3 test_planner.py
Uses a temporary DB so it never touches your real data.
"""

import os
import tempfile

# Point the DB at a temp file BEFORE importing db.
_tmp = tempfile.mkdtemp()
os.environ["MACHINE_PLANNER_DB"] = os.path.join(_tmp, "test.db")

import db  # noqa: E402
import server  # noqa: E402


def run():
    db.init_db()

    # Seed data should exist
    machines = db.list_machines()
    assert len(machines) >= 1, "expected seeded machines"

    # Create a machine
    m = db.create_machine({"name": "Test Drill", "type": "Drill", "status": "operational"})
    assert m["id"] and m["name"] == "Test Drill"

    # Create two overlapping jobs on the same machine
    db.create_job({
        "name": "Job A", "machine_id": m["id"],
        "start_time": "2026-06-25T08:00", "end_time": "2026-06-25T12:00",
    })
    db.create_job({
        "name": "Job B", "machine_id": m["id"],
        "start_time": "2026-06-25T10:00", "end_time": "2026-06-25T14:00",
    })
    conflicts = server.find_conflicts(db.list_jobs())
    overlap = [c for c in conflicts if c["machine_id"] == m["id"]]
    assert overlap, "expected an overlap conflict on the test machine"

    # Non-overlapping job → no new conflict for a fresh machine
    m2 = db.create_machine({"name": "Test Saw"})
    db.create_job({
        "name": "Job C", "machine_id": m2["id"],
        "start_time": "2026-06-25T08:00", "end_time": "2026-06-25T09:00",
    })
    db.create_job({
        "name": "Job D", "machine_id": m2["id"],
        "start_time": "2026-06-25T09:00", "end_time": "2026-06-25T10:00",
    })
    conflicts2 = [c for c in server.find_conflicts(db.list_jobs()) if c["machine_id"] == m2["id"]]
    assert not conflicts2, "adjacent (non-overlapping) jobs must not conflict"

    # Stats sanity
    stats = server.compute_stats(db.list_machines(), db.list_jobs())
    assert stats["machine_count"] == len(db.list_machines())
    assert stats["job_count"] == len(db.list_jobs())
    assert stats["conflict_count"] >= 1

    # Update + delete
    updated = db.update_machine(m["id"], {"status": "down"})
    assert updated["status"] == "down"
    assert db.delete_machine(m["id"]) is True
    # cascade should remove its jobs
    remaining = [j for j in db.list_jobs() if j["machine_id"] == m["id"]]
    assert not remaining, "deleting a machine should cascade-delete its jobs"

    # Job validation
    assert server._validate_job({"name": "x", "machine_id": m2["id"],
                                 "start_time": "2026-06-25T10:00",
                                 "end_time": "2026-06-25T09:00"}), "end before start should fail"
    assert server._validate_job({"name": "", "machine_id": m2["id"],
                                 "start_time": "2026-06-25T08:00",
                                 "end_time": "2026-06-25T09:00"}), "missing name should fail"

    print("All smoke tests passed ✓")


if __name__ == "__main__":
    run()
