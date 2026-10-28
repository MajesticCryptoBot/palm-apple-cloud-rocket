import { useDesk } from "@/lib/wire/store";

type WireMessage = { id: string; from: string; text: string; ts: number };

let socket: WebSocket | null = null;
let timer = 0;

function settings() {
  try {
    return {
      url: localStorage.getItem("wire-companion-url") || "",
      key: localStorage.getItem("wire-companion-key") || "",
      on: localStorage.getItem("wire-companion-on") === "1",
    };
  } catch {
    return { url: "", key: "", on: false };
  }
}

function send(data: unknown) {
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(data));
}

function publish() {
  const { bots } = useDesk.getState();
  send({
    type: "session",
    bots: bots.map((b) => ({
      id: b.id,
      name: b.name,
      exchange: b.exchange,
      online: b.online,
      photo: b.photo && b.photo.length < 160_000 ? b.photo : undefined,
      pins: b.pins ?? [],
      commands: (b.commands ?? []).slice(0, 40),
      kind: b.kind,
    })),
  });
  for (const bot of bots) {
    send({ type: "backlog", botId: bot.id, messages: bot.messages.slice(-80) satisfies WireMessage[] });
  }
}

export function startCompanion() {
  window.clearInterval(timer);
  timer = window.setInterval(connect, 4000);
  connect();
  window.addEventListener("wire-companion", connect);
  let last = "";
  useDesk.subscribe((state) => {
    if (socket?.readyState !== WebSocket.OPEN) return;
    const sig = state.bots.map((b) => `${b.id}:${b.messages.length}:${b.online}:${b.messages.at(-1)?.id ?? ""}`).join("|");
    if (sig === last) return;
    last = sig;
    publish();
  });
}

function connect() {
  const cfg = settings();
  if (!cfg.on || !cfg.url || !cfg.key) {
    socket?.close();
    socket = null;
    return;
  }
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) return;
  const root = cfg.url.replace(/\/$/, "").replace(/^http/i, "ws");
  try {
    socket = new WebSocket(`${root}/ws`);
  } catch {
    return;
  }
  socket.onopen = () => {
    send({ type: "hello", role: "publisher", key: cfg.key, name: "WIRE" });
    publish();
  };
  socket.onmessage = (event) => {
    try {
      const msg = JSON.parse(String(event.data)) as { type?: string; action?: string; botId?: string; text?: string; msgId?: string };
      if (msg.type === "input" && msg.botId && msg.text) {
        useDesk.getState().send(msg.text, msg.botId);
      }
      if (msg.type === "ctrl" && msg.action === "togglePin" && msg.botId && msg.msgId) {
        useDesk.getState().togglePin(msg.botId, msg.msgId);
      }
    } catch {
      /* ignore bad frames */
    }
  };
  socket.onclose = () => {
    socket = null;
  };
}
