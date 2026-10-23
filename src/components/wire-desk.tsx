import { useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import {
  ArrowDown,
  CheckCheck,
  ChevronDown,
  ChevronLeft,
  ChevronUp,
  Clock,
  Copy,
  Menu,
  PanelRight,
  Search,
  Settings,
  Send,
  Volume2,
  VolumeX,
  X,
} from "lucide-react";
import { COMMANDS, laneQuotes, previewLine, pxFmt, type Bot, type CommandSpec, type Message } from "@/lib/wire/engine";
import { BRIDGE_DIRECTORY, useDesk } from "@/lib/wire/store";
import { WireSettings } from "@/components/wire-settings";

function parseCommandLines(raw: string): CommandSpec[] {
  return raw.split("\n").map((line) => line.trim()).filter(Boolean).map((line) => {
    const [rawName, ...desc] = line.split("|");
    const name = rawName.trim();
    const hint = desc.join("|").trim() || "Custom command";
    return { name, hint, group: "Session" as const, danger: /sell|reset|emergency|buy|withdraw|delete/i.test(name) };
  }).filter((command) => /^\/[a-zA-Z0-9_]{1,50}$/.test(command.name));
}

function commandLines(commands: CommandSpec[] = []) {
  return commands.map((command) => `${command.name} | ${command.hint}`).join("\n");
}

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

function Rich({ text, query }: { text: string; query?: string }) {
  const needle = query?.trim().toLowerCase() ?? "";
  const lines = text.split("\n");
  return (
    <>
      {lines.map((line, i) => (
        <span key={i}>
          {i > 0 && <br />}
          {line.split(/(\*\*[^*]+\*\*)/g).map((part, j) => {
            if (part.startsWith("**") && part.endsWith("**")) {
              return (
                <strong key={j} className="font-semibold">
                  {part.slice(2, -2)}
                </strong>
              );
            }
            if (!needle) return <span key={j}>{part}</span>;
            const at = part.toLowerCase().indexOf(needle);
            if (at < 0) return <span key={j}>{part}</span>;
            return (
              <span key={j}>
                {part.slice(0, at)}
                <mark className="rounded-sm bg-warn/50 px-0.5 text-fg">{part.slice(at, at + needle.length)}</mark>
                {part.slice(at + needle.length)}
              </span>
            );
          })}
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
  const [settingsOpen, setSettingsOpen] = useState(false);
  const active = bots.find((b) => b.id === activeId) ?? bots[0] ?? null;

  useEffect(() => {
    const id = window.setInterval(() => useDesk.getState().tickAll(), 1000);
    return () => window.clearInterval(id);
  }, []);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return bots;
    return bots.filter((b) => (`${b.name} ${b.exchange} ${previewLine(b)}`).toLowerCase().includes(q));
  }, [bots, query]);

  return (
    <div className="flex h-dvh min-h-0 overflow-hidden bg-bg text-fg">
      <aside className={`${listMode ? "flex" : "hidden"} min-h-0 w-full shrink-0 flex-col border-r border-line bg-sidebar md:flex md:w-80`}>
        <div className="flex items-center justify-between px-4 pt-4 pb-2">
          <div><h1 className="text-lg font-semibold tracking-tight">WIRE</h1><p className="text-xs text-muted">Local bot control</p></div>
          <button type="button" onClick={() => setSettingsOpen(true)} className="grid size-10 place-items-center rounded-full bg-elevated text-muted hover:bg-bubble-out hover:text-accent" aria-label="Settings" title="Settings"><Settings className="size-5" /></button>
        </div>
        <div className="px-3 pb-2">
          <label className="flex items-center gap-2 rounded-full bg-bg px-3 py-2 text-sm text-muted">
            <Search className="size-4 shrink-0" />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search chat" className="w-full bg-transparent text-fg outline-none placeholder:text-subtle" />
          </label>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          {shown.map((bot) => <ChatRow key={bot.id} bot={bot} active={bot.id === active?.id} onPick={() => { setActive(bot.id); setListMode(false); }} />)}
        </div>
        <div className="border-t border-line px-4 py-3 text-xs leading-relaxed text-muted">Start your Python bot yourself in Windows CMD. WIRE connects to its existing ASP bridge files and never launches or modifies the script.</div>
      </aside>
      <section className={`${listMode ? "hidden" : "flex"} min-h-0 min-w-0 flex-1 flex-col md:flex`}>
        {active ? <Thread bot={active} sound={sound} onBack={() => setListMode(true)} onToggleSound={toggleSound} onToggleInfo={toggleInfo} /> : (
          <div className="grid flex-1 place-items-center px-6 text-center"><div><p className="text-lg font-medium">No bot chat available</p><p className="mt-1 text-sm text-muted">WIRE will connect when the configured bridge publishes its first status snapshot.</p></div></div>
        )}
      </section>
      {active && infoOpen && <>
        <button type="button" className="fixed inset-0 z-20 bg-bg/70 xl:hidden" aria-label="Close details" onClick={toggleInfo} />
        <InfoPanel bot={active} onClose={toggleInfo} />
      </>}
      {settingsOpen && <WireSettings botId={active?.id ?? ""} onClose={() => setSettingsOpen(false)} />}
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
          <span className={`shrink-0 text-xs ${bot.unread > 0 ? "text-accent" : "text-muted"}`}>{last ? hm(last.ts) : ""}</span>
        </span>
        <span className="mt-0.5 flex items-center justify-between gap-2">
          <span className={`truncate text-sm ${bot.typing ? "text-accent" : bot.unread > 0 ? "font-medium text-fg" : "text-muted"}`}>
            {previewLine(bot)}
          </span>
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
  const stick = useRef(true);
  const seen = useRef(bot.messages.length);
  const [chatQuery, setChatQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [hit, setHit] = useState(0);
  const [below, setBelow] = useState(0);
  const [atBottom, setAtBottom] = useState(true);
  const [wallpaper, setWallpaper] = useState("");
  const quotes = bot.source === "bridge" ? [] : laneQuotes(bot);
  const needle = chatQuery.trim().toLowerCase();
  const hits = useMemo(
    () => (needle ? bot.messages.filter((m) => m.text.toLowerCase().includes(needle)).map((m) => m.id) : []),
    [bot.messages, needle],
  );
  const lastLive = [...bot.messages].reverse().find((m) => m.from === "bot");

  function jump() {
    const el = scroller.current;
    if (!el) return;
    stick.current = true;
    el.scrollTop = el.scrollHeight;
    setAtBottom(true);
    setBelow(0);
  }

  function onScroll() {
    const el = scroller.current;
    if (!el) return;
    const near = el.scrollHeight - el.scrollTop - el.clientHeight < 72;
    stick.current = near;
    setAtBottom(near);
    if (near) setBelow(0);
  }

  useEffect(() => {
    const readWallpaper = () => { try { setWallpaper((JSON.parse(localStorage.getItem("wire-wallpapers") || "{}") as Record<string, string>)[bot.id] || ""); } catch { setWallpaper(""); } };
    readWallpaper();
    const onWallpaper = (event: Event) => { const detail = (event as CustomEvent<{ botId: string; dataUrl: string }>).detail; if (detail?.botId === bot.id) setWallpaper(detail.dataUrl || ""); };
    window.addEventListener("wire-wallpaper-change", onWallpaper);
    return () => window.removeEventListener("wire-wallpaper-change", onWallpaper);
  }, [bot.id]);

  useEffect(() => {
    seen.current = bot.messages.length;
    stick.current = true;
    setBelow(0);
    setAtBottom(true);
    setChatQuery("");
    setSearchOpen(false);
    setHit(0);
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [bot.id]);

  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el || needle) return;
    const delta = bot.messages.length - seen.current;
    const last = bot.messages[bot.messages.length - 1];
    seen.current = bot.messages.length;
    if (delta <= 0 && !bot.typing) return;
    if (stick.current || last?.from === "me") {
      el.scrollTop = el.scrollHeight;
      stick.current = true;
      setAtBottom(true);
      setBelow(0);
    } else if (delta > 0) {
      setBelow((n) => n + delta);
    }
  }, [bot.messages.length, bot.typing, bot.id, needle]);

  useEffect(() => {
    setHit(0);
  }, [needle, bot.id]);

  useEffect(() => {
    const id = hits[hit];
    if (!id) return;
    document.getElementById(`m-${id}`)?.scrollIntoView({ block: "center" });
  }, [hit, hits]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f") {
        e.preventDefault();
        setSearchOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

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
          <div className={`truncate text-xs ${bot.online ? "text-accent" : "text-muted"}`}>
            {bot.typing ? (
              <span>typing</span>
            ) : bot.source === "bridge" ? (
              bot.online ? "live script" : "script offline"
            ) : bot.online ? (
              "bot"
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
          className="flex h-10 items-center gap-2 rounded-full px-3 text-sm font-medium text-muted hover:bg-elevated hover:text-fg"
          aria-label="Bot details and script start controls"
          title="Open Details to connect or start this Python script"
        >
          <PanelRight className="size-5" />
          <span className="hidden lg:inline">Details / Start</span>
        </button>
      </header>

      {searchOpen && (
        <div className="flex shrink-0 items-center gap-2 border-b border-line bg-sidebar px-3 py-2">
          <input
            autoFocus
            value={chatQuery}
            onChange={(e) => setChatQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") setSearchOpen(false);
              if (e.key === "Enter" && hits.length) {
                e.preventDefault();
                setHit((i) => (e.shiftKey ? (i - 1 + hits.length) % hits.length : (i + 1) % hits.length));
              }
            }}
            placeholder="Search this chat"
            className="w-full rounded-full bg-bg px-3 py-2 text-sm outline-none"
          />
          <span className="shrink-0 text-xs text-muted tabular-nums">
            {hits.length ? `${hit + 1} of ${hits.length}` : "0"}
          </span>
          <button
            type="button"
            className="grid size-8 place-items-center rounded-full text-muted hover:bg-elevated disabled:opacity-40"
            disabled={!hits.length}
            onClick={() => setHit((i) => (i - 1 + hits.length) % hits.length)}
            aria-label="Previous match"
          >
            <ChevronUp className="size-4" />
          </button>
          <button
            type="button"
            className="grid size-8 place-items-center rounded-full text-muted hover:bg-elevated disabled:opacity-40"
            disabled={!hits.length}
            onClick={() => setHit((i) => (i + 1) % hits.length)}
            aria-label="Next match"
          >
            <ChevronDown className="size-4" />
          </button>
          <button
            type="button"
            className="grid size-8 place-items-center rounded-full text-muted hover:bg-elevated"
            onClick={() => {
              setSearchOpen(false);
              setChatQuery("");
            }}
            aria-label="Close search"
          >
            <X className="size-4" />
          </button>
        </div>
      )}

      <div className="relative min-h-0 flex-1">
        <div ref={scroller} onScroll={onScroll} className="thread-bg absolute inset-0 overflow-y-auto px-3 py-3 md:px-8" style={wallpaper ? { backgroundImage: `linear-gradient(rgba(8,12,18,.38), rgba(8,12,18,.38)), url("${wallpaper}")`, backgroundSize: "cover", backgroundPosition: "center", backgroundAttachment: "fixed" } : undefined}>
          <div className="mx-auto flex max-w-3xl flex-col">
            {bot.messages.map((m, i) => {
              const prev = bot.messages[i - 1];
              const next = bot.messages[i + 1];
              const showDay = !prev || new Date(prev.ts).toDateString() !== new Date(m.ts).toDateString();
              const same = (a?: Message, b?: Message) =>
                !!a && !!b && a.from === b.from && a.from !== "service" && b.ts - a.ts < 5 * 60 * 1000;
              return (
                <div key={m.id} id={`m-${m.id}`}>
                  {showDay && (
                    <div className="my-3 flex justify-center">
                      <span className="rounded-full bg-bubble-in px-3 py-1 text-xs text-muted shadow-sm">{dayLabel(m.ts)}</span>
                    </div>
                  )}
                  <Bubble
                    message={m}
                    query={needle}
                    grouped={same(prev, m)}
                    tail={!same(m, next)}
                    current={hits[hit] === m.id}
                  />
                </div>
              );
            })}
            {bot.typing && (
              <div className="msg-in bubble bubble-in has-tail mt-2 mr-auto flex items-center gap-1 rounded-lg bg-bubble-in px-3 py-3">
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
        {!atBottom && (
          <button
            type="button"
            onClick={jump}
            className="absolute right-4 bottom-3 z-10 grid size-11 place-items-center rounded-full bg-sidebar text-accent shadow-lg ring-1 ring-line"
            aria-label={below ? `${below} new messages` : "Jump to latest"}
          >
            <ArrowDown className="size-5" />
            {below > 0 && (
              <span className="absolute -top-1.5 left-1/2 grid min-w-5 -translate-x-1/2 place-items-center rounded-full bg-accent px-1.5 text-xs font-semibold text-bg">
                {below}
              </span>
            )}
          </button>
        )}
      </div>

      <Composer bot={bot} />
    </>
  );
}

function Bubble({
  message,
  query,
  grouped,
  tail,
  current,
}: {
  message: Message;
  query: string;
  grouped: boolean;
  tail: boolean;
  current: boolean;
}) {
  const [copied, setCopied] = useState(false);
  if (message.from === "service") {
    return (
      <div className="my-2 flex justify-center">
        <span className="max-w-md rounded-full bg-bubble-in px-3 py-1 text-center text-xs text-muted shadow-sm">{message.text}</span>
      </div>
    );
  }
  const mine = message.from === "me";
  const edge = message.tone === "trade" ? "tone-trade" : message.tone === "alert" ? "tone-alert" : "";
  return (
    <div className={`group flex ${mine ? "justify-end" : "justify-start"} ${grouped ? "mt-0.5" : "mt-2"}`}>
      <div
        className={`bubble bubble-col rounded-lg px-2.5 pt-1.5 pb-1.5 text-sm leading-snug ${
          mine ? "bubble-out bg-bubble-out" : `bubble-in bg-bubble-in ${edge}`
        } ${tail ? "has-tail" : ""} ${message.mono ? "font-mono text-xs leading-relaxed" : ""} ${
          current ? "ring-1 ring-warn" : ""
        }`}
      >
        <div className="pr-16 pb-0.5">
          <Rich text={message.text} query={query} />
        </div>
        <span className="absolute right-2 bottom-1 inline-flex items-center gap-0.5 text-xs text-subtle">
          {message.pending && <Clock className="size-3" aria-label="Waiting to send" />}
          {hm(message.ts)}
          {mine && !message.pending && <CheckCheck className="size-3.5 text-accent" aria-label="Read" />}
        </span>
        <button
          type="button"
          onClick={() => {
            void navigator.clipboard?.writeText(message.text).then(() => {
              setCopied(true);
              window.setTimeout(() => setCopied(false), 1200);
            });
          }}
          className="absolute -top-2 right-1 rounded-full bg-sidebar px-2 py-1 text-xs text-muted opacity-0 shadow ring-1 ring-line group-hover:opacity-100"
          aria-label="Copy message"
        >
          {copied ? "Copied" : <Copy className="size-3.5" />}
        </button>
      </div>
    </div>
  );
}

function Composer({ bot }: { bot: Bot }) {
  const send = useDesk((s) => s.send);
  const [draft, setDraft] = useState("");
  const [menuIndex, setMenuIndex] = useState(0);
  const [menuForced, setMenuForced] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setDraft("");
    setMenuIndex(0);
    setMenuForced(false);
    inputRef.current?.focus();
  }, [bot.id]);

  useEffect(() => {
    if (!menuForced) return;
    const onDown = (e: MouseEvent) => {
      if (!boxRef.current?.contains(e.target as Node)) setMenuForced(false);
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [menuForced]);

  const waiting =
    bot.conversation?.kind === "pair"
      ? `Enter trading pair (e.g., BTC/${bot.conversation.lane})`
      : bot.conversation?.kind === "buy_price"
        ? `Enter pair, buy price, and amount (e.g., BTC/${bot.conversation.lane} 80000 0.1)`
        : bot.conversation?.kind === "mb"
          ? `Manual buy on this lane. Send the ${bot.conversation.lane} amount.`
          : null;

  const filtering = draft.startsWith("/") && !draft.includes(" ") && !draft.includes("\n");
  const showMenu = menuForced || filtering;
  const availableCommands = bot.source === "bridge" ? (bot.commands ?? []) : COMMANDS;
  const matches = useMemo(() => {
    if (!showMenu) return [];
    if (!filtering || draft === "/") return availableCommands;
    const needle = draft.toLowerCase();
    return availableCommands.filter(
      (c) => c.name.startsWith(needle) || c.hint.toLowerCase().includes(needle.slice(1)),
    );
  }, [availableCommands, draft, filtering, showMenu]);

  useEffect(() => {
    setMenuIndex(0);
  }, [draft, menuForced]);

  function submit(text: string) {
    const value = text.trim();
    if (!value) return;
    send(value);
    setDraft("");
    setMenuForced(false);
  }

  function onKeyDown(e: ReactKeyboardEvent<HTMLTextAreaElement>) {
    const navigating = showMenu && matches.length && (filtering || !draft);
    if (navigating) {
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
      if (e.key === "Tab") {
        e.preventDefault();
        const name = matches[Math.min(menuIndex, matches.length - 1)]?.name;
        if (name) setDraft(name + " ");
        return;
      }
    }
    if (e.key === "Escape") {
      if (showMenu) {
        e.preventDefault();
        setMenuForced(false);
        if (filtering) setDraft("");
        return;
      }
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (filtering && matches.length) {
        submit(matches[Math.min(menuIndex, matches.length - 1)]?.name ?? draft);
        return;
      }
      submit(draft);
    }
  }

  return (
    <div ref={boxRef} className="relative shrink-0 border-t border-line bg-sidebar">
      {showMenu && matches.length > 0 && (
        <ul className="absolute right-2 bottom-full left-2 z-20 mb-2 max-h-80 overflow-y-auto rounded-xl border border-line bg-sidebar py-1 shadow-xl">
          {matches.map((cmd, i) => (
            <li key={cmd.name}>
              <button
                type="button"
                onMouseEnter={() => setMenuIndex(i)}
                onClick={() => submit(cmd.name)}
                className={`flex w-full items-baseline gap-3 px-3 py-2.5 text-left ${i === menuIndex ? "bg-elevated" : ""}`}
              >
                <span className={`w-40 shrink-0 font-medium ${cmd.danger ? "text-danger" : "text-fg"}`}>{cmd.name}</span>
                <span className="truncate text-sm text-muted">{cmd.hint}</span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {waiting && (
        <div className="mx-3 mt-2 flex items-stretch overflow-hidden rounded-lg bg-bg">
          <div className="w-1 shrink-0 bg-accent" />
          <div className="min-w-0 flex-1 px-3 py-2">
            <div className="text-xs font-medium text-accent">{bot.name}</div>
            <div className="truncate text-sm text-muted">{waiting}</div>
          </div>
          <button
            type="button"
            onClick={() => submit("/cancel")}
            className="grid w-10 place-items-center text-muted hover:text-fg"
            aria-label="Cancel"
          >
            <X className="size-4" />
          </button>
        </div>
      )}

      <div className="flex items-end gap-1.5 px-2 py-2">
        <button
          type="button"
          onClick={() => {
            setMenuForced((v) => !v);
            inputRef.current?.focus();
          }}
          aria-expanded={menuForced}
          aria-label="Commands"
          className={`grid size-11 shrink-0 place-items-center rounded-full ${menuForced ? "bg-accent-strong text-fg" : "text-muted hover:bg-elevated"}`}
        >
          {menuForced ? <X className="size-5" /> : <Menu className="size-5" />}
        </button>
        <textarea
          ref={inputRef}
          rows={1}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={waiting ? "Reply" : "Message"}
          className="max-h-32 min-h-11 flex-1 resize-none rounded-3xl bg-bg px-4 py-2.5 text-sm outline-none placeholder:text-subtle"
        />
        <button
          type="button"
          onClick={() => submit(draft)}
          disabled={!draft.trim()}
          className="grid size-11 shrink-0 place-items-center rounded-full bg-accent text-bg disabled:bg-elevated disabled:text-subtle"
          aria-label="Send"
        >
          <Send className="size-5" />
        </button>
      </div>
    </div>
  );
}

function InfoPanel({ bot, onClose }: { bot: Bot; onClose: () => void }) {
  const updateCommands = useDesk((s) => s.updateCommands);
  const [editingCommands, setEditingCommands] = useState(false);
  const [commandDraft, setCommandDraft] = useState(commandLines(bot.commands));
  return (
    <aside className="absolute inset-y-0 right-0 z-30 flex w-full min-h-0 flex-col border-l border-line bg-sidebar sm:w-80 xl:static">
      <div className="flex items-center justify-between px-4 py-3"><h2 className="font-semibold">Bot details</h2><button type="button" onClick={onClose} className="grid size-10 place-items-center rounded-full hover:bg-elevated" aria-label="Close details"><X className="size-5" /></button></div>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 pb-6">
        <div className="flex items-center gap-3"><Avatar name={bot.name} online={bot.online} /><div><div className="font-medium">{bot.name}</div><div className={`text-sm ${bot.online ? "text-online" : "text-muted"}`}>{bot.online ? "Bridge connected" : "Waiting for running bot"}</div></div></div>
        <section className="rounded-md bg-bg p-3 text-sm"><h3 className="font-medium">Connection</h3><p className="mt-2 text-xs leading-relaxed text-muted">Start ABinanceTradingBot.py yourself in Windows CMD. WIRE does not launch, stop, or edit the script. The integrated ASP bridge must be active in the running process.</p><p className="mt-2 break-all font-mono text-xs text-muted">C:\\Users\\pauld\\Desktop\\ABINANCE TESTNET</p></section>
        <section className="rounded-md bg-bg p-3 text-sm">
          <div className="flex items-center justify-between gap-2"><h3 className="font-medium">Command menu</h3><button type="button" className="text-xs text-accent" onClick={() => { setCommandDraft(commandLines(bot.commands)); setEditingCommands((v) => !v); }}>{editingCommands ? "Cancel" : "Edit commands"}</button></div>
          {editingCommands ? <><p className="mt-1 text-xs text-muted">One command per line: /command | description. This edits only WIRE's menu. The running bot bridge must support the command.</p><textarea value={commandDraft} onChange={(e) => setCommandDraft(e.target.value)} rows={10} className="mt-2 w-full rounded-md bg-sidebar p-2 font-mono text-xs text-fg outline-none" /><button type="button" className="mt-2 rounded-md bg-accent-strong px-3 py-2 text-xs font-medium" onClick={() => { updateCommands(bot.id, parseCommandLines(commandDraft)); setEditingCommands(false); }}>Save commands</button></> : <p className="mt-1 text-xs text-muted">{(bot.commands ?? []).length} commands configured. No script upload or registration is used.</p>}
        </section>
        <p className="text-xs leading-relaxed text-subtle">Type / in the chat to filter commands. Enter sends a command to the running bot. Live trading messages are read from the bridge feed.</p>
      </div>
    </aside>
  );
}

