// smartfire_edge.ino
// Etape B : Filtrage, validite et JSON
// Toujours sans FreeRTOS ni MQTT

#include <DHT.h>
#include <ArduinoJson.h>
#include <math.h>
#include <time.h>

#include "model_stub.h"

// -------------------- PINS --------------------

#define PIN_DHT   15
#define PIN_GAZ   34
#define PIN_FLAME 27

#define FLAME_ACTIVE_LOW 1

#define PIN_LED_G 33
#define PIN_LED_O 32
#define PIN_LED_R 26
const int MEDIAN_SIZE = 5;

int invalidStreak = 0;  // consecutive invalid samples
// -------------------- CONFIGURATION --------------------

#define GAS_THRESHOLD 2000

const char* NODE_ID = "edge30-wokwi";
const char* MODE = "S4";
const int MODEL_VERSION = 1;

DHT dht(PIN_DHT, DHT22);

Eloquent::ML::Port::RandomForest clf;

// -------------------- FILTRAGE --------------------

// Historique des 5 dernieres mesures
float tempWindow[5];
float humWindow[5];
float gasWindow[5];

bool filtersInitialized = false;

// Historique des 3 dernieres mesures de flamme
int flameWindow[3];
bool flameInitialized = false;

// Valeurs filtrees
float filteredT = 25.0f;
float filteredH = 50.0f;
float filteredGas = 300.0f;

int filteredFlame = 0;

// Historique de temperature pour calculer dt
float tempHistory[6];
int tempHistoryCount = 0;

float filteredDt = 0.0f;

// Numero de mesure
uint32_t seq = 0;

// -------------------- MEDIAN FILTER --------------------

float median5(const float input[5]) {

  float values[5];

  for (int i = 0; i < 5; i++) {
    values[i] = input[i];
  }

  // Tri par insertion
  for (int i = 1; i < 5; i++) {

    float key = values[i];
    int j = i - 1;

    while (j >= 0 && values[j] > key) {
      values[j + 1] = values[j];
      j--;
    }

    values[j + 1] = key;
  }

  // La valeur centrale est la mediane
  return values[2];
}

// Ajoute une valeur dans une fenetre de 5 mesures
void updateWindow5(float window[5], float newValue, bool initialized) {

  if (!initialized) {

    for (int i = 0; i < 5; i++) {
      window[i] = newValue;
    }

  } else {

    for (int i = 0; i < 4; i++) {
      window[i] = window[i + 1];
    }

    window[4] = newValue;
  }
}

// -------------------- FLAME MAJORITY VOTING --------------------

int majorityFlame(int newValue) {

  if (!flameInitialized) {

    for (int i = 0; i < 3; i++) {
      flameWindow[i] = newValue;
    }

    flameInitialized = true;

  } else {

    flameWindow[0] = flameWindow[1];
    flameWindow[1] = flameWindow[2];
    flameWindow[2] = newValue;
  }

  int sum = flameWindow[0] +
            flameWindow[1] +
            flameWindow[2];

  return (sum >= 2) ? 1 : 0;
}

// -------------------- TEMPERATURE SLOPE dt --------------------

void updateTemperatureSlope(float newTemperature) {

  if (tempHistoryCount < 6) {

    tempHistory[tempHistoryCount] = newTemperature;
    tempHistoryCount++;

  } else {

    for (int i = 0; i < 5; i++) {
      tempHistory[i] = tempHistory[i + 1];
    }

    tempHistory[5] = newTemperature;
  }

  // Il faut 6 valeurs pour comparer t(n) et t(n-5)
  if (tempHistoryCount >= 6) {

    filteredDt =
      (tempHistory[5] - tempHistory[0]) / 5.0f;

  } else {

    filteredDt = 0.0f;
  }
}
// Reset filtering history after an invalid measurement
void resetAcquisitionHistory() {

  // Reset median windows
  filtersInitialized = false;

  // Reset temperature history
  tempHistoryCount = 0;

  // Reset temperature slope
  filteredDt = 0.0f;
}
// -------------------- VALIDATION --------------------

bool validateSensors(float t, float h, int g) {

  bool temperatureOK =
    !isnan(t) && t >= -10.0f && t <= 120.0f;

  bool humidityOK =
    !isnan(h) && h >= 0.0f && h <= 100.0f;

  bool gasOK =
    g >= 0 && g <= 4095;

  return temperatureOK &&
         humidityOK &&
         gasOK;
}

