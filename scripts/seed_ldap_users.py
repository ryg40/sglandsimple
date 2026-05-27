#!/usr/bin/env python3
"""Generate the Stage 32 fake enterprise LDAP fixture."""

from __future__ import annotations

import json
from pathlib import Path

BASE_DN = "DC=lanGarland,DC=com"
OUT = Path(__file__).resolve().parents[1] / "mcp" / "fixtures" / "ldap_users.json"
TEAMS = ["payments", "platform", "security", "data", "sre", "risk", "audit", "identity", "network", "apps"]
FIRST = ["Maya", "Alex", "Simone", "Avery", "Jordan", "Taylor", "Riley", "Morgan", "Casey", "Jamie", "Priya", "Noah", "Emma", "Liam", "Olivia", "Ethan", "Sophia", "Mason", "Isabella", "Lucas"]
LAST = ["Chen", "Patel", "Stone", "Rivera", "Nguyen", "Garcia", "Brown", "Davis", "Miller", "Wilson", "Moore", "Taylor", "Anderson", "Thomas", "Jackson", "White", "Harris", "Martin", "Lee", "Clark"]
TITLES = ["Engineer", "Senior Engineer", "Staff Engineer", "Analyst", "Product Owner", "Scrum Master", "Architect", "Manager"]


def dn(uid: str, team: str) -> str:
    return f"CN={uid},OU={team.title()},OU=People,{BASE_DN}"


def group_dn(name: str, ou: str = "Groups") -> str:
    return f"CN={name},OU={ou},{BASE_DN}"


def main() -> None:
    users: list[dict] = []
    managers: dict[str, str] = {}
    for ti, team in enumerate(TEAMS):
        director_uid = f"{team}.director"
        manager_uid = f"{team}.manager"
        managers[team] = manager_uid
        for uid, title, mgr in [
            (director_uid, f"Director, {team.title()}", "enterprise.vp"),
            (manager_uid, f"Manager, {team.title()}", director_uid),
        ]:
            mail = f"{uid}@lanGarland.com"
            users.append({
                "cn": uid,
                "displayName": uid.replace('.', ' ').title(),
                "givenName": uid.split('.')[0].title(),
                "sn": uid.split('.')[-1].title(),
                "mail": mail,
                "sAMAccountName": uid,
                "uid": uid,
                "userPrincipalName": mail,
                "title": title,
                "department": team.title(),
                "division": "Technology Risk" if team in {"risk", "audit", "security"} else "Engineering",
                "manager": dn(mgr, team) if mgr != "enterprise.vp" else f"CN=enterprise.vp,OU=Executives,OU=People,{BASE_DN}",
                "directReports": [],
                "memberOf": [group_dn(f"app-team-{team}"), group_dn(f"dl-{team}", "Distribution Lists"), group_dn("sg-compliance-hub-users")],
                "telephoneNumber": f"+1-555-{ti:02d}-{len(users):04d}",
                "physicalDeliveryOfficeName": ["NYC", "ATL", "DFW", "SFO", "SEA"][ti % 5],
                "l": ["New York", "Atlanta", "Dallas", "San Francisco", "Seattle"][ti % 5],
                "employeeID": f"E{100000 + len(users)}",
                "employeeType": "employee",
                "distinguishedName": dn(uid, team) if "director" not in uid else dn(uid, team),
            })
    # executive root
    users.insert(0, {
        "cn": "enterprise.vp", "displayName": "Enterprise Vp", "givenName": "Enterprise", "sn": "Vp",
        "mail": "enterprise.vp@lanGarland.com", "sAMAccountName": "enterprise.vp", "uid": "enterprise.vp",
        "userPrincipalName": "enterprise.vp@lanGarland.com", "title": "VP, Enterprise Technology", "department": "Technology", "division": "Engineering",
        "manager": "", "directReports": [], "memberOf": [group_dn("sg-compliance-hub-users"), group_dn("dl-leadership", "Distribution Lists")],
        "telephoneNumber": "+1-555-00-0000", "physicalDeliveryOfficeName": "NYC", "l": "New York", "employeeID": "E100000", "employeeType": "employee",
        "distinguishedName": f"CN=enterprise.vp,OU=Executives,OU=People,{BASE_DN}",
    })
    # 179 contributors + named users to total 200
    named = [("maya", "chen", "payments"), ("alex", "secops", "security"), ("simone", "patel", "risk"), ("avery", "stone", "platform")]
    entries = named[:]
    idx = 0
    while len(entries) < 179:
        first = FIRST[idx % len(FIRST)].lower(); last = LAST[(idx * 3) % len(LAST)].lower(); team = TEAMS[idx % len(TEAMS)]
        entries.append((first, f"{last}{idx}", team)); idx += 1
    for i, (first, last, team) in enumerate(entries):
        uid = f"{first}.{last}"
        mail = f"{uid}@lanGarland.com"
        attrs = {
            "cn": uid, "displayName": f"{first.title()} {last.title()}", "givenName": first.title(), "sn": last.title(),
            "mail": mail, "sAMAccountName": uid, "uid": uid, "userPrincipalName": mail,
            "title": TITLES[i % len(TITLES)], "department": team.title(), "division": "Technology Risk" if team in {"risk", "audit", "security"} else "Engineering",
            "manager": dn(managers[team], team), "directReports": [],
            "memberOf": [group_dn(f"app-team-{team}"), group_dn(f"dl-{team}", "Distribution Lists"), group_dn("sg-compliance-hub-users")],
            "telephoneNumber": f"+1-555-{TEAMS.index(team):02d}-{i:04d}", "physicalDeliveryOfficeName": ["NYC", "ATL", "DFW", "SFO", "SEA"][i % 5],
            "l": ["New York", "Atlanta", "Dallas", "San Francisco", "Seattle"][i % 5], "employeeID": f"E{100000 + len(users)}", "employeeType": "employee",
            "distinguishedName": dn(uid, team),
        }
        users.append(attrs)
    by_dn = {u["distinguishedName"]: u for u in users}
    for u in users:
        mgr = u.get("manager")
        if mgr in by_dn:
            by_dn[mgr]["directReports"].append(u["distinguishedName"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"base_dn": BASE_DN, "users": users}, indent=2), encoding="utf-8")
    print(f"wrote {len(users)} users to {OUT}")


if __name__ == "__main__":
    main()
