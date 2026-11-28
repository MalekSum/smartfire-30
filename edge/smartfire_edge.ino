// smartfire_edge_stepD.ino : SmartFire-30 Edge node (Wokwi, ESP32)
// STEP D BRANCH: local alarm + four scenarios + ESP-MQTT QoS 1 alerts
//
// Included:
//   - 1 Hz acquisition (esp_timer + binary semaphore), median(5), majority(3), dt, validity
//   - contract JSON (13 fields), printed on serial and published on edge/capteurs
//   - 3 FreeRTOS tasks (acq 3, infer 2, com 1), 4 queues, mutex, flame interrupt
//   - Wi-Fi Wokwi-GUEST, MQTT to the dev broker, edge/statut with QoS 1 Last Will and QoS 1 retained online status
//   - edge/commande/mode (S1..S4) so the mutex protects a parameter written by MQTT
//   - Step D: 2-consecutive-fire alarm, 10-clear-window reset, buzzer + LEDs
//   - S1/S2 remote decisions via fog/resultats; S3/S4 local decisions
//   - edge/alerte published with MQTT QoS 1; S4 Fog confirmation logged
//   - diagnostics: [COM] heartbeat every 5 s (state, heap, queues, stack)
//
// Arduino libraries required:
//   DHT sensor library for ESPx (DHTesp)
//   ArduinoJson@7.4.3
// ESP-MQTT is an ESP-IDF component, NOT an Arduino Library Manager package.
// The active Wokwi build environment must expose the ESP-IDF "mqtt" component
// and its mqtt_client.h header. If it does not, use an ESP-IDF/Arduino-component
// project with REQUIRES mqtt; libraries.txt cannot install this component.

#include <Arduino.h>
#include <stdio.h>       // snprintf for broker URI configuration
#include "smartfire_config.h"
#include <WiFi.h>
#include <string.h>      // memcmp, memcpy, strlen
#include <math.h>        // isnan, round
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "mqtt_client.h"  // ESP-IDF ESP-MQTT component (supports QoS 1 publish)
#include <esp_event.h>
#include <ArduinoJson.h>   // version 7 (JsonDocument)
#include <DHTesp.h>
#include <time.h>
#include <esp_timer.h>

// Real model from Bahi when available, otherwise the provisional stub.
#if __has_include("model.h")
#include "model.h"
#else
#include "model_stub.h"
#endif

// ============================================================
// 1. Configuration
// ============================================================

#define DHT_PIN    15
#define MQ2_PIN    34      // ADC1 (ADC2 is unusable while Wi-Fi is on)
#define FLAME_PIN  27      // LDR module DO used as flame sensor (simulation)
#define PIN_LED_G  33
#define PIN_LED_O  32
#define PIN_LED_R  26
#define PIN_BUZZER 25      // connect the Wokwi buzzer positive pin to GPIO25

#define FLAME_ACTIVE_LOW 1 // LOW = light detected = flame (DO is high when dark)

#define MEDIAN_SIZE 5      // sliding median window (t, h, gaz)
#define FLAME_SIZE  3      // majority vote window (flame)
#define DT_SIZE     6      // 6 samples -> t(n) and t(n-5)

#define MODEL_VERSION 1    // provisional model version; replaced with Bahi model at J3
#define N_CONFIRM 2          // contract: 2 consecutive class-2 decisions
#define CLEAR_WINDOWS 10     // contract: clear alarm after 10 consecutive non-fire decisions
#define PRINT_JSON    1    // 1 = print each sample JSON on serial (set 0 for timing tests)

const char*    DEVICE_ID = "edge30-wokwi";

// ============================================================
// 2. Shared parameters (protected by the mutex mtx)
// ============================================================

int gMode     = 4;      // 1..4 = S1..S4, written by MQTT (default S4)
int gSeuil    = 2000;   // classic detector threshold (SEUIL_CLASSIQUE)
int gNConfirm = N_CONFIRM; // configurable through edge/commande/modele

// ============================================================
// 3. Data structure and global objects
// ============================================================

struct Sample {
  uint32_t seq;
  time_t   ts;
  float    t, h;
  int      gaz, flame;
  float    dt;
  int      valid, y_edge, a_seuil, mode;
};

// Fog decision copied from the MQTT callback into taskInfer (never infer inside callback).
struct RemoteDecision {
  uint32_t seq;
  time_t ts;
  int mode;
  int y_fog;
  bool confirme;
};

// Alarm event passed to taskCom for reliable QoS 1 publication.
struct AlertMessage {
  uint32_t seq;
  time_t ts;
};

DHTesp dht;
// ESP-MQTT owns its internal network task; taskCom only enqueues outgoing records.
esp_mqtt_client_handle_t mqttClient = nullptr;
volatile bool mqttConnected = false;
volatile bool mqttOnlineStatusAcked = false;
volatile bool mqttModeSubscribed = false;
volatile bool mqttFogSubscribed = false;
volatile bool mqttModelSubscribed = false;
volatile int mqttOnlineMessageId = -1;
volatile int mqttModeSubscribeMessageId = -1;
volatile int mqttFogSubscribeMessageId = -1;
volatile int mqttModelSubscribeMessageId = -1;
volatile int mqttLastAlertMessageId = -1;

SemaphoreHandle_t mtx    = nullptr;   // protects gMode, gSeuil, gNConfirm
SemaphoreHandle_t semAcq = nullptr;   // timer -> taskAcq
QueueHandle_t qSample    = nullptr;   // taskAcq  -> taskInfer
QueueHandle_t qOut       = nullptr;   // taskInfer -> taskCom (sensor samples)
QueueHandle_t qRemote     = nullptr;   // MQTT callback -> taskInfer (Fog decisions)
QueueHandle_t qAlert      = nullptr;   // taskInfer -> taskCom (QoS 1 alerts)
esp_timer_handle_t acqTimer = nullptr;

TaskHandle_t hAcq = nullptr, hInfer = nullptr, hCom = nullptr;   // for stack diagnostics

