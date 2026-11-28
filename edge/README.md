# SmartFire30-Edge — Version D

An ESP32-based Edge component for the SmartFire30 AIoT fire and smoke detection system. Version D extends the earlier sensor-processing prototype with FreeRTOS task management, MQTT communication, operating modes, local alarm handling, and interaction with the Fog layer.

> **Status note:** This README describes the Version D firmware and its integration interfaces. The Edge inference model may still be a development `model_stub`; do not describe it as the final trained TinyML model until that model has been integrated and validated on the ESP32.

## 1. Project Overview

The Edge device acquires environmental measurements, filters and validates them, computes temperature variation, performs the local Edge decision where the selected mode requires it, and exchanges measurements, alerts, status, and commands with the Fog layer through MQTT.

The project is tested with an ESP32 in the Wokwi simulator. The photoresistor (LDR) is used as a simulation proxy for a flame sensor; it is not a real flame sensor.

## 2. Main Objectives

- Acquire temperature, humidity, gas, and flame-proxy measurements.
- Filter sensor noise and validate measurements before inference.
- Calculate temperature variation (`dt`).
- Organize acquisition, inference, and communication using FreeRTOS tasks.
- Support the SmartFire30 operating modes (`S1`–`S4`).
- Perform local inference and manage the local alarm when required by the selected mode.
- Communicate with Fog through MQTT, including status, measurements, alerts, commands, and Fog results.
- Synchronize timestamps using NTP before publishing measurements that require Unix epoch timestamps.
- Measure task execution and timing behavior during the performance evaluation.

## 3. Hardware and Simulation Components

| Component | Purpose |
|---|---|
| ESP32 | Main Edge processing and communication unit |
| DHT22 | Temperature and humidity measurement |
| MQ-2 | Gas measurement |
| Photoresistor (LDR) | Flame-sensor proxy in Wokwi simulation |
| Red LED | Visual alarm indicator |
| Buzzer | Audible alarm indicator |

> **Simulation limitation:** The LDR is only a proxy used in Wokwi. Its readings must not be presented as measurements from a physical flame sensor.

## 4. Edge Processing Pipeline

```text
DHT22 / MQ-2 / LDR
        |
        v
Sensor Acquisition
        |
        v
Filtering and Validation
  - Median filter: temperature, humidity, gas (window = 5)
  - Majority vote: flame proxy (3 readings)
        |
        v
Feature Calculation
  - dt: temperature variation over 5 seconds
        |
        v
Edge Inference / Classical Threshold
        |
        +--------------------------+
        |                          |
        v                          v
Local Alarm Logic             MQTT Communication
(when applicable)             Measurements / Alerts / Status
                                   Commands / Fog Results
```

### 4.1 Filtering

A median filter with a window of five samples is applied to temperature, humidity, and gas measurements. A majority-vote filter over three readings is applied to the digital flame-proxy signal.

### 4.2 Temperature Variation (`dt`)

The temperature variation is calculated over a five-second interval:

\[
dt = \frac{T(n)-T(n-5)}{5}
\]

It approximates the temperature change per second. `dt` remains zero until enough history is available.

### 4.3 Data Validation

The `valid` field indicates whether the sensor measurements pass the firmware's validation checks:

- `1`: measurements are considered valid.
- `0`: measurements are invalid and must not be used for model inference.

### 4.4 Decision Values

The `y_edge` field represents the Edge decision:

| Value | Meaning |
|---:|---|
| `-1` | No Edge decision / unknown at this point |
| `0` | Normal |
| `1` | Perturbation |
| `2` | Fire |

The classical threshold indicator `a_seuil` is set when the gas reading reaches the configured threshold. The current contract/configuration value is `2000` ADC units; it is a threshold indicator, not by itself proof that a fire has occurred.

## 5. FreeRTOS Task Organization

Version D separates the main Edge activities into FreeRTOS tasks:

- **Acquisition task (`taskAcq`):** reads sensors, filters and validates the measurements, calculates `dt`, and prepares samples.
- **Inference task (`taskInfer`):** processes samples and produces the Edge decision when local inference is required.
- **Communication task (`taskCom`):** handles Wi-Fi/MQTT communication, subscriptions, publications, and received commands/results.

Queues and task synchronization are used to pass data between the tasks. The timing build can be used to collect observed execution-time, start-interval, and stack high-water-mark measurements. Such observed maxima are measurements from a test run, not a formal worst-case execution-time (WCET) proof.

