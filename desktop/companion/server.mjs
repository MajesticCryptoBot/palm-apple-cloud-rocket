/**
 * WIRE Companion Relay v2 — cloud bridge between the WIRE desktop app
 * (publisher) and the WIRE Companion web app on iPhone (viewers).
 *
 * One deployment serves everything:
 *   - HTTPS static files  → the Companion web app (public/)
 *   - WebSocket at /ws    → pairing + live stream + remote control
 *
 * v2: viewers are no longer read-only. The phone can send commands
 * (`input`) and pin/unpin messages (`ctrl`); the desktop executes them
 * through the exact same code path as local typing. Sessions now carry
 * bot meta (profile photo, pinned ids, command list).
 *
 * Pairing: the desktop app and the phone join with the same pairing key
 * (generated in WIRE Settings → Companion sync). No accounts, no database.
 */

import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";
import { WebSocketServer } from "ws";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC_DIR = path.join(__dirname, "public");
const PORT = Number(process.env.PORT || process.env.RELAY_PORT || 8787);

// ---------------------------------------------------------------- limits --
const MAX_KEY_LEN = 64;
const MAX_BOTS = 24;
const MAX_TEXT = 8000;
const MAX_INPUT_TEXT = 2000;
const MAX_PHOTO = 160_000; // chars of data URL per bot
const MAX_BUTTONS = 8;
const MAX_BUFFER_PER_BOT = 250;
const MAX_BACKLOG_SUBMIT = 200;
const MAX_SOCKETS_PER_ROOM = 24;
const MAX_ROOMS = 500;
const RATE_WINDOW = 10_000;
const RATE_MAX = 240;          // publisher frames
const VIEWER_RATE_MAX = 30;    // viewer frames (input/ctrl flood guard)

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".webmanifest": "application/manifest+json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".ttf": "font/ttf",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".txt": "text/plain; charset=utf-8",
};

// ----------------------------------------------------------------- rooms --
/** room key (normalized) -> room state */
const rooms = new Map();

