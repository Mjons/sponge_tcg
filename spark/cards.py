"""The 100-card SPARK pool.

Units are generated from the stat-to-cost formula so the formula is
SELF-VERIFYING: build_pool() asserts every unit is inside its point budget.

    Stat budget  B = 2*C + 1   (1 point = +1 Attack or +1 Health)
    Keyword/effect costs are subtracted from B before assigning stats.
    Legendaries may spend B + 1 (their only mechanical premium).
    Aggressive (attack-skewed) units pay a -1 "skew tax".

Effects are data (dicts). The engine interprets them; bots read them to
choose targets. Keeping effects as data is what lets 35 spells + ETB
units share one ~40-line resolver instead of 100 special cases.
"""

from dataclasses import dataclass, field
from typing import Optional

# Keyword point costs (subtracted from the stat budget). See README §6.
KEYWORD_COST = {"guard": 1, "rush": 2, "barrier": 2, "drain": 2}
# Minor on-play (ETB) effect costs 2 points of stats.
ETB_COST = 2


@dataclass(frozen=True)
class Card:
    id: int
    name: str
    cost: int
    ctype: str          # "unit" | "spell"
    rarity: str         # common | rare | epic | legendary
    role: str           # aggro | mid | control  (deckbuilding hint)
    atk: int = 0
    health: int = 0
    keywords: tuple = ()
    effects: tuple = ()  # tuple of dict effect-specs
    text: str = ""
    art: Optional[str] = None

    @property
    def is_unit(self):
        return self.ctype == "unit"


# --------------------------------------------------------------------------
# Stat allocation helper
# --------------------------------------------------------------------------
def _split(points, skew=0, allow_zero_atk=False):
    """Split `points` into (atk, health). skew>0 favours attack.

    Non-wall units are guaranteed >=1 attack: a 0-attack unit that isn't a
    deliberate Guard wall is a dead card, so we never generate one.
    """
    points = max(points, 1)
    atk = (points + 1) // 2 + skew
    atk = max(0, min(atk, points))
    health = points - atk
    if health < 1:            # a unit must have >=1 health
        health = 1
        atk = max(0, points - 1)
    if not allow_zero_atk and atk < 1 and points >= 2:
        atk, health = 1, points - 1
    return atk, health


def _budget(cost, legendary=False):
    return 2 * cost + 1 + (1 if legendary else 0)


