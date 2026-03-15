#ifndef __SAMOVAR_ORCHESTRATION_H_
#define __SAMOVAR_ORCHESTRATION_H_

#include "Samovar.h"
#include "state/globals.h"
#include "app/alarm_control.h"
#include "app/config_apply.h"
#include "app/loop_dispatch.h"
#include "app/messages.h"
#ifdef USE_LUA
#include "ui/lua/runtime.h"
#endif
#include "app/runtime_tasks.h"
#include "io/sensor_scan.h"
#include "io/power_control.h"
#include "modes/beer/beer_runtime.h"
#include "modes/bk/bk_finish.h"
#include "modes/dist/dist_runtime.h"
#include "modes/nbk/nbk_finish.h"
#include "modes/rect/rect_runtime.h"
#include "storage/nvs_migration.h"
#include "storage/nvs_profiles.h"
#include "support/task_stack_usage.h"
#include "ui/web/server_init.h"
#include "storage/web_assets_sync.h"

void setupMenu();
void encoder_getvalue();
void menu_calibrate();
void change_samovar_mode();
void samovar_reset();
void menu_switch_focus();
String http_sync_request_get(String url);
void writeString(String Str, uint8_t num);
uint8_t check_I2C_device(uint8_t address);
void initMqtt();
void init_crash_handler();
void recvMsg(uint8_t *data, size_t len);
inline void samovar_app_setup() {
  esp_log_level_set("i2c.master", ESP_LOG_NONE);
  pinMode(0, INPUT);
  vTaskDelay(600 / portTICK_PERIOD_MS);
  if (digitalRead(0) == LOW) {
    WiFi.mode(WIFI_STA);
    WiFi.persistent(true);
    WiFi.disconnect(true, true);
    WiFi.persistent(false);
  }
#ifdef __SAMOVAR_NOT_USE_WDT
  esp_task_wdt_init(1, false);
  esp_task_wdt_init(2, false);
  rtc_wdt_protect_off();
  rtc_wdt_disable();
  disableCore0WDT();
  disableCore1WDT();
#endif
  heap_caps_enable_nonos_stack_heaps();

  vTaskDelay(500 / portTICK_PERIOD_MS);
  Serial.begin(115200);

#ifdef __SAMOVAR_DEBUG
  esp_log_level_set("*", ESP_LOG_VERBOSE);
  Serial.println("Using ESP object:");
  Serial.println(ESP.getSdkVersion());

  Serial.println("Using lower level function:");
  Serial.println(esp_get_idf_version());
#endif

#if defined(ARDUINO_ESP32S3_DEV)
#else
  touch_pad_intr_disable();
#endif

  xMsgSemaphore = xSemaphoreCreateBinaryStatic(&xMsgSemaphoreBuffer);
  xSemaphoreGive(xMsgSemaphore);

  xI2CSemaphore = xSemaphoreCreateBinaryStatic(&xI2CSemaphoreBuffer);
  xSemaphoreGive(xI2CSemaphore);

  WiFi.mode(WIFI_STA);
  WiFi.disconnect(false);
  delay(50);
  WiFi.setSleep(false);
  WiFi.setHostname(host);
  WiFi.setAutoReconnect(true);

  Wire.begin(LCD_SDA, LCD_SCL);

  lcd_found = (check_I2C_device(LCD_ADDRESS) == LCD_ADDRESS);

  stepper.disable();

  WFtotalMilliLitres = 0;

#if (defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3))
  timer = timerBegin(1000000);
  timerAttachInterrupt(timer, &StepperTicker);
#else
  timer = timerBegin(2, 80, true);
  timerAttachInterrupt(timer, &StepperTicker, true);
#endif

  ESP32PWM::allocateTimer(0);
  ESP32PWM::allocateTimer(1);
  ESP32PWM::allocateTimer(2);
  ESP32PWM::allocateTimer(3);

#ifdef SERVO_PIN
  servo.setPeriodHertz(50);
  servo.attach(SERVO_PIN, 500, 2500);
#endif

#ifdef BTN_PIN
  btn.setType(LOW_PULL);
  btn.setTickMode(AUTO);
  btn.setDebounce(30);
#endif

#ifdef ALARM_BTN_PIN
  alarm_btn.setType(HIGH_PULL);
  alarm_btn.setTickMode(AUTO);
  alarm_btn.setDebounce(30);
#endif

  bool wifiAP = false;
#ifdef BTN_PIN
  btn.tick();
  if (btn.isPress()) {
    wifiAP = true;
    vTaskDelay(2000);
  }
#endif

  migrate_from_eeprom();
  read_config();

  Serial.print("NVS: Configuration loaded. Flag = ");
  Serial.println(SamSetup.flag);

  if (SamSetup.flag > 250) {
    Serial.println("NVS is empty. Initializing with default values...");
    SamSetup.flag = 2;
    SamSetup.DeltaSteamTemp = 0.1;
    SamSetup.DeltaPipeTemp = 0.2;
    SamSetup.DeltaWaterTemp = 0;
    SamSetup.DeltaTankTemp = 0;
    SamSetup.DeltaACPTemp = 0;
    SamSetup.SetSteamTemp = 0;
    SamSetup.SetPipeTemp = 0;
    SamSetup.SetWaterTemp = 0;
    SamSetup.SetTankTemp = 0;
    SamSetup.SetACPTemp = 0;
    SamSetup.StepperStepMl = STEPPER_STEP_ML;
    SamSetup.StepperStepMlI2C = I2C_STEPPER_STEP_ML_DEFAULT;
    SamSetup.UsePreccureCorrect = true;
    SamSetup.SteamDelay = 20;
    SamSetup.PipeDelay = 20;
    SamSetup.WaterDelay = 20;
    SamSetup.TankDelay = 20;
    SamSetup.ACPDelay = 20;
    SamSetup.HeaterResistant = 15.2;
    SamSetup.LogPeriod = 3;
    SamSetup.TimeZone = 3;
    SamSetup.blynkauth[0] = '\0';
    SamSetup.videourl[0] = '\0';
    SamSetup.UseWS = 1;
    SamSetup.ColDiam = 2.0f;
    SamSetup.ColHeight = 0.5f;
    SamSetup.PackDens = 80;
    save_profile_nvs();
    Serial.println("Default values saved to NVS");
  }

  pinMode(RELE_CHANNEL1, OUTPUT);
  digitalWrite(RELE_CHANNEL1, !SamSetup.rele1);
  pinMode(RELE_CHANNEL2, OUTPUT);
  digitalWrite(RELE_CHANNEL2, !SamSetup.rele2);
  pinMode(RELE_CHANNEL3, OUTPUT);
  digitalWrite(RELE_CHANNEL3, !SamSetup.rele3);
  pinMode(RELE_CHANNEL4, OUTPUT);
  digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);

