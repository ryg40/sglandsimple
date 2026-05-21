db = db.getSiblingDB("enterprise");

const depts = ["Engineering", "Sales", "Support", "HR", "Finance", "Legal", "Marketing", "SRE", "Security"];
const roles = {
  "Engineering": ["Software Engineer", "Senior Engineer", "Staff Engineer", "Principal Engineer", "Engineering Manager"],
  "Sales": ["Account Executive", "Sales Manager", "VP Sales", "Sales Engineer"],
  "Support": ["Support Engineer", "Support Manager", "Senior Support Engineer"],
  "HR": ["HR Business Partner", "Head of People", "Recruiter"],
  "Finance": ["Financial Analyst", "Finance Manager", "CFO", "Senior Accountant"],
  "Legal": ["Compliance Counsel", "Legal Specialist", "General Counsel"],
  "Marketing": ["Marketing Associate", "Marketing Manager", "Director of Growth"],
  "SRE": ["SRE Engineer", "Senior SRE", "SRE Manager"],
  "Security": ["Security Engineer", "SecOps Lead", "CISO"]
};
const skillList = ["python", "fastapi", "mongodb", "react", "typescript", "kubernetes", "leadership", "excel", "negotiation", "scrum", "go", "rust", "aws", "security"];
const firstNames = ["James", "Mary", "John", "Patricia", "Robert", "Jennifer", "Michael", "Linda", "William", "Elizabeth", "David", "Barbara", "Richard", "Susan", "Joseph", "Jessica", "Thomas", "Sarah", "Charles", "Karen"];
const lastNames = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin"];

// Helper to pad numbers
function pad(num, size) {
  var s = "000000000" + num;
  return s.substr(s.length-size);
}

// 1. Scale employees
const empCount = db.employees.countDocuments({});
if (empCount < 200) {
  const existing = db.employees.find().toArray();
  const additional = [];
  
  for (let i = empCount + 1; i <= 270; i++) {
    const fn = firstNames[Math.floor(Math.random() * firstNames.length)];
    const ln = lastNames[Math.floor(Math.random() * lastNames.length)];
    const dept = depts[Math.random() < 0.4 ? 0 : Math.floor(Math.random() * depts.length)];
    const roleOpts = roles[dept] || ["Analyst"];
    const role = roleOpts[Math.floor(Math.random() * roleOpts.length)];
    
    let manager_id = "emp-003";
    const possibleManagers = existing.concat(additional).filter(function(e) {
      return e.dept === dept && (e.role.indexOf("Manager") > -1 || e.role.indexOf("Director") > -1 || e.role.indexOf("VP") > -1 || e.role.indexOf("CFO") > -1 || e.role.indexOf("CISO") > -1 || e.role.indexOf("Lead") > -1);
    });
    if (possibleManagers.length > 0) {
      manager_id = possibleManagers[Math.floor(Math.random() * possibleManagers.length)]._id;
    }

    const bandNum = (role.indexOf("Manager") > -1) ? "M1" : (role.indexOf("Director") > -1) ? "M2" : "IC" + (2 + Math.floor(Math.random() * 4));
    
    const empSkills = [];
    const skillCount = 2 + Math.floor(Math.random() * 4);
    while (empSkills.length < skillCount) {
      const sk = skillList[Math.floor(Math.random() * skillList.length)];
      if (empSkills.indexOf(sk) === -1) empSkills.push(sk);
    }

    additional.push({
      _id: "emp-" + pad(i, 3),
      name: fn + " " + ln,
      dept: dept,
      role: role,
      hire_date: new Date(new Date().getTime() - Math.random() * 1000 * 60 * 60 * 24 * 365 * 5),
      manager_id: manager_id,
      salary_band: bandNum,
      skills: empSkills
    });
  }
  db.employees.insertMany(additional);
  print("Scaled employees to: " + db.employees.countDocuments({}));
} else {
  print("employees already scaled (" + empCount + ")");
}

