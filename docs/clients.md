# Connecting external MCP clients

The MCP server at `mcp:8080/mcp` (host port `${MCP_PORT}`, default `5451`)
speaks JSON-RPC 2.0 over HTTP POST with a per-session SSE stream on
`GET /mcp`. Stage 3 adds:

- A `Mcp-Session-Id` header returned on `initialize` and required on
every subsequent request.
- Optional bearer auth via `MCP_AUTH_TOKEN`. If unset, the server logs a
startup warning and accepts unauthenticated requests.
- A per-session token-bucket rate limit (`MCP_RATE_PER_MIN`, default 60).
- `GET /mcp` SSE framing (`event: ready`, `event: ping`, and
  `event: message` for mirrored JSON-RPC responses). Normal POST responses
  remain synchronous for compatibility; clients can opt into SSE-only POST
  delivery with `Prefer: respond-async` or `X-MCP-Response-Mode: sse`.

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
- Method: POST for requests; GET for the per-session SSE stream
- Headers:
  - `Content-Type: application/json`
  - `Authorization: Bearer <MCP_AUTH_TOKEN>` (if set)
  - `Mcp-Session-Id: <id from initialize response>` on every call after
    the first `initialize` exchange, including `GET /mcp`

`GET /mcp` emits:

- `event: ready` once when the stream opens
- `event: ping` every ~15 seconds while idle
- `event: message` with JSON-RPC responses mirrored from POST calls for the
  same session

By default POST still returns the JSON-RPC response synchronously. If a client
keeps `GET /mcp` open and wants the response only on that SSE stream, add one
of these request headers to the POST:

```http
Prefer: respond-async
# or
X-MCP-Response-Mode: sse
```

The POST then returns HTTP `202` and the JSON-RPC response is delivered as an
SSE `message` event.

## Quick smoke test (curl)

```bash
# 1. initialize; grab the session id from the response header
SID=$(curl -sS -i http://localhost:5451/mcp \
  -H 'Content-Type: application/json' \
  ${MCP_AUTH_TOKEN:+-H "Authorization: Bearer $MCP_AUTH_TOKEN"} \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  | awk '/^[Mm]cp-[Ss]ession-[Ii]d:/ {print $2}' | tr -d '\r')

# 2. list tools using that session
curl -sS http://localhost:5451/mcp \
  -H 'Content-Type: application/json' \
  ${MCP_AUTH_TOKEN:+-H "Authorization: Bearer $MCP_AUTH_TOKEN"} \
  -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | jq '.result.tools | map(.name)'

# 3. call ask_data
curl -sS http://localhost:5451/mcp \
  -H 'Content-Type: application/json' \
  ${MCP_AUTH_TOKEN:+-H "Authorization: Bearer $MCP_AUTH_TOKEN"} \
  -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"ask_data","arguments":{"question":"open tickets per priority"}}}'
```

## SSE smoke test (curl)

Open a receive stream with the session id:

```bash
curl -N http://localhost:5451/mcp \
  ${MCP_AUTH_TOKEN:+-H "Authorization: Bearer $MCP_AUTH_TOKEN"} \
  -H "Mcp-Session-Id: $SID"
```

In another shell, send a request through the same session. The synchronous
response is still returned by POST and also appears as `event: message` on the
SSE stream:

```bash
curl -sS http://localhost:5451/mcp \
  -H 'Content-Type: application/json' \
  ${MCP_AUTH_TOKEN:+-H "Authorization: Bearer $MCP_AUTH_TOKEN"} \
  -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","id":4,"method":"ping"}'
```

For SSE-only delivery:

```bash
curl -i http://localhost:5451/mcp \
  -H 'Content-Type: application/json' \
  ${MCP_AUTH_TOKEN:+-H "Authorization: Bearer $MCP_AUTH_TOKEN"} \
  -H "Mcp-Session-Id: $SID" \
  -H 'Prefer: respond-async' \
  -d '{"jsonrpc":"2.0","id":5,"method":"tools/list"}'
# HTTP 202; response arrives as event: message on GET /mcp
```

## Chat runtime visibility (`chat_runtime_info`)

The MCP server exposes a `chat_runtime_info` tool that reports which LLM
runtime answers chat and delegated Deep-Agent work, for operators who want to
confirm routing without reading env vars off a host:

```bash
curl -s http://localhost:5451/mcp \
  -H 'Content-Type: application/json' \
  ${MCP_AUTH_TOKEN:+-H "Authorization: Bearer $MCP_AUTH_TOKEN"} \
  -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","id":6,"method":"tools/call",
       "params":{"name":"chat_runtime_info","arguments":{}}}'
```

The JSON content block contains `chat_agent` (the public agent's
provider/model/redacted endpoint) and `platform` (the orchestrator and each
system agent mapped to its resolved role). **Endpoints are redacted to host +
path only — no API keys, credentials, or query strings are ever returned.**
Provider labels are inferred from the host (or an optional `<PREFIX>_PROVIDER`
env var) and are display hints only; every role still speaks the
OpenAI-compatible protocol.

In the web app, the `/chat` page surfaces the same data in a read-only
**Runtime routing** panel via the authenticated `GET /api/chat/runtime` proxy
(any chat reader may view it). Admins additionally see a marker that
admin-selectable provider/model routing is planned but not yet implemented.

## Notes

- Streaming chat completions (`stream: true`) is not supported by the
  agent. MCP tool calls are non-streaming JSON-RPC and are unaffected.
