// smartfire_edge.ino : Étape A (lecture des 3 capteurs, sans FreeRTOS ni réseau)
#include <DHT.h>
#include "model_stub.h"        // modèle provisoire, même interface que le vrai
#include <math.h>

#define PIN_DHT   15
#define PIN_GAZ   34           // ADC1 : l'ADC2 est inutilisable quand le Wi-Fi est actif
#define PIN_FLAME 27
#define FLAME_ACTIVE_LOW 1     // à tester : selon le module, flamme = LOW ou HIGH
#define PIN_LED_G 33
#define PIN_LED_O 32
#define PIN_LED_R 26

DHT dht(PIN_DHT, DHT22);

void setup() {
  Serial.begin(115200);
  pinMode(PIN_FLAME, INPUT);
  pinMode(PIN_LED_G, OUTPUT);
  pinMode(PIN_LED_O, OUTPUT);
  pinMode(PIN_LED_R, OUTPUT);
  dht.begin();                                   // initialise le DHT22
  Serial.println("SmartFire30 Edge - etape A");
}

void loop() {
  float t = dht.readTemperature();               // °C, NaN si lecture échouée
  float h = dht.readHumidity();                  // % humidité
  int   g = analogRead(PIN_GAZ);                 // 0..4095 (ADC 12 bits)
  int   f = (digitalRead(PIN_FLAME) == (FLAME_ACTIVE_LOW ? LOW : HIGH)) ? 1 : 0;
  
  if (isnan(t) || isnan(h)) {
    Serial.println("Erreur: lecture DHT22 invalide");
    digitalWrite(PIN_LED_G, LOW);
    digitalWrite(PIN_LED_O, LOW);
    digitalWrite(PIN_LED_R, LOW);
    delay(1000);
    return;
  }

  Eloquent::ML::Port::RandomForest clf;
  float x[5] = { t, h, (float)g, (float)f, 0.0f }; // ordre FEATURES = [t,h,gaz,flame,dt]
  int y = clf.predict(x);                        // dt = 0 pour l'instant

  digitalWrite(PIN_LED_G, y == 0);               // une seule LED allumée selon la classe
  digitalWrite(PIN_LED_O, y == 1);
  digitalWrite(PIN_LED_R, y == 2);

  Serial.printf("t=%.1f h=%.1f gaz=%d flame=%d -> y=%d\n", t, h, g, f, y);
  delay(1000);                                   // 1 Hz, comme le contrat
}