volatile uint32_t flameEdges = 0;     // edges counted by the interrupt
portMUX_TYPE flameMux = portMUX_INITIALIZER_UNLOCKED;

// Shared by taskCom and MQTT event handler
uint32_t lastMqttInitAttempt = 0;
volatile uint32_t lastControlRetry = 0;  // shared by taskCom and MQTT event handler
bool alertNtpWarningPrinted = false;  // taskCom-only: suppress repeated NTP wait logs
uint32_t lastWifiLog         = 0;
bool     wifiLogged          = false;
bool     ntpWarned           = false;

// ============================================================
// 4. Validation, filters, JSON
// ============================================================

// Reading is valid if no NaN and values inside the contract ranges (bounds included).
bool validateReadings(float t, float h, int gas) {
  if (isnan(t) || isnan(h)) return false;
  if (t < -10.0f || t > 120.0f) return false;
  if (h < 0.0f || h > 100.0f) return false;
  if (gas < 0 || gas > 4095) return false;   // safety net (12-bit ADC)
  return true;
}

// Median of 5 values (sort a copy, take the middle one).
float calculateMedian(const float v[MEDIAN_SIZE]) {
  float s[MEDIAN_SIZE];
  for (int i = 0; i < MEDIAN_SIZE; i++) s[i] = v[i];
  for (int i = 0; i < MEDIAN_SIZE - 1; i++)
    for (int j = 0; j < MEDIAN_SIZE - 1 - i; j++)
      if (s[j] > s[j + 1]) { float tmp = s[j]; s[j] = s[j + 1]; s[j + 1] = tmp; }
  return s[MEDIAN_SIZE / 2];
}

// Majority vote over 3 binary values (no tie possible).
int calculateMajority(const int v[FLAME_SIZE]) {
  int ones = 0;
  for (int i = 0; i < FLAME_SIZE; i++) if (v[i] != 0) ones++;
  return (ones > FLAME_SIZE / 2) ? 1 : 0;
}

// Contract measurement JSON (section 4): exactly 13 fields.
void fillSampleJson(JsonDocument& d, const Sample& s, int mv) {
  d["id"]      = DEVICE_ID;
  d["seq"]     = s.seq;
  d["ts"]      = (long)s.ts;
  d["mode"]    = String("S") + String(s.mode);
  d["t"]       = round(s.t * 10.0) / 10.0;      // DHT22 resolution: 0.1
  d["h"]       = round(s.h * 10.0) / 10.0;
  d["gaz"]     = s.gaz;
  d["flame"]   = s.flame;
  d["dt"]      = round(s.dt * 100.0) / 100.0;   // 0.1 / 5 = 0.02 step
  d["valid"]   = s.valid;
  d["y_edge"]  = s.y_edge;
  d["a_seuil"] = s.a_seuil;
  d["mv"]      = mv;
}

// ============================================================
// 5. Interrupt, timer, LEDs
// ============================================================

void IRAM_ATTR isrFlame() {
  portENTER_CRITICAL_ISR(&flameMux);
  flameEdges++;
  portEXIT_CRITICAL_ISR(&flameMux);
}

// esp_timer callback (runs in the esp_timer task): wakes taskAcq every second.
void onAcqTimer(void*) {
  if (semAcq != nullptr) xSemaphoreGive(semAcq);
}

// Buzzer control for Arduino-ESP32 Core 2.x and 3.x
void setBuzzer(bool on) {

#if ESP_ARDUINO_VERSION_MAJOR >= 3

    if (on) {
        ledcWriteTone(PIN_BUZZER, 2000);
    } else {
        ledcWrite(PIN_BUZZER, 0);
    }

#else

    if (on) ledcWriteTone(0, 2000);
    else    ledcWrite(0, 0);

#endif
}

// Alarm overrides the class LEDs: red LED + buzzer. Otherwise class 0=green, 1=orange;
// class 2 becomes a full alarm only after N_CONFIRM consecutive decisions.
void setOutputs(bool alarm, int y) {
  digitalWrite(PIN_LED_G, (!alarm && y == 0) ? HIGH : LOW);
  digitalWrite(PIN_LED_O, (!alarm && y == 1) ? HIGH : LOW);
  digitalWrite(PIN_LED_R, alarm ? HIGH : LOW);
  setBuzzer(alarm);
}

// ============================================================
// 6. Task 1: acquisition and preprocessing (priority 3)
// ============================================================

