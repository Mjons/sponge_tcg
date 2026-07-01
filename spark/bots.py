"""Archetype deckbuilders + a heuristic play policy.

Three archetypes are built from the shared 100-card pool so the simulator
can measure the aggro/midrange/control triangle and first-player advantage.
The policy is deliberately simple but competent: curve out, trade or race
per archetype, remove the biggest threat, and take lethal when it's there.
"""

from collections import Counter
from .engine import Unit

MAX_COPIES = 2


# --------------------------------------------------------------------------
# Deckbuilding
# --------------------------------------------------------------------------
def _pick(pool, want, deck, counts, pred, cap=MAX_COPIES):
    """Add up to `want` cards matching pred, respecting copy limits."""
    added = 0
    for c in pool:
        if added >= want:
            break
        limit = 1 if c.rarity == "legendary" else cap
        if pred(c) and counts[c.id] < limit:
            take = min(cap if c.rarity != "legendary" else 1, want - added)
            for _ in range(take):
                if counts[c.id] >= limit:
                    break
                deck.append(c)
                counts[c.id] += 1
                added += 1
    return added


def build_deck(pool, archetype):
    deck, counts = [], Counter()
    units = [c for c in pool if c.is_unit]
    spells = [c for c in pool if not c.is_unit]

    if archetype == "aggro":
        # low curve, rush, cheap burn, few answers
        cheap = sorted([u for u in units if u.cost <= 3],
                       key=lambda c: (-(c.role == "aggro"), c.cost, -(c.atk)))
        _pick(cheap, 18, deck, counts, lambda c: True)
        _pick(spells, 8, deck, counts, lambda c: c.role == "aggro" and c.cost <= 3)
        _pick(units, 30 - len(deck), deck, counts, lambda c: c.cost <= 4)
        _pick(pool, 30 - len(deck), deck, counts, lambda c: c.cost <= 5)

    elif archetype == "control":
        # removal, sweepers, draw, big finishers, guards
        _pick(spells, 12, deck, counts,
              lambda c: c.role == "control" and any(
                  e["type"] in ("damage_unit", "destroy", "destroy_damaged", "aoe")
                  for e in c.effects))
        _pick(spells, 4, deck, counts,
              lambda c: any(e["type"] == "draw" for e in c.effects))
        _pick(spells, 2, deck, counts,
              lambda c: any(e["type"] == "heal_face" for e in c.effects))
        big = sorted([u for u in units if u.cost >= 5], key=lambda c: -c.cost)
        _pick(big, 8, deck, counts, lambda c: True)
        _pick(units, 30 - len(deck), deck, counts,
              lambda c: c.cost >= 3 and c.role in ("control", "mid"))
        _pick(pool, 30 - len(deck), deck, counts, lambda c: True)

    else:  # midrange
        mids = sorted(units, key=lambda c: abs(c.cost - 3))
        _pick(mids, 20, deck, counts, lambda c: 2 <= c.cost <= 6)
        _pick(spells, 6, deck, counts,
              lambda c: any(e["type"] in ("damage_unit", "destroy", "damage_flexible")
                            for e in c.effects))
        _pick(pool, 30 - len(deck), deck, counts, lambda c: True)

    # top up defensively if still short
    _pick(pool, 30 - len(deck), deck, counts, lambda c: True)
    assert len(deck) == 30, f"{archetype} deck has {len(deck)} cards"
    return deck


def mulligan_pred(archetype):
    ceiling = {"aggro": 3, "midrange": 4, "control": 5}[archetype]
    return lambda card: card.cost <= ceiling


# --------------------------------------------------------------------------
# Play policy
# --------------------------------------------------------------------------
def _best_enemy_unit(units):
    return max(units, key=lambda u: u.value()) if units else None


def _lethal_this_combat(game, me):
    opp = game.opponent(me)
    _, face_ok = game.legal_attack_targets(me)
    if not face_ok:
        return False
    dmg = sum(u.atk for u in me.board if u.ready)
    return dmg >= opp.life


