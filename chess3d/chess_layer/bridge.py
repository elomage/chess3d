"""Chess layer: turns chess moves into physical motion tasks.

Rules come from python-chess. The bridge keeps track of which physical piece
stands on which square and decides where captured pieces park and which
parked piece comes back on promotion.
"""

from __future__ import annotations

from dataclasses import dataclass

import chess

from ..geometry import Kind, square_node
from ..world import Node, World

KIND_OF = {chess.PAWN: Kind.PAWN, chess.KNIGHT: Kind.KNIGHT, chess.BISHOP: Kind.BISHOP,
           chess.ROOK: Kind.ROOK, chess.QUEEN: Kind.QUEEN, chess.KING: Kind.KING}


@dataclass(frozen=True)
class MotionTask:
    piece_id: str
    goal: Node
    reason: str


def node_of(square: chess.Square) -> Node:
    return square_node(chess.square_file(square), chess.square_rank(square))


class ChessBridge:
    def __init__(self, world: World, board: chess.Board | None = None) -> None:
        self.world = world
        self.board = board or chess.Board()
        self.on_square: dict[chess.Square, str] = {}
        by_node = {p.node: p.id for p in world.pieces.values()}
        for sq in chess.SQUARES:
            if self.board.piece_at(sq) is not None:
                self.on_square[sq] = by_node[node_of(sq)]

    def tasks(self, move: chess.Move) -> list[MotionTask]:
        """Motion tasks for a legal move, in execution order."""
        b = self.board
        if move not in b.legal_moves:
            raise ValueError(f"illegal move {move.uci()} in {b.fen()}")
        tasks: list[MotionTask] = []
        reserved: set[Node] = set()

        def park(piece_id: str, reason: str) -> None:
            slot = self._slot(reserved)
            reserved.add(slot)
            tasks.append(MotionTask(piece_id, slot, reason))

        mover = self.on_square[move.from_square]
        if b.is_en_passant(move):
            victim = move.to_square + (-8 if b.turn == chess.WHITE else 8)
            park(self.on_square[victim], "capture en passant")
        elif b.is_capture(move):
            park(self.on_square[move.to_square], "capture")

        if b.is_castling(move):
            rank = chess.square_rank(move.from_square)
            kingside = chess.square_file(move.to_square) == 6
            rook_from = chess.square(7 if kingside else 0, rank)
            rook_to = chess.square(5 if kingside else 3, rank)
            tasks.append(MotionTask(mover, node_of(move.to_square), "castle king"))
            tasks.append(MotionTask(self.on_square[rook_from], node_of(rook_to), "castle rook"))
        elif move.promotion:
            park(mover, "promoted pawn leaves")
            tasks.append(MotionTask(self._replacement(move.promotion, reserved),
                                    node_of(move.to_square), "promotion"))
        else:
            tasks.append(MotionTask(mover, node_of(move.to_square), "move"))
        return tasks

    def commit(self, move: chess.Move, tasks: list[MotionTask]) -> None:
        """Record the move once its tasks have been executed physically."""
        b = self.board
        if b.is_en_passant(move):
            self.on_square.pop(move.to_square + (-8 if b.turn == chess.WHITE else 8))
        self.on_square.pop(move.to_square, None)
        mover = self.on_square.pop(move.from_square)
        if b.is_castling(move):
            rank = chess.square_rank(move.from_square)
            kingside = chess.square_file(move.to_square) == 6
            rook = self.on_square.pop(chess.square(7 if kingside else 0, rank))
            self.on_square[chess.square(5 if kingside else 3, rank)] = rook
            self.on_square[move.to_square] = mover
        elif move.promotion:
            self.on_square[move.to_square] = tasks[-1].piece_id
        else:
            self.on_square[move.to_square] = mover
        b.push(move)

    def _slot(self, reserved: set[Node]) -> Node:
        taken = {p.node for p in self.world.pieces.values()} | reserved
        for slot in self.world.slots:
            if slot not in taken:
                return slot
        raise RuntimeError("parking area is full")

    def _replacement(self, promotion: chess.PieceType, reserved: set[Node]) -> str:
        """A parked piece of the promoted kind, else a queen as a stand-in."""
        white = self.board.turn == chess.WHITE
        parked = [p for p in self.world.pieces.values()
                  if p.white == white and self.world.is_parked(p) and p.node not in reserved]
        for kind in (KIND_OF[promotion], Kind.QUEEN):
            matches = [p for p in parked if p.kind == kind]
            if matches:
                # Prefer the slot closest to the board (smallest x index).
                return min(matches, key=lambda p: p.node).id
        raise RuntimeError("no piece available for promotion")
