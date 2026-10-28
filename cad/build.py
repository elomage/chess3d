"""Build the piece CAD: fit checks, mass report, STEP/STL exports, previews.

    python -m cad.build                    # all pieces into cad/out
    python -m cad.build --kinds P K --no-export
"""

from __future__ import annotations

import argparse
import math
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import cadquery as cq

from chess3d.geometry import Kind

from . import body, foot
from . import params as P

FOOT_KG = 0.8  # estimate until the prototype is weighed
FOOT_CG_Z = 30.0
# Distance from the axis to the nearest edge of the wheels' contact polygon.
TIP_ARM = P.WHEEL_RHO * math.cos(math.pi / len(P.WHEEL_ANGLES))
MIN_SKIRT_GAP = 3.0


@dataclass
class Report:
    kind: Kind
    shell_kg: float
    ballast_kg: float
    total_kg: float
    cg_z: float
    tip_accel: float
    skirt_tilt_deg: float
    sections: list[float]
    clearance: dict[str, float]
    seat_overlap_mm3: float

    def problems(self) -> list[str]:
        out = []
        for name, d in self.clearance.items():
            if d < P.MIN_CLEARANCE:
                out.append(f"{name} clearance {d:.2f}mm < {P.MIN_CLEARANCE}mm")
        tall = [h for h in self.sections if h > P.PRINT_BED_Z]
        if tall:
            out.append(f"sections taller than the print bed: {tall}")
        if self.seat_overlap_mm3 > 1.0:
            out.append(f"seat balls overlap the floor plate by {self.seat_overlap_mm3:.1f}mm^3")
        return out


def _min_distance(a: cq.Workplane, parts: dict[str, cq.Workplane]) -> tuple[float, str]:
    best, which = math.inf, ""
    for name, p in parts.items():
        d = a.val().distance(p.val())
        if d < best:
            best, which = d, name
    return best, which


def check(b: body.Body, foot_parts: dict[str, cq.Workplane]) -> Report:
    R = P.base_radius(b.kind)
    printed = [b.shell, b.floor_plate] + ([b.head] if b.head is not None else [])
    shell_kg, moment = 0.0, 0.0
    for s in printed:
        v = s.val()
        kg = v.Volume() * P.ASA * 1e-6
        shell_kg += kg
        moment += kg * v.Center().z
    ballast = b.ballast.val()
    ballast_kg = ballast.Volume() * P.BRASS * 1e-6
    moment += ballast_kg * ballast.Center().z + FOOT_KG * FOOT_CG_Z
    total = shell_kg + ballast_kg + FOOT_KG
    cg = moment / total
    parts = {k: v for k, v in foot_parts.items() if k != "balls"}
    clearance = {}
    for name, solid in (("shell", b.shell), ("floor_plate", b.floor_plate), ("ballast", b.ballast)):
        d, nearest = _min_distance(solid, parts)
        clearance[f"{name}-{nearest}"] = d
    overlap = b.floor_plate.intersect(foot_parts["balls"]).val().Volume()
    return Report(
        kind=b.kind, shell_kg=shell_kg, ballast_kg=ballast_kg, total_kg=total, cg_z=cg,
        tip_accel=9.81 * TIP_ARM / cg,
        skirt_tilt_deg=math.degrees(math.atan(MIN_SKIRT_GAP / (R - TIP_ARM))),
        sections=[s.val().BoundingBox().zlen for s in b.sections],
        clearance=clearance, seat_overlap_mm3=overlap)


def foot_checks(foot_parts: dict[str, cq.Workplane]) -> list[str]:
    """The foot alone: only wheels touch the board, nothing collides."""
    out = []
    for name, p in foot_parts.items():
        z = p.val().BoundingBox().zmin
        if name.startswith("wheel"):
            if abs(z) > 0.01:
                out.append(f"{name} bottom at z={z:.2f}, not on the board")
        elif z < 3.0:
            out.append(f"{name} only {z:.2f}mm above the board")
    names = list(foot_parts)
    touching = {("motor", "motor_mount"), ("posts", "base_plate"), ("posts", "top_plate"),
                ("motor_mount", "base_plate"), ("balls", "top_plate")}
    for i, a in enumerate(names):
        for bname in names[i + 1:]:
            kinds = (a.rsplit("_", 1)[0] if a[-1].isdigit() else a,
                     bname.rsplit("_", 1)[0] if bname[-1].isdigit() else bname)
            if kinds in touching or kinds[::-1] in touching:
                continue
            v = foot_parts[a].intersect(foot_parts[bname]).val().Volume()
            if v > 0.5:
                out.append(f"{a} and {bname} overlap by {v:.0f}mm^3")
    return out