void taskAcq(void*) {
  float tb[MEDIAN_SIZE] = {0}, hb[MEDIAN_SIZE] = {0}, gb[MEDIAN_SIZE] = {0};
  int   fb[FLAME_SIZE] = {0};
  float hist[DT_SIZE] = {0};
  int   bi = 0, fi = 0, hi = 0, hc = 0, invalidStreak = 0;
  bool  initialized = false;
  uint32_t seq = 0;

  // Held values; before the first valid reading they are only placeholders
  // and the sample is flagged valid=0.
  float lastT = 25.0f, lastH = 50.0f, lastG = 300.0f, lastDt = 0.0f;
  int   lastFlame = 0;

  for (;;) {
    if (xSemaphoreTake(semAcq, portMAX_DELAY) != pdTRUE) continue;

    TempAndHumidity r = dht.getTempAndHumidity();
    const float t = r.temperature, h = r.humidity;
    const int   gas   = analogRead(MQ2_PIN);
    const int   flame = (digitalRead(FLAME_PIN) == (FLAME_ACTIVE_LOW ? LOW : HIGH)) ? 1 : 0;
    const bool  valid = validateReadings(t, h, gas);
    if (!valid)
      Serial.printf("[ACQ] invalid raw: T=%.1f H=%.1f gas=%d (%s)\n",
                    t, h, gas, dht.getStatusString());
    bool firstValid = false;

    if (valid) {
      invalidStreak = 0;
      if (!initialized) {
        // First valid reading: fill every window with it (no fake history).
        for (int k = 0; k < MEDIAN_SIZE; k++) { tb[k] = t; hb[k] = h; gb[k] = (float)gas; }
        for (int k = 0; k < FLAME_SIZE;  k++) fb[k] = flame;
        bi = 0; fi = 0;
        initialized = true;
        firstValid  = true;
      } else {
        tb[bi] = t; hb[bi] = h; gb[bi] = (float)gas;
        bi = (bi + 1) % MEDIAN_SIZE;
        fb[fi] = flame;
        fi = (fi + 1) % FLAME_SIZE;
      }
      lastT = calculateMedian(tb);
      lastH = calculateMedian(hb);
      lastG = calculateMedian(gb);
      lastFlame = calculateMajority(fb);
    } else if (++invalidStreak >= MEDIAN_SIZE) {
      // Outage as long as the window: stored values are stale.
      // The next valid reading refills the windows and restarts the dt history.
      initialized = false;
    }

    // dt history on the 1 Hz timeline: dt = (t(n) - t(n-5)) / 5, 0 before 6 samples.
    // For a short invalid sample the last valid filtered temperature is held.
    if (initialized) {
      hist[hi] = lastT;
      hi = (hi + 1) % DT_SIZE;
      if (firstValid) hc = 1; else if (hc < DT_SIZE) hc++;
      if (hc == DT_SIZE) {
        const int newest = (hi + DT_SIZE - 1) % DT_SIZE;
        const int oldest = hi;
        lastDt = (hist[newest] - hist[oldest]) / 5.0f;
      } else {
        lastDt = 0.0f;
      }
    } else {
      lastDt = 0.0f;
    }

    Sample s{};
    s.seq = seq++;
    const time_t now = time(nullptr);
    s.ts = (now >= 1700000000) ? now : 0;     // Unix epoch (NTP), 0 until synchronised
    s.t = lastT; s.h = lastH; s.gaz = (int)lastG; s.flame = lastFlame; s.dt = lastDt;
    s.valid = (valid && initialized) ? 1 : 0;
    s.y_edge = -1; s.a_seuil = 0; s.mode = 0; // filled by taskInfer

    if (xQueueSend(qSample, &s, 0) != pdTRUE) Serial.println("[ACQ] qSample full: sample dropped");

    portENTER_CRITICAL(&flameMux);
    const uint32_t edges = flameEdges;
    portEXIT_CRITICAL(&flameMux);

    // raw(...) = sensor readings, filt(...) = after median / majority (evidence for E3)
    Serial.printf("[ACQ] seq=%lu valid=%d raw(T=%.1f H=%.1f gas=%d fl=%d) "
                  "filt(T=%.1f H=%.1f gas=%d fl=%d) dt=%.2f ts=%ld edges=%lu\n",
                  (unsigned long)s.seq, s.valid, t, h, gas, flame,
                  s.t, s.h, s.gaz, s.flame, s.dt, (long)s.ts, (unsigned long)edges);
  }
}

// ============================================================
// 7. Task 2: inference + alarm state machine (priority 2)
// ============================================================

