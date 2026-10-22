// Minimal Arduino stand-in for host tests: a controllable clock.
#pragma once
#include <math.h>
#include <stdint.h>
#include <string.h>
#define PI 3.14159265358979f
extern uint32_t fake_us;
inline uint32_t micros() { return fake_us; }
inline uint32_t millis() { return fake_us / 1000; }
