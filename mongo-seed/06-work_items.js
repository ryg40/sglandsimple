db = db.getSiblingDB('enterprise');

// Empty schema doc so the collection exists
db.work_items.deleteMany({});

db.work_items.insertOne({
  _id: "work-item-placeholder",
  finding_id: "finding-smoke-001",
  epic_id: "epic-rds-001",
  jira_key: "RDS-LOG-1",
  type: "placeholder",
  status: "pending",
  created_at: new Date(),
  updated_at: new Date()
});

print("Initialized work_items collection.");
