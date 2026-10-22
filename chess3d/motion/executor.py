"""Runs plans on movers.

SimExecutor drives ideal SimMovers. TrackingExecutor sends timed paths to
real (or emulated) movers and watches their reported poses; any piece that
leaves its expected position, goes silent, or does not arrive stops the whole
plan with an ExecutionFault.
"""

from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass

from ..world import World
from ..movers.base import Mover, MoverState, Waypoint
from ..movers.sim import SimMover
from .lattice import Lattice
from .planner import Plan, step_seconds


def waypoints(lat: Lattice, traj: list[int], dt: float) -> list[Waypoint]:
    """Keep only the corners and waits of a trajectory, with their times."""
    pts = []
    for t, n in enumerate(traj):
        x, y = lat.xy[n]
        pts.append(Waypoint(float(x), float(y), t * dt))
    keep = [pts[0]]
    for prev, cur, nxt in zip(pts, pts[1:], pts[2:]):
        straight = (abs((cur.x - prev.x) - (nxt.x - cur.x)) < 1e-9
                    and abs((cur.y - prev.y) - (nxt.y - cur.y)) < 1e-9)
        if not straight:
            keep.append(cur)
    if len(pts) > 1:
        keep.append(pts[-1])
    return keep


def position_at(path: list[Waypoint], t: float) -> tuple[float, float]:
    if t <= path[0].t:
        return path[0].x, path[0].y
    for a, b in zip(path, path[1:]):
        if t <= b.t:
            f = (t - a.t) / (b.t - a.t) if b.t > a.t else 1.0
            return a.x + f * (b.x - a.x), a.y + f * (b.y - a.y)
    return path[-1].x, path[-1].y


def facing(world: World, piece_id: str) -> float:
    """Pieces face the opponent: white towards rank 8, black towards rank 1."""
    return 0.0 if world.pieces[piece_id].white else math.pi


class ExecutionFault(RuntimeError):
    def __init__(self, piece_id: str, reason: str, expected: tuple[float, float] | None = None,
                 actual: tuple[float, float] | None = None, detail: str = "") -> None:
        self.piece_id = piece_id
        self.reason = reason
        self.expected = expected
        self.actual = actual
        msg = f"{piece_id}: {reason}"
        if expected and actual:
            msg += f" ({math.dist(expected, actual) * 100:.1f}cm off)"
        if detail:
            msg += f": {detail}"
        super().__init__(msg)

    def as_dict(self) -> dict:
        return {"piece": self.piece_id, "reason": self.reason, "message": str(self),
                "expected": self.expected, "actual": self.actual}


class SimExecutor:
    def __init__(self, lattice: Lattice, movers: dict[str, Mover], speed: float = 0.3,
                 time_scale: float = 1.0, realtime: bool = True) -> None:
        self.lat = lattice
        self.movers = movers
        self.dt = step_seconds(speed)
        self.time_scale = time_scale
        self.realtime = realtime

    def prepare(self, plan: Plan) -> tuple[Plan, dict]:
        """Last change to a plan before it runs, plus extra event fields."""
        return plan, {}

    async def execute(self, plan: Plan, world: World) -> float:
        duration = plan.steps * self.dt
        if self.realtime and duration:
            await asyncio.sleep(duration / self.time_scale)
        return self.run(plan, world)

    async def settle(self, world: World) -> None:
        for pid, p in world.pieces.items():
            m = self.movers.get(pid)
            if isinstance(m, SimMover):
                x, y = self.lat.xy[self.lat.index(p.node)]
                m.follow_path([Waypoint(float(x), float(y), 0.0)])
                m.advance(0.0)

    def run(self, plan: Plan, world: World) -> float:
        """Dispatch all trajectories at once; returns the plan duration in seconds."""
        for pid, traj in plan.trajectories.items():
            self.movers[pid].follow_path(waypoints(self.lat, traj, self.dt))
        duration = plan.steps * self.dt
        sims = [m for m in self.movers.values() if isinstance(m, SimMover)]
        t = 0.0
        while t < duration:
            t = min(t + self.dt, duration)
            for m in sims:
                m.advance(t)
        for pid in plan.trajectories:
            if self.movers[pid].state() == MoverState.FAULT:
                raise ExecutionFault(pid, "mover fault")
            self.movers[pid].rotate_to(facing(world, pid))
            world.pieces[pid].node = self.lat.node(plan.trajectories[pid][-1])
        return duration