void taskInfer(void*) {
  Eloquent::ML::Port::RandomForest clf;   // model.h or model_stub.h (same interface)
  Sample s;
  int mode = 4, threshold = 2000, nConfirm = N_CONFIRM;
  int previousMode = 4;
  int fireStreak = 0, clearStreak = 0;
  bool alarmActive = false;
  bool haveRemoteSeq = false;
  uint32_t lastRemoteSeq = 0;
  uint32_t lastRemoteMs = 0;  // last accepted Fog result in S1/S2
  bool fogTimedOut = false;  // log/apply the unknown decision once per timeout episode
  bool haveSampleSeq = false;
  uint32_t lastSampleSeq = 0;

  // This function is called only from taskInfer, so the alarm counters have one owner.
  auto applyDecision = [&](int y, uint32_t seq, time_t ts, const char* source) {
    const bool wasAlarmActive = alarmActive;

    if (y == 2) {
      fireStreak++;
      clearStreak = 0;
      if (!alarmActive && fireStreak >= nConfirm) {
        alarmActive = true;
        AlertMessage alert{seq, ts};
        if (xQueueSend(qAlert, &alert, 0) != pdTRUE) {
          Serial.printf("[ALARM] qAlert full: alert seq=%lu could not be queued\n",
                        (unsigned long)seq);
        } else {
          Serial.printf("[ALARM] ACTIVATED source=%s seq=%lu (class 2 x %d)\n",
                        source, (unsigned long)seq, nConfirm);
        }
      }
    } else if (y == 0 || y == 1) {
      fireStreak = 0;
      if (clearStreak < CLEAR_WINDOWS) clearStreak++;
      if (alarmActive && clearStreak >= CLEAR_WINDOWS) {
        alarmActive = false;
        Serial.printf("[ALARM] DEACTIVATED source=%s seq=%lu (%d clear windows)\n",
                      source, (unsigned long)seq, CLEAR_WINDOWS);
      }
    } else if (y == -1) {
      // An unknown/invalid window breaks consecutiveness but does not clear an active alarm.
      fireStreak = 0;
      clearStreak = 0;
    }
    // y=-1 means no decision: it must not count as fire or as a clear window.
    if (y >= 0 && y <= 2) setOutputs(alarmActive, y);
    if (wasAlarmActive != alarmActive) {
      Serial.printf("[ALARM] state=%s fireStreak=%d clearStreak=%d\n",
                    alarmActive ? "ON" : "OFF", fireStreak, clearStreak);
    }
  };

  for (;;) {
    if (xQueueReceive(qSample, &s, portMAX_DELAY) != pdTRUE) continue;

    // Read current mode/threshold once for this sample.
    if (xSemaphoreTake(mtx, pdMS_TO_TICKS(50)) == pdTRUE) {
      mode = gMode;
      threshold = gSeuil;
      nConfirm = gNConfirm;
      xSemaphoreGive(mtx);
    }
    if (haveSampleSeq && s.seq != lastSampleSeq + 1) {
      fireStreak = 0;
      clearStreak = 0;
      Serial.println("[ALARM] missing Edge sample sequence; decision streaks reset");
    }
    haveSampleSeq = true;
    lastSampleSeq = s.seq;

    if (mode != previousMode) {
      // Two fire decisions must be consecutive within one scenario. Keep an active alarm latched.
      fireStreak = 0;
      clearStreak = 0;
      previousMode = mode;
      // Start a fresh 3 s response window when entering a remote-decision scenario.
      lastRemoteMs = (mode == 1 || mode == 2) ? millis() : 0;
      fogTimedOut = false;
      Serial.printf("[ALARM] scenario changed -> S%d; decision streaks reset\n", mode);
    }

    // Apply any Fog results already received. QoS 1 can redeliver.
    // S4: Fog results are confirmations only (contract section 2). The local Edge
    // alarm is never changed by them, and they do not touch the S1/S2 sequence state.
    RemoteDecision remote;
    while (xQueueReceive(qRemote, &remote, 0) == pdTRUE) {
      if (remote.mode != mode) {
        Serial.printf("[FOG] stale mode result ignored: result=S%d current=S%d seq=%lu\n",
                      remote.mode, mode, (unsigned long)remote.seq);
        continue;
      }

      if (remote.mode == 4) {
        Serial.printf("[FOG] S4 confirmation: seq=%lu confirme=%d y_fog=%d (Edge alarm remains local)\n",
                      (unsigned long)remote.seq, (int)remote.confirme, remote.y_fog);
        continue;  // C1: do not touch counters or S1/S2 sequence state in S4
      }

      if (remote.mode != 1 && remote.mode != 2) {
        Serial.printf("[FOG] unexpected result mode=S%d ignored\n", remote.mode);
        continue;
      }

      // S1/S2 only: reject duplicates, out-of-order, future and excessively late results.
      if (haveRemoteSeq && (int32_t)(remote.seq - lastRemoteSeq) <= 0) {
        Serial.printf("[FOG] duplicate/out-of-order result ignored seq=%lu\n",
                      (unsigned long)remote.seq);
        continue;
      }
      if ((int32_t)(remote.seq - s.seq) > 0) {
        Serial.printf("[FOG] future result ignored: seq=%lu current=%lu\n",
                      (unsigned long)remote.seq, (unsigned long)s.seq);
        continue;
      }
      if ((int32_t)(s.seq - remote.seq) > 3) {
        Serial.printf("[FOG] late result ignored (>3 s): seq=%lu current=%lu\n",
                      (unsigned long)remote.seq, (unsigned long)s.seq);
        continue;
      }

      // In S1/S2, Fog should answer each measurement; a sequence gap breaks consecutiveness.
      if (haveRemoteSeq && remote.seq != lastRemoteSeq + 1) {
        fireStreak = 0;
        clearStreak = 0;
        Serial.println("[FOG] missing sequence detected; decision streaks reset");
      }
      haveRemoteSeq = true;
      lastRemoteSeq = remote.seq;
      lastRemoteMs = millis();
      fogTimedOut = false;

      applyDecision(remote.y_fog, remote.seq, remote.ts, "fog");
      Serial.printf("[FOG] remote decision applied: mode=S%d seq=%lu y_fog=%d\n",
                    remote.mode, (unsigned long)remote.seq, remote.y_fog);
    }

    // C2: in S1/S2, a missing Fog response for >3 s is an unknown decision (-1).
    // It breaks consecutive-decision streaks but does not turn an active alarm off.
    const bool timedOutNow = (mode == 1 || mode == 2) &&
        (uint32_t)(millis() - lastRemoteMs) > 3000U;
    if (timedOutNow && !fogTimedOut) {
      fogTimedOut = true;
      Serial.printf("[FOG] no result for >3 s: unknown decision -1 (seq=%lu)\n",
                    (unsigned long)s.seq);
      applyDecision(-1, s.seq, s.ts, "fog-timeout");
    } else if (!timedOutNow) {
      fogTimedOut = false;
    }

    s.mode    = mode;
    s.a_seuil = (s.gaz >= threshold) ? 1 : 0;      // classic threshold detector

    if (s.valid && (mode == 3 || mode == 4)) {     // Edge inference only in S3, S4
      float x[5] = { s.t, s.h, (float)s.gaz, (float)s.flame, s.dt };
      s.y_edge = clf.predict(x);
    } else {
      s.y_edge = -1;                               // not calculated in S1/S2 or invalid
    }

    if (mode == 3 || mode == 4) {
      applyDecision(s.y_edge, s.seq, s.ts, "edge");
    }
    // In S1/S2 leave the display unchanged until a valid remote decision arrives.

#if PRINT_JSON
    {
      JsonDocument dbg;
      fillSampleJson(dbg, s, MODEL_VERSION);
      char line[320];
      const size_t n = serializeJson(dbg, line, sizeof(line));
      if (n > 0 && n < sizeof(line)) Serial.printf("[JSON] %s\n", line);
    }
#endif

    // Never block: if qOut is full (network down for a long time), drop the oldest.
    if (xQueueSend(qOut, &s, 0) != pdTRUE) {
      Sample old;
      xQueueReceive(qOut, &old, 0);
      if (xQueueSend(qOut, &s, 0) != pdTRUE) {
        Serial.printf("[INFER] qOut retry failed: seq=%lu dropped\n", (unsigned long)s.seq);
      }
    }
  }
}

// ============================================================
// 8. MQTT / ESP-MQTT (ESP-IDF component)
// ============================================================

static char MQTT_URI_BUFFER[96];  // persistent storage for ESP-MQTT URI
static const char* TOPIC_STATUS = "m2i2a/equipe30/edge/statut";
static const char* TOPIC_MODE   = "m2i2a/equipe30/edge/commande/mode";
static const char* TOPIC_MODEL  = "m2i2a/equipe30/edge/commande/modele";
static const char* TOPIC_DATA   = "m2i2a/equipe30/edge/capteurs";
static const char* TOPIC_ALERT  = "m2i2a/equipe30/edge/alerte";
static const char* TOPIC_FOG_RESULTS = "m2i2a/equipe30/fog/resultats";

