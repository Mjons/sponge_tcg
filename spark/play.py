"""SPARK — interactive play-vs-bot client.

Run:  python run.py play            (pick decks interactively)
      python run.py play aggro control   (you = aggro, bot = control)

You drive your turn with short commands; the bot narrates its own.
"""

import random

from .cards import build_pool
from .engine import Game, Unit
from .bots import build_deck, make_policy, mulligan_pred

ARCH = ["aggro", "midrange", "control"]
LINE = "=" * 62
THIN = "-" * 62

HELP = """
Commands:
  p <h#> [target]   play card h# from hand (target if it needs one)
  a <m#> <target>   attack with your unit m# (target: f=face, e#=enemy unit)
  t                 use your Spark Token (+1 Spark this turn; 2nd player only)
  v                 re-show the board
  h                 help
  e                 end your turn
  q                 quit

Targets:  f = enemy face   e0,e1.. = enemy unit   m0,m1.. = your unit
Keyword tags:  [G]uard  [R]ush  [B]arrier(active)  [D]rain   *ready = can attack
"""


class Quit(Exception):
    pass


def _safe_input(prompt, default=""):
    try:
        return input(prompt)
    except EOFError:
        print(default or "e")
        return default or "e"       # EOF -> end turn, so piped runs terminate
    except KeyboardInterrupt:
        raise Quit()


def _kw_tags(u):
    tags = ""
    if "guard" in u.keywords:
        tags += "[G]"
    if "rush" in u.keywords:
        tags += "[R]"
    if u.barrier:
        tags += "[B]"
    if "drain" in u.keywords:
        tags += "[D]"
    return (" " + tags) if tags else ""


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


