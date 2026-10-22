import asyncio
import math

import chess
import pytest

from chess3d.api.__main__ import carrier_service
from chess3d.chess_layer.bridge import ChessBridge, node_of
from chess3d.motion.carriers import CarrierFleet, segments
from chess3d.motion.planner import Planner, step_seconds
from chess3d.world import World

DT = step_seconds(0.3)


def test_segments_split_on_waits():
    assert segments([1, 2, 3, 3, 3, 4, 4]) == [(0, 2), (4, 5)]
    assert segments([5, 5, 5]) == []


def check_schedule(planner, world, sched, count):
    lat = planner.lat
    assert planner.verify(world, sched.plan) == []
    assert sched.plan.peak_concurrency() <= count
    by_carrier: dict[str, list] = {}
    for job in sched.jobs:
        by_carrier.setdefault(job.carrier, []).append(job)
    carried = set()
    for jobs in by_carrier.values():
        jobs.sort(key=lambda j: j.t0)
        for a, b in zip(jobs, jobs[1:]):
            assert a.t1 <= b.t0, "a carrier does two jobs at once"
            assert math.dist(a.end, b.start) < 1e-6, "a carrier teleports"
        for job in jobs:
            if job.kind == "carry":
                carried.add(job.piece)
                traj = sched.plan.trajectories[job.piece]
                start = tuple(map(float, lat.xy[traj[job.t0]]))
                assert math.dist(start, job.start) < 1e-6
    moved = {pid for pid, tr in sched.plan.trajectories.items() if len(set(tr)) > 1}
    assert moved <= carried, "a piece moved without a carrier"


@pytest.mark.parametrize("count", [1, 2, 4])
def test_clearing_move_with_carriers(count):
    planner = Planner(penalty=1.0, max_moving=count)
    world = World.initial()
    fleet = CarrierFleet(planner.lat, count, DT)
    plan = planner.plan(world, "wBc1", node_of(chess.E3))
    sched = fleet.schedule(plan)
    check_schedule(planner, world, sched, count)
    assert sched.plan.steps >= plan.steps


def test_capture_sequence_with_one_carrier():
    planner = Planner(max_moving=1)
    world = World.initial()
    bridge = ChessBridge(world)
    fleet = CarrierFleet(planner.lat, 1, DT)
    for uci in ["e2e4", "d7d5", "e4d5"]:
        move = chess.Move.from_uci(uci)
        tasks = bridge.tasks(move)
        plan = planner.plan_sequence(world, [(t.piece_id, t.goal) for t in tasks])
        sched = fleet.schedule(plan)
        check_schedule(planner, world, sched, 1)
        planner.apply(world, sched.plan)
        bridge.commit(move, tasks)
    assert world.is_parked(world.pieces["bPd7"])


def test_spread_puts_carriers_on_distinct_field_points():
    planner = Planner()
    fleet = CarrierFleet(planner.lat, 6, DT)
    fleet.spread()
    points = {(round(c.x, 3), round(c.y, 3)) for c in fleet.carriers}
    assert len(points) == 6
    assert all(0 < x < 3 and 0 < y < 3 for x, y in points)


def test_service_runs_with_carriers():
    svc = carrier_service(World.initial(), 3, 0.3, 1.0)
    svc.executor.realtime = False

    async def play():
        for san in ["e4", "e5", "Nf3"]:
            await svc.move(san)

    asyncio.run(play())
    snap = svc.snapshot()
    assert len(snap["carriers"]) == 3
    assert snap["history"] == ["e4", "e5", "Nf3"]
