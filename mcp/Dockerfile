FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Tools needed for the Stage-4 sandbox: `runuser` (drop privileges per
# shell_exec call) and a `bash` shell. `curl` is handy for the builder.
RUN apt-get update \
    && apt-get install -y --no-install-recommends util-linux bash curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Non-root account that shell_exec and the fs_* tools impersonate. Uid 1000
# matches the host owner of ./sandbox/ so writes round-trip cleanly.
RUN useradd --create-home --uid 1000 --shell /bin/bash sandbox \
    && mkdir -p /sandbox \
    && chown sandbox:sandbox /sandbox

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY *.py ./
COPY deep_agent ./deep_agent
COPY connectors ./connectors
COPY workflow ./workflow
COPY report ./report

EXPOSE 8080
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
