db = db.getSiblingDB('enterprise');

const baseUrl = 'https://enterprise.atlassian.net/wiki';
const page = ({
  id,
  title,
  spaceKey,
  spaceName,
  version,
  when,
  by,
  parentId = null,
  labels,
  relevance,
  programArea,
  matchedOn
}) => ({
  _id: id,
  id,
  type: 'page',
  title,
  program_area: programArea,
  space: { key: spaceKey, name: spaceName },
  version: { number: version, when, by: { displayName: by } },
  _links: { webui: `${baseUrl}/spaces/${spaceKey}/pages/${id}` },
  ancestors: parentId ? [{ id: parentId }] : [],
  labels,
  relevance,
  matched_on: matchedOn,
  url: `${baseUrl}/spaces/${spaceKey}/pages/${id}`,
  last_updated: when,
  editor: by
});

const pages = [
  page({
    id: '100401',
    title: 'Runbook: SOX-404 Database Audit Logging Procedure',
    spaceKey: 'COMP',
    spaceName: 'Compliance-Runbooks',
    version: 7,
    when: '2026-05-18',
    by: 'Sultan DevOps',
    parentId: '100400',
    labels: ['sox-404', 'runbook'],
    relevance: 0.94,
    programArea: 'COMP',
    matchedOn: {
      finding_ids: ['finding-smoke-001'],
      epic_ids: ['epic-rds-001'],
      epic_keys: ['RDS-LOG-1'],
      work_item_ids: ['wi-rds-logging-01', 'wi-rds-verify-06'],
      ticket_refs: ['RDS-LOG-1', 'RDS-LOG-3'],
      keywords: ['audit logging', 'RDS'],
      users: ['Sultan DevOps'],
      projects: ['infra-terraform']
    }
  }),
  page({
    id: '100433',
    title: 'Epic Log: RDS Audit Logging — Evidence Index',
    spaceKey: 'COMP',
    spaceName: 'Compliance-Runbooks',
    version: 11,
    when: '2026-05-21',
    by: 'Sultan DevOps',
    parentId: '100400',
    labels: ['epic-log', 'evidence'],
    relevance: 0.97,
    programArea: 'COMP',
    matchedOn: {
      finding_ids: ['finding-smoke-001'],
      epic_ids: ['epic-rds-001'],
      epic_keys: ['RDS-LOG-1'],
      work_item_ids: ['wi-rds-logging-01', 'wi-rds-docs-05', 'wi-rds-verify-06'],
      ticket_refs: ['RDS-LOG-1', 'RDS-LOG-2', 'RDS-LOG-3'],
      keywords: ['evidence', 'PCI-DSS-10.2'],
      users: ['Sultan DevOps'],
      projects: ['infra-terraform']
    }
  }),
  page({
    id: '100412',
    title: 'CI/CD Secure Branch Scanning Policy & Compliance Standards',
    spaceKey: 'ARCH',
    spaceName: 'Architecture-RFCs',
    version: 3,
    when: '2026-05-20',
    by: 'Alex SecOps',
    labels: ['security', 'policy'],
    relevance: 0.88,
    programArea: 'ARCH',
    matchedOn: {
      finding_ids: ['finding-compliance-jira-01'],
      epic_ids: ['epic-control-01'],
      epic_keys: ['SEC-SCAN-101'],
      work_item_ids: ['wi-scan-gate-02', 'wi-scan-ruleset-07'],
      ticket_refs: ['SEC-SCAN-101', 'SEC-SCAN-102'],
      keywords: ['branch protection', 'secret scanning'],
      users: ['Alex SecOps'],
      projects: ['sec-gates']
    }
  }),
  page({
    id: '100420',
    title: 'AWS Certificate Rotation Playbook (ALB Pipeline)',
    spaceKey: 'SRE',
    spaceName: 'SRE-Guides',
    version: 5,
    when: '2026-05-21',
    by: 'Sarah SRE',
    labels: ['tls', 'playbook'],
    relevance: 0.81,
    programArea: 'SRE',
    matchedOn: {
      finding_ids: ['finding-stale-certs-02'],
      epic_ids: ['epic-certs-02'],
      epic_keys: ['OPS-CERT-202'],
      work_item_ids: ['wi-cert-rotate-03', 'wi-cert-observability-08'],
      ticket_refs: ['OPS-CERT-202', 'OPS-CERT-203'],
      keywords: ['certificate', 'rotation', 'ALB'],
      users: ['Sarah SRE'],
      projects: ['infra-k8s']
    }
  }),
  page({
    id: '100455',
    title: 'Stale IAM Exception Register & Owner Attestations',
    spaceKey: 'SEC',
    spaceName: 'Security-Operations',
    version: 4,
    when: '2026-05-22',
    by: 'Priya Morgan',
    labels: ['iam', 'attestation'],
    relevance: 0.86,
    programArea: 'SEC',
    matchedOn: {
      finding_ids: ['finding-unauth-access-03'],
      epic_ids: ['epic-access-03'],
      epic_keys: ['IAM-STALE-303'],
      work_item_ids: ['wi-iam-cleanup-04', 'wi-iam-attestation-09'],
      ticket_refs: ['IAM-STALE-303', 'IAM-STALE-304'],
      keywords: ['stale iam', 'attestation'],
      users: ['Priya Morgan'],
      projects: ['identity-ops']
    }
  }),
  page({
    id: '100460',
    title: 'Evidence Warehouse Lineage Map',
    spaceKey: 'DATA',
    spaceName: 'Data-Governance',
    version: 2,
    when: '2026-05-23',
    by: 'Umar Abdullah',
    labels: ['lineage', 'warehouse'],
    relevance: 0.9,
    programArea: 'DATA',
    matchedOn: {
      finding_ids: ['finding-smoke-001'],
      epic_ids: ['epic-data-01'],
      epic_keys: ['DATA-EVID-404'],
      work_item_ids: ['wi-data-lineage-10'],
      ticket_refs: ['DATA-EVID-404'],
      keywords: ['warehouse', 'lineage', 'audit exports'],
      users: ['Umar Abdullah'],
      projects: ['evidence-warehouse']
    }
  })
];

db.confluence_pages.deleteMany({});
db.confluence_pages.insertMany(pages);

print('Seeded confluence_pages collection with ' + pages.length + ' canonical pages.');
