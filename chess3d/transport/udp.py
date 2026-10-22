"""Wi-Fi UDP transport. Movers send to the orchestrator's port; replies go
back to the address each mover last sent from."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .base import Receiver
from .protocol import ProtocolError, decode, encode

log = logging.getLogger(__name__)
DEFAULT_PORT = 4210


class _Endpoint(asyncio.DatagramProtocol):
    def __init__(self, owner: "UdpTransport") -> None:
        self.owner = owner

    def datagram_received(self, data: bytes, addr) -> None:
        try:
            msg = decode(data)
        except ProtocolError as e:
            log.warning("dropping datagram from %s: %s", addr, e)
            return
        address = f"{addr[0]}:{addr[1]}"
        self.owner.peers.add(address)
        if self.owner.receiver:
            self.owner.receiver(address, msg)


class UdpTransport:
    def __init__(self, host: str = "0.0.0.0", port: int = DEFAULT_PORT) -> None:
        self.host = host
        self.port = port
        self.receiver: Receiver | None = None
        self.peers: set[str] = set()
        self._transport: asyncio.DatagramTransport | None = None

    async def start(self, receiver: Receiver) -> None:
        self.receiver = receiver
        loop = asyncio.get_running_loop()
        self._transport, _ = await loop.create_datagram_endpoint(
            lambda: _Endpoint(self), local_addr=(self.host, self.port))
        self.port = self._transport.get_extra_info("sockname")[1]

    def send(self, address: str, msg: dict[str, Any]) -> None:
        if self._transport is None:
            raise RuntimeError("transport not started")
        host, port = address.rsplit(":", 1)
        self._transport.sendto(encode(msg), (host, int(port)))

    def broadcast(self, msg: dict[str, Any]) -> None:
        for address in list(self.peers):
            self.send(address, msg)

    async def close(self) -> None:
        if self._transport:
            self._transport.close()
            self._transport = None
