#include <Preferences.h>
#include <EEPROM.h>
#include <WiFi.h>
#include "Samovar.h"

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
    saved_ssid.toCharArray(ssid, ssid_len);
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

// Хелпер для сохранения строк (char array -> String -> NVS)
void saveStringIfChanged(const char* key, const char* value) {
  String current = prefs.getString(key, "");
  if (current != String(value)) {
    prefs.putString(key, String(value));
  }
}

// Хелпер для сохранения массивов (адреса датчиков)
void saveBytesIfChanged(const char* key, const void* value, size_t len) {
  uint8_t buf[len];
  size_t readLen = prefs.getBytes(key, buf, len);
  if (readLen != len || memcmp(buf, value, len) != 0) {
    prefs.putBytes(key, value, len);
  }
}

void save_profile_nvs() {
  if (!prefs.begin("sam", false)) {
    Serial.println("NVS: Failed to open namespace for writing!");
    return;
  }

  // --- Основные настройки ---
  prefs.putUChar("flag", SamSetup.flag);
  prefs.putUShort("Mode", SamSetup.Mode);
  prefs.putUChar("TimeZone", SamSetup.TimeZone);
  prefs.putFloat("HeaterR", SamSetup.HeaterResistant);
  prefs.putUChar("LogPeriod", SamSetup.LogPeriod);
  
  // --- Температурные настройки (Set) ---
  prefs.putFloat("SetSteam", SamSetup.SetSteamTemp);
  prefs.putFloat("SetPipe", SamSetup.SetPipeTemp);
  prefs.putFloat("SetWater", SamSetup.SetWaterTemp);
  prefs.putFloat("SetTank", SamSetup.SetTankTemp);
  prefs.putFloat("SetACP", SamSetup.SetACPTemp);
  prefs.putFloat("DistTemp", SamSetup.DistTemp);

  // --- Температурные настройки (Delta) ---
  prefs.putFloat("DeltaSteam", SamSetup.DeltaSteamTemp);
  prefs.putFloat("DeltaPipe", SamSetup.DeltaPipeTemp);
  prefs.putFloat("DeltaWater", SamSetup.DeltaWaterTemp);
  prefs.putFloat("DeltaTank", SamSetup.DeltaTankTemp);
  prefs.putFloat("DeltaACP", SamSetup.DeltaACPTemp);

  // --- Задержки (Delays) ---
  prefs.putUShort("SteamDelay", SamSetup.SteamDelay);
  prefs.putUShort("PipeDelay", SamSetup.PipeDelay);
  prefs.putUShort("WaterDelay", SamSetup.WaterDelay);
  prefs.putUShort("TankDelay", SamSetup.TankDelay);
  prefs.putUShort("ACPDelay", SamSetup.ACPDelay);

  // --- Шаговик и настройки насоса ---
  prefs.putUShort("StepMl", SamSetup.StepperStepMl);
  prefs.putUShort("StepMlI2C", SamSetup.StepperStepMlI2C);
  prefs.putBool("AutoSpeed", SamSetup.useautospeed);
  prefs.putUChar("SpeedPerc", SamSetup.autospeed);
  prefs.putBool("UseWS", SamSetup.UseWS); // Датчик воды

  // --- PID и Power ---
  prefs.putFloat("Kp", SamSetup.Kp);
  prefs.putFloat("Ki", SamSetup.Ki);
  prefs.putFloat("Kd", SamSetup.Kd);
  prefs.putFloat("StbVolt", SamSetup.StbVoltage);
  prefs.putFloat("BVolt", SamSetup.BVolt);
  prefs.putBool("CheckPwr", SamSetup.CheckPower);
  prefs.putBool("UseST", SamSetup.UseST); // Разгонный тэн

  // --- Реле ---
  prefs.putBool("rele1", SamSetup.rele1);
  prefs.putBool("rele2", SamSetup.rele2);
  prefs.putBool("rele3", SamSetup.rele3);
  prefs.putBool("rele4", SamSetup.rele4);

  // --- Адреса датчиков (Bytes) ---
  saveBytesIfChanged("SteamAddr", SamSetup.SteamAdress, 8);
  saveBytesIfChanged("PipeAddr", SamSetup.PipeAdress, 8);
  saveBytesIfChanged("WaterAddr", SamSetup.WaterAdress, 8);
  saveBytesIfChanged("TankAddr", SamSetup.TankAdress, 8);
  saveBytesIfChanged("ACPAddr", SamSetup.ACPAdress, 8);

  // --- Строки (Цвета, URL, Токены) ---
  saveStringIfChanged("SteamCol", SamSetup.SteamColor);
  saveStringIfChanged("PipeCol", SamSetup.PipeColor);
  saveStringIfChanged("WaterCol", SamSetup.WaterColor);
  saveStringIfChanged("TankCol", SamSetup.TankColor);
  saveStringIfChanged("ACPCol", SamSetup.ACPColor);
  
  saveStringIfChanged("blynk", SamSetup.blynkauth);
  saveStringIfChanged("video", SamSetup.videourl);
  saveStringIfChanged("tg_tok", SamSetup.tg_token);
  saveStringIfChanged("tg_id", SamSetup.tg_chat_id);

  // --- Доп настройки ---
  prefs.putBool("Preccure", SamSetup.UsePreccureCorrect);
  prefs.putBool("PrgBuzz", SamSetup.ChangeProgramBuzzer);
  prefs.putBool("UseBuzz", SamSetup.UseBuzzer);
  prefs.putBool("UseBBuzz", SamSetup.UseBBuzzer);
  prefs.putUChar("DistTimeF", SamSetup.DistTimeF);
  prefs.putBool("UseHLS", SamSetup.UseHLS);
  prefs.putFloat("MaxPress", SamSetup.MaxPressureValue);

  // --- НБК настройки ---
  prefs.putFloat("NbkIn", SamSetup.NbkIn);
  prefs.putFloat("NbkDelta", SamSetup.NbkDelta);
  prefs.putFloat("NbkDM", SamSetup.NbkDM);
  prefs.putFloat("NbkDP", SamSetup.NbkDP);
  prefs.putFloat("NbkSteamT", SamSetup.NbkSteamT);
  prefs.putFloat("NbkOwPress", SamSetup.NbkOwPress);

  // --- Параметры колонны ---
  prefs.putFloat("ColDiam", SamSetup.ColDiam);
  prefs.putFloat("ColHeight", SamSetup.ColHeight);
  prefs.putUChar("PackDens", SamSetup.PackDens);

  prefs.end();
  //Serial.println("Profile saved to NVS");
}

