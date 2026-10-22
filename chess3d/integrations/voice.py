"""Turn spoken or typed natural phrases into legal moves.

Speech recognition itself is out of scope; this takes its text output, e.g.
"knight to f3", "e2 e4", "pawn takes d5", "bishop c1 to e3", "castle short",
"queen takes e7", "e8 queen" (promotion).
"""

from __future__ import annotations

import re

import chess

PIECE_WORDS = {
    "pawn": chess.PAWN, "knight": chess.KNIGHT, "night": chess.KNIGHT, "horse": chess.KNIGHT,
    "bishop": chess.BISHOP, "rook": chess.ROOK, "castle": None, "tower": chess.ROOK,
    "queen": chess.QUEEN, "king": chess.KING,
}
SQUARE = re.compile(r"\b([a-h])\s*([1-8])\b")


class VoiceError(ValueError):
    pass


def parse_spoken(board: chess.Board, text: str) -> chess.Move:
    t = text.lower().strip()
    t = re.sub(r"\b(to|moves?|goes|on|the|please|square)\b", " ", t)
    words = t.split()

    if re.search(r"\bcastles?\b", t) and not SQUARE.search(t):
        long_side = any(w in words for w in ("long", "queenside", "queen"))
        rank = 0 if board.turn == chess.WHITE else 7
        to_file = 2 if long_side else 6
        move = chess.Move(chess.square(4, rank), chess.square(to_file, rank))
        if move in board.legal_moves and board.is_castling(move):
            return move
        raise VoiceError("castling is not possible now")

    squares = [chess.square(ord(f) - 97, int(r) - 1) for f, r in SQUARE.findall(t)]
    capture = any(w in words for w in ("takes", "captures", "x", "capture"))
    kinds = [PIECE_WORDS[w] for w in words if w in PIECE_WORDS and PIECE_WORDS[w]]
    if not squares:
        raise VoiceError(f"no square heard in {text!r}")

    promotion = None
    # A piece word after the last square names the promotion piece.
    last_sq = list(SQUARE.finditer(t))[-1]
    tail = t[last_sq.end():].split()
    tail_kinds = [PIECE_WORDS[w] for w in tail if w in PIECE_WORDS and PIECE_WORDS[w]]
    if tail_kinds:
        promotion = tail_kinds[0]
        head = t[:last_sq.start()].split()
        kinds = [PIECE_WORDS[w] for w in head if w in PIECE_WORDS and PIECE_WORDS[w]]

    to_sq = squares[-1]
    from_sq = squares[0] if len(squares) >= 2 else None
    kind = kinds[0] if kinds else None

    candidates = []
    for m in board.legal_moves:
        if m.to_square != to_sq:
            continue
        if from_sq is not None and m.from_square != from_sq:
            continue
        piece = board.piece_type_at(m.from_square)
        if kind is not None and piece != kind:
            continue
        if capture and not board.is_capture(m):
            continue
        if m.promotion and m.promotion != (promotion or chess.QUEEN):
            continue
        candidates.append(m)
    if kind is None and from_sq is None and len(candidates) > 1:
        pawns = [m for m in candidates if board.piece_type_at(m.from_square) == chess.PAWN]
        if len(pawns) == 1:
            candidates = pawns
    if not candidates:
        raise VoiceError(f"no legal move matches {text!r}")
    if len(candidates) > 1:
        options = ", ".join(board.san(m) for m in candidates)
        raise VoiceError(f"{text!r} is ambiguous: {options}")
    return candidates[0]
