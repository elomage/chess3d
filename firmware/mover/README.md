# Mover foot firmware (option 1)

ESP32-S3 firmware for a self-propelled foot. It speaks the UDP protocol in
`chess3d/transport/protocol.py`: it follows timed paths with its own pose
estimate and reports status at 10 Hz while moving, 2 Hz otherwise, and at
once on every state change.

- `src/main.cpp` - Wi-Fi, UDP, message handling, control loop
- `src/motion.cpp` - pose estimator (mecanum odometry, IMU yaw, magnet grid
  fixes) and the timed path follower
- `src/hal.cpp` - hardware layer; placeholder implementations until the PCB
  exists (commanded wheel speeds are echoed as measured)
- `include/config.h` - Wi-Fi, orchestrator address, geometry, gains; put
  credentials in `include/config_local.h` (git-ignored)

Build with PlatformIO: `pio run`, flash with `pio run -t upload`.

Host test of the follower and kinematics, no ESP32 needed:

    cd test/host
    g++ -std=gnu++17 -I. -I../../include test_follow.cpp ../../src/motion.cpp ../../src/hal.cpp -o t && ./t

Still to do on real hardware: Hall array decoding, IMU driver, NFC reader,
motor driver and encoders, acceleration limiting, docking.
