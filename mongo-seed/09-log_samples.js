db = db.getSiblingDB('enterprise');

// Empty schema doc so the collection exists
db.log_samples.deleteMany({});

db.log_samples.insertOne({
  _id: "log-placeholder",
  finding_id: "finding-smoke-001",
  epic_id: "epic-rds-001",
  source: "mock",
  event_type: "login",
  message: "Mock audit log entry for RDS login event",
  severity: "info",
  timestamp: new Date(),
  created_at: new Date()
});

print("Initialized log_samples collection.");
