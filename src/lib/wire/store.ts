import { create } from "zustand";
import { persist } from "zustand/middleware";
import {
  applyUserText,
  createBot,
  pushReplies,
  seedBots,
  tickBot,
  uid,
  type Bot,
  type Exchange,
  type Message,
  type Reply,
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
        if (bot.online) void get().drain(id);
      },
      tickAll: () => {
        const activeId = get().activeId;
        const sound = get().sound;
        let played = false;
        set((s) => ({
          bots: s.bots.map((b) => {
            if (!b.online || b.typing || b.inbox.length) return b;
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
            if (!bot.online) break;
            const job = bot.inbox[0];
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
      partialize: (s) => ({
        bots: s.bots.map((b) => ({ ...b, typing: false, inbox: b.online ? [] : b.inbox })),
        activeId: s.activeId,
        sound: s.sound,
        infoOpen: s.infoOpen,
      }),
    },
  ),
);
