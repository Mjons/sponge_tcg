"""Export the 100-card pool as a readable, printable list."""

from collections import Counter
from .cards import build_pool

RARITY_ORDER = {"legendary": 0, "epic": 1, "rare": 2, "common": 3}


def render(pool):
    lines = []
    lines.append("# SPARK — Card Pool (100 cards)\n")

    units = [c for c in pool if c.is_unit]
    spells = [c for c in pool if not c.is_unit]

    lines.append("## Units (65)\n")
    lines.append("| # | Name | Cost | A/H | Keywords/Text | Rarity | Role | Art |")
    lines.append("|--:|------|:----:|:---:|---------------|--------|------|-----|")
    for c in sorted(units, key=lambda c: (c.cost, RARITY_ORDER[c.rarity], c.name)):
        kw = c.text or "—"
        art = c.art.split("/")[-1] if c.art else ""
        lines.append(f"| {c.id} | {c.name} | {c.cost} | {c.atk}/{c.health} | "
                     f"{kw} | {c.rarity} | {c.role} | {art} |")

    lines.append("\n## Spells (35)\n")
    lines.append("| # | Name | Cost | Text | Rarity | Role |")
    lines.append("|--:|------|:----:|------|--------|------|")
    for c in sorted(spells, key=lambda c: (c.cost, c.name)):
        lines.append(f"| {c.id} | {c.name} | {c.cost} | {c.text} | {c.rarity} | {c.role} |")

    # summary
    lines.append("\n## Distribution checks\n")
    lines.append(f"- Total: **{len(pool)}**  |  Units: **{len(units)}**  |  Spells: **{len(spells)}**")
    lines.append(f"- Rarity: " + ", ".join(f"{k} {v}" for k, v in
                 sorted(Counter(c.rarity for c in pool).items(),
                        key=lambda kv: RARITY_ORDER[kv[0]])))
    lines.append(f"- Unit curve (by cost): " + ", ".join(
        f"{k}:{v}" for k, v in sorted(Counter(c.cost for c in units).items())))
    # answers-to-threats
    answers = sum(1 for c in pool for e in c.effects
                  if e["type"] in ("damage_unit", "destroy", "destroy_damaged",
                                   "aoe", "silence", "bounce"))
    lines.append(f"- Interaction cards (removal/AoE/silence/bounce): **{answers}** "
                 f"(~{100*answers/len(pool):.0f}% of pool)")
    return "\n".join(lines)


if __name__ == "__main__":
    pool = build_pool()
    text = render(pool)
    print(text)
