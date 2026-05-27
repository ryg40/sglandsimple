"""Stage 32 identity-driven hub enrichment."""

from __future__ import annotations

from typing import Any


def _team_from_group(group: str) -> str | None:
    marker = "CN=app-team-"
    if marker in group:
        return group.split(marker, 1)[1].split(",", 1)[0]
    return None


def infer_teams(user: dict[str, Any]) -> list[str]:
    teams: list[str] = []
    for group in user.get("memberOf") or []:
        team = _team_from_group(str(group))
        if team and team not in teams:
            teams.append(team)
    dept = str(user.get("department") or "").lower()
    if dept and dept not in teams:
        teams.append(dept)
    return teams


def user_summary(user: dict[str, Any] | None, chain: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    if not user:
        return None
    manager = chain[0] if chain else None
    return {
        "display_name": user.get("displayName"),
        "email": user.get("mail"),
        "uid": user.get("uid"),
        "title": user.get("title"),
        "department": user.get("department"),
        "division": user.get("division"),
        "location": user.get("l") or user.get("physicalDeliveryOfficeName"),
        "manager": manager and {"display_name": manager.get("displayName"), "email": manager.get("mail"), "title": manager.get("title")},
        "teams": infer_teams(user),
        "groups": user.get("memberOf") or [],
    }


def _source(status: str, summary: str, items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"status": status, "summary": summary, "items": items or []}


APP_ENV_BY_REPO = {
    "payments-api": {"application": "Payments API", "environment": "prod", "team": "payments"},
    "payments-worker": {"application": "Payments Worker", "environment": "stage", "team": "payments"},
    "infra-terraform": {"application": "Compliance Infrastructure", "environment": "prod", "team": "sre"},
    "sec-gates": {"application": "Security Gate Platform", "environment": "prod", "team": "security"},
    "infra-k8s": {"application": "Platform Kubernetes", "environment": "prod", "team": "sre"},
}


def _github_identities(user: dict[str, Any]) -> list[str]:
    values = [user.get("mail"), user.get("uid"), user.get("sAMAccountName"), user.get("userPrincipalName")]
    local = str(user.get("mail") or "").split("@", 1)[0]
    values.extend([local, local.replace(".", "-")])
    seen: set[str] = set(); out: list[str] = []
    for value in values:
        clean = str(value or "").strip()
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key); out.append(clean)
    return out


def _map_repo_to_application(repo: dict[str, Any], teams: list[str]) -> dict[str, Any]:
    name = str(repo.get("repo") or "")
    base = APP_ENV_BY_REPO.get(name)
    if base:
        confidence = 0.9 if base.get("team") in teams else 0.75
        return {**base, "confidence": confidence, "rationale": "matched internal app environment repo map"}
    tags = [str(t) for t in repo.get("tags") or []]
    app_tag = next((t.split(":", 1)[1] for t in tags if t.startswith("app:")), "")
    env_tag = next((t.split(":", 1)[1] for t in tags if t.startswith("env:")), "")
    if app_tag or env_tag:
        return {"application": app_tag or "unknown", "environment": env_tag or "unknown", "team": next((t for t in teams if t in name), "unknown"), "confidence": 0.55, "rationale": "derived from repo tags"}
    return {"application": "unknown", "environment": "unknown", "team": "unknown", "confidence": 0.0, "rationale": "no internal app environment mapping found"}


async def build_identity_enrichment(identity: str, *, ldap_connector: Any, connectors: dict[str, Any] | None = None) -> dict[str, Any]:
    connectors = connectors or {}
    if ldap_connector is None or not getattr(ldap_connector, "enabled", False):
        return {"identity": identity, "found": False, "status": "directory_disabled", "directory": None, "recent_activity": {}, "team_context": {}}
    user = ldap_connector.directory.lookup_user(identity)
    if not user:
        return {"identity": identity, "found": False, "status": "not_found", "directory": None, "recent_activity": {}, "team_context": {}}
    chain = ldap_connector.directory.lookup_hierarchy(identity)
    teams = infer_teams(user)
    activity: dict[str, Any] = {}
    team_context: dict[str, Any] = {}
    for name in ("servicenow", "github", "mongodb", "confluence"):
        conn = connectors.get(name)
        if conn is None:
            activity[name] = _source("disabled", f"{name} connector unavailable")
            continue
        try:
            summary = await conn.summary()
            status = str(summary.get("status") or "unknown")
            sample = summary.get("sample_data") if isinstance(summary.get("sample_data"), list) else []
            matches = []
            needles = [str(user.get("mail", "")).lower(), str(user.get("uid", "")).lower(), *[t.lower() for t in teams]]
            for row in sample[:100]:
                text = str(row).lower()
                if any(n and n in text for n in needles):
                    matches.append(row)
            activity[name] = _source("available" if matches else ("no_data" if status not in {"disabled", "error"} else status), f"{name} summary checked for user/team activity", matches[:5])
        except Exception as exc:  # noqa: BLE001
            activity[name] = _source("degraded", f"{type(exc).__name__}: {exc}")
    github_history = {"status": "disabled", "repos": [], "count": 0, "summary": "GitHub connector unavailable"}
    github = connectors.get("github")
    if github is not None:
        try:
            if hasattr(github, "user_history"):
                github_history = github.user_history(_github_identities(user))
            else:
                github_history = {"status": "no_data", "repos": [], "count": 0, "summary": "GitHub connector has no user history helper"}
            repos = []
            for repo in github_history.get("repos", []):
                repos.append({**repo, "application_mapping": _map_repo_to_application(repo, teams)})
            github_history["repos"] = repos
            github_history["summary"] = f"{len(repos)} repositories with commit/PR interactions"
        except Exception as exc:  # noqa: BLE001
            github_history = {"status": "degraded", "repos": [], "count": 0, "summary": f"{type(exc).__name__}: {exc}"}

    for team in teams:
        team_context[team] = {
            "confluence_query": f"{team} overview technical pages",
            "servicenow_assignment_group": team,
            "distribution_list": f"dl-{team}@lanGarland.com",
            "routing_hint": f"Route {team} requests to the {team} app-team workflow/context pack.",
        }
    return {
        "identity": identity,
        "found": True,
        "status": "ok",
        "directory": user_summary(user, chain),
        "manager_chain": [user_summary(m, []) for m in chain],
        "recent_activity": activity,
        "team_context": team_context,
        "github_history": github_history,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    if not payload.get("found"):
        return f"# Identity enrichment\n\n{payload.get('identity')} — {payload.get('status')}"
    directory = payload.get("directory") or {}
    return f"# Identity enrichment: {directory.get('display_name')}\n\n- {directory.get('title')} · {', '.join(directory.get('teams') or [])}"
