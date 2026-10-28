// Per-installation settings. Copy to config_local.h to override without
// committing credentials.
#pragma once

#if __has_include("config_local.h")
#include "config_local.h"
#endif

#ifndef WIFI_SSID
#define WIFI_SSID "chess3d"
#endif
#ifndef WIFI_PASSWORD
#define WIFI_PASSWORD "change-me"
#endif
#ifndef ORCHESTRATOR_IP
#define ORCHESTRATOR_IP "10.0.0.1"
#endif
#ifndef ORCHESTRATOR_PORT
#define ORCHESTRATOR_PORT 4210
#endif

// Control and reporting rates (Hz).
constexpr float CONTROL_HZ = 200.0f;
constexpr float STATUS_HZ_MOVING = 10.0f;
constexpr float STATUS_HZ_IDLE = 2.0f;

// Drive geometry: three omni wheels at 120 degrees (metres, radians). Wheel
// angles run from the foot's forward axis towards its left; wheel 0 is
// straight ahead. Matches cad/params.py.
constexpr float WHEEL_RADIUS = 0.024f;
constexpr float WHEEL_RHO = 0.060f;  // centre to wheel contact
constexpr int WHEELS = 3;
constexpr float WHEEL_ANGLE[WHEELS] = {0.0f, 2.0943951f, 4.1887902f};
constexpr float MAX_SPEED = 0.45f;        // m/s
constexpr float MAX_ACCEL = 0.8f;         // m/s^2, keeps a 57cm king upright

// Path tracking gains and limits.
constexpr float K_POS = 3.0f;    // 1/s
constexpr float K_HEADING = 4.0f;
constexpr float MAX_TRACKING_ERROR = 0.05f;  // m; beyond this the foot stops itself

// Magnet grid embedded in the board: one magnet per lattice step of a
// square (1/6 of 333mm) would be dense; the rig uses square corners and
// centres, i.e. a 166.7mm pitch.
constexpr float MAGNET_PITCH = 0.3333333f / 2.0f;
