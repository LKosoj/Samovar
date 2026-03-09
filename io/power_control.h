#ifndef __SAMOVAR_POWER_CONTROL_H_
#define __SAMOVAR_POWER_CONTROL_H_

#include <Arduino.h>

#include "Samovar_ini.h"
#include "state/globals.h"
#include "app/alarm_control.h"
#include "support/process_math.h"
#include "mod_rmvk.h"

void set_menu_screen(uint8_t param);
void SendMsg(const String& m, MESSAGE_TYPE msg_type);
void WriteConsoleLog(String StringLogMsg);

inline void set_power_mode(String Mode);

inline void set_power(bool On) {
  if (alarm_event && On) {
    return;
  }
  PowerOn = On;
  if (On) {
    reg_online = false;
    last_reg_online = millis();

    digitalWrite(RELE_CHANNEL1, SamSetup.rele1);
    set_menu_screen(2);
    power_text_ptr = (char*)"OFF";

#ifdef SAMOVAR_USE_SEM_AVR
    vTaskDelay(3000 / portTICK_PERIOD_MS);
#endif

#ifdef SAMOVAR_USE_POWER
    vTaskDelay(SAMOVAR_USE_POWER_START_TIME / portTICK_PERIOD_MS);
    set_power_mode(POWER_SPEED_MODE);
#else
    current_power_mode = POWER_SPEED_MODE;
    digitalWrite(RELE_CHANNEL4, SamSetup.rele4);
#endif
  } else {
    digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);
    acceleration_heater = false;
#ifdef SAMOVAR_USE_POWER
    vTaskDelay(700 / portTICK_PERIOD_MS);
    set_power_mode(POWER_SLEEP_MODE);
    vTaskDelay(200 / portTICK_PERIOD_MS);
#else
    current_power_mode = POWER_SLEEP_MODE;
#endif
    power_text_ptr = (char*)"ON";
    sam_command_sync = SAMOVAR_RESET;
    digitalWrite(RELE_CHANNEL1, !SamSetup.rele1);

    reg_online = false;
    last_reg_online = 0;
  }
}

#ifdef SAMOVAR_USE_POWER

inline void clear_serial_in_buff() {
  uint8_t cleared = 0;
  while (Serial2.available() && cleared < 100) {
    Serial2.read();
    cleared++;
  }
}

