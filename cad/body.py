"""Piece bodies: revolved Staunton shells, floor plates and ballast rings.

Each shell is a profile revolved about the piece axis, hollowed to WALL and
open at the bottom. All pieces share one plinth; above it each kind has its
own stem, collar and crown, given as fractions of its height H and base
radius R. The knight's head here is a placeholder silhouette for fit and
mass checks; the real head is a commissioned sculpt.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import cadquery as cq

from chess3d.geometry import Kind

from . import params as P
from .foot import lug_sector

# Profile segments, (z, r) in mm: ("l", (z, r)) line, ("s", [(z, r), ...])
# spline through the points, ("a", (z, r) mid, (z, r) end) arc.
Seg = tuple


@dataclass
class Body:
    kind: Kind
    shell: cq.Workplane  # whole shell, world frame
    sections: list[cq.Workplane] = field(default_factory=list)
    splits: list[float] = field(default_factory=list)
    floor_plate: cq.Workplane | None = None
    ballast: cq.Workplane | None = None
    head: cq.Workplane | None = None  # knight only, placeholder


def plinth(R: float) -> list[Seg]:
    """Shared plinth, from the skirt up to PLINTH_TOP."""
    g = P.SKIRT_GAP
    return [("l", (g + 10, R)), ("l", (g + 14, R - 3)), ("l", (g + 26, R - 3)),
            ("l", (g + 30, R - 1)), ("l", (g + 36, R - 1)), ("l", (g + 42, R - 4)),
            ("l", (PLINTH_TOP, R - 4))]


PLINTH_TOP = P.SKIRT_GAP + 50


def _ball(H: float, rb: float, rn: float) -> list[Seg]:
    """Ball finial of radius rb on top, joined from a neck of radius rn."""
    zc = H - rb
    zn = zc - math.sqrt(rb * rb - rn * rn)
    a0 = math.atan2(zn - zc, rn)
    am = (a0 + math.pi / 2) / 2
    return [("l", (zn, rn)), ("a", (zc + rb * math.sin(am), rb * math.cos(am)), (H, 0.0))]


def _f(H: float, R: float, pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    return [(zf * H, rf * R) for zf, rf in pts]


def _lines(H: float, R: float, pts: list[tuple[float, float]]) -> list[Seg]:
    return [("l", p) for p in _f(H, R, pts)]


def profile(kind: Kind, H: float, R: float) -> list[Seg]:
    seg = plinth(R)
    if kind is Kind.PAWN:
        seg += [("s", _f(H, R, [(0.21, 0.86), (0.30, 0.74), (0.42, 0.57), (0.55, 0.42), (0.655, 0.30)]))]
        seg += _lines(H, R, [(0.665, 0.30), (0.665, 0.47), (0.70, 0.47), (0.70, 0.27)])
        seg += _ball(H, 0.145 * H, 0.26 * R)
    elif kind is Kind.ROOK:
        seg += [("s", _f(H, R, [(0.20, 0.84), (0.30, 0.70), (0.50, 0.60), (0.68, 0.56)]))]
        seg += [("s", _f(H, R, [(0.74, 0.62), (0.78, 0.70)]))]
        seg += _lines(H, R, [(0.78, 0.74), (0.80, 0.74), (0.80, 0.68), (1.0, 0.68),
                             (1.0, 0.52), (0.93, 0.52), (0.93, 0.0)])
    elif kind is Kind.KNIGHT:
        seg += [("s", _f(H, R, [(0.19, 0.84), (0.26, 0.66)]))]
        seg += _lines(H, R, [(0.30, 0.60), (0.30, 0.0)])
    elif kind is Kind.BISHOP:
        seg += [("s", _f(H, R, [(0.16, 0.82), (0.24, 0.64), (0.40, 0.40), (0.55, 0.29), (0.615, 0.26)]))]
        seg += _lines(H, R, [(0.615, 0.47), (0.645, 0.47), (0.645, 0.25), (0.665, 0.22)])
        seg += [("s", _f(H, R, [(0.72, 0.30), (0.79, 0.35), (0.87, 0.29), (0.915, 0.10)]))]
        seg += _ball(H, 0.04 * H, 0.07 * R)
    elif kind is Kind.QUEEN:
        seg += [("s", _f(H, R, [(0.13, 0.82), (0.20, 0.64), (0.40, 0.37), (0.58, 0.27), (0.615, 0.26)]))]
        seg += _lines(H, R, [(0.615, 0.48), (0.64, 0.48), (0.64, 0.26)])
        seg += [("s", _f(H, R, [(0.70, 0.30), (0.78, 0.40), (0.83, 0.46)]))]
        seg += _lines(H, R, [(0.86, 0.47), (0.86, 0.40)])
        seg += [("s", _f(H, R, [(0.89, 0.30), (0.905, 0.11)]))]
        seg += _ball(H, 0.045 * H, 0.08 * R)
    elif kind is Kind.KING:
        seg += [("s", _f(H, R, [(0.12, 0.82), (0.19, 0.63), (0.40, 0.36), (0.58, 0.27), (0.62, 0.26)]))]
        seg += _lines(H, R, [(0.62, 0.47), (0.645, 0.47), (0.645, 0.26)])
        seg += [("s", _f(H, R, [(0.72, 0.31), (0.80, 0.40), (0.835, 0.43)]))]
        seg += _lines(H, R, [(0.855, 0.44), (0.855, 0.36)])
        seg += [("s", _f(H, R, [(0.875, 0.26), (0.885, 0.10)]))]
        seg += _lines(H, R, [(0.885, 0.0)])
    return seg


# Print sections: split heights as fractions of H, on top of the plinth split.
SPLITS = {Kind.PAWN: [], Kind.ROOK: [0.78], Kind.KNIGHT: [], Kind.BISHOP: [0.615],
          Kind.QUEEN: [0.615], Kind.KING: [0.18, 0.62]}


def _revolve(seg: list[Seg], R: float) -> cq.Workplane:
    # On the XZ workplane local (x, y) is world (x, z): x = radius, y = height.
    wp = cq.Workplane("XZ").moveTo(0, P.SKIRT_GAP).lineTo(R, P.SKIRT_GAP)
    for s in seg:
        if s[0] == "l":
            z, r = s[1]
            wp = wp.lineTo(r, z)
        elif s[0] == "s":
            wp = wp.spline([(r, z) for z, r in s[1]], includeCurrent=True)
        else:
            (zm, rm), (z, r) = s[1], s[2]
            wp = wp.threePointArc((rm, zm), (r, z))
    return wp.close().revolve(360, (0, 0, 0), (0, 1, 0))


def _ring(r_in: float, r_out: float, z0: float, h: float) -> cq.Workplane:
    return cq.Workplane("XY").workplane(offset=z0).circle(r_out).circle(r_in).extrude(h)


def floor_plate() -> cq.Workplane:
    """Same for every body: the seat grooves and bayonet lugs face the foot;
    the shell's spigot and ledge locate it."""
    plate = cq.Workplane("XY").workplane(offset=P.FLOOR_Z).circle(P.FLOOR_R).extrude(P.FLOOR_T)
    d = P.GROOVE_DEPTH
    for a in P.BALL_ANGLES:
        groove = (cq.Workplane("YZ").workplane(offset=P.BALL_RHO - 8)
                  .polyline([(-d, P.FLOOR_Z - 0.01), (d, P.FLOOR_Z - 0.01), (0, P.FLOOR_Z + d)])
                  .close().extrude(16))
        plate = plate.cut(groove.rotate((0, 0, 0), (0, 0, 1), a))
    collar_z = P.FLOOR_Z - P.COLLAR_H
    plate = plate.union(_ring(P.COLLAR_R_IN, P.COLLAR_R_OUT, collar_z, P.COLLAR_H + 0.01))
    for a, w in zip(P.LUG_ANGLES, P.LUG_WIDTHS):
        plate = plate.union(lug_sector(P.LUG_R_IN, P.COLLAR_R_IN + 0.5, collar_z, P.LUG_H, a, w))
    return plate


