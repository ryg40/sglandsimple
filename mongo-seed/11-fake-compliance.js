db = db.getSiblingDB('enterprise');

// Insert a second fake compliance request (finding) and associated epic
const findingId1 = "finding-compliance-jira-01";
const epicId1 = "epic-control-01";

db.audit_findings.deleteMany({ _id: { $in: [findingId1, "finding-stale-certs-02", "finding-unauth-access-03"] } });
db.epics.deleteMany({ _id: { $in: [epicId1, "epic-certs-02", "epic-access-03"] } });

db.audit_findings.insertOne({
  _id: findingId1,
  source: "nessus",
  regulation: "PCI-DSS-v4",
  requirement: "Configure automated code scan alerts and vulnerability reporting inside pipeline repositories",
  severity: "critical",
  status: "open",
  epic_id: epicId1,
  created_at: new Date(),
  updated_at: new Date()
});

db.epics.insertOne({
  _id: epicId1,
  jira_key: "SEC-SCAN-101",
  title: "Vulnerability Scan & Branch Gate Integration",
  regulation_refs: ["PCI-DSS-v4", "NIST-800-53"],
  db_platform_combos: ["GitHub Actions", "GitLab CI"],
  priority: "critical",
  status: "todo",
  created_at: new Date(),
  updated_at: new Date()
});

db.audit_findings.insertOne({
  _id: "finding-stale-certs-02",
  source: "aws-config",
  regulation: "NIST-800-53",
  requirement: "Ensure SSL/TLS certificates on all public-facing application load balancers are rotated automatically every 90 days",
  severity: "high",
  status: "open",
  epic_id: "epic-certs-02",
  created_at: new Date(),
  updated_at: new Date()
});

db.epics.insertOne({
  _id: "epic-certs-02",
  jira_key: "OPS-CERT-202",
  title: "Automated ALB TLS Lifecycle Rotation",
  regulation_refs: ["NIST-800-53", "SOX-404"],
  db_platform_combos: ["AWS ACM", "Let's Encrypt"],
  priority: "high",
  status: "todo",
  created_at: new Date(),
  updated_at: new Date()
});

db.audit_findings.insertOne({
  _id: "finding-unauth-access-03",
  source: "guardduty",
  regulation: "SOC2-CC6.1",
  requirement: "Revoke production login credentials for stale IAM users and automate termination notifications on Slack/Teams",
  severity: "medium",
  status: "open",
  epic_id: "epic-access-03",
  created_at: new Date(),
  updated_at: new Date()
});

db.epics.insertOne({
  _id: "epic-access-03",
  jira_key: "IAM-STALE-303",
  title: "Stale IAM User Cleanup & Alerts",
  regulation_refs: ["SOC2-CC6.1", "ISO-27001"],
  db_platform_combos: ["AWS IAM", "Okta"],
  priority: "medium",
  status: "todo",
  created_at: new Date(),
  updated_at: new Date()
});

print("Seeded additional mock compliance findings and target epics for multi-view testing.");
