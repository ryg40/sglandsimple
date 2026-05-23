db = db.getSiblingDB('enterprise');

// Stage 11: real work-item rows with a spread of due dates and updated_at so the
// Overview attention rules (due-soon / overdue / stalled) have data to fire on.
db.work_items.deleteMany({});

const DAY = 24 * 60 * 60 * 1000;
const now = Date.now();
const at = (offset) => new Date(now + offset * DAY); // offset in days (negative = past)

db.work_items.insertMany([
  {
    _id: 'wi-rds-logging-01',
    finding_id: 'finding-smoke-001',
    epic_id: 'epic-rds-001',
    epic_key: 'RDS-LOG-1',
    jira_key: 'RDS-LOG-1',
    ticket_ref: 'RDS-LOG-1',
    program_area: 'COMP',
    title: 'Enable RDS audit logging via parameter group',
    type: 'implementation',
    status: 'in_progress',
    priority: 'high',
    due_date: at(5),          // due soon
    created_at: at(-20),
    updated_at: at(-1)        // fresh
  },
  {
    _id: 'wi-scan-gate-02',
    finding_id: 'finding-compliance-jira-01',
    epic_id: 'epic-control-01',
    epic_key: 'SEC-SCAN-101',
    jira_key: 'SEC-SCAN-101',
    ticket_ref: 'SEC-SCAN-101',
    program_area: 'ARCH',
    title: 'Wire vulnerability scan gate into CI',
    type: 'implementation',
    status: 'in_progress',
    priority: 'critical',
    due_date: at(-3),         // overdue
    created_at: at(-30),
    updated_at: at(-10)       // stalled (no update in >7d)
  },
  {
    _id: 'wi-cert-rotate-03',
    finding_id: 'finding-stale-certs-02',
    epic_id: 'epic-certs-02',
    epic_key: 'OPS-CERT-202',
    jira_key: 'OPS-CERT-202',
    ticket_ref: 'OPS-CERT-202',
    program_area: 'SRE',
    title: 'Automate ALB TLS certificate rotation',
    type: 'implementation',
    status: 'todo',
    priority: 'high',
    due_date: at(12),         // due soon (within 14d)
    created_at: at(-15),
    updated_at: at(-2)
  },
  {
    _id: 'wi-iam-cleanup-04',
    finding_id: 'finding-unauth-access-03',
    epic_id: 'epic-access-03',
    epic_key: 'IAM-STALE-303',
    jira_key: 'IAM-STALE-303',
    ticket_ref: 'IAM-STALE-303',
    program_area: 'SEC',
    title: 'Revoke stale IAM users + Slack notifications',
    type: 'implementation',
    status: 'in_progress',
    priority: 'medium',
    due_date: at(40),         // comfortably future
    created_at: at(-12),
    updated_at: at(-9)        // stalled
  },
  {
    _id: 'wi-rds-docs-05',
    finding_id: 'finding-smoke-001',
    epic_id: 'epic-rds-001',
    epic_key: 'RDS-LOG-1',
    jira_key: 'RDS-LOG-2',
    ticket_ref: 'RDS-LOG-2',
    program_area: 'COMP',
    title: 'Document RDS logging runbook',
    type: 'documentation',
    status: 'done',
    priority: 'low',
    due_date: at(-1),         // past but done -> should NOT alert
    created_at: at(-25),
    updated_at: at(-1)
  },
  {
    _id: 'wi-rds-verify-06',
    finding_id: 'finding-smoke-001',
    epic_id: 'epic-rds-001',
    epic_key: 'RDS-LOG-1',
    jira_key: 'RDS-LOG-3',
    ticket_ref: 'RDS-LOG-3',
    program_area: 'COMP',
    title: 'Verify pgAudit coverage before evidence export',
    type: 'validation',
    status: 'blocked',
    priority: 'high',
    due_date: at(21),
    created_at: at(-11),
    updated_at: at(-9)
  },
  {
    _id: 'wi-scan-ruleset-07',
    finding_id: 'finding-compliance-jira-01',
    epic_id: 'epic-control-01',
    epic_key: 'SEC-SCAN-101',
    jira_key: 'SEC-SCAN-102',
    ticket_ref: 'SEC-SCAN-102',
    program_area: 'ARCH',
    title: 'Roll out repo rulesets for scan-gate program',
    type: 'implementation',
    status: 'todo',
    priority: 'high',
    due_date: at(24),
    created_at: at(-10),
    updated_at: at(-3)
  },
  {
    _id: 'wi-cert-observability-08',
    finding_id: 'finding-stale-certs-02',
    epic_id: 'epic-certs-02',
    epic_key: 'OPS-CERT-202',
    jira_key: 'OPS-CERT-203',
    ticket_ref: 'OPS-CERT-203',
    program_area: 'SRE',
    title: 'Add ALB certificate expiry evidence stream',
    type: 'observability',
    status: 'in_progress',
    priority: 'medium',
    due_date: at(22),
    created_at: at(-16),
    updated_at: at(-8)
  },
  {
    _id: 'wi-iam-attestation-09',
    finding_id: 'finding-unauth-access-03',
    epic_id: 'epic-access-03',
    epic_key: 'IAM-STALE-303',
    jira_key: 'IAM-STALE-304',
    ticket_ref: 'IAM-STALE-304',
    program_area: 'SEC',
    title: 'Collect stale-IAM owner attestations',
    type: 'governance',
    status: 'blocked',
    priority: 'medium',
    due_date: at(35),
    created_at: at(-18),
    updated_at: at(-8)
  },
  {
    _id: 'wi-data-lineage-10',
    finding_id: 'finding-smoke-001',
    epic_id: 'epic-data-01',
    epic_key: 'DATA-EVID-404',
    jira_key: 'DATA-EVID-404',
    ticket_ref: 'DATA-EVID-404',
    program_area: 'DATA',
    title: 'Map evidence warehouse lineage for audit exports',
    type: 'data',
    status: 'todo',
    priority: 'high',
    due_date: at(28),
    created_at: at(-14),
    updated_at: at(-4)
  }
]);

print('Seeded work_items collection with ' + db.work_items.countDocuments({}) + ' rows.');