// The ESP-MQTT event handler executes in the MQTT task, not in taskCom.
// Shared state is volatile for simple event flags; gMode remains protected by mtx.
static void mqttEventHandler(void* handlerArgs,
                             esp_event_base_t base,
                             int32_t eventId,
                             void* eventData) {
  (void)base;
  if (eventData == nullptr) return;

  esp_mqtt_event_handle_t event = (esp_mqtt_event_handle_t)eventData;
  esp_mqtt_client_handle_t client = (esp_mqtt_client_handle_t)handlerArgs;

  switch ((esp_mqtt_event_id_t)eventId) {
    case MQTT_EVENT_CONNECTED: {
      mqttConnected = true;
      lastControlRetry = millis();
      mqttOnlineStatusAcked = false;
      mqttModeSubscribed = false;
      mqttFogSubscribed = false;
      mqttModelSubscribed = false;
      mqttOnlineMessageId = -1;
      mqttModeSubscribeMessageId = -1;
      mqttFogSubscribeMessageId = -1;
      mqttModelSubscribeMessageId = -1;
      Serial.println("[MQTT] connected");

      const int modeSubId = esp_mqtt_client_subscribe(client, TOPIC_MODE, 1);
      mqttModeSubscribeMessageId = modeSubId;
      Serial.printf("[MQTT] subscribe edge/commande/mode QoS1 id=%d\n", modeSubId);

      const int fogSubId = esp_mqtt_client_subscribe(client, TOPIC_FOG_RESULTS, 1);
      mqttFogSubscribeMessageId = fogSubId;
      Serial.printf("[MQTT] subscribe fog/resultats QoS1 id=%d\n", fogSubId);

      const int modelSubId = esp_mqtt_client_subscribe(client, TOPIC_MODEL, 1);
      mqttModelSubscribeMessageId = modelSubId;
      Serial.printf("[MQTT] subscribe edge/commande/modele QoS1 id=%d\n", modelSubId);

      const int pubId = esp_mqtt_client_enqueue(
          client, TOPIC_STATUS, "online", 6, 1, 1, false);
      mqttOnlineMessageId = pubId;
      Serial.printf("[MQTT] status online queued QoS1 retain=1 id=%d\n", pubId);
      if (pubId < 0) Serial.println("[MQTT] ERROR: could not queue online status");
      break;
    }

    case MQTT_EVENT_DISCONNECTED:
      mqttConnected = false;
      mqttOnlineStatusAcked = false;
      mqttModeSubscribed = false;
      mqttFogSubscribed = false;
      mqttModelSubscribed = false;
      Serial.println("[MQTT] disconnected; ESP-MQTT will try to reconnect");
      break;

    case MQTT_EVENT_SUBSCRIBED:
      if (event->msg_id == mqttModeSubscribeMessageId) {
        mqttModeSubscribed = true;
        Serial.println("[MQTT] edge/commande/mode subscription acknowledged");
      }
      if (event->msg_id == mqttFogSubscribeMessageId) {
        mqttFogSubscribed = true;
        Serial.println("[MQTT] fog/resultats subscription acknowledged");
      }
      if (event->msg_id == mqttModelSubscribeMessageId) {
        mqttModelSubscribed = true;
        Serial.println("[MQTT] edge/commande/modele subscription acknowledged");
      }
      break;

    case MQTT_EVENT_PUBLISHED:
      if (event->msg_id == mqttOnlineMessageId) {
        mqttOnlineStatusAcked = true;
        Serial.println("[MQTT] broker acknowledged edge/statut online (QoS1 PUBACK)");
      } else if (event->msg_id == mqttLastAlertMessageId) {
        mqttLastAlertMessageId = -1;
        Serial.println("[MQTT] broker acknowledged edge/alerte (QoS1 PUBACK)");
      }
      break;

    case MQTT_EVENT_DATA: {
      // These contract messages are small enough to fit in one MQTT data event.
      if (event->current_data_offset != 0 ||
          event->data_len != event->total_data_len ||
          event->topic == nullptr || event->data == nullptr) {
        Serial.println("[MQTT] fragmented/empty DATA event ignored");
        break;
      }

      const size_t modeTopicLen = strlen(TOPIC_MODE);
      const bool isModeTopic = (event->topic_len == (int)modeTopicLen) &&
          (memcmp(event->topic, TOPIC_MODE, modeTopicLen) == 0);
      const size_t fogTopicLen = strlen(TOPIC_FOG_RESULTS);
      const bool isFogTopic = (event->topic_len == (int)fogTopicLen) &&
          (memcmp(event->topic, TOPIC_FOG_RESULTS, fogTopicLen) == 0);
      const size_t modelTopicLen = strlen(TOPIC_MODEL);
      const bool isModelTopic = (event->topic_len == (int)modelTopicLen) &&
          (memcmp(event->topic, TOPIC_MODEL, modelTopicLen) == 0);

      if (isModeTopic) {
        int len = event->data_len;
        while (len > 0 && (event->data[len-1] == '\n' || event->data[len-1] == '\r' ||
                           event->data[len-1] == ' ')) len--;
        if (len == 2 && event->data[0] == 'S' &&
            event->data[1] >= '1' && event->data[1] <= '4') {
          const int requestedMode = event->data[1] - '0';
          if (xSemaphoreTake(mtx, pdMS_TO_TICKS(50)) == pdTRUE) {
            gMode = requestedMode;
            xSemaphoreGive(mtx);
            Serial.printf("[MQTT] mode updated -> S%d\n", requestedMode);
          } else {
            Serial.printf("[MQTT] mode update FAILED (mutex timeout), requested S%d\n",
                          requestedMode);
          }
        } else {
          Serial.println("[MQTT] invalid mode command; expected exactly S1, S2, S3 or S4");
        }
        break;
      }

      if (isFogTopic) {
        JsonDocument doc;
        const DeserializationError err = deserializeJson(doc, event->data, event->data_len);
        if (err) {
          Serial.printf("[FOG] invalid result JSON: %s\n", err.c_str());
          break;
        }
        const char* modeText = doc["mode"] | "";
        const int yFog = doc["y_fog"] | -1;
        const long ts = doc["ts"] | 0L;
        if (!doc["seq"].is<uint32_t>() || modeText[0] != 'S' ||
            modeText[1] < '1' || modeText[1] > '4' || modeText[2] != '\0' ||
            yFog < 0 || yFog > 2 || ts < 1700000000L) {
          Serial.println("[FOG] result ignored: missing/invalid seq, mode, y_fog or ts");
          break;
        }
        RemoteDecision remote{};
        remote.seq = doc["seq"].as<uint32_t>();
        remote.ts = (time_t)ts;
        remote.mode = modeText[1] - '0';
        remote.y_fog = yFog;
        remote.confirme = doc["confirme"] | false;
        if (xQueueSend(qRemote, &remote, 0) != pdTRUE) {
          Serial.printf("[FOG] qRemote full: result seq=%lu dropped\n",
                        (unsigned long)remote.seq);
        } else {
          Serial.printf("[FOG] result queued: mode=%s seq=%lu y_fog=%d confirme=%d\n",
                        modeText, (unsigned long)remote.seq, remote.y_fog,
                        (int)remote.confirme);
        }
        break;
      }

      if (isModelTopic) {
        JsonDocument doc;
        const DeserializationError err = deserializeJson(doc, event->data, event->data_len);
        if (err) {
          Serial.printf("[MQTT] invalid edge/commande/modele JSON: %s\n", err.c_str());
          break;
        }
        const int requestedMv = doc["mv"] | -1;
        const int requestedConfirm = doc["n_confirm"] | -1;
        const int requestedThreshold = doc["seuil_classique"] | -1;
        if (requestedMv < 1 || requestedConfirm < 1 || requestedConfirm > 10 ||
            requestedThreshold < 0 || requestedThreshold > 4095) {
          Serial.println("[MQTT] model config ignored: expected mv>=1, n_confirm=1..10, seuil_classique=0..4095");
          break;
        }
        if (xSemaphoreTake(mtx, pdMS_TO_TICKS(50)) == pdTRUE) {
          gNConfirm = requestedConfirm;
          gSeuil = requestedThreshold;
          xSemaphoreGive(mtx);
          Serial.printf("[MQTT] model parameters updated: n_confirm=%d seuil_classique=%d\n",
                        requestedConfirm, requestedThreshold);
        } else {
          Serial.println("[MQTT] model config update FAILED (mutex timeout)");
        }
        if (requestedMv != MODEL_VERSION) {
          Serial.printf("[MQTT] NOTE: command mv=%d but firmware model is still mv=%d; metadata not changed\n",
                        requestedMv, MODEL_VERSION);
        }
        break;
      }
      break;
    }

    case MQTT_EVENT_ERROR:
      Serial.println("[MQTT] event error reported by ESP-MQTT");
      break;

    default:
      break;
  }
}

