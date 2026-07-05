"""SMUDGE: PANEL BRAWL — a panel-battler (Marvel Snap-like) built on the
same minimal/balanced principles as the combat game.

Starring Smudge the Sponge — a Panel Haus game (the three battle columns
are styled as comic PANELS; code and the API still say "lane" throughout).
Formerly SPARK: LANES.

RULES (fits on a card):
  - 3 panels (columns). Each side has 2 slots per panel.
  - 9 rounds. On round T you have T Energy (does not carry over).
  - Each round: place cards from hand into your panel slots (pay Energy),
    then reveal. Cards have Attack, Power (health AND score) and an
    optional PERK (On Reveal = one-shot; Ongoing = while in play).
  - Reveal is simultaneous & hidden: the bot commits to the pre-round
    board without seeing your staged cards, then both flip. Opposing
    cards in the same slot then trade damage; 0 Power = death.
  - Scoring: after combat you bank a point for every panel you lead
    (Golden panels pay 2). Most points after round 9 wins (ties broken
    by total Power).

BALANCE: power follows the same budget as the combat game,
    Power budget = 2*Cost + 1,  minus the perk's cost in power points.
Perk costs are tuned, not proven — flagged for playtesting.

ARENA MODIFIERS: campaign levels draw named lane rules (see MODS) onto
random lanes at match start — Volcanic burns, Sanctum bans combat, Tailwind
discounts, Golden doubles points, Dead Zone silences On Reveal, Overgrown
buffs. They apply to both sides; the deck faces a fresh puzzle each run.
"""

import random
from dataclasses import dataclass, field
from typing import Optional

LANES = 3
SLOTS_PER_LANE = 2      # 2 per side; combat deaths free slots to replace over 9 rounds
MAX_TURNS = 9
HAND_CAP = 8
OPENING_DRAW = 3      # +1 drawn on turn 1 => 4-card opening hand
DECK_SIZE = 16
ART = "cards/"


def _text(ab):
    if not ab:
        return ""
    t, n = ab["type"], ab.get("amount", 0)
    return {
        "reveal_buff_here_others": f"On Reveal: your other cards here get +{n} Power.",
        "reveal_debuff_here_enemy": f"On Reveal: enemy cards here get -{n} Power.",
        "reveal_buff_other_lanes": f"On Reveal: your cards in the other two lanes get +{n} Power.",
        "reveal_draw": f"On Reveal: draw {n} card{'s' if n != 1 else ''}.",
        "reveal_buff_self": f"On Reveal: +{n} Power.",
        "ongoing_ally_here": f"Ongoing: your other cards here have +{n} Power.",
        "ongoing_per_ally_here": f"Ongoing: +{n} Power for each other card you have here.",
    }[t]


@dataclass(frozen=True)
class LaneCard:
    id: int
    name: str
    cost: int
    attack: int           # damage dealt to the opposing card each round
    power: int            # doubles as health AND lane score; 0 => the card dies
    ability: Optional[dict] = None
    art: Optional[str] = None
    rarity: str = "common"

    @property
    def text(self):
        return _text(self.ability)


def _rev(t, n):
    return {"trigger": "reveal", "type": t, "amount": n}


def _ong(t, n):
    return {"trigger": "ongoing", "type": t, "amount": n}


