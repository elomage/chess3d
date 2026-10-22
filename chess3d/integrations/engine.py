"""Play against a UCI engine such as Stockfish."""

from __future__ import annotations

import chess
import chess.engine


class EnginePlayer:
    def __init__(self, path: str | list[str], white: bool, movetime: float = 1.0) -> None:
        self.path = path
        self.white = white
        self.movetime = movetime
        self._engine: chess.engine.UciProtocol | None = None

    async def start(self) -> None:
        try:
            _, self._engine = await chess.engine.popen_uci(self.path)
        except (FileNotFoundError, PermissionError, chess.engine.EngineError) as e:
            raise RuntimeError(f"cannot start engine {self.path!r}: {e}") from e

    async def choose(self, board: chess.Board) -> chess.Move:
        assert self._engine, "engine not started"
        result = await self._engine.play(board, chess.engine.Limit(time=self.movetime))
        if result.move is None:
            raise RuntimeError("engine returned no move")
        return result.move

    async def close(self) -> None:
        if self._engine:
            await self._engine.quit()
            self._engine = None

    def describe(self) -> dict:
        path = self.path if isinstance(self.path, str) else " ".join(self.path)
        return {"path": path, "side": "white" if self.white else "black",
                "movetime": self.movetime}