# --------------------------------------------------------------------------
# Named marquee units, wired to the existing character art.
# (cost, flavor, keywords, effect, name, art, rarity)
# --------------------------------------------------------------------------
ART = "cards/"
MARQUEE = [
    # Legendaries (5) — B+1 premium, splashy but inside the power ceiling.
    dict(cost=8, name="Oni, the Kaiju",     art="smudgies-sponge-01-kaiju-oni.webp",
         keywords=("guard",), skew=-1, legendary=True, role="control",
         text="Guard."),
    dict(cost=8, name="The Crowned Dark",   art="smudgies-sponge-07-darklord-crown.webp",
         keywords=("drain",), skew=0, legendary=True, role="control",
         effects=({"type": "aoe", "amount": 3},),
         text="On play: deal 3 to all enemy units. Drain."),
    dict(cost=7, name="Emperor Parasol",    art="smudgies-sponge-16-emperor-parasol.webp",
         keywords=("barrier",), skew=-1, legendary=True, role="control",
         effects=({"type": "draw", "amount": 2},),
         text="On play: draw 2. Barrier."),
    dict(cost=7, name="The Kraken",         art="smudgies-sponge-13-kraken.webp",
         keywords=("guard",), skew=1, legendary=True, role="control",
         text="Guard."),
    dict(cost=6, name="Ronin of the Fireblade", art="smudgies-sponge-08-ronin-fireblade.webp",
         keywords=("rush", "drain"), skew=1, legendary=True, role="aggro",
         text="Rush. Drain."),
    # Epics / rares with art (11)
    dict(cost=5, name="Ghostrider's Coin",  art="smudgies-sponge-02-ghostrider-coin.webp",
         keywords=("rush",), skew=1, role="aggro", rarity="epic", text="Rush."),
    dict(cost=4, name="Katana Samurai",     art="smudgies-sponge-03-samurai-katana.webp",
         keywords=("barrier",), skew=0, role="mid", rarity="epic", text="Barrier."),
    dict(cost=5, name="Greatsword Knight",  art="smudgies-sponge-04-knight-greatsword.webp",
         keywords=("guard",), skew=0, role="control", rarity="rare", text="Guard."),
    dict(cost=2, name="Teal Swordsman",     art="smudgies-sponge-05-swordsman-teal.webp",
         skew=1, role="aggro", rarity="common", text=""),
    dict(cost=3, name="Revolver Gunslinger", art="smudgies-sponge-06-gunslinger-revolver.webp",
         skew=1, role="aggro", rarity="rare",
         effects=({"type": "damage_flexible", "amount": 2},),
         text="On play: deal 2 to any target."),
    dict(cost=4, name="Barbarian's Club",   art="smudgies-sponge-09-barbarian-club.webp",
         skew=2, role="aggro", rarity="rare", text=""),
    dict(cost=3, name="The Waterbender",    art="smudgies-sponge-10-waterbender.webp",
         skew=-1, role="control", rarity="rare",
         effects=({"type": "heal_face", "amount": 3},),
         text="On play: heal your face 3."),
    dict(cost=2, name="Electric Brawler",   art="smudgies-sponge-11-brawler-electric.webp",
         keywords=("rush",), skew=1, role="aggro", rarity="rare", text="Rush."),
    dict(cost=3, name="Orb Mage",           art="smudgies-sponge-12-mage-orb.webp",
         skew=0, role="mid", rarity="rare",
         effects=({"type": "draw", "amount": 1},),
         text="On play: draw 1."),
    dict(cost=4, name="Gold Streetfighter", art="smudgies-sponge-14-streetfighter-gold.webp",
         keywords=("guard",), skew=-1, role="control", rarity="rare", text="Guard."),
    dict(cost=6, name="Ronin of Purpleflame", art="smudgies-sponge-15-ronin-purpleflame.webp",
         keywords=("drain",), skew=1, role="mid", rarity="epic", text="Drain."),
]


# --------------------------------------------------------------------------
# Generic unit flavors used to fill each cost tier to its target count.
# --------------------------------------------------------------------------
FLAVORS = {
    "vanilla":    dict(kw=(), skew=0,  eff=(), role="mid"),
    "aggressive": dict(kw=(), skew=1,  eff=(), role="aggro", skew_tax=True),
    "guard":      dict(kw=("guard",),   skew=-1, eff=(), role="control"),
    "wall":       dict(kw=("guard",),   skew=-2, eff=(), role="control"),
    "rush":       dict(kw=("rush",),    skew=1,  eff=(), role="aggro"),
    "barrier":    dict(kw=("barrier",), skew=0,  eff=(), role="mid"),
    "drain":      dict(kw=("drain",),   skew=0,  eff=(), role="control"),
    "etb_draw":   dict(kw=(), skew=0, eff=({"type": "draw", "amount": 1},), role="mid"),
    "etb_burn":   dict(kw=(), skew=0, eff=({"type": "damage_flexible", "amount": 2},), role="aggro"),
}

# Which flavors to use per cost tier, and how many units that tier needs.
UNIT_COUNTS = {1: 8, 2: 12, 3: 12, 4: 10, 5: 8, 6: 6, 7: 5, 8: 4}  # = 65
TIER_FLAVORS = {
    1: ["vanilla", "aggressive", "guard"],   # Rush/Barrier unaffordable at cost 1
    2: ["vanilla", "aggressive", "rush", "guard", "barrier", "etb_burn"],
    3: ["vanilla", "aggressive", "guard", "drain", "etb_draw", "barrier"],
    4: ["vanilla", "aggressive", "guard", "wall", "drain", "etb_draw"],
    5: ["vanilla", "guard", "wall", "drain", "barrier"],
    6: ["vanilla", "guard", "wall", "drain"],
    7: ["vanilla", "guard", "wall"],
    8: ["vanilla", "wall", "guard"],
}

