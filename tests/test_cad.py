"""Fit checks on the piece CAD. Skipped when CadQuery is not installed."""

import pytest

pytest.importorskip("cadquery")

from cad import body, build, foot  # noqa: E402
from chess3d.geometry import Kind  # noqa: E402


@pytest.fixture(scope="module")
def foot_parts():
    return foot.parts()


def test_foot_parts_clear_each_other_and_the_board(foot_parts):
    assert build.foot_checks(foot_parts) == []


@pytest.mark.parametrize("kind", [Kind.PAWN, Kind.KING])  # tightest base, tallest piece
def test_body_fits_the_foot(foot_parts, kind):
    r = build.check(body.build(kind), foot_parts)
    assert r.problems() == []
    assert r.tip_accel > 3.0  # twice the planned 1.5m/s^2 limit
