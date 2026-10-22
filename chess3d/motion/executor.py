"""Turns a lattice plan into timed waypoints and runs it on movers."""

from __future__ import annotations

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


class Executor:
    def __init__(self, lattice: Lattice, movers: dict[str, Mover], speed: float = 0.3) -> None:
        self.lat = lattice
        self.movers = movers
        self.dt = step_seconds(speed)

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
                raise RuntimeError(f"mover {pid} reported a fault")
            world.pieces[pid].node = self.lat.node(plan.trajectories[pid][-1])
        return duration
