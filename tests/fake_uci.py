"""Minimal UCI engine for tests: always plays the first legal move in UCI order."""

import sys

import chess

board = chess.Board()
for line in sys.stdin:
    cmd = line.split()
    if not cmd:
        continue
    if cmd[0] == "uci":
        print("id name fake\nuciok", flush=True)
    elif cmd[0] == "isready":
        print("readyok", flush=True)
    elif cmd[0] == "position":
        board = chess.Board() if cmd[1] == "startpos" else chess.Board(" ".join(cmd[2:8]))
        if "moves" in cmd:
            for uci in cmd[cmd.index("moves") + 1:]:
                board.push_uci(uci)
    elif cmd[0] == "go":
        move = min(board.legal_moves, key=lambda m: m.uci())
        print(f"bestmove {move.uci()}", flush=True)
    elif cmd[0] == "quit":
        break