// Initialise and start ESP-MQTT once Wi-Fi is connected.
// ESP-MQTT handles reconnect attempts internally after start().
bool startMqttClient() {
  if (mqttClient != nullptr) return true;

  // Build the URI from the project configuration header (not a hardcoded URI).
  const int uriLen = snprintf(MQTT_URI_BUFFER, sizeof(MQTT_URI_BUFFER),
                              "mqtt://%s:%d", MQTT_HOST, MQTT_PORT);
  if (uriLen < 0 || (size_t)uriLen >= sizeof(MQTT_URI_BUFFER)) {
    Serial.println("[MQTT] invalid broker host/port configuration");
    return false;
  }
  Serial.printf("[MQTT] broker: %s\n", MQTT_URI_BUFFER);

  esp_mqtt_client_config_t cfg = {};
  cfg.broker.address.uri = MQTT_URI_BUFFER;
  cfg.credentials.client_id = DEVICE_ID;
  if (MQTT_USER[0] != '\0') cfg.credentials.username = MQTT_USER;
  if (MQTT_PASS[0] != '\0') cfg.credentials.authentication.password = MQTT_PASS;

  // Last Will: broker publishes "offline" if this client disconnects unexpectedly.
  cfg.session.last_will.topic = TOPIC_STATUS;
  cfg.session.last_will.msg = "offline";
  cfg.session.last_will.msg_len = 7;
  cfg.session.last_will.qos = 1;
  cfg.session.last_will.retain = true;
  cfg.session.keepalive = 30;

  // ESP-MQTT owns its own task and internal outbox.
  cfg.buffer.size = 512;

  mqttClient = esp_mqtt_client_init(&cfg);
  if (mqttClient == nullptr) {
    Serial.println("[MQTT] esp_mqtt_client_init FAILED");
    return false;
  }

  esp_err_t err = esp_mqtt_client_register_event(
      mqttClient, MQTT_EVENT_ANY, mqttEventHandler, mqttClient);
  if (err != ESP_OK) {
    Serial.printf("[MQTT] register_event FAILED: %s\n", esp_err_to_name(err));
    esp_mqtt_client_destroy(mqttClient);
    mqttClient = nullptr;
    return false;
  }

  err = esp_mqtt_client_start(mqttClient);
  if (err != ESP_OK) {
    Serial.printf("[MQTT] start FAILED: %s\n", esp_err_to_name(err));
    esp_mqtt_client_destroy(mqttClient);
    mqttClient = nullptr;
    return false;
  }

  Serial.println("[MQTT] client started; waiting for MQTT_EVENT_CONNECTED");
  return true;
}

