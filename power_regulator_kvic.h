#pragma once

static inline void commit_kvic_power_response(const PowerRegulatorTelemetry& parsed) {
  // Ток валиден по факту разбора пакета; target/mode применяем только если валидны
  // (best-effort). reg_online держим по факту получения пакета.
  current_power_volt = parsed.currentValue;
  if (parsed.hasTarget) target_power_volt = parsed.targetValue;
  if (parsed.hasMode) set_current_power_mode_value(String(parsed.mode));
  mark_power_regulator_online();
}

void triggerPowerStatus(void *parameter) {
  static String buffer;
  const uint16_t MAX_BUFFER_SIZE = 50; // Ограничение размера буфера (5 пакетов по 9 символов + запас)
  while (true) {
    process_pending_power_request();
    ulTaskNotifyTake(pdTRUE, 500 / portTICK_PERIOD_MS);
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

                PowerRegulatorTelemetry parsed = {};
                NumericParseResult result = parse_kvic_power_response(data.c_str(), parsed);
                if (result.ok()) {
                    commit_kvic_power_response(parsed);
                    packetFound = true;
                    POWER_DEBUG_LOG(Serial.println("KVIC: " + data));
                } else {
                    report_power_response_error("KVIC", result);
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

inline bool apply_regulator_voltage_blocking(float Volt, uint64_t powerGeneration) {
  POWER_DEBUG_LOG(WriteConsoleLog("Set current power =" + (String)Volt));
  vTaskDelay(100 / portTICK_PERIOD_MS);
  String hexString = String((int)(Volt * 10), HEX);
  const String command = "S" + hexString + "\r";
  if (!heater_uart_enqueue(
        UART_NUM_2,
        command.c_str(),
        command.length(),
        powerGeneration,
        true
      )) return false;
  target_power_volt = Volt;
  return true;
}

inline bool apply_regulator_mode_blocking(SafetyRegulatorMode mode, uint64_t powerGeneration) {
  const String Mode = regulator_mode_text(mode);
  if (Mode.length() == 0) return false;
  vTaskDelay(50 / portTICK_PERIOD_MS);
  const String command = "M" + Mode + "\r";
  if (!heater_uart_enqueue(
        UART_NUM_2,
        command.c_str(),
        command.length(),
        powerGeneration,
        mode != SAFETY_REGULATOR_MODE_SLEEP
      )) return false;
  vTaskDelay(300 / portTICK_PERIOD_MS);
  // [T14 п.29] Занятый лок -> false, но железо команду уже приняло: это не
  // отказ регулятора. Повтор записи кэша откладываем на process_pending_power_request().
  if (!set_current_power_mode_value(Mode)) arm_pending_power_mode_retry(mode);
  if (mode == SAFETY_REGULATOR_MODE_SLEEP) {
    target_power_volt = 0;
    current_power_volt = 0;
    current_power_p = 0;
  }
  return true;
}
