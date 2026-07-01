"""Local web server for SPARK: LANES (stdlib only)."""

import json
import os
import random
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .lanes import LaneGame, levels_meta, pool_meta

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")

GAME = LaneGame(random.Random())


def _state():
    return GAME.state() if GAME.turn else {"started": False}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj))

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html", "/lanes.html"):
            try:
                with open(os.path.join(WEB_DIR, "lanes.html"), "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            except FileNotFoundError:
                self._send(404, "lanes.html missing", "text/plain")
        elif path == "/api/state":
            self._json(_state())
        elif path == "/api/levels":
            self._json(levels_meta())
        elif path == "/api/pool":
            self._json(pool_meta())
        elif path.startswith("/cards/"):
            from urllib.parse import unquote
            name = os.path.basename(unquote(path))   # decode %20 etc.; block traversal
            fp = os.path.join(REPO_ROOT, "cards", name)
            if os.path.isfile(fp):
                ext = os.path.splitext(name)[1].lower()
                ctype = {".webp": "image/webp", ".jpg": "image/jpeg",
                         ".jpeg": "image/jpeg", ".png": "image/png"}.get(
                             ext, "application/octet-stream")
                with open(fp, "rb") as f:
                    self._send(200, f.read(), ctype)
            else:
                self._send(404, "no card", "text/plain")
        elif path.startswith("/sfx/") or path.startswith("/music/"):
            from urllib.parse import unquote
            folder = "sfx" if path.startswith("/sfx/") else "music"
            name = os.path.basename(unquote(path))   # decode %20 etc.; block traversal
            fp = os.path.join(REPO_ROOT, folder, name)
            if os.path.isfile(fp):
                ext = os.path.splitext(name)[1].lower()
                ctype = {".mp3": "audio/mpeg", ".ogg": "audio/ogg",
                         ".wav": "audio/wav", ".m4a": "audio/mp4"}.get(
                             ext, "application/octet-stream")
                with open(fp, "rb") as f:
                    self._send(200, f.read(), ctype)
            else:
                self._send(404, "no audio", "text/plain")
        else:
            self._send(404, "not found", "text/plain")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            body = {}
        path = self.path.split("?")[0]
        try:
            if path == "/api/new":
                self._json(GAME.new_game(body.get("level", 0), body.get("deck")))
            elif path == "/api/stage":
                self._json(GAME.stage(body.get("index"), body.get("lane")))
            elif path == "/api/reset":
                self._json(GAME.reset_turn())
            elif path == "/api/end":
                self._json(GAME.end_turn())
            else:
                self._send(404, "not found", "text/plain")
        except Exception as e:
            st = _state()
            st["error"] = f"server error: {e}"
            self._json(st, 200)


def serve(host="127.0.0.1", port=8000, open_browser=True):
    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}"
    print(f"SPARK: LANES running at {url}   (Ctrl-C to stop)", flush=True)
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
        httpd.server_close()


if __name__ == "__main__":
    serve()
