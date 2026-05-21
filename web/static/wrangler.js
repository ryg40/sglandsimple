// Reactive aggregation builder. Each stage card is independently runnable
// (Data-Wrangler style): "Run up to here" sends the pipeline prefix to
// wrangler_run_prefix and renders the preview + a row-count delta.

const PREVIEW_NOTE = "25-row previews";

const state = {
  collections: [],
  active: null,
  sample: null,        // {rows, field_summary, sort_field}
  stages: [],          // [{kind, clauses, live, _runToken}]
};

let stageSeq = 0;

const $ = (s) => document.querySelector(s);
const railNav = $("#collections");
const titleEl = $("#title");
const sampleNote = $("#sample-note");
const chipsEl = $("#chips");
const stagesEl = $("#stages");
const footerNote = $("#footer-note");
const toasts = $("#toasts");

// ---------------------------------------------------------------- helpers

function toast(text, kind = "info", ms = 3500) {
  const t = document.createElement("div");
  t.className = `toast ${kind}`;
  t.textContent = text;
  toasts.appendChild(t);
  setTimeout(() => { t.style.opacity = "0"; t.style.transition = "opacity 300ms"; }, ms);
  setTimeout(() => t.remove(), ms + 350);
}

async function getJSON(url) {
  const r = await fetch(url);
  const text = await r.text();
  let data; try { data = text ? JSON.parse(text) : null; } catch { data = { raw: text }; }
  if (!r.ok) throw new Error(data && data.error ? JSON.stringify(data.error) : text || `${r.status}`);
  return data;
}
async function postJSON(url, body) {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const text = await r.text();
  let data; try { data = text ? JSON.parse(text) : null; } catch { data = { raw: text }; }
  if (!r.ok) throw new Error(data && data.error ? JSON.stringify(data.error) : text || `${r.status}`);
  return data;
}

function fmt(v) {
  if (v === null || v === undefined) return "";
  if (typeof v === "object") { try { return JSON.stringify(v); } catch { return String(v); } }
  return String(v);
}

// ---------------------------------------------------------------- load

async function loadCollections() {
  const data = await getJSON("/api/sheet/collections");
  state.collections = data.collections || [];
  renderRail();
  if (!state.active && state.collections.length) selectCollection(state.collections[0].name);
}

async function selectCollection(name) {
  state.active = name;
  state.stages = [];
  renderRail();
  stagesEl.innerHTML = "";
  await loadSample();
}

async function loadSample() {
  if (!state.active) return;
  try {
    state.sample = await getJSON(`/api/wrangler/sample?collection=${encodeURIComponent(state.active)}`);
    titleEl.textContent = state.active;
    sampleNote.textContent = `sampled ${state.sample.row_count} by ${state.sample.sort_field} desc · ${PREVIEW_NOTE}`;
    renderChips();
  } catch (e) {
    toast(`sample: ${e.message}`, "error", 6000);
  }
}

// ---------------------------------------------------------------- render rail + chips

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

function fieldNames() {
  return (state.sample?.field_summary || []).map((f) => f.field);
}

function renderChips() {
  chipsEl.innerHTML = "";
  for (const f of state.sample?.field_summary || []) {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.innerHTML = `<strong>${f.field}</strong>` +
      `<span class="ctype">${(f.types || []).join("|")}</span>` +
      (f.cardinality != null ? `<span class="ccard">${f.cardinality}</span>` : "");
    chip.title = "click=filter · alt-click=project · right-click=group by";
    chip.addEventListener("click", (e) => {
      if (e.altKey) addStage("project", f.field);
      else addStage("match", f.field);
    });
    chip.addEventListener("contextmenu", (e) => { e.preventDefault(); addStage("group", f.field); });
    chipsEl.appendChild(chip);
  }
}

// ---------------------------------------------------------------- stages model

const STAGE_META = {
  match:   { icon: "⮕", title: "Filter ($match)" },
  group:   { icon: "Σ", title: "Group ($group)" },
  project: { icon: "▦", title: "Project ($project)" },
  sort:    { icon: "↧", title: "Sort ($sort)" },
  limit:   { icon: "⊓", title: "Limit ($limit)" },
};

