"""Monte-Carlo balance harness for SPARK.

Turns the design's 'needs playtesting' flags into numbers:
  - archetype win-rate matrix (aggro / midrange / control triangle)
  - first-player win-rate (target ~51%)
  - game-length distribution (failure mode A: too-fast; B: never-ends)
"""

import random
from collections import defaultdict

from .cards import build_pool
from .bots import build_deck, make_policy, mulligan_pred

ARCHETYPES = ["aggro", "midrange", "control"]


def play_match(pool, arch0, arch1, seed):
    from .engine import Game
    rng = random.Random(seed)
    deck0 = build_deck(pool, arch0)
    deck1 = build_deck(pool, arch1)
    game = Game(deck0, deck1, rng=rng)
    pol0 = make_policy(arch0)
    pol1 = make_policy(arch1)
    mpred0 = mulligan_pred(arch0)
    mpred1 = mulligan_pred(arch1)

    def mull(g, p, first):
        g.mulligan(p, mpred0 if first else mpred1)

    def policy(g, p):
        (pol0 if p is g.players[0] else pol1)(g, p)

    winner = game.run(policy, mulligan_fn=mull)
    return winner, game.turn


def run(games_per_pairing=1500, seed=1234):
    pool = build_pool()
    rng = random.Random(seed)

    wins = defaultdict(lambda: [0, 0, 0])  # (arch0,arch1) -> [w0, w1, draw]
    first_wins = first_total = 0
    turn_hist = defaultdict(int)
    fast_games = long_games = total_games = 0

    for a in ARCHETYPES:
        for b in ARCHETYPES:
            for g in range(games_per_pairing):
                # Actually alternate seats so the archetype matrix is NOT
                # confounded with first-player advantage. 'a' is the row
                # archetype; we record a's result regardless of seat.
                swap = (g % 2 == 1)
                p0, p1 = (b, a) if swap else (a, b)
                seed_g = rng.getrandbits(64)
                winner, turns = play_match(pool, p0, p1, seed_g)
                total_games += 1
                turn_hist[turns] += 1
                if turns <= 6:
                    fast_games += 1
                if turns >= 20:
                    long_games += 1
                # attribute the decisive result to archetype 'a' vs 'b'
                rec = wins[(a, b)]
                if winner == -1:
                    rec[2] += 1
                else:
                    a_won = (winner == 0) != swap   # a sat in P0 unless swapped
                    rec[0 if a_won else 1] += 1
                # first-player stats (seat-based, independent of archetype)
                if winner in (0, 1):
                    first_total += 1
                    if winner == 0:
                        first_wins += 1

    return {
        "pool": pool,
        "wins": wins,
        "first_wins": first_wins,
        "first_total": first_total,
        "turn_hist": turn_hist,
        "fast_games": fast_games,
        "long_games": long_games,
        "total_games": total_games,
        "games_per_pairing": games_per_pairing,
    }


def _winrate(rec):
    w0, w1, d = rec
    total = w0 + w1 + d
    return 100.0 * w0 / total if total else 0.0


def report(res):
    out = []
    out.append("=" * 64)
    out.append("SPARK — BALANCE SIMULATION")
    out.append("=" * 64)
    gpp = res["games_per_pairing"]
    out.append(f"{res['total_games']} games total "
               f"({gpp} per archetype pairing, seat-alternated)\n")

    # Archetype matrix: cell = row archetype's win% vs the column archetype,
    # aggregated over both seats (games are seat-alternated within a pairing).
    out.append("Archetype win-rate matrix  (cell = row win% vs column, both seats):")
    header = "            " + "".join(f"{c[:5]:>9}" for c in ARCHETYPES)
    out.append(header)
    for a in ARCHETYPES:
        row = f"  {a:<9}"
        for b in ARCHETYPES:
            row += f"{_winrate(res['wins'][(a, b)]):>8.1f}%"
        out.append(row)

    # Overall archetype strength (avg win% across all opponents, both seats)
    out.append("\nOverall archetype win-rate (all matchups, both seats):")
    agg = defaultdict(lambda: [0, 0])   # arch -> [wins, decisive games]
    for (a, b), rec in res["wins"].items():
        w0, w1, d = rec
        agg[a][0] += w0
        agg[a][1] += w0 + w1
        agg[b][0] += w1
        agg[b][1] += w0 + w1
    for a in ARCHETYPES:
        w, t = agg[a]
        out.append(f"  {a:<10} {100.0 * w / t:5.1f}%")

    # First-player advantage
    fp = 100.0 * res["first_wins"] / res["first_total"]
    out.append(f"\nFirst-player win-rate: {fp:5.1f}%   (target ~51%; P1 skips "
               f"its first draw, P2 gets a one-time Spark Token)")

    # Game length / failure modes
    hist = res["turn_hist"]
    tg = res["total_games"]
    plies = sorted(hist)
    avg_turns = sum(t * n for t, n in hist.items()) / tg
    # convert plies to 'rounds' (each player-turn is one ply)
    out.append(f"\nGame length: avg {avg_turns:.1f} plies "
               f"(~{avg_turns / 2:.1f} rounds each)")
    out.append(f"  Fast games (<=6 plies, aggro-too-fast check): "
               f"{100.0 * res['fast_games'] / tg:.1f}%")
    out.append(f"  Long games (>=20 plies, stall check):         "
               f"{100.0 * res['long_games'] / tg:.1f}%")
    # tiny ascii histogram by ply buckets
    buckets = defaultdict(int)
    for t, n in hist.items():
        buckets[min(t // 2 * 2, 30)] += n
    out.append("  Length distribution (plies):")
    peak = max(buckets.values())
    for b in sorted(buckets):
        bar = "#" * max(1, int(40 * buckets[b] / peak)) if buckets[b] else ""
        label = f"{b:>2}-{b+1}" if b < 30 else " 30+"
        out.append(f"    {label} {bar} {buckets[b]}")

    out.append("=" * 64)
    return "\n".join(out)


if __name__ == "__main__":
    import sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1500
    res = run(games_per_pairing=n)
    print(report(res))