function normalizeKey(raw) {
  const key = String(raw || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
  if (key.length < 6 || key.length > MAX_KEY_LEN) return null;
  return key;
}

function getRoom(key) {
  let room = rooms.get(key);
  if (!room) {
    if (rooms.size >= MAX_ROOMS) return null;
    room = { key, publishers: new Set(), viewers: new Set(), bots: new Map() };
    rooms.set(key, room);
  }
  return room;
}

/** Drop rooms with nobody connected (the desktop refreshes backlog on reconnect). */
function sweepRoom(room) {
  if (room.publishers.size === 0 && room.viewers.size === 0) rooms.delete(room.key);
}

function roomSnapshot(room) {
  return [...room.bots.values()].map((b) => ({
    id: b.id,
    name: b.name,
    exchange: b.exchange,
    online: b.online,
    photo: b.photo || undefined,
    pins: b.pins && b.pins.length ? b.pins : undefined,
    commands: b.commands && b.commands.length ? b.commands : undefined,
  }));
}

function bufferedMessages(room, botId) {
  const bot = room.bots.get(botId);
  return bot ? bot.messages.slice(-MAX_BUFFER_PER_BOT) : [];
}

function send(socket, payload) {
  if (socket.readyState === socket.OPEN) {
    try { socket.send(JSON.stringify(payload)); } catch { /* socket died mid-send */ }
  }
}

function newRateWin() {
  return { start: Date.now(), count: 0 };
}

function checkRate(socket, max) {
  let win = socket._rateWin;
  const now = Date.now();
  if (!win || now - win.start > RATE_WINDOW) { win = newRateWin(); socket._rateWin = win; }
  win.count += 1;
  return win.count <= max;
}

// ------------------------------------------------------------------ ws ----
const wss = new WebSocketServer({ noServer: true, maxPayload: 4 * 1024 * 1024 });

wss.on("connection", (socket) => {
  socket.isAlive = true;
  socket.role = null;
  socket.room = null;
  socket.on("pong", () => { socket.isAlive = true; });

  socket.on("message", (data) => {
    let msg;
    try { msg = JSON.parse(String(data)); } catch { return; }
    if (!msg || typeof msg.type !== "string") return;

    // ---- handshake -------------------------------------------------------
    if (msg.type === "hello") {
      const key = normalizeKey(msg.key);
      if (!key) { send(socket, { type: "error", error: "invalid-key" }); socket.close(); return; }
      const room = getRoom(key);
      if (!room) { send(socket, { type: "error", error: "relay-full" }); socket.close(); return; }
      const role = msg.role === "publisher" ? "publisher" : "viewer";
      const bucket = role === "publisher" ? room.publishers : room.viewers;
      if (bucket.size >= MAX_SOCKETS_PER_ROOM) { send(socket, { type: "error", error: "room-full" }); socket.close(); return; }
      socket.role = role;
      socket.room = room;
      socket._rateWin = newRateWin();
      bucket.add(socket);
      // A second publisher replaces the stale one (e.g. the PC restarted).
      if (role === "publisher" && room.publishers.size > 1) {
        for (const old of room.publishers) {
          if (old !== socket) {
            try { old.close(4000, "replaced"); } catch { /* */ }
            room.publishers.delete(old);
          }
        }
      }
      send(socket, { type: "welcome", role, key: room.key, viewers: role === "publisher" ? room.viewers.size : undefined });

      if (role === "publisher") {
        broadcastViewers(room, { type: "session", bots: roomSnapshot(room) });
        send(socket, { type: "viewers", count: room.viewers.size });
      } else {
        // Phone just opened: replay the live picture instantly.
        send(socket, { type: "session", bots: roomSnapshot(room) });
        for (const bot of room.bots.values()) {
          const messages = bufferedMessages(room, bot.id);
          if (messages.length) send(socket, { type: "backlog", botId: bot.id, botName: bot.name, messages });
        }
        for (const pub of room.publishers) send(pub, { type: "viewers", count: room.viewers.size });
      }
      return;
    }

    if (!socket.room) return;
    const room = socket.room;

    // ---- viewer remote control -------------------------------------------
    if (socket.role === "viewer") {
      if (!checkRate(socket, VIEWER_RATE_MAX)) return;
      if (msg.type === "input") {
        const botId = String(msg.botId || "").slice(0, 80);
        const text = String(msg.text || "").slice(0, MAX_INPUT_TEXT).trim();
        if (!botId || !text || !room.bots.has(botId)) return;
        for (const pub of room.publishers) send(pub, { type: "input", botId, text });
        return;
      }
      if (msg.type === "ctrl") {
        const botId = String(msg.botId || "").slice(0, 80);
        const action = String(msg.action || "").slice(0, 32);
        const msgId = String(msg.msgId || "").slice(0, 80);
        if (!botId || !room.bots.has(botId)) return;
        for (const pub of room.publishers) send(pub, { type: "ctrl", action, botId, msgId });
        return;
      }
      return;
    }

    // ---- publisher traffic ------------------------------------------------
    if (socket.role !== "publisher") return;
    if (!checkRate(socket, RATE_MAX)) return;

    if (msg.type === "session") {
      if (!Array.isArray(msg.bots)) return;
      const seen = new Set();
      for (const raw of msg.bots.slice(0, MAX_BOTS)) {
        if (!raw || typeof raw.id !== "string") continue;
        const id = raw.id.slice(0, 80);
        seen.add(id);
        const existing = room.bots.get(id);
        const photo = typeof raw.photo === "string" ? raw.photo.slice(0, MAX_PHOTO) : undefined;
        const pins = Array.isArray(raw.pins) ? raw.pins.slice(0, 20).map((p) => String(p).slice(0, 80)) : undefined;
        const commands = Array.isArray(raw.commands)
          ? raw.commands.slice(0, 100).map((c) => ({ name: String(c?.name || "").slice(0, 60), hint: String(c?.hint || "").slice(0, 140) })).filter((c) => c.name)
          : undefined;
        if (existing) {
          existing.name = String(raw.name || existing.name).slice(0, 80);
          existing.exchange = String(raw.exchange || existing.exchange).slice(0, 80);
          existing.online = Boolean(raw.online);
          if (photo !== undefined) existing.photo = photo || undefined;
          if (pins !== undefined) existing.pins = pins;
          if (commands !== undefined) existing.commands = commands;
        } else {
          room.bots.set(id, {
            id,
            name: String(raw.name || "Bot").slice(0, 80),
            exchange: String(raw.exchange || "").slice(0, 80),
            online: Boolean(raw.online),
            messages: [],
            photo: photo || undefined,
            pins: pins || [],
            commands: commands || [],
          });
        }
      }
      for (const id of [...room.bots.keys()]) if (!seen.has(id)) room.bots.delete(id);
      broadcastViewers(room, { type: "session", bots: roomSnapshot(room) });
      return;
    }

    if (msg.type === "backlog") {
      const bot = room.bots.get(String(msg.botId || "").slice(0, 80));
      if (!bot || !Array.isArray(msg.messages)) return;
      bot.messages = msg.messages
        .slice(-MAX_BACKLOG_SUBMIT)
        .filter((m) => m && typeof m.text === "string")
        .map(sanitizeMessage)
        .slice(-MAX_BUFFER_PER_BOT);
      return;
    }

    if (msg.type === "message") {
      const bot = room.bots.get(String(msg.botId || "").slice(0, 80));
      const text = typeof msg.message?.text === "string" ? msg.message.text : "";
      if (!bot || !text) return;
      const clean = sanitizeMessage(msg.message);
      bot.messages.push(clean);
      if (bot.messages.length > MAX_BUFFER_PER_BOT) bot.messages.splice(0, bot.messages.length - MAX_BUFFER_PER_BOT);
      broadcastViewers(room, { type: "message", botId: bot.id, botName: bot.name, message: clean });
      return;
    }

    if (msg.type === "presence") {
      const bot = room.bots.get(String(msg.botId || "").slice(0, 80));
      if (!bot) return;
      bot.online = Boolean(msg.online);
      broadcastViewers(room, { type: "presence", botId: bot.id, online: bot.online });
      return;
    }
  });

  socket.on("close", () => {
    const room = socket.room;
    if (!room) return;
    (socket.role === "publisher" ? room.publishers : room.viewers).delete(socket);
    if (socket.role === "publisher" && room.publishers.size === 0) {
      for (const bot of room.bots.values()) bot.online = false;
      broadcastViewers(room, { type: "session", bots: roomSnapshot(room) });
    }
    if (socket.role === "viewer") for (const pub of room.publishers) send(pub, { type: "viewers", count: room.viewers.size });
    sweepRoom(room);
  });
  socket.on("error", () => { try { socket.close(); } catch { /* already gone */ } });
});

function sanitizeMessage(m) {
  let buttons;
  if (Array.isArray(m.buttons)) {
    buttons = m.buttons.slice(0, MAX_BUTTONS).map((b) => ({
      label: String(b?.label || "").slice(0, 64),
      command: String(b?.command || "").slice(0, 120),
    })).filter((b) => b.label && b.command);
    if (!buttons.length) buttons = undefined;
  }
  return {
    id: String(m.id || crypto.randomUUID()).slice(0, 80),
    from: m.from === "me" ? "me" : "bot",
    text: String(m.text || "").slice(0, MAX_TEXT),
    ts: Number.isFinite(m.ts) ? m.ts : Date.now(),
    tone: ["normal", "trade", "alert"].includes(m.tone) ? m.tone : "normal",
    mono: Boolean(m.mono),
    buttons,
    via: m.via === "phone" ? "phone" : undefined,
  };
}

function broadcastViewers(room, payload) {
  for (const v of room.viewers) send(v, payload);
}

// Heartbeat — drop dead sockets (mobile networks love half-open connections).
const heartbeat = setInterval(() => {
  for (const socket of wss.clients) {
    if (!socket.isAlive) { try { socket.terminate(); } catch { /* */ } continue; }
    socket.isAlive = false;
    try { socket.ping(); } catch { /* */ }
  }
  for (const room of [...rooms.values()]) sweepRoom(room);
}, 25_000);
heartbeat.unref();

// --------------------------------------------------------------- static ---
function serveStatic(req, res) {
  const url = new URL(req.url, "http://localhost");
  let pathname = decodeURIComponent(url.pathname);
  if (pathname === "/") pathname = "/index.html";
  if (pathname === "/health") {
    res.writeHead(200, { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" });
    res.end("ok");
    return;
  }
  const resolved = path.normalize(path.join(PUBLIC_DIR, pathname));
  if (!resolved.startsWith(PUBLIC_DIR)) { res.writeHead(403); res.end(); return; }
  fs.readFile(resolved, (error, body) => {
    if (error) {
      // SPA fallback → the pairing screen inside index.html.
      fs.readFile(path.join(PUBLIC_DIR, "index.html"), (err2, html) => {
        if (err2) { res.writeHead(404); res.end("Not found"); return; }
        res.writeHead(200, { "content-type": MIME[".html"], "cache-control": "no-store" });
        res.end(html);
      });
      return;
    }
    const ext = path.extname(resolved).toLowerCase();
    const immutable = pathname.startsWith("/assets/") || pathname.startsWith("/icons/");
    res.writeHead(200, {
      "content-type": MIME[ext] || "application/octet-stream",
      "cache-control": immutable ? "public, max-age=604800" : ext === ".html" ? "no-store" : "public, max-age=3600",
    });
    res.end(body);
  });
}

const server = http.createServer(serveStatic);
server.on("upgrade", (req, socket, head) => {
  const url = new URL(req.url, "http://localhost");
  if (url.pathname !== "/ws") { socket.destroy(); return; }
  wss.handleUpgrade(req, socket, head, (ws) => wss.emit("connection", ws, req));
});

server.listen(PORT, () => {
  console.log(`[wire-companion-relay] v2 listening on port ${PORT} — app at / · WebSocket at /ws`);
});
