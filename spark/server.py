"""SPARK — local web GUI (stdlib only, no dependencies).

A tiny HTTP server wraps the existing engine and serves a single-page client.
Browsers render the .webp card art natively, so there's nothing to install.

  python run.py gui            # starts http://127.0.0.1:8000 and opens a browser

The client is single-player: you vs the bot. One global session; refresh the
page or click "New Game" to restart.
"""

import json
import os
import random
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .cards import build_pool
from .engine import Game, Unit
from .bots import build_deck, make_policy, mulligan_pred

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
ARCH = ["aggro", "midrange", "control"]


def _target_kind(card):
    """What target the (single) targeting effect on this card needs."""
    for e in card.effects:
        t = e["type"]
        if t in ("damage_unit", "destroy", "destroy_damaged", "bounce", "silence"):
            return "enemy"
        if t == "damage_flexible":
            return "flexible"
        if t == "buff":
            return "friendly"
    return None


class Session:
    """Server-side game driver: human acts via requests; bot plays on end-turn."""

    def __init__(self):
        self.pool = build_pool()
        self.game = None
        self.human_idx = 0
        self.bot_idx = 1
        self.human_arch = "aggro"
        self.bot_arch = "control"
        self.bot_policy = None
        self.log = []
        self.message = ""

    # -- accessors ----------------------------------------------------------
    @property
    def me(self):
        return self.game.players[self.human_idx]

    @property
    def foe(self):
        return self.game.players[self.bot_idx]

    # -- lifecycle ----------------------------------------------------------
    def new_game(self, human_arch, bot_arch, seed=None):
        if human_arch not in ARCH:
            human_arch = "aggro"
        if bot_arch not in ARCH:
            bot_arch = "control"
        self.human_arch, self.bot_arch = human_arch, bot_arch
        rng = random.Random(seed)
        self.human_idx = 0 if rng.random() < 0.5 else 1
        self.bot_idx = 1 - self.human_idx
        decks = [None, None]
        decks[self.human_idx] = build_deck(self.pool, human_arch)
        decks[self.bot_idx] = build_deck(self.pool, bot_arch)
        self.log = []
        self.game = Game(decks[0], decks[1], rng=rng, log=self.log)
        self.bot_policy = make_policy(bot_arch)
        self.message = "New game."

        def mull(g, p, first):
            arch = human_arch if p is self.me else bot_arch
            g.mulligan(p, mulligan_pred(arch))

        self.game.setup(mulligan_fn=mull)
        self._advance_to_human()
        return self.state()

    def _advance_to_human(self):
        """Run bot turns (if any) until the human's turn has begun."""
        g = self.game
        safety = 0
        while g.winner is None and safety < 500:
            safety += 1
            player = g.players[g.active]
            g.turn += 1
            g.start_turn(player)
            if g.check_winner() is not None:
                break
            if player is self.me:
                return                      # human's turn is now live
            self.bot_policy(g, player)
            g._cleanup()
            if g.check_winner() is not None:
                break
            g.active = 1 - g.active

    def end_turn(self):
        g = self.game
        if g.winner is not None:
            return self.state()
        g._cleanup()
        if g.check_winner() is not None:
            return self.state()
        g.active = self.bot_idx
        self.message = "Opponent is thinking…"
        self._advance_to_human()
        if g.winner is None:
            self.message = "Your turn."
        return self.state()

    # -- human actions ------------------------------------------------------
    def _resolve_target(self, spec):
        if not spec:
            return None
        kind = spec.get("kind")
        if kind == "face":
            return "face"
        if kind == "enemy":
            i = spec.get("index")
            if isinstance(i, int) and 0 <= i < len(self.foe.board):
                return self.foe.board[i]
        if kind == "friendly":
            i = spec.get("index")
            if isinstance(i, int) and 0 <= i < len(self.me.board):
                return self.me.board[i]
        return None

    def play(self, index, target_spec):
        g, me = self.game, self.me
        if g.winner is not None or g.active != self.human_idx:
            return self._err("Not your turn.")
        if not isinstance(index, int) or not (0 <= index < len(me.hand)):
            return self._err("No such card.")
        card = me.hand[index]
        if card.cost > me.spark:
            return self._err(f"Not enough Spark ({card.cost} needed).")
        if card.is_unit and len(me.board) >= g.BOARD_CAP:
            return self._err("Your board is full (7).")
        kind = _target_kind(card)
        target = self._resolve_target(target_spec) if kind else None
        if kind == "enemy" and not isinstance(target, Unit):
            return self._err("Choose an enemy unit to target.")
        if kind == "friendly" and not isinstance(target, Unit):
            return self._err("Choose one of your units.")
        if kind == "flexible" and target is None:
            return self._err("Choose a target (a unit or the enemy face).")
        name = card.name
        if g.play_card(me, card, target):
            self.message = f"You played {name}."
            g.check_winner()
        else:
            return self._err("Couldn't play that card.")
        return self.state()

    def attack(self, index, target_spec):
        g, me = self.game, self.me
        if g.winner is not None or g.active != self.human_idx:
            return self._err("Not your turn.")
        if not isinstance(index, int) or not (0 <= index < len(me.board)):
            return self._err("No such unit.")
        attacker = me.board[index]
        if not attacker.ready:
            return self._err("That unit can't attack yet.")
        if attacker.atk <= 0:
            return self._err("That unit has 0 Attack.")
        units, face_ok = g.legal_attack_targets(me)
        target = self._resolve_target(target_spec)
        if target == "face" and not face_ok:
            return self._err("A Guard blocks the way — attack it first.")
        if isinstance(target, Unit) and target not in units:
            return self._err("Illegal target (Guard forces the attack).")
        if target is None:
            return self._err("Choose a target.")
        tname = "face" if target == "face" else target.card.name
        if g.attack(attacker, target):
            self.message = f"{attacker.card.name} attacked {tname}."
            g.check_winner()
        else:
            return self._err("Attack failed.")
        return self.state()

    def token(self):
        g = self.game
        if g.winner is not None or g.active != self.human_idx:
            return self._err("Not your turn.")
        if g.use_token(self.me):
            self.message = "Spark Token spent (+1 Spark)."
        else:
            self.message = "No Spark Token available."
        return self.state()

    def _err(self, msg):
        self.message = msg
        st = self.state()
        st["error"] = msg
        return st

    # -- serialization ------------------------------------------------------
    def _unit_view(self, u, mine):
        _, face_ok = self.game.legal_attack_targets(self.me)
        return {
            "name": u.card.name,
            "cost": u.card.cost,
            "atk": u.atk,
            "health": u.health,
            "maxHealth": u.max_health,
            "keywords": sorted(u.keywords),
            "barrier": u.barrier,
            "guard": "guard" in u.keywords,
            "drain": "drain" in u.keywords,
            "art": ("/" + u.card.art) if u.card.art else None,
            "role": u.card.role,
            "canAttack": bool(mine and u.ready and u.atk > 0
                              and self.game.active == self.human_idx),
        }

    def _hand_view(self, c, i):
        kind = _target_kind(c)
        playable = (c.cost <= self.me.spark
                    and self.game.active == self.human_idx
                    and self.game.winner is None)
        if c.is_unit and len(self.me.board) >= self.game.BOARD_CAP:
            playable = False
        if kind == "enemy" and not self.foe.board:
            playable = False
        if kind == "friendly" and not self.me.board:
            playable = False
        return {
            "index": i,
            "name": c.name,
            "cost": c.cost,
            "type": c.ctype,
            "atk": c.atk,
            "health": c.health,
            "text": c.text,
            "keywords": list(c.keywords),
            "rarity": c.rarity,
            "role": c.role,
            "art": ("/" + c.art) if c.art else None,
            "needsTarget": kind,
            "playable": playable,
        }

    def state(self):
        g = self.game
        if g is None:
            return {"started": False, "archetypes": ARCH}
        me, foe = self.me, self.foe
        _, face_ok = g.legal_attack_targets(me)
        winner = None
        if g.winner is not None:
            winner = ("human" if g.winner == self.human_idx
                      else "bot" if g.winner == self.bot_idx else "draw")
        return {
            "started": True,
            "archetypes": ARCH,
            "active": "human" if g.active == self.human_idx else "bot",
            "winner": winner,
            "message": self.message,
            "startLife": g.start_life,
            "faceAttackable": face_ok,
            "humanFirst": self.human_idx == 0,
            "me": {
                "arch": self.human_arch,
                "life": me.life,
                "spark": me.spark,
                "sparkMax": me.spark_max,
                "token": me.token,
                "deck": len(me.deck),
                "fatigue": me.fatigue,
                "hand": [self._hand_view(c, i) for i, c in enumerate(me.hand)],
                "board": [self._unit_view(u, True) for u in me.board],
            },
            "foe": {
                "arch": self.bot_arch,
                "life": foe.life,
                "sparkMax": foe.spark_max,
                "token": foe.token,
                "deck": len(foe.deck),
                "handCount": len(foe.hand),
                "board": [self._unit_view(u, False) for u in foe.board],
            },
            "log": self.log[-16:],
        }


