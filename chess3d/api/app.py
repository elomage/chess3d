"""REST + WebSocket API.

Chess layer:   /game/...   (moves in UCI or SAN, FEN set-up, engine, voice)
Motion layer:  /pieces/... (free motion for demos; detaches the game state)
Events:        /ws         (state snapshots and timed plans for animation)
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import chess
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..integrations.engine import EnginePlayer
from ..integrations.lichess import LichessLink
from ..integrations.voice import VoiceError, parse_spoken
from ..service import GameService, ServiceError

STATIC = Path(__file__).parent / "static"


class MoveIn(BaseModel):
    move: str


class NewGameIn(BaseModel):
    fen: str = chess.STARTING_FEN


class VoiceIn(BaseModel):
    text: str


class EngineIn(BaseModel):
    path: str = "stockfish"
    side: str = "black"
    movetime: float = 1.0


class LichessIn(BaseModel):
    token: str
    game_id: str


class GotoIn(BaseModel):
    square: str


class ResumeIn(BaseModel):
    adopt: bool = False


class ChoreoStep(BaseModel):
    piece: str
    square: str


class ChoreoIn(BaseModel):
    steps: list[ChoreoStep]


def create_app(service: GameService | None = None, engine: EnginePlayer | None = None,
               hardware=None) -> FastAPI:
    """`hardware` is a chess3d.hardware.Hardware whose service is used."""
    svc = hardware.service if hardware else service or GameService()
    links: list[LichessLink] = []

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if hardware:
            await hardware.start()
        if engine:
            asyncio.create_task(svc.set_engine(engine))
        yield
        if hardware:
            await hardware.close()
        for link in links:
            await link.stop()
        await svc.set_engine(None)

    app = FastAPI(title="chess3d", lifespan=lifespan)
    app.state.service = svc

    async def call(coro):
        try:
            return await coro
        except ServiceError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        except RuntimeError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e

    @app.get("/")
    async def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/state")
    async def state():
        return svc.snapshot()

    @app.get("/game/legal")
    async def legal():
        b = svc.bridge.board
        return {"moves": [{"uci": m.uci(), "san": b.san(m)} for m in b.legal_moves]}

    @app.post("/game/new")
    async def new_game(body: NewGameIn):
        return await call(svc.new_game(body.fen))

    @app.post("/game/move")
    async def move(body: MoveIn):
        return await call(svc.move(body.move))

    @app.post("/game/voice")
    async def voice(body: VoiceIn):
        try:
            m = parse_spoken(svc.bridge.board, body.text)
        except VoiceError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        return await call(svc.move(m, origin="voice"))

    @app.post("/game/engine")
    async def engine_on(body: EngineIn):
        if body.side not in ("white", "black"):
            raise HTTPException(status_code=422, detail="side must be white or black")
        player = EnginePlayer(body.path, white=body.side == "white", movetime=body.movetime)
        await call(svc.set_engine(player))
        return svc.snapshot()["engine"]

    @app.delete("/game/engine")
    async def engine_off():
        await svc.set_engine(None)
        return {"engine": None}

    @app.post("/game/lichess")
    async def lichess(body: LichessIn):
        link = LichessLink(svc, body.token, body.game_id)
        links.append(link)
        link.start()
        return {"game_id": body.game_id}

    @app.post("/reset")
    async def reset():
        return await call(svc.reset())

    @app.post("/resume")
    async def resume(body: ResumeIn):
        return await call(svc.resume(body.adopt))

    @app.get("/discrepancies")
    async def discrepancies():
        return {"discrepancies": svc.discrepancies()}

    @app.post("/pieces/{piece_id}/goto")
    async def goto(piece_id: str, body: GotoIn):
        return await call(svc.goto(piece_id, body.square))

    @app.post("/pieces/{piece_id}/park")
    async def park(piece_id: str):
        return await call(svc.park(piece_id))

    @app.post("/choreography")
    async def choreography(body: ChoreoIn):
        return await call(svc.choreography([(s.piece, s.square) for s in body.steps]))

    @app.websocket("/ws")
    async def ws(socket: WebSocket):
        await socket.accept()
        q = svc.subscribe()
        try:
            await socket.send_json(svc.snapshot())
            while True:
                event = await q.get()
                await socket.send_json(event)
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        finally:
            svc.unsubscribe(q)

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
