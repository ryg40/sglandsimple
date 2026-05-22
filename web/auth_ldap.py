"""LDAP / directory adapter interface and fixture implementation (S19.ldap.1).

This module defines a narrow, privacy-conscious interface (``DirectoryAdapter``)
for user-directory lookups. The sole implementation today is
``FixtureDirectoryAdapter`` — deterministic, no network, seeded from the same
six identities used by ``auth_seed.py``.

Route guards in ``auth.py`` import only ``get_directory_adapter()``; they never
talk to a real LDAP server directly. When a real adapter lands (S19.ldap.2+),
only this module changes — route guards stay identical.

Privacy boundary (docs/auth-rbac.md §Privacy boundary)
-------------------------------------------------------
``lookup_user`` returns ONLY the minimal allowed keys::

    username, display_name, email, groups, source, lookup_ts

Passwords, raw LDAP attributes, and any other directory data are NEVER included,
even in the fixture.

Usage::

    from auth_ldap import get_directory_adapter

    adapter = get_directory_adapter()
    info = adapter.lookup_user("simone.patel@lanGarland.com")
    # -> {"username": ..., "display_name": ..., "email": ...,
    #     "groups": [...], "source": "fixture", "lookup_ts": ...}
"""

from __future__ import annotations

import datetime
import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass  # No circular-import-sensitive imports needed at type-check time

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Allowed keys in the dict returned by lookup_user — enforced by all adapters.
# ---------------------------------------------------------------------------

_MINIMAL_KEYS: frozenset[str] = frozenset(
    {"username", "display_name", "email", "groups", "source", "lookup_ts"}
)


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------


class DirectoryAdapter(ABC):
    """Narrow interface for user-directory lookups.

    All methods are synchronous so they can be wrapped with
    ``asyncio.to_thread`` at the call site when an async context is needed.

    Privacy contract: implementations MUST return only the keys enumerated in
    ``_MINIMAL_KEYS`` from ``lookup_user``.  No passwords, no raw LDAP
    attributes, no attributes beyond those six.
    """

    @abstractmethod
    def lookup_user(self, username: str) -> dict | None:
        """Return minimal user attributes for *username*, or None if not found.

        Parameters
        ----------
        username:
            Login identity — typically the full email address
            (``firstname.lastname@lanGarland.com``).

        Returns
        -------
        dict | None
            On success, a dict with EXACTLY these keys
            (see docs/auth-rbac.md §Privacy boundary):

            - ``username``    — login / principal name (str)
            - ``display_name`` — human-readable full name (str)
            - ``email``       — email address (str)
            - ``groups``      — list of group names the user belongs to (list[str])
            - ``source``      — adapter identifier, e.g. ``"fixture"`` (str)
            - ``lookup_ts``   — ISO-8601 UTC timestamp of the lookup (str)

            Returns ``None`` when the user is not found.

        Raises
        ------
        Exception
            Adapters may raise on transient directory errors (e.g. network
            failure to an LDAP server); callers should convert to HTTP 503.
        """

    @abstractmethod
    def lookup_groups(self, username: str) -> list[str]:
        """Return the list of group names *username* belongs to.

        Returns an empty list (not None) when the user is not found.
        """

    @abstractmethod
    def check_membership(self, username: str, group: str) -> bool:
        """Return True if *username* is a member of *group*."""


# ---------------------------------------------------------------------------
# Fixture implementation
# ---------------------------------------------------------------------------

# Seeded identities from docs/auth-rbac.md §Seeded users.
# Groups use CONFIG values (resolved at adapter instantiation) so the fixture
# matches whatever AUTH_*_GROUP env vars are active — never hardcoded literals.
#
# Layout: list of (login_email, display_name, group_config_attrs)
# group_config_attrs is a tuple of AuthConfig attribute names whose values are
# the group strings to include for this user.
_SEED_SCHEMA: list[tuple[str, str, tuple[str, ...]]] = [
    (
        "avery.stone@lanGarland.com",
        "Avery Stone",
        ("all_users_group",),
    ),
    (
        "simone.patel@lanGarland.com",
        "Simone Patel",
        ("all_users_group", "admin_group"),
    ),
    (
        "marcus.chen@lanGarland.com",
        "Marcus Chen",
        ("all_users_group", "app_user_group"),
    ),
    (
        "elena.brooks@lanGarland.com",
        "Elena Brooks",
        ("all_users_group", "audit_user_group"),
    ),
    (
        "priya.morgan@lanGarland.com",
        "Priya Morgan",
        ("all_users_group", "app_user_group", "audit_user_group"),
    ),
    (
        "jordan.reyes@lanGarland.com",
        "Jordan Reyes",
        ("all_users_group", "admin_group", "audit_user_group"),
    ),
]


