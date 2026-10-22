# chess3d
Large size robotic chess

Orchestration software for a 3x3m robotic chess set: a path-clearing
multi-piece motion planner, a chess layer on python-chess, and a REST +
WebSocket API with a browser viewer. Movers are simulated for now; the
`Mover` interface in `chess3d/movers/base.py` is where hardware drivers plug in.

## Setup

    python3 -m venv .venv
    .venv/bin/pip install -e ".[dev]"

## Run

    .venv/bin/python -m chess3d.api --time-scale 4             # http://127.0.0.1:8000
    .venv/bin/python -m chess3d.api --engine stockfish        # play against a UCI engine

`--time-scale` speeds up the simulated motion; `--speed` sets top speed in m/s.

## API

Chess layer:

| Method | Path | Body |
|---|---|---|
| GET | `/state` | - |
| GET | `/game/legal` | - |
| POST | `/game/new` | `{"fen": "..."}` (optional, arranges the pieces) |
| POST | `/game/move` | `{"move": "e4"}` or `{"move": "e2e4"}` |
| POST | `/game/voice` | `{"text": "knight to f3"}` |
| POST / DELETE | `/game/engine` | `{"path": "stockfish", "side": "black", "movetime": 1.0}` |
| POST | `/game/lichess` | `{"token": "...", "game_id": "..."}` |
| POST | `/reset` | - |

Motion layer (free motion detaches the game until `/reset` or `/game/new`):

| Method | Path | Body |
|---|---|---|
| POST | `/pieces/{id}/goto` | `{"square": "e4"}` |
| POST | `/pieces/{id}/park` | - |
| POST | `/choreography` | `{"steps": [{"piece": "wNg1", "square": "f3"}]}` |

`/ws` streams `state` snapshots and `plan` events with timed waypoints.
Piece ids name the start square, e.g. `wNg1`, `bPe7`, `wQspare1`.

## Benchmark and tests

    .venv/bin/python tools/benchmark.py data/sample.pgn --random 10 --verify
    .venv/bin/python -m pytest
