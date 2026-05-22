import { useRef, useState } from "react";
import { Loader2, Send, Database } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Markdown } from "@/components/markdown";
import { useAskData, useChat } from "@/lib/queries";
import type { ChatCompletion, ChatMessage } from "@/lib/types";
import { cn } from "@/lib/utils";

function reply(data: ChatCompletion): string {
  const content = data.choices?.[0]?.message?.content?.trim();
  if (content && data.error) return `${content}\n\n---\n\n**error detail:** ${JSON.stringify(data.error)}`;
  if (content) return content;
  if (data.error) return `**error:** ${JSON.stringify(data.error)}`;
  return "**No response content was returned.** The request completed without an assistant message.";
}

export default function Chat() {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const chat = useChat();
  const askData = useAskData();
  const busy = chat.isPending || askData.isPending;
  const endRef = useRef<HTMLDivElement>(null);

  const scroll = () => requestAnimationFrame(() => endRef.current?.scrollIntoView({ behavior: "smooth" }));

  async function run(kind: "chat" | "ask") {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    const userMsg: ChatMessage = { role: "user", content: kind === "ask" ? `(ask data) ${text}` : text };
    const next = [...messages, userMsg];
    setMessages(next);
    scroll();
    try {
      const data =
        kind === "ask"
          ? await askData.mutateAsync(text)
          : await chat.mutateAsync([...messages, { role: "user", content: text }]);
      setMessages((m) => [...m, { role: "assistant", content: reply(data) }]);
      scroll();
    } catch (e) {
      toast.error(`Request failed: ${(e as Error).message}`);
      setMessages((m) => [...m, { role: "assistant", content: `**error:** ${(e as Error).message}` }]);
    }
  }

  return (
    <div className="mx-auto flex h-full max-w-4xl flex-col p-5">
      <div className="flex-1 space-y-3 overflow-y-auto pb-4" aria-live="polite">
        {messages.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center text-center text-sm text-muted-foreground">
            <Database className="mb-3 size-8 opacity-40" />
            Ask about the enterprise data, or hit <span className="mx-1 font-medium">Ask data</span> to force a Mongo query.
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={cn("flex", m.role === "user" ? "justify-end" : "justify-start")}>
            <Card
              className={cn(
                "max-w-[85%] px-4 py-3",
                m.role === "user" ? "bg-primary text-primary-foreground" : "bg-card"
              )}
            >
              {m.role === "user" ? (
                <div className="whitespace-pre-wrap text-sm">{m.content}</div>
              ) : (
                <Markdown>{m.content}</Markdown>
              )}
            </Card>
          </div>
        ))}
        {busy && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" /> thinking…
          </div>
        )}
        <div ref={endRef} />
      </div>

      <form
        className="flex items-end gap-2 border-t border-border pt-3"
        onSubmit={(e) => {
          e.preventDefault();
          run("chat");
        }}
      >
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              run("chat");
            }
          }}
          rows={2}
          placeholder="Ask something — e.g. open tickets per priority (⌘+Enter to send)"
          className="flex-1 resize-none rounded-md border border-input bg-card px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
        <div className="flex flex-col gap-2">
          <Button type="submit" disabled={busy}>
            <Send className="size-4" /> Send
          </Button>
          <Button type="button" variant="outline" disabled={busy} onClick={() => run("ask")}>
            <Database className="size-4" /> Ask data
          </Button>
        </div>
      </form>
    </div>
  );
}
