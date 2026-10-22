"""Deterministic 3x3 cube engine (54-facelet string, 18-move HTM) + exact shortest distance for small scrambles.

Facelet order is the standard URFDLB (Kociemba) layout, 9 stickers per face, row-major as seen
looking at the face from outside. Solved = 'U'*9+'R'*9+'F'*9+'D'*9+'L'*9+'B'*9.
Stickers are simulated in 3D, so every move is a true 90-degree layer rotation (no hand-typed tables).
"""
import random
from operator import itemgetter

FACES = "URFDLB"
SOLVED = "".join(f * 9 for f in FACES)
MOVES = [f + s for f in FACES for s in ("", "'", "2")]
_N = {"U": (0, 1, 0), "R": (1, 0, 0), "F": (0, 0, 1), "D": (0, -1, 0), "L": (-1, 0, 0), "B": (0, 0, -1)}


def _loc(face, i):
    r, c = divmod(i, 3)
    pos = {"U": (c - 1, 1, r - 1), "R": (1, 1 - r, 1 - c), "F": (c - 1, 1 - r, 1),
           "D": (c - 1, -1, 1 - r), "L": (-1, 1 - r, c - 1), "B": (1 - c, 1 - r, -1)}[face]
    return pos, _N[face]


_STICKERS = [(f, i) for f in FACES for i in range(9)]
_IDX = {_loc(f, i): k for k, (f, i) in enumerate(_STICKERS)}


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _cw(k, v):
    """Rotate v by -90 deg about unit axis k (= clockwise when looking at the face whose normal is k)."""
    c, d = _cross(k, v), _dot(k, v)
    return tuple(-c[j] + k[j] * d for j in range(3))


def _quarter(face):
    k = _N[face]
    src = list(range(54))
    for idx, (f, i) in enumerate(_STICKERS):
        pos, nrm = _loc(f, i)
        if _dot(pos, k) == 1:
            src[_IDX[(_cw(k, pos), _cw(k, nrm))]] = idx
    return src


PERMS = {}
for _f in FACES:
    _p1 = _quarter(_f)
    _p2 = [_p1[_p1[j]] for j in range(54)]
    _p3 = [_p1[_p1[_p1[j]]] for j in range(54)]
    PERMS[_f] = itemgetter(*_p1)
    PERMS[_f + "2"] = itemgetter(*_p2)
    PERMS[_f + "'"] = itemgetter(*_p3)


def apply_move(state, move):
    if move not in PERMS:
        raise ValueError(f"illegal move {move!r}")
    return "".join(PERMS[move](state))


def apply_moves(state, moves):
    for m in moves:
        state = apply_move(state, m)
    return state


def is_solved(state):
    return state == SOLVED


def inverse(move):
    return move if move.endswith("2") else (move[0] if move.endswith("'") else move + "'")


def random_scramble(n, rng=random):
    seq = []
    while len(seq) < n:
        m = rng.choice(MOVES)
        if seq and m[0] == seq[-1][0]:
            continue
        seq.append(m)
    return seq


# ---- exact shortest distance (HTM), valid for true distance <= 8 -------------------------
_TABLE = None


def _table(depth=4):
    global _TABLE
    if _TABLE is None:
        t, frontier = {SOLVED: 0}, [SOLVED]
        for d in range(1, depth + 1):
            nxt = []
            for s in frontier:
                for m in MOVES:
                    n = apply_move(s, m)
                    if n not in t:
                        t[n] = d
                        nxt.append(n)
            frontier = nxt
        _TABLE = t
    return _TABLE


def optimal_distance(state):
    """Exact HTM distance to solved via meet-in-the-middle (solved-side depth 4 + state-side depth 4).
    Returns None if the true distance is > 8 (unknown)."""
    t = _table()
    best = t.get(state)
    seen, frontier = {state}, [state]
    for d in range(1, 5):
        if best is not None and d >= best:
            break
        nxt = []
        for s in frontier:
            for m in MOVES:
                n = apply_move(s, m)
                if n not in seen:
                    seen.add(n)
                    nxt.append(n)
                    if n in t and (best is None or d + t[n] < best):
                        best = d + t[n]
        frontier = nxt
    return best if best is not None and best <= 8 else None
