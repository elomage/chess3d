"""Multi-piece motion planner with path clearing.

To move one piece to a goal the planner:
1. Finds a blocker-aware route for the piece: the cheapest lattice path where
   every footprint overlap with another piece costs a penalty.
2. Collects the pieces that route touches (blockers). Each blocker gets a
   temporary spot off all corridors and its own blocker-aware route there,
   which may in turn reveal secondary blockers.
3. Plans everything in space-time (prioritised planning with a reservation
   table): blockers move out deepest first, then the piece, then the blockers
   return in reverse order. All agents move in parallel; an agent waits when
   its way is not yet free.
"""

from __future__ import annotations

import heapq
import itertools
import random
from dataclasses import dataclass, field

import numpy as np

from ..geometry import CLEARANCE, GRID
from ..world import Node, World
from .lattice import Lattice

PENALTY = 5.0
MAX_DEPTH = 4


class PlanningError(RuntimeError):
    pass


@dataclass
class Plan:
    piece_id: str
    goal: Node
    # Lattice node index per time step, starting at t=0. After its last entry
    # an agent stays where it is.
    trajectories: dict[str, list[int]] = field(default_factory=dict)
    blockers: list[str] = field(default_factory=list)

    @property
    def steps(self) -> int:
        return max((len(t) - 1 for t in self.trajectories.values()), default=0)

    def moving_at(self, t: int) -> int:
        """Number of agents changing position between t and t+1."""
        return sum(1 for tr in self.trajectories.values()
                   if t + 1 < len(tr) and tr[t] != tr[t + 1])

    def peak_concurrency(self) -> int:
        return max((self.moving_at(t) for t in range(self.steps)), default=0)


class _Reservations:
    """Trajectories of already planned agents, padded to a fixed horizon."""

    def __init__(self, lattice: Lattice, horizon: int) -> None:
        self.lat = lattice
        self.horizon = horizon
        self.agents: dict[str, tuple[list[int], float]] = {}

    def set(self, agent: str, traj: list[int], radius: float) -> None:
        self.agents[agent] = (traj, radius)

    def arrays(self, exclude: str) -> tuple[np.ndarray, np.ndarray]:
        items = [(tr, r) for a, (tr, r) in self.agents.items() if a != exclude]
        pos = np.zeros((len(items), self.horizon + 1, 2))
        radii = np.zeros(len(items))
        for k, (tr, r) in enumerate(items):
            idx = np.array(tr[: self.horizon + 1])
            pos[k, : len(idx)] = self.lat.xy[idx]
            pos[k, len(idx):] = self.lat.xy[idx[-1]]
            radii[k] = r
        return pos, radii