# (name, cost, attack, power, ability, art, rarity)  --  attack+power ~= 2*cost+1
# Every card is art-backed (no placeholder fillers).
_POOL_SPEC = [
    # original marquee sponges
    ("Electric Brawler", 1, 1, 1, _rev("reveal_buff_self", 1),
     "smudgies-sponge-11-brawler-electric.webp", "rare"),
    ("Teal Swordsman", 2, 3, 2, None, "smudgies-sponge-05-swordsman-teal.webp", "common"),
    ("Orb Mage", 2, 1, 2, _rev("reveal_draw", 1),
     "smudgies-sponge-12-mage-orb.webp", "rare"),
    ("Ghostrider's Coin", 2, 1, 2, _rev("reveal_buff_other_lanes", 2),
     "smudgies-sponge-02-ghostrider-coin.webp", "epic"),
    ("Barbarian's Club", 3, 5, 2, None,
     "smudgies-sponge-09-barbarian-club.webp", "rare"),    # glass cannon
    ("Revolver Gunslinger", 3, 3, 2, _rev("reveal_debuff_here_enemy", 2),
     "smudgies-sponge-06-gunslinger-revolver.webp", "rare"),
    ("Ronin of the Fireblade", 3, 2, 2, _rev("reveal_buff_other_lanes", 3),
     "smudgies-sponge-08-ronin-fireblade.webp", "epic"),
    ("The Waterbender", 3, 2, 4, _ong("ongoing_ally_here", 1),
     "smudgies-sponge-10-waterbender.webp", "rare"),
    ("Katana Samurai", 4, 4, 5, None, "smudgies-sponge-03-samurai-katana.webp", "rare"),
    ("Greatsword Knight", 4, 3, 4, _rev("reveal_buff_here_others", 3),
     "smudgies-sponge-04-knight-greatsword.webp", "epic"),
    ("Gold Streetfighter", 4, 3, 4, _ong("ongoing_per_ally_here", 2),
     "smudgies-sponge-14-streetfighter-gold.webp", "epic"),
    ("Emperor Parasol", 5, 3, 5, _ong("ongoing_ally_here", 2),
     "smudgies-sponge-16-emperor-parasol.webp", "legendary"),
    ("Ronin of Purpleflame", 5, 4, 4, _rev("reveal_buff_here_others", 3),
     "smudgies-sponge-15-ronin-purpleflame.webp", "epic"),
    ("Oni, the Kaiju", 6, 6, 7, None, "smudgies-sponge-01-kaiju-oni.webp", "legendary"),
    ("The Kraken", 6, 4, 6, _ong("ongoing_per_ally_here", 2),
     "smudgies-sponge-13-kraken.webp", "legendary"),
    ("The Crowned Dark", 6, 4, 5, _rev("reveal_debuff_here_enemy", 4),
     "smudgies-sponge-07-darklord-crown.webp", "legendary"),

    # --- "Smudgies" full-art sponges (added set) ---
    ("Bandana Sponge", 2, 3, 2, None,
     "grok-524172db-8b9d-4a10-a9d6-93e51c1a38f6.jpg", "rare"),          # ninja thug
    ("Shades Sponge", 2, 2, 2, _rev("reveal_buff_self", 1),
     "grok-74d522af-2ae4-4f1d-8f25-d00d97a4658e.png", "rare"),          # deal-with-it
    ("Aqua Sponge", 3, 2, 3, _ong("ongoing_ally_here", 1),
     "grok-d7bb69ae-8487-4be7-93f2-7fa8681c623f.jpg", "rare"),          # waterbender
    ("Duelist Sponge", 3, 4, 2, None,
     "grok-814e7bc0-5887-470a-b3c8-b57a5900d9c8.jpg", "epic"),          # flintlock
    ("Neon Sponge", 4, 3, 4, _rev("reveal_buff_other_lanes", 2),
     "grok-e4e8874f-0b86-42d3-a1f1-f6c2ceb3bed4.jpg", "rare"),          # cyberpunk
    ("Femme Fatale Sponge", 4, 3, 3, _rev("reveal_debuff_here_enemy", 3),
     "grok-e483296f-2543-45c1-be2b-47ce685837e7.jpg", "epic"),          # skull & shades
    ("Steampunk Ronin", 4, 5, 4, None,
     "smudgies-sponge-steampunk-ronin.png", "epic"),                    # goggles + katana
    ("Sporge the Ember", 6, 6, 6, None,
     "grok-66da6221-544e-4938-8ba0-a745b0ce1b35.jpg", "legendary"),     # armored blaze
    ("Golden Paladin", 6, 5, 5, _rev("reveal_buff_here_others", 3),
     "grok-e49eddca-704d-4946-9538-cbfed9b8fe2f.jpg", "legendary"),     # flaming sword

    # --- second "Smudgies/Captainz" drop ---
    ("Dual Gunner", 4, 5, 3, None,
     "grok-87543e07-f461-4762-8da4-a5b5b7d8b169.jpg", "rare"),          # two pistols
    ("Arcane Tinker", 4, 3, 3, _rev("reveal_draw", 2),
     "grok-500426dd-0220-4f63-a0d5-72e5b30582be.jpg", "epic"),          # steampunk mage
    ("Ink-Squid Mage", 4, 3, 3, _rev("reveal_buff_other_lanes", 3),
     "grok-dc0d8a63-4f91-4975-a46b-564de705af84.jpg", "epic"),          # tentacle wizard
    ("Silent Guardian", 5, 3, 7, None,
     "grok-d4da6b3e-5653-440e-b46f-a46b54df4225.jpg", "epic"),          # medusa wall
    ("Heavy Trooper", 5, 5, 6, None,
     "grok-d5675f62-c05d-4265-9ab5-d287f84896e6.jpg", "epic"),          # armored blaster
    ("Chi Brawler", 5, 6, 5, None,
     "grok-aa496b86-cfc0-47d1-bfb2-20038ab5ac43.png", "legendary"),     # water-fist (4/5)
    ("Tentacle King", 6, 3, 6, _ong("ongoing_ally_here", 2),
     "grok-1a8a6bcf-8a3f-476b-ba1e-7e5f85cbce56.jpg", "legendary"),     # tentacle crown
    ("Rooftop Vigilante", 4, 4, 3, _rev("reveal_debuff_here_enemy", 2),
     "smudgies-vigilante-rooftop.png", "epic"),                         # caped assassin

    # --- third drop (mages, rogues & swashbucklers) ---
    ("Street Tagger", 3, 4, 3, None,
     "smudgies-street-tagger.png", "rare"),                             # neon-city rogue
    ("Emerald Warlock", 4, 3, 4, _rev("reveal_debuff_here_enemy", 2),
     "760777de-e0b7-404d-b89b-beedea1a08ee.png", "epic"),               # green druid-mage
    ("Jungle Ranger", 4, 5, 4, None,
     "smudgies-jungle-ranger.png", "epic"),                             # scimitar hunter
    ("Pirate Captain", 5, 4, 4, _rev("reveal_buff_other_lanes", 3),
     "smudgies-pirate-captain.png", "epic"),                            # spyglass captain
    ("Astral Wizard", 5, 3, 5, _rev("reveal_draw", 2),
     "8bb16c88-1d30-48dd-9c02-2b9e8f943d0b.png", "legendary"),          # star archmage

    # --- fourth drop (ninjas, surfers, monks & riders) ---
    ("Shadow Ninja", 3, 5, 2, None,
     "smudgies-shadow-ninja.png", "epic"),                              # katana assassin
    ("Surfer Sponge", 3, 4, 3, None,
     "smudgies-surfer.png", "rare"),                                    # wave tempo
    ("Blossom Monk", 4, 3, 4, _rev("reveal_buff_here_others", 2),
     "smudgies-blossom-monk.png", "epic"),                              # inspiring monk
    ("Wolf Rider", 4, 5, 4, None,
     "smudgies-wolf-rider.png", "epic"),                                # mounted archer

    # --- fifth drop (20 warriors, mages, monkeys & kaiju) ---
    # cost 1 (fast)
    ("Storm Striker", 1, 2, 1, None, "smudgies-nx-13.png", "rare"),
    ("Monkey Trickster", 1, 2, 1, None,
     "grok-2113f994-1770-447e-88f8-6e39e2e55da9.jpg", "rare"),
    ("Cosmic Ninja", 1, 2, 1, None, "smudgies-nx-03.png", "rare"),
    # cost 2
    ("Frost Monk", 2, 2, 3, _rev("reveal_buff_here_others", 1), "smudgies-nx-02.png", "rare"),
    ("Parasol Kunoichi", 2, 3, 2, None, "smudgies-nx-14.png", "epic"),
    ("One-Eyed Mercenary", 2, 3, 2, None, "smudgies-nx-08.png", "rare"),
    ("Staff Master", 2, 2, 3, None, "smudgies-nx-11.png", "rare"),
    ("Molten Knight", 2, 3, 2, None, "smudgies-nx-09.png", "rare"),
    # cost 3
    ("Oni Berserker", 3, 5, 2, None, "smudgies-nx-07.png", "legendary"),  # glass cannon
    ("Storm Caller", 3, 3, 2, _rev("reveal_debuff_here_enemy", 2), "smudgies-nx-17.png", "epic"),
    ("Jade Staff Monk", 3, 3, 3, None,
     "grok-d49cda03-912f-492f-852b-56a0c02ebccc.jpg", "epic"),
    # cost 4
    ("Cinder Knight", 4, 5, 4, None, "smudgies-nx-05.png", "epic"),
    ("Silver Corsair", 4, 4, 4, None, "smudgies-nx-12.png", "epic"),
    ("Arcane Adept", 4, 3, 4, _rev("reveal_draw", 1), "smudgies-nx-16.png", "epic"),
    ("Horned Berserker", 4, 5, 4, None,
     "grok-6ef64159-02b2-4d86-a992-912c36e7a3cd.jpg", "epic"),
    # cost 5
    ("Kung-Fu Master", 5, 6, 5, None, "smudgies-nx-01.png", "legendary"),
    ("Gilded Commander", 5, 4, 5, _rev("reveal_buff_other_lanes", 2), "smudgies-nx-04.png", "epic"),
    ("Monkey Sage", 5, 5, 6, None, "smudgies-nx-10.png", "legendary"),
    ("Void Sorcerer", 5, 4, 4, _rev("reveal_debuff_here_enemy", 3), "smudgies-nx-15.png", "epic"),
    # cost 6
    ("Ember Warlord", 6, 6, 7, None, "smudgies-nx-06.png", "legendary"),
    ("Lava Kaiju", 6, 7, 6, None,
     "grok-f1f2a7f9-ccc9-4146-abab-e1cff0ec39f3.jpg", "legendary"),
    ("Abyssal Mage", 6, 4, 6, _ong("ongoing_ally_here", 2), "smudgies-nx-18.png", "epic"),
    # sixth drop — Sponge mascots
    ("Sponge, the Wayfarer", 2, 2, 3, _rev("reveal_buff_here_others", 1),
     "smudgies-sponge-woodland.png", "rare"),
    ("Sponge, Sakura Blade", 3, 4, 1, _rev("reveal_debuff_here_enemy", 2),
     "smudgies-sponge-sakura-ninja.png", "epic"),
    ("Sponge, Forest Ranger", 3, 3, 2, _rev("reveal_draw", 1),
     "smudgies-sponge-archer.png", "rare"),
    ("Sponge, Hover Scout", 4, 5, 3, None,
     "smudgies-sponge-hoverboard.png", "epic"),          # fast glass cannon
    ("Sponge, Tide Warden", 5, 4, 6, _rev("reveal_buff_here_others", 2),
     "smudgies-sponge-tide-warden.png", "legendary"),    # trident lane commander
]


