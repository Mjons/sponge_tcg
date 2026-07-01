"""Vercel serverless function for /api/state — SPARK: LANES.

Explicit top-level `class handler` so the @vercel/python builder detects the
entrypoint. The spark import is lazy (inside the methods) so importing this
module at build time never fails; at runtime spark/ is bundled via includeFiles.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

ENDPOINT = "state"


def _dispatch(method, body):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)
    from spark.webapi import dispatch
    return dispatch(ENDPOINT, method, body)


class handler(BaseHTTPRequestHandler):
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
            self._json(_dispatch("GET", {}))
        except Exception as e:
            self._json({"error": f"server error: {e}"}, 200)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            body = {}
        try:
            self._json(_dispatch("POST", body))
        except Exception as e:
            self._json({"error": f"server error: {e}"}, 200)