// -------------------- SETUP --------------------

void setup() {

  Serial.begin(115200);

  pinMode(PIN_FLAME, INPUT);

  pinMode(PIN_LED_G, OUTPUT);
  pinMode(PIN_LED_O, OUTPUT);
  pinMode(PIN_LED_R, OUTPUT);

  dht.begin();

  Serial.println("SmartFire30 Edge - Etape B");
}

// -------------------- LOOP --------------------

void loop() {

  // 1. Acquisition des capteurs

  float rawT = dht.readTemperature();
  float rawH = dht.readHumidity();

  int rawGas = analogRead(PIN_GAZ);

  int rawFlame =
    (digitalRead(PIN_FLAME) ==
     (FLAME_ACTIVE_LOW ? LOW : HIGH)) ? 1 : 0;

  // 2. Validation des mesures

  bool valid = validateSensors(rawT, rawH, rawGas);

  // 3. Filtrage des mesures analogiques

  if (valid) {

  // A valid measurement resets the invalid counter
  invalidStreak = 0;

  // Update median windows
  updateWindow5(tempWindow, rawT, filtersInitialized);
  updateWindow5(humWindow, rawH, filtersInitialized);
  updateWindow5(gasWindow, (float)rawGas, filtersInitialized);

  filtersInitialized = true;

  // Calculate filtered values
  filteredT = median5(tempWindow);
  filteredH = median5(humWindow);
  filteredGas = median5(gasWindow);

  // Update dt
  updateTemperatureSlope(filteredT);

  } else {

    invalidStreak++;

    // Reset only after 5 consecutive invalid measurements
    if (invalidStreak == MEDIAN_SIZE) {

      resetAcquisitionHistory();

      Serial.println(
      "[WARN] 5 consecutive invalid samples: history reset"
    );
  } else if (filtersInitialized) {
      // Keep the 1-second timeline during short glitches
    updateTemperatureSlope(filteredT);
    }
}

  // 5. Filtrage numerique de la flamme
  filteredFlame = majorityFlame(rawFlame);
  Serial.printf(
  "[DEBUG] rawGaz=%d filteredGaz=%.0f rawFlame=%d filteredFlame=%d rawT=%.1f filteredT=%.1f dt=%.3f\n",
  rawGas,
  filteredGas,
  rawFlame,
  filteredFlame,
  rawT,
  filteredT,
  filteredDt
);

  // 6. Classification avec le modele provisoire

  int y_edge = -1;

  if (valid) {

    float features[5] = {
      filteredT,
      filteredH,
      filteredGas,
      (float)filteredFlame,
      filteredDt
    };

    y_edge = clf.predict(features);
  }

  // 7. Detecteur classique de reference

  int a_seuil =
    (filteredGas >= GAS_THRESHOLD) ? 1 : 0;

  // 8. Commande des LEDs

  digitalWrite(PIN_LED_G, y_edge == 0);
  digitalWrite(PIN_LED_O, y_edge == 1);
  digitalWrite(PIN_LED_R, y_edge == 2);

  // 9. Numero de mesure et timestamp

  uint32_t currentSeq = seq++;

  time_t currentTime = time(nullptr);

  uint32_t timestamp;
  // No Wi-Fi/NTP at Step B: 0 means not synchronized
  timestamp = (currentTime >= 1700000000)? (uint32_t)currentTime : 0;

  // 10. Construction du JSON

  JsonDocument doc;

  doc["id"] = NODE_ID;
  doc["seq"] = currentSeq;
  doc["ts"] = timestamp;
  doc["mode"] = MODE;

  doc["t"] = round(filteredT * 10.0) / 10.0;
  doc["h"] = round(filteredH * 10.0) / 10.0;
  doc["gaz"] = (int)filteredGas;
  doc["flame"] = filteredFlame;

  doc["dt"] = round(filteredDt * 100.0) / 100.0;
  doc["valid"] = valid ? 1 : 0;

  doc["y_edge"] = y_edge;
  doc["a_seuil"] = a_seuil;
  doc["mv"] = MODEL_VERSION;

  // 11. Affichage d'une ligne JSON dans le Serial Monitor

  serializeJson(doc, Serial);
  Serial.println();

  delay(1000);
}