void load_profile_nvs() {
  if (!prefs.begin("sam", true)) { // Read-only
    Serial.println("NVS: Failed to open namespace for reading!");
    return;
  }

  // Читаем с дефолтными значениями. Для flag используем 255, чтобы определить "пустой NVS"
  SamSetup.flag = prefs.getUChar("flag", 255);
  SamSetup.Mode = prefs.getUShort("Mode", 0);
  SamSetup.TimeZone = prefs.getUChar("TimeZone", 3);
  SamSetup.HeaterResistant = prefs.getFloat("HeaterR", 10.0);
  SamSetup.LogPeriod = prefs.getUChar("LogPeriod", 3);

  SamSetup.SetSteamTemp = prefs.getFloat("SetSteam", 0);
  SamSetup.SetPipeTemp = prefs.getFloat("SetPipe", 0);
  SamSetup.SetWaterTemp = prefs.getFloat("SetWater", 0);
  SamSetup.SetTankTemp = prefs.getFloat("SetTank", 0);
  SamSetup.SetACPTemp = prefs.getFloat("SetACP", 0);
  SamSetup.DistTemp = prefs.getFloat("DistTemp", 0);

  SamSetup.DeltaSteamTemp = prefs.getFloat("DeltaSteam", 0);
  SamSetup.DeltaPipeTemp = prefs.getFloat("DeltaPipe", 0);
  SamSetup.DeltaWaterTemp = prefs.getFloat("DeltaWater", 0);
  SamSetup.DeltaTankTemp = prefs.getFloat("DeltaTank", 0);
  SamSetup.DeltaACPTemp = prefs.getFloat("DeltaACP", 0);

  SamSetup.SteamDelay = prefs.getUShort("SteamDelay", 0);
  SamSetup.PipeDelay = prefs.getUShort("PipeDelay", 0);
  SamSetup.WaterDelay = prefs.getUShort("WaterDelay", 0);
  SamSetup.TankDelay = prefs.getUShort("TankDelay", 0);
  SamSetup.ACPDelay = prefs.getUShort("ACPDelay", 0);

  SamSetup.StepperStepMl = prefs.getUShort("StepMl", STEPPER_STEP_ML);
  SamSetup.StepperStepMlI2C = prefs.getUShort("StepMlI2C", I2C_STEPPER_STEP_ML_DEFAULT);
  SamSetup.useautospeed = prefs.getBool("AutoSpeed", false);
  SamSetup.autospeed = prefs.getUChar("SpeedPerc", 0);
  SamSetup.UseWS = prefs.getBool("UseWS", true);

  SamSetup.Kp = prefs.getFloat("Kp", 150.0);
  SamSetup.Ki = prefs.getFloat("Ki", 1.4);
  SamSetup.Kd = prefs.getFloat("Kd", 1.4);
  SamSetup.StbVoltage = prefs.getFloat("StbVolt", 100.0);
  SamSetup.BVolt = prefs.getFloat("BVolt", 230.0);
  SamSetup.CheckPower = prefs.getBool("CheckPwr", false);
  SamSetup.UseST = prefs.getBool("UseST", true);

  SamSetup.rele1 = prefs.getBool("rele1", false);
  SamSetup.rele2 = prefs.getBool("rele2", false);
  SamSetup.rele3 = prefs.getBool("rele3", false);
  SamSetup.rele4 = prefs.getBool("rele4", false);

  // Чтение массивов
  prefs.getBytes("SteamAddr", SamSetup.SteamAdress, 8);
  prefs.getBytes("PipeAddr", SamSetup.PipeAdress, 8);
  prefs.getBytes("WaterAddr", SamSetup.WaterAdress, 8);
  prefs.getBytes("TankAddr", SamSetup.TankAdress, 8);
  prefs.getBytes("ACPAddr", SamSetup.ACPAdress, 8);

  // Чтение строк (в буферы структуры)
  prefs.getString("SteamCol", "").toCharArray(SamSetup.SteamColor, 20);
  prefs.getString("PipeCol", "").toCharArray(SamSetup.PipeColor, 20);
  prefs.getString("WaterCol", "").toCharArray(SamSetup.WaterColor, 20);
  prefs.getString("TankCol", "").toCharArray(SamSetup.TankColor, 20);
  prefs.getString("ACPCol", "").toCharArray(SamSetup.ACPColor, 20);
  
  prefs.getString("blynk", "").toCharArray(SamSetup.blynkauth, 33);
  prefs.getString("video", "").toCharArray(SamSetup.videourl, 120);
  prefs.getString("tg_tok", "").toCharArray(SamSetup.tg_token, 50);
  prefs.getString("tg_id", "").toCharArray(SamSetup.tg_chat_id, 14);

  SamSetup.UsePreccureCorrect = prefs.getBool("Preccure", true);
  SamSetup.ChangeProgramBuzzer = prefs.getBool("PrgBuzz", false);
  SamSetup.UseBuzzer = prefs.getBool("UseBuzz", false);
  SamSetup.UseBBuzzer = prefs.getBool("UseBBuzz", false);
  SamSetup.DistTimeF = prefs.getUChar("DistTimeF", 16);
  SamSetup.UseHLS = prefs.getBool("UseHLS", true);
  SamSetup.MaxPressureValue = prefs.getFloat("MaxPress", 0);

  SamSetup.NbkIn = prefs.getFloat("NbkIn", 0);
  SamSetup.NbkDelta = prefs.getFloat("NbkDelta", 0);
  SamSetup.NbkDM = prefs.getFloat("NbkDM", 0);
  SamSetup.NbkDP = prefs.getFloat("NbkDP", 0);
  SamSetup.NbkSteamT = prefs.getFloat("NbkSteamT", 0);
  SamSetup.NbkOwPress = prefs.getFloat("NbkOwPress", 0);

  // --- Параметры колонны ---
  SamSetup.ColDiam = prefs.getFloat("ColDiam", 2.0f);
  SamSetup.ColHeight = prefs.getFloat("ColHeight", 0.5f);
  SamSetup.PackDens = prefs.getUChar("PackDens", 80);

  prefs.end();
  //Serial.println("Profile loaded from NVS");
}

