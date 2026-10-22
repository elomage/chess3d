"""Physical state: which piece stands on which lattice node.

The world knows nothing about chess rules. It maps piece ids to nodes and keeps
track of which board squares and parking slots are taken.
"""

from __future__ import annotations

from dataclasses import dataclass

from .geometry import FOOTPRINTS, Kind, parking_nodes, square_node

Node = tuple[int, int]

BACK_RANK = [Kind.ROOK, Kind.KNIGHT, Kind.BISHOP, Kind.QUEEN,
             Kind.KING, Kind.BISHOP, Kind.KNIGHT, Kind.ROOK]
FILES = "abcdefgh"
SPARE_QUEENS_PER_SIDE = 2


@dataclass
class Piece:
    id: str
    kind: Kind
    white: bool
    node: Node

    @property
    def radius(self) -> float:
        return FOOTPRINTS[self.kind].radius


class World:
    def __init__(self) -> None:
        self.pieces: dict[str, Piece] = {}
        self.slots: list[Node] = parking_nodes()

    @classmethod
    def initial(cls) -> "World":
        """Standard start position plus spare queens in the parking area."""
        w = cls()
        for white, back, front in ((True, 0, 1), (False, 7, 6)):
            c = "w" if white else "b"
            for f, kind in enumerate(BACK_RANK):
                sq = f"{FILES[f]}{back + 1}"
                w.add(Piece(f"{c}{kind.value}{sq}", kind, white, square_node(f, back)))
                sq = f"{FILES[f]}{front + 1}"
                w.add(Piece(f"{c}P{sq}", Kind.PAWN, white, square_node(f, front)))
        for white in (True, False):
            c = "w" if white else "b"
            for k in range(SPARE_QUEENS_PER_SIDE):
                w.add(Piece(f"{c}Qspare{k + 1}", Kind.QUEEN, white, w.free_slot()))
        return w

    def add(self, piece: Piece) -> None:
        self.pieces[piece.id] = piece

    def copy(self) -> "World":
        w = World()
        for p in self.pieces.values():
            w.add(Piece(p.id, p.kind, p.white, p.node))
        return w

    def at(self, node: Node) -> Piece | None:
        for p in self.pieces.values():
            if p.node == node:
                return p
        return None

    def free_slot(self) -> Node:
        taken = {p.node for p in self.pieces.values()}
        for slot in self.slots:
            if slot not in taken:
                return slot
        raise RuntimeError("parking area is full")

    def is_parked(self, piece: Piece) -> bool:
        return piece.node in self.slots