#ifdef USE_WATER_VALVE
  pinMode(WATER_PUMP_PIN, OUTPUT);
  digitalWrite(WATER_PUMP_PIN, !USE_WATER_VALVE);
#endif

  pinMode(BZZ_PIN, OUTPUT);
  digitalWrite(BZZ_PIN, LOW);

#ifdef USE_PRESSURE_MPX
  pinMode(LUA_PIN, INPUT);
#endif

  Serial.println(F("Samovar started"));
  setupMenu();
  writeString(F("      Samovar "), 1);
  writeString("     Version " + (String)SAMOVAR_VERSION, 2);
  writeString(F("Connecting to WI-FI"), 3);

  for (uint8_t i = 0; i < 17; i = i + 8) {
    chipId |= ((ESP.getEfuseMac() >> (40 - i)) & 0xff) << i;
  }

  Serial.printf("ESP32 Chip model = %s Rev %d\n", ESP.getChipModel(), ESP.getChipRevision());
  Serial.print("Chip ID: ");
  Serial.println(chipId);

  String StIP;

  auto start_ap = [&]() {
    WiFi.mode(WIFI_AP);
    WiFi.softAP("Samovar");
    StIP = WiFi.softAPIP().toString();
    Serial.println(F("Started as WiFi AP"));
  };

  if (!wifiAP) {
    WiFi.mode(WIFI_STA);
    WiFi.disconnect(false);

    Serial.println(F("Attempting to connect to saved WiFi..."));
    WiFi.begin();

    uint32_t startMs = millis();
    while (WiFi.status() != WL_CONNECTED && (millis() - startMs) < 15000) {
      delay(250);
      Serial.print(".");
    }
    Serial.println();

    if (WiFi.status() == WL_CONNECTED) {
      StIP = WiFi.localIP().toString();
      Serial.print(F("Connected to "));
      Serial.print(WiFi.SSID());
      Serial.print(F(" - IP: "));
      Serial.println(StIP);
    } else {
      Serial.println(F("Failed to connect to saved WiFi. Starting AP mode..."));
      wifiAP = true;
      start_ap();
    }
  } else {
    start_ap();
  }

  Serial.print(F("IP address: "));
  copyStringSafe(ipst, StIP);

  Serial.println(StIP);

  if (!MDNS.begin(host)) {
    Serial.println(F("Error setting up MDNS responder!"));
  } else {
#ifdef __SAMOVAR_DEBUG
    Serial.println(F("mDNS responder started"));
#endif
  }

  writeString(F("Connected"), 4);

