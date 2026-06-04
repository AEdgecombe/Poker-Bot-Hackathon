# Poker Hackathon — The Monty Python

My entry for the poker bot hackathon (Fullhouse, June 2026). A No-Limit Texas Hold'em bot, written in Python.

The bot lives in [bot.py](bot.py). It's called **The Monty Python**.

---

## The idea

You can build a poker bot two ways:

1. **Try to be perfect.** Solve for the EV-maximising action in every spot. Run Monte Carlo, learn opponent ranges, play GTO.
2. **Try to be unpredictable.** Pick chaotic-but-sane lines so opponents can't model you.

I tried option 1 first. It works fine against weak bots. Buttttt....

I went with option 2 and called it The Monty Python.

---

## How the bot works

Every hand, the bot becomes one of 5 personas, picked by a chaotic function (a logistic map) seeded with the hand id. To an opponent, it looks like 5 different bots showing up in random rotation.

| Persona | Style |
|---|---|
| **The Knight** | "'Tis but a scratch." Calls everything down. |
| **The Inquisitor** | Nobody expects the surprise 3-bet. |
| **The Frenchman** | Opens wide, folds the moment you push back. |
| **The Rabbit** | Quiet, quiet, quiet — then suddenly all-in. |
| **The Lumberjack** | Barrels hard, jams draws, never lets up. |

Bet sizes, bluff frequencies, and raise triggers are all drawn from the same chaos stream, nothing is fixed, so opponents can't fit a model to it.

There's an **equity floor** under all of it: the bot uses `eval7` to compute real hand strength and pot odds, and chaos can't override it. We won't shove 7-2o just because the chaos roll says to.

---

## What I learnt

- **The engine is brutally simple.** One function, `decide(state)`, returns one action. The whole strategy fits in one file. All the complexity is choices, not code.
- **Hand strength is mostly a solved problem.** `eval7` evaluates a 7-card hand in microseconds. You don't need to write your own.
- **Opponent modelling is real EV.** Bucketing opponents into archetypes (aggro / passive / folder) and adjusting your ranges is bigger than tuning preflop charts.
- **Bet sizing is information.** If you bet 0.75 pot every time you have a strong hand, smart opponents will learn that. Jittering sizes by ±15% is free anti-information.
- **GTO is the floor, not the ceiling.** Against weak opponents you make money by exploiting them. Against strong opponents, GTO breaks even — to actually *win* you need them to mis-model you.
- **Variance is a feature when you can't win on skill.** A chaos bot loses more often than a tight GTO bot, but in a tournament you only need to win once. High variance + positive expectation = good tournament strategy.
- **Sandbox sims lie cleanly.** 200-hand heads-up vs the reference bots tells you almost nothing about how you'll do against another serious bot. But it does catch bugs that crash your bot in 5 seconds.
- **`load_failed` errors usually mean the wrong path, not a broken bot.** Spent a frustrated minute on this. The bot was fine; I was loading from `bots/mybot/` which didn't exist.


## Sandbox results

Heads-up, 200 hands, 5 runs each:

| Opponent | Avg chip delta | Wins |
|---|---|---|
| The Shark (tight GTO ref bot) | +3,267 | 4/5 |
| The Mathematician (pot-odds ref bot) | +9,310 | 5/5 |
| ref_bot_2 (pot-odds ref bot) | +9,330 | 5/5 |

4-way tournament (template + shark + aggressor + math, 300 hands): 3 first-place finishes, 2 busts in 5 runs.

