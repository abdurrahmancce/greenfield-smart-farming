/*
  GreenField soil sensor - ESP32 + a capacitive soil-moisture probe (e.g. "v1.2").

  !!  NOT TESTED ON REAL HARDWARE  !!
  The server side (token check, validation, limits) is covered by automated tests, but this sketch has only been
  written, never run on a board. Expect to adjust pins and the two calibration numbers.

  Wiring: probe VCC -> 3V3, GND -> GND, AOUT -> GPIO 34 (an ADC1 pin - ADC2 does not work while Wi-Fi is on).

  Calibration: read the raw value with the probe in dry air (RAW_DRY) and in a glass of water (RAW_WET) and
  put both numbers below. Capacitive probes read LOWER when wetter.

  Security: use HTTPS. For a first test setInsecure() is used; for real use pin the server certificate
  (client.setCACert(...)). Never publish this file with a real token or Wi-Fi password in it.
*/
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>

const char* WIFI_SSID  = "YOUR_WIFI";
const char* WIFI_PASS  = "YOUR_PASSWORD";
const char* SERVER_URL = "https://greenfield-smart-farming-1.onrender.com/api/sensor/ingest";
const char* TOKEN      = "gfs_PASTE_THE_TOKEN_SHOWN_ONCE";

const int  PROBE_PIN = 34;
const int  RAW_DRY   = 3200;     // reading in dry air   (calibrate!)
const int  RAW_WET   = 1400;     // reading in water     (calibrate!)
const uint64_t SLEEP_MINUTES = 15;   // 4 readings/hour; the server accepts up to 120/hour

float readMoisturePercent() {
  long sum = 0;
  for (int i = 0; i < 16; i++) { sum += analogRead(PROBE_PIN); delay(10); }
  float raw = sum / 16.0;
  float pct = (RAW_DRY - raw) * 100.0 / (RAW_DRY - RAW_WET);
  return constrain(pct, 0.0, 100.0);
}

void setup() {
  Serial.begin(115200);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) delay(500);
  if (WiFi.status() == WL_CONNECTED) {
    WiFiClientSecure client;
    client.setInsecure();                 // TEST ONLY - see the note above
    HTTPClient http;
    http.begin(client, SERVER_URL);
    http.addHeader("Content-Type", "application/json");
    http.addHeader("Authorization", String("Bearer ") + TOKEN);
    String body = String("{\"moisture\":") + String(readMoisturePercent(), 1) + "}";
    int code = http.POST(body);
    Serial.printf("POST %s -> HTTP %d\n", body.c_str(), code);   // 201 = saved, 401 = wrong token, 429 = too often
    http.end();
  }
  esp_sleep_enable_timer_wakeup(SLEEP_MINUTES * 60ULL * 1000000ULL);
  esp_deep_sleep_start();                 // battery friendly: wake, send, sleep
}

void loop() {}
