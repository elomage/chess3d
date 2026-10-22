"""Mirror a Lichess game on the physical board (Lichess Board API).

The opponent's moves arrive on the game stream and are played on the board.
Moves made locally (app, voice) for our colour are sent to Lichess. Needs a
personal API token with the board:play scope.

Not yet exercised against the live server; the stream handling is covered by
tests with recorded events.
"""

from __future__ import annotations

import asyncio
import json
import logging

import chess
import httpx

from ..service import GameService

API = "https://lichess.org/api"
log = logging.getLogger(__name__)


class LichessLink:
    def __init__(self, service: GameService, token: str, game_id: str,
                 client: httpx.AsyncClient | None = None) -> None:
        self.service = service
        self.game_id = game_id
        self.client = client or httpx.AsyncClient(
            headers={"Authorization": f"Bearer {token}"}, timeout=None)
        self.white: bool | None = None
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self.service.move_hooks.append(self._on_local_move)
        self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        if self._on_local_move in self.service.move_hooks:
            self.service.move_hooks.remove(self._on_local_move)
        if self._task:
            self._task.cancel()
        await self.client.aclose()

    async def run(self) -> None:
        url = f"{API}/board/game/stream/{self.game_id}"
        async with self.client.stream("GET", url) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.strip():
                    await self.handle(json.loads(line))

    async def handle(self, event: dict) -> None:
        if event.get("type") == "gameFull":
            me = await self._my_id()
            self.white = event.get("white", {}).get("id") == me
            initial = event.get("initialFen", "startpos")
            await self.service.new_game(chess.STARTING_FEN if initial == "startpos" else initial)
            await self._sync(event.get("state", {}).get("moves", ""))
        elif event.get("type") == "gameState":
            await self._sync(event.get("moves", ""))

    async def _sync(self, moves: str) -> None:
        """Play every move from the stream the board has not seen yet."""
        ucis = moves.split()
        played = len(self.service.history)
        for uci in ucis[played:]:
            await self.service.move(uci, origin="lichess")

    async def _on_local_move(self, move: chess.Move, origin: str) -> None:
        if origin == "lichess" or self.white is None:
            return
        board = self.service.bridge.board
        mover_was_white = board.turn == chess.BLACK  # the move is already pushed
        if mover_was_white != self.white:
            return
        url = f"{API}/board/game/{self.game_id}/move/{move.uci()}"
        resp = await self.client.post(url)
        if resp.status_code != 200:
            log.error("lichess rejected %s: %s", move.uci(), resp.text)

    async def _my_id(self) -> str:
        resp = await self.client.get(f"{API}/account")
        resp.raise_for_status()
        return resp.json()["id"]
