import { create } from "zustand";
import { persist } from "zustand/middleware";
import {
  applyUserText,
  createBot,
  makeLocalBot,
  pushReplies,
  seedBots,
  tickBot,
  uid,
  type Bot,
  type Exchange,
  type Message,
  type Reply,
  type Tone,
} from "@/lib/wire/engine";

type DeskState = {
  bots: Bot[];
  activeId: string;
  sound: boolean;
  infoOpen: boolean;
  query: string;
  setQuery: (q: string) => void;
  setActive: (id: string) => void;
  toggleSound: () => void;
  toggleInfo: () => void;
  send: (text: string) => void;
  toggleOnline: (id: string) => void;
  addBot: (name: string, exchange: Exchange) => void;
  removeBot: (id: string) => void;
  tickAll: () => void;
  drain: (id: string) => Promise<void>;
};

const draining = new Set<string>();

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

let audioCtx: AudioContext | null = null;

export function playTone(important: boolean) {
  try {
    const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    audioCtx = audioCtx || new Ctx();
    void audioCtx.resume();
    const o = audioCtx.createOscillator();
    const g = audioCtx.createGain();
    o.type = "sine";
    const t = audioCtx.currentTime;
    o.frequency.setValueAtTime(important ? 740 : 880, t);
    o.frequency.exponentialRampToValueAtTime(important ? 440 : 620, t + 0.09);
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(0.04, t + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 0.16);
    o.connect(g);
    g.connect(audioCtx.destination);
    o.start(t);
    o.stop(t + 0.18);
  } catch {
    /* autoplay gate */
  }
}

function soundFor(replies: Reply[], active: boolean, sound: boolean) {
  if (!sound || !replies.length) return;
  const important = replies.some((r) => r.tone === "trade" || r.tone === "alert");
  if (important) playTone(true);
  else if (!active && replies.some((r) => r.tone === "normal")) playTone(false);
}

type ScriptSnapshot = { activePair?: string | null; activePairUSDC?: string | null; isaacPair?: string | null };

export const BRIDGE_URL = "http://127.0.0.1:47832";

export function isBridge(bot: Bot): boolean {
  return bot.source === "bridge" || bot.name === "ABinanceTradingBot (local)";
}

function toneFor(text: string): { tone: Tone; mono: boolean } {
  const t = text.toLowerCase();
  const alert = /shutdown|failed|error|warning|insufficient|denied|not connected|not running|rescue|unavailable/.test(t);
  const trade = /sell|bought|buy |pair added|trailing|pattern|filled|entry|profit|isaac|order/.test(t);
  return { tone: alert ? "alert" : trade ? "trade" : "normal", mono: text.includes("\n") || text.startsWith("Spot Wallet") };
}

let liveSeq = 0;
let polling = false;
let bridgeUp: boolean | null = null;

async function pollBridge(set: (fn: (s: DeskState) => Partial<DeskState>) => void, get: () => DeskState) {
  if (polling) return;
  if (!get().bots.some(isBridge)) return;
  polling = true;
  try {
    let connected = false;
    let reachable = false;
    try {
      const health = await fetch(`${BRIDGE_URL}/health`, { cache: "no-store" });
      if (health.ok) {
        reachable = true;
        const data = (await health.json()) as { connected?: boolean };
        connected = Boolean(data.connected);
      }
    } catch {
      reachable = false;
    }
    let items: { text: string; ts?: number }[] = [];
    if (reachable) {
      try {
        const live = await fetch(`${BRIDGE_URL}/live?after=${liveSeq}`, { cache: "no-store" });
        if (live.ok) {
          const data = (await live.json()) as { latest?: number; items?: { text: string; ts?: number }[] };
          if (typeof data.latest === "number") liveSeq = data.latest;
          items = Array.isArray(data.items) ? data.items : [];
        }
      } catch {
        /* health already decided reachability */
      }
    }
    const changed = bridgeUp !== connected;
    bridgeUp = connected;
    if (!items.length && !changed) return;
    const now = Date.now();
    const activeId = get().activeId;
    const sound = get().sound;
    const replies: Reply[] = [];
    set((s) => ({
      bots: s.bots.map((b) => {
        if (!isBridge(b)) return b;
        const extra: Message[] = [];
        if (changed) {
          extra.push({
            id: uid("m"),
            from: "service",
            text: connected
              ? "Live script connected. Commands go to the bot. Fills, patterns, and trailing stops will show up here."
              : reachable
                ? "Wire is running, but the trading script is not attached yet."
                : "Live script disconnected.",
            ts: now,
            tone: "service",
          });
        }
        for (const it of items) {
          const text = String(it.text || "");
          if (!text) continue;
          const look = toneFor(text);
          extra.push({
            id: uid("m"),
            from: "bot",
            text,
            ts: it.ts ? Math.round(Number(it.ts) * 1000) : now,
            tone: look.tone,
            mono: look.mono,
          });
          replies.push({ text, tone: look.tone, mono: look.mono });
        }
        if (!extra.length) return { ...b, online: connected, lastSeen: connected ? now : b.lastSeen };
        const active = b.id === activeId;
        return {
          ...b,
          online: connected,
          lastSeen: now,
          messages: [...b.messages, ...extra].slice(-500),
          unread: active ? 0 : b.unread + extra.filter((m) => m.from === "bot").length,
        };
      }),
    }));
    const activeBot = get().bots.find((b) => b.id === activeId);
    soundFor(replies, Boolean(activeBot && isBridge(activeBot)), sound);
  } finally {
    polling = false;
  }
}

