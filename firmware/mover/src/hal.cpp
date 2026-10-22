// Placeholder hardware layer: no motors, sensors or tag reader attached.
// The commanded wheel speeds are echoed back as "measured", so odometry and
// the whole protocol can be exercised on a bare ESP32 devkit.
#include "hal.h"

#include <Arduino.h>

namespace hal {

static WheelSpeeds g_cmd{0, 0, 0, 0};
static float g_yaw = 0.0f;
static uint32_t g_last_us = 0;

void begin() { g_last_us = micros(); }

void setWheelSpeeds(const WheelSpeeds& w) { g_cmd = w; }

WheelSpeeds wheelSpeeds() { return g_cmd; }

ImuSample imu() {
  // TODO: read the IMU (e.g. BNO085 game rotation vector over I2C).
  return {g_yaw, 0.0f, false};
}

MagnetFix magnet() {
  // TODO: read the Hall array (e.g. 3x3 DRV5055 through an ADC mux), fit the
  // magnet position and field direction.
  return {false, 0.0f, 0.0f};
}

const char* bodyTag() {
  // TODO: read the NTAG in the body over the PN532/ST25 reader. Until then
  // the tag can be set at build time for bench tests.
#ifdef BODY_TAG
  return BODY_TAG;
#else
  return "";
#endif
}

float battery() { return 1.0f; }

bool onDock() { return false; }

}  // namespace hal
