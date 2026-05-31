"""
╔══════════════════════════════════════════════════════════════╗
║   THE MONTY PYTHON — chaos-theory poker bot                  ║
║   "Strange women lying in ponds distributing strategies      ║
║    is no basis for a system of game theory."                 ║
╚══════════════════════════════════════════════════════════════╝

Design philosophy:
  Against advanced solvers, you can't out-EV them on the spots they've
  studied. You CAN make every spot a spot they haven't studied. This bot
  picks one of five Monty Python personas per hand using a chaotic
  logistic map seeded by the hand id, so opponents see what looks like
  five different bots in random rotation. Each persona has its own
  ranges, sizings and bluff frequencies. None of them are pure GTO.
  All of them have an equity floor so we don't light money on fire.

Personas (logistic-map driven, roughly equal weights):
  THE KNIGHT          — calls everything down. 'Tis but a scratch.
  THE INQUISITOR      — surprise 3-bets and turn raises. Nobody expects.
  THE FRENCHMAN       — taunts then folds. Wide opens, gives up to pressure.
  THE RABBIT          — small/checked pots; suddenly all-in on a chaos roll.
  THE LUMBERJACK      — fast and aggressive, jam draws, double-barrel light.

Equity floor (always on):
  - Never put chips in past 8% of stack with sub-30% equity unless the
    persona's chaos roll specifically authorises a bluff in that spot.
  - Never call a big bet with absolute trash, regardless of persona.
"""

import math
import random
import eval7

BOT_NAME       = "The Monty Python"
BOT_AVATAR     = "robot_1"
STARTING_STACK = 10_000

_RANKS = "23456789TJQKA"


# ---------------------------------------------------------------------------
# CHAOS — logistic map + hand-id hash drive everything
# ---------------------------------------------------------------------------

def _seed_from(hand_id: str, salt: int = 0) -> float:
    """Deterministic float in (0,1) from hand_id. Same hand_id → same chaos."""
    h = abs(hash((hand_id, salt))) % (2**31)
    x = (h / (2**31)) * 0.98 + 0.01
    # Burn a few logistic-map iterations to mix the bits
    for _ in range(5):
        x = 3.9 * x * (1 - x)
    return x


def _chaos_stream(hand_id: str, n: int = 8) -> list:
    """Generate n chaotic floats deterministically for this hand."""
    x = _seed_from(hand_id, 0)
    out = []
    for _ in range(n):
        x = 3.9 * x * (1 - x)
        out.append(x)
    return out


# ---------------------------------------------------------------------------
# PERSONAS
# ---------------------------------------------------------------------------

KNIGHT, INQUISITOR, FRENCHMAN, RABBIT, LUMBERJACK = (
    "knight", "inquisitor", "frenchman", "rabbit", "lumberjack"
)
PERSONAS = [KNIGHT, INQUISITOR, FRENCHMAN, RABBIT, LUMBERJACK]


def _persona(hand_id: str) -> str:
    x = _seed_from(hand_id, 7)
    idx = min(int(x * len(PERSONAS)), len(PERSONAS) - 1)
    return PERSONAS[idx]


# ---------------------------------------------------------------------------
# HAND STRENGTH
# ---------------------------------------------------------------------------

def _rank(c: str) -> int:
    return _RANKS.index(c[0])


def _preflop_strength(cards: list) -> int:
    """0=trash 1=spec 2=med 3=strong 4=premium."""
    c1, c2 = cards
    r1, r2 = _rank(c1), _rank(c2)
    suited = c1[1] == c2[1]
    if r1 < r2:
        r1, r2 = r2, r1

    if r1 == r2:
        if r1 >= 9: return 4
        if r1 >= 7: return 3
        return 2
    if r1 == 12:
        if r2 == 11: return 4
        if r2 >= 9:  return 3
        if suited or r2 >= 8: return 2
        return 1
    if r1 == 11 and r2 == 10:
        return 3 if suited else 2
    if r1 >= 9 and r2 >= 8:
        return 2
    if suited:
        gap = r1 - r2
        if gap <= 1 and r2 >= 4: return 2
        if gap <= 3:             return 1
    return 0


def _hand_score(hole: list, board: list) -> float:
    if len(board) < 3:
        return 0.5
    try:
        score = eval7.evaluate(
            [eval7.Card(c) for c in hole] + [eval7.Card(c) for c in board]
        )
        return min(score / 57343.0, 1.0)
    except Exception:
        return 0.3


