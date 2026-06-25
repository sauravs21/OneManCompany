// Machine Resources Planner — frontend (vanilla JS, no build step).

const DAY_START = 6;   // gantt window 06:00
const DAY_END = 18;    // .. to 18:00
const HOURS = DAY_END - DAY_START;

const state = {
  machines: [],
  jobs: [],
  conflicts: [],
  stats: {},
  date: todayISO(),
};

// ---- API helpers ----
async function api(method, path, body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `${method} ${path} failed`);
  return data;
}

async function loadAll() {
  const [machines, jobs, conflicts, stats] = await Promise.all([
    api("GET", "/api/machines"),
    api("GET", "/api/jobs"),
    api("GET", "/api/conflicts"),
    api("GET", "/api/stats"),
  ]);
  state.machines = machines;
  state.jobs = jobs;
  state.conflicts = conflicts;
  state.stats = stats;
  render();
}

// ---- Utilities ----
function todayISO() {
  return new Date().toISOString().slice(0, 10);
}
function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}
function machineName(id) {
  const m = state.machines.find(x => x.id === id);
  return m ? m.name : "?";
}
function fmtTime(ts) {
  const d = new Date(ts);
  if (isNaN(d)) return ts;
  return d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
function conflictJobIds() {
  const ids = new Set();
  state.conflicts.forEach(c => { ids.add(c.job_a); ids.add(c.job_b); });
  return ids;
}

// ---- Rendering ----
function render() {
  renderStats();
  renderGantt();
  renderMachines();
  renderJobs();
}

function renderStats() {
  const s = state.stats;
  document.getElementById("stats").innerHTML = `
    <div class="stat"><div class="num">${s.machine_count ?? 0}</div><div class="label">Machines</div></div>
    <div class="stat"><div class="num">${s.job_count ?? 0}</div><div class="label">Jobs</div></div>
    <div class="stat"><div class="num">${s.total_scheduled_hours ?? 0}h</div><div class="label">Scheduled</div></div>
    <div class="stat ${s.conflict_count ? "alert" : ""}"><div class="num">${s.conflict_count ?? 0}</div><div class="label">Conflicts</div></div>
  `;
}

function renderGantt() {
  const gantt = document.getElementById("gantt");
  const conflictIds = conflictJobIds();

  // Conflict banner
  const banner = document.getElementById("conflict-banner");
  if (state.conflicts.length) {
    banner.classList.remove("hidden");
    banner.innerHTML = "⚠️ " + state.conflicts.map(c =>
      `<b>${esc(machineName(c.machine_id))}</b>: “${esc(c.job_a_name)}” overlaps “${esc(c.job_b_name)}”`
    ).join(" &nbsp;·&nbsp; ");
  } else {
    banner.classList.add("hidden");
  }

  if (!state.machines.length) {
    gantt.innerHTML = `<div class="empty">No machines yet. Add one to start planning.</div>`;
    return;
  }

  // Header row with hour ticks
  let html = `<div class="gantt-row gantt-head">
    <div class="gantt-label"><span class="m-name">Machine</span><span class="m-meta">${state.date}</span></div>
    <div class="gantt-hours">`;
  for (let h = DAY_START; h < DAY_END; h++) {
    html += `<span>${String(h).padStart(2, "0")}:00</span>`;
  }
  html += `</div></div>`;

  // One row per machine
  for (const m of state.machines) {
    const dayJobs = state.jobs.filter(j =>
      j.machine_id === m.id && j.start_time.slice(0, 10) === state.date);
    let bars = "";
    for (const j of dayJobs) {
      const pos = barPosition(j);
      if (!pos) continue;
      const conf = conflictIds.has(j.id) ? "is-conflict" : "";
      bars += `<div class="bar status-${esc(j.status)} ${conf}"
        style="left:${pos.left}%;width:${pos.width}%"
        data-job="${j.id}" title="${esc(j.name)} — ${fmtTime(j.start_time)} → ${fmtTime(j.end_time)}">
        <div class="b-name">${esc(j.name)}</div>
        <div class="b-meta">${j.quantity ? "qty " + j.quantity : ""}</div>
      </div>`;
    }
    html += `<div class="gantt-row">
      <div class="gantt-label">
        <span class="m-name"><span class="m-dot ${esc(m.status)}"></span>${esc(m.name)}</span>
        <span class="m-meta">${esc(m.type || "—")}${m.location ? " · " + esc(m.location) : ""}</span>
      </div>
      <div class="gantt-track">${bars}</div>
    </div>`;
  }
  gantt.innerHTML = html;

  gantt.querySelectorAll(".bar").forEach(bar => {
    bar.addEventListener("click", () => openJobModal(Number(bar.dataset.job)));
  });
}

function barPosition(job) {
  const start = new Date(job.start_time);
  const end = new Date(job.end_time);
  if (isNaN(start) || isNaN(end)) return null;
  const startH = start.getHours() + start.getMinutes() / 60;
  const endH = end.getHours() + end.getMinutes() / 60;
  const clampedStart = Math.max(startH, DAY_START);
  const clampedEnd = Math.min(endH, DAY_END);
  if (clampedEnd <= clampedStart) return null;
  return {
    left: ((clampedStart - DAY_START) / HOURS) * 100,
    width: ((clampedEnd - clampedStart) / HOURS) * 100,
  };
}

function renderMachines() {
  const tbody = document.querySelector("#machines-table tbody");
  tbody.innerHTML = state.machines.map(m => `
    <tr>
      <td>${esc(m.name)}</td>
      <td>${esc(m.type) || "—"}</td>
      <td>${esc(m.location) || "—"}</td>
      <td><span class="pill ${esc(m.status)}">${esc(m.status)}</span></td>
      <td>${esc(m.notes) || ""}</td>
      <td>
        <button class="btn small" data-edit-machine="${m.id}">Edit</button>
        <button class="btn small danger" data-del-machine="${m.id}">Delete</button>
      </td>
    </tr>`).join("") || `<tr><td colspan="6" class="empty">No machines yet.</td></tr>`;

  tbody.querySelectorAll("[data-edit-machine]").forEach(b =>
    b.onclick = () => openMachineModal(Number(b.dataset.editMachine)));
  tbody.querySelectorAll("[data-del-machine]").forEach(b =>
    b.onclick = () => deleteMachine(Number(b.dataset.delMachine)));
}

function renderJobs() {
  const tbody = document.querySelector("#jobs-table tbody");
  const conflictIds = conflictJobIds();
  tbody.innerHTML = state.jobs.map(j => `
    <tr>
      <td>${esc(j.name)} ${conflictIds.has(j.id) ? '<span class="pill down">conflict</span>' : ""}</td>
      <td>${esc(machineName(j.machine_id))}</td>
      <td>${fmtTime(j.start_time)}</td>
      <td>${fmtTime(j.end_time)}</td>
      <td>${j.quantity || ""}</td>
      <td><span class="pill ${esc(j.status)}">${esc(j.status.replace("_", " "))}</span></td>
      <td>
        <button class="btn small" data-edit-job="${j.id}">Edit</button>
        <button class="btn small danger" data-del-job="${j.id}">Delete</button>
      </td>
    </tr>`).join("") || `<tr><td colspan="7" class="empty">No jobs scheduled yet.</td></tr>`;

  tbody.querySelectorAll("[data-edit-job]").forEach(b =>
    b.onclick = () => openJobModal(Number(b.dataset.editJob)));
  tbody.querySelectorAll("[data-del-job]").forEach(b =>
    b.onclick = () => deleteJob(Number(b.dataset.delJob)));
}

// ---- Modal ----
const modal = document.getElementById("modal");
let modalSaveHandler = null;

function openModal(title, fieldsHtml, onSave) {
  document.getElementById("modal-title").textContent = title;
  document.getElementById("modal-form").innerHTML = fieldsHtml;
  modal.classList.remove("hidden");
  modalSaveHandler = onSave;
}
function closeModal() {
  modal.classList.add("hidden");
  modalSaveHandler = null;
}
document.getElementById("modal-cancel").onclick = closeModal;
document.getElementById("modal-save").onclick = async () => {
  if (modalSaveHandler) {
    try { await modalSaveHandler(); closeModal(); await loadAll(); }
    catch (e) { alert(e.message); }
  }
};

function field(label, name, value = "", type = "text") {
  return `<div class="modal-form-row"><label>${label}</label>
    <input name="${name}" type="${type}" value="${esc(value)}" /></div>`;
}
function selectField(label, name, value, options) {
  const opts = options.map(o =>
    `<option value="${o}" ${o === value ? "selected" : ""}>${o.replace("_", " ")}</option>`).join("");
  return `<div class="modal-form-row"><label>${label}</label>
    <select name="${name}">${opts}</select></div>`;
}
function formValues() {
  const data = {};
  document.querySelectorAll("#modal-form [name]").forEach(el => data[el.name] = el.value);
  return data;
}

function openMachineModal(id) {
  const m = id ? state.machines.find(x => x.id === id) : {};
  openModal(id ? "Edit machine" : "Add machine",
    field("Name", "name", m.name) +
    field("Type", "type", m.type) +
    field("Location", "location", m.location) +
    selectField("Status", "status", m.status || "operational", ["operational", "maintenance", "down"]) +
    field("Notes", "notes", m.notes),
    async () => {
      const data = formValues();
      if (id) await api("PUT", `/api/machines/${id}`, data);
      else await api("POST", "/api/machines", data);
    });
}

async function deleteMachine(id) {
  if (!confirm("Delete this machine and all its jobs?")) return;
  await api("DELETE", `/api/machines/${id}`);
  await loadAll();
}

function openJobModal(id) {
  const j = id ? state.jobs.find(x => x.id === id) : { start_time: state.date + "T08:00", end_time: state.date + "T12:00" };
  if (!state.machines.length) { alert("Add a machine first."); return; }
  const machineOpts = state.machines.map(m =>
    `<option value="${m.id}" ${m.id === j.machine_id ? "selected" : ""}>${esc(m.name)}</option>`).join("");
  openModal(id ? "Edit job" : "Schedule job",
    field("Job name", "name", j.name) +
    `<div class="modal-form-row"><label>Machine</label><select name="machine_id">${machineOpts}</select></div>` +
    field("Start", "start_time", (j.start_time || "").slice(0, 16), "datetime-local") +
    field("End", "end_time", (j.end_time || "").slice(0, 16), "datetime-local") +
    field("Quantity", "quantity", j.quantity || 0, "number") +
    selectField("Status", "status", j.status || "scheduled", ["scheduled", "in_progress", "done"]) +
    field("Notes", "notes", j.notes),
    async () => {
      const data = formValues();
      data.machine_id = Number(data.machine_id);
      data.quantity = Number(data.quantity);
      if (id) await api("PUT", `/api/jobs/${id}`, data);
      else await api("POST", "/api/jobs", data);
    });
}

async function deleteJob(id) {
  if (!confirm("Delete this job?")) return;
  await api("DELETE", `/api/jobs/${id}`);
  await loadAll();
}

// ---- Tabs & wiring ----
document.querySelectorAll(".tab").forEach(tab => {
  tab.onclick = () => {
    document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
    document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
    tab.classList.add("active");
    document.getElementById("view-" + tab.dataset.view).classList.add("active");
  };
});

document.getElementById("add-machine-btn").onclick = () => openMachineModal(null);
document.getElementById("add-job-btn").onclick = () => openJobModal(null);
document.getElementById("add-job-btn-2").onclick = () => openJobModal(null);

const dateInput = document.getElementById("schedule-date");
dateInput.value = state.date;
dateInput.onchange = () => { state.date = dateInput.value; renderGantt(); };

loadAll().catch(e => alert("Failed to load: " + e.message));