function newStage(kind, seedField) {
  const st = { id: ++stageSeq, kind, live: true, clauses: [] };
  if (kind === "match") st.clauses.push({ field: seedField || "", op: "=", value: "" });
  else if (kind === "group") { st.groupKeys = seedField ? [seedField] : []; st.accs = [{ name: "count", fn: "count", field: "" }]; }
  else if (kind === "project") st.clauses.push({ field: seedField || "", include: true });
  else if (kind === "sort") st.clauses.push({ field: seedField || "", dir: -1 });
  else if (kind === "limit") st.limit = 10;
  return st;
}

function addStage(kind, seedField) {
  state.stages.push(newStage(kind, seedField));
  renderStages();
  const idx = state.stages.length - 1;
  if (state.stages[idx].live) runUpTo(idx);
}

// Build the Mongo stage object for a card.
function compileStage(st) {
  if (st.kind === "match") {
    const m = {};
    for (const c of st.clauses) {
      if (!c.field) continue;
      const v = coerce(c.value);
      switch (c.op) {
        case "=": m[c.field] = v; break;
        case "!=": m[c.field] = { $ne: v }; break;
        case ">": m[c.field] = { $gt: v }; break;
        case ">=": m[c.field] = { $gte: v }; break;
        case "<": m[c.field] = { $lt: v }; break;
        case "<=": m[c.field] = { $lte: v }; break;
        case "contains": m[c.field] = { $regex: String(c.value), $options: "i" }; break;
        case "regex": m[c.field] = { $regex: String(c.value), $options: "i" }; break;
        case "in": m[c.field] = { $in: String(c.value).split(",").map((x) => coerce(x.trim())) }; break;
        case "exists": m[c.field] = { $exists: c.value !== "false" }; break;
      }
    }
    return { $match: m };
  }
  if (st.kind === "group") {
    const g = { _id: st.groupKeys.length === 1 ? `$${st.groupKeys[0]}` : Object.fromEntries(st.groupKeys.map((k) => [k, `$${k}`])) };
    for (const a of st.accs) {
      if (a.fn === "count") g[a.name || "count"] = { $sum: 1 };
      else g[a.name || a.fn] = { [`$${a.fn}`]: a.field ? `$${a.field}` : 1 };
    }
    return { $group: g };
  }
  if (st.kind === "project") {
    const p = {};
    for (const c of st.clauses) { if (c.field) p[c.field] = c.include ? 1 : 0; }
    return { $project: p };
  }
  if (st.kind === "sort") {
    const s = {};
    for (const c of st.clauses) { if (c.field) s[c.field] = Number(c.dir); }
    return { $sort: s };
  }
  if (st.kind === "limit") return { $limit: Number(st.limit) || 10 };
  return {};
}

function coerce(v) {
  if (typeof v !== "string") return v;
  const t = v.trim();
  if (t === "") return "";
  if (t === "true") return true;
  if (t === "false") return false;
  if (/^-?\d+(\.\d+)?$/.test(t)) return Number(t);
  return t;
}

function buildPipeline(uptoIdx) {
  return state.stages.slice(0, uptoIdx + 1).map(compileStage);
}

// ---------------------------------------------------------------- render stages

function renderStages() {
  stagesEl.innerHTML = "";
  state.stages.forEach((st, idx) => stagesEl.appendChild(renderStageCard(st, idx)));
}