def _has_draw(hole: list, board: list) -> bool:
    if len(board) < 3:
        return False
    try:
        all_cards = hole + board
        suits = [c[1] for c in all_cards]
        ranks = sorted({_rank(c) for c in all_cards})
        if max(suits.count(s) for s in "shdc") >= 4:
            return True
        # OESD check: any 4 consecutive ranks?
        for i in range(len(ranks) - 3):
            if ranks[i+3] - ranks[i] == 3:
                return True
        return False
    except Exception:
        return False


# ---------------------------------------------------------------------------
# ACTION HELPERS
# ---------------------------------------------------------------------------

def _raise(gs: dict, fraction: float) -> dict:
    pot   = gs["pot"]
    min_r = gs["min_raise_to"]
    stack = gs["your_stack"]
    bsf   = gs["your_bet_this_street"]
    amount = max(int(pot * fraction), min_r)
    amount = min(amount, stack + bsf)
    if amount >= stack + bsf:
        return {"action": "all_in"}
    return {"action": "raise", "amount": amount}


def _pot_odds(gs: dict) -> float:
    owed = gs["amount_owed"]
    pot  = gs["pot"]
    return owed / (pot + owed) if owed > 0 else 0.0


def _stack_bb(gs: dict) -> float:
    return gs["your_stack"] / 100.0


def _position(gs: dict) -> float:
    return gs["seat_to_act"] / max(len(gs["players"]) - 1, 1)


def _n_opponents(gs: dict) -> int:
    my_seat = gs["seat_to_act"]
    return sum(
        1 for p in gs["players"]
        if not p["is_folded"] and p["seat"] != my_seat
    )


# ---------------------------------------------------------------------------
# EQUITY FLOOR — the one thing chaos can't override
# ---------------------------------------------------------------------------

def _is_committing(gs: dict) -> bool:
    """Are we about to put a meaningful chunk of stack at risk?"""
    owed  = gs["amount_owed"]
    stack = gs["your_stack"]
    return owed > 0 and (owed / max(stack, 1)) > 0.08


def _equity_ok_for_call(gs: dict, score: float, draw: bool) -> bool:
    """Floor: even chaos personas need this to call a real bet."""
    po = _pot_odds(gs)
    if score >= po + 0.02:
        return True
    if draw and po <= 0.30:
        return True
    return False


# ---------------------------------------------------------------------------
# DECISION
# ---------------------------------------------------------------------------

def decide(gs: dict) -> dict:
    try:
        return _decide(gs)
    except Exception:
        return {"action": "check"} if gs.get("can_check") else {"action": "fold"}


