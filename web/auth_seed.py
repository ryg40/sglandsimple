"""Stage-19 seed generator for POC Basic Auth users.

Writes a deterministic users.json to AUTH_BASIC_USERS_FILE (default
/data/auth/users.json).  Passwords are NEVER stored in plaintext; each user
gets a salted pbkdf2_sha256 hash.

Usage (container or host):
    python3 web/auth_seed.py

Env vars:
    AUTH_BASIC_USERS_FILE   — output path  (default: /data/auth/users.json)
    AUTH_BASIC_SEED_PASSWORD — shared dev password  (default: changeme-poc, prints warning)

See docs/auth-rbac.md for the canonical six-user POC table.

Security note: the per-user salt is derived deterministically from the email
address so that re-running with the same seed password produces identical hash
records.  This is acceptable for a POC fixture; in production, every password
change must use a freshly random salt.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Import auth config so group names track env renames (AUTH_*_GROUP).
# We guard the import so that auth_seed.py can be syntax-checked in
# isolation even if auth.py's own imports aren't fully resolved.
# ---------------------------------------------------------------------------
try:
    from auth import CONFIG  # type: ignore[import]
except ModuleNotFoundError:
    # Running outside the web/ package (e.g. from repo root); adjust path.
    sys.path.insert(0, str(Path(__file__).parent))
    from auth import CONFIG  # type: ignore[import]


# ---------------------------------------------------------------------------
# Hashing helpers  (back-fill for auth.verify_password stub in auth.py)
# ---------------------------------------------------------------------------

_ITERATIONS: int = 260_000  # OWASP 2024 minimum for PBKDF2-SHA-256
_ALGO: str = "pbkdf2_sha256"


def hash_password(plain: str, salt: str | None = None) -> dict[str, str | int]:
    """Hash *plain* with PBKDF2-SHA-256.

    Parameters
    ----------
    plain:
        Plaintext password.
    salt:
        Hex-encoded salt string.  When *None* a random 32-byte salt is
        generated via :func:`os.urandom`.  Pass an explicit value to
        reproduce a deterministic hash (POC-only; never do this in production).

    Returns
    -------
    dict with keys ``salt`` (hex str), ``hash`` (hex str), ``algo`` (str),
    ``iterations`` (int).  Store the whole dict; pass it to
    :func:`verify_password` unchanged.
    """
    if salt is None:
        salt_bytes = os.urandom(32)
        salt_hex = salt_bytes.hex()
    else:
        salt_hex = salt
        salt_bytes = bytes.fromhex(salt)

    dk = hashlib.pbkdf2_hmac(
        "sha256",
        plain.encode("utf-8"),
        salt_bytes,
        _ITERATIONS,
    )
    return {
        "salt": salt_hex,
        "hash": dk.hex(),
        "algo": _ALGO,
        "iterations": _ITERATIONS,
    }


def verify_password(plain: str, record: dict[str, str | int]) -> bool:
    """Return True iff *plain* matches the stored hash *record*.

    *record* must be the dict returned by :func:`hash_password`
    (keys: ``salt``, ``hash``, ``algo``, ``iterations``).

    S19.backend.1 should import and use this function — it is the real
    implementation of the stub in auth.py.
    """
    if record.get("algo") != _ALGO:
        raise ValueError(f"Unsupported hash algorithm: {record.get('algo')!r}")
    candidate = hash_password(
        plain,
        salt=str(record["salt"]),
    )
    # Constant-time comparison to prevent timing attacks
    return hmac.compare_digest(
        str(candidate["hash"]),
        str(record["hash"]),
    )


# ---------------------------------------------------------------------------
# Seed user table
# Verbatim from docs/auth-rbac.md "Seeded users (POC)" table.
# Group references use CONFIG so they track AUTH_*_GROUP env renames.
# ---------------------------------------------------------------------------

def _seed_users() -> list[dict]:  # noqa: PLR0914
    """Build the six-user seed list, reading group names from CONFIG."""
    all_g = CONFIG.all_users_group     # sg_all_users
    admin_g = CONFIG.admin_group       # sg_sec_admin
    app_g = CONFIG.app_user_group      # sg_app_user
    audit_g = CONFIG.audit_user_group  # sg_audit_users

    return [
        {
            "display_name": "Avery Stone",
            "email": "avery.stone@lanGarland.com",
            "groups": [all_g],
            "disabled": False,
            "created_at": "2025-01-01T00:00:00Z",
            "notes": "base viewer",
        },
        {
            "display_name": "Simone Patel",
            "email": "simone.patel@lanGarland.com",
            "groups": [all_g, admin_g],
            "disabled": False,
            "created_at": "2025-01-01T00:00:00Z",
            "notes": "admin",
        },
        {
            "display_name": "Marcus Chen",
            "email": "marcus.chen@lanGarland.com",
            "groups": [all_g, app_g],
            "disabled": False,
            "created_at": "2025-01-01T00:00:00Z",
            "notes": "app/db owner",
        },
        {
            "display_name": "Elena Brooks",
            "email": "elena.brooks@lanGarland.com",
            "groups": [all_g, audit_g],
            "disabled": False,
            "created_at": "2025-01-01T00:00:00Z",
            "notes": "audit user",
        },
        {
            "display_name": "Priya Morgan",
            "email": "priya.morgan@lanGarland.com",
            "groups": [all_g, app_g, audit_g],
            "disabled": False,
            "created_at": "2025-01-01T00:00:00Z",
            "notes": "multi-role non-admin",
        },
        {
            "display_name": "Jordan Reyes",
            "email": "jordan.reyes@lanGarland.com",
            "groups": [all_g, admin_g, audit_g],
            "disabled": False,
            "created_at": "2025-01-01T00:00:00Z",
            "notes": "admin + audit",
        },
    ]


# Re-export as module constant so callers can inspect without calling the
# function.
SEED_USERS: list[dict] = _seed_users()


# ---------------------------------------------------------------------------
# Deterministic salt derivation (POC only)
# ---------------------------------------------------------------------------

def _derive_salt(email: str, seed_password: str) -> str:
    """Derive a per-user, deterministic salt from email + seed_password.

    WARNING: deterministic salts are acceptable ONLY for a seeded fixture that
    will be regenerated from env — never use this pattern for real password
    storage.  Real password changes must use os.urandom(32) salts.

    The salt is 32 bytes of PBKDF2 output keyed on (seed_password, email),
    which means re-running with the same seed password always produces the
    same hash (idempotent file generation).
    """
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        seed_password.encode("utf-8"),
        email.encode("utf-8"),
        1,          # minimal iterations — this is just salt derivation
        dklen=32,
    )
    return dk.hex()


# ---------------------------------------------------------------------------
# File generator
# ---------------------------------------------------------------------------

def generate_users_file(
    path: str | None = None,
    seed_password: str | None = None,
) -> dict:
    """Generate the users JSON structure and write it to *path*.

    Parameters
    ----------
    path:
        Destination file path.  Defaults to ``AUTH_BASIC_USERS_FILE`` env var
        or ``/data/auth/users.json``.
    seed_password:
        Shared dev password to hash for every user.  Defaults to
        ``AUTH_BASIC_SEED_PASSWORD`` env var.

    Returns
    -------
    The dict that was written to the file, keyed by ``"generated_at"``,
    ``"generator"``, and ``"users"`` (list).

    Idempotency
    -----------
    Given the same *seed_password*, running this function multiple times
    always produces bit-identical JSON because salts are derived
    deterministically from the email address (see ``_derive_salt``).  This is
    intentional for a POC fixture; real password records must use random salts.
    """
    resolved_path = path or os.environ.get(
        "AUTH_BASIC_USERS_FILE", "/data/auth/users.json"
    )

    if seed_password is None:
        seed_password = os.environ.get("AUTH_BASIC_SEED_PASSWORD", "")

    if not seed_password:
        seed_password = "changeme-poc"
        warnings.warn(
            "AUTH_BASIC_SEED_PASSWORD is not set — defaulting to 'changeme-poc'. "
            "Set this env var before generating production fixtures.",
            UserWarning,
            stacklevel=2,
        )

    users = []
    for user in _seed_users():
        email = user["email"]
        salt = _derive_salt(email, seed_password)
        pw_record = hash_password(seed_password, salt=salt)
        record = dict(user)  # shallow copy; lists are already new from _seed_users()
        record["password"] = pw_record
        users.append(record)

    output = {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "generator": "web/auth_seed.py",
        "note": (
            "POC-only. Passwords are salted PBKDF2-SHA-256 hashes. "
            "Never commit this file. Regenerate with: "
            "AUTH_BASIC_SEED_PASSWORD=<secret> python3 web/auth_seed.py"
        ),
        "users": users,
    }

    dest = Path(resolved_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(output, indent=2), encoding="utf-8")
    return output


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    out_path = os.environ.get("AUTH_BASIC_USERS_FILE", "/data/auth/users.json")
    seed_pw = os.environ.get("AUTH_BASIC_SEED_PASSWORD", "")

    if not seed_pw:
        print(
            "WARNING: AUTH_BASIC_SEED_PASSWORD is not set. "
            "Defaulting to 'changeme-poc'. "
            "Set it before generating fixtures for a shared environment.",
            file=sys.stderr,
        )
        seed_pw = "changeme-poc"

    result = generate_users_file(path=out_path, seed_password=seed_pw)
    user_count = len(result["users"])
    print(f"Wrote {user_count} users to {out_path}")
    print(f"Generated at: {result['generated_at']}")
    for u in result["users"]:
        algo = u["password"]["algo"]
        iters = u["password"]["iterations"]
        print(f"  {u['email']:45s}  groups={u['groups']}  hash={algo}/{iters}")
