# Piece CAD

Parametric CadQuery models of the drive foot and the six piece bodies, with
fit checks and a mass report. Dimensions live in `params.py`; piece base
diameters and heights come from `chess3d/geometry.py`.

- `foot.py` - chassis (base plate, motor mounts, posts, top plate with the
  kinematic seat and bayonet notches) and stand-ins for bought parts (omni
  wheels, gearmotors, battery, PCBs, NFC antenna)
- `body.py` - revolved Staunton shells split into print sections, the
  shared floor plate (seat grooves, bayonet collar and lugs) and the brass
  ballast rings; the knight's head is a placeholder for the commissioned
  sculpt
- `build.py` - checks, report and exports

Install and build:

    .venv/bin/pip install -e ".[cad]"
    .venv/bin/python -m cad.build                 # STEP/STL and report.md into cad/out
    .venv/bin/python -m cad.build --kinds P K --no-export --preview

The checks fail the build report (and `tests/test_cad.py`) when foot and
body come closer than 1mm, foot parts collide, anything but the wheels is
within 3mm of the board, or a shell section is taller than the 256mm print
bed.

Not modelled yet: section joints (alignment pins), the bayonet's locking
ramp and detent, the NFC tag pocket, charging pogo pins, motor clamp
screws, and the knight's real head.
