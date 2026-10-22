"""Movers on real (or emulated) hardware, reached through a Transport.

The hub binds each foot (drive module, identified by its own id) to a piece
by the NFC tag it reads in the piece body, so feet and bodies can be swapped
freely. Tag ids map to piece ids through `tag_map`; by default a tag is the
piece id itself.
"""

from __future__ import annotations

import asyncio
import itertools
import time
from dataclasses import dataclass, field
from typing import Any

from ..transport.base import Transport
from ..transport.protocol import path_message
from .base import MoverState, Pose, Waypoint

STALE_AFTER = 1.0  # seconds without a status before a mover counts as lost
START_DELAY_MS = 200  # lead time so all movers start together


@dataclass
class FootStatus:
    foot: str
    address: str
    pose: Pose = Pose(0.0, 0.0, 0.0)
    state: MoverState = MoverState.IDLE
    tag: str | None = None
    plan: int | None = None
    progress: float = 0.0
    battery: float | None = None
    error: str | None = None
    seen: float = field(default_factory=time.monotonic)


class MoverHub:
    def __init__(self, transport: Transport, tag_map: dict[str, str] | None = None,
                 stale_after: float = STALE_AFTER) -> None:
        self.transport = transport
        self.tag_map = tag_map or {}
        self.stale_after = stale_after
        self.feet: dict[str, FootStatus] = {}
        self.bound: dict[str, str] = {}  # piece id -> foot id
        self._plan_ids = itertools.count(1)
        self._changed = asyncio.Event()

    async def start(self) -> None:
        await self.transport.start(self._receive)

    async def close(self) -> None:
        await self.transport.close()

    def mover(self, piece_id: str) -> "RemoteMover":
        return RemoteMover(piece_id, self)

    def next_plan_id(self) -> int:
        return next(self._plan_ids)

    def status(self, piece_id: str) -> FootStatus | None:
        foot = self.bound.get(piece_id)
        return self.feet.get(foot) if foot else None

    def alive(self, piece_id: str) -> bool:
        st = self.status(piece_id)
        return st is not None and time.monotonic() - st.seen < self.stale_after

    def send(self, piece_id: str, msg: dict[str, Any]) -> None:
        st = self.status(piece_id)
        if st is None:
            raise RuntimeError(f"no foot carries {piece_id}")
        self.transport.send(st.address, msg)

    async def wait_for(self, piece_ids: list[str], timeout: float = 5.0) -> list[str]:
        """Wait until every piece has a live foot; returns those still missing."""
        deadline = time.monotonic() + timeout
        while True:
            missing = [p for p in piece_ids if not self.alive(p)]
            left = deadline - time.monotonic()
            if not missing or left <= 0:
                return missing
            self._changed.clear()
            try:
                await asyncio.wait_for(self._changed.wait(), left)
            except asyncio.TimeoutError:
                pass

    def _receive(self, address: str, msg: dict[str, Any]) -> None:
        foot = msg.get("foot")
        if not foot:
            return
        st = self.feet.get(foot)
        if st is None:
            st = self.feet[foot] = FootStatus(foot, address)
        st.address = address
        st.seen = time.monotonic()
        if msg["t"] == "status":
            st.pose = Pose(float(msg["x"]), float(msg["y"]), float(msg.get("h", 0.0)))
            try:
                st.state = MoverState(msg.get("state", "idle"))
            except ValueError:
                st.state = MoverState.FAULT
            st.plan = msg.get("plan")
            st.progress = float(msg.get("prog") or 0.0)
            st.battery = msg.get("bat")
            st.error = msg.get("err")
            tag = st.tag = msg.get("tag")
            if tag:
                piece = self.tag_map.get(tag, tag)
                for p, f in list(self.bound.items()):
                    if f == foot and p != piece:
                        del self.bound[p]
                self.bound[piece] = foot
        self._changed.set()


class RemoteMover:
    def __init__(self, piece_id: str, hub: MoverHub) -> None:
        self.id = piece_id
        self.hub = hub
        self.plan_id: int | None = None

    def follow_path(self, waypoints: list[Waypoint], heading: float = 0.0,
                    plan_id: int | None = None, start_ms: int = START_DELAY_MS) -> None:
        self.plan_id = plan_id if plan_id is not None else self.hub.next_plan_id()
        wp = [(w.x, w.y, w.t) for w in waypoints]
        self.hub.send(self.id, path_message(self.plan_id, wp, heading, start_ms))

    def stop(self) -> None:
        if self.hub.status(self.id):
            self.hub.send(self.id, {"t": "stop"})

    def rotate_to(self, heading: float) -> None:
        self.hub.send(self.id, {"t": "rotate", "h": heading})

    def set_pose(self, pose: Pose) -> None:
        self.hub.send(self.id, {"t": "pose", "x": pose.x, "y": pose.y, "h": pose.heading})

    def pose(self) -> Pose:
        st = self.hub.status(self.id)
        if st is None:
            raise RuntimeError(f"no foot carries {self.id}")
        return st.pose

    def state(self) -> MoverState:
        if not self.hub.alive(self.id):
            return MoverState.FAULT
        return self.hub.status(self.id).state

    def error(self) -> str | None:
        st = self.hub.status(self.id)
        if st is None or not self.hub.alive(self.id):
            return "no status from mover"
        return st.error

    def progress(self) -> tuple[int | None, float] | None:
        """(plan id, seconds into that plan) from the latest status."""
        st = self.hub.status(self.id)
        return (st.plan, st.progress) if st else None

    def body(self) -> str | None:
        """Piece id named by the tag in the mounted body, if any."""
        st = self.hub.status(self.id)
        return self.hub.tag_map.get(st.tag, st.tag) if st and st.tag else None

    def dock(self) -> None:
        self.hub.send(self.id, {"t": "dock"})
