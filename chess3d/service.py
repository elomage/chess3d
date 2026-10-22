"""Game service: the orchestrator behind the API.

Owns the physical world, the chess bridge, the planner and the movers. All
commands are serialised through one lock, so only one plan runs at a time.
Every change is published as an event to subscribers (WebSocket clients,
integrations).
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from typing import Any

import chess

from .chess_layer.bridge import KIND_OF, ChessBridge, node_of
from .geometry import FOOTPRINTS
from .motion.executor import Executor, waypoints
from .motion.planner import Plan, Planner, PlanningError
from .movers.base import Mover, Pose
from .movers.sim import SimMover
from .world import Node, World

MoveHook = Callable[[chess.Move, str], Awaitable[None]]


class ServiceError(RuntimeError):
    """A command that cannot be carried out in the current state."""


class GameService:
    def __init__(self, planner: Planner | None = None, speed: float = 0.3,
                 time_scale: float = 1.0, realtime: bool = True,
                 movers: dict[str, Mover] | None = None) -> None:
        self.planner = planner or Planner()
        self.lat = self.planner.lat
        self.world = World.initial()
        self.home = {p.id: p.node for p in self.world.pieces.values()}
        self.movers: dict[str, Mover] = movers or {
            p.id: SimMover(p.id, Pose(*map(float, self.lat.xy[self.lat.index(p.node)]), 0.0))
            for p in self.world.pieces.values()}
        self.executor = Executor(self.lat, self.movers, speed)
        self.time_scale = time_scale
        self.realtime = realtime
        self.bridge = ChessBridge(self.world)
        self.synced = True
        self.history: list[str] = []
        self.lock = asyncio.Lock()
        self.queues: set[asyncio.Queue] = set()
        self.move_hooks: list[MoveHook] = []
        self.engine = None  # integrations.engine.EnginePlayer

    # -- events -----------------------------------------------------------

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        self.queues.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.queues.discard(q)

    def _publish(self, event: dict[str, Any]) -> None:
        for q in list(self.queues):
            if q.full():
                q.get_nowait()  # drop the oldest event for slow clients
            q.put_nowait(event)

    def snapshot(self) -> dict[str, Any]:
        b = self.bridge.board
        pieces = []
        for p in self.world.pieces.values():
            x, y = self.lat.xy[self.lat.index(p.node)]
            pieces.append({"id": p.id, "kind": p.kind.value, "white": p.white,
                           "x": float(x), "y": float(y), "radius": p.radius,
                           "height": FOOTPRINTS[p.kind].height,
                           "parked": self.world.is_parked(p)})
        return {"type": "state", "fen": b.fen(), "turn": "white" if b.turn else "black",
                "synced": self.synced, "history": list(self.history),
                "game_over": b.is_game_over(), "result": b.result() if b.is_game_over() else None,
                "engine": self.engine.describe() if self.engine else None,
                "pieces": pieces}

    # -- chess layer ------------------------------------------------------

    def parse_move(self, text: str) -> chess.Move:
        b = self.bridge.board
        try:
            move = chess.Move.from_uci(text)
            if move in b.legal_moves:
                return move
        except ValueError:
            pass
        try:
            return b.parse_san(text)
        except ValueError as e:
            raise ServiceError(f"illegal or unknown move {text!r}") from e

    async def move(self, text: str | chess.Move, origin: str = "api") -> dict[str, Any]:
        async with self.lock:
            if not self.synced:
                raise ServiceError("pieces were moved freely; start a new game or reset first")
            move = text if isinstance(text, chess.Move) else self.parse_move(text)
            if move not in self.bridge.board.legal_moves:
                raise ServiceError(f"illegal move {move.uci()}")
            san = self.bridge.board.san(move)
            tasks = self.bridge.tasks(move)
            plan = await self._plan([(t.piece_id, t.goal) for t in tasks])
            seconds = await self._execute(plan, f"{san}")
            self.bridge.commit(move, tasks)
            self.history.append(san)
            self._publish(self.snapshot())
        for hook in self.move_hooks:
            await hook(move, origin)
        await self._engine_turn()
        return {"san": san, "uci": move.uci(), "seconds": seconds,
                "blockers": plan.blockers, "tasks": [t.reason for t in tasks]}

    async def new_game(self, fen: str = chess.STARTING_FEN) -> dict[str, Any]:
        """Arrange the physical pieces for `fen` and start a game from it."""
        try:
            board = chess.Board(fen)
        except ValueError as e:
            raise ServiceError(f"bad FEN: {e}") from e
        async with self.lock:
            targets = self._assign(board)
            seconds = await self._arrange(targets)
            self.bridge = ChessBridge(self.world, board)
            self.synced = True
            self.history = []
            self._publish(self.snapshot())
        await self._engine_turn()
        return {"fen": board.fen(), "seconds": seconds}

    async def reset(self) -> dict[str, Any]:
        return await self.new_game()

    # -- motion layer -----------------------------------------------------

    async def goto(self, piece_id: str, square: str) -> dict[str, Any]:
        try:
            node = node_of(chess.parse_square(square))
        except ValueError as e:
            raise ServiceError(f"bad square {square!r}") from e
        return await self._free_move(piece_id, node, f"{piece_id} to {square}")

    async def park(self, piece_id: str) -> dict[str, Any]:
        self._piece(piece_id)
        if self.world.is_parked(self.world.pieces[piece_id]):
            return {"seconds": 0.0}
        return await self._free_move(piece_id, self.world.free_slot(), f"park {piece_id}")

    async def choreography(self, steps: list[tuple[str, str]]) -> dict[str, Any]:
        total = 0.0
        for piece_id, square in steps:
            total += (await self.goto(piece_id, square))["seconds"]
        return {"seconds": total}

    async def _free_move(self, piece_id: str, node: Node, label: str) -> dict[str, Any]:
        self._piece(piece_id)
        async with self.lock:
            if any(p.node == node for p in self.world.pieces.values() if p.id != piece_id):
                raise ServiceError("target is occupied")
            plan = await self._plan([(piece_id, node)])
            seconds = await self._execute(plan, label)
            self.synced = False
            self._publish(self.snapshot())
        return {"seconds": seconds, "blockers": plan.blockers}

    def _piece(self, piece_id: str) -> None:
        if piece_id not in self.world.pieces:
            raise ServiceError(f"unknown piece {piece_id!r}")

    # -- engine -----------------------------------------------------------

    async def set_engine(self, engine) -> None:
        if self.engine:
            await self.engine.close()
            self.engine = None
        if engine:
            await engine.start()
        self.engine = engine
        self._publish(self.snapshot())
        await self._engine_turn()

    async def _engine_turn(self) -> None:
        b = self.bridge.board
        if self.engine and self.synced and not b.is_game_over() and b.turn == self.engine.white:
            move = await self.engine.choose(b.copy())
            await self.move(move, origin="engine")

    # -- planning and execution --------------------------------------------

    async def _plan(self, tasks: list[tuple[str, Node]]) -> Plan:
        world = self.world.copy()
        try:
            return await asyncio.to_thread(self.planner.plan_sequence, world, tasks)
        except PlanningError as e:
            raise ServiceError(f"no motion plan: {e}") from e

    async def _execute(self, plan: Plan, label: str) -> float:
        dt = self.executor.dt
        duration = plan.steps * dt
        self._publish({"type": "plan", "label": label, "duration": duration,
                       "time_scale": self.time_scale,
                       "paths": {pid: [[w.x, w.y, w.t] for w in waypoints(self.lat, tr, dt)]
                                 for pid, tr in plan.trajectories.items()}})
        if self.realtime and duration:
            await asyncio.sleep(duration / self.time_scale)
        self.executor.run(plan, self.world)
        self._publish(self.snapshot())
        return duration

    def _assign(self, board: chess.Board) -> dict[str, Node]:
        """Choose a physical piece for every occupied square of `board`.

        Prefers the piece already standing there, then the piece whose home
        square it is, then the nearest free one of the right kind. Pieces not
        needed go (or stay) parked.
        """
        lat = self.lat
        targets: dict[str, Node] = {}
        used: set[str] = set()
        wanted = [(sq, board.piece_at(sq)) for sq in chess.SQUARES if board.piece_at(sq)]
        for sq, pc in wanted:
            node = node_of(sq)
            pool = [p for p in self.world.pieces.values()
                    if p.id not in used and p.white == pc.color and p.kind == KIND_OF[pc.piece_type]]
            if not pool:
                raise ServiceError(f"no physical {pc.symbol()} left for {chess.square_name(sq)}")
            xy = lat.xy[lat.index(node)]

            def rank(p):
                d = math.dist(lat.xy[lat.index(p.node)], xy)
                return (p.node != node, self.home[p.id] != node, d)

            best = min(pool, key=rank)
            targets[best.id] = node
            used.add(best.id)
        taken = set(targets.values())
        free_slots = [s for s in self.world.slots if s not in taken]
        for p in self.world.pieces.values():
            if p.id in used:
                continue
            if self.world.is_parked(p) and p.node not in taken:
                targets[p.id] = p.node
                free_slots.remove(p.node)
        for p in self.world.pieces.values():
            if p.id not in targets:
                targets[p.id] = free_slots.pop(0)
        return targets

    async def _arrange(self, targets: dict[str, Node]) -> float:
        """Bring every piece to its target, displacing occupants when needed."""
        total = 0.0
        for _ in range(4 * len(targets)):
            occupant = {p.node: p.id for p in self.world.pieces.values()}
            pending = [pid for pid, n in targets.items() if self.world.pieces[pid].node != n]
            if not pending:
                return total
            ready = [pid for pid in pending if targets[pid] not in occupant]
            if ready:
                try:
                    plan = await self._plan([(pid, targets[pid]) for pid in ready])
                except ServiceError:
                    plan = await self._plan([(ready[0], targets[ready[0]])])
                total += await self._execute(plan, "arrange")
                continue
            # Every pending target is taken: move one occupant to a spare slot.
            blocked = occupant[targets[pending[0]]]
            spare = [s for s in self.world.slots
                     if s not in occupant and s not in targets.values()]
            if not spare:
                spare = [s for s in self.world.slots if s not in occupant]
            plan = await self._plan([(blocked, spare[0])])
            total += await self._execute(plan, "arrange")
        raise ServiceError("could not arrange the pieces")
