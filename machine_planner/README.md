# Machine Resources Planner

A lightweight internal tool for **factory / manufacturing machine scheduling** —
plan which machine runs which job and when, spot scheduling conflicts, and track
utilization. Built as a self-contained app with **zero external dependencies**
(Python standard library + SQLite + a vanilla-JS frontend).

## Run

```bash
cd machine_planner
python3 server.py
# → http://localhost:8000
```

Use a different port with `PORT=9000 python3 server.py`.
Data is stored in `machine_planner.db` (SQLite, created on first run with a few
sample machines/jobs to get you started).

## Features (MVP)

- **Schedule view** — a Gantt-style timeline (machines × hours of a day) with
  color-coded job bars by status. Click a bar to edit the job.
- **Conflict detection** — overlapping jobs on the same machine are flagged on
  the schedule and listed in a banner + the stats bar.
- **Machines** — add/edit/delete machines (type, location, status:
  operational / maintenance / down).
- **Jobs** — schedule jobs on a machine with start/end time, quantity, and
  status (scheduled / in progress / done).
- **Stats bar** — live counts of machines, jobs, total scheduled hours, and
  conflicts.

## API

| Method | Path | Description |
|--------|------|-------------|
| GET    | `/api/machines` | list machines |
| POST   | `/api/machines` | create machine |
| PUT    | `/api/machines/{id}` | update machine |
| DELETE | `/api/machines/{id}` | delete machine (+ its jobs) |
| GET    | `/api/jobs` | list jobs |
| POST   | `/api/jobs` | create job |
| PUT    | `/api/jobs/{id}` | update job |
| DELETE | `/api/jobs/{id}` | delete job |
| GET    | `/api/conflicts` | overlapping jobs per machine |
| GET    | `/api/stats` | summary counts + per-machine hours |

## Files

```
machine_planner/
├── server.py          # stdlib HTTP server + REST API + domain logic
├── db.py              # SQLite persistence + seed data
├── test_planner.py    # smoke tests (no deps)
├── static/
│   ├── index.html
│   ├── style.css
│   └── app.js
└── README.md
```

## Tests

```bash
cd machine_planner
python3 test_planner.py
```

## Roadmap ideas

- Drag-to-reschedule bars on the Gantt
- Multi-day / week view and machine maintenance windows
- Capacity/throughput-aware auto-scheduling and conflict resolution
- Authentication + multi-user if this graduates from an internal tool
