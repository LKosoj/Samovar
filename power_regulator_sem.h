#pragma once

void clear_serial_in_buff() { // Быстрая очистка буфера (максимум 100 символов)
  uint8_t cleared = 0;
  while (Serial2.available() && cleared < 100) {
      Serial2.read();
      cleared++;
  }
}

static constexpr const char* SEM_AVR_SAMOVAR_AT_PREFIX = "\xD0\x90\xD0\xA2";

static inline void sem_avr_print_samovar_command(const char* suffix) {
  // SEM_AVR distinguishes Samovar power commands from RMVK voltage commands by
  // the legacy UTF-8 Cyrillic A/T prefix bytes. Keep the bytes explicit.
  Serial2.print(SEM_AVR_SAMOVAR_AT_PREFIX);
  Serial2.print(suffix);
}

static inline bool sem_avr_write_samovar_command(
  const char* suffix,
  uint64_t powerGeneration,
  bool energizing
) {
  char command[POWER_UART_COMMAND_MAX];
  const int length = snprintf(
    command,
    sizeof(command),
    "%s%s",
    SEM_AVR_SAMOVAR_AT_PREFIX,
    suffix
  );
  return length > 0 && (size_t)length < sizeof(command) &&
         heater_uart_enqueue(
           UART_NUM_2,
           command,
           (size_t)length,
           powerGeneration,
           energizing
         );
}

static inline void commit_sem_power_mode_response(char mode) {
  set_current_power_mode_value(String(mode));
  mark_power_regulator_online();
}

static inline void commit_sem_current_power_response(uint16_t value) {
  current_power_volt = value;
  mark_power_regulator_online();
}

static inline void commit_sem_target_power_response(uint16_t value) {
  // Транзиентный «0» от +VS? игнорируем (HEAD-семантика): не обнуляем уставку,
  // но связь считаем живой.
  if (value != 0) target_power_volt = value;
  mark_power_regulator_online();
}

// Общий скелет одного обмена с регулятором: взять семафор, прочистить буфер,
// отправить команду (print), дождаться ответа максимум 2 попытками и разобрать
// его (handle). Пост-задержка после блока выполняется ВСЕГДА, даже если семафор
// занять не удалось — это сохранено намеренно.
template <typename SendFn, typename Handle>
static inline void sem_query_response(SendFn print, Handle handle) {
  String resp;
  if (xSemaphoreTake(xSemaphoreAVR, (TickType_t)((RMVK_DEFAULT_READ_TIMEOUT) / portTICK_RATE_MS)) == pdTRUE) {
    vTaskDelay(RMVK_READ_DELAY / 10 / portTICK_PERIOD_MS);
    clear_serial_in_buff();
    vTaskDelay(5 / portTICK_RATE_MS);
    print();
    for (int i = 0; i < 2; i++) {
      vTaskDelay(RMVK_READ_DELAY / portTICK_RATE_MS);
      if (Serial2.available()) {
        resp = Serial2.readStringUntil('\r');
        handle(resp);
        break;
      }
    }
    xSemaphoreGive(xSemaphoreAVR);
  }
  vTaskDelay(RMVK_READ_DELAY / 5 / portTICK_PERIOD_MS);
}

void triggerPowerStatus(void *parameter) {
  while (true) {
    process_pending_power_request();
    if (PowerOn) {
      sem_query_response(
        [] { sem_avr_print_samovar_command("+SS?\r"); },
        [](const String& resp) {
          char mode = '\0';
          NumericParseResult result = parse_sem_power_mode_response(resp.c_str(), mode);
          if (result.ok()) commit_sem_power_mode_response(mode);
          else report_power_response_error("SEM +SS?", result);
          POWER_DEBUG_LOG(if (result.ok()) WriteConsoleLog("CPM=" + get_current_power_mode_value()));
        }
      );
      sem_query_response(
        [] { sem_avr_print_samovar_command("+VO?\r"); },
        [](const String& resp) {
          POWER_DEBUG_LOG(WriteConsoleLog("CPV=" + resp));
          uint16_t value = 0;
          NumericParseResult result = parse_sem_power_value_response(
              resp.c_str(), SamSetup.HeaterResistant, value, /*telemetry=*/true);
          if (result.ok()) commit_sem_current_power_response(value);
          else report_power_response_error("SEM +VO?", result);
        }
      );
      sem_query_response(
        [] { sem_avr_print_samovar_command("+VS?\r"); },
        [](const String& resp) {
          POWER_DEBUG_LOG(WriteConsoleLog("TPV=" + resp));
          uint16_t value = 0;
          NumericParseResult result = parse_sem_power_value_response(
              resp.c_str(), SamSetup.HeaterResistant, value, /*telemetry=*/true);
          if (result.ok()) commit_sem_target_power_response(value);
          else report_power_response_error("SEM +VS?", result);
        }
      );
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
  if (xSemaphoreTake(xSemaphoreAVR, (TickType_t)((RMVK_DEFAULT_READ_TIMEOUT * 3) / portTICK_RATE_MS)) == pdTRUE) {
    String Cmd;
    int V = Volt;
    if (V < 100) Cmd = "0";
    else
      Cmd = "";
    Cmd = Cmd + (String)V;
    vTaskDelay(RMVK_READ_DELAY / 10 / portTICK_PERIOD_MS);
    const bool queued = sem_avr_write_samovar_command(
      (String("+VS=") + Cmd + "\r").c_str(),
      powerGeneration,
      true
    );
    vTaskDelay(RMVK_READ_DELAY / portTICK_PERIOD_MS);
    xSemaphoreGive(xSemaphoreAVR);
    if (!queued) return false;
  } else return false;
  target_power_volt = Volt;
  return true;
}

inline bool apply_regulator_mode_blocking(SafetyRegulatorMode mode, uint64_t powerGeneration) {
  const String Mode = regulator_mode_text(mode);
  if (Mode.length() == 0) return false;
  vTaskDelay(50 / portTICK_PERIOD_MS);
  if (mode == SAFETY_REGULATOR_MODE_SLEEP) {
    if (xSemaphoreTake(xSemaphoreAVR, (TickType_t)((RMVK_DEFAULT_READ_TIMEOUT * 3) / portTICK_RATE_MS)) == pdTRUE) {
      vTaskDelay(RMVK_READ_DELAY / 10 / portTICK_PERIOD_MS);
      const bool queued = sem_avr_write_samovar_command("+ON=0\r", 0, false);
      vTaskDelay(RMVK_READ_DELAY / portTICK_PERIOD_MS);
      xSemaphoreGive(xSemaphoreAVR);
      if (!queued) return false;
    } else return false;
  } else if (mode == SAFETY_REGULATOR_MODE_SPEED) {
    POWER_DEBUG_LOG(WriteConsoleLog("Set power mode=" + Mode));
    if (xSemaphoreTake(xSemaphoreAVR, (TickType_t)((RMVK_DEFAULT_READ_TIMEOUT * 7) / portTICK_RATE_MS)) == pdTRUE) {
      vTaskDelay(RMVK_READ_DELAY / 6 / portTICK_PERIOD_MS);
      const bool queued = sem_avr_write_samovar_command(
        "+ON=1\r", powerGeneration, true
      );
      vTaskDelay(RMVK_READ_DELAY / portTICK_PERIOD_MS);
      xSemaphoreGive(xSemaphoreAVR);
      if (!queued) return false;
    } else return false;
  }
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
