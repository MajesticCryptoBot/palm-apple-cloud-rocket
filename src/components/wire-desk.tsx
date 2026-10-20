import { useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import {
  Check,
  ChevronLeft,
  Clock,
  PanelRight,
  Plus,
  Search,
  Send,
  Volume2,
  VolumeX,
  X,
} from "lucide-react";
import { COMMANDS, laneQuotes, previewLine, pxFmt, type Bot, type CommandSpec, type Message } from "@/lib/wire/engine";
import { useDesk } from "@/lib/wire/store";

function initials(name: string) {
  const parts = name.split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "?") + (parts[1]?.[0] ?? "")).toUpperCase();
}

function hm(ts: number) {
  return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function dayLabel(ts: number) {
  const d = new Date(ts);
  const now = new Date();
  const start = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((start(now) - start(d)) / 86400000);
  if (diff === 0) return "Today";
  if (diff === 1) return "Yesterday";
  return d.toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" });
}

function Rich({ text }: { text: string }) {
  const lines = text.split("\n");
  return (
    <>
      {lines.map((line, i) => (
        <span key={i}>
          {i > 0 && <br />}
          {line.split(/(\*\*[^*]+\*\*)/g).map((part, j) =>
            part.startsWith("**") && part.endsWith("**") ? (
              <strong key={j} className="font-semibold">
                {part.slice(2, -2)}
              </strong>
            ) : (
              <span key={j}>{part}</span>
            ),
          )}
        </span>
      ))}
    </>
  );
}

function Avatar({ name, online, size = "md" }: { name: string; online: boolean; size?: "md" | "sm" }) {
  const cls = size === "sm" ? "size-9 text-xs" : "size-12 text-sm";
  return (
    <span className={`relative grid ${cls} shrink-0 place-items-center rounded-full bg-accent-strong font-semibold text-fg`}>
      {initials(name)}
      <span
        className={`absolute right-0 bottom-0 size-2.5 rounded-full ring-2 ring-sidebar ${online ? "bg-online" : "bg-subtle"}`}
      />
    </span>
  );
}

export function Desk() {
  const bots = useDesk((s) => s.bots);
  const activeId = useDesk((s) => s.activeId);
  const sound = useDesk((s) => s.sound);
  const infoOpen = useDesk((s) => s.infoOpen);
  const query = useDesk((s) => s.query);
  const setQuery = useDesk((s) => s.setQuery);
  const setActive = useDesk((s) => s.setActive);
  const toggleSound = useDesk((s) => s.toggleSound);
  const toggleInfo = useDesk((s) => s.toggleInfo);
  const [listMode, setListMode] = useState(true);
  const [adding, setAdding] = useState(false);

  const active = bots.find((b) => b.id === activeId) ?? null;

  useEffect(() => {
    const id = window.setInterval(() => useDesk.getState().tickAll(), 2500);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!e.altKey || e.key < "1" || e.key > "9") return;
      const bot = useDesk.getState().bots[Number(e.key) - 1];
      if (!bot) return;
      e.preventDefault();
      setActive(bot.id);
      setListMode(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setActive]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return bots;
    return bots.filter((b) => {
      const blob = `${b.name} ${b.exchange} ${previewLine(b)}`.toLowerCase();
      return blob.includes(q);
    });
  }, [bots, query]);

  return (
    <div className="flex h-dvh min-h-0 overflow-hidden bg-bg text-fg">
      <aside
        className={`${listMode ? "flex" : "hidden"} min-h-0 w-full shrink-0 flex-col border-r border-line bg-sidebar md:flex md:w-80`}
      >
        <div className="flex items-center justify-between px-4 pt-4 pb-2">
          <div>
            <h1 className="text-lg font-semibold tracking-tight">Wire</h1>
            <p className="text-xs text-muted">Private desk</p>
          </div>
          <button
            type="button"
            onClick={() => setAdding(true)}
            className="grid size-10 place-items-center rounded-full bg-elevated text-accent hover:bg-bubble-out"
            aria-label="Add a bot"
          >
            <Plus className="size-5" />
          </button>
        </div>
        <div className="px-3 pb-2">
          <label className="flex items-center gap-2 rounded-full bg-bg px-3 py-2 text-sm text-muted">
            <Search className="size-4 shrink-0" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search"
              className="w-full bg-transparent text-fg outline-none placeholder:text-subtle"
            />
          </label>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          {shown.length === 0 && <p className="px-4 py-6 text-sm text-muted">No bots match that search.</p>}
          {shown.map((bot) => (
            <ChatRow
              key={bot.id}
              bot={bot}
              active={bot.id === activeId}
              onPick={() => {
                setActive(bot.id);
                setListMode(false);
              }}
            />
          ))}
        </div>
      </aside>

      <section className={`${listMode ? "hidden" : "flex"} min-h-0 min-w-0 flex-1 flex-col md:flex`}>
        {active ? (
          <Thread
            bot={active}
            sound={sound}
            onBack={() => setListMode(true)}
            onToggleSound={toggleSound}
            onToggleInfo={toggleInfo}
          />
        ) : (
          <div className="grid flex-1 place-items-center px-6 text-center">
            <div>
              <p className="text-lg font-medium">No bot selected</p>
              <p className="mt-1 text-sm text-muted">Add one to start a private chat.</p>
              <button
                type="button"
                onClick={() => setAdding(true)}
                className="mt-4 rounded-full bg-accent-strong px-4 py-2 text-sm font-medium text-fg"
              >
                Add a bot
              </button>
            </div>
          </div>
        )}
      </section>

      {active && infoOpen && (
        <>
          <button
            type="button"
            className="fixed inset-0 z-20 bg-bg/70 xl:hidden"
            aria-label="Close details"
            onClick={toggleInfo}
          />
          <InfoPanel bot={active} onClose={toggleInfo} />
        </>
      )}

      {adding && <AddBotDialog onClose={() => setAdding(false)} />}
    </div>
  );
}

