"""Stage 32 fixture-backed enterprise LDAP directory connector."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

try:
    from .base import Connector
except ImportError:  # direct fixture round-trip imports outside package
    class Connector:  # type: ignore[no-redef]
        pass

DEFAULT_USERS_FILE = Path(__file__).resolve().parents[1] / "fixtures" / "ldap_users.json"


class LdapDirectory:
    """Small adapter shaped like a future python-ldap integration.

    Fixture mode returns `(dn, attributes)` tuples where attributes are lists of
    UTF-8 bytes, matching the important shape of `python-ldap` search results.
    Live mode is intentionally a no-network stub with TODO call sites.
    """

    def __init__(self, *, mode: str = "fixture", users_file: str | None = None, base_dn: str | None = None) -> None:
        self.mode = mode or "fixture"
        self.users_file = Path(users_file or DEFAULT_USERS_FILE)
        self.base_dn = base_dn or os.environ.get("LDAP_BASE_DN", "DC=lanGarland,DC=com")
        self._users: list[dict[str, Any]] | None = None

    def _load(self) -> list[dict[str, Any]]:
        if self.mode == "live":
            # TODO: use python-ldap initialize(), simple_bind_s(), search_s().
            raise RuntimeError("live LDAP mode is not implemented in this POC")
        if self._users is None:
            data = json.loads(self.users_file.read_text(encoding="utf-8"))
            self._users = [u for u in data.get("users", []) if isinstance(u, dict)]
        return self._users

    @staticmethod
    def _attr_bytes(user: dict[str, Any]) -> dict[str, list[bytes]]:
        attrs: dict[str, list[bytes]] = {}
        for key, value in user.items():
            vals = value if isinstance(value, list) else [value]
            attrs[key] = [str(v).encode("utf-8") for v in vals if v is not None and str(v) != ""]
        return attrs

    @staticmethod
    def _public(user: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in user.items() if "password" not in k.lower() and "secret" not in k.lower()}

    def search(self, query: str) -> list[tuple[str, dict[str, list[bytes]]]]:
        found = self.lookup_user(query)
        if not found:
            return []
        return [(found["distinguishedName"], self._attr_bytes(found))]

    def lookup_user(self, identity: str) -> dict[str, Any] | None:
        ident = str(identity or "").strip().lower()
        if not ident:
            return None
        for user in self._load():
            fields = [user.get("mail"), user.get("uid"), user.get("sAMAccountName"), user.get("userPrincipalName"), user.get("distinguishedName"), user.get("cn")]
            if ident in {str(f or "").lower() for f in fields}:
                return self._public(user)
        return None

    def lookup_groups(self, identity: str) -> list[str]:
        user = self.lookup_user(identity)
        return list(user.get("memberOf") or []) if user else []

    def lookup_manager(self, identity: str) -> dict[str, Any] | None:
        user = self.lookup_user(identity)
        if not user or not user.get("manager"):
            return None
        return self.lookup_user(str(user["manager"]))

    def lookup_hierarchy(self, identity: str) -> list[dict[str, Any]]:
        chain: list[dict[str, Any]] = []
        seen: set[str] = set()
        current = self.lookup_user(identity)
        while current and current.get("manager") and current["distinguishedName"] not in seen:
            seen.add(current["distinguishedName"])
            manager = self.lookup_user(str(current["manager"]))
            if not manager:
                break
            chain.append(manager)
            current = manager
        return chain

    def lookup_position(self, identity: str) -> dict[str, Any] | None:
        user = self.lookup_user(identity)
        if not user:
            return None
        return {"title": user.get("title"), "department": user.get("department"), "division": user.get("division"), "location": user.get("l")}


class LdapConnector:
    name = "ldap"

    def __init__(self, enabled: bool = False) -> None:
        # LDAP_ENABLED is the Stage-32 public env; CONN_LDAP_ENABLED also works via registry.
        self.enabled = enabled or os.environ.get("LDAP_ENABLED", "false").lower() == "true"
        self.mode = os.environ.get("LDAP_MODE", "fixture")
        self.app_id = os.environ.get("LDAP_APP_ID", "sglandsimple-directory-poc")
        self.bind_dn = os.environ.get("LDAP_BIND_DN", "")
        self.server_uri = os.environ.get("LDAP_SERVER_URI", "")
        self.directory = LdapDirectory(
            mode=self.mode,
            users_file=os.environ.get("LDAP_USERS_FILE") or str(DEFAULT_USERS_FILE),
            base_dn=os.environ.get("LDAP_BASE_DN"),
        )

    async def health(self) -> dict:
        if not self.enabled:
            return {"status": "disabled", "detail": "directory disabled"}
        if self.mode == "live" and not self.server_uri:
            return {"status": "degraded", "detail": "live mode requires LDAP_SERVER_URI"}
        try:
            count = len(self.directory._load())
            return {"status": "healthy", "mode": self.mode, "users": count, "app_id": self.app_id}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "detail": str(exc)}

    async def summary(self) -> dict:
        try:
            users = self.directory._load() if self.mode != "live" else []
        except Exception:
            users = []
        return {"status": "disabled" if not self.enabled else "healthy", "schema": "ldap_directory", "mode": self.mode, "users_count": len(users), "base_dn": self.directory.base_dn}

    def tools(self) -> list[dict]:
        return [
            {"name": "ldap_lookup_user", "description": "Read-only LDAP fixture lookup by email, uid, sAMAccountName, UPN, or DN.", "inputSchema": {"type": "object", "properties": {"identity": {"type": "string"}}, "required": ["identity"]}},
            {"name": "ldap_lookup_manager_chain", "description": "Read-only LDAP manager chain lookup for an identity.", "inputSchema": {"type": "object", "properties": {"identity": {"type": "string"}}, "required": ["identity"]}},
        ]

    @staticmethod
    def _envelope(payload: Any, is_error: bool = False) -> dict[str, Any]:
        return {"content": [{"type": "text", "text": json.dumps(payload, indent=2, default=str)}], "isError": is_error}

    async def dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            return self._envelope({"status": "disabled", "error": "directory disabled"})
        identity = str(args.get("identity") or "")
        if name == "ldap_lookup_user":
            user = self.directory.lookup_user(identity)
            return self._envelope({"found": bool(user), "user": user, "python_ldap_result": self.directory.search(identity) if user else []})
        if name == "ldap_lookup_manager_chain":
            user = self.directory.lookup_user(identity)
            chain = self.directory.lookup_hierarchy(identity)
            return self._envelope({"found": bool(user), "identity": identity, "user": user, "manager_chain": chain, "depth": len(chain)})
        return self._envelope({"error": f"Unknown tool: {name}"}, is_error=True)
