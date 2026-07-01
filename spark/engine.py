"""SPARK rules engine.

Implements every mechanic from the design spec:
  - incremental Spark (1..10, refills, cannot be stored)  [low variance]
  - 5-step turn: refill / draw / main / combat / end
  - summoning sickness, Rush, Guard, Barrier, Drain
  - simultaneous combat damage, persistent health
  - board cap 7, hand cap 10, fatigue on empty-deck draw
  - first-turn mitigation: P1 skips its first draw; P2 gets a Spark Token
  - starting life 21 (tuned via sim to balance the aggro/control triangle)
  - data-driven effect resolver shared by spells and unit ETB

The engine is policy-agnostic: it exposes legal actions and applies them.
bots.py supplies the decision-making.
"""

import random


class Unit:
    """A unit in play (an instance of a Card)."""
    __slots__ = ("card", "atk", "health", "max_health", "keywords",
                 "barrier", "ready", "owner")

    def __init__(self, card, owner):
        self.card = card
        self.owner = owner
        self.atk = card.atk
        self.health = card.health
        self.max_health = card.health
        self.keywords = set(card.keywords)
        self.barrier = "barrier" in self.keywords
        self.ready = "rush" in self.keywords   # summoning sickness unless Rush

    @property
    def damaged(self):
        return self.health < self.max_health

    def value(self):
        v = self.atk + self.health
        if "guard" in self.keywords:
            v += 2
        if self.barrier:
            v += 2
        if "drain" in self.keywords:
            v += 1
        return v


class Player:
    def __init__(self, deck, name):
        self.name = name
        self.deck = list(deck)
        self.hand = []
        self.board = []
        self.life = 20
        self.spark = 0
        self.spark_max = 0
        self.turns_taken = 0
        self.fatigue = 0
        self.token = False       # one-time +1 Spark (P2 only)

    def alive(self):
        return self.life > 0


