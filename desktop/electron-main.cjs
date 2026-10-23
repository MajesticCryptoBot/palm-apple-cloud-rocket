const { app, BrowserWindow, dialog, ipcMain, shell, Notification, Tray, Menu } = require("electron");
const fs = require("node:fs");
const path = require("node:path");
const http = require("node:http");
const os = require("node:os");
const crypto = require("node:crypto");

const APP_PORT = 47831;
const DESKTOP = path.join(os.homedir(), "Desktop");
const DEFAULT_BRIDGE = "ABINANCE TESTNET";
const ALLOWED_BRIDGES = new Set([
  "ABINANCE TESTNET",
  "BINANCE LIVE",
  "Bitget Live Bot",
  "Bybit Live Bot",
  "GROK TESTNET",
  "ZZZBinance METRICS LIVE",
]);
const seenLiveIds = new Map();
let serverProcess;
let mainWindow;
let tray;
let quitting = false;

function sleep(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }
function bridgeDir(raw) {
  const name = path.basename(String(raw || DEFAULT_BRIDGE).replace(/[\\/]+$/, ""));
  if (!ALLOWED_BRIDGES.has(name)) throw new Error("This bot folder is not configured in WIRE.");
  return path.join(DESKTOP, name);
}
function bridgeFiles(raw) {
  const dir = bridgeDir(raw);
  return {
    directory: dir,
    queue: path.join(dir, "asp_command_queue.json"),
    response: path.join(dir, "asp_command_response.json"),
    live: path.join(dir, "asp_live_feed.json"),
    snapshot: path.join(dir, "asp_status_snapshot.json"),
  };
}
function readJson(file) {
  try { return JSON.parse(fs.readFileSync(file, "utf8")); } catch { return null; }
}
function writeJsonAtomic(file, value) {
  const temp = file + "." + process.pid + ".tmp";
  fs.writeFileSync(temp, JSON.stringify(value, null, 2), "utf8");
  fs.renameSync(temp, file);
}
function bridgeSnapshot(raw) {
  let files;
  try { files = bridgeFiles(raw); } catch (error) {
    return { connected: false, snapshot: null, error: String(error?.message || error) };
  }
  const snapshot = readJson(files.snapshot);
  if (!snapshot || !snapshot.ts) return { connected: false, snapshot: null, error: "" };
  const timestamp = Date.parse(snapshot.ts);
  const fresh = Number.isFinite(timestamp) && Date.now() - timestamp < 15000 && Date.now() >= timestamp - 5000;
  return { connected: Boolean(fresh), snapshot, error: fresh ? "" : "" };
}
function readLiveItems(raw) {
  let files;
  try { files = bridgeFiles(raw); } catch { return []; }
  const entries = readJson(files.live);
  if (!Array.isArray(entries)) return [];
  const key = files.directory;
  if (!seenLiveIds.has(key)) seenLiveIds.set(key, new Set());
  const seen = seenLiveIds.get(key);
  const fresh = [];
  for (const item of entries) {
    const id = String(item?.id ?? "");
    if (!id || seen.has(id)) continue;
    seen.add(id);
    fresh.push({ id, text: String(item?.text ?? ""), ts: item?.ts ? Date.parse(item.ts) : Date.now() });
  }
  while (seen.size > 500) seen.delete(seen.values().next().value);
  return fresh;
}
function registerIpc() {
  ipcMain.handle("wire:select-wallpaper", async () => {
    const result = await dialog.showOpenDialog({
      title: "Choose a chat wallpaper",
      properties: ["openFile"],
      filters: [{ name: "Images", extensions: ["png", "jpg", "jpeg", "webp", "gif"] }],
    });
    if (result.canceled || !result.filePaths[0]) return null;
    const filePath = result.filePaths[0];
    const ext = path.extname(filePath).toLowerCase();
    const mime = ext === ".png" ? "image/png" : ext === ".webp" ? "image/webp" : ext === ".gif" ? "image/gif" : "image/jpeg";
    return "data:" + mime + ";base64," + fs.readFileSync(filePath).toString("base64");
  });
  ipcMain.handle("wire:show-notification", (_event, payload) => {
    const title = String(payload?.title || "WIRE").slice(0, 100);
    const body = String(payload?.body || "").slice(0, 500);
    if (!Notification.isSupported() || !body) return { ok: false };
    new Notification({ title, body, silent: Boolean(payload?.silent) }).show();
    return { ok: true };
  });
  ipcMain.handle("wire:bridge-poll", (_event, rawDirectory) => {
    const state = bridgeSnapshot(rawDirectory);
    return { connected: state.connected, snapshot: state.snapshot, items: readLiveItems(rawDirectory), bridgeDirectory: bridgeDir(rawDirectory) };
  });
  ipcMain.handle("wire:bridge-command", async (_event, payload) => {
    const command = String(payload?.command || "").trim();
    let files;
    try { files = bridgeFiles(payload?.directory); } catch (error) {
      return { ok: false, error: String(error?.message || error) };
    }
    if (!command || command.length > 1000) return { ok: false, error: "Enter a valid command." };
    if (!bridgeSnapshot(payload?.directory).connected) return { ok: false, error: "This bot is offline. Check its running process and bridge." };
    const queueDeadline = Date.now() + 5000;
    while (fs.existsSync(files.queue) && Date.now() < queueDeadline) await sleep(100);
    if (fs.existsSync(files.queue)) return { ok: false, error: "The bot is still processing a command. Retry in a moment." };
    const id = crypto.randomUUID();
    try { writeJsonAtomic(files.queue, { id, command }); }
    catch (error) { return { ok: false, error: "Could not queue command: " + String(error?.message || error) }; }
    const deadline = Date.now() + 35000;
    while (Date.now() < deadline) {
      const response = readJson(files.response);
      if (response && String(response.id) === id) {
        return { ok: true, text: String(response.text || "The bot completed the command without a message."), ts: response.ts || new Date().toISOString() };
      }
      if (!bridgeSnapshot(payload?.directory).connected) return { ok: false, error: "The bot stopped responding before the command completed." };
      await sleep(150);
    }
    return { ok: false, error: "The command timed out. Check the bot process and try again." };
  });
}