#ifdef SAMOVAR_USE_BLYNK
  if (SamSetup.blynkauth[0] != 0 && !wifiAP) {
    writeString(F("Connecting to Blynk "), 3);
    writeString(F("               "), 4);
#ifdef __SAMOVAR_DEBUG
    Serial.println(F("Connecting to Blynk"));
#endif
#ifdef BLYNK_SAMOVAR_TOOL
    Blynk.config(SamSetup.blynkauth, BLYNK_SAMOVAR_TOOL, 8080);
#else
    Blynk.config(SamSetup.blynkauth);
#endif
    Blynk.connect(BLYNK_TIMEOUT_MS);
#ifdef __SAMOVAR_DEBUG
    Serial.println(F("Blynk started"));
#endif
  }
#endif

#ifdef USE_TELEGRAM
  if (WiFi.status() == WL_CONNECTED && SamSetup.tg_token[0] != 0 && SamSetup.tg_chat_id[0] != 0) {
    vTaskDelay(5 / portTICK_PERIOD_MS);
    http_sync_request_get(String("http://212.237.16.93/bot") + SamSetup.tg_token + "/sendMessage?chat_id=" + SamSetup.tg_chat_id + "&text=" + urlEncode("Самовар готов к работе; IP=http://" + StIP));
  } else if (SamSetup.tg_chat_id[0] != 0) {
    Serial.println(F("Проблема с покдлючением к интернету."));
  }
#endif

#ifdef USE_UPDATE_OTA
  ArduinoOTA.onStart([]() {
    ota_running = true;
    String type;
    if (ArduinoOTA.getCommand() == U_FLASH)
      type = "Sketch";
    else {
      type = "Filesystem";
      SPIFFS.end();
    }
    type = type + " update start";
    events.send(type.c_str(), "ota");

#ifdef SAMOVAR_USE_BLYNK
    if (Blynk.connected()) {
      Blynk.disconnect();
    }
#endif
#ifdef USE_MQTT
    if (mqttClient.connected()) {
      mqttClient.disconnect();
    }
#endif
  });
  ArduinoOTA.onEnd([]() {
    ota_running = false;
    events.send(("Update End"), "ota");
  });
  ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
    char p[32];
    const uint32_t percent = (total > 0) ? (progress * 100U) / total : 0U;
    strcpy(p, "Progress: ");
    ultoa(percent, p + strlen(p), 10);
    strcat(p, "%\n");
    events.send(p, "ota");
    yield();
  });
  ArduinoOTA.onError([](ota_error_t error) {
    ota_running = false;
    if (error == OTA_AUTH_ERROR) events.send("Auth Failed", "ota");
    else if (error == OTA_BEGIN_ERROR)
      events.send(("Begin Failed"), "ota");
    else if (error == OTA_CONNECT_ERROR)
      events.send(("Connect Failed"), "ota");
    else if (error == OTA_RECEIVE_ERROR)
      events.send(("Recieve Failed"), "ota");
    else if (error == OTA_END_ERROR)
      events.send(("End Failed"), "ota");
  });
  ArduinoOTA.setHostname(SAMOVAR_HOST);
  ArduinoOTA.setTimeout(30000);
  ArduinoOTA.begin();
#endif

  alarm_event = false;

  sensor_init();

  startService();
  samovar_reset();

  WebServerInit();

#ifdef USE_CRASH_HANDLER
  init_crash_handler();
#endif

#ifdef SAMOVAR_USE_POWER
  xTaskCreatePinnedToCore(
    triggerPowerStatus,
    "PowerStatusTask",
    1800,
    NULL,
    1,
    &PowerStatusTask,
    0);
  set_power_mode(POWER_SLEEP_MODE);
#endif

#ifdef USE_WEB_SERIAL
  WebSerial.begin(&server);
  WebSerial.onMessage(recvMsg);
#endif

#ifdef USE_WATERSENSOR
  attachInterrupt(WATERSENSOR_PIN, WFpulseCounter, FALLING);
#endif

#ifdef USE_HEAD_LEVEL_SENSOR
#ifdef WHLS_HIGH_PULL
  whls.setType(HIGH_PULL);
#else
  whls.setType(LOW_PULL);
