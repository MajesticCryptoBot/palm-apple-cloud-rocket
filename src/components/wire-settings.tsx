import { useEffect, useState } from "react";
import { X, ImagePlus, Palette, BellRing } from "lucide-react";

type Props = { botId: string; onClose: () => void };

const themes = {
  black: { "--color-bg": "#090b10", "--color-sidebar": "#11151d", "--color-elevated": "#1a202b", "--color-bubble-in": "#171d27", "--color-bubble-out": "#243b57", "--color-accent": "#8ab4f8", "--color-accent-strong": "#365f96", "--color-fg": "#f4f6fb", "--color-muted": "#9ba7b8", "--color-subtle": "#697789", "--color-line": "#090b10" },
  midnight: { "--color-bg": "#081426", "--color-sidebar": "#10213a", "--color-elevated": "#1a3150", "--color-bubble-in": "#142943", "--color-bubble-out": "#244d75", "--color-accent": "#78bdff", "--color-accent-strong": "#326da8", "--color-fg": "#f3f7ff", "--color-muted": "#9aafc9", "--color-subtle": "#6f87a5", "--color-line": "#07101e" },
} as const;

function applyTheme(theme: string) {
  const palette = theme === "midnight" ? themes.midnight : themes.black;
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
      <section role="dialog" aria-modal="true" aria-labelledby="wire-settings-title" className="w-full max-w-xl overflow-hidden rounded-2xl border border-line bg-sidebar text-fg shadow-2xl">
        <header className="flex items-center justify-between border-b border-line px-5 py-4">
          <div><h2 id="wire-settings-title" className="text-lg font-semibold">WIRE Settings</h2><p className="text-sm text-muted">Appearance and notifications</p></div>
          <button onClick={onClose} className="grid size-9 place-items-center rounded-full hover:bg-elevated" aria-label="Close settings"><X className="size-5" /></button>
        </header>
        <div className="max-h-[75vh] space-y-6 overflow-y-auto p-5">
          <section>
            <h3 className="flex items-center gap-2 font-medium"><Palette className="size-4 text-accent" /> Theme</h3>
            <p className="mt-1 text-sm text-muted">Choose the main WIRE color palette.</p>
            <div className="mt-3 grid grid-cols-2 gap-3">
              <button onClick={() => chooseTheme("black")} className={`rounded-xl border p-3 text-left ${theme === "black" ? "border-accent" : "border-line"}`}>
                <div className="mb-2 flex gap-1"><span className="h-7 flex-1 rounded bg-[#090b10]" /><span className="h-7 flex-1 rounded bg-[#1a202b]" /><span className="h-7 flex-1 rounded bg-[#243b57]" /></div><span className="font-medium">Dark black</span><span className="block text-xs text-muted">Deep charcoal</span>
              </button>
              <button onClick={() => chooseTheme("midnight")} className={`rounded-xl border p-3 text-left ${theme === "midnight" ? "border-accent" : "border-line"}`}>
                <div className="mb-2 flex gap-1"><span className="h-7 flex-1 rounded bg-[#081426]" /><span className="h-7 flex-1 rounded bg-[#1a3150]" /><span className="h-7 flex-1 rounded bg-[#244d75]" /></div><span className="font-medium">Midnight blue</span><span className="block text-xs text-muted">Telegram-inspired navy</span>
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