class Game:
    BOARD_CAP = 7
    HAND_CAP = 10
    SPARK_CAP = 10
    TURN_LIMIT = 100   # safety; fatigue ends games long before this

    def __init__(self, deck0, deck1, rng=None, log=None,
                 first_skips_draw=True, second_bonus_card=0, second_token=True,
                 start_life=21):
        self.rng = rng or random.Random()
        self.log = log
        self.start_life = start_life
        self.players = [Player(deck0, "P0"), Player(deck1, "P1")]
        for p in self.players:
            p.life = start_life
        self.active = 0
        self.turn = 0
        self.winner = None
        # first-turn mitigation knobs (tuned via sim; see README §7)
        self.first_skips_draw = first_skips_draw
        self.second_bonus_card = second_bonus_card
        self.second_token = second_token

    # -- setup --------------------------------------------------------------
    def _log(self, msg):
        if self.log is not None:
            self.log.append(msg)

    def setup(self, mulligan_fn=None):
        for p in self.players:
            self.rng.shuffle(p.deck)
        # P1 (second player) draws +N bonus cards and gets the Spark Token.
        self._draw(self.players[0], 3, fatigue=False)
        self._draw(self.players[1], 3 + self.second_bonus_card, fatigue=False)
        self.players[1].token = self.second_token
        if mulligan_fn:
            for i, p in enumerate(self.players):
                mulligan_fn(self, p, first=(i == 0))

    def mulligan(self, player, keep_pred):
        """Return unwanted cards to deck, reshuffle, redraw that many. Once."""
        toss = [c for c in player.hand if not keep_pred(c)]
        if not toss:
            return
        for c in toss:
            player.hand.remove(c)
        n = len(toss)
        player.deck.extend(toss)
        self.rng.shuffle(player.deck)
        self._draw(player, n, fatigue=False)

    # -- primitives ---------------------------------------------------------
    def _draw(self, player, n=1, fatigue=True):
        for _ in range(n):
            if player.deck:
                card = player.deck.pop()
                if len(player.hand) < self.HAND_CAP:
                    player.hand.append(card)      # over-cap draws are burned
            elif fatigue:
                player.fatigue += 1
                self._damage_face(player, player.fatigue)
                self._log(f"{player.name} is out of cards: {player.fatigue} fatigue damage")

    def _damage_face(self, player, amount):
        if amount > 0:
            player.life -= amount

    def opponent(self, player):
        return self.players[1 - self.players.index(player)]

    # -- effect resolver (shared by spells & unit ETB) ----------------------
    def apply_effect(self, controller, effect, target=None):
        """target is a Unit, the string 'face', or None. Chosen by the bot."""
        opp = self.opponent(controller)
        t = effect["type"]

        if t == "damage_unit":
            if isinstance(target, Unit):
                self._hit_unit(target, effect["amount"])
        elif t == "damage_face":
            self._damage_face(opp, effect["amount"])
        elif t == "damage_flexible":
            if target == "face":
                self._damage_face(opp, effect["amount"])
            elif isinstance(target, Unit):
                self._hit_unit(target, effect["amount"])
        elif t == "aoe":
            for u in list(opp.board):
                self._hit_unit(u, effect["amount"])
        elif t == "destroy":
            if isinstance(target, Unit):
                target.health = 0
        elif t == "destroy_damaged":
            if isinstance(target, Unit) and target.damaged:
                target.health = 0
        elif t == "draw":
            self._draw(controller, effect["amount"])
        elif t == "heal_face":
            controller.life = min(self.start_life, controller.life + effect["amount"])
        elif t == "buff":
            if isinstance(target, Unit):
                target.atk += effect.get("atk", 0)
                target.health += effect.get("health", 0)
                target.max_health += effect.get("health", 0)
                g = effect.get("grant")
                if g:
                    target.keywords.add(g)
                    if g == "rush":
                        target.ready = True
                    if g == "barrier":
                        target.barrier = True
        elif t == "buff_all":
            for u in controller.board:
                u.atk += effect.get("atk", 0)
                u.health += effect.get("health", 0)
                u.max_health += effect.get("health", 0)
        elif t == "bounce":
            if isinstance(target, Unit) and target in opp.board:
                opp.board.remove(target)
                if len(opp.hand) < self.HAND_CAP:
                    opp.hand.append(target.card)
        elif t == "silence":
            if isinstance(target, Unit):
                target.keywords.clear()
                target.barrier = False
                target.atk = target.card.atk
                target.health = min(target.health, target.card.health)
                target.max_health = target.card.health
        self._cleanup()

    def _hit_unit(self, unit, amount):
        if amount <= 0:
            return
        if unit.barrier:
            unit.barrier = False    # Barrier absorbs the first instance of damage
            return
        unit.health -= amount

    def _cleanup(self):
        for p in self.players:
            p.board = [u for u in p.board if u.health > 0]

    # -- playing cards ------------------------------------------------------
    def play_card(self, player, card, target=None):
        """Play a card from hand. Returns True on success."""
        if card.cost > player.spark or card not in player.hand:
            return False
        if card.is_unit and len(player.board) >= self.BOARD_CAP:
            return False
        player.hand.remove(card)
        player.spark -= card.cost
        tgt = f" -> {self._describe(target)}" if target is not None else ""
        self._log(f"{player.name} plays {card.name} ({card.cost}){tgt}")
        if card.is_unit:
            unit = Unit(card, player)
            player.board.append(unit)
            for e in card.effects:      # ETB effects resolve on entry
                self.apply_effect(player, e, target)
        else:
            for e in card.effects:
                self.apply_effect(player, e, target)
        self._cleanup()
        return True

    def _describe(self, target):
        if target == "face":
            return "face"
        if isinstance(target, Unit):
            return target.card.name
        return str(target)

    def use_token(self, player):
        if player.token:
            player.token = False
            player.spark += 1
            self._log(f"{player.name} uses the Spark Token (+1 Spark)")
            return True
        return False

    # -- combat -------------------------------------------------------------
    def legal_attack_targets(self, attacker_owner):
        """Guard forces attackers onto Guard units first."""
        opp = self.opponent(attacker_owner)
        guards = [u for u in opp.board if "guard" in u.keywords]
        if guards:
            return list(guards), False        # (unit targets, face allowed)
        return list(opp.board), True

    def attack(self, attacker, target):
        """attacker: Unit; target: Unit or 'face'. Simultaneous damage."""
        if not attacker.ready or attacker.atk <= 0:
            return False
        owner = attacker.owner
        opp = self.opponent(owner)
        units, face_ok = self.legal_attack_targets(owner)
        if target == "face":
            if not face_ok:
                return False
            self._damage_face(opp, attacker.atk)
            if "drain" in attacker.keywords:
                owner.life = min(self.start_life, owner.life + attacker.atk)
            self._log(f"{owner.name}: {attacker.card.name} hits face for {attacker.atk}")
        else:
            if target not in units:
                return False
            # snapshot barrier state BEFORE applying (simultaneous)
            atk_prevented = attacker.barrier and target.atk > 0
            def_prevented = target.barrier and attacker.atk > 0
            self._hit_unit(target, attacker.atk)
            self._hit_unit(attacker, target.atk)
            dealt = 0 if def_prevented else attacker.atk
            if "drain" in attacker.keywords and dealt > 0:
                owner.life = min(self.start_life, owner.life + dealt)
            self._log(f"{owner.name}: {attacker.card.name} attacks {target.card.name}")
        attacker.ready = False
        self._cleanup()
        return True

    # -- turn flow ----------------------------------------------------------
    def start_turn(self, player):
        player.turns_taken += 1
        player.spark_max = min(self.SPARK_CAP, player.turns_taken)
        player.spark = player.spark_max        # refill; nothing carries over
        for u in player.board:
            u.ready = True
        # First-turn mitigation: the player going FIRST skips their opening
        # draw (they trade the card for the tempo of curving out first).
        first_player_first_turn = (player is self.players[0]
                                   and player.turns_taken == 1)
        if not (first_player_first_turn and self.first_skips_draw):
            self._draw(player, 1)

    def check_winner(self):
        p0, p1 = self.players
        if not p0.alive() and not p1.alive():
            self.winner = -1        # double-KO -> draw
        elif not p0.alive():
            self.winner = 1
        elif not p1.alive():
            self.winner = 0
        return self.winner

    def run(self, policy, mulligan_fn=None):
        """policy(game, player) executes a full turn (play + combat)."""
        self.setup(mulligan_fn)
        while self.winner is None and self.turn < self.TURN_LIMIT:
            self.turn += 1
            player = self.players[self.active]
            self.start_turn(player)
            if self.check_winner() is not None:   # fatigue could be lethal
                break
            policy(self, player)
            self._cleanup()
            if self.check_winner() is not None:
                break
            self.active = 1 - self.active
        if self.winner is None:
            self.winner = -1      # timeout = draw (should be vanishingly rare)
        return self.winner