// Publish a transition-to-alarm message. QoS 1 is native ESP-MQTT and is
// retransmitted by its outbox until the broker acknowledges it with PUBACK.
bool publishAlert(const AlertMessage& alert) {
  JsonDocument doc;
  time_t alertTs = alert.ts;
  if (alertTs < 1700000000) alertTs = time(nullptr);
  if (alertTs < 1700000000) {
    if (!alertNtpWarningPrinted) {
      Serial.println("[MQTT] alert waiting for NTP; kept in qAlert");
      alertNtpWarningPrinted = true;
    }
    return false;  // keep the alert queued until NTP is ready
  }
  alertNtpWarningPrinted = false;
  doc["id"] = DEVICE_ID;
  doc["seq"] = alert.seq;
  doc["ts"] = (long)alertTs;
  doc["niveau"] = 2;
  doc["source"] = "edge";
  char payload[192];
  const size_t length = serializeJson(doc, payload, sizeof(payload));
  if (length == 0 || length >= sizeof(payload)) {
    Serial.println("[MQTT] alert JSON serialization failed");
    return false;
  }
  const int msgId = esp_mqtt_client_enqueue(
      mqttClient, TOPIC_ALERT, payload, (int)length, 1, 0, true);
  if (msgId < 0) {
    Serial.printf("[MQTT] edge/alerte enqueue FAILED seq=%lu\n", (unsigned long)alert.seq);
    return false;
  }
  mqttLastAlertMessageId = msgId;
  Serial.printf("[MQTT] edge/alerte QUEUED seq=%lu QoS1 retain=0 id=%d\n",
                (unsigned long)alert.seq, msgId);
  return true;
}

// Publication policy per scenario (contract section 2):
//   S1, S2: every second | S3: heartbeat every 10 s | S4: every second for a
//   valid non-zero class, otherwise heartbeat every 10 s.
bool publishSample(const Sample& s) {
  // true = accepted for this policy pass (or deliberately skipped); false = retry.
  const bool shouldPublish =
      (s.mode == 1 || s.mode == 2) ||
      (s.mode == 3 && (s.seq % 10 == 0)) ||
      (s.mode == 4 && (s.y_edge != 0 || (s.seq % 10 == 0)));
  if (!shouldPublish) return true;

  if (s.ts < 1700000000) {
    if (!ntpWarned) {
      Serial.println("[MQTT] NTP not ready: sample not published (contract requires epoch ts)");
      ntpWarned = true;
    }
    return true;
  }
  ntpWarned = false;

  JsonDocument doc;
  fillSampleJson(doc, s, MODEL_VERSION);
  char payload[320];
  const size_t length = serializeJson(doc, payload, sizeof(payload));
  if (length == 0 || length >= sizeof(payload)) {
    Serial.println("[MQTT] JSON serialization failed/too large; sample dropped");
    return true;
  }

  // Contract: periodic sensor measurements use QoS 0, not retained.
  // Use enqueue() so taskCom does not perform a potentially blocking socket write.
  const int msgId = esp_mqtt_client_enqueue(
      mqttClient, TOPIC_DATA, payload, (int)length, 0, 0, true);

  Serial.printf("[MQTT] edge/capteurs seq=%lu %s id=%d (%u bytes, QoS0)\n",
                (unsigned long)s.seq, (msgId >= 0) ? "QUEUED" : "FAILED",
                msgId, (unsigned)length);
  return msgId >= 0;
}

// ============================================================
// 9. Task 3: communication (priority 1)
// ============================================================

