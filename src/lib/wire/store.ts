import { create } from "zustand";
import { persist } from "zustand/middleware";
import {
  applyUserText,
  createBot,
  pushReplies,
  tickBot,
  uid,
  type Bot,
  type CommandSpec,
  type Exchange,
  COMMANDS,
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
  updateCommands: (id: string, commands: CommandSpec[]) => void;
  removeBot: (id: string) => void;
  addBot: (profile: BotProfile) => void;
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

type ScriptSnapshot = { symbol?: string | null; symbol2?: string | null; main_usdt?: number; main_usdc?: number; rescue_usdt?: number; rescue_usdc?: number; isaac_allocated?: number; ts?: string };

export const BOT_PROFILES = [
  { name: "ABinanceTradingBot", exchange: "Binance Testnet" as Exchange, directory: "ABINANCE TESTNET" },
  { name: "Binance Live Bot", exchange: "Binance" as Exchange, directory: "BINANCE LIVE" },
  { name: "Bitget Live Bot", exchange: "Bitget" as Exchange, directory: "Bitget Live Bot" },
  { name: "Bybit Live Bot", exchange: "Bybit" as Exchange, directory: "Bybit Live Bot" },
  { name: "GROK TESTNET", exchange: "Binance Testnet" as Exchange, directory: "GROK TESTNET" },
  { name: "ZZZBinance METRICS LIVE", exchange: "Binance" as Exchange, directory: "ZZZBinance METRICS LIVE" },
] as const;
export type BotProfile = (typeof BOT_PROFILES)[number];
export const BRIDGE_DIRECTORY = ["C:", "Users", "pauld", "Desktop", "ABINANCE TESTNET"].join("\\");

declare global {
  interface Window {
    wire?: {
      selectWallpaper: () => Promise<string | null>;
      showNotification: (payload: { title: string; body: string; silent?: boolean }) => Promise<{ ok: boolean }>;
      bridgePoll: (directory?: string) => Promise<{ connected: boolean; error?: string; snapshot: ScriptSnapshot | null; items: { id: string; text: string; ts?: number }[]; bridgeDirectory: string }>;
      bridgeCommand: (command: string, directory?: string) => Promise<{ ok: boolean; error?: string; text?: string; ts?: string }>;
    };
  }
}

export function isBridge(bot: Bot): boolean {
  return bot.source === "bridge";
}

function toneFor(text: string): { tone: Tone; mono: boolean } {
  const t = text.toLowerCase();
  const alert = /shutdown|failed|error|warning|insufficient|denied|not connected|not running|rescue|unavailable/.test(t);
  const trade = /sell|bought|buy |pair added|trailing|pattern|filled|entry|profit|isaac|order/.test(t);
  return { tone: alert ? "alert" : trade ? "trade" : "normal", mono: text.includes("\n") || text.startsWith("Spot Wallet") };
}

let polling = false;

async function pollBridge(set: (fn: (s: DeskState) => Partial<DeskState>) => void, get: () => DeskState) {
  if (polling || !window.wire?.bridgePoll) return;
  const targets = get().bots.filter(isBridge);
  if (!targets.length) return;
  polling = true;
  try {
    for (const target of targets) {
      const polled = await window.wire.bridgePoll(target.bridgeDirectory).catch(() => null);
      if (!polled) continue;
      const now = Date.now();
      const active = get().activeId === target.id;
      const snapshot = polled.snapshot;
      const extra: Message[] = [];
      const replies: Reply[] = [];
      for (const item of polled.items ?? []) {
        const text = String(item.text || "");
        if (!text) continue;
        const look = toneFor(text);
        extra.push({ id: uid("m"), from: "bot", text, ts: typeof item.ts === "number" && Number.isFinite(item.ts) ? item.ts : now, tone: look.tone, mono: look.mono });
        replies.push({ text, tone: look.tone, mono: look.mono });
      }
      set((state) => ({
        bots: state.bots.map((bot) => {
          if (bot.id !== target.id) return bot;
          const liveState = snapshot ? {
            lanes: {
              USDT: { ...bot.lanes.USDT, symbol: snapshot.symbol ?? null, lastSymbol: snapshot.symbol ?? bot.lanes.USDT.lastSymbol, allocated: Number(snapshot.main_usdt ?? bot.lanes.USDT.allocated), rescuePool: Number(snapshot.rescue_usdt ?? bot.lanes.USDT.rescuePool) },
              USDC: { ...bot.lanes.USDC, symbol: snapshot.symbol2 ?? null, lastSymbol: snapshot.symbol2 ?? bot.lanes.USDC.lastSymbol, allocated: Number(snapshot.main_usdc ?? bot.lanes.USDC.allocated), rescuePool: Number(snapshot.rescue_usdc ?? bot.lanes.USDC.rescuePool) },
            },
            isaac: { ...bot.isaac, allocated: Number(snapshot.isaac_allocated ?? bot.isaac.allocated) },
          } : {};
          return {
            ...bot, ...liveState, online: polled.connected,
            lastSeen: polled.connected ? now : bot.lastSeen,
            messages: extra.length ? [...bot.messages.filter((m) => m.from !== "service"), ...extra].slice(-500) : bot.messages.filter((m) => m.from !== "service"),
            unread: active ? 0 : bot.unread + extra.length,
          };
        }),
      }));
      soundFor(replies, active, get().sound);
      const notificationStyle = (() => { try { return localStorage.getItem("wire-notification-style") || "system-and-chat"; } catch { return "system-and-chat"; } })();
      if (notificationStyle === "system-and-chat" || notificationStyle === "system-only") {
        for (const reply of replies.slice(-3)) {
          void window.wire?.showNotification({ title: target.name, body: reply.text.replace(/\s+/g, " ").slice(0, 240), silent: notificationStyle === "system-only" });
        }
      }
    }
  } finally { polling = false; }
}

const seeded = (() => {
  const bot = createBot({ name: "ABinanceTradingBot", exchange: "Binance Testnet", online: false, source: "bridge", commands: [...COMMANDS] });
  bot.wallet = {};
  bot.history = [];
  bot.prices = {};
  bot.anchors = {};
  bot.series = {};
  bot.messages = [];
  bot.lanes.USDT = { symbol: null, lastSymbol: null, allocated: 0, rescuePool: 0, position: null };
  bot.lanes.USDC = { symbol: null, lastSymbol: null, allocated: 0, rescuePool: 0, position: null };
  bot.isaac.symbol = "";
  bot.isaac.orders = [];
  bot.isaac.virtualUsdt = 0;
  bot.isaac.allocated = 0;
  bot.isaac.initial = 0;
  bot.isaac.trailingStop = null;
  bot.isaac.trailingDistance = null;
  bot.isaac.dipActive = false;
  bot.isaac.dipLevel = null;
  bot.isaac.dipDistance = null;
  return [bot];
})();

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
        if (!bot || !isBridge(bot)) return;
        void pollBridge(set, get);
      },
      updateCommands: (id, commands) => set((s) => ({ bots: s.bots.map((b) => b.id === id ? { ...b, commands } : b) })),
      addBot: (profile) => set((s) => {
        const existing = s.bots.find((b) => b.bridgeDirectory === profile.directory);
        if (existing) return { activeId: existing.id, infoOpen: false };
        const bot = createBot({ name: profile.name, exchange: profile.exchange, online: false, source: "bridge", commands: [...COMMANDS] });
        bot.bridgeDirectory = profile.directory;
        bot.wallet = {}; bot.history = []; bot.prices = {}; bot.anchors = {}; bot.series = {};
        bot.messages = []; bot.inbox = []; bot.typing = false; bot.unread = 0;
        bot.lanes.USDT = { symbol: null, lastSymbol: null, allocated: 0, rescuePool: 0, position: null };
        bot.lanes.USDC = { symbol: null, lastSymbol: null, allocated: 0, rescuePool: 0, position: null };
        bot.isaac.symbol = ""; bot.isaac.orders = []; bot.isaac.virtualUsdt = 0; bot.isaac.allocated = 0; bot.isaac.initial = 0;
        bot.isaac.trailingStop = null; bot.isaac.trailingDistance = null; bot.isaac.dipActive = false; bot.isaac.dipLevel = null; bot.isaac.dipDistance = null;
        return { bots: [...s.bots, bot], activeId: bot.id, infoOpen: false };
      }),
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
        const notice: Message[] = [];
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
              try {
                const result = await window.wire?.bridgeCommand(job.text, bot.bridgeDirectory);
                connected = Boolean(result?.ok);
                blocked = !connected;
                replies = connected
                  ? [String(result?.text || "The running bot returned no message.")]
                  : [String(result?.error || "The local bot bridge is unavailable. Start the bot manually in CMD.")];
                const poll = await window.wire?.bridgePoll(bot.bridgeDirectory);
                if (poll) {
                  snapshot = poll.snapshot;
                  connected = poll.connected && connected;
                }
              } catch {
                replies = ["Bot is not responding. Check that its process and bridge are running."];
                blocked = true;
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
                        USDT: { ...b.lanes.USDT, symbol: snapshot.symbol ?? null, lastSymbol: snapshot.symbol ?? b.lanes.USDT.lastSymbol },
                        USDC: { ...b.lanes.USDC, symbol: snapshot.symbol2 ?? null, lastSymbol: snapshot.symbol2 ?? b.lanes.USDC.lastSymbol },
                      }
                    : b.lanes;
                  return {
                    ...b,
                    online: connected,
                    lastSeen: now,
                    lanes,
                    isaac: snapshot ? { ...b.isaac, allocated: Number(snapshot.isaac_allocated ?? b.isaac.allocated) } : b.isaac,
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
        if (!saved.bots?.length) return { ...current, ...saved, bots: seeded, activeId: seeded[0].id, query: "" };
        const savedBots = saved.bots.filter((b) => b.source === "bridge").map((b) => ({
          ...b, scriptPath: undefined, pythonPath: undefined, bridgePort: undefined,
          typing: false, online: false, unread: 0, source: "bridge" as const,
          bridgeDirectory: b.bridgeDirectory || (b.name === "ABinanceTradingBot" ? "ABINANCE TESTNET" : undefined),
          messages: (b.messages ?? []).filter((m) => m.from !== "service").slice(-500),
          inbox: [], conversation: null,
          commands: b.commands?.length ? b.commands : [...COMMANDS],
          wallet: {}, history: [], prices: {}, anchors: {}, series: {},
          lanes: {
            USDT: { symbol: null, lastSymbol: null, allocated: 0, rescuePool: 0, position: null },
            USDC: { symbol: null, lastSymbol: null, allocated: 0, rescuePool: 0, position: null },
          },
          isaac: { ...b.isaac, symbol: "", orders: [], virtualUsdt: 0, allocated: 0, initial: 0, trailingStop: null, trailingDistance: null, dipActive: false, dipLevel: null, dipDistance: null },
        }));
        const bots = savedBots.length ? savedBots : seeded;
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
