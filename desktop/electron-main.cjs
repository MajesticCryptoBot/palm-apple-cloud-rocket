const { app, BrowserWindow, dialog, ipcMain } = require("electron");
const { fork, spawn, execFile } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const http = require("node:http");
const os = require("node:os");

const APP_PORT = 47831;
const runningBots = new Map();
let serverProcess;

function appFile(...parts) {
  if (app.isPackaged) {
    if (parts[0] === "bridge") return path.join(process.resourcesPath, ...parts);
    return path.join(app.getAppPath(), ...parts);
  }
  if (parts[0] === "bridge") return path.join(__dirname, parts[1]);
  if (parts[0] === "desktop") return path.join(__dirname, ...parts.slice(1));
  return path.join(__dirname, "..", ...parts);
}

function getDefaultScriptPath() {
  const home = os.homedir();
  const candidates = [
    path.join(home, "Desktop", "IG", "ABinanceTradingBot.py"),
    "C:\\Users\\pauld\\Desktop\\IG\\ABinanceTradingBot.py",
  ];
  return candidates.find((p) => fs.existsSync(p)) || null;
}

function findPython(scriptPath) {
  const dir = path.dirname(scriptPath);
  const candidates = [
    path.join(dir, ".venv", "Scripts", "python.exe"),
    path.join(dir, "venv", "Scripts", "python.exe"),
    path.join(path.dirname(dir), ".venv", "Scripts", "python.exe"),
    path.join(os.homedir(), "Desktop", "IG", ".venv", "Scripts", "python.exe"),
  ];
  return candidates.find((p) => fs.existsSync(p)) || null;
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
  ipcMain.handle("wire:default-script", () => getDefaultScriptPath());
  ipcMain.handle("wire:start-bot", async (_event, config) => {
    const scriptPath = String(config?.scriptPath || "");
    const port = Number(config?.port);
    if (!scriptPath || !fs.existsSync(scriptPath)) return { ok: false, error: "The selected Python script does not exist." };
    if (!Number.isInteger(port) || port < 47832 || port > 47999) return { ok: false, error: "Invalid local bridge port." };
    const health = await requestHealth(port);
    if (health?.connected) return { ok: true, alreadyRunning: true };
    const existing = runningBots.get(port);
    if (existing && !existing.killed) return { ok: true, starting: true };
    const python = findPython(scriptPath);
    if (!python) {
      return {
        ok: false,
        error: "WIRE could not find this bot's Python virtual environment. Place its python.exe in the script folder's .venv\\Scripts folder, or configure the interpreter in a future WIRE settings update.",
      };
    }
    const bridgePath = appFile("bridge", "wire_bridge.py");
    if (!fs.existsSync(bridgePath)) return { ok: false, error: "WIRE's local bridge is missing from the installation." };
    const child = spawn(python, [bridgePath, "--run", scriptPath, "--port", String(port), "--no-browser"], {
      cwd: path.dirname(scriptPath),
      windowsHide: true,
      detached: true,
      stdio: "ignore",
      env: { ...process.env, PYTHONUNBUFFERED: "1" },
    });
    child.unref();
    runningBots.set(port, child);
    child.on("exit", () => { if (runningBots.get(port) === child) runningBots.delete(port); });
    child.on("error", (error) => { console.error("WIRE bot launch failed:", error.message); });
    return { ok: true, starting: true };
  });
  ipcMain.handle("wire:stop-bot", async (_event, rawPort) => {
    const port = Number(rawPort);
    const child = runningBots.get(port);
    if (!child?.pid) return { ok: false, error: "This WIRE session did not start the process, so it will not terminate an unknown trading process." };
    if (process.platform === "win32") {
      await new Promise((resolve) => execFile("taskkill", ["/PID", String(child.pid), "/T", "/F"], () => resolve(null)));
    } else {
      try { process.kill(-child.pid, "SIGTERM"); } catch { try { child.kill("SIGTERM"); } catch {} }
    }
    runningBots.delete(port);
    return { ok: true };
  });
}

function startLocalServer() {
  const entry = appFile(".output", "server", "index.mjs");
  if (!fs.existsSync(entry)) throw new Error("WIRE local web server is missing from the installation.");
  serverProcess = fork(entry, [], {
    execPath: process.execPath,
    env: { ...process.env, ELECTRON_RUN_AS_NODE: "1", HOST: "127.0.0.1", PORT: String(APP_PORT), NODE_ENV: "production" },
    stdio: "ignore",
    detached: false,
  });
}

async function createWindow() {
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
