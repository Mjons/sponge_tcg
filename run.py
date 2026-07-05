#!/usr/bin/env python3
"""SPARK — command-line entry point.

  python run.py cards            # validate + print the 100-card pool
  python run.py export           # write CARDS.md
  python run.py sim [N]          # balance simulation (N games per pairing)
  python run.py demo [a] [b]     # play one logged game between two archetypes
  python run.py play [you] [bot] # play the combat game in the terminal
  python run.py gui [port]       # play SMUDGE: PANEL BRAWL in a browser (default port 8000)
  python run.py gui-combat [port]# play the original combat game in a browser
"""

import sys
import random


def cmd_cards():
    from spark.export import render
    from spark.cards import build_pool
    print(render(build_pool()))


def cmd_export():
    from spark.export import render
    from spark.cards import build_pool
    with open("CARDS.md", "w") as f:
        f.write(render(build_pool()) + "\n")
    print("wrote CARDS.md")


def cmd_sim(args):
    from spark.sim import run, report
    n = int(args[0]) if args else 2000
    print(report(run(games_per_pairing=n)))


def cmd_demo(args):
    from spark.cards import build_pool
    from spark.engine import Game
    from spark.bots import build_deck, make_policy, mulligan_pred
    a = args[0] if len(args) > 0 else "aggro"
    b = args[1] if len(args) > 1 else "control"
    pool = build_pool()
    rng = random.Random(42)
    log = []
    g = Game(build_deck(pool, a), build_deck(pool, b), rng=rng, log=log)
    pol0, pol1 = make_policy(a), make_policy(b)
    m0, m1 = mulligan_pred(a), mulligan_pred(b)

    def policy(gg, p):
        who = a if p is gg.players[0] else b
        before = (gg.players[0].life, gg.players[1].life,
                  len(gg.players[0].board), len(gg.players[1].board))
        (pol0 if p is gg.players[0] else pol1)(gg, p)
        after = (gg.players[0].life, gg.players[1].life,
                 len(gg.players[0].board), len(gg.players[1].board))
        print(f"  T{gg.turn:>2} {p.name}({who:<8}) spark{p.spark_max:<2} "
              f"life {before[0]}->{after[0]} / {before[1]}->{after[1]}  "
              f"board {after[2]}v{after[3]}")

    print(f"DEMO: P0={a}  vs  P1={b}  (start life {g.start_life})")
    g.run(policy, mulligan_fn=lambda gg, p, first: gg.mulligan(p, m0 if first else m1))
    result = {0: f"P0 ({a}) wins", 1: f"P1 ({b}) wins", -1: "draw"}[g.winner]
    print(f"RESULT after {g.turn} plies: {result}  "
          f"(life {g.players[0].life} / {g.players[1].life})")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "sim"
    rest = sys.argv[2:]
    if cmd == "cards":
        cmd_cards()
    elif cmd == "export":
        cmd_export()
    elif cmd == "sim":
        cmd_sim(rest)
    elif cmd == "demo":
        cmd_demo(rest)
    elif cmd == "play":
        from spark.play import main as play_main
        play_main(rest)
    elif cmd == "gui":
        from spark.lane_server import serve
        port = int(rest[0]) if rest else 8000
        serve(port=port)
    elif cmd == "gui-combat":
        from spark.server import serve
        port = int(rest[0]) if rest else 8000
        serve(port=port)
    else:
        print(__doc__)
        sys.exit(1)
