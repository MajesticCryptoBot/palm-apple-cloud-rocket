const { app, BrowserWindow, dialog, ipcMain, shell, Notification } = require("electron");
const { spawn, execFile } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const http = require("node:http");
const os = require("node:os");

const APP_PORT = 47831;
const runningBots = new Map();
let serverProcess;

function registryPath() { return path.join(app.getPath("userData"), "wire-processes.json"); }
function botLogPath(port) { return path.join(app.getPath("userData"), "logs", "bot-" + port + ".log"); }
function readRegistry() {
  try { return JSON.parse(fs.readFileSync(registryPath(), "utf8")); } catch { return {}; }
}
function writeRegistry(registry) {
  try { fs.mkdirSync(path.dirname(registryPath()), { recursive: true }); fs.writeFileSync(registryPath(), JSON.stringify(registry, null, 2), "utf8"); } catch (error) { console.error("Could not persist WIRE process registry:", error); }
}

function appFile(...parts) {
  if (app.isPackaged) {
    if (parts[0] === "bridge") return path.join(process.resourcesPath, ...parts);
    return path.join(app.getAppPath(), ...parts);
  }
  if (parts[0] === "bridge") return path.join(__dirname, parts[1]);
  if (parts[0] === "desktop") return path.join(__dirname, ...parts.slice(1));
  return path.join(__dirname, "..", ...parts);
}

function findPython(scriptPath) {
  const dir = path.dirname(scriptPath);
  const localCandidates = [
    path.join(dir, ".venv", "Scripts", "python.exe"),
    path.join(dir, "venv", "Scripts", "python.exe"),
    path.join(path.dirname(dir), ".venv", "Scripts", "python.exe"),
  ];
  const pathCandidates = String(process.env.PATH || "")
    .split(path.delimiter)
    .filter(Boolean)
    .map((entry) => path.join(entry.replace(/^"|"$/g, ""), "python.exe"));
  return [...localCandidates, ...pathCandidates].find((p) => fs.existsSync(p)) || null;
}

function requestHealth(port) {
  return new Promise((resolve) => {
    const req = http.get({ hostname: "127.0.0.1", port, path: "/health", timeout: 600 }, (res) => {
      let body = "";
      res.setEncoding("utf8");
      res.on("data", (chunk) => body += chunk);
      res.on("end", () => {
        try { resolve(JSON.parse(body)); } catch { resolve(null); }
      });
    });
    req.on("timeout", () => { req.destroy(); resolve(null); });
    req.on("error", () => resolve(null));
  });
}

