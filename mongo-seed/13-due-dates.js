db = db.getSiblingDB('enterprise');

// Stage 11: backfill due dates on the existing epics and audit_findings so the
// Overview attention rules (prioritized / due-soon / overdue) have real data.
// Idempotent: re-running just resets the same fields.
const DAY = 24 * 60 * 60 * 1000;
const now = Date.now();
const at = (offset) => new Date(now + offset * DAY);

// epic_id -> days-from-now offset for its due date
const epicDue = {
  "epic-rds-001": 6,      // due soon
  "epic-control-01": -5,  // overdue (critical priority)
  "epic-certs-02": 10,    // due soon
  "epic-access-03": 45,   // future
  "epic-data-01": 28      // future Stage-23 data-governance epic
};
for (const [id, off] of Object.entries(epicDue)) {
  db.epics.updateOne({ _id: id }, { $set: { due_date: at(off) } });
}

// finding_id -> days-from-now offset
const findingDue = {
  "finding-smoke-001": 8,               // due soon, high
  "finding-compliance-jira-01": -2,     // overdue, critical
  "finding-stale-certs-02": 11,         // due soon, high
  "finding-unauth-access-03": 50        // future, medium
};
for (const [id, off] of Object.entries(findingDue)) {
  db.audit_findings.updateOne({ _id: id }, { $set: { due_date: at(off) } });
}

print("Backfilled due_date on epics and audit_findings.");
