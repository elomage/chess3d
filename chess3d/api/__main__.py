"""Run the orchestrator: python -m chess3d.api

Simulated pieces by default. --udp talks to mover firmware over Wi-Fi UDP;
--emulate does the same against emulated feet on this machine.
"""

from __future__ import annotations

import argparse
import logging

import uvicorn

from ..integrations.engine import EnginePlayer
from ..service import GameService
from ..world import World
from .app import create_app


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--speed", type=float, default=0.3, help="top speed m/s")
    ap.add_argument("--time-scale", type=float, default=1.0, help="simulation speed-up")
    ap.add_argument("--engine", help="UCI engine path to play against")
    ap.add_argument("--engine-side", default="black", choices=["white", "black"])
    ap.add_argument("--rig", action="store_true", help="a1-d4 test rig layout with six pieces")
    ap.add_argument("--udp", type=int, metavar="PORT", help="drive mover firmware over UDP")
    ap.add_argument("--emulate", action="store_true", help="UDP stack against emulated feet")
    ap.add_argument("--noise", type=float, default=0.0, help="emulated pose noise (m)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO)

    world = World.rig() if args.rig else World.initial()
    player = EnginePlayer(args.engine, white=args.engine_side == "white") if args.engine else None
    if args.udp is not None or args.emulate:
        from ..hardware import Hardware
        hw = Hardware(world, port=args.udp or 0, speed=args.speed,
                      emulate=args.emulate, noise=args.noise)
        app = create_app(engine=player, hardware=hw)
    else:
        service = GameService(speed=args.speed, time_scale=args.time_scale, world=world)
        app = create_app(service, engine=player)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
