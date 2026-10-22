"""Replay games through the planner and report physical move times.

    python tools/benchmark.py data/sample.pgn
    python tools/benchmark.py --random 20 --plies 80 --seed 1

Each chess move becomes one or more motion tasks (capture, castling,
promotion). They are planned in order but may overlap in time, and within a
task all pieces move in parallel. Reports per-move wall time, displaced blockers and the peak number
of pieces moving at once (the carrier count option 2b would need).
"""

from __future__ import annotations

import argparse
import random
import statistics
import sys
import time
from pathlib import Path

import chess
import chess.pgn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chess3d.chess_layer.bridge import ChessBridge  # noqa: E402
from chess3d.motion.planner import PENALTY, Planner, PlanningError, step_seconds  # noqa: E402
from chess3d.world import World  # noqa: E402

SETTLE_SECONDS = 0.5  # per move: acceleration, final alignment, facing


def pgn_games(path: str):
    with open(path) as f:
        while (game := chess.pgn.read_game(f)) is not None:
            yield game.headers.get("White", "?") + " - " + game.headers.get("Black", "?"), list(game.mainline_moves())


def random_games(n: int, plies: int, seed: int):
    rng = random.Random(seed)
    for k in range(n):
        b = chess.Board()
        moves = []
        while len(moves) < plies and not b.is_game_over():
            legal = list(b.legal_moves)
            captures = [m for m in legal if b.is_capture(m)]
            m = rng.choice(captures if captures and rng.random() < 0.5 else legal)
            moves.append(m)
            b.push(m)
        yield f"random #{k + 1}", moves


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pgn", nargs="?")
    ap.add_argument("--random", type=int, default=0, help="number of random games")
    ap.add_argument("--plies", type=int, default=80)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--speed", type=float, default=0.3, help="top speed m/s")
    ap.add_argument("--target", type=float, default=15.0, help="move time target s")
    ap.add_argument("--penalty", type=float, default=PENALTY, help="blocker cost in lattice steps")
    ap.add_argument("--verify", action="store_true", help="collision-check every plan")
    args = ap.parse_args()

    games = []
    if args.pgn:
        games += list(pgn_games(args.pgn))
    if args.random:
        games += list(random_games(args.random, args.plies, args.seed))
    if not games:
        ap.error("give a PGN file and/or --random N")

    planner = Planner(penalty=args.penalty)
    dt = step_seconds(args.speed)
    times, blockers, peaks, failures, violations = [], [], [], 0, 0
    worst: tuple[float, str] = (0.0, "")
    t_start = time.time()
    for name, moves in games:
        world = World.initial()
        bridge = ChessBridge(world)
        for ply, move in enumerate(moves):
            san = bridge.board.san(move)
            tasks = bridge.tasks(move)
            try:
                plan = planner.plan_sequence(world, [(t.piece_id, t.goal) for t in tasks])
                if args.verify:
                    violations += len(planner.verify(world, plan))
                planner.apply(world, plan)
                seconds = plan.steps * dt + SETTLE_SECONDS
                nblock, peak = len(plan.blockers), plan.peak_concurrency()
            except PlanningError as e:
                failures += 1
                print(f"  FAIL {name} ply {ply + 1} {san}: {e}")
                break
            bridge.commit(move, tasks)
            times.append(seconds)
            blockers.append(nblock)
            peaks.append(peak)
            if seconds > worst[0]:
                worst = (seconds, f"{name} ply {ply + 1} {san}")

    times_sorted = sorted(times)
    p95 = times_sorted[int(0.95 * (len(times_sorted) - 1))] if times else 0.0
    print(f"games {len(games)}, moves {len(times)}, failures {failures}, "
          f"planning {time.time() - t_start:.1f}s")
    if times:
        print(f"move time  mean {statistics.mean(times):.1f}s  median {statistics.median(times):.1f}s  "
              f"p95 {p95:.1f}s  max {worst[0]:.1f}s ({worst[1]})")
        print(f"blockers   mean {statistics.mean(blockers):.2f}  max {max(blockers)}  "
              f"moves needing clearing {sum(1 for b in blockers if b) / len(blockers):.0%}")
        print(f"concurrent peak per move: max {max(peaks)}, "
              f"p95 {sorted(peaks)[int(0.95 * (len(peaks) - 1))]}")
        print(f"target {args.target:.0f}s at p95: {'PASS' if p95 < args.target and not failures else 'FAIL'}")
    if args.verify:
        print(f"collision violations: {violations}")
    return 0 if times and p95 < args.target and not failures and not violations else 1


if __name__ == "__main__":
    raise SystemExit(main())
