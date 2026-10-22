"""Planning lattice over the board and parking area.

Nodes are flattened to an index n = i * ny + j. Every move between two
8-connected neighbours takes one time step; waiting in place is also a step.
"""

from __future__ import annotations

import heapq
import math
from collections import deque

import numpy as np

from ..geometry import CENTER_INSET, CLEARANCE, FULL, GRID, Layout

STEPS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


class Lattice:
    def __init__(self, layout: Layout = FULL) -> None:
        self.layout = layout
        width, depth = layout.width, layout.depth
        self.nx = round(width / GRID) + 1
        self.ny = round(depth / GRID) + 1
        ii, jj = np.meshgrid(np.arange(self.nx), np.arange(self.ny), indexing="ij")
        self.xy = np.stack([ii.ravel() * GRID, jj.ravel() * GRID], axis=1)
        x, y = self.xy[:, 0], self.xy[:, 1]
        eps = 1e-9
        self.valid = ((x >= CENTER_INSET - eps) & (x <= width - CENTER_INSET + eps)
                      & (y >= CENTER_INSET - eps) & (y <= depth - CENTER_INSET + eps))
        self.size = self.nx * self.ny
        self.neighbors: list[list[int]] = [[] for _ in range(self.size)]
        for n in range(self.size):
            if not self.valid[n]:
                continue
            i, j = divmod(n, self.ny)
            for di, dj in STEPS:
                a, b = i + di, j + dj
                if 0 <= a < self.nx and 0 <= b < self.ny:
                    m = a * self.ny + b
                    if self.valid[m]:
                        self.neighbors[n].append(m)

    def index(self, node: tuple[int, int]) -> int:
        return node[0] * self.ny + node[1]

    def node(self, n: int) -> tuple[int, int]:
        return divmod(n, self.ny)

    def free_map(self, radius: float, discs: list[tuple[np.ndarray, float]]) -> np.ndarray:
        """Nodes where a disc of `radius` does not touch any of `discs`."""
        free = self.valid.copy()
        for centre, r in discs:
            d = np.hypot(self.xy[:, 0] - centre[0], self.xy[:, 1] - centre[1])
            free &= d >= radius + r + CLEARANCE - 1e-9
        return free

    def overlap_count(self, radius: float, discs: list[tuple[np.ndarray, float]]) -> np.ndarray:
        count = np.zeros(self.size, dtype=np.int32)
        for centre, r in discs:
            d = np.hypot(self.xy[:, 0] - centre[0], self.xy[:, 1] - centre[1])
            count += d < radius + r + CLEARANCE - 1e-9
        return count

    def step_distances(self, goal: int, free: np.ndarray) -> np.ndarray:
        """BFS step count from every node to `goal` through `free` nodes."""
        dist = np.full(self.size, np.iinfo(np.int32).max, dtype=np.int64)
        if not free[goal]:
            return dist
        dist[goal] = 0
        q = deque([goal])
        while q:
            n = q.popleft()
            for m in self.neighbors[n]:
                if free[m] and dist[m] > dist[n] + 1:
                    dist[m] = dist[n] + 1
                    q.append(m)
        return dist

    def cheapest_paths(self, start: int, node_cost: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Dijkstra from `start`; entering node m costs step length + node_cost[m].

        Returns (cost, parent) arrays. Used for blocker-aware routing, where
        node_cost penalises footprints that overlap other pieces.
        """
        cost = np.full(self.size, math.inf)
        parent = np.full(self.size, -1, dtype=np.int64)
        cost[start] = 0.0
        heap = [(0.0, start)]
        while heap:
            c, n = heapq.heappop(heap)
            if c > cost[n]:
                continue
            i, j = divmod(n, self.ny)
            for m in self.neighbors[n]:
                a, b = divmod(m, self.ny)
                step = 1.0 if (a == i or b == j) else math.sqrt(2.0)
                nc = c + step + node_cost[m]
                if nc < cost[m] - 1e-12:
                    cost[m] = nc
                    parent[m] = n
                    heapq.heappush(heap, (nc, m))
        return cost, parent

    @staticmethod
    def trace(parent: np.ndarray, goal: int) -> list[int]:
        path = [goal]
        while parent[path[-1]] >= 0:
            path.append(int(parent[path[-1]]))
        path.reverse()
        return path
