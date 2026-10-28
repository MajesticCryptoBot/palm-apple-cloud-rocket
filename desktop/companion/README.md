# WIRE Companion Relay v2

The cloud bridge for **WIRE 1.0.9 Companion** — a free, zero-database relay that connects
the WIRE desktop app (Windows) with the WIRE Companion web app on your iPhone.

**New in v2 — the phone is no longer read-only.** You can now send commands from the
iPhone: they run on the PC exactly as if you typed them at the desk. BotMother, pinning,
profile photos and themes all work from the phone too.

```
PC (WIRE 1.0.9)  ──WebSocket──▶  Relay (this folder, on Render.com)  ──WebSocket──▶  iPhone (Safari / PWA)
```

- **One deployment serves everything**: the web app (static files), the WebSocket relay (`/ws`)
  and a health check (`/health`) on a single port.
- **Pairing**: PC and phone join with the same pairing key (WIRE Settings → Companion sync).
  No accounts, no database, nothing stored.
- **Live output**: every bot message streams to the phone in real time; a 250-message ring
  buffer per bot replays instantly when the phone opens (or reconnects).

## Quick start (detailed, beginner-friendly)

Open **[START-HERE.txt](./START-HERE.txt)** — it walks through every click:
GitHub upload → Render deploy → paste URL in WIRE → copy iPhone link → Add to Home Screen.

Short version:

1. Upload the contents of this folder to a **private GitHub repo**.
2. Render.com → New + → Web Service → connect the repo → **Free** plan → Deploy.
3. Copy your service URL (`https://<name>.onrender.com`).
4. WIRE → Settings → Companion sync → paste URL → Test → Generate key → Enable →
   **Copy iPhone link**.
5. Open the link on the iPhone in Safari → Share → **Add to Home Screen**. Done.

## Protocol (v2)

Roles: `publisher` (the PC, one per room) and `viewer` (phones).

| Direction | Message | Purpose |
|---|---|---|
| both | `{type:"hello", role, key, name}` | join a room (pairing key = room id) |
| pub→srv | `{type:"session", bots:[{id,name,exchange,online,photo?,pins?,commands?}]}` | full bot list + meta (photos, pins, commands) |
| pub→srv | `{type:"backlog", botId, messages}` | seed the ring buffer (≤200) |
| pub→srv | `{type:"message", botId, message}` | live message (may carry `buttons`) |
| pub→srv | `{type:"presence", botId, online}` | bot online/offline |
| view→srv | `{type:"input", botId, text}` | **send a command into a chat** → forwarded to the PC |
| view→srv | `{type:"ctrl", action:"togglePin", botId, msgId}` | **pin/unpin** → forwarded to the PC |
| srv→all | `session / backlog / message / presence / viewers` | fan-out to phones |
| srv→pub | `{type:"input"…}`, `{type:"ctrl"…}` | remote control from a phone |

Safety rails: rate limiting (240 msg/10 s publishers, 30/10 s viewers), payload caps
(photos ≤160 KB, text ≤8 KB, input ≤2 KB), room size 24, rooms 500, publisher
replace-on-reconnect, heartbeat sweep, second-publisher takeover (`close 4000`).

The PC applies remote input through the exact same store path as local typing
(`sendTo(botId, text, "phone")`) — **bot workflows are never touched**.

## Run locally

```bash
npm install
npm start          # http://localhost:8787  (PWA at / · ws at /ws · health at /health)
```

Environment: `PORT` (default 8787).

## Deploy on Render (free)

This folder ships with `render.yaml` — Render Blueprint, free instance type,
health check path `/health`. In Render: **New + → Blueprint** and point it at your
repo, or follow START-HERE.txt for the manual Web Service flow.

> Free instances sleep after 15 minutes without traffic. Any WIRE connection with
> Companion sync enabled keeps the relay awake; the first request after a nap needs
> ~30–60 s to wake it.

## iPhone requirements

iOS 15+ (tested against an iPhone 7 on iOS 15.8). No App Store, no Apple account,
no cost — it is a PWA installed via Safari → Add to Home Screen. Works on Wi-Fi and
mobile data, anywhere in the world, as long as the PC is running WIRE.
