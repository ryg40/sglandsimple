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

print("Initialized docs / doc_revisions / doc_sync_log collections (" +
  db.docs.countDocuments({}) + " docs).");
