db = db.getSiblingDB('enterprise');

// Stage 11: real PR rows. At least one open PR carries a failing check so the
// "Blocked PR" attention rule renders; another is stalled (no update in >7d).
db.pr_records.deleteMany({});

const DAY = 24 * 60 * 60 * 1000;
const now = Date.now();
const at = (offset) => new Date(now + offset * DAY);

db.pr_records.insertMany([
  {
    _id: "pr-rds-logging-501",
    work_item_id: "wi-rds-logging-01",
    epic_id: "epic-rds-001",
    pr_number: 501,
    title: "Enable RDS audit logging",
    branch: "feature/rds-audit-logging",
    state: "open",
    status: "open",
    url: "https://github.com/org/repo/pull/501",
    checks: [
      { name: "build", status: "success" },
      { name: "security-scan", status: "failure" }   // blocked PR
    ],
    created_at: at(-4),
    updated_at: at(-1)
  },
  {
    _id: "pr-scan-gate-502",
    work_item_id: "wi-scan-gate-02",
    epic_id: "epic-control-01",
    pr_number: 502,
    title: "Add vulnerability scan gate to CI",
    branch: "feature/scan-gate",
    state: "open",
    status: "open",
    url: "https://github.com/org/repo/pull/502",
    checks: [
      { name: "build", status: "success" },
      { name: "lint", status: "success" }
    ],
    created_at: at(-20),
    updated_at: at(-11)   // stalled
  },
  {
    _id: "pr-cert-rotate-503",
    work_item_id: "wi-cert-rotate-03",
    epic_id: "epic-certs-02",
    pr_number: 503,
    title: "Automate ALB TLS rotation",
    branch: "feature/alb-tls-rotate",
    state: "merged",
    status: "merged",
    url: "https://github.com/org/repo/pull/503",
    checks: [
      { name: "build", status: "success" }
    ],
    created_at: at(-9),
    updated_at: at(-2)
  }
]);

print("Seeded pr_records collection with " + db.pr_records.countDocuments({}) + " rows.");
