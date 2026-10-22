"""Scripted demos: replay a PGN game on the physical board."""

from __future__ import annotations

import asyncio

import chess.pgn

from ..service import GameService


async def play_pgn(service: GameService, path: str, pause: float = 1.0, game_index: int = 0) -> int:
    """Set up the game's start position and play its main line. Returns plies played."""
    with open(path) as f:
        game = None
        for _ in range(game_index + 1):
            game = chess.pgn.read_game(f)
    if game is None:
        raise ValueError(f"no game #{game_index} in {path}")
    await service.new_game(game.board().fen())
    plies = 0
    for move in game.mainline_moves():
        await service.move(move, origin="demo")
        plies += 1
        if pause:
            await asyncio.sleep(pause)
    return plies