#ifndef SAMOVAR_USE_RMVK
inline void triggerPowerStatus(void* parameter) {
  static String buffer;
  const uint16_t MAX_BUFFER_SIZE = 50;
  while (true) {
    vTaskDelay(500 / portTICK_PERIOD_MS);
    buffer = "";
    uint16_t readCount = 0;
    while (Serial2.available() && readCount < MAX_BUFFER_SIZE) {
      char c = Serial2.read();
      buffer += c;
      readCount++;
    }
    if (buffer.length() > MAX_BUFFER_SIZE) {
      buffer = buffer.substring(buffer.length() - MAX_BUFFER_SIZE);
    }

    if (buffer.length() >= 9) {
      int crPositions[5];
      int crCount = 0;
      for (int i = 0; i < buffer.length() && crCount < 5; i++) {
        if (buffer.charAt(i) == '\r') {
          crPositions[crCount] = i;
          crCount++;
        }
      }

      bool packetFound = false;
      for (int i = crCount - 1; i >= 0 && !packetFound; i--) {
        int crPos = crPositions[i];
        if (crPos >= 8) {
          String data = buffer.substring(crPos - 8, crPos);
          if (data.length() == 8 && data.charAt(0) == 'T') {
            String hexData = data.substring(1);

            int cpv = hexToDec(hexData.substring(0, 3));
            if (cpv > 30 && cpv < 2550) {
              current_power_volt = cpv / 10.0F;
              target_power_volt = hexToDec(hexData.substring(3, 6)) / 10.0F;
              current_power_mode = hexData.substring(6, 7);

              reg_online = true;
              last_reg_online = millis();
              packetFound = true;
#ifdef __SAMOVAR_DEBUG
              Serial.println("KVIC: " + data);
#endif
            }
          }
        }
      }
    }

    if (reg_online && last_reg_online > 0 && (millis() - last_reg_online) > 15000UL) {
      reg_online = false;
    }
  }
}
#else
inline void triggerPowerStatus(void* parameter) {
  String resp;
  uint16_t v;
  while (true) {
    if (PowerOn) {
#ifdef SAMOVAR_USE_SEM_AVR
      if (xSemaphoreTake(xSemaphoreAVR, (TickType_t)((RMVK_DEFAULT_READ_TIMEOUT) / portTICK_RATE_MS)) == pdTRUE) {
        vTaskDelay(RMVK_READ_DELAY / 10 / portTICK_PERIOD_MS);
        clear_serial_in_buff();
        vTaskDelay(5 / portTICK_RATE_MS);
        Serial2.print("АТ+SS?\r");
        for (int i = 0; i < 2; i++) {
          vTaskDelay(RMVK_READ_DELAY / portTICK_RATE_MS);
          if (Serial2.available()) {
            current_power_mode = Serial2.readStringUntil('\r');
            reg_online = true;
            last_reg_online = millis();
#ifdef __SAMOVAR_DEBUG
            WriteConsoleLog("CPM=" + current_power_mode);
#endif
            break;
          }
        }
        xSemaphoreGive(xSemaphoreAVR);
      }
      vTaskDelay(RMVK_READ_DELAY / 5 / portTICK_PERIOD_MS);
      if (xSemaphoreTake(xSemaphoreAVR, (TickType_t)((RMVK_DEFAULT_READ_TIMEOUT) / portTICK_RATE_MS)) == pdTRUE) {
        vTaskDelay(RMVK_READ_DELAY / 10 / portTICK_PERIOD_MS);
        clear_serial_in_buff();
        vTaskDelay(5 / portTICK_RATE_MS);
        Serial2.print("АТ+VO?\r");
        for (int i = 0; i < 2; i++) {
          vTaskDelay(RMVK_READ_DELAY / portTICK_RATE_MS);
          if (Serial2.available()) {
            resp = Serial2.readStringUntil('\r');
#ifdef __SAMOVAR_DEBUG
            WriteConsoleLog("CPV=" + resp);
#endif
            current_power_volt = resp.toInt();
            reg_online = true;
            last_reg_online = millis();
            break;
          }
        }
        xSemaphoreGive(xSemaphoreAVR);
      }
      vTaskDelay(RMVK_READ_DELAY / 5 / portTICK_PERIOD_MS);
      if (xSemaphoreTake(xSemaphoreAVR, (TickType_t)((RMVK_DEFAULT_READ_TIMEOUT) / portTICK_RATE_MS)) == pdTRUE) {
        vTaskDelay(RMVK_READ_DELAY / 10 / portTICK_PERIOD_MS);
        vTaskDelay(5 / portTICK_RATE_MS);
        Serial2.print("АТ+VS?\r");
        for (int i = 0; i < 2; i++) {
          vTaskDelay(RMVK_READ_DELAY / portTICK_RATE_MS);
          if (Serial2.available()) {
            resp = Serial2.readStringUntil('\r');
#ifdef __SAMOVAR_DEBUG
            WriteConsoleLog("TPV=" + resp);
#endif
            v = resp.toInt();
            if (v != 0) {
              target_power_volt = v;
            }
            reg_online = true;
            last_reg_online = millis();
            break;
          }
        }
        xSemaphoreGive(xSemaphoreAVR);
      }
      vTaskDelay(RMVK_READ_DELAY / 5 / portTICK_PERIOD_MS);
#else
      current_power_volt = RMVK_get_out_voltge();
      vTaskDelay(RMVK_READ_DELAY / portTICK_PERIOD_MS);
      v = RMVK_get_store_out_voltge();
      vTaskDelay(RMVK_READ_DELAY / portTICK_PERIOD_MS);
      rmvk.on = RMVK_get_state() > 0;
      if (v != 0) {
        target_power_volt = v;
      }
#endif
    }
    if (reg_online && last_reg_online > 0 && (millis() - last_reg_online) > 5000UL) {
      reg_online = false;
    }
    vTaskDelay(RMVK_READ_DELAY / 5 / portTICK_PERIOD_MS);
  }
}
#endif

inline void set_current_power(float Volt);

inline void check_power_error() {
#ifndef __SAMOVAR_DEBUG
  if (SamSetup.CheckPower && PowerOn) {
    if (!reg_online && last_reg_online > 0 && (millis() - last_reg_online) > 15000UL && current_power_mode != POWER_SLEEP_MODE) {
      power_err_cnt++;
      if (power_err_cnt == 2) {
        SendMsg(("Нет связи с регулятором!"), ALARM_MSG);
      }
      if (power_err_cnt > 6) {
        delay(1000);
        set_buzzer(true);
        set_power(false);
        SendMsg(("Аварийное отключение! Нет связи с регулятором нагрева."), ALARM_MSG);
      }
      return;
    }

    if (current_power_mode == POWER_WORK_MODE && current_power_volt > 0 && target_power_volt > 0 &&
        abs((current_power_volt - target_power_volt) / target_power_volt) > 0.2f) {
      power_err_cnt++;
      if (power_err_cnt > 6) set_current_power(target_power_volt);
      if (power_err_cnt > 12) {
        delay(1000);
        set_buzzer(true);
        set_power(false);
        SendMsg(("Аварийное отключение! Ошибка управления нагревателем."), ALARM_MSG);
      }
      return;
    }
  }
#endif
  power_err_cnt = 0;
}

