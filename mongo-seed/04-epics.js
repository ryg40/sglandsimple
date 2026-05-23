db = db.getSiblingDB('enterprise');

const epics = [
  {
    _id: 'epic-rds-001',
    jira_key: 'RDS-LOG-1',
    epic_key: 'RDS-LOG-1',
    title: 'RDS Audit Logging',
    program_area: 'COMP',
    finding_id: 'finding-smoke-001',
    finding_ids: ['finding-smoke-001'],
    ticket_refs: ['RDS-LOG-1', 'RDS-LOG-2', 'RDS-LOG-3'],
    regulation_refs: ['SOX-404', 'PCI-DSS-10.2'],
    db_platform_combos: ['RDS MySQL', 'RDS PostgreSQL', 'RDS MariaDB'],
    priority: 'high',
    status: 'in_progress',
    created_at: new Date(),
    updated_at: new Date()
  },
  {
    _id: 'epic-data-01',
    jira_key: 'DATA-EVID-404',
    epic_key: 'DATA-EVID-404',
    title: 'Evidence Warehouse Lineage & Coverage',
    program_area: 'DATA',
    finding_id: 'finding-smoke-001',
    finding_ids: ['finding-smoke-001'],
    ticket_refs: ['DATA-EVID-404'],
    regulation_refs: ['SOX-404', 'SOC2-CC7.2'],
    db_platform_combos: ['MongoDB', 'Snowflake'],
    priority: 'medium',
    status: 'todo',
    created_at: new Date(),
    updated_at: new Date()
  }
];

db.epics.deleteMany({ _id: { $in: epics.map((epic) => epic._id) } });
db.epics.insertMany(epics);

print('Seeded epics collection with ' + epics.length + ' canonical epic rows.');
