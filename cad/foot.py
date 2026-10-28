"""The drive foot: chassis parts plus stand-ins for bought components.

Every part is placed in the world frame (see params), so the foot can be
checked against any body without further transforms.
"""

from __future__ import annotations

import math

import cadquery as cq

from . import params as P


def _radial(shape: cq.Workplane, angle: float) -> cq.Workplane:
    """Rotate a part built along +x about the piece axis."""
    return shape.rotate((0, 0, 0), (0, 0, 1), angle)


def wheel(angle: float) -> cq.Workplane:
    """Omni wheel stand-in: a cylinder on a radial axle."""
    w = (cq.Workplane("YZ").workplane(offset=P.WHEEL_RHO - P.WHEEL_W / 2)
         .center(0, P.AXLE_Z).circle(P.WHEEL_D / 2).extrude(P.WHEEL_W))
    return _radial(w, angle)


def motor(angle: float) -> cq.Workplane:
    outer = P.WHEEL_RHO - P.WHEEL_W / 2 - P.MOTOR_GAP
    m = cq.Workplane("XY").box(P.MOTOR_LEN, P.MOTOR_W, P.MOTOR_H).translate(
        (outer - P.MOTOR_LEN / 2, 0, P.AXLE_Z))
    return _radial(m, angle)


def motor_mount(angle: float) -> cq.Workplane:
    """Printed clamp block between the base plate and the motor."""
    bottom = P.BASE_PLATE_Z + P.BASE_PLATE_T
    h = P.AXLE_Z - P.MOTOR_H / 2 - bottom
    outer = P.WHEEL_RHO - P.WHEEL_W / 2 - P.MOTOR_GAP
    b = cq.Workplane("XY").box(P.MOTOR_LEN - 6, P.MOTOR_W + 4, h).translate(
        (outer - P.MOTOR_LEN / 2, 0, bottom + h / 2))
    return _radial(b, angle)


def base_plate() -> cq.Workplane:
    """Machined aluminium plate, open at each wheel."""
    plate = (cq.Workplane("XY").workplane(offset=P.BASE_PLATE_Z)
             .circle(P.BASE_PLATE_R).extrude(P.BASE_PLATE_T))
    inner = P.WHEEL_RHO - P.WHEEL_W / 2 - 2
    span = P.BASE_PLATE_R + 5 - inner
    for a in P.WHEEL_ANGLES:
        cut = cq.Workplane("XY").box(span, P.WHEEL_D + 4, 40).translate(
            (inner + span / 2, 0, P.BASE_PLATE_Z))
        plate = plate.cut(_radial(cut, a))
    return plate


def hall_board() -> cq.Workplane:
    """Y-shaped sensor board; its arms run between the wheels."""
    z = P.HALL_Z + P.PCB_T / 2
    hub = cq.Workplane("XY").cylinder(P.PCB_T, P.HALL_ARM_W).translate((0, 0, z))
    for a in P.HALL_ARM_ANGLES:
        arm = cq.Workplane("XY").box(P.HALL_ARM, P.HALL_ARM_W, P.PCB_T).translate((P.HALL_ARM / 2, 0, z))
        hub = hub.union(_radial(arm, a))
    return hub


def hall_sensors() -> list[tuple[float, float]]:
    """Sensor positions on the Y: the centre and two per arm."""
    step = (P.HALL_ARM - 4) / 2
    pts = [(0.0, 0.0)]
    for a in P.HALL_ARM_ANGLES:
        c, s = math.cos(math.radians(a)), math.sin(math.radians(a))
        pts += [(step * k * c, step * k * s) for k in (1, 2)]
    return pts


def battery() -> cq.Workplane:
    x, y, z = P.BATTERY
    return cq.Workplane("XY").box(x, y, z).translate((0, 0, P.BATTERY_Z + z / 2))


