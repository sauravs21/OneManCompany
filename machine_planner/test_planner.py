"""Smoke tests for the Manufacturing Process Planner — stdlib only.

Run: python3 test_planner.py
Uses a temporary DB so it never touches your real data.
"""

import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["MACHINE_PLANNER_DB"] = os.path.join(_tmp, "test.db")

import db  # noqa: E402
import server  # noqa: E402


def run():
    db.init_db()

    # Seed data should exist (machines + a sample work order with a routing)
    assert len(db.list_machines()) >= 1, "expected seeded machines"
    assert len(db.list_work_orders()) >= 1, "expected a seeded work order"
    assert len(db.list_operations()) >= 1, "expected seeded operations"

    # Create a machine, a work order, and a routing
    mill = db.create_machine({"name": "Test Mill", "type": "CNC Milling"})
    turn = db.create_machine({"name": "Test Lathe", "type": "CNC Turning"})
    wo = db.create_work_order({"part_name": "Test Flange", "quantity": 10, "due_date": "2026-07-01"})

    op1 = db.create_operation({"work_order_id": wo["id"], "seq": 10, "name": "Mill faces",
                               "machine_id": mill["id"], "setup_min": 30, "cycle_min": 5})
    op2 = db.create_operation({"work_order_id": wo["id"], "seq": 20, "name": "Turn OD",
                               "machine_id": turn["id"], "setup_min": 20, "cycle_min": 4})

    # Duration = setup + cycle * qty
    assert server.operation_minutes(op1, wo["quantity"]) == 30 + 5 * 10, "op1 duration"
    assert server.operation_minutes(op2, wo["quantity"]) == 20 + 4 * 10, "op2 duration"

    # Auto-schedule respects routing order: op20 starts at/after op10 ends
    result = server.auto_schedule(wo["id"])
    assert "error" not in result, result
    sched = {o["seq"]: o for o in result["operations"]}
    assert sched[10]["start_time"] and sched[20]["start_time"], "both ops scheduled"
    assert sched[20]["start_time"] >= sched[10]["end_time"], "routing order must hold"

    # Auto-schedule on different machines => no self-conflict
    assert not [c for c in server.find_conflicts(db.list_operations())
                if c["op_a"] in (op1["id"], op2["id"]) and c["op_b"] in (op1["id"], op2["id"])], \
        "ops on different machines must not conflict"

    # Two overlapping ops on the SAME machine => conflict detected
    db.create_operation({"work_order_id": wo["id"], "seq": 15, "name": "Clash",
                         "machine_id": mill["id"],
                         "start_time": sched[10]["start_time"], "end_time": sched[10]["end_time"]})
    clash = [c for c in server.find_conflicts(db.list_operations()) if c["machine_id"] == mill["id"]]
    assert clash, "expected a same-machine overlap conflict"

    # Auto-schedule refuses if any op is unassigned
    wo2 = db.create_work_order({"part_name": "Unrouted", "quantity": 5})
    db.create_operation({"work_order_id": wo2["id"], "seq": 10, "name": "No machine"})
    r2 = server.auto_schedule(wo2["id"])
    assert "error" in r2, "should refuse to schedule with an unassigned op"

    # Cascade: deleting a work order removes its operations
    assert db.delete_work_order(wo["id"]) is True
    assert not [o for o in db.list_operations() if o["work_order_id"] == wo["id"]], \
        "deleting a work order should cascade-delete its operations"

    # Deleting a machine leaves operations but nulls the assignment (ON DELETE SET NULL)
    op_keep = db.create_operation({"work_order_id": wo2["id"], "seq": 20, "name": "Keep",
                                   "machine_id": turn["id"]})
    db.delete_machine(turn["id"])
    refetched = next(o for o in db.list_operations() if o["id"] == op_keep["id"])
    assert refetched["machine_id"] is None, "deleting a machine should null op.machine_id"

    # Validation
    assert server._validate_operation({"name": "", "work_order_id": wo2["id"]}), "missing name fails"
    assert server._validate_operation({"name": "x", "work_order_id": wo2["id"],
                                       "start_time": "2026-07-01T10:00",
                                       "end_time": "2026-07-01T09:00"}), "end before start fails"

    # Stats sanity
    stats = server.compute_stats(db.list_machines(), db.list_work_orders(), db.list_operations())
    assert stats["machine_count"] == len(db.list_machines())
    assert stats["work_order_count"] == len(db.list_work_orders())

    print("All smoke tests passed ✓")


if __name__ == "__main__":
    run()
