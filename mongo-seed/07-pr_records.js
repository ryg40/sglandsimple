db = db.getSiblingDB('enterprise');

// Empty schema doc so the collection exists
db.pr_records.deleteMany({});

db.pr_records.insertOne({
  _id: "pr-placeholder",
  work_item_id: "work-item-placeholder",
  epic_id: "epic-rds-001",
  pr_number: 0,
  branch: "feature/placeholder",
  status: "open",
  url: "https://github.com/org/repo/pull/0",
  created_at: new Date(),
  updated_at: new Date()
});

print("Initialized pr_records collection.");
