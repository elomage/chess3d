"""Hardware stack over real UDP sockets against emulated mover firmware."""

import asyncio
import math

import chess
import pytest

from chess3d.chess_layer.bridge import node_of
from chess3d.hardware import Hardware
from chess3d.service import Paused
from chess3d.transport.protocol import ProtocolError, decode, encode, path_message
from chess3d.world import World

SPEED = 1.0  # fast motion keeps the tests short


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 60))


async def rig() -> Hardware:
    hw = Hardware(World.rig(), host="127.0.0.1", port=0, speed=SPEED, emulate=True)
    missing = await hw.start(wait=5)
    assert missing == []
    return hw


def at(hw: Hardware, pid: str, square: int) -> bool:
    x, y = hw.service.lat.xy[hw.service.lat.index(node_of(square))]
    return hw.fleet.distance_from(pid, x, y) < 0.01


def test_protocol_round_trip():
    msg = path_message(3, [(0.1, 0.2, 0.0), (0.3, 0.2, 1.5)], math.pi, 200)
    assert decode(encode(msg)) == msg
    with pytest.raises(ProtocolError):
        decode(b'{"t":"nonsense"}')
    with pytest.raises(ProtocolError):
        path_message(1, [(0, 0, t) for t in range(100)], 0.0, 0)


def test_move_over_udp():
    async def scenario():
        hw = await rig()
        try:
            await hw.service.goto("wNb1", "c3")
            assert at(hw, "wNb1", chess.C3)
            assert hw.service.world.pieces["wNb1"].node == node_of(chess.C3)
            assert hw.fleet.feet["wNb1"].h == pytest.approx(0.0)  # faces the opponent
        finally:
            await hw.close()

    run(scenario())


def test_slip_is_recovered_automatically():
    async def scenario():
        hw = await rig()
        try:
            hw.fleet.feet["wNb1"].faults.slip = (0.3, 0.06, 0.0)
            events = hw.service.subscribe()
            await hw.service.goto("wNb1", "c3")
            assert at(hw, "wNb1", chess.C3)
            assert hw.service.fault is None
            kinds = []
            while not events.empty():
                kinds.append(events.get_nowait()["type"])
            assert "fault" in kinds
        finally:
            await hw.close()

    run(scenario())


def test_stall_pauses_then_resumes_after_fix():
    async def scenario():
        hw = await rig()
        svc = hw.service
        try:
            foot = hw.fleet.feet["wRa1"]
            foot.faults.stall_after = 0.2  # wheels blocked: every attempt stalls
            with pytest.raises(Paused):
                await svc.goto("wRa1", "a4")
            assert svc.fault and svc.fault["piece"] == "wRa1"
            with pytest.raises(Paused):
                await svc.goto("wPb2", "b3")
            result = await svc.resume()
            assert not result["resumed"]
            assert [d["piece"] for d in result["discrepancies"]] == ["wRa1"]
            foot.faults.stall_after = None  # obstruction removed
            result = await svc.resume(adopt=True)
            assert result["resumed"], result
            assert at(hw, "wRa1", chess.A4)
            assert not svc.synced  # the pending free move was committed
            await svc.goto("wPb2", "b3")
        finally:
            await hw.close()

    run(scenario())


def test_silent_foot_pauses_and_reports_missing():
    async def scenario():
        hw = await rig()
        svc = hw.service
        try:
            hw.fleet.feet["wPa2"].faults.silent_after = 0.0
            await asyncio.sleep(1.2)  # longer than the hub's stale timeout
            with pytest.raises(Paused):
                await svc.goto("wNb1", "c3")
            problems = {d["piece"]: d["problem"] for d in svc.discrepancies()}
            assert problems.get("wPa2") == "missing"
        finally:
            await hw.close()

    run(scenario())


def test_body_tag_binds_foot_to_piece():
    async def scenario():
        hw = await rig()
        try:
            hub = hw.hub
            foot_a = hub.bound["wPa2"]
            # Swap bodies: the foot under a2 now carries the b2 body and vice versa.
            hw.fleet.feet["wPa2"].faults.swap_tag = "wPb2"
            hw.fleet.feet["wPb2"].faults.swap_tag = "wPa2"
            await asyncio.sleep(0.8)
            assert hub.bound["wPb2"] == foot_a
            # The world expected b2 at b2: now the b2 body is sensed at a2.
            problems = {d["piece"] for d in hw.service.discrepancies()}
            assert problems == {"wPa2", "wPb2"}
        finally:
            await hw.close()

    run(scenario())
