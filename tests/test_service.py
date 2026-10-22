import asyncio
import json
import sys
from pathlib import Path

import chess
import httpx
import pytest
from fastapi.testclient import TestClient

from chess3d.api import create_app
from chess3d.chess_layer.bridge import node_of
from chess3d.integrations.demo import play_pgn
from chess3d.integrations.engine import EnginePlayer
from chess3d.integrations.lichess import LichessLink
from chess3d.integrations.voice import VoiceError, parse_spoken
from chess3d.motion.planner import Planner
from chess3d.service import GameService, ServiceError

ROOT = Path(__file__).resolve().parents[1]
FAKE_ENGINE = [sys.executable, str(ROOT / "tests" / "fake_uci.py")]
PLANNER = Planner()


def service() -> GameService:
    return GameService(planner=PLANNER, realtime=False)


def run(coro):
    return asyncio.run(coro)


def test_move_updates_world_and_history():
    svc = service()
    result = run(svc.move("e4"))
    assert result["san"] == "e4" and result["seconds"] > 0
    assert svc.world.pieces["wPe2"].node == node_of(chess.E4)
    assert svc.history == ["e4"]


def test_illegal_move_is_rejected():
    svc = service()
    with pytest.raises(ServiceError):
        run(svc.move("e5"))


def test_free_motion_detaches_until_reset():
    async def scenario(svc):
        await svc.goto("wNg1", "h3")
        assert not svc.synced
        with pytest.raises(ServiceError):
            await svc.move("e4")
        await svc.reset()
        assert svc.synced
        assert svc.world.pieces["wNg1"].node == node_of(chess.G1)
        await svc.move("e4")

    run(scenario(service()))


def test_new_game_from_fen_parks_missing_pieces():
    svc = service()
    fen = "4k3/8/8/8/8/8/4P3/4K2R w K - 0 1"
    run(svc.new_game(fen))
    on_board = [p for p in svc.world.pieces.values() if not svc.world.is_parked(p)]
    assert sorted(p.id for p in on_board) == ["bKe8", "wKe1", "wPe2", "wRh1"]
    assert svc.bridge.board.fen() == chess.Board(fen).fen()
    run(svc.move("O-O"))
    assert svc.world.pieces["wRh1"].node == node_of(chess.F1)


def test_voice_phrases():
    b = chess.Board()
    assert parse_spoken(b, "knight to f3") == chess.Move.from_uci("g1f3")
    assert parse_spoken(b, "e2 to e4") == chess.Move.from_uci("e2e4")
    assert parse_spoken(b, "e4") == chess.Move.from_uci("e2e4")
    b = chess.Board("r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 2 4")
    assert parse_spoken(b, "castle short") == chess.Move.from_uci("e1g1")
    b = chess.Board("rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2")
    assert parse_spoken(b, "pawn takes d5") == chess.Move.from_uci("e4d5")
    b = chess.Board("8/P6k/8/8/8/8/8/K7 w - - 0 1")
    assert parse_spoken(b, "a8 knight") == chess.Move.from_uci("a7a8n")
    with pytest.raises(VoiceError):
        parse_spoken(chess.Board(), "knight to e5")


def test_engine_replies_automatically():
    async def scenario(svc):
        await svc.set_engine(EnginePlayer(FAKE_ENGINE, white=False, movetime=0.05))
        try:
            await svc.move("e4")
            assert len(svc.history) == 2  # our move plus the engine's reply
        finally:
            await svc.set_engine(None)

    run(scenario(service()))


def test_demo_plays_pgn():
    svc = service()
    plies = run(play_pgn(svc, str(ROOT / "data" / "sample.pgn"), pause=0))
    assert plies == 33
    assert svc.bridge.board.is_checkmate()


def test_lichess_stream_mirrors_opponent_and_sends_ours():
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/account":
            return httpx.Response(200, json={"id": "me"})
        sent.append(request.url.path)
        return httpx.Response(200, json={"ok": True})

    async def scenario(svc):
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        link = LichessLink(svc, "token", "abc", client=client)
        svc.move_hooks.append(link._on_local_move)
        await link.handle({"type": "gameFull", "white": {"id": "other"}, "black": {"id": "me"},
                           "initialFen": "startpos", "state": {"moves": "e2e4"}})
        assert svc.history == ["e4"] and link.white is False
        await svc.move("e5")  # our move from the app goes to Lichess
        assert sent == ["/api/board/game/abc/move/e7e5"]
        await link.handle({"type": "gameState", "moves": "e2e4 e7e5 g1f3"})
        assert svc.history == ["e4", "e5", "Nf3"]
        await client.aclose()

    run(scenario(service()))


def test_api_and_websocket():
    app = create_app(service())
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "state"
            r = client.post("/game/move", json={"move": "Nf3"})
            assert r.status_code == 200, r.text
            kinds = {ws.receive_json()["type"] for _ in range(3)}
            assert {"plan", "state"} <= kinds
        assert client.post("/game/move", json={"move": "Nf3"}).status_code == 409
        assert client.post("/game/voice", json={"text": "pawn to e5"}).json()["san"] == "e5"
        assert len(client.get("/game/legal").json()["moves"]) > 20
        r = client.post("/pieces/wPa2/goto", json={"square": "a3"})
        assert r.status_code == 200 and not client.get("/state").json()["synced"]
        assert client.post("/reset").status_code == 200
        assert client.get("/").status_code == 200
        json.dumps(client.get("/state").json())
