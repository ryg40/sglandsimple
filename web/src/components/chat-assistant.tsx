import { useMemo, useRef, useState, type ReactNode, type RefObject } from "react";
import {
  ArrowUpRight,
  Bot,
  Database,
  Loader2,
  MessageSquare,
  PanelBottomOpen,
  Send,
  Sparkles,
  Wand2,
} from "lucide-react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Markdown } from "@/components/markdown";
import { useAskData, useChat } from "@/lib/queries";
import type { ChatCompletion, ChatMessage } from "@/lib/types";
import { cn } from "@/lib/utils";

const CHAT_PROMPTS = [
  "Summarize the highest-risk findings across connected systems.",
  "What changed recently across Jira, GitHub, and docs?",
  "Draft an executive-ready status update for the leadership review.",
];

const DATA_PROMPTS = [
  "Show open tickets grouped by priority.",
  "Which documents mention audit logging?",
  "List employees by department and location.",
];

function reply(data: ChatCompletion): string {
  const content = data.choices?.[0]?.message?.content?.trim();
  if (content && data.error) return `${content}\n\n---\n\n**error detail:** ${JSON.stringify(data.error)}`;
  if (content) return content;
  if (data.error) return `**error:** ${JSON.stringify(data.error)}`;
  return "**No response content was returned.** The request completed without an assistant message.";
}

function useAssistantSession() {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const endRef = useRef<HTMLDivElement>(null);
  const chat = useChat();
  const askData = useAskData();
  const busy = chat.isPending || askData.isPending;

  const scroll = () => requestAnimationFrame(() => endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }));

  async function run(kind: "chat" | "ask", seed?: string) {
    const text = (seed ?? input).trim();
    if (!text || busy) return;
    setInput("");
    const userMsg: ChatMessage = { role: "user", content: kind === "ask" ? `(ask data) ${text}` : text };
    const next = [...messages, userMsg];
    setMessages(next);
    scroll();
    try {
      const data = kind === "ask" ? await askData.mutateAsync(text) : await chat.mutateAsync(next);
      setMessages((m) => [...m, { role: "assistant", content: reply(data) }]);
      scroll();
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      toast.error(`Request failed: ${message}`);
      setMessages((m) => [...m, { role: "assistant", content: `**error:** ${message}` }]);
    }
  }

  return {
    input,
    setInput,
    messages,
    busy,
    run,
    endRef,
  };
}

function PromptChips({
  label,
  prompts,
  onPick,
}: {
  label: string;
  prompts: string[];
  onPick: (prompt: string) => void;
}) {
  return (
    <div className="space-y-2">
      <div className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">{label}</div>
      <div className="flex flex-wrap gap-2">
        {prompts.map((prompt) => (
          <button
            key={prompt}
            type="button"
            onClick={() => onPick(prompt)}
            className="rounded-full border border-border bg-background/80 px-3 py-1.5 text-left text-xs text-foreground transition hover:border-primary/40 hover:bg-accent hover:text-accent-foreground"
          >
            {prompt}
          </button>
        ))}
      </div>
    </div>
  );
}

function ConversationFeed({
  messages,
  busy,
  endRef,
  empty,
  className,
}: {
  messages: ChatMessage[];
  busy: boolean;
  endRef: RefObject<HTMLDivElement>;
  empty: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("space-y-3 overflow-y-auto", className)} aria-live="polite">
      {messages.length === 0 && empty}
      {messages.map((m, i) => {
        const isUser = m.role === "user";
        return (
          <div key={i} className={cn("flex", isUser ? "justify-end" : "justify-start")}>
            <Card
              className={cn(
                "max-w-[90%] overflow-hidden border px-4 py-3 shadow-sm",
                isUser
                  ? "border-primary/20 bg-primary text-primary-foreground"
                  : "border-border bg-card/95 backdrop-blur"
              )}
            >
              <div className="mb-2 flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.2em] opacity-80">
                {isUser ? <Send className="size-3" /> : <Bot className="size-3" />}
                {isUser ? "You" : "LanGarland assistant"}
              </div>
              {isUser ? (
                <div className="whitespace-pre-wrap text-sm leading-6">{m.content}</div>
              ) : (
                <Markdown>{m.content}</Markdown>
              )}
            </Card>
          </div>
        );
      })}
      {busy && (
        <div className="flex items-center gap-2 rounded-full border border-border bg-card/80 px-3 py-2 text-sm text-muted-foreground shadow-sm w-fit">
          <Loader2 className="size-4 animate-spin" /> thinking…
        </div>
      )}
      <div ref={endRef} />
    </div>
  );
}