def _decide(gs: dict) -> dict:
    hand_id   = gs.get("hand_id", "x")
    chaos     = _chaos_stream(hand_id, 8)
    persona   = _persona(hand_id)
    street    = gs["street"]
    hole      = gs["your_cards"]
    board     = gs["community_cards"]
    pot       = gs["pot"]
    owed      = gs["amount_owed"]
    can_check = gs["can_check"]
    pos       = _position(gs)
    n_opps    = _n_opponents(gs)
    stack_bb  = _stack_bb(gs)
    survival  = stack_bb < 20

    # ── PREFLOP ──────────────────────────────────────────────────────────
    if street == "preflop":
        s = _preflop_strength(hole)

        # Survival floor — chaos can't make us shove 72o
        if survival and s < 3:
            return {"action": "check"} if can_check else {"action": "fold"}
        if survival and s >= 3:
            return _raise(gs, 99.0)

        # ALL personas: premiums are premium
        if s == 4:
            size = 2.6 + chaos[0] * 1.8     # 2.6x – 4.4x pot, randomised
            return _raise(gs, size)
        if s == 3:
            size = 2.0 + chaos[1] * 1.4
            return _raise(gs, size)

        # KNIGHT — wide calling, no opens unless 2+
        if persona == KNIGHT:
            if s >= 1:
                if can_check: return {"action": "check"}
                if owed <= pot * 0.30: return {"action": "call"}
                return {"action": "fold"} if owed > pot * 0.6 else {"action": "call"}
            if can_check: return {"action": "check"}
            return {"action": "fold"}

        # INQUISITOR — surprise 3-bets, otherwise tight
        if persona == INQUISITOR:
            if chaos[2] < 0.18 and pos >= 0.5 and owed > 0 and owed <= 400:
                return _raise(gs, 3.0 + chaos[3] * 2.0)  # surprise 3-bet bluff
            if s == 2 and pos >= 0.5:
                return _raise(gs, 2.4 + chaos[4])
            if can_check: return {"action": "check"}
            if s >= 2 and owed <= 200: return {"action": "call"}
            return {"action": "fold"}

        # FRENCHMAN — wide opens, fold to pressure
        if persona == FRENCHMAN:
            if owed == 0 and s >= 1:
                return _raise(gs, 2.2 + chaos[5])
            if can_check: return {"action": "check"}
            if owed <= 150 and s >= 2: return {"action": "call"}
            return {"action": "fold"}

        # RABBIT — small pots, occasional shove
        if persona == RABBIT:
            if chaos[6] < 0.06 and s >= 2:
                return _raise(gs, 99.0)  # SUDDEN ALL-IN
            if s == 2 and pos >= 0.4:
                return _raise(gs, 2.2 + chaos[0])
            if can_check: return {"action": "check"}
            if owed <= 150 and s >= 1: return {"action": "call"}
            return {"action": "fold"}

        # LUMBERJACK — fast, aggressive
        if persona == LUMBERJACK:
            if s >= 2:
                return _raise(gs, 2.6 + chaos[1] * 1.2)
            if s == 1 and pos >= 0.4:
                return _raise(gs, 2.2 + chaos[2])
            if can_check: return {"action": "check"}
            if owed <= 200 and s >= 1: return {"action": "call"}
            return {"action": "fold"}

        # Fallback
        if can_check: return {"action": "check"}
        return {"action": "fold"}

    # ── POSTFLOP ─────────────────────────────────────────────────────────
    score = _hand_score(hole, board)
    draw  = _has_draw(hole, board)
    po    = _pot_odds(gs)

    # Universal monster line: nuts → bet big, vary size
    if score >= 0.88:
        size = 0.7 + chaos[0] * 0.7   # 0.7x to 1.4x pot
        return _raise(gs, size)

    # KNIGHT — call everything that isn't insane
    if persona == KNIGHT:
        if can_check: return {"action": "check"}
        # 'Tis but a scratch — but we still respect the equity floor
        if _equity_ok_for_call(gs, score, draw):
            return {"action": "call"}
        if not _is_committing(gs):
            return {"action": "call"}
        return {"action": "fold"}

    # INQUISITOR — surprise raises with strong-ish hands or chaos draws
    if persona == INQUISITOR:
        if score >= 0.55:
            return _raise(gs, 0.7 + chaos[1] * 0.5)
        if draw and chaos[2] < 0.45:
            if can_check: return _raise(gs, 0.55)
            if _equity_ok_for_call(gs, score, draw):
                # Sometimes raise the draw — nobody expects
                if chaos[3] < 0.30 and not _is_committing(gs):
                    return _raise(gs, 0.9)
                return {"action": "call"}
        if can_check:
            # Surprise stab from late position
            if pos >= 0.5 and chaos[4] < 0.25:
                return _raise(gs, 0.5 + chaos[5] * 0.4)
            return {"action": "check"}
        if _equity_ok_for_call(gs, score, draw):
            return {"action": "call"}
        return {"action": "fold"}

    # FRENCHMAN — open big, surrender on resistance
    if persona == FRENCHMAN:
        if can_check:
            if pos >= 0.4 and chaos[0] < 0.55:
                return _raise(gs, 0.4 + chaos[1] * 0.4)
            return {"action": "check"}
        # Facing a bet — fold light, only continue with real equity
        if score >= 0.55:
            return {"action": "call"}
        if draw and po <= 0.28:
            return {"action": "call"}
        return {"action": "fold"}

    # RABBIT — quiet, then sudden chaos
    if persona == RABBIT:
        chaos_bomb = chaos[6] < 0.08
        if chaos_bomb and (score >= 0.50 or draw):
            return _raise(gs, 1.2 + chaos[7])  # OVERBET BOMB
        if can_check: return {"action": "check"}
        if score >= 0.45 and not _is_committing(gs):
            return {"action": "call"}
        if _equity_ok_for_call(gs, score, draw):
            return {"action": "call"}
        return {"action": "fold"}

    # LUMBERJACK — barrel hard, jam draws
    if persona == LUMBERJACK:
        if score >= 0.45 or draw:
            if can_check: return _raise(gs, 0.6 + chaos[0] * 0.5)
            if _equity_ok_for_call(gs, score, draw):
                if chaos[1] < 0.40:
                    return _raise(gs, 0.8 + chaos[2] * 0.6)
                return {"action": "call"}
            return {"action": "fold"}
        # Pure bluff barrel from position
        if can_check and pos >= 0.5 and chaos[3] < 0.35 and street == "flop":
            return _raise(gs, 0.55)
        if can_check: return {"action": "check"}
        return {"action": "fold"}

    # Safety
    if can_check: return {"action": "check"}
    return {"action": "fold"}
