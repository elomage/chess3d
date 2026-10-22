"""Run the orchestrator with simulated movers: python -m chess3d.api"""

from __future__ import annotations

import argparse

import uvicorn

from ..integrations.engine import EnginePlayer
from ..service import GameService
from .app import create_app


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--speed", type=float, default=0.3, help="top speed m/s")
    ap.add_argument("--time-scale", type=float, default=1.0, help="simulation speed-up")
    ap.add_argument("--engine", help="UCI engine path to play against")
    ap.add_argument("--engine-side", default="black", choices=["white", "black"])
    args = ap.parse_args()

    service = GameService(speed=args.speed, time_scale=args.time_scale)
    player = EnginePlayer(args.engine, white=args.engine_side == "white") if args.engine else None
    app = create_app(service, engine=player)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
