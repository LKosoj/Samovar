#pragma once

#include <Arduino.h>
#include "Samovar.h"
#include "samovar_api.h"
#include "runtime_helpers.h"

void set_power(bool On, bool enqueueResetCommand) {
  if (alarm_event && On) {
    return;
  }
  bool wasPowerOn = PowerOn;
  if (On && !wasPowerOn && Samovar_Mode == SAMOVAR_RECTIFICATION_MODE) {
    reset_heat_loss_calculation();
  }
  PowerOn = On;
  if (On) {
    // Стартуем окно ожидания ответа от регулятора (нужно для CheckPower,
    // чтобы отсутствие подключенного регулятора тоже детектилось).
    reg_online = false;
    last_reg_online = millis();

    digitalWrite(RELE_CHANNEL1, SamSetup.rele1);
    set_menu_screen(2);
    power_text_ptr = (char *)"OFF";

#ifdef SAMOVAR_USE_SEM_AVR
    vTaskDelay(3000 / portTICK_PERIOD_MS);
#endif

#ifdef SAMOVAR_USE_POWER
    vTaskDelay(SAMOVAR_USE_POWER_START_TIME / portTICK_PERIOD_MS);
    set_power_mode(POWER_SPEED_MODE);
#else
    set_current_power_mode_value(POWER_SPEED_MODE);
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
    set_current_power_mode_value(POWER_SLEEP_MODE);
#endif
    power_text_ptr = (char *)"ON";
    if (enqueueResetCommand && !queue_samovar_reset_command()) SendMsg("Очередь команд занята: reset после выключения нагрева не поставлен", WARNING_MSG);
    digitalWrite(RELE_CHANNEL1, !SamSetup.rele1);

    // Нагрев выключен — считаем регулятор оффлайн.
    reg_online = false;
    last_reg_online = 0;
  }
}

//////////////////////////////////////////////////////////////////////////////////////////////////////////////
// SAMOVAR_USE_POWER
//////////////////////////////////////////////////////////////////////////////////////////////////////////////
#ifdef SAMOVAR_USE_POWER

void clear_serial_in_buff() { // Быстрая очистка буфера (максимум 100 символов)
  uint8_t cleared = 0;
  while (Serial2.available() && cleared < 100) {
      Serial2.read();
      cleared++;
  }
}

#ifdef SAMOVAR_USE_SEM_AVR
static constexpr const char* SEM_AVR_SAMOVAR_AT_PREFIX = "\xD0\x90\xD0\xA2";

static inline void sem_avr_print_samovar_command(const char* suffix) {
  // SEM_AVR distinguishes Samovar power commands from RMVK voltage commands by
  // the legacy UTF-8 Cyrillic A/T prefix bytes. Keep the bytes explicit.
  Serial2.print(SEM_AVR_SAMOVAR_AT_PREFIX);
  Serial2.print(suffix);
}
#endif

