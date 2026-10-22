// Mover foot firmware: speaks chess3d/transport/protocol.py over Wi-Fi UDP.
//
// The orchestrator sends timed paths; the foot follows them with its own
// pose estimate (odometry + IMU + magnet grid) and reports status at
// 10 Hz while moving, 2 Hz otherwise, and at once on every state change.

#include <Arduino.h>
#include <ArduinoJson.h>
#include <WiFi.h>
#include <WiFiUdp.h>

#include "config.h"
#include "hal.h"
#include "motion.h"

static WiFiUDP udp;
static IPAddress server;
static char foot_id[13];
static Estimator estimator;
static Follower follower;
static bool docked = false;
static State last_state = State::Idle;
static uint32_t last_status_ms = 0;

static State currentState() {
  if (docked) return State::Docked;
  if (follower.error()) return State::Fault;
  return follower.state();
}

static void send(JsonDocument& doc) {
  char buf[512];
  size_t n = serializeJson(doc, buf, sizeof(buf));
  udp.beginPacket(server, ORCHESTRATOR_PORT);
  udp.write(reinterpret_cast<const uint8_t*>(buf), n);
  udp.endPacket();
}

static void sendHello() {
  JsonDocument doc;
  doc["t"] = "hello";
  doc["foot"] = foot_id;
  doc["fw"] = FIRMWARE_VERSION;
  doc["kind"] = "piece";
  send(doc);
}

static void sendStatus() {
  const Pose& p = estimator.pose();
  JsonDocument doc;
  doc["t"] = "status";
  doc["foot"] = foot_id;
  const char* tag = hal::bodyTag();
  if (tag[0]) doc["tag"] = tag; else doc["tag"] = nullptr;
  doc["x"] = p.x;
  doc["y"] = p.y;
  doc["h"] = p.h;
  doc["state"] = stateName(currentState());
  if (follower.plan() >= 0) doc["plan"] = follower.plan(); else doc["plan"] = nullptr;
  doc["prog"] = follower.progress();
  doc["bat"] = hal::battery();
  if (follower.error()) doc["err"] = follower.error(); else doc["err"] = nullptr;
  send(doc);
  last_status_ms = millis();
}

static void handle(JsonDocument& msg) {
  const char* t = msg["t"] | "";
  if (!strcmp(t, "path")) {
    static Waypoint wp[MAX_WAYPOINTS];
    JsonArray arr = msg["wp"].as<JsonArray>();
    int n = 0;
    for (JsonArray w : arr) {
      if (n >= MAX_WAYPOINTS) break;
      wp[n++] = {w[0].as<float>(), w[1].as<float>(), w[2].as<float>()};
    }
    docked = false;
    follower.start(wp, n, msg["h"] | estimator.pose().h, msg["start_ms"] | 0, msg["plan"] | -1);
  } else if (!strcmp(t, "stop")) {
    follower.stop();
    follower.clearError();
  } else if (!strcmp(t, "rotate")) {
    Waypoint here{estimator.pose().x, estimator.pose().y, 0.0f};
    follower.start(&here, 1, msg["h"] | 0.0f, 0, follower.plan());
  } else if (!strcmp(t, "pose")) {
    Pose p;
    p.x = msg["x"] | 0.0f;
    p.y = msg["y"] | 0.0f;
    p.h = msg["h"] | 0.0f;
    estimator.reset(p);
  } else if (!strcmp(t, "dock")) {
    // TODO: drive onto the charging pads; for now just report docked.
    follower.stop();
    docked = true;
  } else if (!strcmp(t, "ping")) {
    JsonDocument doc;
    doc["t"] = "pong";
    doc["foot"] = foot_id;
    doc["seq"] = msg["seq"];
    send(doc);
  }
}

void setup() {
  Serial.begin(115200);
  hal::begin();
  uint64_t mac = ESP.getEfuseMac();
  snprintf(foot_id, sizeof(foot_id), "%012llx", mac);

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);  // latency matters more than power here
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) delay(100);
  server.fromString(ORCHESTRATOR_IP);
  udp.begin(ORCHESTRATOR_PORT);
  Serial.printf("foot %s up at %s\n", foot_id, WiFi.localIP().toString().c_str());
  sendHello();
}

void loop() {
  static uint32_t last_us = micros();
  uint32_t now_us = micros();
  float dt = (now_us - last_us) / 1e6f;
  if (dt < 1.0f / CONTROL_HZ) {
    // Spend the idle time on the network.
    int size = udp.parsePacket();
    if (size > 0) {
      char buf[2048];
      int n = udp.read(buf, sizeof(buf) - 1);
      buf[n > 0 ? n : 0] = 0;
      JsonDocument msg;
      if (!deserializeJson(msg, buf)) handle(msg);
    }
    return;
  }
  last_us = now_us;

  estimator.update(dt);
  float vx, vy, wz;
  follower.update(estimator.pose(), vx, vy, wz);
  driveMecanum(vx, vy, wz);

  State s = currentState();
  float hz = s == State::Moving ? STATUS_HZ_MOVING : STATUS_HZ_IDLE;
  if (s != last_state || millis() - last_status_ms >= 1000.0f / hz) {
    last_state = s;
    sendStatus();
  }
  if (WiFi.status() != WL_CONNECTED) {
    driveMecanum(0, 0, 0);  // never drive blind
    follower.stop();
  }
}
