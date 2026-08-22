#pragma once

void triggerPowerStatus(void *parameter) {
  String resp;
  while (true) {
    process_pending_power_request();
    if (PowerOn) {
      current_power_volt = RMVK_get_out_voltge();
      vTaskDelay(RMVK_READ_DELAY / portTICK_PERIOD_MS);
      uint16_t v = RMVK_get_store_out_voltge();
      vTaskDelay(RMVK_READ_DELAY / portTICK_PERIOD_MS);
      rmvk.on = RMVK_get_state() > 0;
      if (v != 0) {
        target_power_volt = v;
      }
    }
    // Если давно не было ответа от регулятора — считаем его оффлайн.
    // Таймаут с запасом, т.к. запросы идут пачкой и с задержками.
    if (reg_online && last_reg_online > 0 && (millis() - last_reg_online) > 5000UL) {
      reg_online = false;
    }
    ulTaskNotifyTake(pdTRUE, RMVK_READ_DELAY / 5 / portTICK_PERIOD_MS);
  }
}

inline bool apply_regulator_voltage_blocking(float Volt, uint64_t powerGeneration) {
  POWER_DEBUG_LOG(WriteConsoleLog("Set current power =" + (String)Volt));
  vTaskDelay(100 / portTICK_PERIOD_MS);
  if (RMVK_set_out_voltge(Volt, powerGeneration) == RMVK_ERROR) return false;
  target_power_volt = Volt;
  return true;
}

inline bool apply_regulator_mode_blocking(SafetyRegulatorMode mode, uint64_t powerGeneration) {
  const String Mode = regulator_mode_text(mode);
  if (Mode.length() == 0) return false;
  vTaskDelay(50 / portTICK_PERIOD_MS);
  if (mode == SAFETY_REGULATOR_MODE_SLEEP) {
    if (RMVK_set_on(0, 0) == RMVK_ERROR) return false;
  } else if (mode == SAFETY_REGULATOR_MODE_SPEED) {
    POWER_DEBUG_LOG(WriteConsoleLog("Set power mode=" + Mode));
    if (RMVK_set_on(1, powerGeneration) == RMVK_ERROR) return false;
    vTaskDelay(RMVK_READ_DELAY / portTICK_PERIOD_MS);
    if (RMVK_set_out_voltge(MAX_VOLTAGE, powerGeneration) == RMVK_ERROR) return false;
    vTaskDelay(RMVK_READ_DELAY / portTICK_PERIOD_MS);
  }
  set_current_power_mode_value(Mode);
  if (mode == SAFETY_REGULATOR_MODE_SLEEP) {
    target_power_volt = 0;
    current_power_volt = 0;
    current_power_p = 0;
  }
  return true;
}
