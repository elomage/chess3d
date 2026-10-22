"""Mover driver interface.

A mover is whatever physically displaces a piece: the drive foot of a
self-propelled piece (option 1) or a carrier under the board (option 2b). The
planner and executor only talk to movers through this interface.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class MoverState(str, Enum):
    IDLE = "idle"
    MOVING = "moving"
    DOCKED = "docked"
    FAULT = "fault"


@dataclass(frozen=True)
class Pose:
    x: float
    y: float
    heading: float  # radians, 0 = facing towards rank 8


@dataclass(frozen=True)
class Waypoint:
    x: float
    y: float
    t: float  # seconds from the start of the plan


class Mover(Protocol):
    id: str

    def follow_path(self, waypoints: list[Waypoint]) -> None: ...

    def rotate_to(self, heading: float) -> None: ...

    def pose(self) -> Pose: ...

    def state(self) -> MoverState: ...

    def dock(self) -> None: ...