SESSION = Session()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # quiet

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
        if path == "/" or path == "/index.html":
            try:
                with open(os.path.join(WEB_DIR, "index.html"), "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            except FileNotFoundError:
                self._send(404, "index.html missing", "text/plain")
        elif path == "/api/state":
            self._json(SESSION.state())
        elif path.startswith("/cards/"):
            self._serve_card(path)
        else:
            self._send(404, "not found", "text/plain")

    def _serve_card(self, path):
        name = os.path.basename(path)          # prevent traversal
        fp = os.path.join(REPO_ROOT, "cards", name)
        if os.path.isfile(fp):
            ctype = "image/webp" if name.endswith(".webp") else "application/octet-stream"
            with open(fp, "rb") as f:
                self._send(200, f.read(), ctype)
        else:
            self._send(404, "no card", "text/plain")

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
                self._json(SESSION.new_game(body.get("human", "aggro"),
                                            body.get("bot", "control")))
            elif path == "/api/play":
                self._json(SESSION.play(body.get("index"), body.get("target")))
            elif path == "/api/attack":
                self._json(SESSION.attack(body.get("index"), body.get("target")))
            elif path == "/api/token":
                self._json(SESSION.token())
            elif path == "/api/end":
                self._json(SESSION.end_turn())
            else:
                self._send(404, "not found", "text/plain")
        except Exception as e:  # never 500 the client; surface as a message
            self._json({"error": f"server error: {e}", **SESSION.state()}, 200)


def serve(host="127.0.0.1", port=8000, open_browser=True):
    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}"
    print(f"SPARK GUI running at {url}   (Ctrl-C to stop)", flush=True)
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
