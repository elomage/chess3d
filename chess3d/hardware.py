"""Wiring for real or emulated movers: UDP transport, hub, tracking executor."""

from __future__ import annotations

import logging

from .motion.executor import Tolerances, TrackingExecutor
from .motion.lattice import Lattice
from .motion.planner import Planner
from .movers.emulator import EmulatedFleet
from .movers.remote import MoverHub
from .service import GameService
from .transport.udp import UdpTransport
from .world import World

log = logging.getLogger(__name__)


class Hardware:
    def __init__(self, world: World, host: str = "0.0.0.0", port: int = 4210,
                 speed: float = 0.3, tag_map: dict[str, str] | None = None,
                 tolerances: Tolerances | None = None, emulate: bool = False,
                 noise: float = 0.0) -> None:
        self.world = world
        lattice = Lattice(world.layout)
        self.hub = MoverHub(UdpTransport(host, port), tag_map)
        movers = {pid: self.hub.mover(pid) for pid in world.pieces}
        self.executor = TrackingExecutor(lattice, movers, speed, tolerances)
        self.service = GameService(planner=Planner(lattice), world=world, executor=self.executor)
        self.emulate = emulate
        self.noise = noise
        self.fleet: EmulatedFleet | None = None

    async def start(self, wait: float = 10.0) -> list[str]:
        """Open the transport and wait for every piece's foot to report."""
        await self.hub.start()
        if self.emulate:
            port = self.hub.transport.port
            self.fleet = EmulatedFleet(self.world, self.service.lat, ("127.0.0.1", port), self.noise)
            await self.fleet.start()
        missing = await self.hub.wait_for(list(self.world.pieces), wait)
        if missing:
            log.warning("no foot reports for: %s", ", ".join(missing))
        return missing

    async def close(self) -> None:
        if self.fleet:
            await self.fleet.close()
        await self.hub.close()