def report_table(reports: list[Report]) -> str:
    rows = ["| Piece | Printed (kg) | Ballast (kg) | Total (kg) | Centre of mass (mm) "
            "| Tips at (m/s^2) | Tilt to skirt | Sections (mm) | Min clearance (mm) |",
            "|---|---|---|---|---|---|---|---|---|"]
    for r in reports:
        name, d = min(r.clearance.items(), key=lambda kv: kv[1])
        rows.append(f"| {r.kind.name.title()} | {r.shell_kg:.2f} | {r.ballast_kg:.2f} | {r.total_kg:.2f} "
                    f"| {r.cg_z:.0f} | {r.tip_accel:.1f} | {r.skirt_tilt_deg:.1f}° "
                    f"| {' + '.join(f'{h:.0f}' for h in r.sections)} | {d:.1f} ({name}) |")
    return "\n".join(rows)


def export(b: body.Body, out: Path) -> None:
    name = b.kind.name.lower()
    for i, s in enumerate(b.sections):
        cq.exporters.export(s, str(out / f"{name}_shell_{i + 1}.stl"), tolerance=0.05, angularTolerance=0.1)
    if b.head is not None:
        cq.exporters.export(b.head, str(out / f"{name}_head_placeholder.stl"))
    cq.exporters.export(b.ballast, str(out / f"{name}_ballast.step"))
    cq.exporters.export(b.shell, str(out / f"{name}_shell.step"))


def preview(b: body.Body, foot_parts: dict[str, cq.Workplane], path: Path) -> None:
    """Half-section through the piece axis, seen from the front, as SVG
    (and PNG when ImageMagick is available)."""
    R = P.base_radius(b.kind)
    keep = cq.Workplane("XY").box(4 * R, 2 * R, 3 * P.height(b.kind)).translate((0, R, 0))
    shapes = [b.shell, b.floor_plate, b.ballast] + list(foot_parts.values())
    if b.head is not None:
        shapes.append(b.head)
    half = cq.Assembly()
    for i, s in enumerate(shapes):
        cut = s.intersect(keep)
        if cut.val().Volume() > 0:
            half.add(cut, name=f"p{i}")
    svg = path.with_suffix(".svg")
    # The SVG exporter draws world x as up; turn the piece axis onto x.
    upright = half.toCompound().rotate(cq.Vector(0, 0, 0), cq.Vector(0, 1, 0), 90)
    cq.exporters.export(upright, str(svg), opt={
        "projectionDir": (0, -1, 0), "showHidden": False, "width": 500, "height": 700,
        "marginLeft": 20, "marginTop": 20, "strokeWidth": 0.4})
    if shutil.which("convert"):
        subprocess.run(["convert", "-density", "120", "-background", "white", "-flatten",
                        str(svg), str(path.with_suffix(".png"))], check=False)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--kinds", nargs="*", default=[k.value for k in Kind],
                    help="piece letters, e.g. P K (default: all)")
    ap.add_argument("--out", type=Path, default=Path(__file__).parent / "out")
    ap.add_argument("--no-export", action="store_true")
    ap.add_argument("--preview", action="store_true", help="write half-section previews")
    args = ap.parse_args()

    foot_parts = foot.parts()
    problems = foot_checks(foot_parts)
    reports = []
    if not args.no_export or args.preview:
        args.out.mkdir(parents=True, exist_ok=True)
    if not args.no_export:
        cq.exporters.export(foot.assembly(), str(args.out / "foot.step"))
        for name in ("top_plate", f"motor_mount_{P.WHEEL_ANGLES[0]:.0f}"):
            cq.exporters.export(foot_parts[name], str(args.out / f"{name}.stl"))
        cq.exporters.export(foot_parts["base_plate"], str(args.out / "base_plate.step"))
        cq.exporters.export(body.floor_plate(), str(args.out / "floor_plate.stl"))
    for letter in args.kinds:
        b = body.build(Kind(letter))
        r = check(b, foot_parts)
        reports.append(r)
        problems += [f"{b.kind.name.title()}: {p}" for p in r.problems()]
        if not args.no_export:
            export(b, args.out)
        if args.preview:
            preview(b, foot_parts, args.out / f"{b.kind.name.lower()}_section")
    table = report_table(reports)
    print(table)
    print("\n".join(["", "Problems:"] + problems) if problems else "\nNo fit problems.")
    if not args.no_export:
        (args.out / "report.md").write_text(table + "\n")


if __name__ == "__main__":
    main()