_ADJ = ["Ember", "Frost", "Iron", "Storm", "Shadow", "Gilded", "Thorn",
        "Ashen", "Verdant", "Cobalt", "Crimson", "Pale", "Solar", "Void"]
_NOUN = ["Sentinel", "Warden", "Raider", "Hound", "Golem", "Sprite", "Knight",
         "Serpent", "Herald", "Brute", "Archer", "Colossus"]


def _gen_name(i):
    return f"{_ADJ[i // len(_NOUN)]} {_NOUN[i % len(_NOUN)]}"


def _make_unit(cid, cost, flavor, name, art=None, rarity=None,
               role=None, legendary=False, keywords=None, skew=None,
               effects=(), text=""):
    """Build a unit from a flavor spec or explicit overrides, enforcing budget."""
    spec = FLAVORS.get(flavor, {}) if flavor else {}
    kw = tuple(keywords if keywords is not None else spec.get("kw", ()))
    sk = skew if skew is not None else spec.get("skew", 0)
    eff = tuple(effects) if effects else tuple(spec.get("eff", ()))
    role = role or spec.get("role", "mid")

    B = _budget(cost, legendary)
    if spec.get("skew_tax") or (sk >= 2):     # attack-skewed units pay the tax
        B -= 1
    kw_cost = sum(KEYWORD_COST[k] for k in kw)
    eff_cost = ETB_COST * len(eff)
    points = B - kw_cost - eff_cost
    atk, health = _split(points, sk, allow_zero_atk=(flavor == "wall"))

    if not text:
        parts = [k.capitalize() + "." for k in kw]
        text = " ".join(parts)

    if not rarity:
        complexity = len(kw) + len(eff)
        rarity = "epic" if complexity >= 2 else ("rare" if complexity == 1 else "common")

    return Card(cid, name, cost, "unit", rarity, role, atk, health, kw, eff,
                text, (ART + art) if art else None), (atk + health + kw_cost + eff_cost), B


