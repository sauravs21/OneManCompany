// Manufacturing Process Planner — frontend (vanilla JS, no build step).

const DAY_START = 6;   // gantt window 06:00
const DAY_END = 18;    // .. to 18:00
const HOURS = DAY_END - DAY_START;

const state = {
  machines: [],
  machineTypes: [],
  workOrders: [],   // each includes .operations
  operations: [],   // flat list across all work orders
  conflicts: [],
  stats: {},
  date: todayISO(),
  openWO: new Set(),
};

// ---- API ----
async function api(method, path, body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `${method} ${path} failed`);
  return data;
}

async function loadAll() {
  const [machines, machineTypes, workOrders, operations, conflicts, stats] = await Promise.all([
    api("GET", "/api/machines"),
    api("GET", "/api/machine-types"),
    api("GET", "/api/work-orders"),
    api("GET", "/api/operations"),
    api("GET", "/api/conflicts"),
    api("GET", "/api/stats"),
  ]);
  Object.assign(state, { machines, machineTypes, workOrders, operations, conflicts, stats });
  render();
}

// ---- Utils ----
function todayISO() { return new Date().toISOString().slice(0, 10); }
function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}
function machine(id) { return state.machines.find(x => x.id === id); }
function machineName(id) { const m = machine(id); return m ? m.name : "—"; }
function fmtTime(ts) {
  if (!ts) return "—";
  const d = new Date(ts);
  if (isNaN(d)) return ts;
  return d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
function opMinutes(op, qty) {
  return Number(op.setup_min || 0) + Number(op.cycle_min || 0) * Math.max(qty || 0, 0);
}
function fmtDuration(mins) {
  if (!mins) return "0m";
  const h = Math.floor(mins / 60), m = Math.round(mins % 60);
  return (h ? h + "h " : "") + (m ? m + "m" : (h ? "" : "0m"));
}
function conflictOpIds() {
  const ids = new Set();
  state.conflicts.forEach(c => { ids.add(c.op_a); ids.add(c.op_b); });
  return ids;
}

// ---- Render ----
function render() {
  renderStats();
  renderGantt();
  renderWorkOrders();
  renderMachines();
}

function renderStats() {
  const s = state.stats;
  document.getElementById("stats").innerHTML = `
    <div class="stat"><div class="num">${s.machine_count ?? 0}</div><div class="label">Machines</div></div>
    <div class="stat"><div class="num">${s.work_order_count ?? 0}</div><div class="label">Work orders</div></div>
    <div class="stat"><div class="num">${s.operation_count ?? 0}</div><div class="label">Operations</div></div>
    <div class="stat"><div class="num">${s.total_scheduled_hours ?? 0}h</div><div class="label">Scheduled</div></div>
    <div class="stat ${s.conflict_count ? "alert" : ""}"><div class="num">${s.conflict_count ?? 0}</div><div class="label">Conflicts</div></div>
  `;
}

function renderGantt() {
  const gantt = document.getElementById("gantt");
  const conflictIds = conflictOpIds();

  const banner = document.getElementById("conflict-banner");
  if (state.conflicts.length) {
    banner.classList.remove("hidden");
    banner.innerHTML = "⚠️ " + state.conflicts.map(c =>
      `<b>${esc(machineName(c.machine_id))}</b>: “${esc(c.op_a_name)}” overlaps “${esc(c.op_b_name)}”`
    ).join(" &nbsp;·&nbsp; ");
  } else { banner.classList.add("hidden"); }

  if (!state.machines.length) {
    gantt.innerHTML = `<div class="empty">No machines yet. Add one to start planning.</div>`;
    return;
  }

  let html = `<div class="gantt-row gantt-head">
    <div class="gantt-label"><span class="m-name">Machine</span><span class="m-meta">${state.date}</span></div>
    <div class="gantt-hours">`;
  for (let h = DAY_START; h < DAY_END; h++) html += `<span>${String(h).padStart(2, "0")}:00</span>`;
  html += `</div></div>`;

  for (const m of state.machines) {
    const dayOps = state.operations.filter(o =>
      o.machine_id === m.id && (o.start_time || "").slice(0, 10) === state.date);
    let bars = "";
    for (const op of dayOps) {
      const pos = barPosition(op);
      if (!pos) continue;
      const wo = state.workOrders.find(w => w.id === op.work_order_id);
      const conf = conflictIds.has(op.id) ? "is-conflict" : "";
      const label = wo ? `${esc(wo.part_name)} · Op${op.seq}` : esc(op.name);
      bars += `<div class="bar status-${esc(op.status)} ${conf}"
        style="left:${pos.left}%;width:${pos.width}%"
        data-op="${op.id}" title="${esc(op.name)} — ${fmtTime(op.start_time)} → ${fmtTime(op.end_time)}">
        <div class="b-name">${label}</div>
        <div class="b-meta">${esc(op.name)}</div>
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
  gantt.querySelectorAll(".bar").forEach(bar =>
    bar.addEventListener("click", () => openOpModal(Number(bar.dataset.op))));
}

function barPosition(op) {
  const start = new Date(op.start_time), end = new Date(op.end_time);
  if (isNaN(start) || isNaN(end)) return null;
  const sH = start.getHours() + start.getMinutes() / 60;
  const eH = end.getHours() + end.getMinutes() / 60;
  const cs = Math.max(sH, DAY_START), ce = Math.min(eH, DAY_END);
  if (ce <= cs) return null;
  return { left: ((cs - DAY_START) / HOURS) * 100, width: ((ce - cs) / HOURS) * 100 };
}

function renderWorkOrders() {
  const wrap = document.getElementById("wo-list");
  const conflictIds = conflictOpIds();
  if (!state.workOrders.length) {
    wrap.innerHTML = `<div class="empty">No work orders yet. Create one to plan a part's routing.</div>`;
    return;
  }
  wrap.innerHTML = state.workOrders.map(wo => {
    const ops = (wo.operations || []).slice().sort((a, b) => a.seq - b.seq);
    const totalMin = ops.reduce((sum, o) => sum + opMinutes(o, wo.quantity), 0);
    const open = state.openWO.has(wo.id);
    const lastEnd = ops.map(o => o.end_time).filter(Boolean).sort().pop();
    const late = wo.due_date && lastEnd && lastEnd.slice(0, 10) > wo.due_date;
    return `
    <div class="wo-card ${open ? "open" : ""}" data-wo="${wo.id}">
      <div class="wo-head" data-toggle="${wo.id}">
        <span class="wo-caret">▶</span>
        <div>
          <div class="wo-title">${esc(wo.part_name)} ${wo.part_number ? `<span class="wo-sub">(${esc(wo.part_number)})</span>` : ""}</div>
          <div class="wo-sub">${ops.length} op${ops.length === 1 ? "" : "s"} · qty ${wo.quantity} · est ${fmtDuration(totalMin)}</div>
        </div>
        <div class="wo-grow"></div>
        <span class="prio ${esc(wo.priority)}">${esc(wo.priority)}</span>
        <span class="pill ${esc(wo.status)}">${esc(wo.status.replace("_", " "))}</span>
        <span class="wo-due ${late ? "late" : ""}">${wo.due_date ? "due " + wo.due_date : "no due date"}${late ? " · LATE" : ""}</span>
      </div>
      <div class="wo-body">
        ${ops.length ? `
        <table class="routing">
          <thead><tr><th class="seq">Op</th><th>Operation</th><th>Machine</th><th>Setup</th><th>Cycle/pc</th><th>Duration</th><th>Scheduled</th><th>Status</th><th></th></tr></thead>
          <tbody>
            ${ops.map(o => `
              <tr>
                <td class="seq">${o.seq}</td>
                <td>${esc(o.name)} ${conflictIds.has(o.id) ? '<span class="pill down">conflict</span>' : ""}</td>
                <td>${o.machine_id ? esc(machineName(o.machine_id)) : '<span class="warn-text">unassigned</span>'}</td>
                <td>${o.setup_min || 0}m</td>
                <td>${o.cycle_min || 0}m</td>
                <td>${fmtDuration(opMinutes(o, wo.quantity))}</td>
                <td>${o.start_time ? fmtTime(o.start_time) : "—"}</td>
                <td><span class="pill ${esc(o.status)}">${esc(o.status.replace("_", " "))}</span></td>
                <td>
                  <button class="btn small" data-edit-op="${o.id}">Edit</button>
                  <button class="btn small danger" data-del-op="${o.id}">✕</button>
                </td>
              </tr>`).join("")}
          </tbody>
        </table>` : `<div class="empty">No operations yet — add the first routing step.</div>`}
        <div class="wo-body-actions">
          <button class="btn" data-add-op="${wo.id}">+ Add operation</button>
          <button class="btn primary" data-schedule="${wo.id}">⚡ Auto-schedule</button>
          <button class="btn" data-edit-wo="${wo.id}">Edit work order</button>
          <button class="btn danger" data-del-wo="${wo.id}">Delete</button>
        </div>
      </div>
    </div>`;
  }).join("");

  wrap.querySelectorAll("[data-toggle]").forEach(el => el.onclick = () => {
    const id = Number(el.dataset.toggle);
    state.openWO.has(id) ? state.openWO.delete(id) : state.openWO.add(id);
    renderWorkOrders();
  });
  wrap.querySelectorAll("[data-add-op]").forEach(b => b.onclick = () => openOpModal(null, Number(b.dataset.addOp)));
  wrap.querySelectorAll("[data-edit-op]").forEach(b => b.onclick = () => openOpModal(Number(b.dataset.editOp)));
  wrap.querySelectorAll("[data-del-op]").forEach(b => b.onclick = () => deleteOp(Number(b.dataset.delOp)));
  wrap.querySelectorAll("[data-edit-wo]").forEach(b => b.onclick = () => openWOModal(Number(b.dataset.editWo)));
  wrap.querySelectorAll("[data-del-wo]").forEach(b => b.onclick = () => deleteWO(Number(b.dataset.delWo)));
  wrap.querySelectorAll("[data-schedule]").forEach(b => b.onclick = () => autoSchedule(Number(b.dataset.schedule)));
}

function renderMachines() {
  const tbody = document.querySelector("#machines-table tbody");
  const hours = state.stats.per_machine_hours || {};
  tbody.innerHTML = state.machines.map(m => `
    <tr>
      <td>${esc(m.name)}</td>
      <td>${esc(m.type) || "—"}</td>
      <td>${esc(m.location) || "—"}</td>
      <td><span class="pill ${esc(m.status)}">${esc(m.status)}</span></td>
      <td>${hours[m.id] ?? 0}h</td>
      <td>${esc(m.notes) || ""}</td>
      <td>
        <button class="btn small" data-edit-machine="${m.id}">Edit</button>
        <button class="btn small danger" data-del-machine="${m.id}">Delete</button>
      </td>
    </tr>`).join("") || `<tr><td colspan="7" class="empty">No machines yet.</td></tr>`;
  tbody.querySelectorAll("[data-edit-machine]").forEach(b => b.onclick = () => openMachineModal(Number(b.dataset.editMachine)));
  tbody.querySelectorAll("[data-del-machine]").forEach(b => b.onclick = () => deleteMachine(Number(b.dataset.delMachine)));
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
function closeModal() { modal.classList.add("hidden"); modalSaveHandler = null; }
document.getElementById("modal-cancel").onclick = closeModal;
document.getElementById("modal-save").onclick = async () => {
  if (!modalSaveHandler) return;
  try { await modalSaveHandler(); closeModal(); await loadAll(); }
  catch (e) { alert(e.message); }
};

function field(label, name, value = "", type = "text") {
  return `<div class="modal-form-row"><label>${label}</label>
    <input name="${name}" type="${type}" value="${esc(value)}" /></div>`;
}
function selectField(label, name, value, options) {
  const opts = options.map(o => {
    const [val, lbl] = Array.isArray(o) ? o : [o, o.replace("_", " ")];
    return `<option value="${esc(val)}" ${String(val) === String(value) ? "selected" : ""}>${esc(lbl)}</option>`;
  }).join("");
  return `<div class="modal-form-row"><label>${label}</label><select name="${name}">${opts}</select></div>`;
}
function formValues() {
  const data = {};
  document.querySelectorAll("#modal-form [name]").forEach(el => data[el.name] = el.value);
  return data;
}

// ---- Machines ----
function openMachineModal(id) {
  const m = id ? machine(id) : {};
  const typeOpts = state.machineTypes.length ? state.machineTypes : ["CNC Milling", "CNC Turning", "Grinding"];
  openModal(id ? "Edit machine" : "Add machine",
    field("Name", "name", m.name) +
    selectField("Type", "type", m.type || typeOpts[0], typeOpts) +
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
  if (!confirm("Delete this machine? Operations assigned to it will be left unassigned.")) return;
  await api("DELETE", `/api/machines/${id}`); await loadAll();
}

// ---- Work orders ----
function openWOModal(id) {
  const wo = id ? state.workOrders.find(w => w.id === id) : { quantity: 1, due_date: state.date };
  openModal(id ? "Edit work order" : "New work order",
    field("Part name", "part_name", wo.part_name) +
    field("Part number", "part_number", wo.part_number) +
    field("Quantity", "quantity", wo.quantity || 1, "number") +
    field("Due date", "due_date", wo.due_date || "", "date") +
    selectField("Priority", "priority", wo.priority || "normal", ["rush", "high", "normal", "low"]) +
    selectField("Status", "status", wo.status || "planned", ["planned", "released", "in_progress", "done"]) +
    field("Notes", "notes", wo.notes),
    async () => {
      const data = formValues();
      data.quantity = Number(data.quantity);
      if (id) await api("PUT", `/api/work-orders/${id}`, data);
      else { const created = await api("POST", "/api/work-orders", data); state.openWO.add(created.id); }
    });
}
async function deleteWO(id) {
  if (!confirm("Delete this work order and all its operations?")) return;
  await api("DELETE", `/api/work-orders/${id}`); await loadAll();
}
async function autoSchedule(id) {
  try {
    const r = await api("POST", `/api/work-orders/${id}/auto-schedule`);
    state.openWO.add(id);
    await loadAll();
    const firstStart = (r.operations || []).map(o => o.start_time).filter(Boolean).sort()[0];
    if (firstStart) { state.date = firstStart.slice(0, 10); document.getElementById("schedule-date").value = state.date; renderGantt(); }
  } catch (e) { alert("Auto-schedule: " + e.message); }
}

// ---- Operations ----
function openOpModal(id, woId) {
  const op = id ? state.operations.find(o => o.id === id) : null;
  const wo = state.workOrders.find(w => w.id === (op ? op.work_order_id : woId));
  if (!wo) { alert("Create a work order first."); return; }
  if (!state.machines.length) { alert("Add a machine first."); return; }
  const nextSeq = op ? op.seq : ((wo.operations || []).reduce((mx, o) => Math.max(mx, o.seq), 0) + 10) || 10;
  const machineOpts = [["", "— unassigned —"]].concat(state.machines.map(m => [m.id, `${m.name} (${m.type})`]));
  openModal(id ? `Edit operation — ${esc(wo.part_name)}` : `Add operation — ${esc(wo.part_name)}`,
    field("Op #", "seq", op ? op.seq : nextSeq, "number") +
    field("Operation name", "name", op ? op.name : "") +
    selectField("Machine", "machine_id", op ? (op.machine_id || "") : "", machineOpts) +
    field("Setup (min)", "setup_min", op ? op.setup_min : 0, "number") +
    field("Cycle / piece (min)", "cycle_min", op ? op.cycle_min : 0, "number") +
    field("Start", "start_time", op ? (op.start_time || "").slice(0, 16) : "", "datetime-local") +
    field("End", "end_time", op ? (op.end_time || "").slice(0, 16) : "", "datetime-local") +
    selectField("Status", "status", op ? op.status : "pending", ["pending", "scheduled", "in_progress", "done"]) +
    `<p class="hint">Tip: leave start/end blank and use <b>Auto-schedule</b> to place operations automatically.</p>`,
    async () => {
      const data = formValues();
      data.seq = Number(data.seq);
      data.setup_min = Number(data.setup_min);
      data.cycle_min = Number(data.cycle_min);
      data.machine_id = data.machine_id ? Number(data.machine_id) : null;
      if (id) await api("PUT", `/api/operations/${id}`, data);
      else { data.work_order_id = wo.id; await api("POST", "/api/operations", data); }
      state.openWO.add(wo.id);
    });
}
async function deleteOp(id) {
  if (!confirm("Delete this operation?")) return;
  await api("DELETE", `/api/operations/${id}`); await loadAll();
}

// ---- Tabs & wiring ----
document.querySelectorAll(".tab").forEach(tab => tab.onclick = () => {
  document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
  document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
  tab.classList.add("active");
  document.getElementById("view-" + tab.dataset.view).classList.add("active");
});

document.getElementById("add-machine-btn").onclick = () => openMachineModal(null);
document.getElementById("add-wo-btn").onclick = () => openWOModal(null);

const dateInput = document.getElementById("schedule-date");
dateInput.value = state.date;
dateInput.onchange = () => { state.date = dateInput.value; renderGantt(); };

loadAll().catch(e => alert("Failed to load: " + e.message));
