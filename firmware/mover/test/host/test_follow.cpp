// Closed-loop host test: follower + mecanum kinematics + odometry.
// Build and run (from this directory):
//   g++ -std=gnu++17 -I. -I../../include test_follow.cpp ../../src/motion.cpp ../../src/hal.cpp -o t && ./t
#include <stdio.h>

#include "Arduino.h"
#include "motion.h"

uint32_t fake_us = 1000000;

static int check(const char* name, bool ok) {
  printf("%s %s\n", ok ? "PASS" : "FAIL", name);
  return ok ? 0 : 1;
}

static int run(const char* name, Pose start, const Waypoint* wp, int n, float heading) {
  Estimator est;
  est.reset(start);
  Follower f;
  f.start(wp, n, heading, 0, 1);
  float max_err = 0;
  const float dt = 0.005f;
  for (int i = 0; i < 2000 && f.state() == State::Moving; i++) {
    fake_us += 5000;
    est.update(dt);
    float vx, vy, wz;
    f.update(est.pose(), vx, vy, wz);
    driveMecanum(vx, vy, wz);
    if (f.state() != State::Moving) break;  // progress() is 0 once idle
    const Pose& p = est.pose();
    float t = f.progress(), rx = wp[n - 1].x, ry = wp[n - 1].y;
    for (int k = 1; k < n; k++)
      if (t <= wp[k].t) {
        float u = (t - wp[k - 1].t) / (wp[k].t - wp[k - 1].t);
        rx = wp[k - 1].x + u * (wp[k].x - wp[k - 1].x);
        ry = wp[k - 1].y + u * (wp[k].y - wp[k - 1].y);
        break;
      }
    float e = hypotf(p.x - rx, p.y - ry);
    if (e > max_err) max_err = e;
  }
  const Pose& p = est.pose();
  float dh = fabsf(remainderf(p.h - heading, 2 * PI));
  printf("  %s: end (%.4f, %.4f, %.3f) max tracking error %.1fmm\n", name, p.x, p.y, p.h,
         max_err * 1000);
  int bad = 0;
  bad += check(name, f.state() == State::Idle && !f.error());
  bad += check("  reaches goal", hypotf(p.x - wp[n - 1].x, p.y - wp[n - 1].y) < 0.006f);
  bad += check("  final heading", dh < 0.03f);
  bad += check("  tracks closely", max_err < 0.02f);
  return bad;
}

int main() {
  int bad = 0;
  Waypoint straight[] = {{0.333f, 0.333f, 0.0f}, {0.333f, 1.0f, 2.2f}};
  bad += run("straight up a file", {0.333f, 0.333f, 0.0f}, straight, 2, 0.0f);
  Waypoint lshape[] = {{0.667f, 0.333f, 0.0f}, {0.667f, 0.5f, 0.6f}, {0.5f, 0.667f, 1.4f},
                       {0.5f, 1.0f, 2.5f}};
  bad += run("knight-like dogleg, black piece", {0.667f, 0.333f, PI}, lshape, 4, PI);
  Waypoint wait[] = {{1.0f, 1.0f, 0.0f}, {1.0f, 1.0f, 0.8f}, {1.3333f, 1.0f, 2.0f}};
  bad += run("wait then sideways", {1.0f, 1.0f, 0.0f}, wait, 3, 0.0f);
  printf("%s\n", bad ? "FAILED" : "all passed");
  return bad;
}
