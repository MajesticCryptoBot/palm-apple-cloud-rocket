"""Wire bridge. Local Telegram replacement for the trading script.

Run the bot through this process so every command and every automatic
message (patterns, fills, trailing stops, rescues, Isaac) hits the desk:

    py -3 wire_bridge.py --run C:\\path\\to\\ABinanceTradingBot.py

Or double-click Wire.bat and pass the script path.
The desk is http://127.0.0.1:47832/ and the same port serves /command /live /health.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "127.0.0.1"
PORT = 47832
NO_BROWSER = False


class Bridge:
    def __init__(self) -> None:
        self.live: list[dict] = []
        self.seq = 0
        self.app = None
        self.loop = None
        self.user_id = 0
        self.state_mod = None
        self.connected = False
        self._cmd_replies: list[str] | None = None
        self._lock = threading.Lock()
        self._cmd_lock = threading.Lock()
        self._update_id = 1
        self.httpd: ThreadingHTTPServer | None = None

    def publish(self, text: str) -> None:
        text = str(text or "").strip()
        if not text:
            return
        with self._lock:
            if self._cmd_replies is not None:
                self._cmd_replies.append(text)
                return
            self.seq += 1
            self.live.append({"seq": self.seq, "text": text, "ts": time.time()})
            if len(self.live) > 400:
                self.live = self.live[-400:]

    def since(self, after: int) -> tuple[int, list[dict]]:
        with self._lock:
            items = [item for item in self.live if item["seq"] > after]
            if after <= 0:
                items = items[-40:]
            return self.seq, items

    def attach(self, application) -> None:
        self.app = application
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            self.loop = None
        self.connected = True
        for mod in list(sys.modules.values()):
            raw = getattr(mod, "TELEGRAM_USER_ID", None)
            if raw:
                try:
                    self.user_id = int(raw)
                except (TypeError, ValueError):
                    pass
            if hasattr(mod, "SYMBOL") and hasattr(mod, "SYMBOL2"):
                self.state_mod = mod
        self.publish("Wire attached. This script is live in the desk.")

    def snapshot(self) -> dict:
        mod = self.state_mod
        if mod is None:
            for candidate in list(sys.modules.values()):
                if hasattr(candidate, "SYMBOL") and hasattr(candidate, "SYMBOL2"):
                    mod = candidate
                    self.state_mod = candidate
                    break
        return {
            "ok": True,
            "activePair": getattr(mod, "SYMBOL", None) if mod else None,
            "activePairUSDC": getattr(mod, "SYMBOL2", None) if mod else None,
            "isaacPair": getattr(mod, "ISAAC_DCA_SYMBOL", None) if mod else None,
            "connected": self.connected and self.app is not None,
        }

    async def deliver(self, text: str) -> list[str]:
        if self.app is None or self.loop is None:
            return ["The trading script is not attached. Start it with: py -3 wire_bridge.py --run ABinanceTradingBot.py"]
        caught: list[str] = []
        with self._lock:
            self._cmd_replies = caught
        try:
            update = self._update(text)
            await self.app.process_update(update)
        except Exception as exc:
            caught.append(f"Command failed: {exc}")
        finally:
            with self._lock:
                self._cmd_replies = None
        return caught or ["Command accepted. The script sent no reply text."]

    def _update(self, text: str):
        from datetime import datetime, timezone

        from telegram import Chat, Message, Update, User

        self._update_id += 1
        uid = self.user_id or 1
        user = User(id=uid, is_bot=False, first_name="Wire")
        chat = Chat(id=uid, type=Chat.PRIVATE)
        message = Message(
            message_id=self._update_id,
            date=datetime.now(timezone.utc),
            chat=chat,
            from_user=user,
            text=text,
        )
        message.set_bot(self.app.bot)
        return Update(update_id=self._update_id, message=message)

    def ask(self, text: str, timeout: float = 40) -> tuple[bool, list[str]]:
        if self.app is None or self.loop is None:
            return False, ["The trading script is not attached. Start it with wire_bridge.py --run."]
        with self._cmd_lock:
            future = asyncio.run_coroutine_threadsafe(self.deliver(text), self.loop)
            try:
                return True, future.result(timeout=timeout)
            except Exception as exc:
                return False, [f"Command failed: {exc}"]

    def start(self) -> None:
        if self.httpd is not None:
            return
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args) -> None:
                return

            def _cors(self) -> None:
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Private-Network", "true")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")

            def _json(self, code: int, payload: dict) -> None:
                raw = json.dumps(payload).encode("utf-8")
                self.send_response(code)
                self._cors()
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(raw)

            def do_OPTIONS(self) -> None:
                self.send_response(204)
                self._cors()
                self.end_headers()

            def do_GET(self) -> None:
                path = self.path.split("?", 1)[0]
                if path == "/health":
                    self._json(200, {"ok": True, "connected": bridge.connected and bridge.app is not None})
                    return
                if path == "/snapshot":
                    self._json(200, bridge.snapshot())
                    return
                if path == "/live":
                    after = 0
                    if "?" in self.path:
                        for part in self.path.split("?", 1)[1].split("&"):
                            if part.startswith("after="):
                                try:
                                    after = int(part.split("=", 1)[1])
                                except ValueError:
                                    after = 0
                    latest, items = bridge.since(after)
                    self._json(200, {"ok": True, "latest": latest, "items": items})
                    return
                self._json(404, {"ok": False, "error": "Not found"})

            def do_POST(self) -> None:
                path = self.path.split("?", 1)[0]
                if path != "/command":
                    self._json(404, {"ok": False, "error": "Not found"})
                    return
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    body = json.loads(raw.decode("utf-8") or "{}")
                except json.JSONDecodeError:
                    self._json(400, {"ok": False, "blocked": True, "replies": ["Command body was not JSON."]})
                    return
                text = str(body.get("text") or "").strip()
                if not text:
                    self._json(400, {"ok": False, "blocked": True, "replies": ["Empty command."]})
                    return
                ok, replies = bridge.ask(text)
                self._json(200 if ok else 503, {"ok": ok, "blocked": not ok, "replies": replies})

        self.httpd = ThreadingHTTPServer((HOST, PORT), Handler)
        thread = threading.Thread(target=self.httpd.serve_forever, name="wire-bridge", daemon=True)
        thread.start()


BRIDGE = Bridge()


def install_patches() -> None:
    from telegram import Bot
    from telegram.ext import Application

    if not getattr(Application.start, "_wire", False):
        orig_start = Application.start

        async def start(self, *args, **kwargs):
            result = await orig_start(self, *args, **kwargs)
            BRIDGE.attach(self)
            return result

        start._wire = True  # type: ignore[attr-defined]
        Application.start = start  # type: ignore[method-assign]

    if not getattr(Bot.send_message, "_wire", False):
        orig_send = Bot.send_message

        async def send_message(self, *args, **kwargs):
            text = kwargs.get("text", args[1] if len(args) > 1 else "")
            BRIDGE.publish("" if text is None else str(text))
            return await orig_send(self, *args, **kwargs)

        send_message._wire = True  # type: ignore[attr-defined]
        Bot.send_message = send_message  # type: ignore[method-assign]


def launch_browser() -> None:
    webbrowser.open(f"http://{HOST}:{PORT}/")


def run_script(path: str) -> None:
    import runpy

    script = os.path.abspath(path)
    if not os.path.isfile(script):
        raise SystemExit(f"Script not found: {script}")
    os.chdir(os.path.dirname(script))
    sys.path.insert(0, os.getcwd())
    BRIDGE.start()
    try:
        install_patches()
    except Exception as exc:
        BRIDGE.publish(f"Could not patch Telegram: {exc}")
    print(f"Wire listening on http://{HOST}:{PORT}/")
    print(f"Running {script}")
    if not NO_BROWSER:
        launch_browser()
    runpy.run_path(script, run_name="__main__")


def selftest() -> None:
    BRIDGE.start()
    BRIDGE.publish("PATTERN 6: EMA Momentum Alignment (Elite)\nBuy Order Filled and Targets Set")
    BRIDGE.publish("TRAILING-STOP SELL\nETH/USDT\nSold 1.420000 ETH @ 3310.12")
    import urllib.error
    import urllib.request

    with urllib.request.urlopen(f"http://{HOST}:{PORT}/health") as response:
        health = json.loads(response.read().decode())
    with urllib.request.urlopen(f"http://{HOST}:{PORT}/live?after=0") as response:
        live = json.loads(response.read().decode())
    request = urllib.request.Request(
        f"http://{HOST}:{PORT}/command",
        data=json.dumps({"text": "/status"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request) as response:
            command = json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        command = json.loads(error.read().decode())
    assert health["ok"] is True and health["connected"] is False
    assert len(live["items"]) == 2
    assert command["blocked"] is True
    assert "not attached" in command["replies"][0]
    print("wire bridge selftest ok")


def main() -> None:
    global PORT, NO_BROWSER
    args = sys.argv[1:]
    if "--port" in args:
        index = args.index("--port")
        if index + 1 >= len(args):
            raise SystemExit("Usage: --port 47832")
        try:
            PORT = int(args[index + 1])
        except ValueError as exc:
            raise SystemExit("--port must be an integer") from exc
        if not 1024 <= PORT <= 65535:
            raise SystemExit("--port must be between 1024 and 65535")
    NO_BROWSER = "--no-browser" in args
    if "--selftest" in args:
        selftest()
        return
    if "--run" in args:
        index = args.index("--run")
        if index + 1 >= len(args):
            raise SystemExit("Usage: wire_bridge.py --run path\\to\\ABinanceTradingBot.py")
        try:
            run_script(args[index + 1])
        except Exception:
            traceback.print_exc()
            raise
        return
    BRIDGE.start()
    print(f"Wire listening on http://{HOST}:{PORT}/")
    print("Start the bot with: py -3 wire_bridge.py --run ABinanceTradingBot.py")
    if not NO_BROWSER and ("--desktop" in args or not args):
        launch_browser()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