def _perk_cost(ab):
    """Stat-point price of a perk, subtracted from the 2*cost+1 budget.

    Prices reflect expected value in a 3-lane, 2-slots-per-side game:
      buff_self n           -> n    (literally n stats, delivered at reveal)
      draw n                -> n+1  (a fresh card is worth a bit over a stat/card)
      buff_here_others n    -> n-1  (at most ONE other slot here, and it must
                                     already be revealed — heavily conditional)
      debuff_here_enemy n   -> n    (up to 2 targets if revealed; can kill)
      buff_other_lanes n    -> n    (up to 4 targets, typically ~1 revealed)
      ongoing_ally_here n   -> n    (continuous +n to the one neighbor slot)
      ongoing_per_ally_here n -> n  (self-buffing version of the same)
    """
    if not ab:
        return 0
    t, n = ab["type"], ab["amount"]
    return {
        "reveal_buff_self": n,
        "reveal_draw": n + 1,
        "reveal_buff_here_others": max(0, n - 1),
        "reveal_debuff_here_enemy": n,
        "reveal_buff_other_lanes": n,
        "ongoing_ally_here": n,
        "ongoing_per_ally_here": n,
    }[t]


def _check_pool(pool):
    """The lane pool proves itself on every build, like the combat pool:
    stats plus the perk's price must fit inside the 2*cost+1 budget."""
    names = set()
    for c in pool:
        budget = 2 * c.cost + 1
        spent = c.attack + c.power + _perk_cost(c.ability)
        assert spent <= budget, (
            f"{c.name}: {c.attack}/{c.power} + perk {_perk_cost(c.ability)} "
            f"= {spent} exceeds budget {budget} (cost {c.cost})")
        assert 1 <= c.cost <= 6 and c.attack >= 1 and c.power >= 1, c.name
        assert c.name not in names, f"duplicate name: {c.name}"
        names.add(c.name)


def build_pool():
    pool = []
    for i, (name, cost, attack, power, ab, art, rarity) in enumerate(_POOL_SPEC):
        pool.append(LaneCard(i, name, cost, attack, power, ab,
                             (ART + art) if art else None, rarity))
    _check_pool(pool)
    return pool


# deck curve: how many cards of each cost a 16-card deck runs (for 9 rounds)
_CURVE = {1: 1, 2: 4, 3: 4, 4: 3, 5: 2, 6: 2}


_RARITY_W = {"common": 0, "rare": 1, "epic": 2, "legendary": 3}


def _card_strength(c):
    s = c.attack + c.power + 2 * _RARITY_W[c.rarity]
    if c.ability:
        s += 2
    return s


def build_deck(pool, rng, bias=0):
    """bias 0 = random; 1 = prefer stronger cards; 2 = greedily pick the best."""
    by_cost = {}
    for c in pool:
        by_cost.setdefault(c.cost, []).append(c)
    deck = []
    for cost, n in _CURVE.items():
        cands = by_cost.get(cost, [])[:]
        rng.shuffle(cands)
        if bias:
            # sort by strength; bias 2 takes the very best, bias 1 keeps some spread
            cands.sort(key=_card_strength, reverse=True)
            if bias == 1:
                cands = cands[: max(n, len(cands) - n)]  # top slice, still some variety
                rng.shuffle(cands)
        deck.extend(cands[:n])
    if len(deck) < DECK_SIZE:
        rest = [c for c in pool if c not in deck]
        rest.sort(key=_card_strength, reverse=True) if bias else rng.shuffle(rest)
        deck.extend(rest[:DECK_SIZE - len(deck)])
    return deck[:DECK_SIZE]


# --------------------------------------------------------------------------
# Campaign: levels unlock in order; difficulty scales via bot skill, the
# opponent's deck bias, and (for bosses) energy / opening-card handicaps.
# Each level also carries arena MODIFIERS: named lane rules drawn at match
# start and pinned to random lanes, so the same deck faces a different
# board puzzle every run. Modifiers apply to BOTH sides equally.
# --------------------------------------------------------------------------
MODS = {
    "volcanic":  dict(name="Volcanic",  icon="🌋",
                      desc="Cards here take 1 damage after each round's combat."),
    "sanctum":   dict(name="Sanctum",   icon="🕊️",
                      desc="No combat here — a pure Power race."),
    "tailwind":  dict(name="Tailwind",  icon="🌀",
                      desc="Cards cost 1 less Energy to play here (min 1)."),
    "golden":    dict(name="Golden",    icon="🏆",
                      desc="Leading this panel banks 2 points instead of 1."),
    "deadzone":  dict(name="Dead Zone", icon="🚫",
                      desc="On Reveal abilities don't trigger here."),
    "overgrown": dict(name="Overgrown", icon="🌿",
                      desc="Cards here have +1 Power while in this panel."),
}

