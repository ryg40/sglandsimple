// Airtable/NocoDB-flavored grid against the sheet_* MCP tools.
// State is intentionally tiny; the server is the source of truth.

const PAGE_SIZE = 50;

const state = {
  collections: [],     // [{name, count}]
  active: null,        // collection name
  rows: [],
  columns: [],         // ordered field names; _id is always first
  total: 0,
  skip: 0,
};

const $ = (sel) => document.querySelector(sel);
const railNav = $("#collections");
const titleEl = $("#title");
const countEl = $("#count");
const pageEl = $("#page");
const prevBtn = $("#prev");
const nextBtn = $("#next");
const addBtn = $("#addRow");
const head = $("#grid-head");
const body = $("#grid-body");
const empty = $("#empty");
const nlForm = $("#nl-bar");
const nlInput = $("#nl-input");
const nlBtn = $("#nl-go");
const toasts = $("#toasts");

// --------------------------------------------------------------- toasts

function toast(text, kind = "info", ms = 3000) {
  const t = document.createElement("div");
  t.className = `toast ${kind}`;
  t.textContent = text;
  toasts.appendChild(t);
  setTimeout(() => {
    t.style.opacity = "0";
    t.style.transition = "opacity 300ms";
  }, ms);
  setTimeout(() => t.remove(), ms + 350);
}

// --------------------------------------------------------------- network

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) {
    const text = await r.text();
    throw new Error(`${r.status} ${url}: ${text}`);
  }
  return r.json();
}

async function sendJSON(method, url, body) {
  const r = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body == null ? undefined : JSON.stringify(body),
  });
  const text = await r.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { raw: text }; }
  if (!r.ok) {
    const msg = data && data.error ? JSON.stringify(data.error) : text || `${r.status}`;
    throw new Error(msg);
  }
  return data;
}

// --------------------------------------------------------------- load

async function loadCollections() {
  const data = await getJSON("/api/sheet/collections");
  state.collections = data.collections || [];
  renderRail();
  if (!state.active && state.collections.length) {
    await selectCollection(state.collections[0].name);
  }
}

async function selectCollection(name) {
  state.active = name;
  state.skip = 0;
  renderRail();
  await loadRows();
}

async function loadRows() {
  if (!state.active) return;
  try {
    const data = await getJSON(
      `/api/sheet/rows?collection=${encodeURIComponent(state.active)}` +
      `&skip=${state.skip}&limit=${PAGE_SIZE}`
    );
    state.rows = data.rows || [];
    state.total = data.total || 0;
    state.columns = deriveColumns(state.rows);
    renderGrid();
  } catch (e) {
    toast(`load: ${e.message}`, "error", 6000);
  }
}

function deriveColumns(rows) {
  const seen = new Set();
  const cols = [];
  for (const r of rows) {
    for (const k of Object.keys(r)) {
      if (!seen.has(k)) {
        seen.add(k);
        cols.push(k);
      }
    }
  }
  // Always start with _id; everything else in insertion order.
  cols.sort((a, b) => (a === "_id" ? -1 : b === "_id" ? 1 : 0));
  return cols;
}

// --------------------------------------------------------------- render

function renderRail() {
  railNav.innerHTML = "";
  for (const c of state.collections) {
    const btn = document.createElement("button");
    btn.className = "collection-btn" + (state.active === c.name ? " active" : "");
    btn.innerHTML = `<span>${c.name}</span><span class="badge">${c.count}</span>`;
    btn.addEventListener("click", () => selectCollection(c.name));
    railNav.appendChild(btn);
  }
}

function renderGrid() {
  titleEl.textContent = state.active || "—";
  countEl.textContent = state.total ? `${state.total} rows` : "no rows";

  const from = state.rows.length ? state.skip + 1 : 0;
  const to   = state.skip + state.rows.length;
  pageEl.textContent = `${from}–${to} of ${state.total}`;
  prevBtn.disabled = state.skip <= 0;
  nextBtn.disabled = to >= state.total;

  head.innerHTML = "";
  for (const c of state.columns) {
    const th = document.createElement("th");
    th.textContent = c;
    if (c === "_id") th.className = "col-id";
    head.appendChild(th);
  }
  const thAct = document.createElement("th");
  thAct.className = "col-actions";
  head.appendChild(thAct);

  body.innerHTML = "";
  if (!state.rows.length) {
    empty.hidden = false;
    return;
  }
  empty.hidden = true;

  for (const row of state.rows) {
    const tr = document.createElement("tr");
    tr.dataset.id = row._id;
    for (const c of state.columns) {
      const td = document.createElement("td");
      if (c === "_id") {
        td.className = "col-id";
        td.textContent = row[c] ?? "";
      } else {
        td.className = "editable";
        td.dataset.field = c;
        td.textContent = formatValue(row[c]);
        td.addEventListener("click", () => editCell(td, row));
      }
      tr.appendChild(td);
    }
    const tdAct = document.createElement("td");
    tdAct.className = "col-actions";
    const del = document.createElement("button");
    del.className = "danger";
    del.textContent = "✕";
    del.title = "Delete row";
    del.addEventListener("click", () => deleteRow(row));
    tdAct.appendChild(del);
    tr.appendChild(tdAct);
    body.appendChild(tr);
  }
}