# Kept for callers that run plans synchronously (benchmark, tests).
Executor = SimExecutor


class CarrierSimExecutor(SimExecutor):
    """Option 2b in simulation: carriers under the board move the pieces.

    Plans must come from a Planner(max_moving=len(fleet.carriers)).
    """

    def __init__(self, lattice: Lattice, movers: dict[str, Mover], fleet, speed: float = 0.3,
                 time_scale: float = 1.0, realtime: bool = True, spread: bool = True) -> None:
        super().__init__(lattice, movers, speed, time_scale, realtime)
        self.fleet = fleet
        self.spread = spread

    def prepare(self, plan: Plan) -> tuple[Plan, dict]:
        sched = self.fleet.schedule(plan)
        return sched.plan, {"carriers": sched.carrier_paths(self.lat, self.dt),
                            "carrier_wait": sched.inserted_steps * self.dt}

    async def execute(self, plan: Plan, world: World) -> float:
        duration = await super().execute(plan, world)
        if self.spread:
            self.fleet.spread()
        return duration

    def carrier_positions(self) -> list[dict]:
        return [{"id": c.id, "x": c.x, "y": c.y, "under": c.under} for c in self.fleet.carriers]


@dataclass
class Tolerances:
    tracking: float = 0.03  # max distance from the expected position while moving
    resting: float = 0.02  # max drift of a piece that should stand still
    arrival: float = 0.015  # max distance from the goal at the end
    lag: float = 0.25  # status age allowance, seconds
    settle: float = 2.0  # time allowed after the plan to report arrival


