"""Self-contained HTTP server for the Manufacturing Process Planner.

Stdlib only (http.server + json + sqlite3). Serves a REST API under /api and
the static frontend. Models machines, work orders, and operations (routing
steps) so parts can be planned through a sequence of machining operations.

Run:
    python3 server.py            # http://localhost:8000
    PORT=9000 python3 server.py
"""

import json
import os
import re
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import db

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
PORT = int(os.environ.get("PORT", "8000"))


# ---- Domain logic ----

def _parse(ts):
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def operation_minutes(op, quantity):
    """Total minutes for an operation = setup + cycle * quantity."""
    return float(op.get("setup_min", 0) or 0) + float(op.get("cycle_min", 0) or 0) * max(quantity, 0)


def find_conflicts(operations):
    """Overlapping scheduled operations on the same machine."""
    conflicts = []
    by_machine = {}
    for op in operations:
        if op.get("machine_id") and op.get("start_time") and op.get("end_time"):
            by_machine.setdefault(op["machine_id"], []).append(op)
    for machine_id, group in by_machine.items():
        group = sorted(group, key=lambda o: o["start_time"])
        for i in range(len(group)):
            for k in range(i + 1, len(group)):
                a, b = group[i], group[k]
                a_s, a_e = _parse(a["start_time"]), _parse(a["end_time"])
                b_s, b_e = _parse(b["start_time"]), _parse(b["end_time"])
                if None in (a_s, a_e, b_s, b_e):
                    continue
                if a_s < b_e and b_s < a_e:
                    conflicts.append({
                        "machine_id": machine_id,
                        "op_a": a["id"], "op_b": b["id"],
                        "op_a_name": a["name"], "op_b_name": b["name"],
                    })
    return conflicts


def auto_schedule(wo_id):
    """Greedily schedule a work order's operations.

    Respects routing order (op N starts after op N-1 finishes) and machine
    availability (no overlap with already-scheduled operations on that machine).
    Returns the updated operations, or an error dict.
    """
    wo = next((w for w in db.list_work_orders() if w["id"] == wo_id), None)
    if wo is None:
        return {"error": "work order not found"}
    ops = db.list_operations_for(wo_id)
    if not ops:
        return {"error": "work order has no operations to schedule"}
    unassigned = [o for o in ops if not o.get("machine_id")]
    if unassigned:
        return {"error": f"assign a machine to every operation first "
                         f"(missing on {len(unassigned)})"}

    # Busy intervals per machine from OTHER work orders' scheduled operations.
    all_ops = db.list_operations()
    busy = {}
    for o in all_ops:
        if o["work_order_id"] == wo_id:
            continue
        if o.get("machine_id") and o.get("start_time") and o.get("end_time"):
            s, e = _parse(o["start_time"]), _parse(o["end_time"])
            if s and e:
                busy.setdefault(o["machine_id"], []).append((s, e))

    # Start from the work order's due date morning, else next 08:00.
    cursor = _shift_start()
    updated = []
    for op in sorted(ops, key=lambda o: o["seq"]):
        dur = timedelta(minutes=operation_minutes(op, wo["quantity"]))
        machine_id = op["machine_id"]
        start = _earliest_slot(cursor, dur, busy.get(machine_id, []))
        end = start + dur
        busy.setdefault(machine_id, []).append((start, end))
        cursor = end  # next op cannot start before this one ends
        db.update_operation(op["id"], {
            "start_time": start.strftime("%Y-%m-%dT%H:%M"),
            "end_time": end.strftime("%Y-%m-%dT%H:%M"),
            "status": "scheduled" if op["status"] == "pending" else op["status"],
        })
        updated.append(op["id"])
    return {"scheduled": updated, "operations": db.list_operations_for(wo_id)}


def _shift_start():
    """Next 08:00 from now (keeps the demo readable; real impl would use a calendar)."""
    now = datetime.now().replace(second=0, microsecond=0)
    start = now.replace(hour=8, minute=0)
    if now.hour >= 8:
        start = start + timedelta(days=1) if now.hour >= 17 else now
    return start


def _earliest_slot(not_before, duration, intervals):
    """First start >= not_before where [start, start+duration] hits no interval."""
    candidate = not_before
    ordered = sorted(intervals)
    moved = True
    while moved:
        moved = False
        for (s, e) in ordered:
            if candidate < e and s < candidate + duration:  # overlap
                candidate = e
                moved = True
    return candidate


def compute_stats(machines, work_orders, operations):
    machine_hours = {m["id"]: 0.0 for m in machines}
    for op in operations:
        s, e = _parse(op.get("start_time", "")), _parse(op.get("end_time", ""))
        if op.get("machine_id") and s and e and e > s:
            machine_hours[op["machine_id"]] = machine_hours.get(op["machine_id"], 0.0) + \
                (e - s).total_seconds() / 3600.0
    return {
        "machine_count": len(machines),
        "work_order_count": len(work_orders),
        "operation_count": len(operations),
        "total_scheduled_hours": round(sum(machine_hours.values()), 1),
        "per_machine_hours": {str(mid): round(h, 1) for mid, h in machine_hours.items()},
        "conflict_count": len(find_conflicts(operations)),
        "unscheduled_ops": sum(1 for o in operations if not o.get("start_time")),
    }


# ---- Routing ----

ROUTES = []


