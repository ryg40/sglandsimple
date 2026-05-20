"""Stage-4 sandbox: filesystem and shell tools confined to /sandbox.

The MCP server process runs as root (the container's default) but every
fs/shell operation in this module:

- Resolves paths through ``safe_path`` so traversal/abs paths are
  rejected before any I/O happens.
- Runs ``shell_exec`` via ``runuser -u sandbox`` so the command itself
  cannot write outside /sandbox or touch other container state.

The host bind-mount (./sandbox -> /sandbox) is owned by uid 1000 so the
``sandbox`` user can read and write through the mount.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

SANDBOX_ROOT = Path(os.environ.get("DEEP_AGENT_SANDBOX_ROOT", "/sandbox")).resolve()
SHELL_TIMEOUT_DEFAULT = float(os.environ.get("DEEP_AGENT_SHELL_TIMEOUT", "30"))
SHELL_USER = os.environ.get("DEEP_AGENT_SHELL_USER", "sandbox")
SHELL_OUTPUT_LIMIT = int(os.environ.get("DEEP_AGENT_SHELL_OUTPUT_LIMIT", "20000"))


class SandboxError(ValueError):
    """Raised on path-resolution / sandbox-policy violations."""


def safe_path(rel: str) -> Path:
    """Resolve ``rel`` against /sandbox and refuse anything that escapes.

    Accepts relative paths. Rejects absolute paths, paths whose resolved
    location is not under /sandbox, and any input that resolves through
    a symlink pointing outside the sandbox.
    """
    if not isinstance(rel, str) or not rel.strip():
        raise SandboxError("path must be a non-empty string")
    if rel.startswith("/"):
        raise SandboxError(f"absolute paths are not allowed: {rel!r}")
    candidate = (SANDBOX_ROOT / rel).resolve()
    try:
        candidate.relative_to(SANDBOX_ROOT)
    except ValueError as e:
        raise SandboxError(f"path escapes sandbox: {rel!r}") from e
    return candidate


# ---------------------------------------------------------------------------
# Filesystem
# ---------------------------------------------------------------------------


def fs_read(path: str, max_bytes: int = 256_000) -> str:
    p = safe_path(path)
    if not p.exists():
        raise SandboxError(f"no such file: {path!r}")
    if not p.is_file():
        raise SandboxError(f"not a regular file: {path!r}")
    data = p.read_bytes()
    if len(data) > max_bytes:
        return data[:max_bytes].decode("utf-8", errors="replace") + f"\n…[truncated {len(data) - max_bytes} bytes]"
    return data.decode("utf-8", errors="replace")


def fs_write(path: str, content: str) -> dict:
    p = safe_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    # Keep files owned by the sandbox user so shell_exec can edit them.
    try:
        os.chown(p, 1000, 1000)
    except (PermissionError, LookupError):
        pass
    return {"path": str(p.relative_to(SANDBOX_ROOT)), "bytes": len(content.encode("utf-8"))}


def fs_edit(path: str, old_string: str, new_string: str) -> dict:
    if old_string == new_string:
        raise SandboxError("old_string and new_string are identical")
    p = safe_path(path)
    if not p.exists() or not p.is_file():
        raise SandboxError(f"no such file: {path!r}")
    text = p.read_text(encoding="utf-8")
    count = text.count(old_string)
    if count == 0:
        raise SandboxError("old_string not found in file")
    if count > 1:
        raise SandboxError(f"old_string is not unique (matches {count} places); enlarge the snippet")
    updated = text.replace(old_string, new_string, 1)
    p.write_text(updated, encoding="utf-8")
    return {"path": str(p.relative_to(SANDBOX_ROOT)), "bytes": len(updated.encode("utf-8"))}


# ---------------------------------------------------------------------------
# Shell
# ---------------------------------------------------------------------------


async def shell_exec(cmd: str, timeout_sec: float | None = None) -> dict:
    """Run ``cmd`` inside /sandbox as the non-root sandbox user.

    The command is wrapped in ``bash -lc`` so shell syntax (pipes, &&,
    redirects) works. Output is truncated at SHELL_OUTPUT_LIMIT to keep
    runaway processes from blowing the per-call context budget.
    """
    if not isinstance(cmd, str) or not cmd.strip():
        raise SandboxError("cmd must be a non-empty string")

    timeout = float(timeout_sec) if timeout_sec is not None else SHELL_TIMEOUT_DEFAULT
    # `runuser -u <user> -- bash -lc <cmd>` drops to uid 1000 before exec.
    argv = ["runuser", "-u", SHELL_USER, "--", "bash", "-lc", cmd]

    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(SANDBOX_ROOT),
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        finally:
            await proc.wait()
        return {
            "cmd": cmd,
            "exit_code": None,
            "stdout": "",
            "stderr": f"[sandbox] timed out after {timeout}s",
            "timed_out": True,
        }

    def _decode(buf: bytes) -> str:
        text = buf.decode("utf-8", errors="replace")
        if len(text) > SHELL_OUTPUT_LIMIT:
            return text[:SHELL_OUTPUT_LIMIT] + f"\n…[truncated {len(text) - SHELL_OUTPUT_LIMIT} chars]"
        return text

    return {
        "cmd": cmd,
        "exit_code": proc.returncode,
        "stdout": _decode(stdout),
        "stderr": _decode(stderr),
        "timed_out": False,
    }