class TrackingExecutor:
    def __init__(self, lattice: Lattice, movers: dict[str, Mover], speed: float = 0.3,
                 tolerances: Tolerances | None = None, poll: float = 0.05,
                 start_delay: float = 0.2) -> None:
        self.lat = lattice
        self.movers = movers
        self.dt = step_seconds(speed)
        self.speed = speed
        self.tol = tolerances or Tolerances()
        self.poll = poll
        self.start_delay = start_delay
        self.time_scale = 1.0

    def prepare(self, plan: Plan) -> tuple[Plan, dict]:
        return plan, {}

    async def execute(self, plan: Plan, world: World) -> float:
        lat = self.lat
        paths = {pid: waypoints(lat, tr, self.dt) for pid, tr in plan.trajectories.items()
                 if len(set(tr)) > 1}
        duration = plan.steps * self.dt
        await self._run(paths, world, duration)
        for pid in paths:
            world.pieces[pid].node = lat.node(plan.trajectories[pid][-1])
        return duration

    async def settle(self, world: World) -> None:
        """Drive every piece that is off its lattice node straight onto it.

        Used after a fault, once the world has been snapped to the sensed
        poses: offsets are below half a lattice step, far less than the gap
        between pieces.
        """
        paths = {}
        for pid, p in world.pieces.items():
            if pid not in self.movers:
                continue
            goal = tuple(map(float, self.lat.xy[self.lat.index(p.node)]))
            actual = self._xy(pid)
            d = math.dist(actual, goal)
            if d > self.tol.arrival:
                paths[pid] = [Waypoint(*actual, 0.0), Waypoint(*goal, max(d / self.speed, 0.3))]
        if paths:
            await self._run(paths, world, max(p[-1].t for p in paths.values()))

    async def _run(self, paths: dict[str, list[Waypoint]], world: World, duration: float) -> None:
        lat = self.lat
        resting = {pid: tuple(map(float, lat.xy[lat.index(p.node)]))
                   for pid, p in world.pieces.items() if pid not in paths and pid in self.movers}
        try:
            for pid, path in paths.items():
                self.movers[pid].follow_path(path, heading=facing(world, pid),
                                             start_ms=int(self.start_delay * 1000))
            t0 = time.monotonic() + self.start_delay
            while True:
                await asyncio.sleep(self.poll)
                t = time.monotonic() - t0
                self._check_resting(resting)
                done = t > duration
                for pid, path in paths.items():
                    self._check_tracking(pid, path, t, final=done)
                if done and self._arrived(paths):
                    break
                if t > duration + self.tol.settle:
                    pid = next(p for p in paths if not self._arrived({p: paths[p]}))
                    raise ExecutionFault(pid, "did not arrive", (paths[pid][-1].x, paths[pid][-1].y),
                                         self._xy(pid))
        except ExecutionFault:
            self.stop_all()
            raise

    def stop_all(self) -> None:
        for m in self.movers.values():
            stop = getattr(m, "stop", None)
            if stop:
                try:
                    stop()
                except RuntimeError:
                    pass

    def _xy(self, pid: str) -> tuple[float, float]:
        p = self.movers[pid].pose()
        return (p.x, p.y)

    def _alive(self, pid: str) -> None:
        m = self.movers[pid]
        if m.state() == MoverState.FAULT:
            detail = getattr(m, "error", lambda: None)() or ""
            raise ExecutionFault(pid, "mover lost", detail=detail)

    def _check_resting(self, resting: dict[str, tuple[float, float]]) -> None:
        for pid, xy in resting.items():
            self._alive(pid)
            actual = self._xy(pid)
            if math.dist(actual, xy) > self.tol.resting:
                raise ExecutionFault(pid, "displaced", xy, actual)

    def _check_tracking(self, pid: str, path: list[Waypoint], t: float, final: bool) -> None:
        self._alive(pid)
        actual = self._xy(pid)
        if final:
            return  # arrival is judged by _arrived
        m = self.movers[pid]
        progress = getattr(m, "progress", lambda: None)()
        if progress is not None:
            # The status says how far into the plan the mover is: compare
            # against exactly that point and make sure it keeps up.
            plan_id, prog = progress
            if plan_id != getattr(m, "plan_id", None):
                if t > self.tol.lag * 2:
                    raise ExecutionFault(pid, "path not started", detail=f"status plan {plan_id}")
                return
            if prog <= 0.0:
                # Not started yet, or already finished this plan.
                if t > self.tol.lag * 2 and m.state() != MoverState.MOVING:
                    goal = (path[-1].x, path[-1].y)
                    if math.dist(actual, goal) > self.tol.arrival:
                        raise ExecutionFault(pid, "stopped early", goal, actual)
                return
            expected = position_at(path, prog)
            if math.dist(actual, expected) > self.tol.tracking:
                raise ExecutionFault(pid, "left its path", expected, actual)
            if t - prog > self.tol.lag + 0.1:  # status period plus margin
                raise ExecutionFault(pid, "fell behind", position_at(path, t), actual,
                                     detail=f"{t - prog:.2f}s late")
            return
        # No progress reports: accept any expected position in the recent past.
        samples = [position_at(path, t - k * self.tol.lag / 4) for k in range(5)]
        err = min(math.dist(actual, s) for s in samples)
        if err > self.tol.tracking:
            raise ExecutionFault(pid, "left its path", samples[0], actual)

    def _arrived(self, paths: dict[str, list[Waypoint]]) -> bool:
        for pid, path in paths.items():
            m = self.movers[pid]
            goal = (path[-1].x, path[-1].y)
            if m.state() == MoverState.MOVING or math.dist(self._xy(pid), goal) > self.tol.arrival:
                return False
        return True