def make_policy(archetype):
    aggressive = archetype == "aggro"

    def choose_target(game, me, card_or_effect):
        """Pick a target for the (single) effect on a card being considered."""
        opp = game.opponent(me)
        effects = card_or_effect.effects if hasattr(card_or_effect, "effects") else ()
        for e in effects:
            t = e["type"]
            if t in ("damage_unit", "destroy", "destroy_damaged"):
                cands = opp.board
                if t == "destroy_damaged":
                    cands = [u for u in cands if u.damaged]
                if t == "damage_unit":
                    # prefer a unit this exactly kills, else biggest
                    kill = [u for u in cands if not u.barrier and u.health <= e["amount"]]
                    if kill:
                        return max(kill, key=lambda u: u.value())
                return _best_enemy_unit(cands)
            if t == "damage_flexible":
                if aggressive and (game.turn > 6 or not opp.board):
                    return "face"
                kill = [u for u in opp.board if not u.barrier and u.health <= e["amount"]
                        and u.value() >= 4]
                if kill:
                    return max(kill, key=lambda u: u.value())
                return "face" if aggressive else (_best_enemy_unit(opp.board) or "face")
            if t in ("buff", "buff_all"):
                ready = [u for u in me.board if u.ready and u.atk > 0]
                return max(ready, key=lambda u: u.atk) if ready else (me.board[0] if me.board else None)
            if t in ("bounce", "silence"):
                return _best_enemy_unit(opp.board)
        return None

    def playable_targets_ok(game, me, card):
        """Skip a card that needs a target but has none."""
        opp = game.opponent(me)
        for e in card.effects:
            t = e["type"]
            if t in ("damage_unit", "destroy", "destroy_damaged", "bounce", "silence"):
                pool = opp.board
                if t == "destroy_damaged":
                    pool = [u for u in pool if u.damaged]
                if not pool:
                    return False
            if t in ("buff", "buff_all") and not me.board:
                return False
        return True

    def score(game, me, card):
        opp = game.opponent(me)
        if card.is_unit:
            s = 10 + card.atk + card.health + card.cost * 0.6
            if "guard" in card.keywords and not aggressive:
                s += 3
            if "rush" in card.keywords:
                s += 2
            return s
        # spells
        s = 0
        for e in card.effects:
            t = e["type"]
            if t in ("damage_unit", "destroy", "destroy_damaged"):
                tgt = _best_enemy_unit(opp.board if t != "destroy_damaged"
                                       else [u for u in opp.board if u.damaged])
                if tgt is None:
                    return -1
                s = 8 + tgt.value()
                if tgt.value() < 5 and card.cost >= 3:  # don't waste hard removal
                    s -= 6
            elif t == "aoe":
                killed = [u for u in opp.board if not u.barrier and u.health <= e["amount"]]
                if len(opp.board) < 2:
                    return -1
                s = 4 + 3 * len(killed) + len(opp.board)
            elif t == "damage_flexible":
                if aggressive:
                    s = 6 + e["amount"]
                else:
                    tgt = _best_enemy_unit(opp.board)
                    s = 5 + (tgt.value() if tgt else e["amount"])
            elif t == "draw":
                s = (7 if len(me.hand) <= 2 else 3) + (1 if archetype == "control" else 0)
            elif t == "heal_face":
                s = 8 if me.life <= 10 else (2 if me.life <= 15 else -1)
            elif t in ("buff", "buff_all"):
                ready = [u for u in me.board if u.ready and u.atk > 0]
                s = 4 + (2 if ready else -5)
            elif t == "bounce":
                s = 5 if opp.board else -1
            elif t == "silence":
                tgt = _best_enemy_unit(opp.board)
                s = (3 + tgt.value()) if tgt and (tgt.keywords or tgt.barrier) else -1
        return s

    def play_phase(game, me):
        # Proactive Spark Token use (mostly P2): "coin out" a card one turn
        # early when holding something that costs exactly spark+1.
        if me.token and game.turn <= 12:
            if any(c.cost == me.spark + 1 for c in me.hand):
                game.use_token(me)
        # If we have exact lethal on board already, skip to combat.
        guard = 0
        while guard < 40:
            guard += 1
            affordable = [c for c in me.hand if c.cost <= me.spark]
            # consider spending the Spark Token to enable a bigger play (P2)
            if me.token and not affordable and me.hand:
                nxt = min(c.cost for c in me.hand)
                if nxt == me.spark + 1:
                    game.use_token(me)
                    continue
            best, best_s = None, 0.5
            for c in affordable:
                if c.effects and not playable_targets_ok(game, me, c):
                    continue
                sc = score(game, me, c)
                if sc > best_s:
                    best, best_s = c, sc
            if best is None:
                # early-game token use to keep tempo
                if me.token and game.turn <= 5 and me.hand:
                    if any(c.cost == me.spark + 1 for c in me.hand):
                        game.use_token(me)
                        continue
                break
            tgt = choose_target(game, me, best)
            game.play_card(me, best, tgt)

    def combat_phase(game, me):
        opp = game.opponent(me)
        # take lethal if available
        if _lethal_this_combat(game, me):
            for u in [u for u in me.board if u.ready]:
                game.attack(u, "face")
                if game.check_winner() is not None:
                    return
        for u in [u for u in me.board if u.ready and u.atk > 0]:
            if game.check_winner() is not None:
                return
            units, face_ok = game.legal_attack_targets(me)
            if not units and face_ok:
                game.attack(u, "face")
                continue
            if not units:
                continue
            # evaluate best unit target: favourable/lethal trades
            def trade_score(t):
                kills_them = u.atk >= t.health and not t.barrier
                dies = t.atk >= u.health and not u.barrier
                sc = 0
                if kills_them:
                    sc += t.value()
                if dies:
                    sc -= u.value()
                return sc
            best_t = max(units, key=trade_score)
            good_trade = trade_score(best_t) > 0
            must_hit_guard = not face_ok
            if must_hit_guard:
                game.attack(u, best_t)
            elif aggressive:
                # aggro goes face unless there's a clean kill that also survives
                clean = (u.atk >= best_t.health and not best_t.barrier
                         and best_t.atk < u.health)
                game.attack(u, best_t if (clean and best_t.value() >= 5) else "face")
            else:
                if good_trade:
                    game.attack(u, best_t)
                elif face_ok and not opp.board:
                    game.attack(u, "face")
                elif face_ok and me.board and sum(x.atk for x in me.board) >= 8:
                    game.attack(u, "face")   # pressure when ahead on board
                else:
                    game.attack(u, best_t)   # chip in

    def policy(game, me):
        play_phase(game, me)
        combat_phase(game, me)

    return policy
