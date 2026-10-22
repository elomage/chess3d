"""Transport interface: carries protocol messages to and from movers.

Addresses are opaque strings chosen by the transport (e.g. "10.0.0.7:4210"
for UDP). A later ESP-NOW or 802.15.4 gateway only has to implement this.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

Receiver = Callable[[str, dict[str, Any]], None]


class Transport(Protocol):
    async def start(self, receiver: Receiver) -> None: ...

    def send(self, address: str, msg: dict[str, Any]) -> None: ...

    def broadcast(self, msg: dict[str, Any]) -> None: ...

    async def close(self) -> None: ...
