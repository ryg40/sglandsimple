db = db.getSiblingDB('enterprise');

const findingId = "finding-smoke-001";
const epicId = "epic-rds-001";

db.audit_findings.deleteMany({ _id: findingId });

db.audit_findings.insertOne({
  _id: findingId,
  source: "manual",
  regulation: "SOX-404",
  requirement: "Database audit logs must capture login events, SQL errors, and SQL queries",
  severity: "high",
  status: "open",
  epic_id: epicId,
  created_at: new Date(),
  updated_at: new Date()
});

print("Seeded audit_findings collection with sample finding.");
