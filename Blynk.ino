#include "Samovar.h"
#include "control_numeric_input.h"
#include "samovar_api.h"
#include "program_io.h"
#ifdef SAMOVAR_USE_BLYNK
#include <BlynkSimpleEsp32.h>

static inline void report_blynk_numeric_error(
    uint8_t virtualPin,
    NumericParseResult result) {
  String message = "Blynk V";
  message += virtualPin;
  message += ": ";
  message += numeric_parse_error_code(result.error);
  SendMsg(message, WARNING_MSG);
}

// [П3] Тривиальный BLYNK_READ: тело — ровно одна Blynk.virtualWrite(pin, expr),
// обёрнутая в стандартный guard от повторного входа. static bool живёт внутри
// РАЗВОРОТА макроса, поэтому у каждого пина остаётся СВОЙ независимый флаг,
// как и раньше, а не один общий на все обработчики.
// НЕ использовать для обработчиков с несколькими virtualWrite, с vTaskDelay
// между записями, с побочной логикой (копирование строк под runtime_state_lock,
// ветвления) - и для тех, чью буквальную сигнатуру "BLYNK_READ(pin)" ищут
// smoke-тесты через extract_function_body (см. BLYNK_READ(V24) и
// tools/smoke_program_io_contract.py - его нельзя завернуть в этот макрос).
// expr не должен содержать запятую верхнего уровня (не в скобках) - это один
// аргумент макроса; такое выражение оборачивать в скобки или не сворачивать.
#define BLYNK_READ_SIMPLE(pin, expr) \
  BLYNK_READ(pin) { \
    static bool inReadHandler = false; \
    if (inReadHandler) return; \
    inReadHandler = true; \
    Blynk.virtualWrite(pin, expr); \
    inReadHandler = false; \
  }

#ifdef USE_LUA
WidgetTerminal terminal(V22);

BLYNK_WRITE(V22) {
  if (mode_switch_in_progress()) return;
  String lstr = param.asStr();  // assigning incoming value from pin V22 to a variable
  terminal.println(lstr);
  lstr = run_lua_string(lstr);
  if (lstr.length() > 0) {
    terminal.println("ERR in lua: " + lstr);
  }
  else {
    terminal.println(F("Lua queued"));
  }
  terminal.flush();
}
#endif

BLYNK_READ(V0) {
  static bool inReadHandler = false;
  if (inReadHandler) return; // Предотвращаем рекурсию
  inReadHandler = true;
  
  vTaskDelay(2 / portTICK_PERIOD_MS);
  Blynk.virtualWrite(V0, SteamSensor.avgTemp);
  vTaskDelay(2 / portTICK_PERIOD_MS);
  Blynk.virtualWrite(V4, PowerOn);
  int i;
  int k;
  if (startval > 0 && startval < 5)
    i = 1;
  else
    i = 0;
  Blynk.virtualWrite(V3, i);
  vTaskDelay(2 / portTICK_PERIOD_MS);
  if (PauseOn)
    k = 1;
  else
    k = 0;
  Blynk.virtualWrite(V13, k);
  
  inReadHandler = false;
}

BLYNK_READ_SIMPLE(V1, PipeSensor.avgTemp)

BLYNK_READ_SIMPLE(V25, ACPSensor.avgTemp)

BLYNK_READ_SIMPLE(V2, WthdrwlProgress)

BLYNK_READ_SIMPLE(V5, bme_pressure)

BLYNK_READ_SIMPLE(V6, WaterSensor.avgTemp)

BLYNK_READ_SIMPLE(V7, TankSensor.avgTemp)

BLYNK_READ_SIMPLE(V8, get_liquid_volume())

BLYNK_READ_SIMPLE(V9, ActualVolumePerHour)

BLYNK_READ(V10) {
  static bool inReadHandler = false;
  if (inReadHandler) return;
  inReadHandler = true;
  // [C-1] Читаем строки времени под замком.
  {
    String timesCopy;
    bool locked = runtime_state_lock(pdMS_TO_TICKS(50));
    if (locked) {
      timesCopy = WthdrwTimeS + "; " + WthdrwTimeAllS;
      runtime_state_unlock(true);
    }
    Blynk.virtualWrite(V10, timesCopy);
  }
  inReadHandler = false;
}

BLYNK_READ(V11) {
  static bool inReadHandler = false;
  if (inReadHandler) return;
  inReadHandler = true;
  // [C-1] Читаем строку StrCrt под замком.
  {
    String strCrtCopy;
    bool locked = runtime_state_lock(pdMS_TO_TICKS(50));
    if (locked) {
      strCrtCopy = StrCrt;
      runtime_state_unlock(true);
    }
    Blynk.virtualWrite(V11, strCrtCopy);
  }
  inReadHandler = false;
}

BLYNK_READ(V14) {
  static bool inReadHandler = false;
  if (inReadHandler) return;
  inReadHandler = true;
  // [C-2] Читаем кэш SamovarStatus под замком; FSM продвигает его раз в секунду
  // из секундного гейта triggerSysTicker (core 0) через tick_status_fsm().
  {
    String statusCopy;
    bool locked = runtime_state_lock(pdMS_TO_TICKS(50));
    if (locked) {
      statusCopy = SamovarStatus;
      runtime_state_unlock(true);
    }
    Blynk.virtualWrite(V14, statusCopy);
  }
  inReadHandler = false;
}

BLYNK_READ_SIMPLE(V15, ipst)

