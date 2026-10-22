"""Carrier scheduling for option 2b: robots under the board move the pieces.

A piece plan (planned with Planner(max_moving=K)) is cut into motion
segments: maximal intervals in which one piece keeps moving. Each segment
needs a carrier under the piece. Carriers are assigned greedily in start
order, choosing the one that can be under the piece first; a carrier
already under that piece is reused without travel or pick-up time. When no
carrier can make it in time, the whole board freezes until it arrives:
inserting the same wait into every trajectory keeps the plan collision-free.

Carriers drive in the cavity in straight lines; collisions between carriers
are not modelled yet.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .lattice import Lattice
from .planner import Plan

PICK_SECONDS = 0.5  # engage the magnet under a piece


@dataclass
class Carrier:
    id: str
    x: float
    y: float
    under: str | None = None  # piece the carrier is engaged with
    busy_until: int = 0  # step (in the current plan) when its last job ends


@dataclass
class CarrierJob:
    carrier: str
    kind: str  # "travel" or "carry"
    t0: int  # steps in the stretched plan
    t1: int
    piece: str | None = None
    start: tuple[float, float] = (0.0, 0.0)
    end: tuple[float, float] = (0.0, 0.0)


@dataclass
class CarrierSchedule:
    plan: Plan  # the piece plan, stretched by the inserted waits
    jobs: list[CarrierJob] = field(default_factory=list)
    inserted_steps: int = 0
    empty_distance: float = 0.0

    def carrier_paths(self, lattice: Lattice, dt: float) -> dict[str, list[list[float]]]:
        """Timed [x, y, t] waypoints per carrier, for viewers. While carrying,
        a carrier follows the piece's own trajectory."""
        out: dict[str, list[list[float]]] = {}
        for job in sorted(self.jobs, key=lambda j: j.t0):
            pts = out.setdefault(job.carrier, [])
            if not pts:
                pts.append([job.start[0], job.start[1], 0.0])
            if job.kind == "travel":
                pts.append([job.start[0], job.start[1], job.t0 * dt])
                pts.append([job.end[0], job.end[1], job.t1 * dt])
            else:
                traj = self.plan.trajectories[job.piece]
                for t in range(job.t0, job.t1 + 1):
                    x, y = lattice.xy[traj[min(t, len(traj) - 1)]]
                    pts.append([float(x), float(y), t * dt])
        return out


def segments(traj: list[int]) -> list[tuple[int, int]]:
    """(t0, t1) intervals of continuous motion: moves from t0 to t1."""
    out = []
    t = 0
    while t + 1 < len(traj):
        if traj[t] != traj[t + 1]:
            t0 = t
            while t + 1 < len(traj) and traj[t] != traj[t + 1]:
                t += 1
            out.append((t0, t))
        else:
            t += 1
    return out


class CarrierFleet:
    def __init__(self, lattice: Lattice, count: int, dt: float, speed: float = 0.4,
                 pick_seconds: float = PICK_SECONDS,
                 home: list[tuple[float, float]] | None = None) -> None:
        self.lat = lattice
        self.dt = dt
        self.speed = speed
        self.pick_steps = math.ceil(pick_seconds / dt)
        if home is None:
            # Spread along the lane between the board and the parking area.
            x = min(lattice.layout.width, 3.0)
            depth = lattice.layout.depth
            home = [(x, depth * (k + 0.5) / count) for k in range(count)]
        self.carriers = [Carrier(f"c{k + 1}", *home[k]) for k in range(count)]

    def schedule(self, plan: Plan) -> CarrierSchedule:
        lat = self.lat
        segs = []
        for pid, traj in plan.trajectories.items():
            for t0, t1 in segments(traj):
                segs.append((t0, t1, pid, traj))
        segs.sort(key=lambda s: (s[0], s[2]))
        inserts: list[tuple[int, int]] = []  # (original step, extra steps)

        def start_shift(t: int) -> int:
            return t + sum(n for at, n in inserts if at <= t)

        def end_shift(t: int) -> int:
            return t + sum(n for at, n in inserts if at < t)

        for c in self.carriers:
            c.busy_until = 0
        pending: list[tuple] = []
        for t0, t1, pid, traj in segs:
            sx, sy = map(float, lat.xy[traj[t0]])
            free = [c for c in self.carriers if c.busy_until <= t0]
            if not free:
                raise RuntimeError("more pieces move at once than there are carriers; "
                                   "plan with Planner(max_moving=len(carriers))")
            best, best_ready, best_travel = None, math.inf, 0
            for c in free:
                if c.under == pid and math.dist((c.x, c.y), (sx, sy)) < 1e-6:
                    travel = 0
                else:
                    travel = math.ceil(math.dist((c.x, c.y), (sx, sy)) / self.speed / self.dt) + self.pick_steps
                ready = end_shift(c.busy_until) + travel
                if ready < best_ready:
                    best, best_ready, best_travel = c, ready, travel
            need = start_shift(t0)
            if best_ready > need:
                inserts.append((t0, best_ready - need))
            if best_travel:
                pending.append(("travel", best.id, best.busy_until, best_travel, pid,
                                (best.x, best.y), (sx, sy)))
            ex, ey = map(float, lat.xy[traj[t1]])
            pending.append(("carry", best.id, t0, t1, pid, (sx, sy), (ex, ey)))
            best.x, best.y, best.under, best.busy_until = ex, ey, pid, t1

        sched = CarrierSchedule(self._stretch(plan, inserts), inserted_steps=sum(n for _, n in inserts))
        for kind, cid, a, b, pid, start, end in pending:
            if kind == "travel":
                t0 = end_shift(a)
                sched.jobs.append(CarrierJob(cid, kind, t0, t0 + b, pid, start, end))
                sched.empty_distance += math.dist(start, end)
            else:
                sched.jobs.append(CarrierJob(cid, kind, start_shift(a), end_shift(b), pid, start, end))
        for c in self.carriers:
            c.busy_until = 0
        return sched

    def spread(self) -> float:
        """Between moves (while players think): send the carriers to evenly
        spread rest points over the field, disengaged. Returns the longest
        trip in metres; it costs no game time unless the next move comes
        sooner than that trip takes."""
        n = len(self.carriers)
        cols = math.ceil(math.sqrt(n))
        rows = math.ceil(n / cols)
        lay = self.lat.layout
        field = min(lay.width, lay.depth)  # the square board area
        points = [(field * (c + 0.5) / cols, field * (r + 0.5) / rows)
                  for r in range(rows) for c in range(cols)][:n]
        longest = 0.0
        free = list(self.carriers)
        for px, py in points:
            c = min(free, key=lambda c: math.dist((c.x, c.y), (px, py)))
            free.remove(c)
            longest = max(longest, math.dist((c.x, c.y), (px, py)))
            c.x, c.y, c.under = px, py, None
        return longest

    @staticmethod
    def _stretch(plan: Plan, inserts: list[tuple[int, int]]) -> Plan:
        trajs = {}
        for pid, traj in plan.trajectories.items():
            tr = list(traj)
            for at, n in sorted(inserts, reverse=True):
                if at < len(tr):
                    tr[at + 1:at + 1] = [tr[at]] * n
            trajs[pid] = tr
        return Plan(plan.piece_id, plan.goal, trajs, blockers=list(plan.blockers))
