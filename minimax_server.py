#!/usr/bin/env python3
"""
Fast page server for MiniMax — keeps the chat page loaded, accepts queries via HTTP.

First call: launches browser + loads page (~13s).
Subsequent calls: instant (~4-6s per query).

Usage:
  python minimax_server.py                # Start server (port 9871)
  curl -X POST http://127.0.0.1:9871/query -d '{"prompt":"Hello"}'
  python minimax_server.py --stop         # Stop server
"""

import json
import os
import signal
import sys
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from threading import Thread, Lock

MINIMAX_HOME = Path.home() / ".minimax-cli"
MINIMAX_AUTH = MINIMAX_HOME / "auth.json"
MINIMAX_URL = "https://agent.minimax.io"
PORT = 9871
PID_FILE = MINIMAX_HOME / "server.pid"

_pg = None
_ctx = None
_pw = None
_lock = Lock()
_response_ready = None  # threading.Event
_last_response = ""


def load_auth():
    if MINIMAX_AUTH.exists():
        return json.loads(MINIMAX_AUTH.read_text())
    return {}


def setup_cookies(ctx, auth):
    for n, v in auth.get("cookies", {}).items():
        d = ".minimax.io"
        if n in ("_token",): d = "agent.minimax.io"
        elif n in ("_sid", "_lf"): d = "account.minimax.io"
        ctx.add_cookies([{"name": n, "value": v, "domain": d, "path": "/",
                          "httpOnly": False, "secure": True, "sameSite": "Lax"}])


def init_browser():
    """Launch browser and load the MiniMax chat page once."""
    global _pw, _ctx, _pg

    from playwright.sync_api import sync_playwright

    auth = load_auth()
    profile_dir = str(MINIMAX_HOME / "browser-profile")

    _pw = sync_playwright().start()
    _ctx = _pw.chromium.launch_persistent_context(
        profile_dir, headless=True,
        viewport={"width": 1280, "height": 800},
        args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"])
    setup_cookies(_ctx, auth)
    _pg = _ctx.pages[0] if _ctx.pages else _ctx.new_page()

    # Block slow resources for faster page load
    try:
        def _abort(route):
            if route.request.resource_type in {"image", "font", "media"}:
                route.abort()
            else:
                route.continue_()
        _pg.route("**/*", _abort)
    except Exception: pass

    _pg.goto(MINIMAX_URL, timeout=30000)
    try: _pg.wait_for_selector('.ProseMirror', timeout=10000)
    except: time.sleep(3)

    # Dismiss modals
    for txt in ["Close", "Try it now", "Accept", "Got it"]:
        try:
            btns = _pg.locator(f'button:has-text("{txt}")')
            for i in range(btns.count()):
                try:
                    b = btns.nth(i)
                    if b.is_visible(timeout=500): b.click()
                except Exception:
                    pass
        except Exception:
            pass

    # Check auth
    editor = _pg.locator('.ProseMirror').first
    if editor.count() == 0:
        raise RuntimeError("MiniMax editor not found — auth may be expired")


def send_query(prompt: str) -> str:
    """Type prompt into already-loaded page, wait for response, return text."""
    global _pg

    editor = _pg.locator('.ProseMirror').first
    if editor.count() == 0:
        raise RuntimeError("Editor lost — page may have navigated away")

    # Focus and type
    editor.click()
    time.sleep(0.1)
    _pg.keyboard.type(prompt, delay=8)
    time.sleep(0.2)
    _pg.keyboard.press("Enter")

    # Wait for response
    prev_count = _pg.locator('.matrix-markdown.message-content').count()
    deadline = time.time() + 120
    while time.time() < deadline:
        content_els = _pg.locator('.matrix-markdown.message-content')
        loading = _pg.locator('[class*="loading"]')
        if content_els.count() > prev_count and loading.count() == 0:
            time.sleep(0.3)
            return content_els.last.inner_text().strip()
        time.sleep(0.3)

    return ""


def cleanup():
    global _ctx, _pw
    if _ctx:
        try:
            _ctx.close()
        except Exception:
            pass
    if _pw:
        try:
            _pw.stop()
        except Exception:
            pass


class QueryHandler(BaseHTTPRequestHandler):
    allow_reuse_address = True
    def do_POST(self):
        if self.path != "/query":
            self.send_error(404)
            return

        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len)
        try:
            data = json.loads(body)
            prompt = data.get("prompt", "")
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return

        if not prompt:
            self.send_error(400, "Missing prompt")
            return

        with _lock:
            try:
                text = send_query(prompt)
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "err": str(e)}).encode())
                return

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True, "text": text}).encode())

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        elif self.path == "/stop":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Stopping...")
            Thread(target=self.server.shutdown).start()
        else:
            self.send_error(404)

    def log_message(self, format, *args):
        pass  # Suppress HTTP logs


def run_server():
    global _pg, _ctx, _pw

    # Write PID
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))

    # Ensure clean shutdown
    def on_exit(*args):
        cleanup()
        PID_FILE.unlink(missing_ok=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, on_exit)
    signal.signal(signal.SIGINT, on_exit)

    try:
        init_browser()
    except Exception as e:
        print(f"Failed to init browser: {e}", file=sys.stderr)
        PID_FILE.unlink(missing_ok=True)
        sys.exit(1)

    server = HTTPServer(("127.0.0.1", PORT), QueryHandler)
    print(f"MiniMax server ready on :{PORT}", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        cleanup()
        PID_FILE.unlink(missing_ok=True)


def stop_server():
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, signal.SIGTERM)
            PID_FILE.unlink(missing_ok=True)
            print(f"Stopped (PID={pid})")
            return
        except (ProcessLookupError, ValueError):
            PID_FILE.unlink(missing_ok=True)
    print("No server running")


def query(prompt: str) -> dict:
    """Send query to running server. Returns {"ok": True, "text": "..."}."""
    import urllib.request

    data = json.dumps({"prompt": prompt}).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/query",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"ok": False, "err": str(e)}


def ensure_server():
    """Ensure server is running. Returns True if ready."""
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, 0)
            # Health check
            import urllib.request
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2) as r:
                    if r.status == 200:
                        return True
            except Exception:
                pass
        except (ProcessLookupError, ValueError):
            PID_FILE.unlink(missing_ok=True)
    return False


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--stop":
        stop_server()
        return
    if len(sys.argv) > 1 and sys.argv[1] == "--status":
        if ensure_server():
            print("Server running")
        else:
            print("Server not running")
        return
    if len(sys.argv) > 1 and sys.argv[1] == "--query":
        prompt = sys.argv[2] if len(sys.argv) > 2 else sys.stdin.read().strip()
        if ensure_server():
            result = query(prompt)
            print(json.dumps(result, ensure_ascii=False))
        else:
            print(json.dumps({"ok": False, "err": "server not running"}, ensure_ascii=False))
            sys.exit(1)
        return

    run_server()


if __name__ == "__main__":
    main()
