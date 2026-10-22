import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "backend"))
from cube import *

def test_basic():
    assert apply_move(SOLVED, "U")[18:21] == "RRR"        
    for f in FACES:
        s = SOLVED
        for _ in range(4): s = apply_move(s, f)
        assert s == SOLVED and apply_moves(SOLVED, [f, f + "'"]) == SOLVED and apply_moves(SOLVED, [f, f]) == apply_move(SOLVED, f + "2")
    assert apply_moves(SOLVED, ["R", "U", "R'", "U'"] * 6) == SOLVED
    assert apply_moves(SOLVED, ["R", "U"] * 105) == SOLVED and apply_moves(SOLVED, ["R", "U"] * 15) != SOLVED
    for f in FACES: assert sorted(apply_move(SOLVED, f)) == sorted(SOLVED)

def test_optimal():
    assert optimal_distance(SOLVED) == 0 and optimal_distance(apply_move(SOLVED, "R2")) == 1
    assert optimal_distance(apply_moves(SOLVED, ["R", "U", "F2"])) == 3
    for n in (4, 5):
        for _ in range(5):
            d = optimal_distance(apply_moves(SOLVED, random_scramble(n)))
            assert d is not None and d <= n