# mods = this level's themed pool of possible lane rules; nmods = how many
# are drawn (each to a distinct random lane) when a match starts.
LEVELS = [
    dict(name="Tide Pool Tutorial", sub="A gentle warm-up.",     skill=0, bias=0, energy=0, opening=0,
         mods=(), nmods=0),
    dict(name="Back-Alley Brawl",   sub="Street scrappers.",      skill=1, bias=0, energy=0, opening=0,
         mods=("tailwind",), nmods=1),
    dict(name="The Duelist's Court", sub="Sharper blades.",       skill=1, bias=1, energy=0, opening=0,
         mods=("sanctum", "tailwind"), nmods=1),
    dict(name="Steampunk Foundry",  sub="Clockwork tactics.",     skill=2, bias=1, energy=0, opening=0,
         mods=("volcanic", "tailwind"), nmods=1),
    dict(name="Neon Underground",   sub="They read your moves.",  skill=2, bias=2, energy=0, opening=0,
         mods=("deadzone", "tailwind", "golden"), nmods=1),
    dict(name="Jungle Gauntlet",    sub="Apex predators.",        skill=2, bias=2, energy=0, opening=1,
         mods=("overgrown", "sanctum", "volcanic"), nmods=2),
    dict(name="Pirate Armada",      sub="Outgunned.",             skill=3, bias=2, energy=0, opening=0,
         mods=("golden", "volcanic", "tailwind"), nmods=2),
    dict(name="The Ink Court",      sub="Masters of the board.",  skill=3, bias=2, energy=0, opening=1,
         mods=("deadzone", "sanctum", "golden"), nmods=2),
    dict(name="Ember Throne",       sub="A blazing gauntlet.",    skill=3, bias=2, energy=0, opening=1,
         mods=("volcanic", "golden", "deadzone"), nmods=2),
    dict(name="Kraken's Abyss",     sub="The final boss.",        skill=3, bias=2, energy=0, opening=2,
         mods=("sanctum", "volcanic", "deadzone", "golden", "overgrown"), nmods=3),
]


def _difficulty_label(cfg):
    score = cfg["skill"] + cfg["bias"] + cfg["energy"] + cfg["opening"]
    if score <= 1:
        return "Easy"
    if score <= 3:
        return "Normal"
    if score <= 5:
        return "Hard"
    if score <= 7:
        return "Very Hard"
    return "Boss"


def levels_meta():
    return [{"id": i, "name": L["name"], "sub": L["sub"],
             "difficulty": _difficulty_label(L),
             "mods": [{"key": k, **MODS[k]} for k in L["mods"]]}
            for i, L in enumerate(LEVELS)]


# --------------------------------------------------------------------------
# Card leveling (the grind). Milestones instead of a flat stat treadmill:
#   L2: +1 Power
#   L3: +1 Attack OR +1 Power — the player's choice (defaults to Power)
#   L4: perk amount +1 (cards with no perk get +1 Power instead)
#   L5: +1 Attack and +1 Power
# --------------------------------------------------------------------------
LEVEL_CAP = 5


def level_bonus(level, choice=None, has_perk=False):
    level = max(1, min(LEVEL_CAP, int(level)))
    atk = pw = perk = 0
    if level >= 2:
        pw += 1
    if level >= 3:
        if choice == "attack":
            atk += 1
        else:
            pw += 1
    if level >= 4:
        if has_perk:
            perk += 1
        else:
            pw += 1
    if level >= 5:
        atk += 1
        pw += 1
    return {"attack": atk, "power": pw, "perk": perk}


def card_at_level(card, level, choice=None):
    from dataclasses import replace
    has_perk = bool(card.ability and "amount" in card.ability)
    b = level_bonus(level, choice, has_perk)
    if not b["attack"] and not b["power"] and not b["perk"]:
        return card
    ability = card.ability
    if b["perk"] and ability:
        ability = {**ability, "amount": ability["amount"] + b["perk"]}
    return replace(card, attack=card.attack + b["attack"],
                   power=card.power + b["power"], ability=ability)


def pool_meta():
    """All cards (base stats) for the library / client deck-builder.

    textPlus is the perk text at the L4 milestone (amount +1) so the client
    can show leveled ability text without re-implementing _text."""
    return [{"id": c.id, "name": c.name, "cost": c.cost, "attack": c.attack,
             "power": c.power, "text": c.text, "rarity": c.rarity, "art": c.art,
             "textPlus": (_text({**c.ability, "amount": c.ability["amount"] + 1})
                          if c.ability else None)}
            for c in build_pool()]


class Placed:
    """A card on the board."""
    __slots__ = ("card", "owner", "bonus", "revealed", "uid")

    def __init__(self, card, owner, uid):
        self.card = card
        self.owner = owner
        self.uid = uid          # stable id so the client can animate this card
        self.bonus = 0          # permanent adjustment from On Reveal perks
        self.revealed = False