function Composer({
  input,
  setInput,
  onRun,
  busy,
  compact = false,
}: {
  input: string;
  setInput: (value: string) => void;
  onRun: (kind: "chat" | "ask") => void;
  busy: boolean;
  compact?: boolean;
}) {
  return (
    <form
      className={cn(
        "rounded-2xl border border-border bg-card/95 p-3 shadow-lg backdrop-blur",
        compact ? "space-y-3" : "space-y-3"
      )}
      onSubmit={(e) => {
        e.preventDefault();
        onRun("chat");
      }}
    >
      <label htmlFor={compact ? "assistant-panel-input" : "assistant-page-input"} className="sr-only">
        Message the assistant
      </label>
      <textarea
        id={compact ? "assistant-panel-input" : "assistant-page-input"}
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            onRun("chat");
          }
        }}
        rows={compact ? 3 : 4}
        placeholder="Ask for a summary, cross-system trace, or direct data pull…"
        className="w-full resize-none rounded-xl border border-input bg-background px-4 py-3 text-sm shadow-inner focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      />
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="text-xs text-muted-foreground">
          Use <span className="font-medium text-foreground">⌘/Ctrl + Enter</span> to send. Ask Data forces a Mongo-backed answer.
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" disabled={busy} onClick={() => onRun("ask")}>
            <Database className="size-4" /> Ask data
          </Button>
          <Button type="submit" disabled={busy}>
            <Send className="size-4" /> Send
          </Button>
        </div>
      </div>
    </form>
  );
}

