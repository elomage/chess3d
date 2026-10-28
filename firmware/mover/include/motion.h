// Pose estimation and timed path following for a three-wheel omni foot.
#pragma once

#include <stdint.h>

constexpr int MAX_WAYPOINTS = 64;  // matches chess3d.transport.protocol

struct Pose {
  float x = 0, y = 0, h = 0;  // board frame, m and rad (0 = facing rank 8)
};

struct Waypoint {
  float x, y, t;  // t: seconds from the path start
};

enum class State : uint8_t { Idle, Moving, Docked, Fault };
const char* stateName(State s);

class Estimator {
 public:
  void reset(const Pose& p) { pose_ = p; }
  // Dead reckoning from wheel speeds (rad/s) and IMU yaw, corrected by
  // absolute magnet-grid fixes whenever one is available.
  void update(float dt);
  const Pose& pose() const { return pose_; }

 private:
  Pose pose_;
  float yaw_offset_ = 0;  // IMU yaw minus board heading
  bool yaw_aligned_ = false;
};

class Follower {
 public:
  void start(const Waypoint* wp, int n, float final_heading, uint32_t start_ms_from_now,
             int32_t plan_id);
  void stop();
  // Computes the body-frame velocity command; returns false when idle.
  bool update(const Pose& pose, float& vx, float& vy, float& wz);
  State state() const { return state_; }
  int32_t plan() const { return plan_; }
  float progress() const;  // seconds into the current path, 0 when idle
  const char* error() const { return error_; }
  void clearError() { error_ = nullptr; }

 private:
  void reference(float t, float& x, float& y, float& vx, float& vy) const;

  Waypoint wp_[MAX_WAYPOINTS];
  int n_ = 0;
  float heading_ = 0;
  uint32_t start_ms_ = 0;
  int32_t plan_ = -1;
  State state_ = State::Idle;
  const char* error_ = nullptr;
};

// Body-frame velocity to omni wheel speeds, with speed limiting.
void driveOmni(float vx, float vy, float wz);
