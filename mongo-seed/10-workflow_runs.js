db = db.getSiblingDB('enterprise');

// Empty schema doc so the collection exists
db.workflow_runs.deleteMany({});

db.workflow_runs.insertOne({
  _id: "run-placeholder",
  finding_id: "finding-smoke-001",
  epic_id: "epic-rds-001",
  step_index: 0,
  status: "completed",
  artifacts: {},
  dry_run: true,
  source: "workflow_init",
  created_at: new Date(),
  updated_at: new Date()
});

print("Initialized workflow_runs collection.");