## 6. Operating Modes

The Edge firmware supports four operating modes. The selected mode is received from Fog through `edge/commande/mode`.

| Mode | Edge behavior | Fog behavior |
|---|---|---|
| `S1` — Cloud decision | Publishes each measurement; `y_edge = -1`; applies the remote decision received through Fog | Relays the inference request to Cloud and returns the decision |
| `S2` — Fog decision | Publishes each measurement; `y_edge = -1`; applies the decision received from Fog | Performs inference and publishes the decision |
| `S3` — Edge decision | Performs local inference and manages the local alarm; sends periodic status/heartbeat and alerts | Relays/stores data; does not replace the Edge decision |
| `S4` — Hybrid | Performs local inference and manages the local alarm; publishes less frequently during normal conditions and more frequently when the Edge detects a non-normal condition | Performs a second inference to confirm or infirm the Edge result |

In `S4`, Fog results are treated as confirmation information; they do not take ownership of the Edge's local alarm counters. In `S1` and `S2`, the Edge depends on the remote decision. If no Fog result arrives within the configured timeout (3 seconds), the remote decision is treated as unknown (`-1`); an unknown result must not be interpreted as a command to clear an already active local alarm.

> The operating mode is selected by a retained MQTT command. During a coordinated end-to-end test, the project lead should control mode changes so multiple team members do not overwrite one another's retained command.

## 7. Local Alarm Behavior

When local Edge alarm handling is active:

- A fire decision (`y_edge = 2`) must be observed for two consecutive inference windows before activating the alarm.
- The red LED and buzzer indicate an active alarm.
- The alarm is cleared after ten consecutive windows without a fire decision, according to the implemented local alarm logic.

The exact behavior should be checked against the current firmware revision when thresholds or counters are changed.

## 8. MQTT Communication

The Edge communicates with the Fog layer using the project topic prefix:

`m2i2a/equipe30/`

### 8.1 Edge Topics

| Topic | Direction | QoS | Retained | Purpose |
|---|---|---:|---|---|
| `edge/capteurs` | Edge → Fog | 0 | No | Sensor measurements and Edge metadata |
| `edge/alerte` | Edge → Fog | 1 | No | Fire alert event |
| `edge/statut` | Edge → Fog | 1 | Yes | Edge online/offline status; Last Will reports offline after an unexpected disconnect |
| `edge/metriques` | Edge → Fog | 0 | No | Edge performance/diagnostic metrics, when enabled |
| `edge/commande/mode` | Fog → Edge | 1 | Yes | Operating mode command (`S1`, `S2`, `S3`, or `S4`) |
| `edge/commande/modele` | Fog → Edge | 1 | Yes | Model/configuration parameters |
| `fog/resultats` | Fog → Edge | 1 | No | Fog inference results and confirmation information |

All topics above are relative to the `m2i2a/equipe30/` prefix. For example, the full sensor topic is `m2i2a/equipe30/edge/capteurs`.

### 8.2 Quality of Service and Retained Messages

- QoS 0 is used for frequent sensor measurements and metrics, where an occasional lost update is acceptable.
- QoS 1 is used for alerts, status, commands, and Fog results, where delivery acknowledgement is important.
- The Edge status is retained so a newly connected dashboard can read the latest reported status.
- The Edge Last Will publishes the offline status if the MQTT connection is lost unexpectedly.
- The mode command is retained so the Edge receives the latest selected mode after reconnecting.

### 8.3 Alert Message

The Edge alert message follows this structure:

```json
{
  "id": "edge30-wokwi",
  "seq": 12,
  "ts": 1790000000,
  "niveau": 2,
  "source": "edge"
}
```

This is an illustrative payload. The actual timestamp and sequence number are generated at runtime.

### 8.4 MQTT Configuration

Broker connection settings should be supplied through the firmware configuration (for example, host, port, username, and password), rather than being duplicated throughout the application code. Credentials must not be committed to a public Git repository. Development broker settings used for Wokwi testing are not production security configuration.

## 9. Sensor Measurement JSON

A sensor message contains the contract fields below:

```json
{
  "id": "edge30-wokwi",
  "seq": 12,
  "ts": 1790000000,
  "mode": "S4",
  "t": 28.5,
  "h": 64.5,
  "gaz": 1800,
  "flame": 0,
  "dt": 0.2,
  "valid": 1,
  "y_edge": 1,
  "a_seuil": 0,
  "mv": 2
}
```

