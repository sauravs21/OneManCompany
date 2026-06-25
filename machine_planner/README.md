# Manufacturing Process Planner

A lightweight internal tool for **planning manufacturing processes** — model your
shop's machines (CNC milling, turning, grinding, drilling, inspection…), define
each part's **routing** (the ordered sequence of operations it flows through),
and schedule those operations across machines on a Gantt timeline.

Built as a self-contained app with **zero external dependencies** (Python
standard library + SQLite + a vanilla-JS frontend).

## Run

```bash
cd machine_planner
python3 server.py
# → http://localhost:8000
```

Use a different port with `PORT=9000 python3 server.py`.
Data lives in `machine_planner.db` (SQLite, created on first run with sample
machines and a 3-operation work order to get you started).

## Concepts

- **Machine** — a piece of equipment (type, location, status:
  operational / maintenance / down).
- **Work order** — a part to produce: name, part number, **quantity**, due date,
  priority, status.
- **Operation (routing step)** — one step in a work order's process, in sequence
  (Op 10, 20, 30…). Each has an assigned machine, **setup time**, and **cycle
  time per piece**. Duration is computed automatically as
  `setup + cycle × quantity`.

## Features (MVP)

- **Schedule view** — Gantt timeline (machines × hours of a day). Each bar is an
  operation placed on its assigned machine, color-coded by status and labelled
  with `part · Op#`. Click a bar to edit the operation.
- **Work orders + routing** — expandable cards listing each part's operations
  with live duration roll-up and a LATE flag when the schedule runs past the due
  date.
- **Auto-schedule** — one click sequences a work order's operations respecting
  **routing order** (Op N starts after Op N-1 finishes) **and machine
  availability** (no overlap with operations already booked on that machine).
- **Conflict detection** — overlapping operations on the same machine are flagged
  on the schedule, in a banner, and in the stats bar.
- **Stats bar** — machines, work orders, operations, total scheduled hours, and
  conflicts at a glance; per-machine load shown on the Machines tab.

## API

| Method | Path | Description |
|--------|------|-------------|
| GET    | `/api/machines` | list machines |
| GET    | `/api/machine-types` | suggested machine type list |
| POST   | `/api/machines` | create machine |
| PUT/DELETE | `/api/machines/{id}` | update / delete machine |
| GET    | `/api/work-orders` | list work orders (each with its operations) |
| POST   | `/api/work-orders` | create work order |
| PUT/DELETE | `/api/work-orders/{id}` | update / delete work order (cascades operations) |
| POST   | `/api/work-orders/{id}/auto-schedule` | sequence its operations |
| GET    | `/api/operations` | list all operations |
| POST   | `/api/operations` | create operation |
| PUT/DELETE | `/api/operations/{id}` | update / delete operation |
| GET    | `/api/conflicts` | overlapping operations per machine |
| GET    | `/api/stats` | summary counts + per-machine hours |

## Files

```
machine_planner/
├── server.py          # stdlib HTTP server, REST API, scheduler, conflict logic
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

- Working calendar / shifts (the auto-scheduler currently packs time linearly
  rather than around shop hours)
- Drag-to-reschedule bars on the Gantt; multi-day / week view
- Machine capability matching (only allow ops on machines of the right type)
- Capacity & WIP limits, maintenance windows, and finite-capacity loading
- Shop-floor status updates (start/complete an op) and progress tracking
