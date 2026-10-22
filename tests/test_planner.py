import chess
import pytest

from chess3d.chess_layer.bridge import ChessBridge, node_of
from chess3d.geometry import FOOTPRINTS, GRID, SQUARE, Kind, node_xy, square_node
from chess3d.motion.planner import Plan, Planner, PlanningError
from chess3d.motion.executor import Executor
from chess3d.movers.base import Pose
from chess3d.movers.sim import SimMover
from chess3d.world import Piece, World


@pytest.fixture(scope="module")
def planner():
    return Planner(penalty=1.0)


def test_square_centres_lie_on_lattice():
    x, y = node_xy(*square_node(0, 0))
    assert x == pytest.approx(SQUARE) and y == pytest.approx(SQUARE)
    x, y = node_xy(*square_node(7, 7))
    assert x == pytest.approx(8 * SQUARE) and y == pytest.approx(8 * SQUARE)
    assert SQUARE / GRID == pytest.approx(6)


def test_pawns_fill_half_a_square():
    assert FOOTPRINTS[Kind.PAWN].base_diameter == pytest.approx(0.51 * SQUARE)
    assert FOOTPRINTS[Kind.KING].height > 0.5


def test_blocked_bishop_clears_and_restores(planner):
    world = World.initial()
    before = {p.id: p.node for p in world.pieces.values()}
    # Bc1-e3 with the d2 pawn still at home: the planner must displace it.
    plan = planner.plan(world, "wBc1", node_of(chess.E3))
    assert planner.verify(world, plan) == []
    assert "wPd2" in plan.blockers
    planner.apply(world, plan)
    assert world.pieces["wBc1"].node == node_of(chess.E3)
    for pid, node in before.items():
        if pid != "wBc1":
            assert world.pieces[pid].node == node, pid


def test_knight_from_start_position(planner):
    world = World.initial()
    plan = planner.plan(world, "wNg1", node_of(chess.F3))
    assert planner.verify(world, plan) == []
    assert plan.trajectories["wNg1"][-1] == planner.lat.index(node_of(chess.F3))


def test_occupied_goal_is_rejected(planner):
    world = World.initial()
    with pytest.raises(PlanningError):
        planner.plan(world, "wNg1", node_of(chess.E2))


def test_verify_detects_collision(planner):
    world = World.initial()
    lat = planner.lat
    # The e2 pawn slides sideways straight into the d2 pawn.
    start = lat.index(node_of(chess.E2))
    i, j = lat.node(start)
    path = [lat.index((i - k, j)) for k in range(4)]
    plan = Plan("wPe2", lat.node(path[-1]), {"wPe2": path})
    assert planner.verify(world, plan)


def test_capture_overlaps_with_attacker(planner):
    world = World.initial()
    bridge = ChessBridge(world)
    for uci in ["e2e4", "d7d5"]:
        move = chess.Move.from_uci(uci)
        tasks = bridge.tasks(move)
        planner.apply(world, planner.plan_sequence(world, [(t.piece_id, t.goal) for t in tasks]))
        bridge.commit(move, tasks)
    move = chess.Move.from_uci("e4d5")
    tasks = bridge.tasks(move)
    assert [t.reason for t in tasks] == ["capture", "move"]
    seq = planner.plan_sequence(world, [(t.piece_id, t.goal) for t in tasks])
    assert planner.verify(world, seq) == []
    separate = planner.plan(world, tasks[0].piece_id, tasks[0].goal).steps
    assert seq.steps < separate + 12  # attacker does not wait for the full trip


def play(bridge: ChessBridge, planner: Planner, ucis: list[str]) -> list:
    tasks = []
    for uci in ucis:
        move = chess.Move.from_uci(uci)
        tasks = bridge.tasks(move)
        plan = planner.plan_sequence(bridge.world, [(t.piece_id, t.goal) for t in tasks])
        assert planner.verify(bridge.world, plan) == [], uci
        planner.apply(bridge.world, plan)
        bridge.commit(move, tasks)
    return tasks


def test_castling_moves_king_and_rook(planner):
    world = World.initial()
    bridge = ChessBridge(world)
    tasks = play(bridge, planner, ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "g8f6", "e1g1"])
    assert [t.reason for t in tasks] == ["castle king", "castle rook"]
    assert world.pieces["wKe1"].node == node_of(chess.G1)
    assert world.pieces["wRh1"].node == node_of(chess.F1)


def test_en_passant_parks_victim(planner):
    world = World.initial()
    bridge = ChessBridge(world)
    tasks = play(bridge, planner, ["e2e4", "a7a6", "e4e5", "d7d5", "e5d6"])
    assert tasks[0].reason == "capture en passant"
    assert world.is_parked(world.pieces["bPd7"])


def test_promotion_brings_spare_queen(planner):
    board = chess.Board("8/P6k/8/8/8/8/8/K7 w - - 0 1")
    world = World()
    world.add(Piece("wPa2", Kind.PAWN, True, node_of(chess.A7)))
    world.add(Piece("wKe1", Kind.KING, True, node_of(chess.A1)))
    world.add(Piece("bKe8", Kind.KING, False, node_of(chess.H7)))
    world.add(Piece("wQspare1", Kind.QUEEN, True, world.free_slot()))
    bridge = ChessBridge(world, board)
    tasks = play(bridge, planner, ["a7a8q"])
    assert [t.reason for t in tasks] == ["promoted pawn leaves", "promotion"]
    assert world.pieces["wQspare1"].node == node_of(chess.A8)
    assert world.is_parked(world.pieces["wPa2"])


def test_executor_moves_sim_movers(planner):
    world = World.initial()
    lat = planner.lat
    movers = {p.id: SimMover(p.id, Pose(*lat.xy[lat.index(p.node)], 0.0))
              for p in world.pieces.values()}
    plan = planner.plan(world, "wBc1", node_of(chess.E3))
    seconds = Executor(lat, movers).run(plan, world)
    assert seconds > 0
    pose = movers["wBc1"].pose()
    assert (pose.x, pose.y) == pytest.approx(tuple(lat.xy[lat.index(node_of(chess.E3))]))
    assert world.pieces["wBc1"].node == node_of(chess.E3)