#endif

  whls.setDebounce(50);
  whls.setTickMode(MANUAL);
  whls.setTimeout(WHLS_ALARM_TIME * 1000);
  attachInterrupt(WHEAD_LEVEL_SENSOR_PIN, isrWHLS_TICK, CHANGE);
#endif

#ifdef USE_MQTT
  if (!wifiAP) {
    initMqtt();
    vTaskDelay(500);
  }
#endif

  xTaskCreatePinnedToCore(
    triggerSysTicker,
    "SysTicker",
    3200,
    NULL,
    1,
    &SysTickerTask1,
    0);

  xTaskCreatePinnedToCore(
    triggerGetClock,
    "GetClockTicker",
    3400,
    NULL,
    1,
    &GetClockTask1,
    1);

  NTP.setTimeOffset(SamSetup.TimeZone * 3600);
  NTP.setUpdateInterval(1800000);
  NTP.begin();
  delay(100);
  if (WiFi.status() == WL_CONNECTED) {
    int attempts = 0;
    while (!NTP.forceUpdate() && attempts < 2) {
      delay(500);
      attempts++;
    }
  }

#ifdef USE_LUA
  lua_init();
#endif

  writeString(F("      Samovar     "), 1);
  writeString("     Version " + (String)SAMOVAR_VERSION, 2);
  writeString(F("                  "), 3);
  writeString(F("      Started     "), 4);

  get_task_stack_usage();
  Serial.println("Samovar ready");

  use_I2C_dev = 0;

  if (check_I2C_device(1) == 1) {
    use_I2C_dev = 1;
    Serial.println("I2C Stepper as Mixer");
  }
  if (check_I2C_device(2) == 2) {
    use_I2C_dev = 2;
    Serial.println("I2C Stepper as Pump");
  }
  used_byte = SPIFFS.usedBytes();

  SamovarStatus.reserve(80);
}

inline void samovar_app_loop() {
  if (uxTaskGetStackHighWaterMark(NULL) < 325) {
    SendMsg("Стек переполнился. Перезагрузка", ALARM_MSG);
    vTaskDelay(5000);
    ESP.restart();
  }
#ifdef USE_STEPPER_ACCELERATION
  portENTER_CRITICAL_ISR(&timerMux);
#if (defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3))
  timerAlarm(timer, stepper.getPeriod(), true, 0);
#else
  timerAlarmWrite(timer, stepper.getPeriod(), true);
#endif
  portEXIT_CRITICAL_ISR(&timerMux);
#endif

#ifdef USE_UPDATE_OTA
  ArduinoOTA.handle();
  if (ota_running) {
    yield();
    delay(1);
  }
#endif

#ifdef SAMOVAR_USE_BLYNK
  if (!ota_running && Blynk.connected()) {
    Blynk.run();
  }
#endif

#ifdef ALARM_BTN_PIN
  alarm_btn.tick();
  if (alarm_btn.isPress()) {
    set_alarm();
  }
#endif

#ifdef BTN_PIN
  btn.tick();
  if (btn.isPress()) {
    if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE) {
      if (!PowerOn) {
        set_power(true);
      } else if (startval == 0 && SamovarStatusInt < SAMOVAR_STATUS_DISTILLATION) {
        menu_samovar_start();
      } else if (startval != 0 && !program_Pause && SamovarStatusInt < SAMOVAR_STATUS_DISTILLATION) {
        pause_withdrawal(!PauseOn);
      } else if (startval != 0 && program_Pause && SamovarStatusInt < SAMOVAR_STATUS_DISTILLATION) {
        menu_samovar_start();
      }
      if (startval == 100) {
        startval = 0;
        menu_calibrate();
        menu_switch_focus();
      }
    } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
      if (!PowerOn) {
        sam_command_sync = SAMOVAR_DISTILLATION;
      } else
        distiller_finish();
    } else if (Samovar_Mode == SAMOVAR_BK_MODE) {
      if (!PowerOn) {
        sam_command_sync = SAMOVAR_BK;
      } else
        bk_finish();
    } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
      if (!PowerOn) {
        sam_command_sync = SAMOVAR_NBK;
      } else
        nbk_finish();
    } else if (Samovar_Mode == SAMOVAR_BEER_MODE) {
      if (!PowerOn) {
        sam_command_sync = SAMOVAR_BEER;
      } else
        run_beer_program(ProgramNum + 1);
    }
  }
#endif

  process_sam_command_sync();
  dispatch_samovar_mode_runtime();

  encoder.tick();
  encoder_getvalue();

  process_buzzer();
  vTaskDelay(5 / portTICK_PERIOD_MS);
}

#endif