export function ChatWorkspace() {
  const session = useAssistantSession();
  const insightCards = useMemo(
    () => [
      {
        icon: Sparkles,
        title: "Executive-ready synthesis",
        text: "Turn scattered Jira, GitHub, docs, and connector context into a crisp narrative.",
      },
      {
        icon: Database,
        title: "Grounded data pulls",
        text: "Use Ask Data for Mongo-backed answers when you need a concrete count or table.",
      },
      {
        icon: Wand2,
        title: "Next-step guidance",
        text: "Draft follow-ups, remediation plans, summaries, and handoff notes in the same workspace.",
      },
    ],
    []
  );

  return (
    <div className="min-h-full bg-[radial-gradient(circle_at_top_left,rgba(255,208,0,0.16),transparent_24%),radial-gradient(circle_at_top_right,rgba(6,116,140,0.14),transparent_22%)] px-4 py-5 sm:px-6 lg:px-8">
      <div className="mx-auto flex h-full max-w-7xl flex-col gap-5">
        <Card className="overflow-hidden border-primary/10 bg-[linear-gradient(135deg,rgba(26,20,70,0.98),rgba(26,20,70,0.9)_55%,rgba(6,116,140,0.76))] p-6 text-white shadow-2xl">
          <div className="grid gap-6 lg:grid-cols-[1.4fr_0.9fr] lg:items-end">
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="accent" className="bg-white/15 text-white">Focused assistant</Badge>
                <Badge variant="outline" className="border-white/20 text-white/80">Tool-aware</Badge>
                <Badge variant="outline" className="border-white/20 text-white/80">Ask Data ready</Badge>
              </div>
              <div className="space-y-2">
                <h2 className="max-w-3xl text-3xl font-semibold tracking-tight sm:text-4xl">
                  A richer command desk for cross-system analysis, grounded answers, and fast follow-through.
                </h2>
                <p className="max-w-2xl text-sm leading-6 text-white/80 sm:text-base">
                  Use the focused chat view when the assistant is your primary workspace. Pull direct data,
                  compare signals across systems, and turn findings into concise updates without leaving the app.
                </p>
              </div>
              <PromptChips label="Starter prompts" prompts={CHAT_PROMPTS} onPick={(prompt) => session.setInput(prompt)} />
            </div>

            <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-1">
              {insightCards.map((item) => (
                <div key={item.title} className="rounded-2xl border border-white/10 bg-white/10 p-4 backdrop-blur-sm">
                  <div className="mb-3 flex size-10 items-center justify-center rounded-xl bg-white/15">
                    <item.icon className="size-5 text-primary" />
                  </div>
                  <div className="text-sm font-semibold">{item.title}</div>
                  <p className="mt-1 text-xs leading-5 text-white/75">{item.text}</p>
                </div>
              ))}
            </div>
          </div>
        </Card>

        <div className="grid min-h-0 flex-1 gap-5 xl:grid-cols-[18rem_minmax(0,1fr)]">
          <div className="space-y-4 xl:order-2">
            <Card className="border-border/80 bg-card/90 p-4 shadow-sm">
              <div className="mb-3 flex items-center gap-2">
                <MessageSquare className="size-4 text-secondary" />
                <h3 className="text-sm font-semibold">Context rail</h3>
              </div>
              <div className="space-y-3 text-sm text-muted-foreground">
                <div className="rounded-xl border border-border bg-background/70 p-3">
                  <div className="mb-1 text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">Best for</div>
                  Cross-system questions, summary drafting, connector-aware guidance, and MCP tool-assisted answers.
                </div>
                <div className="rounded-xl border border-border bg-background/70 p-3">
                  <div className="mb-1 text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">Power move</div>
                  Start in natural language, then switch to <span className="font-medium text-foreground">Ask Data</span> when you need a grounded result set.
                </div>
                <PromptChips label="Direct data prompts" prompts={DATA_PROMPTS} onPick={(prompt) => session.run("ask", prompt)} />
              </div>
            </Card>
          </div>

          <div className="flex min-h-[36rem] flex-col gap-4 xl:order-1">
            <Card className="flex min-h-0 flex-1 flex-col border-border/80 bg-card/92 p-4 shadow-xl sm:p-5">
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3 border-b border-border pb-4">
                <div>
                  <div className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">Live conversation</div>
                  <h3 className="text-lg font-semibold">Strategy, synthesis, and evidence in one thread</h3>
                </div>
                <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                  <Badge variant="outline">{session.messages.length} messages</Badge>
                  <Badge variant="outline">MCP-enabled</Badge>
                </div>
              </div>

              <ConversationFeed
                messages={session.messages}
                busy={session.busy}
                endRef={session.endRef}
                className="min-h-0 flex-1 pr-1"
                empty={
                  <div className="flex h-full min-h-[18rem] flex-col items-center justify-center rounded-2xl border border-dashed border-border bg-background/50 px-6 text-center">
                    <div className="mb-4 flex size-14 items-center justify-center rounded-2xl bg-primary/10 text-primary">
                      <Bot className="size-7" />
                    </div>
                    <h4 className="text-base font-semibold">Start with a question, a ticket review, or an evidence request.</h4>
                    <p className="mt-2 max-w-xl text-sm leading-6 text-muted-foreground">
                      The assistant can summarize connected systems, draft updates, or route you into Ask Data for explicit Mongo-backed answers.
                    </p>
                  </div>
                }
              />
            </Card>

            <Composer
              input={session.input}
              setInput={session.setInput}
              onRun={(kind) => session.run(kind)}
              busy={session.busy}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

export function GlobalAssistant() {
  const [open, setOpen] = useState(false);
  const session = useAssistantSession();
  const latestPreview = session.messages.at(-1)?.content?.replace(/[#*_`>-]/g, " ").trim() ?? "Ask for a summary, a status pull, or direct data help.";

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="fixed bottom-4 right-4 z-30 flex w-[min(24rem,calc(100vw-2rem))] items-center gap-3 rounded-2xl border border-border bg-card/95 px-4 py-3 text-left shadow-2xl backdrop-blur transition hover:border-primary/40 hover:shadow-primary/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:bottom-5 sm:right-5"
        aria-label="Open assistant"
      >
        <div className="flex size-10 shrink-0 items-center justify-center rounded-2xl bg-primary text-primary-foreground shadow-sm">
          <PanelBottomOpen className="size-5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold">Assistant</span>
            <Badge variant="outline" className="text-[10px]">Global</Badge>
          </div>
          <p className="truncate text-xs text-muted-foreground">{latestPreview}</p>
        </div>
        <ArrowUpRight className="size-4 shrink-0 text-muted-foreground" />
      </button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="bottom-4 left-1/2 top-auto grid h-[min(85vh,42rem)] w-[min(44rem,calc(100vw-1.5rem))] translate-x-[-50%] translate-y-0 gap-0 rounded-3xl border-border p-0 sm:bottom-5 sm:left-auto sm:right-5 sm:w-[42rem] sm:translate-x-0">
          <DialogHeader className="border-b border-border bg-[linear-gradient(135deg,rgba(26,20,70,0.98),rgba(6,116,140,0.9))] px-5 py-4 text-white">
            <DialogTitle className="flex items-center gap-2 text-white">
              <Bot className="size-5 text-primary" /> LanGarland assistant
            </DialogTitle>
            <DialogDescription className="text-white/75">
              Quick help from any workspace. Ask a question, pull direct data, or continue in the focused chat view.
            </DialogDescription>
          </DialogHeader>

          <div className="flex min-h-0 flex-1 flex-col bg-background/95">
            <div className="border-b border-border px-5 py-3">
              <PromptChips label="Quick prompts" prompts={CHAT_PROMPTS.slice(0, 2)} onPick={(prompt) => session.setInput(prompt)} />
            </div>

            <ConversationFeed
              messages={session.messages}
              busy={session.busy}
              endRef={session.endRef}
              className="min-h-0 flex-1 px-5 py-4"
              empty={
                <div className="flex h-full min-h-[14rem] flex-col items-center justify-center rounded-2xl border border-dashed border-border bg-card/40 px-5 text-center">
                  <div className="mb-3 flex size-12 items-center justify-center rounded-2xl bg-secondary/15 text-secondary">
                    <Bot className="size-6" />
                  </div>
                  <p className="text-sm font-medium">Need a quick answer without leaving this page?</p>
                  <p className="mt-1 max-w-md text-sm text-muted-foreground">
                    Use the compact assistant here, or jump to the full chat view when the conversation becomes the main task.
                  </p>
                </div>
              }
            />

            <div className="space-y-3 border-t border-border p-4">
              <Composer
                input={session.input}
                setInput={session.setInput}
                onRun={(kind) => session.run(kind)}
                busy={session.busy}
                compact
              />
              <div className="flex flex-wrap justify-end gap-2">
                <Button variant="outline" size="sm" asChild>
                  <Link to="/chat" onClick={() => setOpen(false)}>
                    Open full chat
                  </Link>
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>
                  Keep working here
                </Button>
              </div>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
