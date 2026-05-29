"""Deep Agent sandbox sidecar entrypoint (S21.deploy.1).

A minimal, dependency-free HTTP server that gives the optional `sandbox`
service a real, health-checkable lifecycle instead of `sleep infinity`. It does
two things:

* serves ``GET /healthz`` → ``200 {"status":"ok",...}`` so compose/orchestrators
  can gate readiness on it (and a sidecar deployment has a liveness signal);
* keeps the shared ``DEEP_AGENT_ARTIFACT_DIR`` present and writable as the
  unprivileged ``sandbox`` user, which is the directory the in-mcp deep-agent
  and any future sidecar runtime exchange artifacts through.

It deliberately uses only the stdlib so the sandbox image stays tiny and has no
attack surface beyond Python itself — the heavy agent runtime stays in the
`mcp` image (``DEEP_AGENT_RUNTIME_MODE=in_mcp``, the default). When
``DEEP_AGENT_RUNTIME_MODE=sidecar`` this process is the place a future
out-of-band executor would attach; today it provides the isolated, non-root,
health-checked execution environment that gate satisfies.
"""

from __future__ import annotations

import json
import os
import signal
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("SANDBOX_PORT", "8090"))
ARTIFACT_DIR = os.environ.get("DEEP_AGENT_ARTIFACT_DIR", "/sandbox/agent-artifacts")
RUNTIME_MODE = os.environ.get("DEEP_AGENT_RUNTIME_MODE", "in_mcp")


def _ensure_artifact_dir() -> bool:
    try:
        os.makedirs(ARTIFACT_DIR, exist_ok=True)
        # Probe writability without leaving a file behind.
        return os.access(ARTIFACT_DIR, os.W_OK)
    except OSError as e:
        print(f"[sandbox.sidecar] artifact dir {ARTIFACT_DIR} not writable: {e}", file=sys.stderr, flush=True)
        return False


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 — stdlib API
        if self.path.rstrip("/") in ("/healthz", ""):
            body = json.dumps(
                {
                    "status": "ok",
                    "service": "deep-agent-sandbox",
                    "runtime_mode": RUNTIME_MODE,
                    "artifact_dir": ARTIFACT_DIR,
                    "artifact_writable": _ensure_artifact_dir(),
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *_args: object) -> None:
        # Silence per-request access logs; healthz polls every 10s.
        return


def main() -> None:
    _ensure_artifact_dir()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), _Handler)
    print(
        f"[sandbox.sidecar] listening on :{PORT} mode={RUNTIME_MODE} artifacts={ARTIFACT_DIR}",
        flush=True,
    )

    def _stop(*_args: object) -> None:
        print("[sandbox.sidecar] shutting down", flush=True)
        server.shutdown()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    server.serve_forever()


if __name__ == "__main__":
    main()
