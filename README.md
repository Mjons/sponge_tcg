# SPARK — reference implementation

A minimal, balanced trading card game, built as a runnable Python package with
a **self-verifying card pool**, a **rules engine**, archetype **bots**, and a
**Monte-Carlo balance simulator**. No third-party dependencies (Python 3.10+).

```
spark/
  cards.py    100-card pool, generated from the stat-to-cost formula (self-checks on build)
  engine.py   rules engine: turns, Spark, combat, keywords, effects, fatigue, mitigation knobs
  bots.py     archetype deckbuilders (aggro / midrange / control) + heuristic play policy
  sim.py      balance harness: archetype matrix, first-player win-rate, game-length
  export.py   render the pool to Markdown
  play.py     interactive play-vs-bot terminal client
run.py        CLI entry point
CARDS.md      exported 100-card list (generated)
```

## Run it

```bash
python run.py cards          # validate + print the 100-card pool
python run.py export         # (re)generate CARDS.md
python run.py sim 3000       # full balance run: 27,000 games (3000 per pairing)
python run.py demo aggro control   # watch one logged game, turn by turn
python run.py play           # PLAY the combat game in the terminal
python run.py play aggro control   # you = aggro, bot = control
python run.py gui            # PLAY *SPARK: LANES* in a browser (http://127.0.0.1:8000)
python run.py gui-combat    # play the original combat game in a browser
python run.py gui 8080      # ...on a custom port
```

## SPARK: LANES (`python run.py gui`)

A second game built on the same pool/formula: a **lane battler** (Marvel
Snap-like). Files: `spark/lanes.py` (engine + card set with perks + bot),
`spark/lane_server.py`, `spark/web/lanes.html`.

- **3 lanes**, **3 cards per side per lane** stacked into clean vertical
  columns. **9 rounds** that build on each other — cards you place stay. On
  round _T_ you have _T_ Energy (no banking).
- **Cards have Attack (⚔) and Power.** Power is both the card's health and its
  contribution to the lane score. Each reveal runs a **combat phase**: opposing
  cards in the same slot strike simultaneously, subtracting each other's Attack
  from their Power — you watch the numbers fall and lane totals drop in real
  time. A card reduced to **0 Power dies** and its slot opens up to be
  **replaced** next round. Unopposed cards take no damage and just hold/score.
- **Round scoring:** after combat you bank **1 point for every lane you lead**.
  Most points after round 9 wins (ties broken by total Power).
- **Simultaneous hidden reveal, animated:** click a card then a slot on your
  side to stage it; stage what your Energy allows; hit **Reveal**. The bot
  commits blind, then both sides flip **one at a time** — perks fire (floating
  +N/−N, flashes), then cards **clash** (damage floats, deaths shrink away),
  totals tick, and each led lane flares and banks **+1 pt**.
- **Perks that affect other cards** — On Reveal (✦) and Ongoing (∞): buff your
  cards in a lane / the _other_ lanes, debuff (and now potentially **kill**)
  enemies in a lane, scale with allies, or draw.
- **Budget = 2·Cost + 1 split into Attack + Power**, minus perk cost (same spine
  as the combat game). Attack/Power splits and perk costs are hand-tuned —
  _flagged for playtesting_ (combat makes boards churn fast).
- **Campaign + collection (RPG grind):** a home menu with **10 levels** that
  unlock in order (beat one → unlock the next). Difficulty scales via bot skill
  (0→3, combat-aware at the top), opponent deck bias (random→legendary), and
  boss handicaps (+energy / +cards). A **Card Library** tracks every card's
  owned/locked state; you start with commons+rares and **unlock epics/legendaries
  by clearing levels**. Every card earns **XP** each match (more on a win) and
  **levels up** (+1 Power/level, +1 Attack/2 levels, cap L5) — grinding earlier
  levels powers up your deck to clear later ones. Progress is saved in the
  browser (`localStorage`); the server applies each card's level to its stats.
  Endpoints: `/api/levels`, `/api/pool`, and `/api/new {level, deck}`.
- **Mobile-first UI:** a narrow single-column layout (max-width 480px) with thin,
  card-focused lanes. **2 slots per side per lane**; each card **fills the lane
  width** and is locked to the **2:3 aspect ratio of the art**. The hand is a
  horizontal-scroll strip at the bottom.
- **Art:** the pool includes the original character webp set plus the full-art
  "Smudgies" sponge cards (Sporge, the Duelist, Steampunk Ronin, Golden Paladin,
  Neon Edition, …) served straight from `cards/` (webp + jpg).

### Browser GUI

`python run.py gui` starts a local, dependency-free web app (Python's stdlib
`http.server`) and opens it in your browser. Your `.webp` card art is served
directly and rendered natively — no image library needed. Click a card to play
it (it asks for a target if one is needed); click one of your ⚡-lit units then
an enemy unit or their 🎯 face to attack. Guard, Barrier, lethal, Spark costs,
and summoning sickness are all enforced server-side by the same engine the sim
uses. Spark shows as amber pips; the battle log narrates the bot's moves.

### Deploy SPARK: LANES to Vercel

The lane game also runs on Vercel with no code changes to the engine. Because
Vercel functions are **stateless** (no long-lived process), the game is served
two ways:

- **Locally** — `python run.py gui` uses `spark/lane_server.py`, which keeps the
  game in memory (one process, one player).
