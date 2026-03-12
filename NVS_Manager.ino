#include <Preferences.h>
#include <EEPROM.h>
#include <WiFi.h>
#include "Samovar.h"
#include "state/globals.h"
#include "support/safe_parse.h"
#include "storage/nvs_profiles.h"

Preferences prefs;

// -------------------------------------------------------------------------------------------------
// Wi-Fi креды (используем стандартный namespace ESP32, как ESPAsyncWiFiManager):
// ESP32 автоматически сохраняет креденшалы при вызове WiFi.begin(ssid, password) с WiFi.persistent(true)
// Для чтения используем WiFi.SSID() и WiFi.begin() без параметров
// -------------------------------------------------------------------------------------------------

bool load_wifi_credentials(char *ssid, size_t ssid_len, char *pass, size_t pass_len) {
  if (!ssid || !pass || ssid_len == 0 || pass_len == 0) return false;
  ssid[0] = '\0';
  pass[0] = '\0';

  // Используем тот же подход, что и ESPAsyncWiFiManager:
  // WiFi.SSID() возвращает сохраненный SSID из стандартного namespace
  String saved_ssid = WiFi.SSID();
  
  if (saved_ssid.length() > 0) {
    size_t n = saved_ssid.length();
    if (n >= ssid_len) n = ssid_len - 1;
    if (n > 0) memcpy(ssid, saved_ssid.c_str(), n);
    ssid[n] = '\0';
    // Пароль нельзя получить через WiFi API без подключения,
    // но это не проблема - WiFi.begin() без параметров использует сохраненный пароль автоматически
    return true;
  }

  return false;
}

String get_wifi_ssid() {
  // Используем WiFi.SSID() для получения сохраненного SSID (как ESPAsyncWiFiManager)
  return WiFi.SSID();
}

void save_wifi_credentials(const char *ssid, const char *pass) {
  if (!ssid) return;
  
  // WiFi.persistent(true) включает автоматическое сохранение в стандартный namespace
  // WiFi.begin(ssid, pass) сохраняет креденшалы автоматически
  WiFi.persistent(true);
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, pass ? pass : "");
  WiFi.persistent(false);
  
  Serial.print(F("WiFi credentials saved. SSID: "));
  Serial.println(ssid);
}

void clear_wifi_credentials() {
  // Используем WiFi.disconnect(true) для очистки сохраненных креденшалов
  // true означает, что нужно также очистить сохраненные креденшалы из стандартного namespace
  WiFi.disconnect(true);
  
  Serial.println(F("WiFi credentials cleared from standard namespace"));
}