void taskCom(void*) {
  Serial.println("[WiFi] connecting to Wokwi-GUEST ...");
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin("Wokwi-GUEST", "", 6);

  configTime(0, 0, "pool.ntp.org");   // UTC epoch, required by the contract ts field

  uint32_t lastHb = 0;
  for (;;) {
    if ((uint32_t)(millis() - lastHb) >= 5000) {
      lastHb = millis();
      Serial.printf("[COM] wifi=%d mqtt=%d onlinePUBACK=%d modeSUBACK=%d fogSUBACK=%d modelSUBACK=%d "
                    "heap=%u qOut=%u qFog=%u qAlert=%u time=%ld stackFree acq=%u infer=%u com=%u\n",
                    (int)WiFi.status(), (int)mqttConnected,
                    (int)mqttOnlineStatusAcked, (int)mqttModeSubscribed, (int)mqttFogSubscribed,
                    (int)mqttModelSubscribed,
                    (unsigned)ESP.getFreeHeap(), (unsigned)uxQueueMessagesWaiting(qOut),
                    (unsigned)uxQueueMessagesWaiting(qRemote), (unsigned)uxQueueMessagesWaiting(qAlert),
                    (long)time(nullptr),
                    (unsigned)uxTaskGetStackHighWaterMark(hAcq),
                    (unsigned)uxTaskGetStackHighWaterMark(hInfer),
                    (unsigned)uxTaskGetStackHighWaterMark(NULL));
    }

    if (WiFi.status() == WL_CONNECTED) {
      if (!wifiLogged) {
        Serial.printf("[WiFi] connected, IP=%s\n", WiFi.localIP().toString().c_str());
        wifiLogged = true;
      }

      if (mqttClient == nullptr &&
          (lastMqttInitAttempt == 0 ||
           (uint32_t)(millis() - lastMqttInitAttempt) >= 3000)) {
        lastMqttInitAttempt = millis();
        startMqttClient();
      }

      // Recover setup operations only if they were rejected locally. QoS 1
      // publications already accepted by ESP-MQTT are retransmitted by its outbox.
      if (mqttConnected && (uint32_t)(millis() - lastControlRetry) >= 5000) {
        lastControlRetry = millis();
        if (!mqttModeSubscribed) {
          const int subId = esp_mqtt_client_subscribe(mqttClient, TOPIC_MODE, 1);
          mqttModeSubscribeMessageId = subId;
          if (subId >= 0) Serial.printf("[MQTT] retry mode subscribe queued id=%d\n", subId);
        }
        if (!mqttFogSubscribed) {
          const int subId = esp_mqtt_client_subscribe(mqttClient, TOPIC_FOG_RESULTS, 1);
          mqttFogSubscribeMessageId = subId;
          if (subId >= 0) Serial.printf("[MQTT] retry fog subscribe queued id=%d\n", subId);
        }
        if (!mqttModelSubscribed) {
          const int subId = esp_mqtt_client_subscribe(mqttClient, TOPIC_MODEL, 1);
          mqttModelSubscribeMessageId = subId;
          if (subId >= 0) Serial.printf("[MQTT] retry model subscribe queued id=%d\n", subId);
        }
        if (!mqttOnlineStatusAcked && mqttOnlineMessageId < 0) {
          const int pubId = esp_mqtt_client_enqueue(
              mqttClient, TOPIC_STATUS, "online", 6, 1, 1, false);
          mqttOnlineMessageId = pubId;
          if (pubId >= 0) Serial.printf("[MQTT] retry online status queued id=%d\n", pubId);
        }
      }

      // Send alerts before periodic measurements. The QoS 1 ESP-MQTT outbox
      // handles broker-level retransmission after an alert is accepted.
      AlertMessage alert;
      if (mqttConnected && xQueueReceive(qAlert, &alert, 0) == pdTRUE) {
        if (!publishAlert(alert)) {
          if (xQueueSendToFront(qAlert, &alert, 0) != pdTRUE) {
            Serial.printf("[MQTT] alert retry queue full: seq=%lu dropped\n",
                          (unsigned long)alert.seq);
          }
          vTaskDelay(pdMS_TO_TICKS(100));
        }
      }

      // Process a small batch per pass. MQTT transport/reconnect work is done
      // by ESP-MQTT's own task, not by this FreeRTOS communication task.
      for (int sent = 0; sent < 3 && mqttConnected; ++sent) {
        Sample sample;
        if (xQueueReceive(qOut, &sample, 0) != pdTRUE) break;

        if (!publishSample(sample)) {
          if (xQueueSendToFront(qOut, &sample, 0) != pdTRUE) {
            Serial.printf("[MQTT] retry queue full: seq=%lu dropped\n",
                          (unsigned long)sample.seq);
          }
          vTaskDelay(pdMS_TO_TICKS(100));
          break;
        }
      }
    } else {
      wifiLogged = false;
      if ((uint32_t)(millis() - lastWifiLog) >= 5000) {
        Serial.printf("[WiFi] not connected, status=%d\n", WiFi.status());
        lastWifiLog = millis();
      }
    }

    vTaskDelay(pdMS_TO_TICKS(10));
  }
}

// ============================================================
// 10. Setup and loop
// ============================================================

void setup() {
  Serial.begin(115200);
  #if defined(ESP_ARDUINO_VERSION_MAJOR)
  Serial.printf("Arduino-ESP32 core %d.%d.%d\n", ESP_ARDUINO_VERSION_MAJOR,
                ESP_ARDUINO_VERSION_MINOR, ESP_ARDUINO_VERSION_PATCH);
  #endif

  dht.setup(DHT_PIN, DHTesp::DHT22);
  pinMode(FLAME_PIN, INPUT);
  pinMode(MQ2_PIN, INPUT);
  pinMode(PIN_LED_G, OUTPUT);
  pinMode(PIN_LED_O, OUTPUT);
  pinMode(PIN_LED_R, OUTPUT);
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  if (!ledcAttach(PIN_BUZZER, 2000, 8)) {Serial.println("[WARN] buzzer LEDC attach failed");
  }
  ledcWrite(PIN_BUZZER, 0);// Start with buzzer OFF
#else
  ledcSetup(0, 2000, 8);
  ledcAttachPin(PIN_BUZZER, 0);
  ledcWrite(0, 0);// Start with buzzer OFF
#endif
  analogReadResolution(12);                  // 0..4095
  setOutputs(false, -1);

  mtx      = xSemaphoreCreateMutex();
  semAcq   = xSemaphoreCreateBinary();
  qSample  = xQueueCreate(8,   sizeof(Sample));
  qOut     = xQueueCreate(120, sizeof(Sample));
  qRemote  = xQueueCreate(16,  sizeof(RemoteDecision));
  qAlert   = xQueueCreate(8,   sizeof(AlertMessage));
  if (!mtx || !semAcq || !qSample || !qOut || !qRemote || !qAlert) {
    Serial.println("[FATAL] FreeRTOS object creation failed");
    while (true) delay(1000);
  }

  attachInterrupt(digitalPinToInterrupt(FLAME_PIN), isrFlame, CHANGE);

  esp_timer_create_args_t args = {};
  args.callback = &onAcqTimer;
  args.name     = "acq1s";
  if (esp_timer_create(&args, &acqTimer) != ESP_OK) {
    Serial.println("[FATAL] timer creation failed");
    while (true) delay(1000);
  }

  // Priorities: acquisition (strict 1 Hz deadline) > inference > communication (can block).
  const BaseType_t a = xTaskCreate(taskAcq,   "taskAcq",   4096, nullptr, 3, &hAcq);
  const BaseType_t i = xTaskCreate(taskInfer, "taskInfer", 6144, nullptr, 2, &hInfer);
  const BaseType_t c = xTaskCreate(taskCom,   "taskCom",   8192, nullptr, 1, &hCom);
  if (a != pdPASS || i != pdPASS || c != pdPASS) {
    Serial.println("[FATAL] task creation failed");
    while (true) delay(1000);
  }

  if (esp_timer_start_periodic(acqTimer, 1000000) != ESP_OK) {   // 1 s = 1,000,000 us
    Serial.println("[FATAL] timer start failed");
    while (true) delay(1000);
  }
  Serial.println("SmartFire Edge: taskAcq / taskInfer / taskCom started");
}

void loop() {
  vTaskDelay(portMAX_DELAY);                 // everything runs in the tasks
}