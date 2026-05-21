db = db.getSiblingDB('enterprise');

// Empty schema doc so the collection exists
db.doc_records.deleteMany({});

db.doc_records.insertOne({
  _id: "doc-placeholder",
  epic_id: "epic-rds-001",
  finding_id: "finding-smoke-001",
  title: "Placeholder Epic Log",
  confluence_url: "https://confluence.example.com/placeholder",
  status: "draft",
  created_at: new Date(),
  updated_at: new Date()
});

print("Initialized doc_records collection.");
