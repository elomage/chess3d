"""Messages between the orchestrator and mover firmware.

One JSON object per datagram, keyed by "t" (type). Lengths in metres,
angles in radians, times in seconds unless the key says _ms.

Orchestrator -> mover
    path    {"t":"path","plan":7,"start_ms":200,"wp":[[x,y,t],...],"h":0.0}
            follow timed waypoints; t is relative to the start, which is
            start_ms after the message is received; h is the final heading
    stop    {"t":"stop"}                      brake now, drop the path
    rotate  {"t":"rotate","h":1.57}
    dock    {"t":"dock"}
    pose    {"t":"pose","x":..,"y":..,"h":..} overwrite the pose estimate
    ping    {"t":"ping","seq":3}

Mover -> orchestrator
    hello   {"t":"hello","foot":"a4cf12","fw":"0.1","kind":"piece"}
    status  {"t":"status","foot":"a4cf12","tag":"wNg1","x":..,"y":..,"h":..,
             "state":"moving","plan":7,"prog":1.25,"bat":0.82,"err":null}
            sent at 10 Hz while moving, 2 Hz otherwise; "tag" is the NFC id
            read from the piece body (None when no body is mounted)
    pong    {"t":"pong","seq":3}
"""

from __future__ import annotations

import json
from typing import Any

PROTOCOL_VERSION = 1
MAX_WAYPOINTS = 64
MOVER_TYPES = {"hello", "status", "pong"}
ORCHESTRATOR_TYPES = {"path", "stop", "rotate", "dock", "pose", "ping"}


class ProtocolError(ValueError):
    pass


def encode(msg: dict[str, Any]) -> bytes:
    return json.dumps(msg, separators=(",", ":")).encode()


def decode(data: bytes) -> dict[str, Any]:
    try:
        msg = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ProtocolError(f"not JSON: {e}") from e
    if not isinstance(msg, dict) or msg.get("t") not in MOVER_TYPES | ORCHESTRATOR_TYPES:
        raise ProtocolError(f"unknown message {msg!r}")
    return msg


def path_message(plan: int, waypoints: list[tuple[float, float, float]],
                 heading: float, start_ms: int) -> dict[str, Any]:
    if len(waypoints) > MAX_WAYPOINTS:
        raise ProtocolError(f"{len(waypoints)} waypoints, firmware takes {MAX_WAYPOINTS}")
    return {"t": "path", "plan": plan, "start_ms": start_ms, "h": round(heading, 4),
            "wp": [[round(x, 4), round(y, 4), round(t, 3)] for x, y, t in waypoints]}
