import { useEffect, useState } from "react";
import { X, ImagePlus, Palette, BellRing } from "lucide-react";

type Props = { botId: string; onClose: () => void };

const themes = {
  black: {
    "--color-bg": "#080b12", "--color-sidebar": "#101722", "--color-elevated": "#1a2432",
    "--color-bubble-in": "#182333", "--color-bubble-out": "#263f60",
    "--color-accent": "#91bfff", "--color-accent-strong": "#416fc0",
    "--color-fg": "#f5f7ff", "--color-muted": "#a0aec3", "--color-subtle": "#718098",
    "--color-line": "#202b3a", "--color-online": "#6be0b0",
  },
  midnight: {
    "--color-bg": "#071323", "--color-sidebar": "#0e2038", "--color-elevated": "#1b3554",
    "--color-bubble-in": "#142b46", "--color-bubble-out": "#245987",
    "--color-accent": "#77d3ff", "--color-accent-strong": "#287bb5",
    "--color-fg": "#f3f8ff", "--color-muted": "#a5bdd9", "--color-subtle": "#7894b6",
    "--color-line": "#213a57", "--color-online": "#64e2b1",
  },
  aurora: {
    "--color-bg": "#09151a", "--color-sidebar": "#10252a", "--color-elevated": "#1a3538",
    "--color-bubble-in": "#173238", "--color-bubble-out": "#245c61",
    "--color-accent": "#7ce7d1", "--color-accent-strong": "#278c83",
    "--color-fg": "#effdfa", "--color-muted": "#a1c8c4", "--color-subtle": "#739d98",
    "--color-line": "#234447", "--color-online": "#66e2a9",
  },
  graphite: {
    "--color-bg": "#111318", "--color-sidebar": "#1b1e25", "--color-elevated": "#292e38",
    "--color-bubble-in": "#252b34", "--color-bubble-out": "#414c66",
    "--color-accent": "#b4c7ff", "--color-accent-strong": "#5c72b8",
    "--color-fg": "#f7f8fc", "--color-muted": "#b3bac8", "--color-subtle": "#858e9f",
    "--color-line": "#303642", "--color-online": "#7bd9b0",
  },
} as const;

function applyTheme(theme: string) {
  const palette = theme === "aurora" ? themes.aurora : theme === "graphite" ? themes.graphite : theme === "midnight" ? themes.midnight : themes.black;
  for (const [key, value] of Object.entries(palette)) document.documentElement.style.setProperty(key, value);
  document.documentElement.dataset.wireTheme = theme;
}