function renderStageCard(st, idx) {
  const meta = STAGE_META[st.kind];
  const card = document.createElement("div");
  card.className = "stage-card";
  card.dataset.idx = idx;

  const head = document.createElement("div");
  head.className = "stage-head";
  head.innerHTML = `<span class="icon">${meta.icon}</span><span class="stage-title">${meta.title}</span>`;
  const delta = document.createElement("span"); delta.className = "delta"; delta.id = `delta-${st.id}`;
  head.appendChild(delta);
  const live = document.createElement("label"); live.className = "live";
  live.innerHTML = `<input type="checkbox" ${st.live ? "checked" : ""}/> live`;
  live.querySelector("input").addEventListener("change", (e) => { st.live = e.target.checked; });
  head.appendChild(live);
  const actions = document.createElement("span"); actions.className = "stage-actions";
  const dup = document.createElement("button"); dup.textContent = "⧉"; dup.title = "Duplicate";
  dup.addEventListener("click", () => { state.stages.splice(idx + 1, 0, JSON.parse(JSON.stringify({ ...st, id: ++stageSeq }))); renderStages(); });
  const rm = document.createElement("button"); rm.className = "danger"; rm.textContent = "✕";
  rm.addEventListener("click", () => { state.stages.splice(idx, 1); renderStages(); });
  actions.append(dup, rm); head.appendChild(actions);
  card.appendChild(head);

  const bodyEl = document.createElement("div");
  bodyEl.className = "stage-body";
  bodyEl.appendChild(renderStageEditor(st, idx));

  const runRow = document.createElement("div"); runRow.className = "run-row";
  const runBtn = document.createElement("button"); runBtn.textContent = "▶ Run up to here";
  runBtn.addEventListener("click", () => runUpTo(idx));
  runRow.appendChild(runBtn);
  bodyEl.appendChild(runRow);

  const prev = document.createElement("div"); prev.className = "preview"; prev.id = `preview-${st.id}`; prev.hidden = true;
  bodyEl.appendChild(prev);
  card.appendChild(bodyEl);
  return card;
}

function fieldSelect(value, onChange) {
  const sel = document.createElement("select");
  const blank = document.createElement("option"); blank.value = ""; blank.textContent = "—"; sel.appendChild(blank);
  for (const f of fieldNames()) {
    const o = document.createElement("option"); o.value = f; o.textContent = f; if (f === value) o.selected = true; sel.appendChild(o);
  }
  sel.addEventListener("change", (e) => onChange(e.target.value));
  return sel;
}