function formatValue(v) {
  if (v === null || v === undefined) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  try { return JSON.stringify(v); } catch { return String(v); }
}

// --------------------------------------------------------------- editing

function editCell(td, row) {
  if (td.classList.contains("editing")) return;
  const field = td.dataset.field;
  const current = row[field];
  const wasJson = current && typeof current === "object";
  const initial = wasJson ? JSON.stringify(current) : (current ?? "");
  td.classList.add("editing");
  td.textContent = "";

  const input = document.createElement(wasJson ? "textarea" : "input");
  if (!wasJson) input.type = inferInputType(current);
  input.value = initial;
  td.appendChild(input);
  input.focus();
  if (input.select) input.select();

  let done = false;
  const commit = async () => {
    if (done) return;
    done = true;
    const raw = input.value;
    td.classList.remove("editing");
    let parsed = raw;
    if (wasJson || raw.trim().startsWith("{") || raw.trim().startsWith("[")) {
      try { parsed = JSON.parse(raw); } catch { /* keep as string */ }
    } else if (input.type === "number" && raw !== "") {
      const n = Number(raw);
      if (!Number.isNaN(n)) parsed = n;
    }
    if (parsed === current || (raw === initial)) {
      td.textContent = formatValue(current);
      return;
    }
    td.textContent = formatValue(parsed);
    td.classList.add("saving");
    try {
      await sendJSON("POST", "/api/sheet/cell", {
        collection: state.active,
        _id: row._id,
        field,
        value: parsed,
      });
      row[field] = parsed;
      td.classList.remove("saving");
      td.classList.add("saved");
      setTimeout(() => td.classList.remove("saved"), 800);
    } catch (e) {
      td.classList.remove("saving");
      td.classList.add("errored");
      td.textContent = formatValue(current);
      setTimeout(() => td.classList.remove("errored"), 1500);
      toast(`save failed: ${e.message}`, "error", 6000);
    }
  };
  const cancel = () => {
    if (done) return;
    done = true;
    td.classList.remove("editing");
    td.textContent = formatValue(current);
  };

  input.addEventListener("blur", commit);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      input.blur();
    } else if (e.key === "Escape") {
      e.preventDefault();
      cancel();
    }
  });
}

function inferInputType(value) {
  if (typeof value === "number") return "number";
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}/.test(value)) return "text"; // dates are strings here
  return "text";
}

// --------------------------------------------------------------- add/delete

async function deleteRow(row) {
  if (!confirm(`Delete ${state.active} ${row._id}? Audit log will record this.`)) return;
  try {
    await sendJSON("DELETE", `/api/sheet/row?collection=${encodeURIComponent(state.active)}&_id=${encodeURIComponent(row._id)}`);
    toast(`Deleted ${row._id}`, "ok");
    await loadRows();
  } catch (e) {
    toast(`delete failed: ${e.message}`, "error", 6000);
  }
}

addBtn.addEventListener("click", async () => {
  if (!state.active) return;
  const seed = prompt(`New ${state.active} row — _id (or blank for auto):`);
  if (seed === null) return;
  const doc = {};
  if (seed.trim()) doc._id = seed.trim();
  try {
    await sendJSON("POST", "/api/sheet/row", { collection: state.active, doc });
    toast("Row inserted", "ok");
    await loadRows();
  } catch (e) {
    toast(`insert failed: ${e.message}`, "error", 6000);
  }
});

// --------------------------------------------------------------- paging

prevBtn.addEventListener("click", () => {
  state.skip = Math.max(0, state.skip - PAGE_SIZE);
  loadRows();
});
nextBtn.addEventListener("click", () => {
  state.skip = state.skip + PAGE_SIZE;
  loadRows();
});

// --------------------------------------------------------------- NL bar

nlForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const instruction = nlInput.value.trim();
  if (!instruction || !state.active) return;
  nlBtn.disabled = true;
  const pending = toast(`Planning edits on ${state.active}…`, "info", 12000);
  try {
    const data = await sendJSON("POST", "/api/sheet/nl", {
      collection: state.active,
      instruction,
    });
    if (data.isError || data.error) {
      toast(`NL: ${data.error || data.summary || "failed"}`, "error", 8000);
    } else {
      const applied = (data.applied || []).length;
      const failed = (data.failed || []).length;
      const kind = failed ? "error" : "ok";
      toast(`Applied ${applied} op(s)${failed ? `, ${failed} failed` : ""}.`, kind, 6000);
    }
    nlInput.value = "";
    await loadRows();
  } catch (err) {
    toast(`NL failed: ${err.message}`, "error", 8000);
  } finally {
    nlBtn.disabled = false;
  }
});

// --------------------------------------------------------------- boot

loadCollections().catch((e) => toast(`init: ${e.message}`, "error", 8000));