class Planner:
    def __init__(self, lattice: Lattice | None = None, horizon: int = 600,
                 max_expansions: int = 200_000, retries: int = 6, seed: int = 0,
                 penalty: float = PENALTY) -> None:
        self.lat = lattice or Lattice()
        self.penalty = penalty
        self.horizon = horizon
        self.max_expansions = max_expansions
        self.retries = retries
        self.rng = random.Random(seed)

    # -- public -----------------------------------------------------------

    def plan(self, world: World, piece_id: str, goal: Node) -> Plan:
        return self.plan_sequence(world, [(piece_id, goal)])

    def plan_sequence(self, world: World, tasks: list[tuple[str, Node]]) -> Plan:
        """Plan tasks in order. A later task may start before an earlier one
        has finished, e.g. the capturing piece sets off while the captured
        one is still on its way to the parking area."""
        current = world.copy()
        trajs: dict[str, list[int]] = {}
        blockers: list[str] = []
        for piece_id, goal in tasks:
            new, order = self._plan_one(current, piece_id, goal, trajs)
            trajs.update(new)
            blockers += order
            for pid, tr in new.items():
                current.pieces[pid].node = self.lat.node(tr[-1])
        piece_id, goal = tasks[-1]
        return Plan(piece_id, goal, trajs, blockers=blockers)

    def _plan_one(self, world: World, piece_id: str, goal: Node,
                  prior: dict[str, list[int]]) -> tuple[dict[str, list[int]], list[str]]:
        lat = self.lat
        mover = world.pieces[piece_id]
        g = lat.index(goal)
        if not lat.valid[g]:
            raise PlanningError(f"goal {goal} outside the movable area")
        if lat.index(mover.node) == g:
            return {}, []
        others = [p for p in world.pieces.values() if p.id != piece_id]
        for p in others:
            if self._overlaps([g], mover.radius, p):
                raise PlanningError(f"goal {goal} is occupied by {p.id}")

        temps, depth = self._clearing(world, piece_id, g)
        moving = [piece_id, *temps]
        groups: dict[int, list[str]] = {}
        for q in temps:
            groups.setdefault(depth[q], []).append(q)

        last: PlanningError | None = None
        for attempt in range(self.retries):
            order_out: list[str] = []
            for d in sorted(groups, reverse=True):
                grp = list(groups[d])
                if attempt:
                    self.rng.shuffle(grp)
                order_out += grp
            try:
                trajs = self._schedule(world, piece_id, g, temps, order_out, moving, prior)
            except PlanningError as e:
                last = e
                continue
            return trajs, order_out
        raise last or PlanningError("no plan found")

    def apply(self, world: World, plan: Plan) -> None:
        for pid, traj in plan.trajectories.items():
            world.pieces[pid].node = self.lat.node(traj[-1])

    def verify(self, world: World, plan: Plan) -> list[str]:
        """Check every pair of pieces at every step and half step."""
        lat = self.lat
        ids = list(world.pieces)
        radii = np.array([world.pieces[i].radius for i in ids])
        steps = plan.steps
        pos = np.zeros((len(ids), steps + 1, 2))
        for k, pid in enumerate(ids):
            tr = plan.trajectories.get(pid, [lat.index(world.pieces[pid].node)])
            idx = np.array(tr + [tr[-1]] * (steps + 1 - len(tr)))
            pos[k] = lat.xy[idx]
            for a, b in zip(tr, tr[1:]):
                if a != b and b not in lat.neighbors[a]:
                    return [f"{pid} jumps from {lat.node(a)} to {lat.node(b)}"]
        need = radii[:, None] + radii[None, :] + CLEARANCE - 1e-9
        np.fill_diagonal(need, 0.0)
        errors = []
        for t in range(steps + 1):
            samples = [pos[:, t]]
            if t < steps:
                samples.append((pos[:, t] + pos[:, t + 1]) / 2)
            for p in samples:
                d = np.hypot(p[:, None, 0] - p[None, :, 0], p[:, None, 1] - p[None, :, 1])
                for a, b in zip(*np.nonzero(np.triu(d < need, 1))):
                    errors.append(f"t={t}: {ids[a]} and {ids[b]} too close ({d[a, b]:.3f}m)")
        return errors

    # -- clearing ---------------------------------------------------------

    def _overlaps(self, path: list[int], radius: float, piece) -> bool:
        pts = self.lat.xy[path]
        c = self.lat.xy[self.lat.index(piece.node)]
        d = np.hypot(pts[:, 0] - c[0], pts[:, 1] - c[1])
        return bool((d < radius + piece.radius + CLEARANCE - 1e-9).any())

    def _discs(self, pieces) -> list[tuple[np.ndarray, float]]:
        return [(self.lat.xy[self.lat.index(p.node)], p.radius) for p in pieces]

    def _route(self, start: int, radius: float, penalised) -> tuple[np.ndarray, np.ndarray]:
        """Blocker-aware Dijkstra: overlapping a penalised disc costs PENALTY."""
        cost_field = self.penalty * self.lat.overlap_count(radius, penalised).astype(float)
        return self.lat.cheapest_paths(start, cost_field)

    def _clearing(self, world: World, piece_id: str, goal: int):
        lat = self.lat
        mover = world.pieces[piece_id]
        start = lat.index(mover.node)
        others = [p for p in world.pieces.values() if p.id != piece_id]
        cost, parent = self._route(start, mover.radius, self._discs(others))
        path0 = lat.trace(parent, goal)

        corridors: list[tuple[np.ndarray, float]] = [(lat.xy[path0], mover.radius)]
        moving = {piece_id}
        temps: dict[str, int] = {}
        depth: dict[str, int] = {}
        queue: list[str] = []
        for p in others:
            if self._overlaps(path0, mover.radius, p):
                depth[p.id] = 1
                queue.append(p.id)

        while queue:
            qid = queue.pop(0)
            if qid in moving:
                continue
            if depth[qid] > MAX_DEPTH:
                raise PlanningError("clearing needs too many nested displacements")
            moving.add(qid)
            q = world.pieces[qid]
            origins = [p for p in world.pieces.values() if p.id != qid]
            free = lat.free_map(q.radius, self._discs(origins))
            for pts, rc in corridors:
                for c in pts:
                    free &= np.hypot(lat.xy[:, 0] - c[0], lat.xy[:, 1] - c[1]) >= q.radius + rc + CLEARANCE - 1e-9
            temp_discs = [(lat.xy[n], world.pieces[t].radius) for t, n in temps.items()]
            for c, r in temp_discs:
                free &= np.hypot(lat.xy[:, 0] - c[0], lat.xy[:, 1] - c[1]) >= q.radius + r + CLEARANCE - 1e-9
            penalised = self._discs(p for p in origins if p.id not in moving or p.id == piece_id)
            cost, parent = self._route(lat.index(q.node), q.radius, penalised + temp_discs)
            cand = np.flatnonzero(free & np.isfinite(cost))
            if cand.size == 0:
                raise PlanningError(f"no temporary spot for {qid}")
            temp = int(cand[np.argmin(cost[cand])])
            out = lat.trace(parent, temp)
            temps[qid] = temp
            corridors.append((lat.xy[out], q.radius))
            for p in world.pieces.values():
                if p.id not in moving and p.id not in depth and self._overlaps(out, q.radius, p):
                    depth[p.id] = depth[qid] + 1
                    queue.append(p.id)
        return temps, depth

    # -- space-time -------------------------------------------------------

    def _schedule(self, world, piece_id, goal, temps, order_out, moving, prior) -> dict[str, list[int]]:
        lat = self.lat
        res = _Reservations(lat, self.horizon)
        for pid, tr in prior.items():
            res.set(pid, tr, world.pieces[pid].radius)
        trajs: dict[str, list[int]] = {}
        for pid in moving:
            p = world.pieces[pid]
            trajs[pid] = list(prior.get(pid, [lat.index(p.node)]))
            res.set(pid, trajs[pid], p.radius)
        static = [p for p in world.pieces.values() if p.id not in moving and p.id not in prior]
        static_discs = self._discs(static)
        free_cache: dict[float, np.ndarray] = {}

        def extend(pid: str, target: int) -> None:
            r = world.pieces[pid].radius
            if r not in free_cache:
                free_cache[r] = lat.free_map(r, static_discs)
            tr = trajs[pid]
            new = self._space_time(tr[-1], target, len(tr) - 1, r, free_cache[r], res, pid)
            trajs[pid] = tr[:-1] + new
            res.set(pid, trajs[pid], r)

        for qid in order_out:
            extend(qid, temps[qid])
        extend(piece_id, goal)
        for qid in reversed(order_out):
            extend(qid, lat.index(world.pieces[qid].node))
        return trajs

    def _space_time(self, start: int, goal: int, t0: int, radius: float,
                    free: np.ndarray, res: _Reservations, agent: str) -> list[int]:
        lat = self.lat
        h = lat.step_distances(goal, free)
        if h[start] >= np.iinfo(np.int32).max:
            raise PlanningError(f"{agent}: goal {lat.node(goal)} unreachable")
        pos, radii = res.arrays(exclude=agent)
        need = radii + radius + CLEARANCE - 1e-9
        H = self.horizon

        def safe_forever(n: int, t: int) -> bool:
            if not len(radii):
                return True
            p = pos[:, t:, :]
            d = np.hypot(p[..., 0] - lat.xy[n, 0], p[..., 1] - lat.xy[n, 1])
            return bool((d >= need[:, None]).all())

        tie = itertools.count()
        heap = [(t0 + int(h[start]), int(h[start]), next(tie), start, t0)]
        came: dict[tuple[int, int], tuple[int, int] | None] = {(start, t0): None}
        expansions = 0
        while heap:
            _, _, _, n, t = heapq.heappop(heap)
            if n == goal and safe_forever(n, t):
                path = []
                key: tuple[int, int] | None = (n, t)
                while key is not None:
                    path.append(key[0])
                    key = came[key]
                return path[::-1]
            expansions += 1
            if expansions > self.max_expansions or t >= H:
                continue
            succ = [n] + [m for m in lat.neighbors[n] if free[m]]
            succ = [m for m in succ if (m, t + 1) not in came and h[m] < np.iinfo(np.int32).max]
            if not succ:
                continue
            s_xy = lat.xy[succ]
            if len(radii):
                p1 = pos[:, t + 1]
                pm = (pos[:, t] + p1) / 2
                mid = (lat.xy[n] + s_xy) / 2
                d1 = np.hypot(s_xy[:, None, 0] - p1[None, :, 0], s_xy[:, None, 1] - p1[None, :, 1])
                dm = np.hypot(mid[:, None, 0] - pm[None, :, 0], mid[:, None, 1] - pm[None, :, 1])
                ok = ((d1 >= need[None]) & (dm >= need[None])).all(axis=1)
            else:
                ok = np.ones(len(succ), dtype=bool)
            for m, good in zip(succ, ok):
                if good:
                    came[(m, t + 1)] = (n, t)
                    heapq.heappush(heap, (t + 1 + int(h[m]), int(h[m]), next(tie), m, t + 1))
        raise PlanningError(f"{agent}: no collision-free path to {lat.node(goal)}")


def step_seconds(speed: float = 0.3) -> float:
    """Wall time of one lattice step; a diagonal step must fit at top speed."""
    return GRID * 2 ** 0.5 / speed