function renderStageEditor(st, idx) {
  const wrap = document.createElement("div");
  const liveRerun = () => { if (st.live) debounceRun(idx); };

  if (st.kind === "match") {
    st.clauses.forEach((c, ci) => {
      const row = document.createElement("div"); row.className = "row-edit";
      row.appendChild(fieldSelect(c.field, (v) => { c.field = v; liveRerun(); }));
      const op = document.createElement("select");
      for (const o of ["=", "!=", ">", ">=", "<", "<=", "contains", "regex", "in", "exists"]) {
        const opt = document.createElement("option"); opt.value = o; opt.textContent = o; if (o === c.op) opt.selected = true; op.appendChild(opt);
      }
      op.addEventListener("change", (e) => { c.op = e.target.value; liveRerun(); });
      row.appendChild(op);
      const val = document.createElement("input"); val.placeholder = "value"; val.value = c.value;
      val.addEventListener("input", (e) => { c.value = e.target.value; liveRerun(); });
      row.appendChild(val);
      const del = document.createElement("button"); del.className = "remove danger"; del.textContent = "−";
      del.addEventListener("click", () => { st.clauses.splice(ci, 1); renderStages(); liveRerun(); });
      row.appendChild(del);
      wrap.appendChild(row);
    });
    wrap.appendChild(addClause("+ condition", () => { st.clauses.push({ field: "", op: "=", value: "" }); renderStages(); }));
  } else if (st.kind === "group") {
    const keyRow = document.createElement("div"); keyRow.className = "row-edit";
    keyRow.innerHTML = `<span class="muted">group by</span>`;
    keyRow.appendChild(fieldSelect(st.groupKeys[0] || "", (v) => { st.groupKeys = v ? [v] : []; liveRerun(); }));
    wrap.appendChild(keyRow);
    st.accs.forEach((a, ai) => {
      const row = document.createElement("div"); row.className = "row-edit";
      const name = document.createElement("input"); name.placeholder = "out name"; name.value = a.name; name.style.minWidth = "90px";
      name.addEventListener("input", (e) => { a.name = e.target.value; liveRerun(); });
      row.appendChild(name);
      const fn = document.createElement("select");
      for (const o of ["count", "sum", "avg", "min", "max", "addToSet", "first", "last"]) {
        const opt = document.createElement("option"); opt.value = o; opt.textContent = o; if (o === a.fn) opt.selected = true; fn.appendChild(opt);
      }
      fn.addEventListener("change", (e) => { a.fn = e.target.value; liveRerun(); });
      row.appendChild(fn);
      row.appendChild(fieldSelect(a.field, (v) => { a.field = v; liveRerun(); }));
      const del = document.createElement("button"); del.className = "remove danger"; del.textContent = "−";
      del.addEventListener("click", () => { st.accs.splice(ai, 1); renderStages(); liveRerun(); });
      row.appendChild(del);
      wrap.appendChild(row);
    });
    wrap.appendChild(addClause("+ accumulator", () => { st.accs.push({ name: "", fn: "sum", field: "" }); renderStages(); }));
  } else if (st.kind === "project") {
    st.clauses.forEach((c, ci) => {
      const row = document.createElement("div"); row.className = "row-edit";
      row.appendChild(fieldSelect(c.field, (v) => { c.field = v; liveRerun(); }));
      const inc = document.createElement("select");
      for (const o of [["1", "include"], ["0", "exclude"]]) {
        const opt = document.createElement("option"); opt.value = o[0]; opt.textContent = o[1]; if ((o[0] === "1") === c.include) opt.selected = true; inc.appendChild(opt);
      }
      inc.addEventListener("change", (e) => { c.include = e.target.value === "1"; liveRerun(); });
      row.appendChild(inc);
      const del = document.createElement("button"); del.className = "remove danger"; del.textContent = "−";
      del.addEventListener("click", () => { st.clauses.splice(ci, 1); renderStages(); liveRerun(); });
      row.appendChild(del);
      wrap.appendChild(row);
    });
    wrap.appendChild(addClause("+ field", () => { st.clauses.push({ field: "", include: true }); renderStages(); }));
  } else if (st.kind === "sort") {
    st.clauses.forEach((c, ci) => {
      const row = document.createElement("div"); row.className = "row-edit";
      row.appendChild(fieldSelect(c.field, (v) => { c.field = v; liveRerun(); }));
      const dir = document.createElement("select");
      for (const o of [["-1", "desc"], ["1", "asc"]]) {
        const opt = document.createElement("option"); opt.value = o[0]; opt.textContent = o[1]; if (Number(o[0]) === c.dir) opt.selected = true; dir.appendChild(opt);
      }
      dir.addEventListener("change", (e) => { c.dir = Number(e.target.value); liveRerun(); });
      row.appendChild(dir);
      const del = document.createElement("button"); del.className = "remove danger"; del.textContent = "−";
      del.addEventListener("click", () => { st.clauses.splice(ci, 1); renderStages(); liveRerun(); });
      row.appendChild(del);
      wrap.appendChild(row);
    });
    wrap.appendChild(addClause("+ sort key", () => { st.clauses.push({ field: "", dir: -1 }); renderStages(); }));
  } else if (st.kind === "limit") {
    const row = document.createElement("div"); row.className = "row-edit";
    const n = document.createElement("input"); n.type = "number"; n.min = "1"; n.value = st.limit;
    n.addEventListener("input", (e) => { st.limit = e.target.value; liveRerun(); });
    row.appendChild(n);
    wrap.appendChild(row);
  }
  return wrap;
}

function addClause(label, fn) {
  const b = document.createElement("button"); b.className = "add-clause"; b.textContent = label;
  b.addEventListener("click", fn);
  return b;
}

// ---------------------------------------------------------------- run

const debounceTimers = {};
function debounceRun(idx) {
  const st = state.stages[idx];
  clearTimeout(debounceTimers[st.id]);
  debounceTimers[st.id] = setTimeout(() => {
    // re-run this card and all below it
    for (let i = idx; i < state.stages.length; i++) if (state.stages[i].live) runUpTo(i);
  }, 300);
}

