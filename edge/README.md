# SmartFire30-Edge

An AIoT-based fire and smoke detection system using ESP32 for sensor
acquisition, local data processing, and Edge decision-making.

## Project Overview

**SmartFire30-Edge** is part of the SmartFire30 project. It monitors
environmental conditions using sensors and processes collected data
locally on the ESP32.

This version focuses on **Step B**: sensor acquisition, filtering,
validation, temperature variation calculation, local decision-making,
and JSON serialization.

## Objectives

-   Acquire environmental sensor data.
-   Filter noisy sensor measurements.
-   Validate sensor readings.
-   Calculate temperature variation (`dt`).
-   Perform local Edge decision-making.
-   Generate structured JSON messages.
-   Test the system using Wokwi simulation.

## System Components

  Component             Purpose
  --------------------- --------------------------------------
  ESP32                 Main processing unit
  DHT22                 Temperature and humidity measurement
  MQ-2                  Gas measurement
  Photoresistor (LDR)   Flame sensor proxy in simulation

> **Note:** The LDR is a simulation substitute for the flame sensor, not
> a real flame sensor.

## Architecture

``` text
Sensors
   |
   v
ESP32 -> Data Acquisition -> Filtering -> Validation
                                  |
             +------------------+------------------+
             |                  |                  |
       Median Filter       Median Filter      Median Filter
        Temperature         Humidity             Gas
             |
       Majority Vote (3 samples) for Flame Proxy
                                  |
                                  v
                   Temperature Variation (dt)
                                  |
                                  v
                        Edge Decision
                                  |
                                  v
                        JSON Serialization
                                  |
                                  v
                         Serial Monitor
```

## Data Processing

### Median Filtering

A median filter with a window size of 5 samples is applied to
temperature, humidity, and gas measurements to reduce noise and the
effect of abnormal readings.

### Flame Proxy Filtering

A Majority Vote filter using 3 readings is applied to the
photoresistor's digital signal to reduce temporary fluctuations.

### Temperature Variation (`dt`)

Temperature variation is calculated over a 5-second interval:

\[ dt = `\frac{T(n)-T(n-5)}{5}`{=tex} \]

It represents the approximate temperature change per second. During the
initial acquisition period, `dt` is zero until sufficient history is
available.

### Data Validation

The `valid` field indicates whether the current sensor measurements are
considered valid:

-   `1`: Valid measurements.
-   `0`: Invalid measurements.

Invalid data should not be used for model inference.

## JSON Data Format

Example output:

``` json
{
  "id": "edge30-wokwi",
  "seq": 0,
  "ts": 0,
  "mode": "S4",
  "t": 20,
  "h": 71.5,
  "gaz": 3628,
  "flame": 0,
  "dt": 0,
  "valid": 1,
  "y_edge": 1,
  "a_seuil": 1,
  "mv": 1
}
```

  Field       Description
  ----------- ----------------------------------
  `id`        Device identifier
  `seq`       Sample sequence number
  `ts`        Timestamp
  `mode`      Operating mode
  `t`         Filtered temperature in °C
  `h`         Filtered humidity in %
  `gaz`       Filtered gas sensor reading
  `flame`     Filtered flame-proxy state
  `dt`        Temperature variation per second
  `valid`     Data validity indicator
  `y_edge`    Local Edge decision
  `a_seuil`   Threshold-based alarm indicator
  `mv`        Model version

## Project Structure

``` text
SmartFire30-Edge/
|
├── edge/
│   ├── smartfire_edge.ino
│   ├── model_stub.h
│   ├── diagram.json
│   └── libraries.txt
|
├── simulation/
│   └── wokwi-project.txt
|
└── README.md
```

## Files Description

-   `smartfire_edge.ino`: Main ESP32 firmware for acquisition,
    filtering, validation, calculations, and JSON output.
-   `model_stub.h`: Temporary Edge decision model used during
    development and testing.
-   `diagram.json`: Wokwi circuit configuration.
-   `libraries.txt`: Required Arduino libraries.
-   `wokwi-project.txt`: Wokwi project configuration.

## Simulation

The project is tested using the Wokwi ESP32 simulator.

1.  Open the Wokwi project.
2.  Start the ESP32 simulation.
3.  Adjust sensor values in the simulator.
4.  Open the Serial Monitor.
5.  Observe raw readings, filtered values, and JSON messages.

Simulation enables testing under different environmental conditions
without physical hardware.

## Current Development Status

### Step B --- Sensor Acquisition and Processing

-   [x] Sensor acquisition
-   [x] Median filtering for temperature
-   [x] Median filtering for humidity
-   [x] Median filtering for gas
-   [x] Majority Vote filtering for flame proxy
-   [x] Temperature variation calculation (`dt`)
-   [x] JSON serialization
-   [x] Initial Wokwi testing
-   [ ] Unix Epoch timestamp synchronization

## Future Development

Future stages are planned to add FreeRTOS task management, MQTT
communication, integration of the real AI model, and system performance
evaluation.

## Technologies

ESP32 · Arduino/C++ · Wokwi · DHT22 · MQ-2 · Photoresistor · JSON · AIoT
· Edge Computing

------------------------------------------------------------------------

**Project:** SmartFire30\
**Component:** Edge Device\
**Current Stage:** Step B --- Sensor Acquisition, Filtering, Validation
and JSON Serialization