- **On Vercel** — `api/*.py` are serverless functions built on
  `spark/webapi.py`. They hold no state: the browser keeps the whole game as an
  opaque `_game` token (see `LaneGame.serialize` / `from_serialized`) and sends
  it back on every request. The same `spark/web/lanes.html` client works with
  both servers.

To deploy:

1. Push this repo to GitHub.
2. On [vercel.com](https://vercel.com), **Add New → Project** and import the repo.
3. Deploy. Every `git push` to `main` re-deploys automatically.

`vercel.json` uses an explicit `builds`/`routes` config (zero-config detection
served the `.py` files as static text instead of building them):

- `api/*.py` are built with `@vercel/python`; each defines a top-level
  `class handler(BaseHTTPRequestHandler)` and imports `spark` lazily at runtime.
  `includeFiles: "spark/**"` bundles the engine into every function.
- `spark/web/lanes.html` and `cards/**` are served as static assets.
- Routes map `/` → the game, `/api/<name>` → the matching `.py` function, and a
  `filesystem` handler serves the static files.

The Python functions handle `/api/new`, `/api/stage`, `/api/reset`, `/api/end`,
`/api/state`, `/api/levels`, and `/api/pool`.

### Playing against the bot

Seats are randomized; you build one of the three archetype decks and so does
the bot. Your turn is driven by short commands (the bot narrates its own):

```
  p <h#> [target]   play card h# from hand (prompts for a target if needed)
  a <m#> <target>   attack with your unit m#   (target: f=face, e#=enemy unit)
  t                 spend your Spark Token (+1 Spark; second player only)
  v / h / e / q     view board / help / end turn / quit
Targets:  f=enemy face   e0,e1..=enemy unit   m0,m1..=your unit
Tags:     [G]uard [R]ush [B]arrier [D]rain   *ready = can attack this turn
```

The board is drawn each turn: opponent on top, you on the bottom, hand below
with an `x` marking cards you can't afford. Guard, Barrier, lethal, and
summoning-sickness are all enforced by the engine — illegal moves are refused
with a reason, so you can't misplay the rules.

`import spark.cards; spark.cards.build_pool()` asserts — on every build — that
all 65 units are inside their point budget, the face-burn cap holds, no unit
breaks the stat ceiling, and the pool is exactly 100 cards (65 units / 35
spells / 50-30-15-5 rarity / the intended cost curve). **The formula proves
itself; if a card were mis-costed the import would fail.**

## The stat-to-cost formula (the spine)

    stat budget  B = 2*C + 1        (1 point = +1 Attack or +1 Health)
    Legendary:   B + 1              (their only mechanical premium)
    keyword costs subtracted from B:  Guard -1, Rush -2, Barrier -2, Drain -2
    minor on-play (ETB) effect: -2
    attack-skewed units (Atk-Health >= ~3) pay a -1 skew tax

Every generated unit is built by this and budget-checked at import.

## What the simulator measured (design → data)

The design flagged three things as "needs playtesting." The sim turned them
into numbers, and **two of my paper guesses were wrong** — corrected here:

| Item                  | Paper design                        | What the sim said                                                                                                                                      | Final                                |
| --------------------- | ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------ |
| Starting life         | 20 (guessed 20→22 if aggro weak)    | Life is the aggro/control dial; **monotone**. Corrected pool wanted more, not less.                                                                    | **21**                               |
| First-turn mitigation | P2 draws +1 card **and** gets Token | +1 card **on top of** the skip-draw rule over-corrects to 42%. Best config: same 3-card hands, **P1 skips its first draw**, P2 keeps the Token → 51.0% | skip-draw + Token, **no bonus card** |
| Aggro/control balance | assumed fine                        | control dominated (55/45) until the clock was tuned                                                                                                    | balanced at life 21                  |

The sim also caught two implementation bugs the design hid: a seat-swap that
never swapped (confounding the archetype matrix with turn order), and a
low-budget formula edge that emitted **0-attack "dead" Rush units at cost 1**
(fixed: the generator never emits a 0-attack non-wall unit; that fix buffed
aggro and forced the life re-tune from 18 → 21 — a clean example of the
card-power / life-total interplay).

### Final balance (27,000 games, seat-alternated)

```
Archetype win-rate (all matchups, both seats):  aggro 51.0%  midrange 47.4%  control 51.6%
Rock-paper-scissors:  aggro > midrange,  control > midrange,  aggro > control
First-player win-rate:  50.8%   (target ~51%)
Failure mode A (aggro too fast, <=6 plies):  0.0%
Failure mode B (never ends):  0 draws / 0 timeouts in 4000 games; longest 55 plies (fatigue always closes)
```

## Mitigation knobs (tunable, in `engine.Game`)

`first_skips_draw=True`, `second_bonus_card=0`, `second_token=True`,
`start_life=21`. Change them and re-run `sim` to reproduce the sweeps above.

## Still needs _human_ playtesting (bots ≈ competent, not expert)

- Spell tempo costs (removal/burn/draw) are hand-tuned, not formula-derived.
- The bot values Guard/Rush/Barrier with fixed weights; a human meta could
  push these. Keyword point-costs are the most likely thing to re-tune.
- Midrange sits ~2.5% under 50 — acceptable (classic "fair-deck" underdog),
  but worth watching if the pool grows.
