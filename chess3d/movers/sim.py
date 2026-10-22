"""Ideal simulated mover: follows waypoints exactly."""

from __future__ import annotations

from .base import MoverState, Pose, Waypoint


class SimMover:
    def __init__(self, mover_id: str, pose: Pose) -> None:
        self.id = mover_id
        self._pose = pose
        self._path: list[Waypoint] = []
        self._state = MoverState.IDLE

    def follow_path(self, waypoints: list[Waypoint]) -> None:
        self._path = list(waypoints)
        self._state = MoverState.MOVING if waypoints else MoverState.IDLE

    def rotate_to(self, heading: float) -> None:
        self._pose = Pose(self._pose.x, self._pose.y, heading)

    def pose(self) -> Pose:
        return self._pose

    def state(self) -> MoverState:
        return self._state

    def dock(self) -> None:
        self._state = MoverState.DOCKED

    def advance(self, t: float) -> None:
        """Move to the interpolated position at plan time `t`."""
        path = self._path
        if not path:
            return
        if t >= path[-1].t:
            last = path[-1]
            self._pose = Pose(last.x, last.y, self._pose.heading)
            self._path = []
            self._state = MoverState.IDLE
            return
        for a, b in zip(path, path[1:]):
            if a.t <= t <= b.t:
                f = (t - a.t) / (b.t - a.t) if b.t > a.t else 1.0
                self._pose = Pose(a.x + f * (b.x - a.x), a.y + f * (b.y - a.y), self._pose.heading)
                return
