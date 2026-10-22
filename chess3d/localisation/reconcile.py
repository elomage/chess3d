"""Compare the expected board with what the sensors report.

A PoseSource reports where pieces really are. For option 1 that is the
movers themselves (each foot fuses magnet grid, odometry and IMU in
firmware); an overhead camera or a board-side coil grid would be further
sources with the same interface.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from ..motion.lattice import Lattice
from ..movers.base import Mover, MoverState, Pose
from ..world import Node, World


class PoseSource(Protocol):
    def poses(self) -> dict[str, Pose | None]:
        """Sensed pose per piece id; None when the piece cannot be seen."""
        ...


class MoverPoses:
    def __init__(self, movers: dict[str, Mover]) -> None:
        self.movers = movers

    def poses(self) -> dict[str, Pose | None]:
        out: dict[str, Pose | None] = {}
        for pid, m in self.movers.items():
            try:
                out[pid] = None if m.state() == MoverState.FAULT else m.pose()
            except RuntimeError:
                out[pid] = None
        return out


@dataclass
class Discrepancy:
    piece_id: str
    problem: str  # "missing" or "displaced"
    expected: tuple[float, float]
    actual: tuple[float, float] | None = None

    @property
    def error(self) -> float | None:
        return math.dist(self.expected, self.actual) if self.actual else None

    def as_dict(self) -> dict:
        return {"piece": self.piece_id, "problem": self.problem, "expected": self.expected,
                "actual": self.actual, "error": self.error}


def reconcile(world: World, lat: Lattice, source: PoseSource,
              tolerance: float = 0.02) -> list[Discrepancy]:
    sensed = source.poses()
    out = []
    for pid, p in world.pieces.items():
        if pid not in sensed:
            continue  # no sensor covers this piece
        expected = tuple(map(float, lat.xy[lat.index(p.node)]))
        pose = sensed[pid]
        if pose is None:
            out.append(Discrepancy(pid, "missing", expected))
        elif math.dist(expected, (pose.x, pose.y)) > tolerance:
            out.append(Discrepancy(pid, "displaced", expected, (pose.x, pose.y)))
    return out


def snap(lat: Lattice, pose: Pose) -> Node:
    """Nearest valid lattice node to a sensed pose."""
    d = np.hypot(lat.xy[:, 0] - pose.x, lat.xy[:, 1] - pose.y)
    d[~lat.valid] = np.inf
    return lat.node(int(np.argmin(d)))