# --------------------------------------------------------------------------
# The 35 spells (explicit — spell value is tuned, not formula-derived).
# --------------------------------------------------------------------------
def _spells(start_id):
    S = []
    cid = start_id

    def add(name, cost, effects, role, rarity, text):
        nonlocal cid
        S.append(Card(cid, name, cost, "spell", rarity, role, 0, 0, (),
                      tuple(effects), text))
        cid += 1

    # -- Single-target removal (10): the primary answer -------------------
    add("Jolt", 1, [{"type": "damage_unit", "amount": 2}], "control", "common", "Deal 2 to a unit.")
    add("Pin", 1, [{"type": "damage_unit", "amount": 2}], "control", "common", "Deal 2 to a unit.")
    add("Cinder", 2, [{"type": "damage_unit", "amount": 3}], "control", "common", "Deal 3 to a unit.")
    add("Smite", 2, [{"type": "damage_unit", "amount": 3}], "control", "common", "Deal 3 to a unit.")
    add("Execute", 2, [{"type": "destroy_damaged"}], "control", "rare", "Destroy a damaged unit.")
    add("Fracture", 3, [{"type": "damage_unit", "amount": 5}], "control", "common", "Deal 5 to a unit.")
    add("Hex", 3, [{"type": "damage_unit", "amount": 5}], "control", "rare", "Deal 5 to a unit.")
    add("Banish", 4, [{"type": "destroy"}], "control", "rare", "Destroy a unit.")
    add("Doom", 4, [{"type": "destroy"}], "control", "epic", "Destroy a unit.")
    add("Reckoning", 5, [{"type": "destroy"}, {"type": "draw", "amount": 1}], "control", "epic",
        "Destroy a unit. Draw 1.")

    # -- AoE / sweepers (4): scarce, expensive anti-snowball valve ---------
    add("Tremor", 3, [{"type": "aoe", "amount": 2}], "control", "rare", "Deal 2 to all enemy units.")
    add("Chill", 4, [{"type": "aoe", "amount": 3}], "control", "epic", "Deal 3 to all enemy units.")
    add("Pyre", 5, [{"type": "aoe", "amount": 4}], "control", "epic", "Deal 4 to all enemy units.")
    add("Wrath", 6, [{"type": "aoe", "amount": 5}], "control", "epic", "Deal 5 to all enemy units.")

    # -- Burn (6): reach; face damage capped at 5 -------------------------
    add("Spark Bolt", 1, [{"type": "damage_flexible", "amount": 2}], "aggro", "common", "Deal 2 to any target.")
    add("Scorch", 2, [{"type": "damage_flexible", "amount": 3}], "aggro", "common", "Deal 3 to any target.")
    add("Flame", 2, [{"type": "damage_flexible", "amount": 3}], "aggro", "common", "Deal 3 to any target.")
    add("Blast", 3, [{"type": "damage_flexible", "amount": 4}], "aggro", "rare", "Deal 4 to any target.")
    add("Lance", 4, [{"type": "damage_flexible", "amount": 5}], "aggro", "rare", "Deal 5 to any target.")
    add("Meteorlet", 5, [{"type": "damage_flexible", "amount": 5}], "aggro", "rare", "Deal 5 to any target.")

    # -- Card draw / refuel (5) -------------------------------------------
    add("Glimpse", 1, [{"type": "draw", "amount": 1}], "mid", "common", "Draw 1.")
    add("Insight", 3, [{"type": "draw", "amount": 2}], "control", "common", "Draw 2.")
    add("Recall", 3, [{"type": "draw", "amount": 2}], "control", "common", "Draw 2.")
    add("Archive", 5, [{"type": "draw", "amount": 3}], "control", "rare", "Draw 3.")
    add("Great Tome", 6, [{"type": "draw", "amount": 4}], "control", "epic", "Draw 4.")

    # -- Buffs / combat tricks (6) ----------------------------------------
    add("Empower", 1, [{"type": "buff", "atk": 2, "health": 2}], "aggro", "common", "Give a unit +2/+2.")
    add("Rally", 2, [{"type": "buff", "atk": 3, "health": 3}], "aggro", "common", "Give a unit +3/+3.")
    add("Bulwark", 2, [{"type": "buff", "atk": 0, "health": 4, "grant": "guard"}], "control", "rare",
        "Give a unit +0/+4 and Guard.")
    add("Charge", 1, [{"type": "buff", "atk": 1, "health": 0, "grant": "rush"}], "aggro", "rare",
        "Give a unit +1/+0 and Rush.")
    add("Frenzy", 3, [{"type": "buff", "atk": 4, "health": 2}], "aggro", "rare", "Give a unit +4/+2.")
    add("Warcry", 4, [{"type": "buff_all", "atk": 1, "health": 1}], "aggro", "epic", "Give your units +1/+1.")

    # -- Utility (4) ------------------------------------------------------
    add("Salve", 1, [{"type": "heal_face", "amount": 4}], "control", "common", "Heal your face 4.")
    add("Mend", 3, [{"type": "heal_face", "amount": 8}], "control", "rare", "Heal your face 8.")
    add("Return", 2, [{"type": "bounce"}], "mid", "rare", "Return an enemy unit to hand.")
    add("Quell", 2, [{"type": "silence"}], "control", "rare", "Silence an enemy unit.")

    return S