class FixtureDirectoryAdapter(DirectoryAdapter):
    """Deterministic, no-network directory adapter backed by seeded fixture data.

    Group names are read from ``auth.CONFIG`` at instantiation so they always
    reflect the current ``AUTH_*_GROUP`` env vars — fixture users will have the
    same group strings that ``auth_seed.py`` and ``auth.py`` use.

    This adapter covers all four placeholder groups::

        sg_all_users, sg_sec_admin, sg_app_user, sg_audit_users

    (or whatever the env-configured equivalents are).
    """

    def __init__(self) -> None:
        # Lazy import to avoid circular import at module load time.
        from auth import CONFIG as _CONFIG  # type: ignore[import]

        # Build the fixture user records once, using live CONFIG values.
        self._records: dict[str, dict] = {}
        for email, display_name, config_attrs in _SEED_SCHEMA:
            groups = [getattr(_CONFIG, attr) for attr in config_attrs]
            self._records[email.lower()] = {
                "username": email,
                "display_name": display_name,
                "email": email,
                "groups": groups,
            }

    # ------------------------------------------------------------------
    # DirectoryAdapter implementation
    # ------------------------------------------------------------------

    def lookup_user(self, username: str) -> dict | None:
        """Return minimal attributes for *username* from fixture data.

        The returned dict contains EXACTLY the minimal allowed keys
        (``_MINIMAL_KEYS``); no extra fields are added.

        Parameters
        ----------
        username:
            Looked up case-insensitively against the fixture email index.

        Returns
        -------
        dict | None
        """
        record = self._records.get(username.lower())
        if record is None:
            return None

        ts = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        result = {
            "username": record["username"],
            "display_name": record["display_name"],
            "email": record["email"],
            "groups": list(record["groups"]),  # defensive copy
            "source": "fixture",
            "lookup_ts": ts,
        }
        # Enforce the privacy boundary — only allowed keys are returned.
        assert set(result.keys()) == _MINIMAL_KEYS, (
            f"FixtureDirectoryAdapter.lookup_user returned unexpected keys: {set(result.keys())}"
        )
        return result

    def lookup_groups(self, username: str) -> list[str]:
        """Return the list of groups *username* belongs to.

        Returns an empty list when the user is not found.
        """
        record = self._records.get(username.lower())
        if record is None:
            return []
        return list(record["groups"])

    def check_membership(self, username: str, group: str) -> bool:
        """Return True if *username* is a member of *group*."""
        return group in self.lookup_groups(username)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_directory_adapter() -> DirectoryAdapter:
    """Return the appropriate ``DirectoryAdapter`` for the current config.

    Selection logic
    ---------------
    1. If ``CONFIG.ldap_url`` is set (non-empty), a real LDAP adapter *would*
       be used here.

       TODO(S19.ldap.2): Instantiate and return a real ``LdapDirectoryAdapter``
       when ``CONFIG.ldap_url`` is set.  The adapter should use
       ``CONFIG.ldap_base_dn`` and ``CONFIG.ldap_bind_secret_file`` for
       connection parameters.  Until that work lands, we fall through to the
       fixture unconditionally.

    2. Otherwise (including the TODO fall-through above), return a
       ``FixtureDirectoryAdapter``.

    The returned adapter is freshly constructed on each call (cheap for the
    fixture; real adapters may maintain a connection pool internally).
    """
    # Lazy import to avoid circular import at module load time.
    from auth import CONFIG as _CONFIG  # type: ignore[import]

    if _CONFIG.ldap_url:
        # TODO(S19.ldap.2): real LDAP adapter goes here.
        # Example stub of how it will look:
        #
        #   from auth_ldap_real import LdapDirectoryAdapter
        #   return LdapDirectoryAdapter(
        #       url=_CONFIG.ldap_url,
        #       base_dn=_CONFIG.ldap_base_dn,
        #       bind_secret_file=_CONFIG.ldap_bind_secret_file,
        #   )
        #
        # For now, log a warning and fall back to the fixture so the service
        # stays functional even when LDAP is partially configured.
        logger.warning(
            "auth_ldap: AUTH_LDAP_URL is set (%r) but no real LDAP adapter is "
            "implemented yet (S19.ldap.2). Falling back to FixtureDirectoryAdapter. "
            "This is ONLY acceptable in a development/POC environment.",
            _CONFIG.ldap_url,
        )

    return FixtureDirectoryAdapter()