function ChatRow({ bot, active, onPick }: { bot: Bot; active: boolean; onPick: () => void }) {
  const last = bot.messages[bot.messages.length - 1];
  return (
    <button
      type="button"
      onClick={onPick}
      className={`flex w-full items-center gap-3 px-3 py-2.5 text-left ${active ? "bg-bubble-out" : "hover:bg-elevated"}`}
    >
      <Avatar name={bot.name} online={bot.online} />
      <span className="min-w-0 flex-1">
        <span className="flex items-baseline justify-between gap-2">
          <span className="truncate font-medium">{bot.name}</span>
          <span className="shrink-0 text-xs text-muted">{last ? hm(last.ts) : ""}</span>
        </span>
        <span className="mt-0.5 flex items-center justify-between gap-2">
          <span className={`truncate text-sm ${bot.typing ? "text-accent" : "text-muted"}`}>{previewLine(bot)}</span>
          {bot.unread > 0 && (
            <span className="grid min-w-5 place-items-center rounded-full bg-accent px-1.5 text-xs font-semibold text-bg">
              {bot.unread}
            </span>
          )}
        </span>
      </span>
    </button>
  );
}

function Thread({
  bot,
  sound,
  onBack,
  onToggleSound,
  onToggleInfo,
}: {
  bot: Bot;
  sound: boolean;
  onBack: () => void;
  onToggleSound: () => void;
  onToggleInfo: () => void;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  const [chatQuery, setChatQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const quotes = laneQuotes(bot);
  const visible = chatQuery.trim()
    ? bot.messages.filter((m) => m.text.toLowerCase().includes(chatQuery.trim().toLowerCase()))
    : bot.messages;
  const lastLive = [...bot.messages].reverse().find((m) => m.from === "bot");

  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el || chatQuery.trim()) return;
    const go = () => {
      el.scrollTop = el.scrollHeight;
    };
    go();
    const id = requestAnimationFrame(go);
    return () => cancelAnimationFrame(id);
  }, [bot.id, bot.messages.length, bot.typing, chatQuery]);

  useEffect(() => {
    setChatQuery("");
    setSearchOpen(false);
  }, [bot.id]);

  return (
    <>
      <header className="flex shrink-0 items-center gap-2 border-b border-line bg-sidebar px-2 py-2 md:px-3">
        <button
          type="button"
          onClick={onBack}
          className="grid size-10 place-items-center rounded-full text-muted hover:bg-elevated md:hidden"
          aria-label="Back to bots"
        >
          <ChevronLeft className="size-5" />
        </button>
        <Avatar name={bot.name} online={bot.online} size="sm" />
        <div className="min-w-0 flex-1">
          <div className="truncate font-semibold leading-tight">{bot.name}</div>
          <div className={`truncate text-xs ${bot.online ? "text-online" : "text-muted"}`}>
            {bot.typing ? (
              <span className="text-accent">typing</span>
            ) : bot.online ? (
              "online"
            ) : (
              `last seen ${hm(bot.lastSeen)}`
            )}
            <span className="text-subtle"> · {bot.exchange}</span>
          </div>
        </div>
        <div className="hidden text-right sm:block">
          {quotes.map((q) => (
            <div key={q.pair} className="font-mono text-xs leading-4 tabular-nums text-muted">
              <span className="text-fg">{q.pair}</span> {pxFmt(q.price)}
              {q.pnl != null && (
                <span className={q.pnl >= 0 ? "text-online" : "text-danger"}>
                  {" "}
                  {q.pnl >= 0 ? "+" : ""}
                  {q.pnl.toFixed(2)}%
                </span>
              )}
            </div>
          ))}
        </div>
        <button
          type="button"
          onClick={() => setSearchOpen((v) => !v)}
          className="grid size-10 place-items-center rounded-full text-muted hover:bg-elevated"
          aria-label="Search this chat"
        >
          <Search className="size-5" />
        </button>
        <button
          type="button"
          onClick={onToggleSound}
          className="grid size-10 place-items-center rounded-full text-muted hover:bg-elevated"
          aria-label={sound ? "Mute notifications" : "Unmute notifications"}
        >
          {sound ? <Volume2 className="size-5" /> : <VolumeX className="size-5" />}
        </button>
        <button
          type="button"
          onClick={onToggleInfo}
          className="grid size-10 place-items-center rounded-full text-muted hover:bg-elevated"
          aria-label="Bot details"
        >
          <PanelRight className="size-5" />
        </button>
      </header>

      {searchOpen && (
        <div className="shrink-0 border-b border-line bg-sidebar px-3 py-2">
          <input
            autoFocus
            value={chatQuery}
            onChange={(e) => setChatQuery(e.target.value)}
            placeholder="Search in this chat"
            className="w-full rounded-full bg-bg px-3 py-2 text-sm outline-none"
          />
        </div>
      )}

      <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto px-3 py-3 md:px-6">
        <div className="mx-auto flex max-w-3xl flex-col gap-1.5">
          {visible.map((m, i) => {
            const prev = visible[i - 1];
            const showDay = !prev || new Date(prev.ts).toDateString() !== new Date(m.ts).toDateString();
            return (
              <div key={m.id}>
                {showDay && (
                  <div className="my-2 flex justify-center">
                    <span className="rounded-full bg-bubble-in px-3 py-1 text-xs text-muted">{dayLabel(m.ts)}</span>
                  </div>
                )}
                <Bubble message={m} />
              </div>
            );
          })}
          {bot.typing && (
            <div className="msg-in mr-auto flex items-center gap-1 rounded-md rounded-bl-sm bg-bubble-in px-3 py-3">
              <span className="typing-dot size-1.5 rounded-full bg-muted" />
              <span className="typing-dot size-1.5 rounded-full bg-muted" />
              <span className="typing-dot size-1.5 rounded-full bg-muted" />
            </div>
          )}
        </div>
        <div className="sr-only" aria-live="polite">
          {lastLive?.text ?? ""}
        </div>
      </div>

      <Composer bot={bot} />
    </>
  );
}