#ifndef SAMOVAR_USE_RMVK
void triggerPowerStatus(void *parameter) {
  static String buffer;
  const uint16_t MAX_BUFFER_SIZE = 50; // Ограничение размера буфера (5 пакетов по 9 символов + запас)
  while (true) {
    vTaskDelay(500 / portTICK_PERIOD_MS);
    buffer = "";
    uint16_t readCount = 0;
    // Читаем данные с ограничением размера буфера
    while (Serial2.available() && readCount < MAX_BUFFER_SIZE) {
        char c = Serial2.read();
        buffer += c;
        readCount++;
    }
    // Если накопилось больше лимита - оставляем только последние символы
    if (buffer.length() > MAX_BUFFER_SIZE) {
        buffer = buffer.substring(buffer.length() - MAX_BUFFER_SIZE);
    }

    // Если в буфере есть данные
    if (buffer.length() >= 9) { // Минимум 9 символов для полного пакета (T1234567\r)
        // Находим все позиции \r в буфере
        int crPositions[5]; // Массив для позиций \r (максимум 5 пакетов)
        int crCount = 0;
        for (int i = 0; i < buffer.length() && crCount < 5; i++) {
            if (buffer.charAt(i) == '\r') {
                crPositions[crCount] = i;
                crCount++;
            }
        }

        // Проверяем пакеты от последнего к первому
        bool packetFound = false;
        for (int i = crCount - 1; i >= 0 && !packetFound; i--) {
            int crPos = crPositions[i];
            // Проверяем, что перед \r есть минимум 8 символов
            if (crPos >= 8) {
                // Берем 8 символов перед \r (формат T1234567)
                String data = buffer.substring(crPos - 8, crPos);

                // Проверяем что первый символ 'T'
                if (data.length() == 8 && data.charAt(0) == 'T') {
                    String hexData = data.substring(1); // убираем 'T'

                    int cpv = hexToDec(hexData.substring(0, 3));
                    if (cpv > 30 && cpv < 2550) {
                        current_power_volt = cpv / 10.0F;
                        target_power_volt = hexToDec(hexData.substring(3, 6)) / 10.0F;
                        set_current_power_mode_value(hexData.substring(6, 7));

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
    // Если давно не было ответа от регулятора — считаем его оффлайн.
    // Таймаут с запасом, т.к. запросы идут пачкой и с задержками.
    if (reg_online && last_reg_online > 0 && (millis() - last_reg_online) > 15000UL) {
      reg_online = false;
    }
  }
}
#else
void triggerPowerStatus(void *parameter) {
  String resp;
  uint16_t v;
  while (true) {
    if (PowerOn) {
#ifdef SAMOVAR_USE_SEM_AVR
      if (xSemaphoreTake(xSemaphoreAVR, (TickType_t)((RMVK_DEFAULT_READ_TIMEOUT) / portTICK_RATE_MS)) == pdTRUE) {
        vTaskDelay(RMVK_READ_DELAY / 10 / portTICK_PERIOD_MS);
        clear_serial_in_buff();
        vTaskDelay(5 / portTICK_RATE_MS);
        sem_avr_print_samovar_command("+SS?\r");
        for (int i = 0; i < 2; i++) {
          vTaskDelay(RMVK_READ_DELAY / portTICK_RATE_MS);
          if (Serial2.available()) {
            set_current_power_mode_value(Serial2.readStringUntil('\r'));
            // Есть ответ от регулятора -> связь жива
            reg_online = true;
            last_reg_online = millis();
#ifdef __SAMOVAR_DEBUG
            WriteConsoleLog("CPM=" + get_current_power_mode_value());
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
        sem_avr_print_samovar_command("+VO?\r");
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
        sem_avr_print_samovar_command("+VS?\r");
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
    // Если давно не было ответа от регулятора — считаем его оффлайн.
    // Таймаут с запасом, т.к. запросы идут пачкой и с задержками.
    if (reg_online && last_reg_online > 0 && (millis() - last_reg_online) > 5000UL) {
      reg_online = false;
    }
    vTaskDelay(RMVK_READ_DELAY / 5 / portTICK_PERIOD_MS);
  }
}
#endif

void check_power_error() {
#ifndef __SAMOVAR_DEBUG
  if (SamSetup.CheckPower && PowerOn) {
    // 1) Потеря связи с регулятором: отключаем нагрев при длительном отсутствии ответа.
    // [L-10] Аварийный таймаут здесь — 15000 мс.
    // В triggerPowerStatus() reg_online сбрасывается с разными таймаутами намеренно:
    //   Serial2-ветка (#ifndef SAMOVAR_USE_RMVK): 15000 мс (пакеты идут пассивно, нужен запас);
    //   RMVK-ветка   (#else):                      5000 мс (опрос активный, детект быстрее).
    // Таймаут здесь (15000 мс) выставлен с запасом поверх обоих значений.
    if (!reg_online && last_reg_online > 0 && (millis() - last_reg_online) > 15000UL && !current_power_mode_is(POWER_SLEEP_MODE)) {
      power_err_cnt++;
      if (power_err_cnt == 2) {
        SendMsg(("Нет связи с регулятором!"), ALARM_MSG);
      }
      if (power_err_cnt > 6) {
        request_emergency_stop("Аварийное отключение! Нет связи с регулятором нагрева.");
      }
      return;
    }

    // 2) Проверим, что заданное напряжение/мощность не сильно отличается от реального
    // (наличие связи с регулятором, пробой семистора и т.п.)
    if (current_power_mode_is(POWER_WORK_MODE) && current_power_volt > 0 && target_power_volt > 0 &&
        abs((current_power_volt - target_power_volt) / target_power_volt) > 0.2f) {
      power_err_cnt++;
      //if (power_err_cnt == 2) SendMsg(("Ошибка регулятора!"), ALARM_MSG);
      if (power_err_cnt > 6) set_current_power(target_power_volt);
      if (power_err_cnt > 12) {
        request_emergency_stop("Аварийное отключение! Ошибка управления нагревателем.");
      }
      return;
    }
  }
#endif
  power_err_cnt = 0;
}


//получаем текущие параметры работы регулятора напряжения
void get_current_power() {
  if (!PowerOn) {
    current_power_volt = 0;
    target_power_volt = 0;
    set_current_power_mode_value("N");
    current_power_p = 0;
    return;
  }
  if (current_power_mode_is(POWER_SLEEP_MODE)) {
    current_power_volt = 0;
    target_power_volt = 0;
    current_power_p = 0;
    return;
  }
#ifndef SAMOVAR_USE_SEM_AVR
  //Считаем мощность V*V*K/R, K = 0,98~1
  current_power_p = current_power_volt * current_power_volt / SamSetup.HeaterResistant;
#else
  current_power_p = target_power_volt;
#endif
}

//устанавливаем напряжение для регулятора напряжения
void set_current_power(float Volt) {
  if (!PowerOn) return;
#ifdef __SAMOVAR_DEBUG
  WriteConsoleLog("Set current power =" + (String)Volt);
#endif
#ifdef SAMOVAR_USE_SEM_AVR
  float maxPower = SamSetup.HeaterResistant > 1 ? (230.0f * 230.0f / SamSetup.HeaterResistant) : 4000.0f;
  if (Volt > maxPower) Volt = maxPower;
#else
  if (Volt > 230.0f) Volt = 230.0f;
#endif
  //vTaskDelay(100 / portTICK_PERIOD_MS); 5.13
#ifndef SAMOVAR_USE_SEM_AVR
  if (Volt < 40) {
#else
  if (Volt < 100) {
#endif
    set_power_mode(POWER_SLEEP_MODE);
    target_power_volt = 0;  // Обнуляем целевое напряжение при переходе в SLEEP режим
    return;
  } else {
    set_power_mode(POWER_WORK_MODE);
    //vTaskDelay(100/portTICK_PERIOD_MS);
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
    else
      Cmd = "";
    Cmd = Cmd + (String)V;
    vTaskDelay(RMVK_READ_DELAY / 10 / portTICK_PERIOD_MS);
    sem_avr_print_samovar_command("+VS=");
    Serial2.print(Cmd);
    Serial2.print("\r");
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

void set_power_mode(String Mode) {
  if (current_power_mode_is(Mode)) return;
  set_current_power_mode_value(Mode);

  // Обнуляем показатели питания при переходе в SLEEP режим
  if (Mode == POWER_SLEEP_MODE) {
    target_power_volt = 0;
    current_power_volt = 0;
    current_power_p = 0;
  }

  vTaskDelay(50 / portTICK_PERIOD_MS);
#ifdef SAMOVAR_USE_RMVK
  if (Mode == POWER_SLEEP_MODE) {
#ifdef SAMOVAR_USE_SEM_AVR
    if (xSemaphoreTake(xSemaphoreAVR, (TickType_t)((RMVK_DEFAULT_READ_TIMEOUT * 3) / portTICK_RATE_MS)) == pdTRUE) {
      vTaskDelay(RMVK_READ_DELAY / 10 / portTICK_PERIOD_MS);
      sem_avr_print_samovar_command("+ON=0\r");
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
      sem_avr_print_samovar_command("+ON=1\r");
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

unsigned int hexToDec(String hexString) {
  unsigned int decValue = 0;
  int nextInt;

  for (uint8_t i = 0; i < hexString.length(); i++) {

    nextInt = int(hexString.charAt(i));
    if (nextInt >= 48 && nextInt <= 57) nextInt = map(nextInt, 48, 57, 0, 9);
    if (nextInt >= 65 && nextInt <= 70) nextInt = map(nextInt, 65, 70, 10, 15);
    if (nextInt >= 97 && nextInt <= 102) nextInt = map(nextInt, 97, 102, 10, 15);
    nextInt = constrain(nextInt, 0, 15);

    decValue = (decValue * 16) + nextInt;
  }

  return decValue;
}
#endif