class Match:
    def __init__(self, human_arch="aggro", bot_arch="control", human_first=None,
                 seed=None):
        self.pool = build_pool()
        self.human_arch = human_arch
        self.bot_arch = bot_arch
        self.rng = random.Random(seed)
        if human_first is None:
            human_first = self.rng.random() < 0.5
        self.human_first = human_first
        self.human_idx = 0 if human_first else 1
        self.bot_idx = 1 - self.human_idx

        decks = [None, None]
        decks[self.human_idx] = build_deck(self.pool, human_arch)
        decks[self.bot_idx] = build_deck(self.pool, bot_arch)
        self.log = []
        self.game = Game(decks[0], decks[1], rng=self.rng, log=self.log)
        self.bot_policy = make_policy(bot_arch)
        self.cursor = 0   # index into self.log already shown to the player

    # -- players ------------------------------------------------------------
    @property
    def me(self):
        return self.game.players[self.human_idx]

    @property
    def foe(self):
        return self.game.players[self.bot_idx]

    # -- rendering ----------------------------------------------------------
    def render(self):
        g, me, foe = self.game, self.me, self.foe
        print("\n" + LINE)
        print(f" Opponent [{self.bot_arch}]   life {foe.life:>3}   "
              f"spark {foe.spark_max}/{foe.spark_max}   hand:{len(foe.hand)}   "
              f"token:{'yes' if foe.token else 'no'}")
        if foe.board:
            for i, u in enumerate(foe.board):
                print(f"     [e{i}] {u.card.name:<20} {u.atk}/{u.health}{_kw_tags(u)}")
        else:
            print("     (no units)")
        print(THIN)
        if me.board:
            for i, u in enumerate(me.board):
                rdy = "  *ready" if (u.ready and u.atk > 0) else ""
                print(f"     [m{i}] {u.card.name:<20} {u.atk}/{u.health}"
                      f"{_kw_tags(u)}{rdy}")
        else:
            print("     (no units)")
        print(f" You [{self.human_arch}]   life {me.life:>3}   "
              f"spark {me.spark}/{me.spark_max}   "
              f"token:{'yes' if me.token else 'no'}")
        print(LINE)
        print(" Your hand:")
        for i, c in enumerate(me.hand):
            afford = " " if c.cost <= me.spark else "x"
            if c.is_unit:
                body = f"Unit {c.atk}/{c.health}"
                extra = f"  {c.text}" if c.text else ""
            else:
                body = "Spell"
                extra = f"  {c.text}"
            print(f"  {afford}[h{i}] {c.cost:>2}  {c.name:<20} {body}{extra}")
        print(f" Spark {me.spark}/{me.spark_max}   "
              f"[p]lay  [a]ttack  [t]oken  [v]iew  [h]elp  [e]nd  [q]uit")

    def flush_bot_log(self):
        new = self.log[self.cursor:]
        if new:
            print(f"\n── Opponent's turn [{self.bot_arch}] ──")
            name = self.foe.name
            for line in new:
                # strip the internal "P0 " / "P0: " prefix — the header says who
                for pre in (name + ": ", name + " "):
                    if line.startswith(pre):
                        line = line[len(pre):]
                        break
                print("   " + line)
        self.cursor = len(self.log)

    # -- target parsing -----------------------------------------------------
    def _resolve_target(self, tok):
        """'f' -> 'face'; 'e#' -> enemy unit; 'm#' -> my unit; else None."""
        if not tok:
            return None
        tok = tok.strip().lower()
        if tok in ("f", "face"):
            return "face"
        try:
            if tok[0] == "e":
                return self.foe.board[int(tok[1:])]
            if tok[0] == "m":
                return self.me.board[int(tok[1:])]
        except (ValueError, IndexError):
            return None
        return None

    # -- command handlers ---------------------------------------------------
    def do_play(self, args):
        me = self.me
        if not args:
            print("  usage: p <h#> [target]")
            return
        try:
            idx = int(args[0].lstrip("h"))
            card = me.hand[idx]
        except (ValueError, IndexError):
            print("  no such card in hand.")
            return
        if card.cost > me.spark:
            print(f"  not enough Spark ({card.cost} needed, {me.spark} available)."
                  f"  Try 't' for your Token.")
            return
        if card.is_unit and len(me.board) >= self.game.BOARD_CAP:
            print("  your board is full (7).")
            return

        kind = _target_kind(card)
        target = None
        if kind:
            tok = args[1] if len(args) > 1 else None
            if kind == "enemy":
                if not self.foe.board:
                    print("  no enemy unit to target — hold this card.")
                    return
                target = self._resolve_target(tok) if tok else None
                if not isinstance(target, Unit) or target not in self.foe.board:
                    tok = _safe_input("  target enemy unit (e#): ")
                    target = self._resolve_target(tok)
                if not isinstance(target, Unit) or target not in self.foe.board:
                    print("  invalid target.")
                    return
            elif kind == "flexible":
                target = self._resolve_target(tok) if tok else None
                if target is None:
                    tok = _safe_input("  target (f=face / e#): ")
                    target = self._resolve_target(tok)
                if target != "face" and (not isinstance(target, Unit)
                                         or target not in self.foe.board):
                    print("  invalid target.")
                    return
            elif kind == "friendly":
                if not me.board:
                    print("  no friendly unit to buff — hold this card.")
                    return
                target = self._resolve_target(tok) if tok else None
                if not isinstance(target, Unit) or target not in me.board:
                    tok = _safe_input("  target your unit (m#): ")
                    target = self._resolve_target(tok)
                if not isinstance(target, Unit) or target not in me.board:
                    print("  invalid target.")
                    return

        ok = self.game.play_card(me, card, target)
        if ok:
            self.cursor = len(self.log)   # don't re-narrate our own action
            self.render()
        else:
            print("  couldn't play that.")

    def do_attack(self, args):
        g, me = self.game, self.me
        if len(args) < 2:
            print("  usage: a <m#> <target>   (target: f or e#)")
            return
        try:
            attacker = me.board[int(args[0].lstrip("m"))]
        except (ValueError, IndexError):
            print("  no such unit.")
            return
        if not attacker.ready:
            print("  that unit isn't ready (summoning sickness / already attacked).")
            return
        if attacker.atk <= 0:
            print("  that unit has 0 Attack.")
            return
        units, face_ok = g.legal_attack_targets(me)
        target = self._resolve_target(args[1])
        if target == "face" and not face_ok:
            print("  a Guard is in the way — you must attack it first.")
            return
        if isinstance(target, Unit) and target not in units:
            print("  illegal target (Guard forces you onto a Guard unit).")
            return
        if target is None:
            print("  invalid target.")
            return
        foe_before = set(id(u) for u in self.foe.board)
        me_before = set(id(u) for u in me.board)
        tname = "face" if target == "face" else target.card.name
        if g.attack(attacker, target):
            self.cursor = len(self.log)
            # report kills
            killed = [u for u in [target] if isinstance(u, Unit)
                      and id(u) not in set(id(x) for x in self.foe.board)]
            lost = [id(attacker)] if id(attacker) not in set(id(x) for x in me.board) else []
            note = ""
            if killed:
                note += f"  {tname} dies."
            if lost:
                note += f"  Your {attacker.card.name} dies."
            print(f"  {attacker.card.name} attacks {tname}.{note}")
            self.render()
        else:
            print("  attack failed.")

    def do_token(self):
        if self.game.use_token(self.me):
            self.cursor = len(self.log)
            print(f"  Spark Token spent. Spark now {self.me.spark}/{self.me.spark_max}.")
        else:
            print("  no Spark Token available.")

    # -- turns --------------------------------------------------------------
    def human_turn(self):
        self.render()
        while True:
            if self.game.check_winner() is not None:
                return
            raw = _safe_input("\n > ").strip()
            if not raw:
                continue
            cmd, *args = raw.split()
            cmd = cmd.lower()
            if cmd in ("e", "end"):
                return
            elif cmd in ("q", "quit"):
                raise Quit()
            elif cmd in ("h", "help", "?"):
                print(HELP)
            elif cmd in ("v", "view"):
                self.render()
            elif cmd in ("p", "play"):
                self.do_play(args)
            elif cmd in ("a", "attack"):
                self.do_attack(args)
            elif cmd in ("t", "token"):
                self.do_token()
            else:
                print("  unknown command — 'h' for help.")

    def _mulligan(self, game, player, first):
        if player is not self.me:
            game.mulligan(player, mulligan_pred(self.bot_arch))
            return
        print("\nYour opening hand:")
        for i, c in enumerate(player.hand):
            stat = f"{c.atk}/{c.health}" if c.is_unit else "spell"
            print(f"   [{i}] {c.cost}  {c.name} ({stat})")
        raw = _safe_input("Mulligan which? (space-separated #, blank=keep): ", "")
        toss = set()
        for tok in raw.split():
            if tok.isdigit() and int(tok) < len(player.hand):
                toss.add(int(tok))
        if toss:
            game.mulligan(player, lambda c: player.hand.index(c) not in toss)

    # -- driver -------------------------------------------------------------
    def run(self):
        g = self.game
        who = "You" if self.human_first else f"Bot ({self.bot_arch})"
        print(LINE)
        print(f" SPARK — you are [{self.human_arch}] vs bot [{self.bot_arch}]")
        print(f" Starting life {g.start_life}.  {who} go first.")
        print(LINE)

        def policy(gg, p):
            if p is self.me:
                self.human_turn()
                self.cursor = len(self.log)
            else:
                self.bot_policy(gg, p)
                self.flush_bot_log()

        try:
            g.setup(mulligan_fn=self._mulligan)
            while g.winner is None and g.turn < g.TURN_LIMIT:
                g.turn += 1
                player = g.players[g.active]
                g.start_turn(player)
                if g.check_winner() is not None:
                    break
                policy(g, player)
                g._cleanup()
                if g.check_winner() is not None:
                    break
                g.active = 1 - g.active
            self._announce()
        except Quit:
            print("\nGGs — quit.")

    def _announce(self):
        w = self.game.winner
        print("\n" + LINE)
        if w == self.human_idx:
            print(f" YOU WIN!  ({self.me.life} life left)")
        elif w == self.bot_idx:
            print(f" You lose — the {self.bot_arch} bot wins. (you: {self.me.life})")
        else:
            print(" Draw.")
        print(LINE)


def _choose(prompt, options, default):
    print(prompt)
    for i, o in enumerate(options):
        print(f"   {i+1}. {o}")
    raw = _safe_input(f" choose [1-{len(options)}, default {default+1}]: ", "")
    if raw.strip().isdigit():
        k = int(raw) - 1
        if 0 <= k < len(options):
            return k
    return default


def main(args):
    if len(args) >= 2 and args[0] in ARCH and args[1] in ARCH:
        Match(args[0], args[1]).run()
        return
    ha = _choose("Pick YOUR deck:", ARCH, 0)
    ba = _choose("Pick the BOT's deck:", ARCH, 2)
    Match(ARCH[ha], ARCH[ba]).run()
