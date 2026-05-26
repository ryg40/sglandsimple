# Deep Agent sandbox runtime (Stage 21, optional sidecar).
#
# Opt-in container for running agent shell/code/filesystem work isolated from
# the MCP request path. Off by default — only started via the `sandbox` compose
# profile (`docker compose --profile sandbox up`) or when
# DEEP_AGENT_RUNTIME_MODE=sidecar. Until the Stage-21 runtime lands
# (S21.deploy.1) this image just provides an isolated, non-root execution
# environment with a shared /sandbox bind mount; it idles otherwise.
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

USER sandbox

# No long-running process yet — the Stage-21 sidecar runtime (S21.deploy.1) will
# replace this with the agent-runtime entrypoint. Idle so the container is
# available for `docker compose exec` and stays healthy without doing work.
CMD ["sleep", "infinity"]