class LaneGame:
    def __init__(self, rng=None):
        self.rng = rng or random.Random()
        self.decks = [[], []]
        self.hands = [[], []]
        # lanes[i] = {0:[Placed...], 1:[Placed...]}
        self.lanes = [{0: [], 1: []} for _ in range(LANES)]
        self.turn = 0
        self.energy = 0                    # human's remaining energy this turn
        self.staged = {0: [], 1: []}       # Placed added this turn, per owner
        self._uid = 0
        self.points = {0: 0, 1: 0}         # cumulative lane-points (round scoring)
        self.log = []
        self.winner = None                 # 'human' | 'bot' | 'draw' | None
        self.over = False
        self.message = ""
        self.level = 0
        self.bot_skill = 1
        self.bot_energy_bonus = 0
        self.lane_mods = [None] * LANES    # arena modifier key (or None) per lane
        self._played = set()               # your card ids that hit the board
        self._kills = {}                   # your card id -> enemy cards it felled
        self._survived = []                # your card ids alive at match end
        self._deaths = 0                   # your cards lost (any cause)
        self._sweeps = 0                   # rounds you led all three lanes
        self._legacy_stats = False         # token predates stat tracking: the
                                           # counts are incomplete, don't report

    # -- setup --------------------------------------------------------------
    def new_game(self, level=0, deck=None):
        cfg = LEVELS[level] if 0 <= level < len(LEVELS) else LEVELS[0]
        self.level = level if 0 <= level < len(LEVELS) else 0
        self.bot_skill = cfg["skill"]
        self.bot_energy_bonus = cfg["energy"]
        self.lane_mods = self._draw_mods(cfg)
        self._played = set()
        self._kills = {}
        self._survived = []
        self._deaths = 0
        self._sweeps = 0
        self._legacy_stats = False
        pool = build_pool()
        # your deck: leveled cards from your collection (if provided), else random
        player = self._build_player_deck(pool, deck)
        self.decks = [player, build_deck(pool, self.rng, bias=cfg["bias"])]
        for d in self.decks:
            self.rng.shuffle(d)
        self.hands = [[], []]
        self.lanes = [{0: [], 1: []} for _ in range(LANES)]
        self.turn = 0
        self.staged = {0: [], 1: []}
        self._uid = 0
        self.points = {0: 0, 1: 0}
        self.log = [f"Level {level + 1}: {cfg['name']} — {MAX_TURNS} rounds. "
                    f"Lead a panel each round to score. Most points wins!"]
        for li, key in enumerate(self.lane_mods):
            if key:
                m = MODS[key]
                self.log.append(f"Panel {li + 1} is {m['name']} {m['icon']} — "
                                f"{m['desc']}")
        self.winner = None
        self.over = False
        self._draw(0, OPENING_DRAW)
        self._draw(1, OPENING_DRAW + cfg["opening"])
        self._start_turn()
        return self.state()

    def _draw_mods(self, cfg):
        """Draw this level's arena modifiers onto distinct random lanes."""
        mods = [None] * LANES
        keys = [k for k in cfg.get("mods", ()) if k in MODS]
        n = min(cfg.get("nmods", 0), len(keys), LANES)
        if n:
            for key, li in zip(self.rng.sample(keys, n),
                               self.rng.sample(range(LANES), n)):
                mods[li] = key
        return mods

    def play_cost(self, card, lane):
        """Energy to place `card` in `lane` (Tailwind discounts by 1, min 1)."""
        if self.lane_mods[lane] == "tailwind":
            return max(1, card.cost - 1)
        return card.cost

    def _build_player_deck(self, pool, spec):
        """spec = [{id, level, choice}, ...] from the player's collection.

        The collection owns each card once, so duplicate ids in the spec are
        dropped (a hand-crafted request can't run 16 copies of a legendary).
        """
        if not spec:
            return build_deck(pool, self.rng, bias=0)
        by_id = {c.id: c for c in pool}
        deck, seen = [], set()
        for entry in spec:
            if not isinstance(entry, dict):
                continue
            cid = entry.get("id")
            c = by_id.get(cid)
            if c is None or cid in seen:
                continue
            seen.add(cid)
            choice = entry.get("choice")
            if choice not in ("attack", "power"):
                choice = None
            deck.append(card_at_level(c, entry.get("level", 1), choice))
        if len(deck) < 8:                       # safety: pad a too-small deck
            deck += build_deck(pool, self.rng, bias=0)
        return deck[:DECK_SIZE]

    def _draw(self, owner, n):
        # n can arrive via a client-tampered game token (a forged reveal_draw
        # amount) — clamp it, or a huge value spins this loop for seconds of
        # CPU even though every iteration past HAND_CAP is a no-op.
        for _ in range(max(0, min(int(n), HAND_CAP))):
            if self.decks[owner] and len(self.hands[owner]) < HAND_CAP:
                self.hands[owner].append(self.decks[owner].pop())

    def _start_turn(self):
        self.turn += 1
        self.energy = self.turn
        self.staged = {0: [], 1: []}
        self._draw(0, 1)
        self._draw(1, 1)
        self.message = f"Turn {self.turn}: you have {self.energy} Energy."

    # -- scoring ------------------------------------------------------------
    def _lane_eff(self, li, bot_view=False):
        """Return {owner: [effective power per card]} including Ongoing perks.

        bot_view=True is the bot's information set: your staged-but-unrevealed
        cards are invisible (the bot still sees its own commitments). Bot
        decision code must use this, or it peeks at your hidden picks.
        """
        lane = self.lanes[li]
        grow = 1 if self.lane_mods[li] == "overgrown" else 0
        out = {}
        for owner in (0, 1):
            cards = lane[owner]
            if bot_view and owner == 0:
                cards = [c for c in cards if c.revealed]
            eff = [c.card.power + c.bonus + grow for c in cards]
            for i, src in enumerate(cards):
                ab = src.card.ability
                if not ab or ab.get("trigger") != "ongoing" or not src.revealed:
                    continue
                t, amt = ab["type"], ab["amount"]
                if t == "ongoing_ally_here":
                    for j in range(len(cards)):
                        if j != i:
                            eff[j] += amt
                elif t == "ongoing_per_ally_here":
                    eff[i] += amt * (len(cards) - 1)
            out[owner] = [max(0, v) for v in eff]
        return out

    def _lane_totals(self, li, bot_view=False):
        e = self._lane_eff(li, bot_view=bot_view)
        return sum(e[0]), sum(e[1])

    # -- placement ----------------------------------------------------------
    def _space(self, owner, li):
        return len(self.lanes[li][owner]) < SLOTS_PER_LANE

    def _place(self, owner, card, li):
        pc = Placed(card, owner, self._uid)
        self._uid += 1
        self.lanes[li][owner].append(pc)
        self.staged[owner].append((pc, li))
        return pc

    def stage(self, hand_index, lane):
        if self.over:
            return self._err("The match is over.")
        if not (0 <= lane < LANES):
            return self._err("No such panel.")
        if not isinstance(hand_index, int) or not (0 <= hand_index < len(self.hands[0])):
            return self._err("No such card.")
        card = self.hands[0][hand_index]
        cost = self.play_cost(card, lane)
        if cost > self.energy:
            return self._err(f"Not enough Energy ({cost} needed, {self.energy} left).")
        if not self._space(0, lane):
            return self._err(f"That panel is full on your side ({SLOTS_PER_LANE}).")
        self.hands[0].pop(hand_index)
        self.energy -= cost
        self._place(0, card, lane)
        self.message = (f"Staged {card.name} in Panel {lane + 1} — "
                        f"hidden from the rival until you Reveal.")
        return self.state()

    def reset_turn(self):
        """Return everything you staged this turn to your hand."""
        for pc, li in reversed(self.staged[0]):
            self.lanes[li][0].remove(pc)
            self.hands[0].append(pc.card)
            self.energy += self.play_cost(pc.card, li)   # refund what was paid
        self.staged[0] = []
        self.message = "Cleared your staged cards."
        return self.state()

    # -- bot ----------------------------------------------------------------
    def _bot_play(self):
        energy = self.turn + self.bot_energy_bonus
        skill = self.bot_skill
        while True:
            # evaluate every affordable (card, lane) — costs vary per lane
            # under Tailwind, so affordability is a property of the pair
            choice, best = None, None
            for card in self.hands[1]:
                for li in range(LANES):
                    if not self._space(1, li):
                        continue
                    if self.play_cost(card, li) > energy:
                        continue
                    v = (self._placement_value(card, li, skill) if skill >= 2
                         else self._simple_value(card, li, skill))
                    if best is None or v > best:
                        best, choice = v, (card, li)
            if not choice:
                break
            card, lane = choice
            self.hands[1].remove(card)
            energy -= self.play_cost(card, lane)
            self._place(1, card, lane)

    def _simple_value(self, card, li, skill):
        """Low-skill: strongest card first, into the lane it's most behind in
        (skill 0 just fills the emptiest lane)."""
        if skill == 0:
            lane_score = -len(self.lanes[li][1])
        else:
            h, b = self._lane_totals(li, bot_view=True)
            lane_score = (h - b) + card.power * 0.1 - len(self.lanes[li][1]) * 0.5
        return card.power * 100 + lane_score

    def _placement_value(self, card, li, skill):
        """Higher-skill heuristic: flip/secure lanes, don't waste on lost ones,
        and (skill 3) weight Attack that can kill an enemy card here."""
        h, b = self._lane_totals(li, bot_view=True)
        nb = b + card.power
        val = card.power
        if b <= h and nb > h:
            val += 8 + (nb - h)             # flips a lane the bot was losing
        elif b > h:
            val -= min(b - h, 6) * 0.6       # already winning -> diminishing returns
        space = SLOTS_PER_LANE - len(self.lanes[li][1])
        if nb + space * 3 < h:
            val -= 5                         # realistically can't catch up here
        visible_foes = [c for c in self.lanes[li][0] if c.revealed]
        if skill >= 3 and visible_foes:
            weakest = min(c.card.power + c.bonus for c in visible_foes)
            if card.attack >= weakest:
                val += 3 + card.attack * 0.4  # can kill an enemy scorer
        val -= len(self.lanes[li][1]) * 0.4   # slight spread preference
        mod = self.lane_mods[li]
        if mod == "golden":
            val += 2.5                        # double points: worth contesting
        elif mod == "volcanic" and card.power <= 2:
            val -= 3                          # burns out in a couple of rounds
        elif mod == "sanctum":
            val -= card.attack * 0.3          # attack is wasted here
        elif mod == "deadzone" and (card.ability or {}).get("trigger") == "reveal":
            val -= 2                          # the perk won't fire
        elif mod == "tailwind" and card.cost > 1:
            val += 0.8                        # discount stretches the turn's energy
        return val

    # -- reveal (produces an animation timeline) ----------------------------
    def _snapshot(self):
        """Effective power of every 'active' card, keyed by uid, + lane totals.

        Your cards always count (you've committed them); the opponent's count
        only once revealed. This keeps the on-screen numbers continuous as the
        opponent's cards flip in one by one.
        """
        powers, lanes = {}, []
        for li in range(LANES):
            grow = 1 if self.lane_mods[li] == "overgrown" else 0
            tot = {0: 0, 1: 0}
            for owner in (0, 1):
                cards = (self.lanes[li][0] if owner == 0
                         else [c for c in self.lanes[li][1] if c.revealed])
                eff = [c.card.power + c.bonus + grow for c in cards]
                for i, src in enumerate(cards):
                    ab = src.card.ability
                    if not ab or ab.get("trigger") != "ongoing":
                        continue
                    t, amt = ab["type"], ab["amount"]
                    if t == "ongoing_ally_here":
                        for j in range(len(cards)):
                            if j != i:
                                eff[j] += amt
                    elif t == "ongoing_per_ally_here":
                        eff[i] += amt * (len(cards) - 1)
                for i, c in enumerate(cards):
                    v = max(0, eff[i])
                    powers[c.uid] = v
                    tot[owner] += v
            lanes.append({"you": tot[0], "foe": tot[1]})
        return {"powers": powers, "lanes": lanes}

    def _reveal_effect(self, pc, li):
        """Apply pc's perk. Returns [{uid, delta}] hits for the client to show.

        On-Reveal effects mutate `bonus` permanently; Ongoing effects return
        a one-time visual (the snapshot reflects the real, continuous value).
        """
        ab = pc.card.ability
        if not ab:
            return []
        if ab["trigger"] == "reveal" and self.lane_mods[li] == "deadzone":
            return []                       # Dead Zone: On Reveal perks fizzle
        owner, t, amt = pc.owner, ab["type"], ab["amount"]
        lane = self.lanes[li]
        hits = []
        if ab["trigger"] == "reveal":
            if t == "reveal_buff_here_others":
                for c in lane[owner]:
                    if c is not pc and c.revealed:
                        c.bonus += amt
                        hits.append({"uid": c.uid, "delta": amt})
            elif t == "reveal_debuff_here_enemy":
                for c in lane[1 - owner]:
                    if c.revealed:
                        c.bonus -= amt
                        hits.append({"uid": c.uid, "delta": -amt})
            elif t == "reveal_buff_other_lanes":
                for lj in range(LANES):
                    if lj != li:
                        for c in self.lanes[lj][owner]:
                            if c.revealed:
                                c.bonus += amt
                                hits.append({"uid": c.uid, "delta": amt})
            elif t == "reveal_buff_self":
                pc.bonus += amt
                hits.append({"uid": pc.uid, "delta": amt})
            elif t == "reveal_draw":
                self._draw(owner, amt)
        elif ab["trigger"] == "ongoing":
            if t == "ongoing_ally_here":
                for c in lane[owner]:
                    if c is not pc and c.revealed:
                        hits.append({"uid": c.uid, "delta": amt})
            elif t == "ongoing_per_ally_here":
                n = len([c for c in lane[owner] if c.revealed]) - 1
                if n > 0:
                    hits.append({"uid": pc.uid, "delta": amt * n})
        return hits

    def _payload(self, pc):
        return {
            "uid": pc.uid, "owner": pc.owner,
            "name": pc.card.name, "cost": pc.card.cost,
            "attack": pc.card.attack, "base": pc.card.power,
            "art": pc.card.art, "text": pc.card.text, "rarity": pc.card.rarity,
        }

    def _combat_events(self):
        """Opposing cards in the same slot trade damage each round; 0 => death.
        Sanctum lanes skip combat; Volcanic lanes burn the survivors after."""
        events = []
        for li in range(LANES):
            mod = self.lane_mods[li]
            grow = 1 if mod == "overgrown" else 0

            def alive(pc):
                # Overgrown's +1 counts as health too: power doubles as HP,
                # so a card the UI shows at 1 must not die at intrinsic 0.
                return pc.card.power + pc.bonus + grow > 0

            you, foe = self.lanes[li][0], self.lanes[li][1]
            if mod != "sanctum":
                for i in range(max(len(you), len(foe))):
                    a = you[i] if i < len(you) else None
                    b = foe[i] if i < len(foe) else None
                    if a and b:                   # a duel: simultaneous strike
                        was_alive = alive(b)      # corpses (perk kills waiting
                        a.bonus -= b.card.attack  # for the sweep) credit no one
                        b.bonus -= a.card.attack
                        if was_alive and not alive(b):
                            self._kills[a.card.id] = \
                                self._kills.get(a.card.id, 0) + 1
                        events.append({"kind": "attack", "lane": li, "hits": [
                            {"uid": a.uid, "delta": -b.card.attack},
                            {"uid": b.uid, "delta": -a.card.attack}]})
                        events.append({"kind": "snapshot", **self._snapshot()})
            if mod == "volcanic":
                hits = []
                for c in you + foe:
                    if not alive(c):
                        continue                  # the dead don't burn again
                    c.bonus -= 1
                    hits.append({"uid": c.uid, "delta": -1})
                if hits:
                    events.append({"kind": "mod", "mod": "volcanic", "lane": li,
                                   "hits": hits})
                    events.append({"kind": "snapshot", **self._snapshot()})
            dead = [c for side in (you, foe) for c in side if not alive(c)]
            if dead:
                self._deaths += sum(1 for c in you if not alive(c))
                for c in dead:
                    events.append({"kind": "death", "uid": c.uid})
                self.lanes[li][0] = [c for c in you if alive(c)]
                self.lanes[li][1] = [c for c in foe if alive(c)]
                events.append({"kind": "snapshot", **self._snapshot()})
        return events

    def end_turn(self):
        if self.over:
            return self.state()
        self._bot_play()
        events = []
        # Reveal order: your staged first, then the bot's, each in play order.
        order = list(self.staged[0]) + list(self.staged[1])
        for pc, li in order:
            pc.revealed = True
            if pc.owner == 0:
                self._played.add(pc.card.id)     # committed to the board -> full XP
            events.append({"kind": "reveal", "uid": pc.uid, "owner": pc.owner,
                           "lane": li, "card": self._payload(pc)})
            hits = self._reveal_effect(pc, li)
            if hits:
                events.append({"kind": "effect", "uid": pc.uid, "lane": li,
                               "text": pc.card.text, "hits": hits})
            events.append({"kind": "snapshot", **self._snapshot()})
        # -- combat: opposing cards attack, take damage, and can die ---------
        events.extend(self._combat_events())
        # -- round scoring: a point per led lane (Golden lanes pay double) ---
        led = {0: 0, 1: 0}
        for li in range(LANES):
            h, b = self._lane_totals(li)
            pts = 2 if self.lane_mods[li] == "golden" else 1
            side = "you" if h > b else "foe" if b > h else "tie"
            if side == "you":
                self.points[0] += pts
                led[0] += 1
            elif side == "foe":
                self.points[1] += pts
                led[1] += 1
            events.append({"kind": "score", "lane": li, "side": side, "pts": pts,
                           "you": self.points[0], "foe": self.points[1]})
        if led[0] == LANES:
            self._sweeps += 1              # a full-board round (star objective)
        self._narrate_turn(led)
        self.staged = {0: [], 1: []}
        if self.turn >= MAX_TURNS:
            self._finish()
        else:
            self._start_turn()
        st = self.state()
        st["events"] = events
        return st

    def _narrate_turn(self, led):
        who = {0: "You", 1: "Opponent"}
        for owner in (0, 1):
            for pc, li in self.staged[owner]:
                note = f" ({pc.card.text})" if pc.card.ability else ""
                self.log.append(f"R{self.turn}: {who[owner]} played "
                                f"{pc.card.name} in Panel {li + 1}.{note}")
        self.log.append(f"R{self.turn}: panels led — you {led[0]}, opp {led[1]}."
                        f"  Score {self.points[0]}–{self.points[1]}.")

    def _finish(self):
        self.over = True
        self._survived = sorted({pc.card.id for li in range(LANES)
                                 for pc in self.lanes[li][0]})
        p0, p1 = self.points[0], self.points[1]
        totals = {0: 0, 1: 0}
        for li in range(LANES):
            h, b = self._lane_totals(li)
            totals[0] += h
            totals[1] += b
        if p0 > p1:
            self.winner = "human"
        elif p1 > p0:
            self.winner = "bot"
        elif totals[0] > totals[1]:      # tie on points -> total Power breaks it
            self.winner = "human"
        elif totals[1] > totals[0]:
            self.winner = "bot"
        else:
            self.winner = "draw"
        self.log.append(f"Final score {p0}–{p1} "
                        f"(total power {totals[0]}–{totals[1]}).")

    # -- serialization ------------------------------------------------------
    def _err(self, msg):
        self.message = msg
        st = self.state()
        st["error"] = msg
        return st

    def _card_view(self, pc, eff, hide):
        if hide:
            return {"hidden": True}
        return {
            "uid": pc.uid,
            "name": pc.card.name,
            "cost": pc.card.cost,
            "attack": pc.card.attack,
            "power": eff,
            "base": pc.card.power,
            "bonus": eff - pc.card.power,
            "text": pc.card.text,
            "art": pc.card.art,
            "rarity": pc.card.rarity,
            "revealed": pc.revealed,
        }

    def _hand_view(self, c, i):
        # playable if it fits the budget in ANY open lane (Tailwind can make
        # a card affordable there that the raw cost says isn't)
        playable = not self.over and any(
            self._space(0, li) and self.play_cost(c, li) <= self.energy
            for li in range(LANES))
        return {
            "index": i,
            "name": c.name,
            "cost": c.cost,
            "attack": c.attack,
            "power": c.power,
            "text": c.text,
            "art": c.art,
            "rarity": c.rarity,
            "playable": playable,
        }

    def state(self):
        lanes = []
        for li in range(LANES):
            eff = self._lane_eff(li)
            hcards, bcards = self.lanes[li][0], self.lanes[li][1]
            h_total, b_total = sum(eff[0]), sum(eff[1])
            mk = self.lane_mods[li]
            lanes.append({
                "index": li,
                "mod": {"key": mk, **MODS[mk]} if mk else None,
                # your cards always visible; opponent's hidden until revealed
                "you": [self._card_view(pc, eff[0][j], False)
                        for j, pc in enumerate(hcards)],
                "foe": [self._card_view(pc, eff[1][j], not pc.revealed)
                        for j, pc in enumerate(bcards)],
                "youPower": h_total,
                "foePower": b_total,
                "youSpace": SLOTS_PER_LANE - len(hcards),
                "leader": "you" if h_total > b_total else
                          "foe" if b_total > h_total else "tie",
            })
        # provisional lane record for the header
        wins = {"you": 0, "foe": 0}
        for L in lanes:
            if L["leader"] == "you":
                wins["you"] += 1
            elif L["leader"] == "foe":
                wins["foe"] += 1
        st = {
            "started": True,
            "turn": self.turn,
            "maxTurns": MAX_TURNS,
            "slotsPerLane": SLOTS_PER_LANE,
            "level": self.level,
            "levelName": LEVELS[self.level]["name"],
            "energy": self.energy,
            "energyMax": self.turn,
            "over": self.over,
            "winner": self.winner,
            "message": self.message,
            "laneWins": wins,                       # current per-lane leaders
            "score": {"you": self.points[0], "foe": self.points[1]},  # banked points
            "you": {
                "hand": [self._hand_view(c, i) for i, c in enumerate(self.hands[0])],
                "deck": len(self.decks[0]),
            },
            "foe": {
                "handCount": len(self.hands[1]),
                "deck": len(self.decks[1]),
            },
            "lanes": lanes,
            "log": self.log[-18:],
        }
        if self.over and not self._legacy_stats:
            # per-card performance so the client can award earned XP
            st["matchStats"] = {
                "played": sorted(self._played),
                "kills": {str(k): v for k, v in self._kills.items()},
                "survived": list(self._survived),
                "deaths": self._deaths,
                "sweeps": self._sweeps,
            }
        return st

    # -- stateless serialization (for serverless hosts, e.g. Vercel) ---------
    # The client holds the whole game as an opaque token and sends it back on
    # every request; the server rebuilds, applies one action, and returns the
    # new token. This removes the reliance on in-process global state.
    def serialize(self):
        rs = self.rng.getstate()                      # (version, tuple, gauss)
        d = {
            "rng": [rs[0], list(rs[1]), rs[2]],
            "decks": [[_card_dict(c) for c in d] for d in self.decks],
            "hands": [[_card_dict(c) for c in h] for h in self.hands],
            "lanes": [[[_placed_dict(pc) for pc in lane[0]],
                       [_placed_dict(pc) for pc in lane[1]]]
                      for lane in self.lanes],
            "staged": [[{"uid": pc.uid, "lane": li} for pc, li in self.staged[0]],
                       [{"uid": pc.uid, "lane": li} for pc, li in self.staged[1]]],
            "turn": self.turn,
            "energy": self.energy,
            "uid": self._uid,
            "points": [self.points[0], self.points[1]],
            "log": self.log,
            "winner": self.winner,
            "over": self.over,
            "message": self.message,
            "level": self.level,
            "botSkill": self.bot_skill,
            "botEnergyBonus": self.bot_energy_bonus,
            "laneMods": list(self.lane_mods),
            "played": sorted(self._played),
            "kills": [[k, v] for k, v in self._kills.items()],
            "survived": list(self._survived),
            "deaths": self._deaths,
            "sweeps": self._sweeps,
        }
        if self._legacy_stats:
            # keep a pre-stats token honest across round trips: dropping the
            # keys re-marks it legacy on the next from_serialized
            for k in ("played", "kills", "survived", "deaths", "sweeps"):
                del d[k]
        return d

    @classmethod
    def from_serialized(cls, data):
        g = cls()
        rs = data["rng"]
        g.rng.setstate((rs[0], tuple(rs[1]), rs[2]))
        g.decks = [[_card_from(c) for c in d] for d in data["decks"]]
        g.hands = [[_card_from(c) for c in h] for h in data["hands"]]
        g.lanes = []
        by_uid = {}
        for lane in data["lanes"]:
            L = {0: [], 1: []}
            for side in (0, 1):
                for pd in lane[side]:
                    pc = Placed(_card_from(pd["card"]), pd["owner"], pd["uid"])
                    pc.bonus = pd["bonus"]
                    pc.revealed = pd["revealed"]
                    L[side].append(pc)
                    by_uid[pc.uid] = pc
            g.lanes.append(L)
        g.staged = {0: [], 1: []}
        for side in (0, 1):
            for s in data["staged"][side]:
                pc = by_uid.get(s["uid"])
                if pc is not None:                    # same object as in lanes
                    g.staged[side].append((pc, s["lane"]))
        g.turn = data["turn"]
        g.energy = data["energy"]
        g._uid = data["uid"]
        g.points = {0: data["points"][0], 1: data["points"][1]}
        g.log = list(data["log"])
        g.winner = data["winner"]
        g.over = data["over"]
        g.message = data["message"]
        g.level = data["level"]
        g.bot_skill = data["botSkill"]
        g.bot_energy_bonus = data["botEnergyBonus"]
        # newer fields default cleanly for tokens minted before they existed
        g.lane_mods = list(data.get("laneMods") or [None] * LANES)
        g._legacy_stats = "played" not in data
        g._played = set(data.get("played") or [])
        g._kills = {int(k): v for k, v in (data.get("kills") or [])}
        g._survived = list(data.get("survived") or [])
        g._deaths = data.get("deaths") or 0
        g._sweeps = data.get("sweeps") or 0
        return g


