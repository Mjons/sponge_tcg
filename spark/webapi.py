"""Stateless HTTP handler for SPARK: LANES, shared by the Vercel functions.

Vercel runs each request in a fresh, stateless serverless function, so there
is no long-lived in-memory game (unlike ``lane_server.py`` used for local
play). Instead the client holds the whole game as an opaque ``game`` token and
sends it back on every request; we rebuild the game, apply one action, and
return the new token embedded in the state as ``_game``.

Each ``api/<endpoint>.py`` file is a tiny shim that calls ``make_handler``.
"""

import json
import random

from .lanes import LaneGame, levels_meta, pool_meta


def dispatch(endpoint, method, body):
    """Compute the JSON response for one request. Pure: no global state."""
    if method == "GET":
        if endpoint == "levels":
            return levels_meta()
        if endpoint == "pool":
            return pool_meta()
        if endpoint == "state":
            # No server-side session; a fresh client starts at level select.
            return {"started": False}
        return {"error": "not found"}

    # POST — a game-mutating action.
    if endpoint == "new":
        g = LaneGame(random.Random())
        st = g.new_game(body.get("level", 0), body.get("deck"))
    else:
        data = body.get("game")
        if not data:
            return {"error": "no game state; start a new game first"}
        g = LaneGame.from_serialized(data)
        if endpoint == "stage":
            st = g.stage(body.get("index"), body.get("lane"))
        elif endpoint == "reset":
            st = g.reset_turn()
        elif endpoint == "end":
            st = g.end_turn()
        else:
            return {"error": "not found"}

    st["_game"] = g.serialize()      # opaque token the client returns next time
    return st


def make_handler(endpoint):
    """Build a BaseHTTPRequestHandler subclass bound to one endpoint.

    Vercel's Python runtime imports ``handler`` from each api/*.py file.
    """
    from http.server import BaseHTTPRequestHandler

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, obj, code=200):
            data = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            try:
                self._json(dispatch(endpoint, "GET", {}))
            except Exception as e:                       # never 500 the client
                self._json({"error": f"server error: {e}"}, 200)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                body = {}
            try:
                self._json(dispatch(endpoint, "POST", body))
            except Exception as e:
                self._json({"error": f"server error: {e}"}, 200)

    return Handler
