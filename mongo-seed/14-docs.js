// Stage 14 — Docs Wiki collections: docs / doc_revisions / doc_sync_log.
// System of record for the in-app documentation library. The real corpus is
// imported from the repo Markdown by scripts/import_docs.py; these seeds make
// the collections exist with the 14b shape and give the smoke test + UI a few
// deterministic rows (including one deliberately stale doc to exercise the
// needs_attention lifecycle rule).
db = db.getSiblingDB('enterprise');

db.docs.deleteMany({});
db.doc_revisions.deleteMany({});
db.doc_sync_log.deleteMany({});

const now = new Date();
const longAgo = new Date(now.getTime() - 200 * 24 * 3600 * 1000); // ~200d → past DOCS_REVIEW_DAYS

function seedDoc(d) {
  db.docs.insertOne(d);
  db.doc_revisions.insertOne({
    _id: d._id + ":v" + d.version,
    doc_id: d._id,
    version: d.version,
    body_md: d.body_md,
    author: d.owner,
    created_at: d.created_at,
    note: "seed",
  });
}

seedDoc({
  _id: "doc-welcome",
  slug: "welcome",
  path: "welcome",
  title: "Welcome to the Fleet-Dispatch Docs Wiki",
  body_md: "# Welcome\n\nThis is the in-app documentation library. Every doc lives in MongoDB as the system of record. Public docs sync to Confluence under the same path tree.\n",
  tags: ["onboarding"],
  status: "up_to_date",
  visibility: "internal",
  owner: "platform",
  version: 1,
  confluence_page_id: null,
  last_reviewed_at: now,
  created_at: now,
  updated_at: now,
});

seedDoc({
  _id: "doc-runbooks-rds-audit-logging",
  slug: "runbooks/rds-audit-logging",
  path: "runbooks/rds-audit-logging",
  title: "Runbook: RDS Audit Logging",
  body_md: "# RDS Audit Logging Runbook\n\nEnable `audit_logging` on the production RDS instance to satisfy SOX-404 / PCI-DSS-10.2.\n\n## Steps\n\n1. Set the parameter group flag.\n2. Reboot in a maintenance window.\n3. Confirm logs land in CloudTrail.\n",
  tags: ["rds", "sox-404", "runbook"],
  status: "up_to_date",
  visibility: "public",
  owner: "sultan-devops",
  version: 1,
  confluence_page_id: null,
  last_reviewed_at: now,
  created_at: now,
  updated_at: now,
});

// Deliberately stale → import/triage should flag needs_attention.
seedDoc({
  _id: "doc-runbooks-legacy-cert-rotation",
  slug: "runbooks/legacy-cert-rotation",
  path: "runbooks/legacy-cert-rotation",
  title: "Runbook: Legacy Certificate Rotation",
  body_md: "# Legacy Certificate Rotation\n\nThis runbook has not been reviewed in a long time and references the old ALB pipeline.\n",
  tags: ["tls", "runbook"],
  status: "needs_attention",
  visibility: "internal",
  owner: "sarah-sre",
  version: 1,
  confluence_page_id: null,
  last_reviewed_at: longAgo,
  created_at: longAgo,
  updated_at: longAgo,
});

// Stage 23 teaching docs are also stored in the wiki seed so a fresh stack has
// the training corpus before the optional Markdown importer runs.
seedDoc({
  _id: "doc-overlap-chain",
  slug: "overlap-chain",
  path: "teaching/overlap-chain",
  title: "How the overlap chain works",
  body_md: "# How the overlap chain works\n\nThe POC traceability chain links Archer risk findings to Jira epics/work items, GitHub commits/PRs, ServiceNow changes, Snowflake evidence, and Confluence pages. The shared keys are `finding_id`, `epic_key`, and `ticket_refs`. Example: `finding-smoke-001` → `RDS-LOG-1` → `RDS-LOG-3` → `CHG0042042` → `SFQ-RDS-AUDIT-COVERAGE` → Confluence pages `100401`/`100433`.\n\nSee `docs/overlap-chain.md` in the repo for the full walkthrough.\n",
  tags: ["stage-23", "training", "overlap-chain", "mcp"],
  status: "up_to_date",
  visibility: "public",
  owner: "platform",
  version: 1,
  confluence_page_id: null,
  last_reviewed_at: now,
  created_at: now,
  updated_at: now,
});

seedDoc({
  _id: "doc-agentic-workflows",
  slug: "agentic-workflows",
  path: "teaching/agentic-workflows",
  title: "Agentic workflows in this stack",
  body_md: "# Agentic workflows in this stack\n\nLangGraph workflows live server-side in the MCP service. Key examples are the docs-agent HITL apply gate, standup follow-up proposal flow, compliance workflow orchestrator, Ask Data graph, and the planned Deep Agent platform. Every production mutation stays dry-run/proposed until the relevant HITL gate and write flags allow it.\n\nSee `docs/agentic-workflows.md` for the full guide.\n",
  tags: ["stage-23", "training", "agentic-workflows", "langgraph"],
  status: "up_to_date",
  visibility: "public",
  owner: "platform",
  version: 1,
  confluence_page_id: null,
  last_reviewed_at: now,
  created_at: now,
  updated_at: now,
});

seedDoc({
  _id: "doc-mcp-in-this-stack",
  slug: "mcp-in-this-stack",
  path: "teaching/mcp-in-this-stack",
  title: "MCP in this stack",
  body_md: "# MCP in this stack\n\nThe browser calls web `/api/*` routes; web proxies to MCP JSON-RPC tools; the OpenAI-compatible agent also uses MCP for tool dispatch. Connectors are live-or-mock by flag and token. Confluence is the Stage 23 worked example: set `CONN_CONFLUENCE_ENABLED=true`, `CONFLUENCE_MCP_URL`, and `CONFLUENCE_TOKEN`; live writes additionally require `WORKFLOW_WRITES_ENABLED=true`, `CONFLUENCE_WRITES_ENABLED=true`, and the docs sync gate.\n\nSee `docs/mcp-in-this-stack.md` for the full guide.\n",
  tags: ["stage-23", "training", "mcp", "confluence"],
  status: "up_to_date",
  visibility: "public",
  owner: "platform",
  version: 1,
  confluence_page_id: null,
  last_reviewed_at: now,
  created_at: now,
  updated_at: now,
});

print("Initialized docs / doc_revisions / doc_sync_log collections (" +
  db.docs.countDocuments({}) + " docs).");