function registerIpc() {
  ipcMain.handle("wire:select-script", async () => {
    const result = await dialog.showOpenDialog({
      title: "Choose a local Python bot script",
      properties: ["openFile"],
      filters: [{ name: "Python scripts", extensions: ["py"] }],
    });
    return result.canceled ? null : result.filePaths[0] || null;
  });
  ipcMain.handle("wire:open-bot-log", async (_event, rawPort) => {
    const port = Number(rawPort);
    if (!Number.isInteger(port) || port < 47832 || port > 47999) return { ok: false, error: "Invalid bot port." };
    const logPath = botLogPath(port);
    fs.mkdirSync(path.dirname(logPath), { recursive: true });
    if (!fs.existsSync(logPath)) fs.writeFileSync(logPath, "WIRE has not started this bot yet.\n", "utf8");
    const error = await shell.openPath(logPath);
    return error ? { ok: false, error } : { ok: true };
  });
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
  ipcMain.handle("wire:select-python", async () => {
    const result = await dialog.showOpenDialog({ title: "Choose the Python interpreter for this bot", properties: ["openFile"], filters: [{ name: "Python executable", extensions: ["exe"] }] });
    return result.canceled ? null : result.filePaths[0] || null;
  });
  ipcMain.handle("wire:start-bot", async (_event, config) => {
    const scriptPath = String(config?.scriptPath || "");
    const port = Number(config?.port);
    if (!scriptPath || !fs.existsSync(scriptPath)) return { ok: false, error: "The selected Python script does not exist." };
    if (!Number.isInteger(port) || port < 47832 || port > 47999) return { ok: false, error: "Invalid local bridge port." };
    const health = await requestHealth(port);
    if (health?.connected) return { ok: true, alreadyRunning: true };
    if (health) return { ok: false, error: "A WIRE bridge is already listening on this port, but its script is not attached. Stop that session or check its Python error before starting it again." };
    const existing = runningBots.get(port);
    if (existing && !existing.killed) return { ok: true, starting: true };
    const selectedPython = String(config?.pythonPath || "");
    const python = selectedPython && fs.existsSync(selectedPython) ? selectedPython : findPython(scriptPath);
    if (!python) {
      return {
        ok: false,
        error: "WIRE could not find this bot's Python environment. Choose the matching python.exe when adding this bot, or place it in the script folder's .venv\\Scripts folder.",
      };
    }
    const bridgePath = appFile("bridge", "wire_bridge.py");
    if (!fs.existsSync(bridgePath)) return { ok: false, error: "WIRE's local bridge is missing from the installation." };
    const logPath = botLogPath(port);
    fs.mkdirSync(path.dirname(logPath), { recursive: true });
    fs.appendFileSync(logPath, "\n[WIRE] Starting " + scriptPath + " at " + new Date().toISOString() + "\n", "utf8");
    const logFd = fs.openSync(logPath, "a");
    const child = spawn(python, [bridgePath, "--run", scriptPath, "--port", String(port), "--no-browser"], {
      cwd: path.dirname(scriptPath),
      windowsHide: true,
      detached: true,
      stdio: ["ignore", logFd, logFd],
      env: { ...process.env, PYTHONUNBUFFERED: "1" },
    });
    fs.closeSync(logFd);
    child.unref();
    runningBots.set(port, child);
    const registry = readRegistry();
    registry[String(port)] = child.pid;
    writeRegistry(registry);
    child.on("exit", (code, signal) => {
      fs.appendFileSync(botLogPath(port), "\n[WIRE] Script process exited with code " + code + " and signal " + (signal || "none") + " at " + new Date().toISOString() + "\n", "utf8");
      if (runningBots.get(port) === child) runningBots.delete(port);
      const current = readRegistry();
      if (Number(current[String(port)]) === child.pid) { delete current[String(port)]; writeRegistry(current); }
    });
    child.on("error", (error) => { console.error("WIRE bot launch failed:", error.message); });
    return { ok: true, starting: true };
  });
  ipcMain.handle("wire:stop-bot", async (_event, rawPort) => {
    const port = Number(rawPort);
    const health = await requestHealth(port);
    if (!health) return { ok: false, error: "The local bridge is not responding. WIRE will not terminate a process based on a stale process ID." };
    const child = runningBots.get(port);
    const registry = readRegistry();
    const pid = child?.pid || Number(registry[String(port)]);
    if (!pid) return { ok: false, error: "WIRE has no saved process ID for this bridge, so it will not terminate an unknown trading process." };
    if (process.platform === "win32") {
      await new Promise((resolve) => execFile("taskkill", ["/PID", String(pid), "/T", "/F"], () => resolve(null)));
    } else {
      try { process.kill(-pid, "SIGTERM"); } catch { try { process.kill(pid, "SIGTERM"); } catch {} }
    }
    runningBots.delete(port);
    delete registry[String(port)];
    writeRegistry(registry);
    return { ok: true };
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
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error("The WIRE local server did not become ready. Restart the app and try again.");
}

function startLocalServer() {
  const entry = appFile(".output", "server", "index.mjs");
  if (!fs.existsSync(entry)) throw new Error("WIRE local web server is missing from the installation.");
  serverProcess = spawn(process.execPath, [entry], {
    env: { ...process.env, ELECTRON_RUN_AS_NODE: "1", HOST: "127.0.0.1", NITRO_HOST: "127.0.0.1", PORT: String(APP_PORT), NITRO_PORT: String(APP_PORT), NODE_ENV: "production" },
    stdio: "ignore",
    detached: false,
  });
}

async function createWindow() {
  await waitForLocalApp();
  const win = new BrowserWindow({
    width: 1320,
    height: 860,
    minWidth: 900,
    minHeight: 600,
    backgroundColor: "#0e1621",
    autoHideMenuBar: true,
    webPreferences: {
      preload: appFile("desktop", "electron-preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
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
app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