def _card_dict(c):
    return {"id": c.id, "name": c.name, "cost": c.cost, "attack": c.attack,
            "power": c.power, "ability": c.ability, "art": c.art,
            "rarity": c.rarity}


def _card_from(d):
    return LaneCard(d["id"], d["name"], d["cost"], d["attack"], d["power"],
                    d.get("ability"), d.get("art"), d.get("rarity", "common"))


def _placed_dict(pc):
    return {"uid": pc.uid, "owner": pc.owner, "bonus": pc.bonus,
            "revealed": pc.revealed, "card": _card_dict(pc.card)}


if __name__ == "__main__":
    # quick self-play sanity check, sweeping every campaign level so all
    # arena modifiers and bot skills get exercised
    import collections
    for lvl in range(len(LEVELS)):
        tally = collections.Counter()
        for s in range(30):
            g = LaneGame(random.Random(lvl * 1000 + s))
            g.new_game(level=lvl)
            while not g.over:
                # trivial "human": play the cheapest card into the emptiest lane
                hand = g.hands[0]
                progressed = True
                while progressed:
                    progressed = False
                    for i, c in enumerate(sorted(hand, key=lambda c: c.cost)):
                        if c.cost <= g.energy:
                            idx = g.hands[0].index(c)
                            lane = min(range(LANES), key=lambda li: len(g.lanes[li][0]))
                            if g.lanes[lane][0].__len__() < SLOTS_PER_LANE:
                                g.stage(idx, lane)
                                progressed = True
                                break
                g.end_turn()
            tally[g.winner] += 1
        mods = "+".join(LEVELS[lvl]["mods"]) or "none"
        print(f"L{lvl + 1:<2} {LEVELS[lvl]['name']:<20} "
              f"(mods {mods}): {dict(tally)}")
