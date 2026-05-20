# Connecting external MCP clients

The MCP server at `mcp:8080/mcp` (host port `${MCP_PORT}`, default `5451`)
speaks JSON-RPC 2.0 over HTTP POST with an SSE keepalive on `GET /mcp`.
Stage 3 adds:

- A `Mcp-Session-Id` header returned on `initialize` and required on
every subsequent request.
- Optional bearer auth via `MCP_AUTH_TOKEN`. If unset, the server logs a
startup warning and accepts unauthenticated requests.
- A per-session token-bucket rate limit (`MCP_RATE_PER_MIN`, default 60).

---

## Generating `MCP_AUTH_TOKEN`

A strong random value is the only supported auth method. Generate it once:

```bash
openssl rand -hex 32
# → 6f3e2c...   (64 hex chars = 256 bits)
```

Persist it in the gitignored `.env.local` file (never commit secrets):

```bash
cd /opt/stacks/sglandsimple
# Add or replace the line in .env.local
# grep -q "^MCP_AUTH_TOKEN=" .env.local \
#   && sed -i 's/^MCP_AUTH_TOKEN=.*/MCP_AUTH_TOKEN=6f3e2c.../' .env.local \
#   || echo "MCP_AUTH_TOKEN=6f3e2c..." >> .env.local
docker compose up -d mcp
```

The server logs on startup whether auth is enabled:

```
[mcp] bearer auth enabled (token length 64)
#   vs
[mcp] WARNING: MCP_AUTH_TOKEN is not set; /mcp is open.
```

If `MCP_AUTH_TOKEN` is unset, every client request succeeds but the server is
completely open — use this only on LAN-trusted hosts.

---

## Session handshake (`Mcp-Session-Id`)

Every conversation with the MCP server is **stateful** (rate limit, idle TTL).
You must:

1. Call `initialize` once — the response carries a `Mcp-Session-Id` header:
2. Include that same `Mcp-Session-Id` header on **every** subsequent POST.

### Step-by-step curl walkthrough

```bash
# Set this to the value you generated above, or leave it empty if auth is off.
export MCP_AUTH_TOKEN="6f3e2c..."

export MCP_URL="http://192.168.29.36:5451/mcp"

# ──────────────────────────────
# 1) initialize  →  grab Session-Id
# ──────────────────────────────
INIT=$(curl -sS -i "$MCP_URL" \
  -H 'Content-Type: application/json' \
  ${MCP_AUTH_TOKEN:+-H "Authorization: Bearer $MCP_AUTH_TOKEN"} \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}')

echo "$INIT"

# Extract the session id from the response header.
SID=$(echo "$INIT" | awk '/^[Mm]cp-[Ss]ession-[Ii]d:/ {print $2}' | tr -d '\r')
echo "Session ID: $SID"

# ──────────────────────────────
# 2) list tools  (requires Session-Id + Bearer)
# ──────────────────────────────
curl -sS "$MCP_URL" \
  -H 'Content-Type: application/json' \
  ${MCP_AUTH_TOKEN:+-H "Authorization: Bearer $MCP_AUTH_TOKEN"} \
  -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | jq '.result.tools | map(.name)'

# ──────────────────────────────
# 3) call ask_data  (same session)
# ──────────────────────────────
curl -sS "$MCP_URL" \
  -H 'Content-Type: application/json' \
  ${MCP_AUTH_TOKEN:+-H "Authorization: Bearer $MCP_AUTH_TOKEN"} \
  -H "Mcp-Session-Id: $SID" \
  -d '{
    "jsonrpc":"2.0","id":3,"method":"tools/call",
    "params":{"name":"ask_data","arguments":{"question":"open tickets per priority"}}
  }' | jq '.result.content[0].text'
```

### What happens if you skip the session id?

```json
{"jsonrpc":"2.0","id":null,
 "error":{"code":-32003,"message":"Missing Mcp-Session-Id header"}}
```

HTTP `400`. The server expects every non-`initialize` POST to carry the
session id it handed out. If the session has expired (idle TTL defaults to
30 minutes) you get:

```json
{"jsonrpc":"2.0","id":null,
 "error":{"code":-32004,"message":"Unknown or expired session"}}
```

When that happens, simply `initialize` again for a fresh `Mcp-Session-Id`.

### What happens on a bad bearer token?

HTTP `401` with `WWW-Authenticate: Bearer realm="mcp"` and:

```json
{"jsonrpc":"2.0","id":null,
 "error":{"code":-32001,"message":"Unauthorized"}}
```

---

## Reachability

- LAN: `http://<your-host>:5451/mcp` — the host port.
- Public (after S3.expose.2 lands): one of
  - `https://${PUBLIC_HOSTNAME}/mcp` (path-routed on the existing host), or
  - `https://${MCP_PUBLIC_HOSTNAME}/mcp` (separate hostname).
  Decide and document in IMPLEMENT.md S3.expose.1.

## opencode

Add this entry to your opencode config (typically `~/.config/opencode/config.json`):

```json
{
  "mcp": {
    "sglandsimple": {
      "type": "remote",
      "url": "http://<your-host>:5451/mcp",
      "headers": {
        "Authorization": "Bearer <MCP_AUTH_TOKEN>"
      }
    }
  }
}
```

If `MCP_AUTH_TOKEN` is unset on the server, omit the `headers` block.

## VS Code Chat / GitHub Copilot Chat

`settings.json`:

```json
{
  "mcp.servers": {
    "sglandsimple": {
      "type": "http",
      "url": "http://<your-host>:5451/mcp",
      "headers": {
        "Authorization": "Bearer <MCP_AUTH_TOKEN>"
      }
    }
  }
}
```

## PiAgent / generic Streamable-HTTP MCP client

Most generic Streamable-HTTP clients want:

- URL: `http://<your-host>:5451/mcp`
- Method: POST for requests; GET for the keepalive SSE stream
- Headers:
  - `Content-Type: application/json`
  - `Authorization: Bearer <MCP_AUTH_TOKEN>` (if set)
  - `Mcp-Session-Id: <id from initialize response>` on every call after
    the first `initialize` exchange

## Quick smoke test (curl)

```bash
# 1. initialize; grab the session id from the response header
SID=$(curl -sS -i http://localhost:5451/mcp \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer $MCP_AUTH_TOKEN' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  | awk '/^mcp-session-id:/ {print $2}' | tr -d '\r')

# 2. list tools using that session
curl -sS http://localhost:5451/mcp \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $MCP_AUTH_TOKEN" \
  -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | jq '.result.tools | map(.name)'

# 3. call ask_data
curl -sS http://localhost:5451/mcp \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $MCP_AUTH_TOKEN" \
  -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"ask_data","arguments":{"question":"open tickets per priority"}}}'
```

## Notes

- The `GET /mcp` SSE stream currently emits only `event: ping` keepalives.
  Stage 3.2 (deferred) wires per-session response push for clients that
  prefer to receive responses on SSE rather than as the POST result.
- Streaming chat completions (`stream: true`) is not supported by the
  agent. MCP tool calls are non-streaming JSON-RPC and are unaffected.
