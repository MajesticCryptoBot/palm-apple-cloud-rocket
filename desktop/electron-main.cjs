const { app, BrowserWindow, dialog, ipcMain, shell, Notification } = require("electron");
const fs = require("node:fs");
const path = require("node:path");
const http = require("node:http");
const os = require("node:os");
const crypto = require("node:crypto");

const APP_PORT = 47831;
// This must match the directory configured in the user's ASP bridge script.
const BRIDGE_DIR = path.join(os.homedir(), "Desktop", "ABINANCE TESTNET");
const QUEUE_FILE = path.join(BRIDGE_DIR, "asp_command_queue.json");
const RESPONSE_FILE = path.join(BRIDGE_DIR, "asp_command_response.json");
const LIVE_FILE = path.join(BRIDGE_DIR, "asp_live_feed.json");
const SNAPSHOT_FILE = path.join(BRIDGE_DIR, "asp_status_snapshot.json");
const seenLiveIds = new Set();
let firstLiveRead = true;
let serverProcess;

function sleep(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }
function readJson(file) {
  try { return JSON.parse(fs.readFileSync(file, "utf8")); } catch { return null; }
}
function writeJsonAtomic(file, value) {
  const temp = file + "." + process.pid + ".tmp";
  fs.writeFileSync(temp, JSON.stringify(value, null, 2), "utf8");
  fs.renameSync(temp, file);
}
function bridgeSnapshot() {
  const snapshot = readJson(SNAPSHOT_FILE);
  if (!snapshot || !snapshot.ts) return { connected: false, snapshot: null, error: "Waiting for the running bot bridge to publish its status snapshot." };
  const timestamp = Date.parse(snapshot.ts);
  const fresh = Number.isFinite(timestamp) && Date.now() - timestamp < 15000 && Date.now() >= timestamp - 5000;
  const filesExist = fs.existsSync(LIVE_FILE) && fs.existsSync(QUEUE_FILE) || fs.existsSync(LIVE_FILE) && fs.existsSync(RESPONSE_FILE);
  return {
    connected: Boolean(fresh && filesExist),
    snapshot,
    error: fresh ? "" : "Bridge snapshot is stale. Confirm the bot is running in CMD and its bridge task is active.",
  };
}
function readLiveItems() {
  const entries = readJson(LIVE_FILE);
  if (!Array.isArray(entries)) return [];
  const fresh = [];
  for (const item of entries) {
    const id = String(item?.id ?? "");
    if (!id || seenLiveIds.has(id)) continue;
    seenLiveIds.add(id);
    fresh.push({ id, text: String(item?.text ?? ""), ts: item?.ts ? Date.parse(item.ts) : Date.now() });
  }
  // The bridge itself keeps only 120 entries; cap our dedupe set too.
  while (seenLiveIds.size > 500) seenLiveIds.delete(seenLiveIds.values().next().value);
  if (firstLiveRead) firstLiveRead = false;
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
  ipcMain.handle("wire:bridge-poll", () => {
    const state = bridgeSnapshot();
    const items = readLiveItems();
    return {
      connected: state.connected,
      error: state.error,
      snapshot: state.snapshot,
      items,
      bridgeDirectory: BRIDGE_DIR,
    };
  });
  ipcMain.handle("wire:bridge-command", async (_event, rawCommand) => {
    const command = String(rawCommand || "").trim();
    if (!command || command.length > 1000) return { ok: false, error: "Enter a valid command." };
    const state = bridgeSnapshot();
    if (!state.connected) return { ok: false, error: state.error || "The running bot bridge is not connected. Start your bot manually in CMD." };
    // Do not overwrite a request that the bot has not picked up yet.
    const queueDeadline = Date.now() + 5000;
    while (fs.existsSync(QUEUE_FILE) && Date.now() < queueDeadline) await sleep(100);
    if (fs.existsSync(QUEUE_FILE)) return { ok: false, error: "The bot still has a queued command. Wait for it to finish, then retry." };
    const id = crypto.randomUUID();
    try {
      writeJsonAtomic(QUEUE_FILE, { id, command });
    } catch (error) {
      return { ok: false, error: "Could not write the bridge command queue: " + String(error?.message || error) };
    }
    const deadline = Date.now() + 35000;
    while (Date.now() < deadline) {
      const response = readJson(RESPONSE_FILE);
      if (response && String(response.id) === id) {
        return { ok: true, text: String(response.text || "The bot completed the command without a message."), ts: response.ts || new Date().toISOString() };
      }
      const current = bridgeSnapshot();
      if (!current.connected) return { ok: false, error: current.error || "The bot bridge stopped responding while the command was running." };
      await sleep(150);
    }
    return { ok: false, error: "Timed out waiting for the running bot. Check the CMD window for bridge errors; WIRE did not execute a simulated command." };
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
  throw new Error("The WIRE local server did not become ready. Restart the app and try again.");
}
function appFile(...parts) {
  if (app.isPackaged) return path.join(app.getAppPath(), ...parts);
  if (parts[0] === "desktop") return path.join(__dirname, ...parts.slice(1));
  return path.join(__dirname, "..", ...parts);
}
function startLocalServer() {
  const entry = appFile(".output", "server", "index.mjs");
  if (!fs.existsSync(entry)) throw new Error("WIRE local web server is missing from the installation.");
  serverProcess = require("node:child_process").spawn(process.execPath, [entry], {
    env: { ...process.env, ELECTRON_RUN_AS_NODE: "1", HOST: "127.0.0.1", NITRO_HOST: "127.0.0.1", PORT: String(APP_PORT), NITRO_PORT: String(APP_PORT), NODE_ENV: "production" },
    stdio: "ignore",
    detached: false,
  });
}
async function createWindow() {
  await waitForLocalApp();
  const win = new BrowserWindow({
    width: 1320, height: 860, minWidth: 900, minHeight: 600,
    backgroundColor: "#0e1621", autoHideMenuBar: true,
    webPreferences: {
      preload: appFile("desktop", "electron-preload.cjs"),
      contextIsolation: true, nodeIntegration: false, sandbox: true,
    },
  });
  await win.loadURL("http://127.0.0.1:" + APP_PORT);
}
app.whenReady().then(() => {
  registerIpc();
  startLocalServer();
  createWindow().catch((error) => {
    dialog.showErrorBox("WIRE could not start", String(error?.message || error));
    app.quit();
  });
});
app.on("before-quit", () => {
  if (serverProcess && !serverProcess.killed) serverProcess.kill();
});
app.on("window-all-closed", () => { if (process.platform !== "darwin") app.quit(); });