def main_pcb() -> cq.Workplane:
    x, y = P.MAIN_PCB
    board = cq.Workplane("XY").box(x, y, P.PCB_T).translate((0, 0, P.MAIN_PCB_Z + P.PCB_T / 2))
    parts = cq.Workplane("XY").box(x - 4, y - 4, P.MAIN_PCB_PARTS_H).translate(
        (0, 0, P.MAIN_PCB_Z + P.PCB_T + P.MAIN_PCB_PARTS_H / 2))
    return board.union(parts)


def posts() -> cq.Workplane:
    bottom = P.BASE_PLATE_Z + P.BASE_PLATE_T
    h = P.TOP_PLATE_Z - bottom
    pts = [(P.POST_RHO * math.cos(math.radians(a)), P.POST_RHO * math.sin(math.radians(a)))
           for a in P.POST_ANGLES]
    return (cq.Workplane("XY").workplane(offset=bottom).pushPoints(pts)
            .circle(P.POST_D / 2).extrude(h))


def lug_sector(r_in: float, r_out: float, z0: float, h: float, angle: float,
               width: float) -> cq.Workplane:
    """Annular sector centred on `angle`, `width` degrees wide."""
    ring = (cq.Workplane("XY").workplane(offset=z0).circle(r_out).circle(r_in).extrude(h))
    a0, a1 = math.radians(angle - width / 2), math.radians(angle + width / 2)
    far = r_out * 2
    wedge = (cq.Workplane("XY").workplane(offset=z0 - 1)
             .polyline([(0, 0), (far * math.cos(a0), far * math.sin(a0)),
                        (far * math.cos((a0 + a1) / 2) * 1.5, far * math.sin((a0 + a1) / 2) * 1.5),
                        (far * math.cos(a1), far * math.sin(a1))]).close().extrude(h + 2))
    return ring.intersect(wedge)


def top_plate() -> cq.Workplane:
    """Printed plate: carries the seat balls and lets the lugs pass at the
    insertion angle. Printed, not metal, so the NFC reader sees through it."""
    plate = (cq.Workplane("XY").workplane(offset=P.TOP_PLATE_Z)
             .circle(P.TOP_PLATE_R).extrude(P.TOP_PLATE_T))
    for a, w in zip(P.LUG_ANGLES, P.LUG_WIDTHS):
        notch = lug_sector(P.LUG_R_IN - 0.5, P.TOP_PLATE_R + 1, P.TOP_PLATE_Z - 1,
                           P.TOP_PLATE_T + 2, a - P.BAYONET_TURN, w + 2)
        plate = plate.cut(notch)
    return plate


def balls() -> cq.Workplane:
    out = None
    for a in P.BALL_ANGLES:
        x, y = P.BALL_RHO * math.cos(math.radians(a)), P.BALL_RHO * math.sin(math.radians(a))
        s = cq.Workplane("XY").sphere(P.BALL_D / 2).translate((x, y, P.BALL_Z))
        out = s if out is None else out.union(s)
    return out


def nfc_antenna() -> cq.Workplane:
    return cq.Workplane("XY").box(30, 30, 1).translate((0, 0, P.TOP_PLATE_Z - 1.5))


def parts() -> dict[str, cq.Workplane]:
    """Every foot part by name; wheels, motors and mounts are numbered by
    their angle."""
    out = {
        "base_plate": base_plate(),
        "hall_board": hall_board(),
        "battery": battery(),
        "main_pcb": main_pcb(),
        "posts": posts(),
        "top_plate": top_plate(),
        "balls": balls(),
        "nfc_antenna": nfc_antenna(),
    }
    for a in P.WHEEL_ANGLES:
        out[f"wheel_{a:.0f}"] = wheel(a)
        out[f"motor_{a:.0f}"] = motor(a)
        out[f"motor_mount_{a:.0f}"] = motor_mount(a)
    return out


def assembly() -> cq.Workplane:
    out = None
    for p in parts().values():
        out = p if out is None else out.union(p)
    return out