async function runUpTo(idx) {
  const st = state.stages[idx];
  if (!st) return;
  const pipeline = buildPipeline(idx);
  const deltaEl = document.getElementById(`delta-${st.id}`);
  const prevEl = document.getElementById(`preview-${st.id}`);
  if (deltaEl) deltaEl.textContent = "running…";
  try {
    const data = await postJSON("/api/wrangler/run", { collection: state.active, pipeline, upto: idx });
    if (deltaEl) deltaEl.textContent = `${data.input_count} → ${data.output_count} rows`;
    renderPreview(prevEl, data.rows, idx);
  } catch (e) {
    if (deltaEl) deltaEl.textContent = "error";
    toast(`stage ${idx}: ${e.message}`, "error", 6000);
  }
}

function renderPreview(el, rows, idx) {
  if (!el) return;
  el.hidden = false;
  el.innerHTML = "";
  if (!rows || !rows.length) { el.innerHTML = `<div class="muted" style="padding:8px">no rows</div>`; return; }
  const cols = [];
  for (const r of rows) for (const k of Object.keys(r)) if (!cols.includes(k)) cols.push(k);
  const table = document.createElement("table");
  const thead = document.createElement("thead"); const htr = document.createElement("tr");
  for (const c of cols) { const th = document.createElement("th"); th.textContent = c; htr.appendChild(th); }
  thead.appendChild(htr); table.appendChild(thead);
  const tbody = document.createElement("tbody");
  for (const r of rows) {
    const tr = document.createElement("tr");
    if (r._id != null) tr.dataset.rid = String(r._id);
    for (const c of cols) { const td = document.createElement("td"); td.textContent = fmt(r[c]); tr.appendChild(td); }
    // hover-link to the previous stage's preview by _id
    tr.addEventListener("mouseenter", () => linkRow(idx, tr.dataset.rid, true));
    tr.addEventListener("mouseleave", () => linkRow(idx, tr.dataset.rid, false));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody); el.appendChild(table);
}

function linkRow(idx, rid, on) {
  if (!rid || idx <= 0) return;
  const prevSt = state.stages[idx - 1];
  if (!prevSt) return;
  const prevEl = document.getElementById(`preview-${prevSt.id}`);
  if (!prevEl) return;
  const match = prevEl.querySelector(`tr[data-rid="${CSS.escape(rid)}"]`);
  if (match) match.classList.toggle("linked", on);
}

// ---------------------------------------------------------------- footer actions

$("#run-all").addEventListener("click", () => { if (state.stages.length) runUpTo(state.stages.length - 1); });
$("#refresh").addEventListener("click", loadSample);

document.querySelectorAll("#add-stage-row button").forEach((b) =>
  b.addEventListener("click", () => addStage(b.dataset.kind)));

$("#save").addEventListener("click", async () => {
  if (!state.stages.length) { toast("nothing to save", "info"); return; }
  const name = prompt("Pipeline name:");
  if (!name) return;
  try {
    const stages = state.stages.map(compileStage);
    const r = await postJSON("/api/wrangler/save", { name, collection: state.active, stages });
    toast(`saved “${name}” (${r._id})`, "ok");
  } catch (e) { toast(`save failed: ${e.message}`, "error", 6000); }
});

$("#load").addEventListener("click", async () => {
  const panel = $("#load-panel"); const list = $("#load-list");
  list.innerHTML = "<div class='muted'>loading…</div>";
  panel.hidden = false;
  try {
    const data = await getJSON(`/api/wrangler/pipelines?collection=${encodeURIComponent(state.active)}`);
    list.innerHTML = "";
    if (!data.pipelines || !data.pipelines.length) { list.innerHTML = "<div class='muted'>no saved pipelines</div>"; return; }
    for (const p of data.pipelines) {
      const card = document.createElement("div"); card.className = "load-card";
      card.innerHTML = `<h4>${p.name}</h4><div class="muted">${(p.stages || []).length} stages · ${p.collection}</div>`;
      const btn = document.createElement("button"); btn.className = "load-btn primary"; btn.textContent = "Load";
      btn.addEventListener("click", () => { hydrateFromStages(p.stages); panel.hidden = true; toast(`loaded “${p.name}”`, "ok"); });
      card.appendChild(btn); list.appendChild(card);
    }
  } catch (e) { list.innerHTML = `<div class='muted'>error: ${e.message}</div>`; }
});
$("#load-close").addEventListener("click", () => { $("#load-panel").hidden = true; });

