#ifndef __SAMOVAR_NVS_WIFI_H_
#define __SAMOVAR_NVS_WIFI_H_

#include <Arduino.h>
#include <WiFi.h>

inline bool load_wifi_credentials(char *ssid, size_t ssid_len, char *pass, size_t pass_len) {
  if (!ssid || !pass || ssid_len == 0 || pass_len == 0) return false;
  ssid[0] = '\0';
  pass[0] = '\0';

  // Используем тот же подход, что и ESPAsyncWiFiManager:
  // WiFi.SSID() возвращает сохраненный SSID из стандартного namespace.
  String saved_ssid = WiFi.SSID();

  if (saved_ssid.length() > 0) {
    size_t n = saved_ssid.length();
    if (n >= ssid_len) n = ssid_len - 1;
    if (n > 0) memcpy(ssid, saved_ssid.c_str(), n);
    ssid[n] = '\0';
    // Пароль нельзя получить через WiFi API без подключения,
    // но WiFi.begin() без параметров использует сохраненный пароль автоматически.
    return true;
  }

  return false;
}

inline String get_wifi_ssid() {
  // Используем WiFi.SSID() для получения сохраненного SSID.
  return WiFi.SSID();
}

inline void save_wifi_credentials(const char *ssid, const char *pass) {
  if (!ssid) return;

  // WiFi.begin(ssid, pass) сохраняет креденшалы в стандартном namespace ESP32.
  WiFi.persistent(true);
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, pass ? pass : "");
  WiFi.persistent(false);

  Serial.print(F("WiFi credentials saved. SSID: "));
  Serial.println(ssid);
}

inline void clear_wifi_credentials() {
  // true очищает сохраненные креденшалы из стандартного namespace.
  WiFi.disconnect(true);

  Serial.println(F("WiFi credentials cleared from standard namespace"));
}

#endif
