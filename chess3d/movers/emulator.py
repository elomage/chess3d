"""Emulated mover firmware speaking the UDP protocol.

Stands in for ESP32 feet so the whole hardware stack (transport, hub,
tracking executor, fault recovery) can run on a PC. Each foot follows its
timed path with optional position noise and can be told to misbehave.
"""

from __future__ import annotations

import asyncio
import math
import random
import time
from dataclasses import dataclass, field
from typing import Any

from ..transport.protocol import ProtocolError, decode, encode
from ..world import World
from .base import MoverState

TICK = 0.02


@dataclass
class Faults:
    slip: tuple[float, float, float] | None = None  # (after s, dx, dy) jump once
    stall_after: float | None = None  # stop moving this long into a path
    silent_after: float | None = None  # stop sending status
    swap_tag: str | None = None  # report this body tag instead
    used: set[str] = field(default_factory=set)


class EmulatedFoot(asyncio.DatagramProtocol):
    def __init__(self, foot: str, tag: str | None, x: float, y: float,
                 server: tuple[str, int], noise: float = 0.0, seed: int = 0) -> None:
        self.foot = foot
        self.tag = tag
        self.x, self.y, self.h = x, y, 0.0
        self.server = server
        self.noise = noise
        self.rng = random.Random(seed)
        self.state = MoverState.IDLE
        self.plan: int | None = None
        self.path: list[list[float]] = []
        self.target_h = 0.0
        self.start = 0.0
        self.faults = Faults()
        self.transport: asyncio.DatagramTransport | None = None
        self._task: asyncio.Task | None = None
        self._last_status = 0.0
        self.received: list[dict[str, Any]] = []

    # -- asyncio plumbing ------------------------------------------------

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        self.transport, _ = await loop.create_datagram_endpoint(
            lambda: self, local_addr=("127.0.0.1", 0))
        self._send({"t": "hello", "foot": self.foot, "fw": "emu", "kind": "piece"})
        self._task = asyncio.create_task(self._loop())

    async def close(self) -> None:
        if self._task:
            self._task.cancel()
        if self.transport:
            self.transport.close()

    def datagram_received(self, data: bytes, addr) -> None:
        try:
            msg = decode(data)
        except ProtocolError:
            return
        self.received.append(msg)
        t = msg["t"]
        if t == "path":
            self.plan = msg["plan"]
            self.path = msg["wp"]
            self.target_h = msg.get("h", self.h)
            self.start = time.monotonic() + msg.get("start_ms", 0) / 1000
            self.state = MoverState.MOVING
        elif t == "stop":
            self.path = []
            self.state = MoverState.IDLE
        elif t == "rotate":
            self.h = msg["h"]
        elif t == "pose":
            self.x, self.y, self.h = msg["x"], msg["y"], msg.get("h", self.h)
        elif t == "dock":
            self.state = MoverState.DOCKED
        elif t == "ping":
            self._send({"t": "pong", "foot": self.foot, "seq": msg.get("seq")})

    def _send(self, msg: dict[str, Any]) -> None:
        if self.transport:
            self.transport.sendto(encode(msg), self.server)

    # -- behaviour --------------------------------------------------------

    def _progress(self) -> float:
        return max(0.0, time.monotonic() - self.start)

    def _step(self) -> None:
        before = self.state
        self._move()
        if self.state != before:
            self.force_status()  # firmware reports state changes at once

    def _move(self) -> None:
        if self.state != MoverState.MOVING or not self.path:
            return
        t = self._progress()
        f = self.faults
        if f.stall_after is not None and t > f.stall_after:
            return
        if f.slip and t > f.slip[0] and "slip" not in f.used:
            f.used.add("slip")
            self.x += f.slip[1]
            self.y += f.slip[2]
            self.path = []  # wheels lost the path; firmware gives up
            self.state = MoverState.IDLE
            return
        wp = self.path
        if t >= wp[-1][2]:
            self.x, self.y = wp[-1][0], wp[-1][1]
            self.h = self.target_h
            self.path = []
            self.state = MoverState.IDLE
            return
        for a, b in zip(wp, wp[1:]):
            if a[2] <= t <= b[2]:
                k = (t - a[2]) / (b[2] - a[2]) if b[2] > a[2] else 1.0
                self.x = a[0] + k * (b[0] - a[0])
                self.y = a[1] + k * (b[1] - a[1])
                return
        self.x, self.y = wp[0][0], wp[0][1]  # before the first waypoint time

    async def _loop(self) -> None:
        started = time.monotonic()
        while True:
            self._step()
            now = time.monotonic()
            period = 0.1 if self.state == MoverState.MOVING else 0.5
            silent = (self.faults.silent_after is not None
                      and now - started > self.faults.silent_after)
            if now - self._last_status >= period and not silent:
                self._last_status = now
                n = self.noise
                self._send({
                    "t": "status", "foot": self.foot,
                    "tag": self.faults.swap_tag or self.tag,
                    "x": self.x + (self.rng.gauss(0, n) if n else 0.0),
                    "y": self.y + (self.rng.gauss(0, n) if n else 0.0),
                    "h": self.h, "state": self.state.value, "plan": self.plan,
                    "prog": round(self._progress(), 3) if self.path else 0.0,
                    "bat": 0.9, "err": None})
            await asyncio.sleep(TICK)

    def force_status(self) -> None:
        """Send a status on the next tick (after a fault was injected)."""
        self._last_status = 0.0


class EmulatedFleet:
    """One emulated foot per piece in `world`, carrying that piece's tag."""

    def __init__(self, world: World, lattice, server: tuple[str, int],
                 noise: float = 0.0, seed: int = 0) -> None:
        self.feet: dict[str, EmulatedFoot] = {}
        for k, p in enumerate(world.pieces.values()):
            x, y = lattice.xy[lattice.index(p.node)]
            self.feet[p.id] = EmulatedFoot(f"foot{k:02d}", p.id, float(x), float(y),
                                           server, noise, seed + k)

    async def start(self) -> None:
        for foot in self.feet.values():
            await foot.run()

    async def close(self) -> None:
        for foot in self.feet.values():
            await foot.close()

    def distance_from(self, piece_id: str, x: float, y: float) -> float:
        f = self.feet[piece_id]
        return math.hypot(f.x - x, f.y - y)
