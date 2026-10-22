"""Endurance test for the a1-d4 rig: random free moves, measured.

    python tools/rig_cycle.py --emulate --moves 100 --slip-rate 0.05
    python tools/rig_cycle.py --udp 4210 --moves 500          # real feet

Each cycle moves a random piece to a random free rig square. Reports final
position errors, faults, how many were recovered automatically, and pauses
(resolved here with resume(adopt=True), standing in for a human).
"""

from __future__ import annotations

import argparse
import asyncio
import math
import random
import statistics
import sys
import time
from pathlib import Path

import chess

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chess3d.chess_layer.bridge import node_of  # noqa: E402
from chess3d.geometry import RIG_SQUARES  # noqa: E402
from chess3d.hardware import Hardware  # noqa: E402
from chess3d.service import Paused, ServiceError  # noqa: E402
from chess3d.world import World  # noqa: E402

RIG_SQUARE_NAMES = [chess.square_name(chess.square(f, r))
                    for f in range(RIG_SQUARES) for r in range(RIG_SQUARES)]


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--moves", type=int, default=100)
    ap.add_argument("--udp", type=int, default=0, help="UDP port for real feet")
    ap.add_argument("--emulate", action="store_true")
    ap.add_argument("--speed", type=float, default=0.3)
    ap.add_argument("--noise", type=float, default=0.0, help="emulated pose noise (m)")
    ap.add_argument("--slip-rate", type=float, default=0.0, help="emulated slips per move")
    ap.add_argument("--stall-rate", type=float, default=0.0, help="emulated stalls per move")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    if not args.emulate and not args.udp:
        ap.error("use --emulate or --udp PORT")

    rng = random.Random(args.seed)
    hw = Hardware(World.rig(), port=args.udp, speed=args.speed,
                  emulate=args.emulate, noise=args.noise)
    missing = await hw.start()
    if missing:
        print("missing feet:", ", ".join(missing))
        await hw.close()
        return 1
    svc = hw.service
    faults: list[str] = []
    svc_events = svc.subscribe()
    errors, durations = [], []
    recovered = paused = failed_resume = unplannable = 0
    started = time.time()
    try:
        for k in range(args.moves):
            occupied = {p.node for p in svc.world.pieces.values()}
            pid = rng.choice(list(svc.world.pieces))
            free = [s for s in RIG_SQUARE_NAMES if node_of(chess.parse_square(s)) not in occupied]
            target = rng.choice(free)
            if args.emulate:
                foot = hw.fleet.feet[pid]
                if rng.random() < args.slip_rate:
                    foot.faults.used.discard("slip")
                    foot.faults.slip = (rng.uniform(0.2, 1.0), rng.uniform(-0.06, 0.06),
                                        rng.uniform(-0.06, 0.06))
                if rng.random() < args.stall_rate:
                    foot.faults.stall_after = rng.uniform(0.2, 1.0)
            n_before = len(faults)
            try:
                result = await svc.goto(pid, target)
                durations.append(result["seconds"])
            except Paused:
                paused += 1
                if args.emulate:
                    for f in hw.fleet.feet.values():
                        f.faults.stall_after = None  # the "human" clears the obstruction
                if not (await svc.resume(adopt=True))["resumed"]:
                    failed_resume += 1
                    break
            except ServiceError as e:
                unplannable += 1
                print(f"  move {k + 1}: {pid} to {target}: {e}")
            while not svc_events.empty():
                ev = svc_events.get_nowait()
                if ev["type"] == "fault":
                    faults.append(ev["message"])
            if len(faults) > n_before and not svc.fault:
                recovered += 1
            for p in svc.world.pieces.values():
                x, y = svc.lat.xy[svc.lat.index(p.node)]
                pose = hw.service.movers[p.id].pose()
                errors.append(math.dist((x, y), (pose.x, pose.y)))
    finally:
        await hw.close()

    print(f"moves {args.moves} in {time.time() - started:.0f}s, unplannable {unplannable}")
    if durations:
        print(f"move time mean {statistics.mean(durations):.1f}s max {max(durations):.1f}s")
    if errors:
        e = sorted(errors)
        print(f"rest position error mean {statistics.mean(e) * 1000:.1f}mm "
              f"p95 {e[int(0.95 * (len(e) - 1))] * 1000:.1f}mm max {e[-1] * 1000:.1f}mm")
    print(f"faults {len(faults)}, recovered automatically {recovered}, paused {paused}, "
          f"resume failed {failed_resume}")
    return 0 if not failed_resume else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
