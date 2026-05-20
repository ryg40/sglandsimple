// Chat UI: posts to /api/chat by default; /api/ask_data on the dedicated button.
// Renders markdown via marked + highlight.js (loaded from CDN by index.html).

const $ = (sel) => document.querySelector(sel);
const history = $("#history");
const input = $("#input");
const status = $("#status");
const composer = $("#composer");
const sendBtn = $("#send");
const askDataBtn = $("#askdata");
const clearBtn = $("#clear");

const conversation = []; // {role, content}

marked.setOptions({
  highlight: (code, lang) => {
    if (lang && hljs.getLanguage(lang)) {
      try { return hljs.highlight(code, { language: lang }).value; } catch {}
    }
    return hljs.highlightAuto(code).value;
  },
});

function renderMarkdown(text) {
  return marked.parse(text || "");
}

function appendMessage(role, content, opts = {}) {
  const div = document.createElement("div");
  div.className = `msg ${role}${opts.error ? " error" : ""}`;
  const r = document.createElement("div");
  r.className = "role";
  r.textContent = role;
  div.appendChild(r);
  const body = document.createElement("div");
  body.className = "body";
  if (role === "user") {
    body.textContent = content;
  } else {
    body.innerHTML = renderMarkdown(content);
  }
  div.appendChild(body);
  history.appendChild(div);
  history.scrollTop = history.scrollHeight;
}

function setBusy(busy, label) {
  sendBtn.disabled = busy;
  askDataBtn.disabled = busy;
  status.textContent = busy ? (label || "working…") : "";
}

async function sendChat() {
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  appendMessage("user", text);
  conversation.push({ role: "user", content: text });
  setBusy(true, "thinking…");
  try {
    const r = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: conversation }),
    });
    const data = await r.json();
    if (data.error) {
      appendMessage("assistant", `**error:** ${JSON.stringify(data.error)}`, { error: true });
    } else {
      const reply = data.choices?.[0]?.message?.content ?? "";
      appendMessage("assistant", reply || "_(empty reply)_");
      conversation.push({ role: "assistant", content: reply });
    }
  } catch (e) {
    appendMessage("assistant", `**error:** ${e.message}`, { error: true });
  } finally {
    setBusy(false);
  }
}

async function askData() {
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  appendMessage("user", `(ask data) ${text}`);
  conversation.push({ role: "user", content: text });
  setBusy(true, "querying mongo…");
  try {
    const r = await fetch("/api/ask_data", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: text }),
    });
    const data = await r.json();
    if (data.error) {
      appendMessage("assistant", `**error:** ${JSON.stringify(data.error)}`, { error: true });
    } else {
      const reply = data.choices?.[0]?.message?.content ?? "";
      appendMessage("assistant", reply || "_(empty reply)_");
      conversation.push({ role: "assistant", content: reply });
    }
  } catch (e) {
    appendMessage("assistant", `**error:** ${e.message}`, { error: true });
  } finally {
    setBusy(false);
  }
}

composer.addEventListener("submit", (e) => {
  e.preventDefault();
  sendChat();
});
askDataBtn.addEventListener("click", askData);
clearBtn.addEventListener("click", () => {
  conversation.length = 0;
  history.innerHTML = "";
});

input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
    e.preventDefault();
    sendChat();
  }
});