const seeded = seedBots();

export const useDesk = create<DeskState>()(
  persist(
    (set, get) => ({
      bots: seeded,
      activeId: seeded[0]?.id ?? "",
      sound: true,
      infoOpen: false,
      query: "",
      setQuery: (query) => set({ query }),
      setActive: (id) =>
        set((s) => ({
          activeId: id,
          bots: s.bots.map((b) => (b.id === id ? { ...b, unread: 0 } : b)),
        })),
      toggleSound: () => set((s) => ({ sound: !s.sound })),
      toggleInfo: () => set((s) => ({ infoOpen: !s.infoOpen })),
      toggleOnline: (id) => {
        const bot = get().bots.find((b) => b.id === id);
        if (!bot) return;
        if (isBridge(bot)) {
          bridgeUp = null;
          void pollBridge(set, get);
          return;
        }
        const online = !bot.online;
        set((s) => ({
          bots: s.bots.map((b) =>
            b.id === id
              ? {
                  ...b,
                  online,
                  lastSeen: Date.now(),
                  typing: false,
                  messages: online
                    ? [
                        ...b.messages,
                        {
                          id: uid("m"),
                          from: "service" as const,
                          text: "Bot is online.",
                          ts: Date.now(),
                          tone: "service" as const,
                        },
                      ]
                    : b.messages,
                }
              : b,
          ),
        }));
        if (online) void get().drain(id);
      },
      addBot: (name, exchange) => {
        const bot = createBot({ name, exchange, online: true });
        set((s) => ({ bots: [...s.bots, bot], activeId: bot.id }));
      },
      removeBot: (id) =>
        set((s) => {
          const bots = s.bots.filter((b) => b.id !== id);
          const activeId = s.activeId === id ? (bots[0]?.id ?? "") : s.activeId;
          return { bots, activeId };
        }),
      send: (text) => {
        const trimmed = text.trim();
        if (!trimmed) return;
        const id = get().activeId;
        const bot = get().bots.find((b) => b.id === id);
        if (!bot) return;
        const jobId = uid("j");
        const mine: Message = {
          id: jobId,
          from: "me",
          text: trimmed,
          ts: Date.now(),
          pending: !bot.online,
        };
        const notice: Message[] =
          !bot.online && !bot.messages.some((m) => m.pending)
            ? [
                {
                  id: uid("m"),
                  from: "service",
                  text: "Bot is offline. This message will send when it is back.",
                  ts: Date.now(),
                  tone: "service",
                },
              ]
            : [];
        set((s) => ({
          bots: s.bots.map((b) =>
            b.id === id
              ? { ...b, messages: [...b.messages, mine, ...notice], inbox: [...b.inbox, { id: jobId, text: trimmed }], unread: 0 }
              : b,
          ),
        }));
        if (bot.online || isBridge(bot)) void get().drain(id);
      },
      tickAll: () => {
        void pollBridge(set, get);
        const activeId = get().activeId;
        const sound = get().sound;
        let played = false;
        set((s) => ({
          bots: s.bots.map((b) => {
            if (isBridge(b) || !b.online || b.typing || b.inbox.length) return b;
            const { bot, replies } = tickBot(b, Date.now());
            if (!replies.length) return { ...bot, messages: b.messages, inbox: b.inbox, typing: false, unread: b.unread };
            const pushed = pushReplies(b.messages, replies, Date.now());
            const active = b.id === activeId;
            if (!played) {
              soundFor(replies, active, sound);
              played = replies.some((r) => r.tone === "trade" || r.tone === "alert" || !active);
            }
            return {
              ...bot,
              messages: pushed.messages,
              inbox: b.inbox,
              typing: false,
              unread: active ? 0 : b.unread + pushed.unreadAdd,
            };
          }),
        }));
      },
      drain: async (id: string) => {
        if (draining.has(id)) return;
        draining.add(id);
        try {
          for (;;) {
            const bot = get().bots.find((b) => b.id === id);
            if (!bot || bot.inbox.length === 0) break;
            const job = bot.inbox[0];
            if (isBridge(bot)) {
              set((s) => ({ bots: s.bots.map((b) => (b.id === id ? { ...b, typing: true } : b)) }));
              let replies: string[] = [];
              let blocked = false;
              let connected = false;
              let snapshot: ScriptSnapshot | null = null;
              const ctrl = new AbortController();
              const timer = setTimeout(() => ctrl.abort(), 20000);
              try {
                const response = await fetch(`${BRIDGE_URL}/command`, {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  cache: "no-store",
                  body: JSON.stringify({ text: job.text }),
                  signal: ctrl.signal,
                });
                const data = (await response.json().catch(() => ({}))) as {
                  replies?: unknown;
                  error?: string;
                  blocked?: boolean;
                };
                connected = response.ok && !data.blocked;
                blocked = Boolean(data.blocked) || !response.ok;
                replies = Array.isArray(data.replies)
                  ? data.replies.map((v) => String(v))
                  : [String(data.error || "The script returned no response.")];
                try {
                  const snap = await fetch(`${BRIDGE_URL}/snapshot`, { cache: "no-store" });
                  if (snap.ok) snapshot = (await snap.json()) as ScriptSnapshot;
                } catch {
                  /* reply still stands */
                }
              } catch {
                replies = ["REAL SCRIPT NOT CONNECTED. Run desktop\\Wire.bat on this PC, then start the bot with it. This chat did not simulate the command."];
                blocked = true;
              } finally {
                clearTimeout(timer);
              }
              const now = Date.now();
              const newMessages: Message[] = replies.map((reply) => {
                const look = toneFor(reply);
                return { id: uid("m"), from: "bot" as const, text: reply, ts: now, tone: blocked ? "alert" : look.tone, mono: look.mono };
              });
              const active = get().activeId === id;
              set((s) => ({
                bots: s.bots.map((b) => {
                  if (b.id !== id) return b;
                  const lanes = snapshot
                    ? {
                        USDT: { ...b.lanes.USDT, symbol: snapshot.activePair || b.lanes.USDT.symbol, lastSymbol: snapshot.activePair || b.lanes.USDT.lastSymbol },
                        USDC: { ...b.lanes.USDC, symbol: snapshot.activePairUSDC || b.lanes.USDC.symbol, lastSymbol: snapshot.activePairUSDC || b.lanes.USDC.lastSymbol },
                      }
                    : b.lanes;
                  return {
                    ...b,
                    online: connected,
                    lastSeen: now,
                    lanes,
                    isaac: snapshot?.isaacPair ? { ...b.isaac, symbol: snapshot.isaacPair } : b.isaac,
                    messages: [...b.messages.map((m) => (m.id === job.id ? { ...m, pending: false } : m)), ...newMessages].slice(-500),
                    inbox: b.inbox.filter((j) => j.id !== job.id),
                    typing: false,
                    unread: active ? 0 : b.unread + newMessages.length,
                  };
                }),
              }));
              soundFor(newMessages.map((m) => ({ text: m.text, tone: m.tone ?? "normal" })), active, get().sound);
              continue;
            }
            if (!bot.online) break;
            set((s) => ({
              bots: s.bots.map((b) => (b.id === id ? { ...b, typing: true } : b)),
            }));
            const slow = /^\/(status|compound_status|isaac_status)/.test(job.text);
            await sleep(slow ? 720 : 480);
            const cur = get().bots.find((b) => b.id === id);
            if (!cur || cur.inbox[0]?.id !== job.id) {
              set((s) => ({ bots: s.bots.map((b) => (b.id === id ? { ...b, typing: false } : b)) }));
              continue;
            }
            if (!cur.online) {
              set((s) => ({
                bots: s.bots.map((b) =>
                  b.id === id
                    ? {
                        ...b,
                        typing: false,
                        messages: b.messages.map((m) => (m.id === job.id ? { ...m, pending: true } : m)),
                      }
                    : b,
                ),
              }));
              break;
            }
            const applied = applyUserText(cur, job.text, Date.now());
            const pushed = pushReplies(
              cur.messages.map((m) => (m.id === job.id ? { ...m, pending: false } : m)),
              applied.replies,
              Date.now(),
            );
            const active = get().activeId === id;
            set((s) => ({
              bots: s.bots.map((b) =>
                b.id !== id
                  ? b
                  : {
                      ...applied.bot,
                      messages: pushed.messages,
                      inbox: b.inbox.filter((j) => j.id !== job.id),
                      typing: false,
                      unread: active ? 0 : b.unread + (active ? 0 : pushed.unreadAdd),
                    },
              ),
            }));
            soundFor(applied.replies, active, get().sound);
          }
        } finally {
          draining.delete(id);
          const bot = get().bots.find((b) => b.id === id);
          if (bot && bot.online && bot.inbox.length) void get().drain(id);
        }
      },
    }),
    {
      name: "wire-desk-v1",
      merge: (persisted, current) => {
        const saved = (persisted ?? {}) as Partial<DeskState>;
        if (!saved.bots?.length) return { ...current, ...saved };
        const bots = saved.bots.map((b) => ({
          ...b,
          typing: false,
          source: b.source ?? (b.name === "ABinanceTradingBot (local)" ? "bridge" : "engine"),
          inbox: b.inbox ?? [],
        }));
        if (!bots.some(isBridge)) bots.unshift(makeLocalBot());
        const activeId = saved.activeId && bots.some((b) => b.id === saved.activeId) ? saved.activeId : bots[0].id;
        return { ...current, ...saved, bots, activeId, query: "" };
      },
      partialize: (s) => ({
        bots: s.bots.map((b) => ({ ...b, typing: false, inbox: b.online ? [] : b.inbox })),
        activeId: s.activeId,
        sound: s.sound,
        infoOpen: s.infoOpen,
      }),
    },
  ),
);