| Field | Description |
|---|---|
| `id` | Edge device identifier |
| `seq` | Sample sequence number |
| `ts` | Unix epoch timestamp (seconds) |
| `mode` | Active operating mode (`S1`–`S4`) |
| `t` | Filtered temperature in °C |
| `h` | Filtered relative humidity in % |
| `gaz` | Filtered gas sensor ADC reading |
| `flame` | Filtered flame-proxy state |
| `dt` | Temperature variation per second |
| `valid` | Measurement validity indicator |
| `y_edge` | Edge decision (`-1`, `0`, `1`, or `2`) |
| `a_seuil` | Classical gas-threshold indicator |
| `mv` | Model/configuration version identifier |

> The example values are illustrative, not a prescribed test vector. Use the current model stub and firmware configuration to choose Wokwi slider values for normal, perturbation, and fire tests.

## 10. Timestamp Synchronization

The firmware synchronizes time using NTP. The `ts` field must contain a Unix epoch timestamp. Measurements must not be published with a placeholder timestamp of zero when NTP is not ready; the firmware waits until the required timestamp is available.

## 11. Project Structure

The exact filenames can vary between the stable and timing projects. A typical Version D layout is:

```text
SmartFire30-Edge/
├── edge/
│   ├── smartfire_edge_stepD.ino
│   ├── smartfire_config.h
│   ├── model_stub.h
│   ├── diagram.json
│   └── libraries.txt
├── simulation/
│   └── wokwi-project.txt
└── README.md
```

### File Responsibilities

- `smartfire_edge_stepD.ino`: main Version D firmware, task creation, acquisition/inference/communication flow, MQTT handling, and alarm logic.
- `smartfire_config.h`: project configuration such as pins and MQTT connection parameters.
- `model_stub.h`: provisional decision logic used while the final Edge model is being integrated.
- `diagram.json`: Wokwi circuit configuration.
- `libraries.txt`: Arduino libraries required by the Wokwi project.
- `wokwi-project.txt`: Wokwi project configuration, if this file is used by the selected project layout.

Update the structure above if the checked-in filenames differ from the actual Version D repository.

## 12. Running the Wokwi Simulation

1. Open the Version D Wokwi project.
2. Check the firmware configuration, including Wi-Fi and MQTT broker settings.
3. Start the ESP32 simulation.
4. Wait for Wi-Fi and MQTT connection messages in the Serial Monitor.
5. Wait for NTP synchronization before expecting timestamped measurements to be published.
6. Confirm that the Edge subscribes to `edge/commande/mode`, `edge/commande/modele`, and `fog/resultats`.
7. Observe `edge/statut`, `edge/capteurs`, and `edge/alerte` with an MQTT client or the project dashboard.
8. Test the agreed operating modes and sensor conditions with the team. During a shared broker test, coordinate retained mode changes with the project lead.

## 13. Development and Test Status

The following checklist should be updated to match the latest tested commit and evidence:

- [x] Sensor acquisition and filtering from the earlier processing stage
- [x] Temperature variation calculation (`dt`)
- [x] Measurement validation field
- [x] FreeRTOS task separation for acquisition, inference, and communication
- [x] MQTT connection and subscriptions
- [x] Edge online/offline status using retained status and Last Will
- [x] Sensor measurement publication
- [x] QoS 1 Edge alert publication
- [x] Operating mode command reception (`S1`–`S4`)
- [x] Fog result reception
- [x] Local alarm logic in Edge-controlled modes
- [x] NTP timestamp synchronization before timestamped publication
- [ ] Final trained TinyML model integrated and validated on ESP32
- [ ] Full end-to-end Edge → Fog → Cloud → dashboard validation documented for the current commit
- [ ] Physical hardware validation (if physical sensors/board are available)

A checked box means the corresponding functionality has been implemented or observed in the development tests described for Version D; it does not replace a test report or prove production readiness.

## 14. Technologies

ESP32 · Arduino/C++ · FreeRTOS · Wokwi · DHT22 · MQ-2 · Photoresistor (LDR proxy) · MQTT · JSON · NTP · Edge Computing · AIoT

---

**Project:** SmartFire30  
**Component:** Edge Device  
**Firmware stage:** Version D — FreeRTOS, MQTT, operating modes, local alarm, and Fog interaction
