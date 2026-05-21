db = db.getSiblingDB('enterprise');

const epicId = "epic-rds-001";

db.epics.deleteMany({ _id: epicId });

db.epics.insertOne({
  _id: epicId,
  jira_key: "RDS-LOG-1",
  title: "RDS Audit Logging",
  regulation_refs: ["SOX-404", "PCI-DSS-10.2"],
  db_platform_combos: ["RDS MySQL", "RDS PostgreSQL", "RDS MariaDB"],
  priority: "high",
  status: "in_progress",
  created_at: new Date(),
  updated_at: new Date()
});

print("Seeded epics collection with RDS priority epic.");