def route(method, pattern):
    regex = re.compile("^" + pattern + "$")
    def deco(fn):
        ROUTES.append((method, regex, fn))
        return fn
    return deco


@route("GET", r"/api/machines")
def _m_list(h, m): return 200, db.list_machines()


@route("GET", r"/api/machine-types")
def _m_types(h, m): return 200, db.MACHINE_TYPES


@route("POST", r"/api/machines")
def _m_create(h, m):
    body = h.read_json()
    if not body.get("name", "").strip():
        return 400, {"error": "name is required"}
    return 201, db.create_machine(body)


@route("PUT", r"/api/machines/(\d+)")
def _m_update(h, m):
    r = db.update_machine(int(m.group(1)), h.read_json())
    return (200, r) if r else (404, {"error": "machine not found"})


@route("DELETE", r"/api/machines/(\d+)")
def _m_delete(h, m):
    return (200, {"deleted": True}) if db.delete_machine(int(m.group(1))) \
        else (404, {"error": "machine not found"})


@route("GET", r"/api/work-orders")
def _wo_list(h, m):
    wos = db.list_work_orders()
    ops = db.list_operations()
    for wo in wos:
        wo["operations"] = [o for o in ops if o["work_order_id"] == wo["id"]]
    return 200, wos


@route("POST", r"/api/work-orders")
def _wo_create(h, m):
    body = h.read_json()
    if not body.get("part_name", "").strip():
        return 400, {"error": "part_name is required"}
    return 201, db.create_work_order(body)


@route("PUT", r"/api/work-orders/(\d+)")
def _wo_update(h, m):
    r = db.update_work_order(int(m.group(1)), h.read_json())
    return (200, r) if r else (404, {"error": "work order not found"})


@route("DELETE", r"/api/work-orders/(\d+)")
def _wo_delete(h, m):
    return (200, {"deleted": True}) if db.delete_work_order(int(m.group(1))) \
        else (404, {"error": "work order not found"})


@route("POST", r"/api/work-orders/(\d+)/auto-schedule")
def _wo_autoschedule(h, m):
    result = auto_schedule(int(m.group(1)))
    return (400, result) if "error" in result else (200, result)


@route("GET", r"/api/operations")
def _op_list(h, m): return 200, db.list_operations()


@route("POST", r"/api/operations")
def _op_create(h, m):
    body = h.read_json()
    err = _validate_operation(body)
    if err:
        return 400, {"error": err}
    return 201, db.create_operation(body)


@route("PUT", r"/api/operations/(\d+)")
def _op_update(h, m):
    body = h.read_json()
    if "start_time" in body and "end_time" in body and body["start_time"] and body["end_time"]:
        if _parse(body["end_time"]) and _parse(body["start_time"]) and \
                _parse(body["end_time"]) <= _parse(body["start_time"]):
            return 400, {"error": "end_time must be after start_time"}
    r = db.update_operation(int(m.group(1)), body)
    return (200, r) if r else (404, {"error": "operation not found"})


@route("DELETE", r"/api/operations/(\d+)")
def _op_delete(h, m):
    return (200, {"deleted": True}) if db.delete_operation(int(m.group(1))) \
        else (404, {"error": "operation not found"})


@route("GET", r"/api/conflicts")
def _conflicts(h, m): return 200, find_conflicts(db.list_operations())


@route("GET", r"/api/stats")
def _stats(h, m):
    return 200, compute_stats(db.list_machines(), db.list_work_orders(), db.list_operations())


def _validate_operation(body):
    if not body.get("name", "").strip():
        return "name is required"
    if not body.get("work_order_id"):
        return "work_order_id is required"
    s, e = body.get("start_time", ""), body.get("end_time", "")
    if s and e:
        ps, pe = _parse(s), _parse(e)
        if not ps or not pe:
            return "start_time/end_time must be valid ISO datetimes"
        if pe <= ps:
            return "end_time must be after start_time"
    return None


# ---- HTTP handler ----

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def read_json(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            return {}

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _dispatch(self, method):
        path = self.path.split("?")[0]
        if path.startswith("/api/"):
            for m_method, regex, fn in ROUTES:
                if m_method != method:
                    continue
                match = regex.match(path)
                if match:
                    try:
                        status, payload = fn(self, match)
                    except Exception as exc:
                        status, payload = 500, {"error": str(exc)}
                    self._send_json(status, payload)
                    return
            self._send_json(404, {"error": "not found"})
            return
        if method == "GET":
            self._serve_static(path)
        else:
            self._send_json(404, {"error": "not found"})

    def _serve_static(self, path):
        if path in ("/", ""):
            path = "/index.html"
        safe = os.path.normpath(path).lstrip("/")
        full = os.path.join(STATIC_DIR, safe)
        if not full.startswith(STATIC_DIR) or not os.path.isfile(full):
            self.send_error(404, "Not found")
            return
        ctype = {".html": "text/html", ".js": "application/javascript",
                 ".css": "text/css", ".json": "application/json"}.get(
            os.path.splitext(full)[1], "application/octet-stream")
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self): self._dispatch("GET")
    def do_POST(self): self._dispatch("POST")
    def do_PUT(self): self._dispatch("PUT")
    def do_DELETE(self): self._dispatch("DELETE")


def main():
    db.init_db()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Manufacturing Process Planner running at http://localhost:{PORT}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