def knight_head(H: float, R: float) -> cq.Workplane:
    """Placeholder head: a silhouette facing +y, extruded and hollowed."""
    pts = [(-0.45, 0.30), (0.40, 0.30), (0.45, 0.50), (0.75, 0.72), (0.80, 0.82), (0.55, 0.90),
           (0.20, 0.98), (0.0, 1.0), (-0.15, 0.97), (-0.45, 0.85), (-0.55, 0.60)]
    t = 0.5 * R
    head = (cq.Workplane("YZ").workplane(offset=-t / 2)
            .polyline([(yf * R, zf * H) for yf, zf in pts]).close().extrude(t))
    return head.shell(-P.WALL)


def _crown(kind: Kind, shell: cq.Workplane, H: float, R: float) -> cq.Workplane:
    if kind is Kind.ROOK:
        for a in (0, 45, 90, 135):
            notch = cq.Workplane("XY").box(2.2 * R, 0.22 * R, 0.07 * H + 1).translate((0, 0, H - 0.035 * H + 0.5))
            shell = shell.cut(notch.rotate((0, 0, 0), (0, 0, 1), a + 22.5))
    elif kind is Kind.BISHOP:
        slot = (cq.Workplane("XY").box(2 * R, R, 6).translate((0, R / 2, 0))
                .rotate((0, 0, 0), (1, 0, 0), -35).translate((0, 0, 0.80 * H)))
        shell = shell.cut(slot)
    elif kind is Kind.QUEEN:
        for k in range(8):
            a = math.radians(22.5 + 45 * k)
            r = 0.47 * R
            shell = shell.cut(cq.Workplane("XY").sphere(0.07 * R).translate(
                (r * math.cos(a), r * math.sin(a), 0.865 * H)))
    elif kind is Kind.KING:
        z0 = 0.885 * H - 1
        bar = cq.Workplane("XY").box(0.14 * R, 0.11 * R, H - z0).translate((0, 0, (z0 + H) / 2))
        arm = cq.Workplane("XY").box(0.42 * R, 0.11 * R, 0.12 * R).translate((0, 0, 0.95 * H))
        shell = shell.union(bar).union(arm)
    return shell