def _assign_rarities(cards):
    """Reassign rarities to hit 50 common / 30 rare / 15 epic / 5 legendary."""
    from dataclasses import replace
    legendaries = [c for c in cards if c.rarity == "legendary"]
    rest = [c for c in cards if c.rarity != "legendary"]

    def complexity(c):
        return (len(c.keywords) + len(c.effects)
                + (1 if c.cost >= 6 else 0)
                + (0.5 if not c.is_unit else 0))   # spells skew slightly rarer

    rest.sort(key=lambda c: (-complexity(c), c.cost, c.id))
    n_epic = 15
    n_rare = 30
    out = {c.id: c for c in legendaries}
    for i, c in enumerate(rest):
        if i < n_epic:
            r = "epic"
        elif i < n_epic + n_rare:
            r = "rare"
        else:
            r = "common"
        out[c.id] = replace(c, rarity=r)
    # preserve original ordering
    return [out[c.id] for c in cards]


# --------------------------------------------------------------------------
# Assemble & verify the full 100-card pool.
# --------------------------------------------------------------------------
def build_pool():
    cards = []
    cid = 0
    violations = []

    # 1) Marquee (art-backed) units first.
    for m in MARQUEE:
        card, used, B = _make_unit(
            cid, m["cost"], None, m["name"], art=m.get("art"),
            rarity=m.get("rarity", "legendary" if m.get("legendary") else None),
            role=m.get("role"), legendary=m.get("legendary", False),
            keywords=m.get("keywords", ()), skew=m.get("skew", 0),
            effects=m.get("effects", ()), text=m.get("text", ""))
        if used > B:
            violations.append((card.name, used, B))
        cards.append(card)
        cid += 1

    # 2) Fill each cost tier with generated units up to its target count.
    made_per_cost = {}
    for c in cards:
        if c.is_unit:
            made_per_cost[c.cost] = made_per_cost.get(c.cost, 0) + 1

    name_i = 0
    for cost in sorted(UNIT_COUNTS):
        need = UNIT_COUNTS[cost] - made_per_cost.get(cost, 0)
        flavors = TIER_FLAVORS[cost]
        for k in range(need):
            flavor = flavors[k % len(flavors)]
            card, used, B = _make_unit(cid, cost, flavor, _gen_name(name_i))
            if used > B:
                violations.append((card.name, used, B))
            cards.append(card)
            cid += 1
            name_i += 1

    # 3) Spells.
    cards.extend(_spells(cid))

    # 4) Rarity rebalance to the design target 50/30/15/5 (cosmetic tier,
    #    NOT a power tier). Legendaries are fixed; the rest are assigned by
    #    complexity so splashier cards read as rarer.
    cards = _assign_rarities(cards)

    # ---- self-checks (the formula proves itself) ----
    units = [c for c in cards if c.is_unit]
    spells = [c for c in cards if not c.is_unit]
    assert len(cards) == 100, f"expected 100 cards, got {len(cards)}"
    assert len(units) == 65, f"expected 65 units, got {len(units)}"
    assert len(spells) == 35, f"expected 35 spells, got {len(spells)}"
    assert not violations, f"budget violations: {violations}"
    # face-damage ceiling: no single card deals >5 to face
    for c in cards:
        for e in c.effects:
            if e["type"] in ("damage_flexible", "damage_face"):
                assert e["amount"] <= 5, f"{c.name} breaks the face-burn cap"
    # power ceiling: no unit total stats > cost-8 legendary budget (18)
    for u in units:
        assert u.atk + u.health <= 18, f"{u.name} breaks the stat ceiling"

    return cards


if __name__ == "__main__":
    pool = build_pool()
    from collections import Counter
    print(f"Pool OK: {len(pool)} cards")
    print("By type:", Counter(c.ctype for c in pool))
    print("By rarity:", Counter(c.rarity for c in pool))
    print("Units by cost:", dict(sorted(Counter(c.cost for c in pool if c.is_unit).items())))
