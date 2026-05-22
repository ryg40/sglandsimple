"""Stage-19 auth model and configuration for the web service.

This module contains:
  - Pure, unit-testable data structures and derivation functions (Role,
    Capability, AuthConfig, UserContext, build_user_context, …).
  - Identity resolution: resolve_user / require_user / require_capability.
  - A small in-memory cache for the Basic Auth users file.

See docs/auth-rbac.md for the authoritative policy.

Downstream tasks (not yet wired):
  S19.backend.2 — /api/me endpoint
  S19.backend.3 — per-route capability guards
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Final

# FastAPI is imported lazily (inside functions) so that auth.py remains
# importable in plain Python contexts (auth_seed.py, tests, py_compile) even
# when the fastapi package is not installed on the host.
if TYPE_CHECKING:
    from fastapi import HTTPException, Request  # noqa: F401 (type hints only)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

class Role:
    """String constants for application roles (intentionally not an enum so
    they round-trip cleanly through JSON without extra serialisation)."""

    VIEWER: Final = "viewer"
    APP_USER: Final = "app_user"
    AUDIT_USER: Final = "audit_user"
    ADMIN: Final = "admin"

    ALL: Final = (VIEWER, APP_USER, AUDIT_USER, ADMIN)


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------

class Capability:
    """String constants for individual capability grants.

    Names match docs/auth-rbac.md exactly where given; extras fill in gaps
    implied by the capability matrix.
    """

    # Workflow / connector mutations
    CAN_RUN_WORKFLOW: Final = "canRunWorkflow"
    CAN_APPLY_JIRA: Final = "canApplyJira"
    CAN_UPDATE_ARCHER: Final = "canUpdateArcher"

    # Docs / knowledge base
    CAN_MANAGE_DOCS: Final = "canManageDocs"
    CAN_SYNC_DOCS: Final = "canSyncDocs"            # Confluence push (admin only)

    # Architecture inventory
    CAN_EDIT_ARCHITECTURE_INVENTORY: Final = "canEditArchitectureInventory"

    # Auth/admin diagnostics
    CAN_ADMIN_AUTH: Final = "canAdminAuth"

    # Data access / editing (implied by matrix rows "Edit sheet/data records"
    # and "Wrangler / analytics")
    CAN_EDIT_DATA: Final = "canEditData"            # sheet/wrangler write

    # Jira validate (audit users may validate/comment but not apply)
    CAN_VALIDATE_JIRA: Final = "canValidateJira"

    # Read-level access to chat / Ask Data
    CAN_READ_CHAT: Final = "canReadChat"

    # All capability values as a frozenset, useful for validation
    ALL: Final = frozenset({
        CAN_RUN_WORKFLOW,
        CAN_APPLY_JIRA,
        CAN_UPDATE_ARCHER,
        CAN_MANAGE_DOCS,
        CAN_SYNC_DOCS,
        CAN_EDIT_ARCHITECTURE_INVENTORY,
        CAN_ADMIN_AUTH,
        CAN_EDIT_DATA,
        CAN_VALIDATE_JIRA,
        CAN_READ_CHAT,
    })


# ---------------------------------------------------------------------------
# Config (read from env at module load — replaceable in tests by patching os.environ)
# ---------------------------------------------------------------------------

def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _env_bool(key: str, default: bool = False) -> bool:
    return _env(key, "true" if default else "false").lower() in ("1", "true", "yes")


class AuthConfig:
    """Snapshot of AUTH_* env vars.  Constructed once at module level; tests
    can call AuthConfig() again after patching os.environ to get a fresh copy.
    """

    def __init__(self) -> None:
        # Auth mode: sso | basic | trusted_network | headers | ldap | disabled
        self.auth_mode: str = _env("AUTH_MODE", "basic")

        # Group names — config values, never hardcoded policy literals
        self.all_users_group: str = _env("AUTH_ALL_USERS_GROUP", "sg_all_users")
        self.admin_group: str = _env("AUTH_ADMIN_GROUP", "sg_sec_admin")
        self.app_user_group: str = _env("AUTH_APP_USER_GROUP", "sg_app_user")
        self.audit_user_group: str = _env("AUTH_AUDIT_USER_GROUP", "sg_audit_users")

        # Trusted proxy / SSO headers
        self.trusted_header_user: str = _env("AUTH_TRUSTED_HEADER_USER", "X-Forwarded-User")
        self.trusted_header_groups: str = _env("AUTH_TRUSTED_HEADER_GROUPS", "X-Forwarded-Groups")

        # SSO guardrail
        self.sso_required: bool = _env_bool("AUTH_SSO_REQUIRED", False)

        # Basic Auth
        self.basic_users_file: str = _env("AUTH_BASIC_USERS_FILE", "/data/auth/users.json")
        self.basic_seed_password: str = _env("AUTH_BASIC_SEED_PASSWORD", "")

        # Dev/test headers (must be off in production)
        self.dev_headers_enabled: bool = _env_bool("AUTH_DEV_HEADERS_ENABLED", False)

        # LDAP (future)
        self.ldap_url: str = _env("AUTH_LDAP_URL", "")
        self.ldap_base_dn: str = _env("AUTH_LDAP_BASE_DN", "")
        self.ldap_bind_secret_file: str = _env("AUTH_LDAP_BIND_SECRET_FILE", "")

        # Caching
        self.cache_ttl_seconds: int = int(_env("AUTH_CACHE_TTL_SECONDS", "300") or "300")

    # Derived: group → role mapping as a dict, built from config values
    def group_role_map(self) -> dict[str, str]:
        """Return a mapping from *configured* group name to Role constant.

        Built fresh from self so it always reflects the current config values.
        The all_users_group maps to viewer; the other three groups map to their
        respective non-viewer roles.  If a user is in multiple groups the
        union of capabilities is used (admin wins).
        """
        return {
            self.all_users_group: Role.VIEWER,
            self.admin_group: Role.ADMIN,
            self.app_user_group: Role.APP_USER,
            self.audit_user_group: Role.AUDIT_USER,
        }


# Module-level singleton — imported by route handlers.
# Tests that need isolation should construct AuthConfig() directly.
CONFIG: AuthConfig = AuthConfig()


# ---------------------------------------------------------------------------
# ROLE_CAPABILITIES matrix
# ---------------------------------------------------------------------------

# Implements the capability matrix from docs/auth-rbac.md.
# admin is a strict superset; union semantics apply across multiple roles.

ROLE_CAPABILITIES: dict[str, set[str]] = {
    Role.VIEWER: {
        Capability.CAN_READ_CHAT,
        # View overview/architecture/docs — enforced as "authenticated viewer"
        # at the route level; no explicit capability constant needed beyond
        # requiring the user context to be non-anonymous.
    },
    Role.APP_USER: {
        Capability.CAN_READ_CHAT,
        Capability.CAN_RUN_WORKFLOW,          # request/preview only (route checks depth)
        Capability.CAN_MANAGE_DOCS,           # own app docs/runbooks
        Capability.CAN_EDIT_ARCHITECTURE_INVENTORY,  # own app/db entries
        Capability.CAN_EDIT_DATA,             # owned onboarding records
    },
    Role.AUDIT_USER: {
        Capability.CAN_READ_CHAT,
        Capability.CAN_RUN_WORKFLOW,          # report/audit workflows
        Capability.CAN_UPDATE_ARCHER,
        Capability.CAN_MANAGE_DOCS,           # audit artifacts/docs
        Capability.CAN_EDIT_ARCHITECTURE_INVENTORY,  # audit annotations
        Capability.CAN_VALIDATE_JIRA,
        Capability.CAN_EDIT_DATA,             # artifact metadata only (route checks depth)
    },
    Role.ADMIN: {
        # Full superset
        Capability.CAN_READ_CHAT,
        Capability.CAN_RUN_WORKFLOW,
        Capability.CAN_APPLY_JIRA,
        Capability.CAN_UPDATE_ARCHER,
        Capability.CAN_MANAGE_DOCS,
        Capability.CAN_SYNC_DOCS,
        Capability.CAN_EDIT_ARCHITECTURE_INVENTORY,
        Capability.CAN_ADMIN_AUTH,
        Capability.CAN_EDIT_DATA,
        Capability.CAN_VALIDATE_JIRA,
    },
}


# ---------------------------------------------------------------------------
# Pure derivation functions
# ---------------------------------------------------------------------------

def groups_to_roles(groups: list[str], config: AuthConfig | None = None) -> list[str]:
    """Derive the list of Role constants for the given group membership list.

    Uses the env-configured group→role map from *config* (defaults to the
    module-level CONFIG singleton).  Unknown groups are silently ignored.
    The returned list contains unique roles in a stable order (Role.ALL order).
    """
    cfg = config or CONFIG
    mapping = cfg.group_role_map()
    found: set[str] = set()
    for group in groups:
        role = mapping.get(group)
        if role is not None:
            found.add(role)
    # Stable ordering
    return [r for r in Role.ALL if r in found]


def roles_to_capabilities(roles: list[str] | set[str]) -> set[str]:
    """Union the capability sets for the given roles.

    Admin role is a strict superset so the result will equal admin's set if
    admin is present.  Unknown role strings are silently ignored.
    """
    caps: set[str] = set()
    for role in roles:
        caps |= ROLE_CAPABILITIES.get(role, set())
    return caps


# ---------------------------------------------------------------------------
# UserContext
# ---------------------------------------------------------------------------

@dataclass
class UserContext:
    """Resolved identity + authorization context for a single request.

    Constructed by identity-resolution code (S19.backend.1); consumed by
    route guards (S19.backend.3) and the /api/me endpoint (S19.backend.2).
    """

    username: str                       # typically email: firstname.lastname@lanGarland.com
    display_name: str
    email: str
    groups: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    capabilities: set[str] = field(default_factory=set)
    auth_mode: str = ""                 # mirrors AUTH_MODE value at time of resolution
    source: str = ""                    # e.g. "basic", "sso_header", "trusted_network", "dev_header"

    def has(self, capability: str) -> bool:
        """Return True if this user context includes the given capability."""
        return capability in self.capabilities

    def is_authenticated(self) -> bool:
        """Return True when the context represents a real resolved identity."""
        return bool(self.username)


# ---------------------------------------------------------------------------
# Convenience builder
# ---------------------------------------------------------------------------

def build_user_context(
    username: str,
    display_name: str,
    email: str,
    groups: list[str],
    auth_mode: str,
    source: str,
    config: AuthConfig | None = None,
) -> UserContext:
    """Derive roles and capabilities from groups and return a UserContext.

    This is the canonical factory used by every identity-resolution path so
    that group→role→capability logic stays in one place.
    """
    cfg = config or CONFIG
    roles = groups_to_roles(groups, cfg)
    caps = roles_to_capabilities(roles)
    return UserContext(
        username=username,
        display_name=display_name,
        email=email,
        groups=list(groups),
        roles=roles,
        capabilities=caps,
        auth_mode=auth_mode,
        source=source,
    )


# ---------------------------------------------------------------------------
# Unauthenticated sentinel
# ---------------------------------------------------------------------------
# Design decision: identity resolution returns None for "no valid credentials"
# (rather than raising).  require_user() and require_capability() convert None
# to HTTPException so the same resolver can be called by middleware OR directly
# by route handlers without forcing try/except at every call site.
# ---------------------------------------------------------------------------

_UNAUTHENTICATED: None = None  # type alias marker; callers test ``is None``


# ---------------------------------------------------------------------------
# Basic Auth users-file cache
# ---------------------------------------------------------------------------

@dataclass
class _UsersFileCache:
    """Tiny mtime-aware in-memory cache for the Basic Auth users JSON.

    Reload is triggered when:
      - the cache is empty (first access), OR
      - the file mtime has changed (file was regenerated), OR
      - CONFIG.cache_ttl_seconds have elapsed since the last load.

    Intentionally *not* thread-safe with asyncio locks — the worst case is a
    redundant re-read on a hot path, which is acceptable for a low-traffic POC.
    """

    _data: list[dict[str, Any]] = field(default_factory=list)
    _loaded_at: float = 0.0
    _mtime: float = 0.0

    def load(self, path: str, ttl: int) -> list[dict[str, Any]]:
        """Return the current user list, reloading from disk if needed."""
        now = time.monotonic()
        try:
            mtime = Path(path).stat().st_mtime
        except OSError:
            # File does not exist yet — return empty; caller will fail auth.
            logger.warning("auth: users file not found: %s", path)
            return []

        stale = (now - self._loaded_at) > ttl
        if self._data and not stale and mtime == self._mtime:
            return self._data

        try:
            raw = Path(path).read_text(encoding="utf-8")
            doc = json.loads(raw)
        except Exception as exc:
            logger.error("auth: failed to read users file %s: %s", path, exc)
            return self._data  # keep stale data rather than locking everyone out

        self._data = doc.get("users", [])
        self._loaded_at = now
        self._mtime = mtime
        logger.debug("auth: loaded %d users from %s", len(self._data), path)
        return self._data


_users_cache = _UsersFileCache()


def _get_users() -> list[dict[str, Any]]:
    """Return users list from the configured Basic Auth users file."""
    return _users_cache.load(CONFIG.basic_users_file, CONFIG.cache_ttl_seconds)


# ---------------------------------------------------------------------------
# LDAP stub (S19.ldap.1 swaps this out)
# ---------------------------------------------------------------------------

def _ldap_lookup(username: str) -> UserContext | None:
    """Delegate LDAP lookup to the directory adapter (S19.ldap.1).

    Calls ``auth_ldap.get_directory_adapter().lookup_user(username)`` and
    maps the returned minimal-attribute dict into a ``UserContext`` using
    ``build_user_context``.  Returns None when the adapter reports the user
    is not found.

    Isolation contract: this function is the *only* place that calls any LDAP
    adapter.  The adapter module (``auth_ldap``) is lazy-imported here to
    avoid circular imports — ``auth_ldap`` imports ``auth.CONFIG``, which is
    fine as long as neither module imports the other at module load time.
    """
    # Lazy import to avoid circular import: auth_ldap imports auth.CONFIG.
    import sys as _sys
    import importlib as _importlib

    # Ensure web/ is on sys.path so the sibling module resolves correctly when
    # auth.py is imported from a different working directory (e.g. py_compile).
    _web_dir = str(Path(__file__).parent)
    if _web_dir not in _sys.path:
        _sys.path.insert(0, _web_dir)

    _auth_ldap = _importlib.import_module("auth_ldap")
    adapter = _auth_ldap.get_directory_adapter()

    info = adapter.lookup_user(username)
    if info is None:
        return None

    return build_user_context(
        username=info["username"],
        display_name=info["display_name"],
        email=info["email"],
        groups=info["groups"],
        auth_mode="ldap",
        source=info.get("source", "ldap"),
    )


# ---------------------------------------------------------------------------
# Identity resolution
# ---------------------------------------------------------------------------

def resolve_user(request: Any) -> UserContext | None:  # noqa: PLR0911
    """Resolve the request's identity according to CONFIG.auth_mode.

    Returns a UserContext on success, or None when credentials are absent or
    invalid (the caller should treat None as 401-worthy unauthenticated).

    This function is *synchronous* (FastAPI handles both sync and async
    dependencies transparently).

    Mode semantics (mirrors docs/auth-rbac.md §Auth modes):

    disabled
        Skip all auth; return a synthetic all-capabilities admin context.
        SECURITY RISK: never enable in an Internet-facing deployment.

    headers
        Only when AUTH_DEV_HEADERS_ENABLED=true; reads X-SG-User and
        X-SG-Groups (comma-separated) from the request.  Must be disabled in
        production — if the flag is off, return None (treat as unauthenticated).

    trusted_network
        Read username from AUTH_TRUSTED_HEADER_USER / REMOTE_USER if present,
        else use the literal string 'anonymous-network-user'.  Groups default
        to [all_users_group] so the user always gets viewer capabilities.

    sso
        Derive identity ONLY from AUTH_TRUSTED_HEADER_USER /
        AUTH_TRUSTED_HEADER_GROUPS (set by the reverse proxy).
        X-SG-* dev headers are intentionally IGNORED here regardless of
        AUTH_DEV_HEADERS_ENABLED — this is a hard security boundary.
        If the trusted user header is absent → return None (401-worthy).

    basic
        Parse Authorization: Basic …, look the user up in the users file,
        verify with auth_seed.verify_password.  Honour the 'disabled' flag.
        Wrong/missing creds → return None.

    ldap
        Delegate to _ldap_lookup (stub until S19.ldap.1).  Raises
        NotImplementedError for non-fixture users — callers convert to 503.
    """
    mode = CONFIG.auth_mode

    if mode == "disabled":
        # ------------------------------------------------------------------ #
        # SECURITY WARNING: disabled mode grants full admin access to every   #
        # request.  It exists only for local development where running a full  #
        # auth stack is impractical.  Never enable AUTH_MODE=disabled in an   #
        # environment reachable from an untrusted network.                    #
        # ------------------------------------------------------------------ #
        return UserContext(
            username="local-dev",
            display_name="Local Dev (auth disabled)",
            email="local-dev@localhost",
            groups=list(CONFIG.group_role_map().keys()),
            roles=list(Role.ALL),
            capabilities=set(Capability.ALL),
            auth_mode=mode,
            source="disabled",
        )

    if mode == "headers":
        if not CONFIG.dev_headers_enabled:
            # Dev headers gate is closed — unauthenticated.
            return _UNAUTHENTICATED
        raw_user = request.headers.get("X-SG-User", "").strip()
        if not raw_user:
            return _UNAUTHENTICATED
        raw_groups = request.headers.get("X-SG-Groups", "").strip()
        groups = [g.strip() for g in raw_groups.split(",") if g.strip()] if raw_groups else []
        return build_user_context(
            username=raw_user,
            display_name=raw_user,
            email=raw_user if "@" in raw_user else f"{raw_user}@dev.local",
            groups=groups,
            auth_mode=mode,
            source="dev_header",
        )

    if mode == "trusted_network":
        # Try the configured trusted header first, then the CGI legacy name.
        username = (
            request.headers.get(CONFIG.trusted_header_user, "").strip()
            or request.headers.get("REMOTE_USER", "").strip()
            or "anonymous-network-user"
        )
        groups = [CONFIG.all_users_group]
        return build_user_context(
            username=username,
            display_name=username,
            email=username if "@" in username else f"{username}@network.local",
            groups=groups,
            auth_mode=mode,
            source="trusted_network",
        )

    if mode == "sso":
        # SECURITY: never read X-SG-* dev headers here, even if
        # AUTH_DEV_HEADERS_ENABLED is set.  Only the configured trusted proxy
        # headers are honoured in SSO mode.
        username = request.headers.get(CONFIG.trusted_header_user, "").strip()
        if not username:
            return _UNAUTHENTICATED
        raw_groups = request.headers.get(CONFIG.trusted_header_groups, "").strip()
        groups = [g.strip() for g in raw_groups.split(",") if g.strip()] if raw_groups else []
        return build_user_context(
            username=username,
            display_name=username,
            email=username if "@" in username else f"{username}@sso.local",
            groups=groups,
            auth_mode=mode,
            source="sso_header",
        )

    if mode == "basic":
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.lower().startswith("basic "):
            return _UNAUTHENTICATED
        try:
            decoded = base64.b64decode(auth_header[6:].strip()).decode("utf-8", errors="replace")
        except Exception:
            return _UNAUTHENTICATED
        # RFC 7617: credentials = userid ":" *password
        sep = decoded.find(":")
        if sep < 0:
            return _UNAUTHENTICATED
        username = decoded[:sep]
        plain_password = decoded[sep + 1:]

        users = _get_users()
        record = next(
            (u for u in users if u.get("email", "").lower() == username.lower()),
            None,
        )
        if record is None:
            return _UNAUTHENTICATED
        if record.get("disabled", False):
            return _UNAUTHENTICATED

        pw_record = record.get("password")
        if not pw_record:
            return _UNAUTHENTICATED

        # Import at call time to avoid circular imports; auth_seed is a sibling
        # module (not a package dependency of auth.py at load time).
        try:
            from auth_seed import verify_password as _verify  # type: ignore[import]
        except ModuleNotFoundError:
            import sys
            sys.path.insert(0, str(Path(__file__).parent))
            from auth_seed import verify_password as _verify  # type: ignore[import]

        try:
            ok = _verify(plain_password, pw_record)
        except Exception as exc:
            logger.warning("auth: password verification error for %s: %s", username, exc)
            return _UNAUTHENTICATED

        if not ok:
            return _UNAUTHENTICATED

        groups = record.get("groups", [])
        display = record.get("display_name", username)
        return build_user_context(
            username=username,
            display_name=display,
            email=username,
            groups=groups,
            auth_mode=mode,
            source="basic",
        )

    if mode == "ldap":
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.lower().startswith("basic "):
            return _UNAUTHENTICATED
        try:
            decoded = base64.b64decode(auth_header[6:].strip()).decode("utf-8", errors="replace")
        except Exception:
            return _UNAUTHENTICATED
        sep = decoded.find(":")
        if sep < 0:
            return _UNAUTHENTICATED
        username = decoded[:sep]
        # Password extraction kept for future real LDAP bind; stub ignores it.
        return _ldap_lookup(username)  # raises NotImplementedError for non-fixture users

    # Unknown mode — treat as unauthenticated and log so operators notice.
    logger.error("auth: unknown AUTH_MODE=%r; treating all requests as unauthenticated", mode)
    return _UNAUTHENTICATED


# ---------------------------------------------------------------------------
# Guard helpers (consumed by S19.backend.3 route guards)
# ---------------------------------------------------------------------------

def require_user(request: Any) -> UserContext:
    """Resolve the request identity and raise HTTP 401 if unauthenticated.

    Raises
    ------
    fastapi.HTTPException  status=401
        When resolve_user returns None (missing / invalid credentials).
        Includes a ``WWW-Authenticate: Basic`` header when AUTH_MODE is basic,
        so browsers surface a native credentials prompt.
    """
    from fastapi import HTTPException as _HTTPException  # lazy: fastapi only present at runtime
    user = resolve_user(request)
    if user is None:
        hdrs: dict[str, str] = {}
        if CONFIG.auth_mode == "basic":
            hdrs["WWW-Authenticate"] = 'Basic realm="sglandsimple"'
        raise _HTTPException(status_code=401, detail="Authentication required", headers=hdrs)
    return user


def require_capability(capability: str) -> Callable[[Any], UserContext]:
    """FastAPI dependency factory that checks for a specific capability.

    Usage::

        @app.get("/api/admin/something")
        async def handler(user: UserContext = Depends(require_capability(Capability.CAN_ADMIN_AUTH))):
            ...

    Raises
    ------
    fastapi.HTTPException  status=401
        When the request is unauthenticated (no valid credentials).
    fastapi.HTTPException  status=403
        When the user is authenticated but lacks *capability*.
    """
    def _guard(request: Any) -> UserContext:
        from fastapi import HTTPException as _HTTPException  # lazy
        user = require_user(request)  # raises 401 if unauthenticated
        if not user.has(capability):
            raise _HTTPException(
                status_code=403,
                detail=f"Forbidden: capability '{capability}' required",
            )
        return user

    _guard.__name__ = f"require_{capability}"
    return _guard


# ---------------------------------------------------------------------------
# Placeholder password-hash helper signature
# (real implementation is in auth_seed.verify_password; used by basic mode above)
# ---------------------------------------------------------------------------

def verify_password(plain: str, hashed: str) -> bool:  # noqa: ARG001
    """Legacy stub — kept for import-time type-checking compatibility.

    Identity resolution (basic mode) calls ``auth_seed.verify_password``
    directly.  This stub raises NotImplementedError so stale callers are
    caught immediately.
    """
    raise NotImplementedError(
        "Call auth_seed.verify_password(plain, record) instead — "
        "this stub exists only for import-time compatibility."
    )
