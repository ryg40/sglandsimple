// Seed the employees collection.
db = db.getSiblingDB("enterprise");

if (db.employees.countDocuments({}) > 0) {
  print("employees already seeded (" + db.employees.countDocuments({}) + " docs), skipping");
} else {
  const employees = [
    // Engineering — IC -> M1 -> M2 chain
    { _id: "emp-001", name: "Alice Nguyen",    dept: "Engineering", role: "Software Engineer",       hire_date: ISODate("2021-03-15"), manager_id: "emp-002", salary_band: "IC3", skills: ["python", "fastapi", "mongodb"] },
    { _id: "emp-002", name: "Bob Carter",      dept: "Engineering", role: "Engineering Manager",     hire_date: ISODate("2018-06-01"), manager_id: "emp-003", salary_band: "M1",  skills: ["leadership", "python", "go"] },
    { _id: "emp-003", name: "Diana Prince",    dept: "Engineering", role: "Director of Engineering", hire_date: ISODate("2015-09-12"), manager_id: null,       salary_band: "M2",  skills: ["strategy", "hiring"] },
    { _id: "emp-004", name: "Carlos Ramirez",  dept: "Engineering", role: "Senior Engineer",         hire_date: ISODate("2019-11-04"), manager_id: "emp-002", salary_band: "IC4", skills: ["rust", "kubernetes", "networking"] },
    { _id: "emp-005", name: "Eva Schultz",     dept: "Engineering", role: "Staff Engineer",          hire_date: ISODate("2017-02-22"), manager_id: "emp-002", salary_band: "IC5", skills: ["distributed-systems", "python", "design"] },
    { _id: "emp-006", name: "Frank Liu",       dept: "Engineering", role: "Software Engineer",       hire_date: ISODate("2022-08-08"), manager_id: "emp-002", salary_band: "IC2", skills: ["typescript", "react"] },
    { _id: "emp-007", name: "Grace Hopper II", dept: "Engineering", role: "Principal Engineer",      hire_date: ISODate("2016-01-10"), manager_id: "emp-003", salary_band: "IC6", skills: ["compilers", "python", "mentoring"] },

    // Sales
    { _id: "emp-010", name: "Hank Morrison",   dept: "Sales", role: "Account Executive",       hire_date: ISODate("2020-04-19"), manager_id: "emp-011", salary_band: "IC3", skills: ["negotiation", "enterprise-sales"] },
    { _id: "emp-011", name: "Iris Park",       dept: "Sales", role: "Sales Manager",           hire_date: ISODate("2017-07-30"), manager_id: "emp-012", salary_band: "M1",  skills: ["leadership", "forecasting"] },
    { _id: "emp-012", name: "Jamal Edwards",   dept: "Sales", role: "VP Sales",                hire_date: ISODate("2014-12-01"), manager_id: null,       salary_band: "M3",  skills: ["strategy", "enterprise"] },
    { _id: "emp-013", name: "Kira Tanaka",     dept: "Sales", role: "Account Executive",       hire_date: ISODate("2021-10-11"), manager_id: "emp-011", salary_band: "IC2", skills: ["smb", "demo"] },
    { _id: "emp-014", name: "Leon Bauer",      dept: "Sales", role: "Sales Engineer",          hire_date: ISODate("2019-05-17"), manager_id: "emp-011", salary_band: "IC4", skills: ["mongodb", "demo", "architecture"] },

    // Support
    { _id: "emp-020", name: "Mira Khan",       dept: "Support", role: "Support Engineer",       hire_date: ISODate("2022-02-14"), manager_id: "emp-021", salary_band: "IC2", skills: ["triage", "linux", "python"] },
    { _id: "emp-021", name: "Noah Bennett",    dept: "Support", role: "Support Manager",        hire_date: ISODate("2019-09-23"), manager_id: "emp-003", salary_band: "M1",  skills: ["leadership", "process"] },
    { _id: "emp-022", name: "Olivia Reyes",    dept: "Support", role: "Senior Support Engineer",hire_date: ISODate("2020-06-04"), manager_id: "emp-021", salary_band: "IC4", skills: ["mongodb", "k8s", "debugging"] },
    { _id: "emp-023", name: "Pavan Iyer",      dept: "Support", role: "Support Engineer",       hire_date: ISODate("2023-01-09"), manager_id: "emp-021", salary_band: "IC2", skills: ["python", "triage"] },

    // HR
    { _id: "emp-030", name: "Quinn Murphy",    dept: "HR", role: "HR Business Partner",       hire_date: ISODate("2018-11-19"), manager_id: "emp-031", salary_band: "IC4", skills: ["onboarding", "policy"] },
    { _id: "emp-031", name: "Rita Singh",      dept: "HR", role: "Head of People",            hire_date: ISODate("2016-05-02"), manager_id: null,       salary_band: "M2",  skills: ["strategy", "compensation"] },
    { _id: "emp-032", name: "Sam Goldberg",    dept: "HR", role: "Recruiter",                 hire_date: ISODate("2021-08-30"), manager_id: "emp-031", salary_band: "IC2", skills: ["sourcing", "interviewing"] },

    // Finance
    { _id: "emp-040", name: "Tara Williams",   dept: "Finance", role: "Financial Analyst",     hire_date: ISODate("2020-02-03"), manager_id: "emp-041", salary_band: "IC3", skills: ["excel", "forecasting"] },
    { _id: "emp-041", name: "Umar Abdullah",   dept: "Finance", role: "Finance Manager",       hire_date: ISODate("2017-10-15"), manager_id: "emp-042", salary_band: "M1",  skills: ["budgeting", "leadership"] },
    { _id: "emp-042", name: "Vera Costa",      dept: "Finance", role: "CFO",                   hire_date: ISODate("2013-03-22"), manager_id: null,       salary_band: "M3",  skills: ["strategy", "investor-relations"] },
    { _id: "emp-043", name: "Will Becker",     dept: "Finance", role: "Senior Accountant",     hire_date: ISODate("2019-07-08"), manager_id: "emp-041", salary_band: "IC4", skills: ["accounting", "audit"] },

    // A couple more engineers to round out
    { _id: "emp-008", name: "Xavi Domingo",    dept: "Engineering", role: "Software Engineer",     hire_date: ISODate("2023-04-17"), manager_id: "emp-002", salary_band: "IC2", skills: ["python", "fastapi", "testing"] },
    { _id: "emp-009", name: "Yumi Sato",       dept: "Engineering", role: "Senior Engineer",       hire_date: ISODate("2018-12-03"), manager_id: "emp-005", salary_band: "IC4", skills: ["python", "ml", "data"] },
    { _id: "emp-015", name: "Zane Foster",     dept: "Sales", role: "Sales Development Rep",  hire_date: ISODate("2023-06-12"), manager_id: "emp-011", salary_band: "IC1", skills: ["outbound", "prospecting"] },
    { _id: "emp-024", name: "Anya Volkov",     dept: "Support", role: "Support Engineer",       hire_date: ISODate("2022-11-28"), manager_id: "emp-021", salary_band: "IC2", skills: ["linux", "mongodb"] },
  ];

  db.employees.insertMany(employees);
  print("inserted " + employees.length + " employees");
}
