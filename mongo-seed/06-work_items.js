db = db.getSiblingDB('enterprise');

// Stage 11: real work-item rows with a spread of due dates and updated_at so the
// Overview attention rules (due-soon / overdue / stalled) have data to fire on.
db.work_items.deleteMany({});

const DAY = 24 * 60 * 60 * 1000;
const now = Date.now();
const at = (offset) => new Date(now + offset * DAY); // offset in days (negative = past)

db.work_items.insertMany([
  {
    _id: "wi-rds-logging-01",
    finding_id: "finding-smoke-001",
    epic_id: "epic-rds-001",
    jira_key: "RDS-LOG-1",
    title: "Enable RDS audit logging via parameter group",
    type: "implementation",
    status: "in_progress",
    priority: "high",
    due_date: at(5),          // due soon
    created_at: at(-20),
    updated_at: at(-1)        // fresh
  },
  {
    _id: "wi-scan-gate-02",
    finding_id: "finding-compliance-jira-01",
    epic_id: "epic-control-01",
    jira_key: "SEC-SCAN-101",
    title: "Wire vulnerability scan gate into CI",
    type: "implementation",
    status: "in_progress",
    priority: "critical",
    due_date: at(-3),         // overdue
    created_at: at(-30),
    updated_at: at(-10)       // stalled (no update in >7d)
  },
  {
    _id: "wi-cert-rotate-03",
    finding_id: "finding-stale-certs-02",
    epic_id: "epic-certs-02",
    jira_key: "OPS-CERT-202",
    title: "Automate ALB TLS certificate rotation",
    type: "implementation",
    status: "todo",
    priority: "high",
    due_date: at(12),         // due soon (within 14d)
    created_at: at(-15),
    updated_at: at(-2)
  },
  {
    _id: "wi-iam-cleanup-04",
    finding_id: "finding-unauth-access-03",
    epic_id: "epic-access-03",
    jira_key: "IAM-STALE-303",
    title: "Revoke stale IAM users + Slack notifications",
    type: "implementation",
    status: "in_progress",
    priority: "medium",
    due_date: at(40),         // comfortably future
    created_at: at(-12),
    updated_at: at(-9)        // stalled
  },
  {
    _id: "wi-rds-docs-05",
    finding_id: "finding-smoke-001",
    epic_id: "epic-rds-001",
    jira_key: "RDS-LOG-2",
    title: "Document RDS logging runbook",
    type: "documentation",
    status: "done",
    priority: "low",
    due_date: at(-1),         // past but done -> should NOT alert
    created_at: at(-25),
    updated_at: at(-1)
  }
]);

print("Seeded work_items collection with " + db.work_items.countDocuments({}) + " rows.");