// 2. Scale tickets
const tktCount = db.tickets.countDocuments({});
if (tktCount < 300) {
  const adTkts = [];
  const subjects = ["Slow query response", "Access authorization failure", "Backup replication lag too high", "Typo correction requested", "Certificate renewal prompt", "Rate limiter tweak needed", "Onboarding links broken", "Kubernetes cluster configuration upgrade", "Vulnerability alert flagged", "API load balancing spike", "Invoice details missing", "New repository compliance setup"];
  const detailedtext = "Automated simulated compliance tracing event ticket triggered by system scanners. High urgency logs verify compliance status controls on staging lanes are in degraded performance bounds. Action is required for standard verification review.";
  const tags = ["sec", "infra", "auth", "billing", "docs", "meeting", "performance", "testing", "mongodb", "k8s"];
  const states = ["open", "in_progress", "resolved", "closed"];
  const priorities = ["p0", "p1", "p2", "p3"];

  for (let i = tktCount + 1; i <= 400; i++) {
    const subj = subjects[Math.floor(Math.random() * subjects.length)];
    const chosenAssignee = "emp-" + pad(1 + Math.floor(Math.random() * 25), 3);
    const status = states[Math.floor(Math.random() * states.length)];
    const priority = priorities[Math.floor(Math.random() * priorities.length)];
    const numTags = 1 + Math.floor(Math.random() * 3);
    const itemTags = [];
    while (itemTags.length < numTags) {
      const t = tags[Math.floor(Math.random() * tags.length)];
      if (itemTags.indexOf(t) === -1) itemTags.push(t);
    }

    adTkts.push({
      _id: "tkt-" + pad(i, 3),
      title: subj + " (" + i + ")",
      body: detailedtext,
      status: status,
      priority: priority,
      assignee_id: chosenAssignee,
      created_at: new Date(new Date().getTime() - Math.random() * 1000 * 60 * 60 * 24 * 30),
      tags: itemTags
    });
  }
  db.tickets.insertMany(adTkts);
  print("Scaled tickets to: " + db.tickets.countDocuments({}));
} else {
  print("tickets already scaled (" + tktCount + ")");
}

// 3. Scale documents
const docsCount = db.documents.countDocuments({});
if (docsCount < 150) {
  const adDocs = [];
  const docTitles = ["Onboarding Process Book", "Developer Laptop Setup instructions", "SAML SSO Policy Guidelines", "Disaster Recovery Drill Procedures", "Expense Report Submission Guidelines", "GDPR Subject Access Request Runbook", "MongoDB Optimization Strategy", "API Gateway Performance Benchmarks", "AWS Secret Key Rotation Steps", "Continuous Integration Flakiness Guidelines", "Quarterly Budget Forecast Model", "Security Checklist Questionnaire for Prospects"];
  const spaces = ["Support", "Engineering", "HR", "Sales", "Finance", "SRE", "Security"];

  for (let i = docsCount + 1; i <= 200; i++) {
    const title = docTitles[Math.floor(Math.random() * docTitles.length)];
    const author = "emp-" + pad(1 + Math.floor(Math.random() * 25), 3);
    const space = spaces[Math.floor(Math.random() * spaces.length)];

    adDocs.push({
      _id: "doc-" + pad(i, 3),
      title: title + " v" + (1 + Math.floor(Math.random() * 5)),
      body: "This secure compliance document record is published for internal standard policy guidance. All personnel are instructed to review standard operating controls inside the audit dashboard regularly.",
      author_id: author,
      space: space,
      created_at: new Date(new Date().getTime() - Math.random() * 1000 * 60 * 60 * 24 * 180),
      updated_at: new Date()
    });
  }
  db.documents.insertMany(adDocs);
  print("Scaled documents to: " + db.documents.countDocuments({}));
} else {
  print("documents already scaled (" + docsCount + ")");
}
