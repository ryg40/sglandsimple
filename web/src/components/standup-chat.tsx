import { FormEvent, ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link2, MessageSquare, Radio, RefreshCw, UsersRound, WifiOff } from "lucide-react";
import { useAuth } from "@/components/auth-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

type ConnectionStatus = "connecting" | "connected" | "reconnecting" | "local" | "error";

type StandupChatMessage = {
  id: string;
  clientMessageId?: string;
  author: string;
  authorEmail?: string;
  body: string;
  createdAt: string;
  pending?: boolean;
  deliveryStatus?: "sending" | "sent";
  source?: "seed" | "local" | "server";
};

type PresenceParticipant = {
  id: string;
  displayName: string;
  email?: string;
};

type PresenceState = {
  count: number;
  participants: PresenceParticipant[];
};

type ConnectionState = {
  status: ConnectionStatus;
  detail: string;
};

export type StandupAssociation = {
  token: string;
  kind: "jira" | "confluence" | "github" | "servicenow" | "archer" | "snowflake" | "mongodb" | "mention" | "url";
  sourceMessageId: string;
  sourceAuthor: string;
};

export type StandupTraceState = {
  connection: ConnectionState;
  presence: PresenceState;
  messageCount: number;
  associationCount: number;
};

export type StandupProposalApproval = {
  actor?: string;
  decision?: string;
  decided_at?: string;
  dry_run_only?: boolean;
  applied?: boolean;
  apply_result?: Record<string, unknown>;
} | null;

export type StandupProposal = {
  id: string;
  type?: string;
  target_service?: string;
  title?: string;
  rationale?: string;
  status: "proposed" | "approved" | "rejected" | string;
  dry_run?: boolean;
  dry_run_payload?: Record<string, unknown>;
  validation_state?: Record<string, unknown>;
  source_message_ids?: string[];
  confidence?: number | null;
  approval?: StandupProposalApproval;
  created_by?: string;
  created_at?: string;
  updated_at?: string;
};

/** Imperative controls the parent route uses to drive the approval tray. */
export type StandupControls = {
  proposals: StandupProposal[];
  /** True when a live websocket is connected and can carry actions. */
  canSend: boolean;
  summarize: () => void;
  approve: (proposalId: string) => void;
  reject: (proposalId: string) => void;
  edit: (proposalId: string, dryRunPayload: Record<string, unknown>) => void;
  summarizing: boolean;
};

type StandupChatProps = {
  sessionId?: string;
  onAssociationCountChange?: (count: number) => void;
  onAssociationsChange?: (associations: StandupAssociation[]) => void;
  onTraceChange?: (trace: StandupTraceState) => void;
  onControlsChange?: (controls: StandupControls) => void;
};

function normalizeProposal(raw: unknown): StandupProposal | null {
  if (!raw || typeof raw !== "object") return null;
  const record = raw as Record<string, unknown>;
  const id = record.id;
  if (typeof id !== "string" || !id) return null;
  return { ...(record as StandupProposal), id, status: String(record.status ?? "proposed") };
}

function mergeProposals(current: StandupProposal[], incoming: StandupProposal[]): StandupProposal[] {
  const byId = new Map<string, StandupProposal>();
  for (const proposal of current) byId.set(proposal.id, proposal);
  for (const proposal of incoming) byId.set(proposal.id, { ...byId.get(proposal.id), ...proposal });
  return Array.from(byId.values());
}

const MAX_RECONNECT_ATTEMPTS = 2;

const INITIAL_MESSAGES: StandupChatMessage[] = [
  {
    id: "seed-1",
    author: "Scrum master",
    body: "Keep notes here while triaging Jira. Live websocket persistence keeps the session available across refreshes.",
    createdAt: "09:00",
    source: "seed",
  },
  {
    id: "seed-2",
    author: "Agent preview",
    body: "Dry-run only: candidate follow-ups should route through the existing Jira stage / validate / apply gates.",
    createdAt: "09:01",
    source: "seed",
  },
];

