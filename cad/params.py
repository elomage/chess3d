"""Shared dimensions of the piece hardware, in millimetres.

World frame: the board surface is z = 0, the piece axis is z, and +y is the
direction the piece faces (towards the opponent for a knight). Piece base
diameters and heights come from chess3d.geometry so the CAD and the planner
agree.
"""

from __future__ import annotations

import math

from chess3d.geometry import FOOTPRINTS, Kind

# Drive: three omni wheels at 120 degrees (kiwi drive), axles radial, one
# wheel straight ahead. Three wheels always share the load on a board that
# is not perfectly flat; mecanum wheels on +-45mm reach 89mm from the centre
# and do not fit in the 170mm pawn base.
WHEEL_D = 48.0
WHEEL_W = 22.0
WHEEL_RHO = 60.0  # centre of the wheel's contact from the piece axis
WHEEL_ANGLES = (90.0, 210.0, 330.0)
AXLE_Z = WHEEL_D / 2

# Micro metal gearmotor with a magnetic encoder: 12 x 10mm section.
MOTOR_LEN = 30.0  # gearbox + motor + encoder
MOTOR_W = 12.0
MOTOR_H = 10.0
MOTOR_GAP = 1.0  # gearbox face to the wheel's inner face

# Chassis stack.
HALL_Z = 4.0  # underside of the Hall sensor board
HALL_ARM = 70.0  # centre to the end of each arm of the Y-shaped board
HALL_ARM_ANGLES = (30.0, 150.0, 270.0)  # between the wheels
HALL_ARM_W = 16.0
PCB_T = 1.6
BASE_PLATE_Z = 9.0
BASE_PLATE_T = 4.0
BASE_PLATE_R = 75.0
BATTERY = (70.0, 40.0, 21.0)  # 2 x 18650 holder, x, y, z
BATTERY_Z = 31.0
MAIN_PCB = (70.0, 50.0)
MAIN_PCB_Z = 56.0
MAIN_PCB_PARTS_H = 8.0
POST_RHO = 46.0
POST_ANGLES = (30.0, 150.0, 270.0)  # between the wheels
POST_D = 6.0
TOP_PLATE_Z = 70.0
TOP_PLATE_T = 4.0
TOP_PLATE_R = 52.0

# Kinematic seat: three steel balls in the top plate, sitting in three radial
# 90-degree V-grooves in the body's floor plate.
BALL_D = 6.0
BALL_RHO = 40.0
BALL_ANGLES = (90.0, 210.0, 330.0)
BALL_Z = TOP_PLATE_Z + TOP_PLATE_T + 1.0  # centre, 1mm proud of the plate
GROOVE_DEPTH = 4.0
# A ball of radius r in a 90-degree V touches both flanks when the V's apex
# is r * sqrt(2) above the ball centre.
FLOOR_Z = BALL_Z + BALL_D / 2 * math.sqrt(2) - GROOVE_DEPTH  # floor plate underside

# Bayonet: three lugs on a collar under the floor plate hook under the top
# plate. Unequal lug widths allow only one orientation, so the body's
# heading is fixed to the foot's.
FLOOR_T = 5.0
FLOOR_R = 58.0
COLLAR_R_OUT = 57.0
COLLAR_R_IN = 53.5
COLLAR_H = 10.0
LUG_R_IN = 49.0
LUG_H = 3.0
LUG_ANGLES = (90.0, 210.0, 330.0)  # locked position
LUG_WIDTHS = (24.0, 16.0, 16.0)  # degrees
BAYONET_TURN = 40.0  # degrees from insertion to locked

# Body shell.
SKIRT_GAP = 4.0  # skirt above the board; shims in the floor plate set 3-5mm
WALL = 2.4
LEDGE_H = 3.0  # glue ledge above the floor plate
LEDGE_R_IN = 52.0
LIP_H = 2.0  # lip at the skirt bottom that carries the ballast ring
LIP_R_IN = 77.0
BALLAST_R_IN = 78.0
BALLAST_MAX_H = 8.0
PRINT_BED_Z = 256.0  # tallest section a printer takes

# Materials, g/cm^3.
ASA = 1.07
BRASS = 8.5

# Clearance the checks require between foot and body.
MIN_CLEARANCE = 1.0

BALLAST_KG = {Kind.PAWN: 0.20, Kind.ROOK: 0.20, Kind.KNIGHT: 0.30,
              Kind.BISHOP: 0.30, Kind.QUEEN: 0.40, Kind.KING: 0.50}


def base_radius(kind: Kind) -> float:
    return FOOTPRINTS[kind].base_diameter * 1000 / 2


def height(kind: Kind) -> float:
    return FOOTPRINTS[kind].height * 1000
