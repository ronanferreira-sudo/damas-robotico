from damas.draughts import BoardState, choose_move
from damas.game import plan_actions
from damas.robot.kinematics import BoardToRobot, grid_squares


def test_choose_move_legal_from_start():
    state = BoardState()
    move = choose_move(state, backend="minimax", minimax_depth=2)
    assert move is not None
    assert state.is_legal(move)


def test_choose_move_captures_free_piece():
    # Torre branca em a1 pode capturar torre preta em a8 (xeque-mate simples de teste).
    state = BoardState("8/4r3/8/8/8/8/8/R3K2k w Q - 0 1")
    move = choose_move(state, backend="minimax", minimax_depth=3)
    assert move is not None
    assert state.is_legal(move)


def test_plan_actions_simple_move():
    prev = {"e2": "P"}
    new = {"e4": "P"}
    actions = plan_actions(prev, new)
    assert actions == [("move", "white", "e2", "e4")]


def test_plan_actions_capture():
    prev = {"e4": "P", "d5": "p"}
    new = {"d5": "P"}
    actions = plan_actions(prev, new)
    moves = [a for a in actions if a[0] == "move"]
    captures = [a for a in actions if a[0] == "capture"]
    assert ("move", "white", "e4", "d5") in moves
    assert ("capture", "black", "d5", None) in captures


def test_plan_actions_castling():
    prev = {"e1": "K", "h1": "R"}
    new = {"g1": "K", "f1": "R"}
    actions = plan_actions(prev, new)
    moves = {(a[2], a[3]) for a in actions if a[0] == "move"}
    assert ("e1", "g1") in moves
    assert ("h1", "f1") in moves


def test_kinematics_alignment():
    kin = BoardToRobot(origin_x=100.0, origin_y=-100.0, spacing=45.0, rotation_deg=0.0)
    assert kin.to_xy("a1") == (100.0, -100.0)
    assert kin.to_xy("b1") == (145.0, -100.0)
    x, y = kin.to_xy("a2")
    assert abs(x - 100.0) < 1e-6 and abs(y - (-55.0)) < 1e-6


def test_kinematics_rotation():
    kin = BoardToRobot(origin_x=0.0, origin_y=0.0, spacing=10.0, rotation_deg=90.0)
    # file 'b' (dx=10) rotacionado 90graus vira (0,10)
    x, y = kin.to_xy("b1")
    assert abs(x) < 1e-6 and abs(y - 10.0) < 1e-6


def test_grid_squares_4x4():
    squares = grid_squares(4, 4)
    assert len(squares) == 16
    assert squares[0] == "a1"
    assert squares[3] == "d1"
    assert squares[-1] == "d4"
    assert set(squares) == {f"{f}{r}" for f in "abcd" for r in "1234"}


def test_grid_squares_8x8():
    squares = grid_squares(8, 8)
    assert len(squares) == 64
    assert squares[0] == "a1"
    assert squares[-1] == "h8"


def test_kinematics_4x4():
    kin = BoardToRobot(origin_x=0.0, origin_y=0.0, spacing=10.0, rotation_deg=0.0)
    assert kin.to_xy("a1") == (0.0, 0.0)
    x, y = kin.to_xy("d4")
    assert abs(x - 30.0) < 1e-6 and abs(y - 30.0) < 1e-6