const TOKEN_PATTERN = /(https?:\/\/[^\s<>()]+|\b[A-Z][A-Z0-9]+-\d+\b|@[A-Za-z][\w.-]{1,63})/g;

function makeId(prefix: string) {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function formatTime(value: unknown) {
  if (typeof value === "string" && value.trim()) {
    const date = new Date(value);
    if (!Number.isNaN(date.getTime())) {
      return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    }
    return value;
  }
  return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function normalizeMessage(raw: unknown): StandupChatMessage | null {
  if (!raw || typeof raw !== "object") return null;
  const record = raw as Record<string, unknown>;
  const body = record.body ?? record.text ?? record.content;
  if (typeof body !== "string" || !body.trim()) return null;
  const author = record.author ?? record.user ?? record.name ?? "Participant";
  return {
    id: String(record.id ?? record.message_id ?? makeId("server")),
    clientMessageId: typeof record.client_message_id === "string" && record.client_message_id ? record.client_message_id : undefined,
    author: typeof author === "string" && author.trim() ? author : "Participant",
    authorEmail: typeof record.author_email === "string" ? record.author_email : undefined,
    body,
    createdAt: formatTime(record.createdAt ?? record.created_at ?? record.timestamp),
    source: "server",
  };
}

function normalizeMessages(raw: unknown): StandupChatMessage[] {
  if (!Array.isArray(raw)) return [];
  return raw.map(normalizeMessage).filter((message): message is StandupChatMessage => Boolean(message));
}

function mergeMessages(messages: StandupChatMessage[]) {
  const byId = new Map<string, StandupChatMessage>();
  const localIds = new Set(messages.filter((message) => message.source === "local").map((message) => message.id));
  const clientToServerId = new Map<string, string>();
  for (const message of messages) {
    if (message.source === "server" && message.clientMessageId) {
      clientToServerId.set(message.clientMessageId, message.id);
    }
  }
  for (const message of messages) {
    const replacementId = clientToServerId.get(message.id);
    if (message.source === "local" && replacementId) continue;
    const existing = byId.get(message.id);
    const acknowledgedLocal = message.source === "server" && Boolean(message.clientMessageId && localIds.has(message.clientMessageId));
    byId.set(message.id, {
      ...existing,
      ...message,
      pending: acknowledgedLocal ? false : message.pending ?? existing?.pending ?? false,
      deliveryStatus: acknowledgedLocal ? "sent" : message.deliveryStatus ?? existing?.deliveryStatus,
    });
  }
  return Array.from(byId.values());
}

function extractTokens(body: string) {
  return Array.from(body.matchAll(TOKEN_PATTERN), (match) => match[0]);
}

function classifyToken(token: string): StandupAssociation["kind"] {
  const lower = token.toLowerCase();
  if (token.startsWith("@")) return "mention";
  if (/^[A-Z][A-Z0-9]+-\d+$/.test(token) || lower.includes("jira")) return "jira";
  if (lower.includes("confluence") || lower.includes("/wiki/")) return "confluence";
  if (lower.includes("github.com")) return "github";
  if (lower.includes("servicenow") || lower.includes("snow") || /\b(?:inc|chg|ritm)\d+\b/i.test(token)) return "servicenow";
  if (lower.includes("archer")) return "archer";
  if (lower.includes("snowflake")) return "snowflake";
  if (lower.includes("mongodb") || lower.includes("mongo")) return "mongodb";
  return "url";
}

function getAssociations(messages: StandupChatMessage[]) {
  const byKey = new Map<string, StandupAssociation>();
  for (const message of messages) {
    for (const token of extractTokens(message.body)) {
      const kind = classifyToken(token);
      const key = `${kind}:${token}`;
      if (!byKey.has(key)) {
        byKey.set(key, {
          token,
          kind,
          sourceMessageId: message.id,
          sourceAuthor: message.author,
        });
      }
    }
  }
  return Array.from(byKey.values());
}

function getWsUrl(sessionId: string) {
  const url = new URL(`/api/standup/ws/${encodeURIComponent(sessionId)}`, window.location.origin);
  url.protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

function unwrapPayload(event: Record<string, unknown>) {
  const payload = event.payload ?? event.data;
  return payload && typeof payload === "object" ? (payload as Record<string, unknown>) : event;
}

function normalizePresence(raw: Record<string, unknown>): PresenceState | null {
  const participantsRaw = raw.participants ?? raw.users ?? raw.members;
  const participants = Array.isArray(participantsRaw)
    ? participantsRaw
        .map((participant, index): PresenceParticipant | null => {
          if (typeof participant === "string") return { id: participant, displayName: participant };
          if (participant && typeof participant === "object") {
            const record = participant as Record<string, unknown>;
            const name = record.display_name ?? record.name ?? record.author ?? record.user ?? record.id;
            const email = record.email;
            const id = record.client_id ?? record.id ?? email ?? name ?? index;
            return typeof name === "string" && name.trim()
              ? {
                  id: String(id),
                  displayName: name,
                  email: typeof email === "string" && email.trim() ? email : undefined,
                }
              : null;
          }
          return null;
        })
        .filter((participant): participant is PresenceParticipant => Boolean(participant))
    : [];
  const countRaw = raw.count ?? raw.online ?? raw.participant_count;
  const count = typeof countRaw === "number" ? countRaw : participants.length;
  if (count === 0 && participants.length === 0) return null;
  return { count: Math.max(count, participants.length), participants };
}

function renderMessageBody(body: string) {
  const parts: ReactNode[] = [];
  let lastIndex = 0;
  for (const match of body.matchAll(TOKEN_PATTERN)) {
    const token = match[0];
    const index = match.index ?? 0;
    if (index > lastIndex) parts.push(body.slice(lastIndex, index));
    if (token.startsWith("http")) {
      parts.push(
        <a
          key={`${token}-${index}`}
          href={token}
          target="_blank"
          rel="noreferrer"
          className="font-medium text-primary underline-offset-2 hover:underline"
        >
          {token}
        </a>,
      );
    } else if (token.startsWith("@")) {
      parts.push(
        <span key={`${token}-${index}`} className="rounded bg-primary/10 px-1 font-medium text-primary">
          {token}
        </span>,
      );
    } else {
      parts.push(
        <span key={`${token}-${index}`} className="font-mono font-medium text-primary">
          {token}
        </span>,
      );
    }
    lastIndex = index + token.length;
  }
  if (lastIndex < body.length) parts.push(body.slice(lastIndex));
  return parts;
}

function statusBadgeVariant(status: ConnectionStatus) {
  if (status === "connected") return "success";
  if (status === "error") return "destructive";
  if (status === "local") return "outline";
  return "warning";
}

export function StandupChat({
  sessionId = "daily-standup",
  onAssociationCountChange,
  onAssociationsChange,
  onTraceChange,
  onControlsChange,
}: StandupChatProps) {
  const { me } = useAuth();
  const [messages, setMessages] = useState<StandupChatMessage[]>(INITIAL_MESSAGES);
  const [proposals, setProposals] = useState<StandupProposal[]>([]);
  const [summarizing, setSummarizing] = useState(false);
  const [draft, setDraft] = useState("");
  const [connection, setConnection] = useState<ConnectionState>({
    status: "connecting",
    detail: "Opening live standup websocket…",
  });
  const [presence, setPresence] = useState<PresenceState>({ count: 1, participants: [{ id: "local", displayName: "You" }] });
  const [retryToken, setRetryToken] = useState(0);
  const socketRef = useRef<WebSocket | null>(null);
  const reconnectAttemptRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const clientIdRef = useRef(makeId("client"));
  const fallbackAuthor = useMemo(() => `Browser ${clientIdRef.current.slice(-4)}`, []);
  const displayName = me?.authenticated && me.user?.display_name ? me.user.display_name : fallbackAuthor;
  const email = me?.authenticated && me.user?.email ? me.user.email : "";
  const authorRef = useRef(displayName);
  const emailRef = useRef(email);

  useEffect(() => {
    authorRef.current = displayName;
    emailRef.current = email;
  }, [displayName, email]);

  const associations = useMemo(() => getAssociations(messages), [messages]);
  const associationCount = associations.length;

  useEffect(() => {
    onAssociationCountChange?.(associationCount);
  }, [associationCount, onAssociationCountChange]);

  useEffect(() => {
    onAssociationsChange?.(associations);
  }, [associations, onAssociationsChange]);

  useEffect(() => {
    onTraceChange?.({
      connection,
      presence,
      messageCount: messages.length,
      associationCount,
    });
  }, [associationCount, connection, messages.length, onTraceChange, presence]);

  const handleServerEvent = useCallback((raw: string) => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      return;
    }
    if (!parsed || typeof parsed !== "object") return;
    const event = parsed as Record<string, unknown>;
    const type = String(event.type ?? event.event ?? event.kind ?? "");
    const payload = unwrapPayload(event);

    if (type === "session.snapshot" || type === "snapshot") {
      const snapshot = payload.snapshot && typeof payload.snapshot === "object" ? (payload.snapshot as Record<string, unknown>) : payload;
      const messagesRaw = snapshot.messages ?? snapshot.chat ?? snapshot.history;
      const incoming = normalizeMessages(messagesRaw);
      setMessages((current) =>
        mergeMessages([
          ...incoming,
          ...current.filter((message) => message.source === "local" || message.pending),
        ]),
      );
      const presenceRaw = snapshot.presence && typeof snapshot.presence === "object" ? (snapshot.presence as Record<string, unknown>) : snapshot;
      const nextPresence = normalizePresence(presenceRaw);
      if (nextPresence) setPresence(nextPresence);
      const proposalsRaw = snapshot.proposals;
      if (Array.isArray(proposalsRaw)) {
        const incoming = proposalsRaw.map(normalizeProposal).filter((p): p is StandupProposal => Boolean(p));
        setProposals((current) => mergeProposals(current, incoming));
      }
      return;
    }

    if (type === "agent.running") {
      setSummarizing(true);
      return;
    }

    if (type === "agent.summary") {
      setSummarizing(false);
      const proposalsRaw = payload.proposals;
      if (Array.isArray(proposalsRaw)) {
        const incoming = proposalsRaw.map(normalizeProposal).filter((p): p is StandupProposal => Boolean(p));
        setProposals((current) => mergeProposals(current, incoming));
      }
      return;
    }

    if (type === "proposal.created" || type === "proposal.updated") {
      const proposal = normalizeProposal(payload.proposal ?? payload);
      if (proposal) setProposals((current) => mergeProposals(current, [proposal]));
      return;
    }

    if (type === "chat.message" || type === "chat") {
      const message = normalizeMessage(payload.message ?? payload);
      if (!message) return;
      setMessages((current) => mergeMessages([...current, message]));
      return;
    }

    if (type === "presence.update" || type === "presence") {
      const presenceRaw = payload.presence && typeof payload.presence === "object" ? (payload.presence as Record<string, unknown>) : payload;
      const nextPresence = normalizePresence(presenceRaw);
      if (nextPresence) setPresence(nextPresence);
      return;
    }

    if (type === "error") {
      setSummarizing(false);
      const errorObj = payload.error && typeof payload.error === "object" ? (payload.error as Record<string, unknown>) : payload;
      const detail = errorObj.message ?? errorObj.detail ?? payload.message ?? payload.detail ?? "Standup websocket reported an error.";
      setConnection({ status: "error", detail: String(detail) });
    }
  }, []);

  useEffect(() => {
    if (typeof WebSocket === "undefined") {
      setConnection({ status: "local", detail: "This browser does not support websockets; notes stay local." });
      return;
    }

    let closedByEffect = false;
    let opened = false;
    const status: ConnectionStatus = reconnectAttemptRef.current > 0 ? "reconnecting" : "connecting";
    setConnection({
      status,
      detail: status === "reconnecting" ? "Reconnecting live standup chat…" : "Opening live standup websocket…",
    });

    const ws = new WebSocket(getWsUrl(sessionId));
    socketRef.current = ws;

    ws.onopen = () => {
      opened = true;
      reconnectAttemptRef.current = 0;
      setConnection({ status: "connected", detail: "Live websocket connected." });
      ws.send(
        JSON.stringify({
          type: "join",
          session_id: sessionId,
          client_id: clientIdRef.current,
          author: authorRef.current,
          display_name: authorRef.current,
          email: emailRef.current,
        }),
      );
    };

    ws.onmessage = (event) => {
      if (typeof event.data === "string") handleServerEvent(event.data);
    };

    ws.onerror = () => {
      if (!opened) {
        setConnection({
          status: "reconnecting",
          detail: "Live standup websocket is not available yet; retrying before switching to local capture.",
        });
      }
    };

    ws.onclose = () => {
      if (closedByEffect) return;
      socketRef.current = null;
      if (reconnectAttemptRef.current < MAX_RECONNECT_ATTEMPTS) {
        reconnectAttemptRef.current += 1;
        const delay = reconnectAttemptRef.current * 1200;
        setConnection({
          status: "reconnecting",
          detail: `Live chat disconnected; reconnecting in ${Math.round(delay / 1000)}s…`,
        });
        reconnectTimerRef.current = setTimeout(() => setRetryToken((token) => token + 1), delay);
      } else {
        setConnection({
          status: "local",
          detail: "Live websocket endpoint is absent or unreachable; notes are captured locally in this browser.",
        });
      }
    };

    return () => {
      closedByEffect = true;
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      if (socketRef.current === ws) socketRef.current = null;
      ws.close();
    };
  }, [displayName, email, handleServerEvent, retryToken, sessionId]);

  function addLocalMessage(body: string, pending = false) {
    const message: StandupChatMessage = {
      id: makeId(pending ? "client" : "local"),
      author: authorRef.current || "You",
      authorEmail: emailRef.current,
      body,
      createdAt: formatTime(undefined),
      pending,
      deliveryStatus: pending ? "sending" : undefined,
      source: "local",
    };
    setMessages((current) => mergeMessages([...current, message]));
    return message;
  }

  function retryLiveConnection() {
    if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
    socketRef.current?.close();
    socketRef.current = null;
    reconnectAttemptRef.current = 0;
    setRetryToken((token) => token + 1);
  }

  const sendEvent = useCallback((type: string, payload: Record<string, unknown>) => {
    const socket = socketRef.current;
    if (connection.status !== "connected" || socket?.readyState !== WebSocket.OPEN) return false;
    try {
      socket.send(JSON.stringify({ type, session_id: sessionId, ...payload }));
      return true;
    } catch {
      return false;
    }
  }, [connection.status, sessionId]);

  const canSend = connection.status === "connected";

  const summarize = useCallback(() => {
    if (sendEvent("agent.summarize", { trigger: "manual" })) setSummarizing(true);
  }, [sendEvent]);

  const approve = useCallback((proposalId: string) => {
    sendEvent("proposal.approve", { proposal_id: proposalId });
  }, [sendEvent]);

  const reject = useCallback((proposalId: string) => {
    sendEvent("proposal.reject", { proposal_id: proposalId });
  }, [sendEvent]);

  const edit = useCallback((proposalId: string, dryRunPayload: Record<string, unknown>) => {
    sendEvent("proposal.edit", { proposal_id: proposalId, dry_run_payload: dryRunPayload });
  }, [sendEvent]);

  useEffect(() => {
    onControlsChange?.({ proposals, canSend, summarize, approve, reject, edit, summarizing });
  }, [approve, canSend, edit, onControlsChange, proposals, reject, summarize, summarizing]);

  function addMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const body = draft.trim();
    if (!body) return;

    const socket = socketRef.current;
    const canSend = connection.status === "connected" && socket?.readyState === WebSocket.OPEN;
    const message = addLocalMessage(body, canSend);
    setDraft("");

    if (!canSend) {
      if (connection.status !== "local") {
        setConnection({
          status: connection.status,
          detail: "Captured locally while live standup chat connects.",
        });
      }
      return;
    }

    try {
      socket.send(
        JSON.stringify({
          type: "chat.message",
          session_id: sessionId,
          id: message.id,
          client_id: clientIdRef.current,
          author: authorRef.current,
          display_name: authorRef.current,
          email: emailRef.current,
          body,
        }),
      );
    } catch {
      setConnection({
        status: "local",
        detail: "Live send failed; this note remains local and you can retry the websocket.",
      });
    }
  }

  return (
    <Card className="flex min-h-[22rem] flex-1 flex-col overflow-hidden">
      <CardHeader className="border-b bg-muted/20 pb-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <MessageSquare className="size-4 text-primary" />
              Standup chat
            </CardTitle>
            <CardDescription>Live session chat with local fallback when the websocket endpoint is absent.</CardDescription>
          </div>
          <Badge variant={statusBadgeVariant(connection.status)} className="gap-1 whitespace-nowrap text-[10px]">
            {connection.status === "local" ? <WifiOff className="size-3" /> : <Radio className="size-3" />}
            {connection.status}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="flex min-h-0 flex-1 flex-col gap-3 p-3">
        <div className="rounded-md border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span>{connection.detail}</span>
            {connection.status !== "connected" && (
              <Button type="button" variant="ghost" size="sm" onClick={retryLiveConnection} className="h-6 px-2">
                <RefreshCw className="size-3" />
                Retry live
              </Button>
            )}
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <UsersRound className="size-3.5" />
            <span>{presence.count} present</span>
            {presence.participants.slice(0, 4).map((participant) => (
              <Badge key={participant.id} variant="outline" className="text-[10px]" title={participant.email}>
                {participant.displayName}
              </Badge>
            ))}
          </div>
        </div>

        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
          {messages.length === 0 ? (
            <div className="rounded-lg border border-dashed bg-muted/20 p-4 text-center text-sm text-muted-foreground">
              No standup messages yet. Add a note, Jira key, link, or @mention to start capturing context.
            </div>
          ) : (
            messages.map((message) => {
              const tokens = extractTokens(message.body);
              return (
                <div key={message.id} className="rounded-lg border bg-card p-3 text-sm shadow-sm">
                  <div className="mb-1 flex items-center justify-between gap-2 text-xs">
                    <span className="font-medium">{message.author}</span>
                    <span className="text-muted-foreground">
                      {message.deliveryStatus ? `${message.deliveryStatus} · ` : ""}
                      {message.createdAt}
                    </span>
                  </div>
                  <p className="break-words text-sm leading-relaxed">{renderMessageBody(message.body)}</p>
                  {tokens.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {tokens.map((token) => (
                        <Badge key={`${message.id}-${token}`} variant="outline" className="gap-1 font-mono text-[10px]">
                          <Link2 className="size-3" />
                          {token}
                        </Badge>
                      ))}
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>

        <form onSubmit={addMessage} className="flex gap-2">
          <Input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Add a standup note, Jira key, link, or @mention…"
            aria-label="Standup note"
          />
          <Button type="submit">Add</Button>
        </form>
      </CardContent>
    </Card>
  );
}