// Функция для сброса флага миграции (для тестирования)
void reset_migration_flag() {
  prefs.begin("sam", false);
  prefs.remove("migrated");
  prefs.end();
  Serial.println("NVS: Migration flag reset. Reboot to test migration again.");
}

void migrate_from_eeprom() {
  // Проверяем, была ли миграция
  prefs.begin("sam", true);
  bool migrated = prefs.getBool("migrated", false);
  prefs.end();

  if (migrated) {
    Serial.println("NVS: Migration already done in previous boot.");
    return;
  }

  Serial.println("NVS: Checking for old EEPROM data...");
  EEPROM.begin(sizeof(SetupEEPROM)); // Открываем эмуляцию EEPROM
  SetupEEPROM temp;
  EEPROM.get(0, temp);
  
  // Простая проверка валидности: флаг должен быть не пустым (не 255)
  // В вашем коде используется проверка if (SamSetup.flag > 250) SamSetup.flag = 2;
  // Значит, если флаг <= 250, там, вероятно, есть данные.
  if (temp.flag <= 250) {
    Serial.print("NVS: Found valid EEPROM data (flag=");
    Serial.print(temp.flag);
    Serial.println("). Migrating to NVS...");
    
    // Копируем во временную глобальную переменную, чтобы использовать функцию сохранения
    SetupEEPROM backup = SamSetup; // Сохраняем текущее состояние (на всякий случай)
    SamSetup = temp;               // Подменяем на данные из EEPROM
    
    save_profile_nvs();            // Сохраняем в NVS
    
    SamSetup = backup;             // Возвращаем как было (хотя дальше все равно будет load)
    
    // Ставим флаг миграции
    prefs.begin("sam", false);
    prefs.putBool("migrated", true);
    prefs.end();
    Serial.println("NVS: Migration completed successfully!");
  } else {
    Serial.print("NVS: EEPROM is empty or invalid (flag=");
    Serial.print(temp.flag);
    Serial.println("). Skipping migration.");
    // Если EEPROM пустой, просто ставим флаг, чтобы не проверять каждый раз
    prefs.begin("sam", false);
    prefs.putBool("migrated", true);
    prefs.end();
  }
  EEPROM.end();
}
