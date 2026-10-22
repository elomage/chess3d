"""Physical layout of the board, border, parking area and piece footprints.

All lengths are in metres. The world frame has its origin at the outer corner
of the board next to a1 (white's left), x along the files towards h, y along
the ranks towards 8. The parking area sits to the right of the board (x > 3m).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

BOARD_SIZE = 3.0
# Classic border of half a square: 8 squares + 2 * 0.5 square = 9 squares.
SQUARE = BOARD_SIZE / 9.0
BORDER = SQUARE / 2.0
PARKING_WIDTH = 1.5
AREA_WIDTH = BOARD_SIZE + PARKING_WIDTH
AREA_DEPTH = BOARD_SIZE

# Planning lattice pitch. 1/6 of a square puts square centres, square corners
# and edge midpoints exactly on lattice nodes.
GRID = SQUARE / 6.0
NODES_PER_SQUARE = 6

# Minimum distance a piece centre keeps from the outer edge of the area. The
# body may overhang the edge a little, the drive foot underneath may not.
CENTER_INSET = 0.05

# Extra gap required between two piece bases on top of the sum of radii.
CLEARANCE = 0.01


class Kind(str, Enum):
    PAWN = "P"
    KNIGHT = "N"
    BISHOP = "B"
    ROOK = "R"
    QUEEN = "Q"
    KING = "K"


@dataclass(frozen=True)
class Footprint:
    base_diameter: float
    height: float

    @property
    def radius(self) -> float:
        return self.base_diameter / 2.0


# Staunton No.6 ratios (king 95mm on a 57mm square) scaled to our square.
FOOTPRINTS: dict[Kind, Footprint] = {
    Kind.PAWN: Footprint(0.51 * SQUARE, 0.88 * SQUARE),
    Kind.KNIGHT: Footprint(0.58 * SQUARE, 1.05 * SQUARE),
    Kind.BISHOP: Footprint(0.58 * SQUARE, 1.23 * SQUARE),
    Kind.ROOK: Footprint(0.58 * SQUARE, 0.96 * SQUARE),
    Kind.QUEEN: Footprint(0.65 * SQUARE, 1.49 * SQUARE),
    Kind.KING: Footprint(0.70 * SQUARE, 1.67 * SQUARE),
}

PARKING_COLUMNS = 4
PARKING_ROWS = 8


def square_node(file: int, rank: int) -> tuple[int, int]:
    """Lattice node (i, j) of the centre of a square, file and rank 0..7."""
    return (NODES_PER_SQUARE * (file + 1), NODES_PER_SQUARE * (rank + 1))


def node_xy(i: int, j: int) -> tuple[float, float]:
    return (i * GRID, j * GRID)


def parking_nodes() -> list[tuple[int, int]]:
    """Parking slots in fill order: far column first, then towards the board.

    Slots use the same pitch as the board squares so that any piece fits.
    """
    board_nodes = round(BOARD_SIZE / GRID)
    slots = []
    for col in reversed(range(PARKING_COLUMNS)):
        i = board_nodes + NODES_PER_SQUARE // 2 + NODES_PER_SQUARE * col
        for row in range(PARKING_ROWS):
            slots.append((i, NODES_PER_SQUARE * (row + 1)))
    return slots
