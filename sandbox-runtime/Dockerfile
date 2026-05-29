# Deep Agent sandbox runtime (Stage 21, optional sidecar).
#
# Opt-in container for running agent shell/code/filesystem work isolated from
# the MCP request path. Off by default — only started via the `sandbox` compose
# profile (`docker compose --profile sandbox up`) or when
# DEEP_AGENT_RUNTIME_MODE=sidecar. It provides an isolated, non-root execution
# environment with a shared /sandbox bind mount and (S21.deploy.1) a
# health-checked sidecar entrypoint instead of idling.
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Same sandbox tooling as the mcp image: a shell + privilege-drop tool so agent
# shell_exec runs as an unprivileged user, plus curl/ca-certificates for the
# builder.
RUN apt-get update \
    && apt-get install -y --no-install-recommends util-linux bash curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Non-root account that fs/shell tools impersonate. Uid 1000 matches the host
# owner of ./sandbox so writes round-trip cleanly (same as the mcp image).
RUN useradd --create-home --uid 1000 --shell /bin/bash sandbox \
    && mkdir -p /sandbox \
    && chown sandbox:sandbox /sandbox

# Stdlib-only sidecar entrypoint: serves /healthz and keeps the shared artifact
# dir present/writable. No pip deps — the heavy agent runtime stays in `mcp`.
COPY sidecar.py /app/sidecar.py

USER sandbox

EXPOSE 8090

# Health-checked liveness for the sidecar (S21.deploy.1). The compose service
# also declares this; baking it in means a bare `docker run` of the image is
# health-aware too.
HEALTHCHECK --interval=10s --timeout=3s --retries=5 --start-period=10s \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8090/healthz',timeout=2).status==200 else 1)"

CMD ["python", "/app/sidecar.py"]
