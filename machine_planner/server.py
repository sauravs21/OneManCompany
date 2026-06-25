"""Self-contained HTTP server for the Machine Resources Planner.

Stdlib only (http.server + json + sqlite3) so it runs with `python3 server.py`
and no dependencies. Serves a REST API under /api and the static frontend.

Run:
    python3 server.py            # http://localhost:8000
    PORT=9000 python3 server.py
"""

import json
import os
import re
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import db

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
PORT = int(os.environ.get("PORT", "8000"))


# ---- Domain logic ----

def _parse(ts):
    """Parse an ISO-ish datetime string; tolerate missing seconds."""
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def find_conflicts(jobs):
    """Return list of overlapping job pairs scheduled on the same machine."""
    conflicts = []
    by_machine = {}
    for job in jobs:
        by_machine.setdefault(job["machine_id"], []).append(job)
    for machine_id, group in by_machine.items():
        group = sorted(group, key=lambda j: j["start_time"])
        for i in range(len(group)):
            for k in range(i + 1, len(group)):
                a, b = group[i], group[k]
                a_start, a_end = _parse(a["start_time"]), _parse(a["end_time"])
                b_start, b_end = _parse(b["start_time"]), _parse(b["end_time"])
                if None in (a_start, a_end, b_start, b_end):
                    continue
                if a_start < b_end and b_start < a_end:
                    conflicts.append({
                        "machine_id": machine_id,
                        "job_a": a["id"],
                        "job_b": b["id"],
                        "job_a_name": a["name"],
                        "job_b_name": b["name"],
                    })
    return conflicts


def compute_stats(machines, jobs):
    """Per-machine scheduled hours and utilization for the busiest day window."""
    machine_hours = {m["id"]: 0.0 for m in machines}
    for job in jobs:
        start, end = _parse(job["start_time"]), _parse(job["end_time"])
        if start and end and end > start:
            machine_hours[job["machine_id"]] = machine_hours.get(job["machine_id"], 0.0) + \
                (end - start).total_seconds() / 3600.0
    total_jobs = len(jobs)
    total_hours = round(sum(machine_hours.values()), 1)
    return {
        "machine_count": len(machines),
        "job_count": total_jobs,
        "total_scheduled_hours": total_hours,
        "per_machine_hours": {str(mid): round(h, 1) for mid, h in machine_hours.items()},
        "conflict_count": len(find_conflicts(jobs)),
    }


# ---- HTTP handler ----

ROUTES = []


def route(method, pattern):
    regex = re.compile("^" + pattern + "$")
    def deco(fn):
        ROUTES.append((method, regex, fn))
        return fn
    return deco


@route("GET", r"/api/machines")
def _get_machines(h, m):
    return 200, db.list_machines()


@route("POST", r"/api/machines")
def _post_machine(h, m):
    body = h.read_json()
    if not body.get("name", "").strip():
        return 400, {"error": "name is required"}
    return 201, db.create_machine(body)


@route("PUT", r"/api/machines/(\d+)")
def _put_machine(h, m):
    res = db.update_machine(int(m.group(1)), h.read_json())
    return (200, res) if res else (404, {"error": "machine not found"})


@route("DELETE", r"/api/machines/(\d+)")
def _delete_machine(h, m):
    ok = db.delete_machine(int(m.group(1)))
    return (200, {"deleted": True}) if ok else (404, {"error": "machine not found"})


@route("GET", r"/api/jobs")
def _get_jobs(h, m):
    return 200, db.list_jobs()


@route("POST", r"/api/jobs")
def _post_job(h, m):
    body = h.read_json()
    err = _validate_job(body)
    if err:
        return 400, {"error": err}
    return 201, db.create_job(body)


@route("PUT", r"/api/jobs/(\d+)")
def _put_job(h, m):
    res = db.update_job(int(m.group(1)), h.read_json())
    return (200, res) if res else (404, {"error": "job not found"})


@route("DELETE", r"/api/jobs/(\d+)")
def _delete_job(h, m):
    ok = db.delete_job(int(m.group(1)))
    return (200, {"deleted": True}) if ok else (404, {"error": "job not found"})


@route("GET", r"/api/conflicts")
def _get_conflicts(h, m):
    return 200, find_conflicts(db.list_jobs())


@route("GET", r"/api/stats")
def _get_stats(h, m):
    return 200, compute_stats(db.list_machines(), db.list_jobs())


def _validate_job(body):
    if not body.get("name", "").strip():
        return "name is required"
    if not body.get("machine_id"):
        return "machine_id is required"
    start, end = _parse(body.get("start_time", "")), _parse(body.get("end_time", ""))
    if not start or not end:
        return "valid start_time and end_time are required (ISO format)"
    if end <= start:
        return "end_time must be after start_time"
    return None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quieter logging
        pass

    def read_json(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
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
                    except Exception as exc:  # surface errors as JSON
                        status, payload = 500, {"error": str(exc)}
                    self._send_json(status, payload)
                    return
            self._send_json(404, {"error": "not found"})
            return
        if method == "GET":
            self._serve_static(path)
            return
        self._send_json(404, {"error": "not found"})

    def _serve_static(self, path):
        if path in ("/", ""):
            path = "/index.html"
        # prevent path traversal
        safe = os.path.normpath(path).lstrip("/")
        full = os.path.join(STATIC_DIR, safe)
        if not full.startswith(STATIC_DIR) or not os.path.isfile(full):
            self.send_error(404, "Not found")
            return
        ctype = {
            ".html": "text/html", ".js": "application/javascript",
            ".css": "text/css", ".json": "application/json",
        }.get(os.path.splitext(full)[1], "application/octet-stream")
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")


def main():
    db.init_db()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Machine Resources Planner running at http://localhost:{PORT}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