function Bubble({ message }: { message: Message }) {
  if (message.from === "service") {
    return (
      <div className="my-1 flex justify-center">
        <span className="max-w-md rounded-full bg-bubble-in px-3 py-1 text-center text-xs text-muted">{message.text}</span>
      </div>
    );
  }
  const mine = message.from === "me";
  const edge = message.tone === "trade" ? "tone-trade" : message.tone === "alert" ? "tone-alert" : "";
  return (
    <div className={`msg-in flex ${mine ? "justify-end" : "justify-start"}`}>
      <div
        className={`bubble-col rounded-lg px-3 py-1.5 text-sm leading-normal ${
          mine ? "rounded-br-sm bg-bubble-out" : `rounded-bl-sm bg-bubble-in ${edge}`
        } ${message.mono ? "font-mono text-xs leading-relaxed" : ""}`}
      >
        <span className="float-right mt-1 ml-3 inline-flex items-center gap-1 text-xs text-subtle">
          {message.pending && <Clock className="size-3" aria-label="Waiting to send" />}
          {hm(message.ts)}
          {mine && !message.pending && <Check className="size-3 text-accent" aria-label="Sent" />}
        </span>
        <Rich text={message.text} />
      </div>
    </div>
  );
}

function Composer({ bot }: { bot: Bot }) {
  const send = useDesk((s) => s.send);
  const [draft, setDraft] = useState("");
  const [menuIndex, setMenuIndex] = useState(0);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    setDraft("");
    setMenuIndex(0);
    inputRef.current?.focus();
  }, [bot.id]);

  const waiting =
    bot.conversation?.kind === "pair"
      ? `Waiting for a ${bot.conversation.lane} pair. /cancel to abort.`
      : bot.conversation?.kind === "buy_price"
        ? "Waiting for pair, price, and amount. /cancel to abort."
        : bot.conversation?.kind === "mb"
          ? `Waiting for the ${bot.conversation.lane} amount. /cancel to abort.`
          : null;

  const menuOpen = draft.startsWith("/") && !draft.includes(" ") && !draft.includes("\n");
  const matches = useMemo(() => {
    if (!menuOpen) return [];
    const needle = draft.toLowerCase();
    return COMMANDS.filter(
      (c) => needle === "/" || c.name.startsWith(needle) || c.hint.toLowerCase().includes(needle.slice(1)),
    );
  }, [draft, menuOpen]);

  useEffect(() => {
    setMenuIndex(0);
  }, [draft]);

  function submit(text: string) {
    const value = text.trim();
    if (!value) return;
    send(value);
    setDraft("");
  }

  function onKeyDown(e: ReactKeyboardEvent<HTMLTextAreaElement>) {
    if (menuOpen && matches.length) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setMenuIndex((i) => (i + 1) % matches.length);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setMenuIndex((i) => (i - 1 + matches.length) % matches.length);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setDraft("");
        return;
      }
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (menuOpen && matches.length && !draft.includes(" ")) {
        submit(matches[Math.min(menuIndex, matches.length - 1)]?.name ?? draft);
        return;
      }
      submit(draft);
    }
  }

  return (
    <div className="relative shrink-0 border-t border-line bg-sidebar">
      {menuOpen && matches.length > 0 && (
        <ul className="absolute right-2 bottom-full left-2 z-10 mb-2 max-h-72 overflow-y-auto rounded-md border border-line bg-sidebar py-1 shadow-lg">
          {matches.map((cmd, i) => (
            <li key={cmd.name}>
              <button
                type="button"
                onMouseEnter={() => setMenuIndex(i)}
                onClick={() => submit(cmd.name)}
                className={`flex w-full items-baseline gap-3 px-3 py-2 text-left ${i === menuIndex ? "bg-elevated" : ""}`}
              >
                <span className={`w-36 shrink-0 font-medium ${cmd.danger ? "text-danger" : "text-accent"}`}>{cmd.name}</span>
                <span className="truncate text-sm text-muted">{cmd.hint}</span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {waiting && <div className="px-4 pt-2 text-xs text-accent">{waiting}</div>}

      <CommandRail
        onSend={(name) => {
          submit(name);
          inputRef.current?.focus();
        }}
      />

      <div className="flex items-end gap-2 px-3 pt-1 pb-3">
        <textarea
          ref={inputRef}
          rows={1}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Write a message"
          className="max-h-32 min-h-11 flex-1 resize-none rounded-md bg-bg px-3 py-2.5 text-sm outline-none placeholder:text-subtle"
        />
        <button
          type="button"
          onClick={() => submit(draft)}
          disabled={!draft.trim()}
          className="grid size-11 shrink-0 place-items-center rounded-full bg-accent-strong text-fg disabled:bg-elevated disabled:text-subtle"
          aria-label="Send"
        >
          <Send className="size-5" />
        </button>
      </div>
    </div>
  );
}

function CommandRail({ onSend }: { onSend: (name: string) => void }) {
  const groups = ["USDT", "USDC", "Isaac", "Session"] as const;
  return (
    <div className="flex gap-3 overflow-x-auto px-3 pt-2 pb-1">
      {groups.map((group) => (
        <div key={group} className="flex shrink-0 items-center gap-1">
          <span className="pr-1 text-xs font-semibold tracking-wide text-subtle uppercase">{group}</span>
          {COMMANDS.filter((c) => c.group === group).map((cmd) => (
            <CommandChip key={cmd.name} cmd={cmd} onSend={onSend} />
          ))}
        </div>
      ))}
    </div>
  );
}

function CommandChip({ cmd, onSend }: { cmd: CommandSpec; onSend: (name: string) => void }) {
  return (
    <button
      type="button"
      onClick={() => onSend(cmd.name)}
      title={cmd.hint}
      className={`shrink-0 rounded-full bg-bg px-2.5 py-1.5 text-xs font-medium ${cmd.danger ? "text-danger" : "text-accent"} hover:bg-elevated`}
    >
      {cmd.name}
    </button>
  );
}

function InfoPanel({ bot, onClose }: { bot: Bot; onClose: () => void }) {
  const toggleOnline = useDesk((s) => s.toggleOnline);
  const removeBot = useDesk((s) => s.removeBot);
  const [confirm, setConfirm] = useState(false);
  const usdt = bot.lanes.USDT;
  const usdc = bot.lanes.USDC;

  return (
    <aside className="absolute inset-y-0 right-0 z-30 flex w-full min-h-0 flex-col border-l border-line bg-sidebar sm:w-80 xl:static">
      <div className="flex items-center justify-between px-4 py-3">
        <h2 className="font-semibold">Details</h2>
        <button type="button" onClick={onClose} className="grid size-10 place-items-center rounded-full hover:bg-elevated" aria-label="Close details">
          <X className="size-5" />
        </button>
      </div>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 pb-6">
        <div className="flex items-center gap-3">
          <Avatar name={bot.name} online={bot.online} />
          <div>
            <div className="font-medium">{bot.name}</div>
            <div className="text-sm text-muted">{bot.exchange}</div>
          </div>
        </div>
        <button
          type="button"
          onClick={() => toggleOnline(bot.id)}
          className={`w-full rounded-md px-3 py-2.5 text-sm font-medium ${bot.online ? "bg-elevated text-fg" : "bg-accent-strong text-fg"}`}
        >
          {bot.online ? "Stop bot" : "Bring online"}
        </button>
        <LaneBlock title="USDT lane" symbol={usdt.symbol} position={usdt.position} allocated={usdt.allocated} quote={bot.wallet.USDT} />
        <LaneBlock title="USDC lane" symbol={usdc.symbol} position={usdc.position} allocated={usdc.allocated} quote={bot.wallet.USDC} />
        <section className="rounded-md bg-bg p-3 text-sm">
          <h3 className="font-medium">Isaac DCA</h3>
          <p className="mt-1 text-muted">
            {bot.isaac.symbol} · {bot.isaac.orders.length}/7 orders · {bot.isaac.paused ? "paused" : "running"}
          </p>
          <p className="font-mono text-xs text-subtle tabular-nums">Pool ${bot.isaac.virtualUsdt.toFixed(0)} / {bot.isaac.allocated.toFixed(0)}</p>
        </section>
        <p className="text-xs leading-relaxed text-subtle">
          Commands stay pinned above the message box. Alt+1 to Alt+9 switches bots. This desk speaks the same command set as the trading scripts.
        </p>
        {!confirm ? (
          <button type="button" onClick={() => setConfirm(true)} className="text-sm text-danger">
            Remove this bot
          </button>
        ) : (
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => removeBot(bot.id)}
              className="rounded-md bg-danger px-3 py-2 text-sm font-medium text-fg"
            >
              Remove
            </button>
            <button type="button" onClick={() => setConfirm(false)} className="rounded-md bg-elevated px-3 py-2 text-sm">
              Keep
            </button>
          </div>
        )}
      </div>
    </aside>
  );
}

function LaneBlock({
  title,
  symbol,
  position,
  allocated,
  quote,
}: {
  title: string;
  symbol: string | null;
  position: Bot["lanes"]["USDT"]["position"];
  allocated: number;
  quote: { free: number; locked: number } | undefined;
}) {
  return (
    <section className="rounded-md bg-bg p-3 text-sm">
      <h3 className="font-medium">{title}</h3>
      <p className="mt-1 text-muted">{symbol ?? "No pair set"}</p>
      <p className="font-mono text-xs text-subtle tabular-nums">
        Allocated ${allocated.toFixed(0)} · Free ${quote?.free.toFixed(2) ?? "0.00"}
      </p>
      {position && (
        <p className="mt-1 font-mono text-xs tabular-nums text-fg">
          {position.amount.toFixed(4)} @ {pxFmt(position.entry)} · rescue {position.rescueCount}/5 · {["RUN", "BREATHE", "LOCK", "STEEL", "HARVEST", "MOONSHOT"][position.phase]}
        </p>
      )}
    </section>
  );
}

function AddBotDialog({ onClose }: { onClose: () => void }) {
  const addBot = useDesk((s) => s.addBot);
  const [name, setName] = useState("");
  const [exchange, setExchange] = useState<Bot["exchange"]>("Binance Testnet");
  const options: Bot["exchange"][] = ["Binance Testnet", "Binance", "Bybit", "Bitget"];

  return (
    <div className="fixed inset-0 z-40 grid place-items-center bg-bg/70 px-4">
      <form
        className="w-full max-w-md rounded-lg bg-sidebar p-5"
        onSubmit={(e) => {
          e.preventDefault();
          if (!name.trim()) return;
          addBot(name.trim(), exchange);
          onClose();
        }}
      >
        <h2 className="text-lg font-semibold">Add a bot</h2>
        <p className="mt-1 text-sm text-muted">Each bot keeps its own pairs, wallet, and Isaac cycle.</p>
        <label className="mt-4 block text-xs font-medium text-muted">
          Name
          <input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="ABinance Testnet"
            className="mt-1 w-full rounded-md bg-bg px-3 py-2.5 text-sm text-fg outline-none"
          />
        </label>
        <label className="mt-3 block text-xs font-medium text-muted">
          Exchange
          <select
            value={exchange}
            onChange={(e) => setExchange(e.target.value as Bot["exchange"])}
            className="mt-1 w-full rounded-md bg-bg px-3 py-2.5 text-sm text-fg outline-none"
          >
            {options.map((o) => (
              <option key={o}>{o}</option>
            ))}
          </select>
        </label>
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-md px-3 py-2 text-sm text-muted">
            Cancel
          </button>
          <button type="submit" className="rounded-md bg-accent-strong px-4 py-2 text-sm font-medium text-fg">
            Create
          </button>
        </div>
      </form>
    </div>
  );
}