function probeLocalApp() {
  return new Promise((resolve) => {
    const req = http.get({ hostname: "127.0.0.1", port: APP_PORT, path: "/", timeout: 800 }, (res) => {
      res.resume();
      resolve(Boolean(res.statusCode && res.statusCode < 500));
    });
    req.on("timeout", () => { req.destroy(); resolve(false); });
    req.on("error", () => resolve(false));
  });
}
async function waitForLocalApp() {
  const deadline = Date.now() + 25000;
  while (Date.now() < deadline) {
    if (await probeLocalApp()) return;
    await sleep(250);
  }
  throw new Error("WIRE could not start. Restart the app and try again.");
}
function appFile(...parts) {
  if (app.isPackaged) return path.join(app.getAppPath(), ...parts);
  if (parts[0] === "desktop") return path.join(__dirname, ...parts.slice(1));
  return path.join(__dirname, "..", ...parts);
}
function startLocalServer() {
  const entry = appFile(".output", "server", "index.mjs");
  if (!fs.existsSync(entry)) throw new Error("WIRE installation is incomplete.");
  serverProcess = require("node:child_process").spawn(process.execPath, [entry], {
    env: { ...process.env, ELECTRON_RUN_AS_NODE: "1", HOST: "127.0.0.1", NITRO_HOST: "127.0.0.1", PORT: String(APP_PORT), NITRO_PORT: String(APP_PORT), NODE_ENV: "production" },
    stdio: "ignore",
    detached: false,
  });
}
async function showWindow() {
  if (!mainWindow) return;
  mainWindow.show();
  mainWindow.focus();
}
async function createWindow() {
  await waitForLocalApp();
  mainWindow = new BrowserWindow({
    width: 1320, height: 860, minWidth: 900, minHeight: 600,
    backgroundColor: "#0e1621", autoHideMenuBar: true, show: false,
    webPreferences: { preload: appFile("desktop", "electron-preload.cjs"), contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  mainWindow.on("ready-to-show", () => mainWindow?.show());
  mainWindow.on("close", (event) => {
    if (!quitting) { event.preventDefault(); mainWindow?.hide(); }
  });
  await mainWindow.loadURL("http://127.0.0.1:" + APP_PORT);
  try {
    const icon = await app.getFileIcon(process.execPath, { size: "small" });
    tray = new Tray(icon);
    tray.setToolTip("WIRE");
    tray.setContextMenu(Menu.buildFromTemplate([
      { label: "Open WIRE", click: () => void showWindow() },
      { type: "separator" },
      { label: "Quit WIRE", click: () => { quitting = true; app.quit(); } },
    ]));
    tray.on("double-click", () => void showWindow());
  } catch { /* tray is optional on restricted Windows desktops */ }
}
app.whenReady().then(() => {
  registerIpc();
  startLocalServer();
  createWindow().catch((error) => { dialog.showErrorBox("WIRE could not start", String(error?.message || error)); app.quit(); });
});
app.on("before-quit", () => {
  quitting = true;
  if (tray) tray.destroy();
  if (serverProcess && !serverProcess.killed) serverProcess.kill();
});
app.on("window-all-closed", () => { /* WIRE stays in the notification area until Quit is chosen. */ });
