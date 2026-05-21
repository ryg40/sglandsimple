import type { ReactNode } from "react";
import { Badge } from "./ui/badge";

// Stage 12 — schema-keyed column registry for the Hub detail table.
// Each connector's summary() carries a `schema` hint; the Hub renders the
// matching column set. Falls back to a generic key/value dump for any
// connector without a registered schema.

export interface Column {
  header: string;
  align?: "left" | "right";
  cell: (row: any) => ReactNode;
}

function chip(text: string, cls: string) {
  return <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold ${cls}`}>{text}</span>;
}

const statusChip = (s: string) =>
  chip(
    s,
    /done|closed|merged|success|available|active|enabled|logging/i.test(s)
      ? "bg-green-100 text-green-800"
      : /progress/i.test(s)
      ? "bg-blue-50 text-blue-700 border border-blue-200"
      : /block|denied|fail|breach|disabled/i.test(s)
      ? "bg-red-100 text-red-800"
      : "bg-slate-100 text-slate-700 border",
  );

export const SCHEMA_COLUMNS: Record<string, Column[]> = {
  jira_sprint: [
    { header: "Key", cell: (r) => <span className="font-mono font-bold text-blue-600 dark:text-blue-400">{r.key}</span> },
    { header: "Summary", cell: (r) => <span className="max-w-[220px] truncate inline-block align-bottom" title={r.summary}>{r.summary}</span> },
    { header: "Epic", cell: (r) => <span className="font-mono text-[10.5px]">{r.epic_name ?? r.epic_key}</span> },
    { header: "Status", cell: (r) => statusChip(r.status ?? r.fields?.status?.name ?? "—") },
    { header: "Assignee", cell: (r) => <span className="font-serif text-muted-foreground">{r.assignee}</span> },
    { header: "Pts", align: "right", cell: (r) => <span className="font-mono">{r.story_points ?? "—"}</span> },
    {
      header: "Updated",
      align: "right",
      cell: (r) =>
        r.flagged ? (
          <span className="font-mono text-red-600" title={`Neglected — ${r.age_days}d since update`}>
            {r.updated} ⚠
          </span>
        ) : (
          <span className="font-mono text-muted-foreground">{r.updated}</span>
        ),
    },
  ],
  github_commits: [
    { header: "SHA", cell: (r) => <span className="font-mono font-semibold text-emerald-600 dark:text-emerald-400">{r.sha}</span> },
    { header: "Message", cell: (r) => <span className="max-w-[220px] truncate inline-block align-bottom" title={r.message}>{r.message}</span> },
    { header: "Project", cell: (r) => <span className="text-[11px]">{r.project}</span> },
    {
      header: "Tags",
      cell: (r) => (
        <span className="flex flex-wrap gap-1">
          {(r.tags ?? []).map((t: string) => (
            <Badge key={t} variant="outline" className="text-[9px] font-mono py-0 px-1 font-normal">{t}</Badge>
          ))}
        </span>
      ),
    },
    {
      header: "Checks",
      cell: (r) =>
        chip(
          r.checks_state,
          r.checks_state === "passing" ? "bg-green-100 text-green-800" : r.checks_state === "failing" ? "bg-red-100 text-red-800" : "bg-amber-50 text-amber-700 border border-amber-200",
        ),
    },
    { header: "Author", align: "right", cell: (r) => <span className="font-mono text-muted-foreground">@{r.author}</span> },
  ],
  confluence_links: [
    { header: "Title", cell: (r) => <a href={r.url} target="_blank" rel="noreferrer" className="font-medium text-cyan-600 dark:text-cyan-400 hover:underline max-w-[230px] truncate inline-block align-bottom" title={r.title}>{r.title}</a> },
    { header: "Space", cell: (r) => <span className="font-mono text-[10.5px]">{r.space?.name ?? r.space?.key ?? r.space}</span> },
    {
      header: "Matched on",
      cell: (r) => {
        const m = r.matched_on ?? {};
        const tags = [
          ...(m.ticket_refs ?? []).map((x: string) => `#${x}`),
          ...(m.users ?? []),
          ...(m.projects ?? []),
          ...(m.keywords ?? []).map((x: string) => `“${x}”`),
        ];
        return (
          <span className="flex flex-wrap gap-1">
            {tags.slice(0, 5).map((t: string, i: number) => (
              <Badge key={i} variant="outline" className="text-[9px] py-0 px-1 font-normal">{t}</Badge>
            ))}
          </span>
        );
      },
    },
    { header: "Updated", align: "right", cell: (r) => <span className="font-mono text-muted-foreground text-[10.5px]">{r.last_updated}</span> },
  ],
  snowflake_audit: [
    { header: "Timestamp", cell: (r) => <span className="font-mono text-muted-foreground">{r.timestamp}</span> },
    { header: "User", cell: (r) => <span className="font-semibold text-sky-600 dark:text-sky-400">{r.user_name}</span> },
    { header: "Event", cell: (r) => <span className="uppercase font-mono text-[10.5px]">{r.event_type}</span> },
    { header: "SQL", cell: (r) => <span className="max-w-[180px] truncate inline-block align-bottom font-mono text-slate-500 text-[10px]" title={r.sql_text}>{r.sql_text}</span> },
    { header: "Status", cell: (r) => <Badge variant={r.status === "SUCCESS" ? "default" : "destructive"} className="text-[9px] py-0 px-1 font-mono">{r.status}</Badge> },
  ],
  aws_resources: [
    { header: "Resource", cell: (r) => <span className="font-mono font-semibold text-orange-600 dark:text-orange-400">{r.resource_id}</span> },
    { header: "Service", cell: (r) => <Badge variant="outline" className="text-[9px] font-mono py-0 px-1">{r.service}</Badge> },
    { header: "Type", cell: (r) => <span className="font-mono text-[10.5px]">{r.resource_type}</span> },
    { header: "Region", cell: (r) => <span className="font-mono text-[10.5px]">{r.region}</span> },
    { header: "Env", cell: (r) => chip(r.env, r.env === "prod" ? "bg-purple-100 text-purple-800" : "bg-slate-100 text-slate-700 border") },
    {
      header: "Audit log",
      cell: (r) =>
        r.audit_logging === "disabled"
          ? chip("disabled ⚠", "bg-red-100 text-red-800")
          : chip(r.audit_logging, r.audit_logging === "enabled" ? "bg-green-100 text-green-800" : "bg-slate-100 text-slate-600 border"),
    },
    { header: "Status", align: "right", cell: (r) => statusChip(r.status) },
  ],
  snow_grc: [
    { header: "Number", cell: (r) => <span className="font-mono font-bold text-rose-600 dark:text-rose-400">{r.number}</span> },
    { header: "Type", cell: (r) => chip(r.record_type, r.record_type === "incident" ? "bg-rose-50 text-rose-700 border border-rose-200" : "bg-indigo-50 text-indigo-700 border border-indigo-200") },
    { header: "Summary", cell: (r) => <span className="max-w-[220px] truncate inline-block align-bottom" title={r.short_description}>{r.short_description}</span> },
    {
      header: "Priority / Risk",
      cell: (r) =>
        r.record_type === "incident"
          ? chip(r.priority, /^1/.test(r.priority) ? "bg-red-100 text-red-800" : "bg-slate-100 text-slate-700 border")
          : chip(`${r.risk} risk`, /high/i.test(r.risk) ? "bg-red-100 text-red-800" : "bg-amber-50 text-amber-700 border border-amber-200"),
    },
    { header: "CI", cell: (r) => <span className="font-mono text-[10.5px]">{r.cmdb_ci}</span> },
    { header: "State", cell: (r) => statusChip(r.state) },
    {
      header: "When",
      align: "right",
      cell: (r) =>
        r.record_type === "incident" ? (
          <span className="font-mono text-[10.5px] text-muted-foreground" title={`SLA due ${r.sla_due}`}>{r.sla_breach ? "SLA BREACH ⚠" : r.opened_at}</span>
        ) : (
          <span className="font-mono text-[10.5px] text-muted-foreground">{r.start_date}</span>
        ),
    },
  ],
  mongo_collections: [
    { header: "Collection", cell: (r) => <span className="font-mono font-semibold text-green-700 dark:text-green-400">{r.name}</span> },
    { header: "Documents", align: "right", cell: (r) => <span className="font-mono">{(r.count ?? 0).toLocaleString()}</span> },
  ],
  archer_findings: [
    { header: "Finding", cell: (r) => <span className="font-mono font-semibold">{r.finding_id}</span> },
    { header: "Control", cell: (r) => <Badge variant="outline" className="text-[9px] font-mono py-0 px-1">{r.control}</Badge> },
    { header: "Title", cell: (r) => <span className="max-w-[240px] truncate inline-block align-bottom" title={r.title}>{r.title}</span> },
    { header: "Severity", cell: (r) => chip(r.severity, /high|critical/i.test(r.severity) ? "bg-red-100 text-red-800" : "bg-amber-50 text-amber-700 border border-amber-200") },
    { header: "Status", align: "right", cell: (r) => statusChip(r.status) },
  ],
};

// Generic fallback for any connector without a registered schema: show the
// first handful of scalar keys.
export function fallbackColumns(rows: any[]): Column[] {
  const first = rows[0] ?? {};
  return Object.keys(first)
    .filter((k) => ["string", "number", "boolean"].includes(typeof first[k]))
    .slice(0, 6)
    .map((k) => ({ header: k, cell: (r: any) => <span className="font-mono text-[11px]">{String(r[k])}</span> }));
}