inline void get_current_power() {
  if (!PowerOn) {
    current_power_volt = 0;
    target_power_volt = 0;
    current_power_mode = "N";
    current_power_p = 0;
    return;
  }
#ifndef SAMOVAR_USE_SEM_AVR
  current_power_p = current_power_volt * current_power_volt / SamSetup.HeaterResistant;
#else
  current_power_p = target_power_volt;
#endif
}

inline void set_current_power(float Volt) {
  if (!PowerOn) return;
#ifdef __SAMOVAR_DEBUG
  WriteConsoleLog("Set current power =" + (String)Volt);
#endif
#ifndef SAMOVAR_USE_SEM_AVR
  if (Volt < 40) {
#else
  if (Volt < 100) {
#endif
    set_power_mode(POWER_SLEEP_MODE);
    target_power_volt = 0;
    return;
  } else {
    set_power_mode(POWER_WORK_MODE);
  }
  target_power_volt = Volt;
  vTaskDelay(100 / portTICK_PERIOD_MS);
#ifdef SAMOVAR_USE_RMVK
#ifndef SAMOVAR_USE_SEM_AVR
  RMVK_set_out_voltge(Volt);
#else
  if (xSemaphoreTake(xSemaphoreAVR, (TickType_t)((RMVK_DEFAULT_READ_TIMEOUT * 3) / portTICK_RATE_MS)) == pdTRUE) {
    String Cmd;
    int V = Volt;
    if (V < 100) Cmd = "0";
    else Cmd = "";
    Cmd = Cmd + (String)V;
    vTaskDelay(RMVK_READ_DELAY / 10 / portTICK_PERIOD_MS);
    Serial2.print("АТ+VS=" + Cmd + "\r");
    vTaskDelay(RMVK_READ_DELAY / portTICK_PERIOD_MS);
    xSemaphoreGive(xSemaphoreAVR);
  }
#endif
#else
  String hexString = String((int)(Volt * 10), HEX);
  Serial2.print("S" + hexString + "\r");
#endif
  target_power_volt = Volt;
}

inline void set_power_mode(String Mode) {
  if (current_power_mode == Mode) return;
  current_power_mode = Mode;

  if (Mode == POWER_SLEEP_MODE) {
    target_power_volt = 0;
  }

  vTaskDelay(50 / portTICK_PERIOD_MS);
#ifdef SAMOVAR_USE_RMVK
  if (Mode == POWER_SLEEP_MODE) {
#ifdef SAMOVAR_USE_SEM_AVR
    if (xSemaphoreTake(xSemaphoreAVR, (TickType_t)((RMVK_DEFAULT_READ_TIMEOUT * 3) / portTICK_RATE_MS)) == pdTRUE) {
      vTaskDelay(RMVK_READ_DELAY / 10 / portTICK_PERIOD_MS);
      Serial2.print("АТ+ON=0\r");
      vTaskDelay(RMVK_READ_DELAY / portTICK_PERIOD_MS);
      xSemaphoreGive(xSemaphoreAVR);
    }
#else
    RMVK_set_on(0);
#endif
  } else if (Mode == POWER_SPEED_MODE) {
#ifdef __SAMOVAR_DEBUG
    WriteConsoleLog("Set power mode=" + Mode);
#endif
#ifdef SAMOVAR_USE_SEM_AVR
    if (xSemaphoreTake(xSemaphoreAVR, (TickType_t)((RMVK_DEFAULT_READ_TIMEOUT * 7) / portTICK_RATE_MS)) == pdTRUE) {
      vTaskDelay(RMVK_READ_DELAY / 6 / portTICK_PERIOD_MS);
      Serial2.flush();
      Serial2.print("АТ+ON=1\r");
      vTaskDelay(RMVK_READ_DELAY / portTICK_PERIOD_MS);
      Serial2.flush();
      xSemaphoreGive(xSemaphoreAVR);
    }
#else
    RMVK_set_on(1);
    vTaskDelay(RMVK_READ_DELAY / portTICK_PERIOD_MS);
    RMVK_set_out_voltge(MAX_VOLTAGE);
    vTaskDelay(RMVK_READ_DELAY / portTICK_PERIOD_MS);
#endif
  }
#else
  Serial2.print("M" + Mode + "\r");
  vTaskDelay(300 / portTICK_PERIOD_MS);
#endif
}

#endif

#endif