def ballast_ring(kind: Kind, R: float) -> tuple[cq.Workplane, float]:
    """Brass ring on the skirt lip, sized for BALLAST_KG up to BALLAST_MAX_H.
    Returns the ring and its mass in kg."""
    r_out = R - P.WALL - 0.3
    area = math.pi * (r_out ** 2 - P.BALLAST_R_IN ** 2)
    h = min(P.BALLAST_KG[kind] / (area * P.BRASS * 1e-6), P.BALLAST_MAX_H)
    ring = _ring(P.BALLAST_R_IN, r_out, P.SKIRT_GAP + P.LIP_H, h)
    return ring, area * h * P.BRASS * 1e-6


def build(kind: Kind) -> Body:
    H, R = P.height(kind), P.base_radius(kind)
    outer = _revolve(profile(kind, H, R), R)
    shell = outer.faces("<Z").shell(-P.WALL)
    # Spigot round the floor plate, glue ledge above it, lip for the ballast.
    fit = (_ring(P.FLOOR_R + 0.2, R, P.FLOOR_Z, P.FLOOR_T)
           .union(_ring(P.LEDGE_R_IN, R, P.FLOOR_Z + P.FLOOR_T, P.LEDGE_H))
           .union(_ring(P.LIP_R_IN, R, P.SKIRT_GAP, P.LIP_H)))
    shell = shell.union(fit.intersect(outer))
    shell = _crown(kind, shell, H, R)
    head = None
    if kind is Kind.KNIGHT:
        head = knight_head(H, R)
    splits = [PLINTH_TOP] + [f * H for f in SPLITS[kind]]
    sections, z0 = [], 0.0
    for z1 in splits + [H + 1]:
        box = cq.Workplane("XY").box(3 * R, 3 * R, z1 - z0).translate((0, 0, (z0 + z1) / 2))
        sections.append(shell.intersect(box))
        z0 = z1
    ballast, _ = ballast_ring(kind, R)
    return Body(kind, shell, sections, splits, floor_plate(), ballast, head)
