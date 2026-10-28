// Hardware abstraction for the foot. Implement these for the actual PCB;
// hal.cpp holds placeholder versions so the rest builds and runs on a bare
// devkit (wheels do nothing, odometry integrates the commands).
#pragma once

#include <stdint.h>

namespace hal {

struct WheelSpeeds {
  // rad/s per wheel, in WHEEL_ANGLE order; positive turns the foot
  // anticlockwise seen from above
  float w[3];
};

struct ImuSample {
  float yaw;       // rad, integrated by the IMU fusion
  float yaw_rate;  // rad/s
  bool ok;
};

// Position of the nearest grid magnet relative to the foot centre, measured
// by the Hall sensor array; valid only when a magnet is under the array.
struct MagnetFix {
  bool valid;
  float fwd, left;  // m, in the foot frame
};

void begin();
void setWheelSpeeds(const WheelSpeeds& w);
WheelSpeeds wheelSpeeds();  // measured by the encoders
ImuSample imu();
MagnetFix magnet();
// NFC tag id of the mounted piece body ("" when none).
const char* bodyTag();
float battery();  // 0..1
bool onDock();

}  // namespace hal