// ---------------------------------------------------------------- suggest

$("#suggest").addEventListener("click", async () => {
  const panel = $("#suggest-panel"); const list = $("#suggest-list");
  list.innerHTML = "<div class='muted'>asking the agent…</div>";
  panel.hidden = false;
  try {
    const data = await postJSON("/api/wrangler/suggest", { collection: state.active });
    list.innerHTML = "";
    const pipelines = data.pipelines || [];
    if (!pipelines.length) { list.innerHTML = "<div class='muted'>no valid suggestions returned</div>"; return; }
    for (const p of pipelines) {
      const card = document.createElement("div"); card.className = "suggest-card";
      card.innerHTML = `<h4>${p.name}</h4><div class="muted">${p.rationale || ""}</div>` +
        `<pre>${JSON.stringify(p.stages, null, 2)}</pre>`;
      const btn = document.createElement("button"); btn.className = "load-btn primary"; btn.textContent = "Load into builder";
      btn.addEventListener("click", () => { hydrateFromStages(p.stages); panel.hidden = true; toast(`loaded “${p.name}”`, "ok"); });
      card.appendChild(btn); list.appendChild(card);
    }
  } catch (e) { list.innerHTML = `<div class='muted'>error: ${e.message}</div>`; }
});
$("#suggest-close").addEventListener("click", () => { $("#suggest-panel").hidden = true; });

// Rebuild editable stage cards from raw Mongo stages (best-effort decompile).
function hydrateFromStages(rawStages) {
  state.stages = [];
  for (const raw of rawStages || []) {
    const key = Object.keys(raw)[0];
    const body = raw[key];
    let st = null;
    if (key === "$match") {
      st = newStage("match"); st.clauses = [];
      for (const [field, cond] of Object.entries(body)) {
        if (cond && typeof cond === "object" && !Array.isArray(cond)) {
          const opKey = Object.keys(cond)[0];
          const map = { $ne: "!=", $gt: ">", $gte: ">=", $lt: "<", $lte: "<=", $regex: "contains", $in: "in", $exists: "exists" };
          let val = cond[opKey];
          if (opKey === "$in" && Array.isArray(val)) val = val.join(",");
          st.clauses.push({ field, op: map[opKey] || "=", value: String(val) });
        } else {
          st.clauses.push({ field, op: "=", value: String(cond) });
        }
      }
      if (!st.clauses.length) st.clauses.push({ field: "", op: "=", value: "" });
    } else if (key === "$group") {
      st = newStage("group");
      const id = body._id;
      if (typeof id === "string") st.groupKeys = [id.replace(/^\$/, "")];
      else if (id && typeof id === "object") st.groupKeys = Object.values(id).map((v) => String(v).replace(/^\$/, ""));
      else st.groupKeys = [];
      st.accs = [];
      for (const [name, acc] of Object.entries(body)) {
        if (name === "_id") continue;
        const fn = Object.keys(acc)[0].replace(/^\$/, "");
        const operand = acc[`$${fn}`];
        st.accs.push({ name, fn: fn === "sum" && operand === 1 ? "count" : fn, field: typeof operand === "string" ? operand.replace(/^\$/, "") : "" });
      }
      if (!st.accs.length) st.accs.push({ name: "count", fn: "count", field: "" });
    } else if (key === "$project") {
      st = newStage("project"); st.clauses = Object.entries(body).map(([field, v]) => ({ field, include: !!v }));
    } else if (key === "$sort") {
      st = newStage("sort"); st.clauses = Object.entries(body).map(([field, dir]) => ({ field, dir: Number(dir) }));
    } else if (key === "$limit") {
      st = newStage("limit"); st.limit = Number(body);
    }
    if (st) state.stages.push(st);
  }
  renderStages();
  if (state.stages.length) runUpTo(state.stages.length - 1);
}

// ---------------------------------------------------------------- boot

loadCollections().catch((e) => toast(`init: ${e.message}`, "error", 8000));
