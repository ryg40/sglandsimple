// Editable stage model <-> Mongo aggregation stages. Mirrors the Stage-7
// vanilla builder's compile/decompile logic, typed.

import type { Stage } from "./types";

export type StageKind = "match" | "group" | "project" | "sort" | "limit";

export interface MatchClause { field: string; op: string; value: string }
export interface Accumulator { name: string; fn: string; field: string }
export interface ProjectClause { field: string; include: boolean }
export interface SortClause { field: string; dir: number }

export interface EditableStage {
  id: number;
  kind: StageKind;
  live: boolean;
  clauses?: MatchClause[];
  projects?: ProjectClause[];
  sorts?: SortClause[];
  groupKeys?: string[];
  accs?: Accumulator[];
  limit?: number;
}

export const STAGE_META: Record<StageKind, { icon: string; title: string }> = {
  match: { icon: "⮕", title: "Filter ($match)" },
  group: { icon: "Σ", title: "Group ($group)" },
  project: { icon: "▦", title: "Project ($project)" },
  sort: { icon: "↧", title: "Sort ($sort)" },
  limit: { icon: "⊓", title: "Limit ($limit)" },
};

let seq = 0;
export function nextId() { return ++seq; }

export function newStage(kind: StageKind, seedField?: string): EditableStage {
  const st: EditableStage = { id: nextId(), kind, live: true };
  if (kind === "match") st.clauses = [{ field: seedField ?? "", op: "=", value: "" }];
  else if (kind === "group") { st.groupKeys = seedField ? [seedField] : []; st.accs = [{ name: "count", fn: "count", field: "" }]; }
  else if (kind === "project") st.projects = [{ field: seedField ?? "", include: true }];
  else if (kind === "sort") st.sorts = [{ field: seedField ?? "", dir: -1 }];
  else if (kind === "limit") st.limit = 10;
  return st;
}

function coerce(v: string): unknown {
  const t = v.trim();
  if (t === "") return "";
  if (t === "true") return true;
  if (t === "false") return false;
  if (/^-?\d+(\.\d+)?$/.test(t)) return Number(t);
  return t;
}

export function compileStage(st: EditableStage): Stage {
  if (st.kind === "match") {
    const m: Record<string, unknown> = {};
    for (const c of st.clauses ?? []) {
      if (!c.field) continue;
      const v = coerce(c.value);
      switch (c.op) {
        case "=": m[c.field] = v; break;
        case "!=": m[c.field] = { $ne: v }; break;
        case ">": m[c.field] = { $gt: v }; break;
        case ">=": m[c.field] = { $gte: v }; break;
        case "<": m[c.field] = { $lt: v }; break;
        case "<=": m[c.field] = { $lte: v }; break;
        case "contains":
        case "regex": m[c.field] = { $regex: c.value, $options: "i" }; break;
        case "in": m[c.field] = { $in: c.value.split(",").map((x) => coerce(x.trim())) }; break;
        case "exists": m[c.field] = { $exists: c.value !== "false" }; break;
      }
    }
    return { $match: m };
  }
  if (st.kind === "group") {
    const keys = st.groupKeys ?? [];
    const g: Record<string, unknown> = {
      _id: keys.length === 1 ? `$${keys[0]}` : Object.fromEntries(keys.map((k) => [k, `$${k}`])),
    };
    for (const a of st.accs ?? []) {
      if (a.fn === "count") g[a.name || "count"] = { $sum: 1 };
      else g[a.name || a.fn] = { [`$${a.fn}`]: a.field ? `$${a.field}` : 1 };
    }
    return { $group: g };
  }
  if (st.kind === "project") {
    const p: Record<string, number> = {};
    for (const c of st.projects ?? []) if (c.field) p[c.field] = c.include ? 1 : 0;
    return { $project: p };
  }
  if (st.kind === "sort") {
    const s: Record<string, number> = {};
    for (const c of st.sorts ?? []) if (c.field) s[c.field] = Number(c.dir);
    return { $sort: s };
  }
  return { $limit: Number(st.limit) || 10 };
}

const OP_MAP: Record<string, string> = {
  $ne: "!=", $gt: ">", $gte: ">=", $lt: "<", $lte: "<=",
  $regex: "contains", $in: "in", $exists: "exists",
};

export function decompile(stages: Stage[]): EditableStage[] {
  const out: EditableStage[] = [];
  for (const raw of stages ?? []) {
    const key = Object.keys(raw)[0];
    const body = raw[key] as Record<string, unknown>;
    if (key === "$match") {
      const st = newStage("match");
      st.clauses = [];
      for (const [field, cond] of Object.entries(body)) {
        if (cond && typeof cond === "object" && !Array.isArray(cond)) {
          const opKey = Object.keys(cond as object)[0];
          let val = (cond as Record<string, unknown>)[opKey];
          if (opKey === "$in" && Array.isArray(val)) val = val.join(",");
          st.clauses.push({ field, op: OP_MAP[opKey] ?? "=", value: String(val) });
        } else {
          st.clauses.push({ field, op: "=", value: String(cond) });
        }
      }
      if (!st.clauses.length) st.clauses.push({ field: "", op: "=", value: "" });
      out.push(st);
    } else if (key === "$group") {
      const st = newStage("group");
      const id = body._id;
      if (typeof id === "string") st.groupKeys = [id.replace(/^\$/, "")];
      else if (id && typeof id === "object") st.groupKeys = Object.values(id as object).map((v) => String(v).replace(/^\$/, ""));
      else st.groupKeys = [];
      st.accs = [];
      for (const [name, acc] of Object.entries(body)) {
        if (name === "_id") continue;
        const fn = Object.keys(acc as object)[0].replace(/^\$/, "");
        const operand = (acc as Record<string, unknown>)[`$${fn}`];
        st.accs.push({ name, fn: fn === "sum" && operand === 1 ? "count" : fn, field: typeof operand === "string" ? operand.replace(/^\$/, "") : "" });
      }
      if (!st.accs.length) st.accs.push({ name: "count", fn: "count", field: "" });
      out.push(st);
    } else if (key === "$project") {
      const st = newStage("project");
      st.projects = Object.entries(body).map(([field, v]) => ({ field, include: !!v }));
      out.push(st);
    } else if (key === "$sort") {
      const st = newStage("sort");
      st.sorts = Object.entries(body).map(([field, dir]) => ({ field, dir: Number(dir) }));
      out.push(st);
    } else if (key === "$limit") {
      const st = newStage("limit");
      st.limit = Number(body);
      out.push(st);
    }
  }
  return out;
}
