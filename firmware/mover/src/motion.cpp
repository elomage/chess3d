#include "motion.h"

#include <Arduino.h>
#include <math.h>

#include "config.h"
#include "hal.h"

const char* stateName(State s) {
  switch (s) {
    case State::Idle: return "idle";
    case State::Moving: return "moving";
    case State::Docked: return "docked";
    default: return "fault";
  }
}

static float wrapAngle(float a) {
  while (a > PI) a -= 2 * PI;
  while (a < -PI) a += 2 * PI;
  return a;
}

// -- Estimator --------------------------------------------------------------

void Estimator::update(float dt) {
  // Forward kinematics of the omni base: wheel speeds to body velocity.
  // Wheel i's rim speed is u = -sin(a) vx + cos(a) vy + rho wz; with the
  // wheels 120 degrees apart this inverts exactly.
  hal::WheelSpeeds w = hal::wheelSpeeds();
  float su = 0, cu = 0, u_sum = 0;
  for (int i = 0; i < WHEELS; i++) {
    float u = WHEEL_RADIUS * w.w[i];
    su += sinf(WHEEL_ANGLE[i]) * u;
    cu += cosf(WHEEL_ANGLE[i]) * u;
    u_sum += u;
  }
  float bvx = -2.0f / 3 * su;
  float bvy = 2.0f / 3 * cu;
  float bwz = u_sum / (3 * WHEEL_RHO);

  hal::ImuSample imu = hal::imu();
  if (imu.ok) {
    if (!yaw_aligned_) {
      yaw_offset_ = imu.yaw - pose_.h;
      yaw_aligned_ = true;
    }
    pose_.h = wrapAngle(imu.yaw - yaw_offset_);
  } else {
    pose_.h = wrapAngle(pose_.h + bwz * dt);
  }
  // Heading 0 faces +y (rank 8). Body frame: forwards f = (-sin h, cos h),
  // left l = (-cos h, -sin h).
  float c = cosf(pose_.h), s = sinf(pose_.h);
  pose_.x += (-s * bvx - c * bvy) * dt;
  pose_.y += (c * bvx - s * bvy) * dt;

  hal::MagnetFix fix = hal::magnet();
  if (fix.valid) {
    // Magnet position in the board frame, snapped to the grid it belongs
    // to; the foot is then where that grid point minus the offset puts it.
    float ox = -s * fix.fwd - c * fix.left;
    float oy = c * fix.fwd - s * fix.left;
    float gx = roundf((pose_.x + ox) / MAGNET_PITCH) * MAGNET_PITCH;
    float gy = roundf((pose_.y + oy) / MAGNET_PITCH) * MAGNET_PITCH;
    const float gain = 0.3f;  // complementary filter towards the fix
    pose_.x += gain * ((gx - ox) - pose_.x);
    pose_.y += gain * ((gy - oy) - pose_.y);
  }
}

// -- Follower ---------------------------------------------------------------

void Follower::start(const Waypoint* wp, int n, float final_heading, uint32_t start_ms_from_now,
                     int32_t plan_id) {
  n_ = n > MAX_WAYPOINTS ? MAX_WAYPOINTS : n;
  for (int i = 0; i < n_; i++) wp_[i] = wp[i];
  heading_ = final_heading;
  start_ms_ = millis() + start_ms_from_now;
  plan_ = plan_id;
  error_ = nullptr;
  state_ = n_ > 0 ? State::Moving : State::Idle;
}

void Follower::stop() {
  n_ = 0;
  state_ = State::Idle;
}

float Follower::progress() const {
  if (state_ != State::Moving) return 0.0f;
  int32_t dt = (int32_t)(millis() - start_ms_);
  return dt > 0 ? dt / 1000.0f : 0.0f;
}

void Follower::reference(float t, float& x, float& y, float& vx, float& vy) const {
  vx = vy = 0;
  if (t <= wp_[0].t) {
    x = wp_[0].x;
    y = wp_[0].y;
    return;
  }
  for (int i = 1; i < n_; i++) {
    const Waypoint &a = wp_[i - 1], &b = wp_[i];
    if (t <= b.t) {
      float span = b.t - a.t;
      float f = span > 0 ? (t - a.t) / span : 1.0f;
      x = a.x + f * (b.x - a.x);
      y = a.y + f * (b.y - a.y);
      if (span > 0) {
        vx = (b.x - a.x) / span;
        vy = (b.y - a.y) / span;
      }
      return;
    }
  }
  x = wp_[n_ - 1].x;
  y = wp_[n_ - 1].y;
}

bool Follower::update(const Pose& pose, float& vx, float& vy, float& wz) {
  vx = vy = wz = 0;
  if (state_ != State::Moving) return false;
  float t = progress();
  float rx, ry, rvx, rvy;
  reference(t, rx, ry, rvx, rvy);
  float ex = rx - pose.x, ey = ry - pose.y;
  if (sqrtf(ex * ex + ey * ey) > MAX_TRACKING_ERROR) {
    error_ = "tracking error";
    stop();
    return false;
  }
  // World-frame velocity: feed-forward from the reference plus feedback.
  float wvx = rvx + K_POS * ex, wvy = rvy + K_POS * ey;
  // Heading: hold the start heading while moving, turn at the end.
  bool last = t >= wp_[n_ - 1].t;
  float eh = last ? wrapAngle(heading_ - pose.h) : 0.0f;
  wz = K_HEADING * eh;
  // Rotate into the body frame (see Estimator::update for the axes).
  float c = cosf(pose.h), s = sinf(pose.h);
  vx = -s * wvx + c * wvy;  // forwards
  vy = -c * wvx - s * wvy;  // left
  if (last && fabsf(eh) < 0.02f && sqrtf(ex * ex + ey * ey) < 0.005f) {
    state_ = State::Idle;
    vx = vy = wz = 0;
  }
  return true;
}

// -- Drive ------------------------------------------------------------------

void driveOmni(float vx, float vy, float wz) {
  float v = sqrtf(vx * vx + vy * vy);
  if (v > MAX_SPEED) {
    vx *= MAX_SPEED / v;
    vy *= MAX_SPEED / v;
  }
  // TODO: acceleration limiting against MAX_ACCEL (the planner's timing
  // already assumes gentle starts; the firmware must enforce it).
  hal::WheelSpeeds w;
  for (int i = 0; i < WHEELS; i++) {
    float a = WHEEL_ANGLE[i];
    w.w[i] = (-sinf(a) * vx + cosf(a) * vy + WHEEL_RHO * wz) / WHEEL_RADIUS;
  }
  hal::setWheelSpeeds(w);
}
