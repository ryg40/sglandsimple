"""Auth explanation surface — S19.agent.2.

Self-contained, pure module that answers "why does/doesn't user X have access
to capability/route Y?" using only:

  - ``auth_ldap.get_directory_adapter().lookup_user`` — minimal-attribute lookup
  - ``auth.groups_to_roles`` + ``auth.roles_to_capabilities`` — policy derivation
  - ``auth.ROLE_CAPABILITIES`` — role→capability matrix

**Privacy boundary** (docs/auth-rbac.md §Privacy boundary):
The returned dict contains ONLY ``username``, ``display_name``, ``groups``,
``roles``, ``capability``, ``granted``, ``reason``, and ``granting_roles``.
Passwords, full directory dumps, tokens, and any other attributes are NEVER
included.  This is enforced at the end of ``explain_access`` by filtering the
output dict to exactly the allowed keys.

**Architecture decision (S19.agent.1):**
This module ships as a self-contained pure function (option d — staged
combination).  It can later be exposed as an MCP tool or wrapped by an
auth-specialist agent without modifying this file.  No new deps, no network.
Fixture-backed for the POC; swapping to a real LDAP adapter only requires
changing the adapter returned by ``get_directory_adapter``.

CLI usage (admin smoke test)::

    python3 web/auth_explain.py <username> <capability_or_route>

    # Examples:
    python3 web/auth_explain.py simone.patel@lanGarland.com canApplyJira
    python3 web/auth_explain.py avery.stone@lanGarland.com canApplyJira
    python3 web/auth_explain.py unknown@lanGarland.com canRunWorkflow
    python3 web/auth_explain.py simone.patel@lanGarland.com /api/jira/apply
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Ensure the web/ directory is on sys.path so sibling modules resolve correctly
# when this file is executed directly (e.g. python3 web/auth_explain.py).
_WEB_DIR = str(Path(__file__).parent)
if _WEB_DIR not in sys.path:
    sys.path.insert(0, _WEB_DIR)

from auth import groups_to_roles, roles_to_capabilities, ROLE_CAPABILITIES  # type: ignore[import]
from auth_ldap import get_directory_adapter  # type: ignore[import]


# ---------------------------------------------------------------------------
# Route → capability mapping
# (mirrors docs/auth-rbac.md §Web API capability requirements)
# ---------------------------------------------------------------------------

#: Maps known API route patterns to the required capability string.
#: Only mutation routes carry an explicit capability; read/viewer routes are
#: listed as ``None`` (meaning "authenticated" is sufficient — any valid user).
#: Unknown routes fall back to a "require authentication" explanation.
ROUTE_CAPABILITY_MAP: dict[str, str | None] = {
    # Public (no auth required)
    "/healthz": None,
    "/api/me": None,
    # Viewer-level (authenticated only, no specific capability gate)
    "/api/overview": None,
    "/api/topology": None,
    "/api/architecture": None,
    "/api/connectors": None,
    "/api/audit/recent": None,
    "/api/sheet/collections": None,
    "/api/sheet/rows": None,
    "/api/wrangler/sample": None,
    "/api/wrangler/pipelines": None,
    "/api/jira/issues": None,
    "/api/docs/tree": None,
    "/api/docs/search": None,
    "/api/reports/download": None,
    # Capability-gated routes
    "/api/chat": "canReadChat",
    "/api/ask_data": "canReadChat",
    "/api/sheet/cell": "canEditData",
    "/api/sheet/row": "canEditData",
    "/api/sheet/nl": "canEditData",
    "/api/wrangler/run": "canEditData",
    "/api/wrangler/save": "canEditData",
    "/api/wrangler/suggest": "canEditData",
    "/api/workflow/run": "canRunWorkflow",
    "/api/jira/stage": "canValidateJira",
    "/api/jira/validate": "canValidateJira",
    "/api/jira/revert": "canApplyJira",
    "/api/jira/apply": "canApplyJira",
    "/api/docs": "canManageDocs",
    "/api/docs/sync": "canSyncDocs",
    "/api/docs/agent": "canSyncDocs",
}

# All known capability strings (kept in sync with auth.Capability.ALL).
_ALL_CAPABILITIES: frozenset[str] = frozenset({
    "canRunWorkflow",
    "canApplyJira",
    "canUpdateArcher",
    "canManageDocs",
    "canSyncDocs",
    "canEditArchitectureInventory",
    "canAdminAuth",
    "canEditData",
    "canValidateJira",
    "canReadChat",
})

# Allowed output keys — privacy boundary enforced at end of explain_access.
_ALLOWED_OUTPUT_KEYS: frozenset[str] = frozenset({
    "username",
    "display_name",
    "groups",
    "roles",
    "capability",
    "granted",
    "reason",
    "granting_roles",
})


def _resolve_capability(capability_or_route: str) -> tuple[str | None, str]:
    """Return (capability_string | None, explanation_target).

    If *capability_or_route* is a known capability string, return it directly.
    If it looks like a route (starts with ``/``), look it up in
    ``ROUTE_CAPABILITY_MAP``; routes mapped to ``None`` are viewer-level
    (authentication is sufficient, no extra capability gate).

    Returns a 2-tuple:
      - The capability string to check (or None for viewer-only routes).
      - A human-readable label for the target used in ``reason`` strings.
    """
    cap = capability_or_route.strip()

    # Direct capability name
    if cap in _ALL_CAPABILITIES:
        return cap, f"capability '{cap}'"

    # Route lookup
    if cap.startswith("/"):
        route_cap = ROUTE_CAPABILITY_MAP.get(cap)
        if cap in ROUTE_CAPABILITY_MAP:
            if route_cap is None:
                return None, f"route '{cap}' (viewer/authenticated access)"
            return route_cap, f"route '{cap}' (requires capability '{route_cap}')"
        # Unknown route — treat as requiring authentication, explain clearly.
        return "UNKNOWN_ROUTE", f"route '{cap}' (not in route map)"

    # Unknown string — treat as an unknown capability name.
    return "UNKNOWN_CAPABILITY", f"capability '{cap}' (unrecognised)"


def _roles_granting(capability: str) -> list[str]:
    """Return the list of role names that grant *capability*."""
    return [role for role, caps in ROLE_CAPABILITIES.items() if capability in caps]


def explain_access(username: str, capability_or_route: str) -> dict[str, Any]:
    """Explain why *username* does or does not have access to *capability_or_route*.

    Parameters
    ----------
    username:
        Login identity, typically a full email address
        (``firstname.lastname@lanGarland.com``).
    capability_or_route:
        Either a capability string (e.g. ``"canApplyJira"``) or a known API
        route (e.g. ``"/api/jira/apply"``).

    Returns
    -------
    dict
        Exactly the following keys (privacy boundary enforced):

        ``username``       — login name as looked up
        ``display_name``   — human-readable name from directory (or "Unknown")
        ``groups``         — list of group names the user belongs to
        ``roles``          — list of app roles derived from groups
        ``capability``     — the capability string being evaluated
                             (or None for viewer-only routes)
        ``granted``        — True if the user has the capability (or is authed
                             for viewer-only routes)
        ``reason``         — human-readable explanation sentence
        ``granting_roles`` — roles that would grant this capability (may be
                             empty for unknown/None capabilities)

    Never includes passwords, tokens, full directory dumps, or any attribute
    beyond the allowed keys listed above.
    """
    capability, target_label = _resolve_capability(capability_or_route)

    # Unknown route/capability: short-circuit with a clear explanation.
    if capability in ("UNKNOWN_ROUTE", "UNKNOWN_CAPABILITY"):
        result: dict[str, Any] = {
            "username": username,
            "display_name": "Unknown",
            "groups": [],
            "roles": [],
            "capability": capability_or_route,
            "granted": False,
            "reason": (
                f"Cannot evaluate: {target_label} is not a recognised capability "
                f"or route. No access decision can be made."
            ),
            "granting_roles": [],
        }
        return {k: result[k] for k in _ALLOWED_OUTPUT_KEYS}

    # Directory lookup — enforces minimal-attribute privacy contract.
    adapter = get_directory_adapter()
    info = adapter.lookup_user(username)

    if info is None:
        result = {
            "username": username,
            "display_name": "Unknown",
            "groups": [],
            "roles": [],
            "capability": capability,
            "granted": False,
            "reason": (
                f"User '{username}' was not found in the directory. "
                f"Access to {target_label} is denied."
            ),
            "granting_roles": _roles_granting(capability) if capability else [],
        }
        return {k: result[k] for k in _ALLOWED_OUTPUT_KEYS}

    # Derive roles and capabilities from groups.
    groups: list[str] = info["groups"]
    display_name: str = info["display_name"]
    roles: list[str] = groups_to_roles(groups)
    caps: set[str] = roles_to_capabilities(roles)

    # Viewer-only route (capability is None) — any authenticated user is granted.
    if capability is None:
        result = {
            "username": info["username"],
            "display_name": display_name,
            "groups": groups,
            "roles": roles,
            "capability": None,
            "granted": True,
            "reason": (
                f"Granted: {target_label} requires only authentication. "
                f"'{display_name}' is a recognised user with roles {roles}."
            ),
            "granting_roles": [],
        }
        return {k: result[k] for k in _ALLOWED_OUTPUT_KEYS}

    # Capability check.
    granted: bool = capability in caps
    granting_roles: list[str] = _roles_granting(capability)

    if granted:
        # Find which of the user's roles actually grant this capability.
        user_granting = [r for r in roles if r in granting_roles]
        group_detail = ", ".join(
            f"group '{g}'"
            for g in groups
            # Only mention groups that map to a granting role — omit noise.
            if any(
                groups_to_roles([g]) and set(groups_to_roles([g])).intersection(user_granting)
                for _ in [None]  # single-element loop for the local var
            )
        ) or ", ".join(f"group '{g}'" for g in groups)
        role_label = user_granting[0] if len(user_granting) == 1 else str(user_granting)
        reason = (
            f"Granted via role '{role_label}' ({group_detail}). "
            f"Effective roles: {roles}; capability '{capability}' is in the role's grant set."
        )
    else:
        reason = (
            f"Denied: capability '{capability}' requires one of roles {granting_roles}; "
            f"'{display_name}' has roles {roles}, which do not include any of those roles."
        )

    result = {
        "username": info["username"],
        "display_name": display_name,
        "groups": groups,
        "roles": roles,
        "capability": capability,
        "granted": granted,
        "reason": reason,
        "granting_roles": granting_roles,
    }

    # Privacy boundary: strip any key not in the allowed set.
    return {k: result[k] for k in _ALLOWED_OUTPUT_KEYS}


# ---------------------------------------------------------------------------
# CLI entry point — admin smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(
            "Usage: python3 web/auth_explain.py <username> <capability_or_route>\n"
            "\n"
            "Examples:\n"
            "  python3 web/auth_explain.py simone.patel@lanGarland.com canApplyJira\n"
            "  python3 web/auth_explain.py avery.stone@lanGarland.com canApplyJira\n"
            "  python3 web/auth_explain.py unknown@lanGarland.com canRunWorkflow\n"
            "  python3 web/auth_explain.py simone.patel@lanGarland.com /api/jira/apply\n",
            file=sys.stderr,
        )
        sys.exit(1)

    _username, _cap_or_route = sys.argv[1], sys.argv[2]
    _result = explain_access(_username, _cap_or_route)
    print(json.dumps(_result, indent=2, default=str))