BLYNK_READ_SIMPLE(V19, SAMOVAR_VERSION)

BLYNK_READ_SIMPLE(V20, Samovar_Mode)

BLYNK_READ(V24) {
  static bool inReadHandler = false;
  if (inReadHandler) return;
  inReadHandler = true;
  Blynk.virtualWrite(V24, serialize_program_for_mode(Samovar_Mode));
  inReadHandler = false;
}

#if defined(USE_PRESSURE_XGZ) || defined(USE_PRESSURE_MPX) || defined(USE_PRESSURE_1WIRE)
BLYNK_READ_SIMPLE(V23, pressure_value)
#endif

#ifdef SAMOVAR_USE_POWER
BLYNK_READ_SIMPLE(V21, "Тек:" + (String)current_power_volt + " Цель:" + (String)target_power_volt)
#endif

#ifdef SAMOVAR_USE_POWER
BLYNK_READ_SIMPLE(V16, target_power_volt)

BLYNK_WRITE(V16) {
  if (mode_switch_in_progress()) return;
  float maxPower = 0.0f;
#ifdef SAMOVAR_USE_SEM_AVR
  const bool semBuild = true;
#else
  const bool semBuild = false;
#endif
  NumericParseResult result = control_power_input_max(
      semBuild, SamSetup.HeaterResistant, maxPower);
  float value = 0.0f;
  if (result.ok()) result = parse_control_power(param.asStr(), maxPower, value);
  if (!result.ok()) {
    report_blynk_numeric_error(16, result);
    return;
  }
  set_current_power(value);
}
#endif

BLYNK_WRITE(V17) {
  if (mode_switch_in_progress()) return;
  // Ноль останавливает отбор напрямую через stopService(), в обход set_pump_speed():
  // get_speed_from_rate(0) зажимает результат до 1 (минимальная скорость мотора), а
  // set_pump_speed(1, true) внутри себя зовёт stopService() и тут же startService() -
  // насос не останавливается, а ползёт на минимальной скорости. Нулевой вход разбираем
  // ДО строгого парсера, который rate<=0 просто отвергает как недопустимое значение.
  // Тот же статус, что проверяет set_pump_speed() (logic.h) - шаговый мотор ещё
  // используют калибровка насоса, HopStepperStep() и самотест, V17=0 не должен
  // обрывать их вне отбора. После остановки обнуляем скорость/производительность,
  // как и другие точки остановки отбора (WebServer.ino, alarm.h, I2CStepper.h).
  float rate = 0.0f;
  NumericParseResult result = parse_finite_float(param.asStr(), rate);
  if (result.ok() && rate == 0.0f) {
    if (SamovarStatusInt == SAMOVAR_STATUS_RECT_WITHDRAWAL || SamovarStatusInt == SAMOVAR_STATUS_RECT_AUTOPAUSE || SamovarStatusInt == SAMOVAR_STATUS_PAUSED) {
      stopService();
      CurrrentStepperSpeed = 0;
      ActualVolumePerHour = 0;
    }
    return;
  }
  uint16_t stepSpeed = 0;
  result = parse_control_rate_steps(
      param.asStr(), SamSetup.StepperStepMl, stepSpeed);
  if (!result.ok()) {
    report_blynk_numeric_error(17, result);
    return;
  }
  set_pump_speed(stepSpeed, true);
}

BLYNK_WRITE(V18) {
  if (mode_switch_in_progress()) return;
  set_body_temp();
}

BLYNK_WRITE(V12) {
  if (mode_switch_in_progress()) return;
  bool state = false;
  NumericParseResult result = parse_exact_bool(param.asStr(), state);
  if (!result.ok()) {
    report_blynk_numeric_error(12, result);
    return;
  }
  if (!PowerOn) return;
  if (state) {
    SamovarCommands command = mode_start_command(Samovar_Mode);
    if (!queue_samovar_command(command)) {
      SendMsg("Очередь команд занята: команда Blynk V12 не поставлена", WARNING_MSG);
    }
  }
}

BLYNK_WRITE(V13) {
  if (mode_switch_in_progress()) return;
  // [P7 п.4][P2 п.6][Ревью] PauseOn (ректификация) ИЛИ beerManualPause (пиво) - см.
  // Menu.ino menu_pause(). Пауза/возобновление - через общие хелперы enter_manual_pause()/
  // resume_from_pause() (logic.h), симметрично остальным точкам входа.
  if (PauseOn || beerManualPause) resume_from_pause();
  else enter_manual_pause();
}

BLYNK_WRITE(V3) {
  if (mode_switch_in_progress()) return;
  bool value = false;
  NumericParseResult result = parse_exact_bool(param.asStr(), value);
  if (!result.ok()) {
    report_blynk_numeric_error(3, result);
    return;
  }
  if (value && PowerOn) {
    menu_samovar_start();
  } else {
    if (!queue_samovar_reset_command()) SendMsg("Очередь команд занята: reset из Blynk не поставлен", WARNING_MSG);
  }
}
BLYNK_WRITE(V4) {
  if (mode_switch_in_progress()) return;
  SamovarCommands command = SAMOVAR_POWER;
  if (!PowerOn) command = mode_power_on_command(Samovar_Mode);
  if (!queue_samovar_command(command)) {
    SendMsg("Очередь команд занята: команда Blynk V4 не поставлена", WARNING_MSG);
  }
  //set_power(Value4);
}

#endif