export function WireSettings({ botId, onClose }: Props) {
  const [theme, setTheme] = useState(() => {
    try { return localStorage.getItem("wire-theme") || "midnight"; } catch { return "midnight"; }
  });
  const [notificationStyle, setNotificationStyle] = useState(() => {
    try { return localStorage.getItem("wire-notification-style") || "system-and-chat"; } catch { return "system-and-chat"; }
  });
  const [hasWallpaper, setHasWallpaper] = useState(false);
  const [status, setStatus] = useState("");

  useEffect(() => {
    applyTheme(theme);
    try { setHasWallpaper(Boolean((JSON.parse(localStorage.getItem("wire-wallpapers") || "{}") as Record<string, string>)[botId])); } catch { setHasWallpaper(false); }
  }, [theme, botId]);

  function chooseTheme(value: string) {
    setTheme(value);
    try { localStorage.setItem("wire-theme", value); } catch { /* settings remain usable for this session */ }
    applyTheme(value);
  }

  async function uploadWallpaper() {
    const dataUrl = await window.wire?.selectWallpaper();
    if (!dataUrl || !botId) return;
    try {
      const map = JSON.parse(localStorage.getItem("wire-wallpapers") || "{}") as Record<string, string>;
      map[botId] = dataUrl;
      localStorage.setItem("wire-wallpapers", JSON.stringify(map));
      setHasWallpaper(true);
      window.dispatchEvent(new CustomEvent("wire-wallpaper-change", { detail: { botId, dataUrl } }));
      setStatus("Wallpaper applied to this chat.");
    } catch {
      setStatus("This image could not be saved. Please choose a smaller image.");
    }
  }

  function removeWallpaper() {
    try {
      const map = JSON.parse(localStorage.getItem("wire-wallpapers") || "{}") as Record<string, string>;
      delete map[botId];
      localStorage.setItem("wire-wallpapers", JSON.stringify(map));
    } catch { /* no saved wallpaper */ }
    setHasWallpaper(false);
    window.dispatchEvent(new CustomEvent("wire-wallpaper-change", { detail: { botId, dataUrl: "" } }));
    setStatus("Chat wallpaper removed.");
  }

  function changeNotification(value: string) {
    setNotificationStyle(value);
    try { localStorage.setItem("wire-notification-style", value); } catch { /* in-memory selection still applies */ }
    setStatus("Notification preference saved.");
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/65 p-4" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <section role="dialog" aria-modal="true" aria-labelledby="wire-settings-title" className="wire-settings-dialog w-full max-w-xl overflow-hidden rounded-2xl border border-line bg-sidebar text-fg shadow-2xl">
        <header className="flex items-center justify-between border-b border-line px-5 py-4">
          <div><h2 id="wire-settings-title" className="text-lg font-semibold">WIRE Settings</h2><p className="text-sm text-muted">Appearance and notifications</p></div>
          <button onClick={onClose} className="grid size-9 place-items-center rounded-full hover:bg-elevated" aria-label="Close settings"><X className="size-5" /></button>
        </header>
        <div className="max-h-[75vh] space-y-6 overflow-y-auto p-5">
          <section>
            <h3 className="flex items-center gap-2 font-medium"><Palette className="size-4 text-accent" /> Theme</h3>
            <p className="mt-1 text-sm text-muted">Choose the main WIRE color palette.</p>
            <div className="mt-3 grid grid-cols-2 gap-3">
              <button onClick={() => chooseTheme("black")} className={`wire-theme-card rounded-xl border p-3 text-left ${theme === "black" ? "is-selected border-accent" : "border-line"}`}>
                <div className="mb-2 flex gap-1"><span className="h-7 flex-1 rounded bg-[#090b10]" /><span className="h-7 flex-1 rounded bg-[#1a202b]" /><span className="h-7 flex-1 rounded bg-[#243b57]" /></div><span className="font-medium">Dark black</span><span className="block text-xs text-muted">Deep charcoal</span>
              </button>
              <button onClick={() => chooseTheme("midnight")} className={`wire-theme-card rounded-xl border p-3 text-left ${theme === "midnight" ? "is-selected border-accent" : "border-line"}`}>
                <div className="mb-2 flex gap-1"><span className="h-7 flex-1 rounded bg-[#081426]" /><span className="h-7 flex-1 rounded bg-[#1a3150]" /><span className="h-7 flex-1 rounded bg-[#244d75]" /></div><span className="font-medium">Midnight blue</span><span className="block text-xs text-muted">Telegram-inspired navy</span>
              </button>
              <button onClick={() => chooseTheme("aurora")} className="wire-theme-card rounded-xl border border-line p-3 text-left">
                <div className="mb-2 flex gap-1"><span className="h-7 flex-1 rounded bg-[#09151a]" /><span className="h-7 flex-1 rounded bg-[#1a3538]" /><span className="h-7 flex-1 rounded bg-[#245c61]" /></div><span className="font-medium">Aurora teal</span><span className="block text-xs text-muted">Cool teal accents</span>
              </button>
              <button onClick={() => chooseTheme("graphite")} className="wire-theme-card rounded-xl border border-line p-3 text-left">
                <div className="mb-2 flex gap-1"><span className="h-7 flex-1 rounded bg-[#111318]" /><span className="h-7 flex-1 rounded bg-[#292e38]" /><span className="h-7 flex-1 rounded bg-[#414c66]" /></div><span className="font-medium">Graphite</span><span className="block text-xs text-muted">Soft slate contrast</span>
              </button>
            </div>
          </section>
          <section className="border-t border-line pt-5">
            <h3 className="flex items-center gap-2 font-medium"><ImagePlus className="size-4 text-accent" /> Chat wallpaper</h3>
            <p className="mt-1 text-sm text-muted">Choose an image from your PC for the currently selected chat.</p>
            <div className="mt-3 flex flex-wrap gap-2">
              <button onClick={() => void uploadWallpaper()} disabled={!botId} className="rounded-lg bg-accent-strong px-4 py-2 text-sm font-medium disabled:opacity-40">Upload picture…</button>
              <button onClick={removeWallpaper} disabled={!hasWallpaper} className="rounded-lg bg-elevated px-4 py-2 text-sm disabled:opacity-40">Remove wallpaper</button>
            </div>
            {hasWallpaper && <p className="mt-2 text-xs text-online">A wallpaper is set for this chat.</p>}
          </section>
          <section className="border-t border-line pt-5">
            <h3 className="flex items-center gap-2 font-medium"><BellRing className="size-4 text-accent" /> Notifications</h3>
            <p className="mt-1 text-sm text-muted">Trading messages always remain in the relevant WIRE chat. Choose whether Windows desktop pop-up notifications also appear.</p>
            <label className="mt-3 block text-sm">
              Notification style
              <select value={notificationStyle} onChange={(e) => changeNotification(e.target.value)} className="mt-1 w-full rounded-lg border border-line bg-bg px-3 py-2.5 text-fg outline-none">
                <option value="system-and-chat">Windows pop-up + WIRE chat</option>
                <option value="system-only">Windows pop-up (message also saved in chat)</option>
                <option value="chat-only">WIRE chat only — no Windows pop-ups</option>
              </select>
            </label>
            <p className="mt-2 text-xs text-muted">Windows pop-ups depend on Windows notification permissions for WIRE.</p>
          </section>
          {status && <p role="status" className="rounded-lg bg-elevated px-3 py-2 text-sm text-muted">{status}</p>}
        </div>
        <footer className="flex justify-end border-t border-line px-5 py-3"><button onClick={onClose} className="rounded-lg bg-accent-strong px-4 py-2 text-sm font-medium">Done</button></footer>
      </section>
    </div>
  );
}
