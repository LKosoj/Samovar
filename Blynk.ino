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

BLYNK_READ(V1) {
  static bool inReadHandler = false;
  if (inReadHandler) return;
  inReadHandler = true;
  Blynk.virtualWrite(V1, PipeSensor.avgTemp);
  inReadHandler = false;
}

BLYNK_READ(V25) {
  static bool inReadHandler = false;
  if (inReadHandler) return;
  inReadHandler = true;
  Blynk.virtualWrite(V25, ACPSensor.avgTemp);
  inReadHandler = false;
}

BLYNK_READ(V2) {
  static bool inReadHandler = false;
  if (inReadHandler) return;
  inReadHandler = true;
  Blynk.virtualWrite(V2, WthdrwlProgress);
  inReadHandler = false;
}

BLYNK_READ(V5) {
  static bool inReadHandler = false;
  if (inReadHandler) return;
  inReadHandler = true;
  Blynk.virtualWrite(V5, bme_pressure);
  inReadHandler = false;
}

BLYNK_READ(V6) {
  static bool inReadHandler = false;
  if (inReadHandler) return;
  inReadHandler = true;
  Blynk.virtualWrite(V6, WaterSensor.avgTemp);
  inReadHandler = false;
}

BLYNK_READ(V7) {
  static bool inReadHandler = false;
  if (inReadHandler) return;
  inReadHandler = true;
  Blynk.virtualWrite(V7, TankSensor.avgTemp);
  inReadHandler = false;
}

BLYNK_READ(V8) {
  static bool inReadHandler = false;
  if (inReadHandler) return;
  inReadHandler = true;
  Blynk.virtualWrite(V8, get_liquid_volume());
  inReadHandler = false;
}

BLYNK_READ(V9) {
  static bool inReadHandler = false;
  if (inReadHandler) return;
  inReadHandler = true;
  Blynk.virtualWrite(V9, ActualVolumePerHour);
  inReadHandler = false;
}

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

BLYNK_READ(V15) {
  static bool inReadHandler = false;
  if (inReadHandler) return;
  inReadHandler = true;
  Blynk.virtualWrite(V15, ipst);
  inReadHandler = false;
}

BLYNK_READ(V19) {
  static bool inReadHandler = false;
  if (inReadHandler) return;
  inReadHandler = true;
  Blynk.virtualWrite(V19, SAMOVAR_VERSION);
  inReadHandler = false;
}

BLYNK_READ(V20) {
  static bool inReadHandler = false;
  if (inReadHandler) return;
  inReadHandler = true;
  Blynk.virtualWrite(V20, Samovar_Mode);
  inReadHandler = false;
}

BLYNK_READ(V24) {
  static bool inReadHandler = false;
  if (inReadHandler) return;
  inReadHandler = true;
  Blynk.virtualWrite(V24, serialize_program_for_mode(Samovar_Mode));
  inReadHandler = false;
}

#if defined(USE_PRESSURE_XGZ) || defined(USE_PRESSURE_MPX) || defined(USE_PRESSURE_1WIRE)
BLYNK_READ(V23) {
  static bool inReadHandler = false;
  if (inReadHandler) return;
  inReadHandler = true;
  Blynk.virtualWrite(V23, pressure_value);
  inReadHandler = false;
}
#endif

#ifdef SAMOVAR_USE_POWER
BLYNK_READ(V21) {
  static bool inReadHandler = false;
  if (inReadHandler) return;
  inReadHandler = true;
  Blynk.virtualWrite(V21, "Тек:" + (String)current_power_volt + " Цель:" + (String)target_power_volt);
  inReadHandler = false;
}
#endif

#ifdef SAMOVAR_USE_POWER
BLYNK_READ(V16) {
  static bool inReadHandler = false;
  if (inReadHandler) return;
  inReadHandler = true;
  Blynk.virtualWrite(V16, target_power_volt);
  inReadHandler = false;
}

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

// ---------------------------------------------------------------------------
// V27: телеметрия режима одним JSON для мобильных приложений (PIN_SPEC.md §9).
// Берётся тот же снимок, что и /ajax (captureAjaxTelemetrySnapshot, Samovar.ino),
// сериализатор читает ТОЛЬКО снимок. Ключи короткие: буфер BLYNK_MAX_SENDBYTES.
// Поля, которых нет в сборке/режиме, не пишутся - приложение показывает то, что пришло.
// ---------------------------------------------------------------------------
static void write_blynk_mode_json(Print& out, const AjaxTelemetrySnapshot& s) {
  bool first = true;
  out.print('{');
  jsonFieldRaw(out, first, "st", s.statusInt);
  jsonFieldRaw(out, first, "pn", s.programIndex + 1);
  jsonFieldString(out, first, "pt", s.programType);
  if (s.hasAlcohol) {
    jsonFieldFloat(out, first, "alc", s.alcohol, 2);
    jsonFieldFloat(out, first, "salc", s.steamAlcohol, 2);
  }
  if (s.hasTimePrediction) {
    jsonFieldBool(out, first, "rpa", s.rowPredictionAvailable);
    jsonFieldBool(out, first, "ppa", s.processPredictionAvailable);
    if (s.rowPredictionAvailable) {
      jsonFieldRaw(out, first, "tr", s.timeRemaining);
      jsonFieldRaw(out, first, "rtt", s.rowPredictedTotalTime);
    }
    if (s.processPredictionAvailable) {
      jsonFieldRaw(out, first, "ptr", s.processRemainingTime);
      jsonFieldRaw(out, first, "tt", s.totalTime);
    }
  }
  jsonFieldRaw(out, first, "det", s.detectorStatus);
  jsonFieldFloat(out, first, "dtr", s.detectorTrend, 3);
  jsonFieldBool(out, first, "boil", s.boilingDetected);
  jsonFieldRaw(out, first, "bev", s.boilingEvidence);
  jsonFieldBool(out, first, "bps", s.boilingPrecisionSensorConfigured);
  jsonFieldBool(out, first, "wauto", s.bkWaterAuto);
  jsonFieldFloat(out, first, "wsp", s.bkSteamSetpoint, 1);
#ifdef USE_WATER_PUMP
  jsonFieldRaw(out, first, "wpwm", s.waterPumpSpeed);
#endif
#ifdef USE_WATERSENSOR
  jsonFieldFloat(out, first, "wf", s.waterFlowRate, 2);
  jsonFieldRaw(out, first, "wft", s.waterFlowTotalMl);
#endif
#if defined(USE_PRESSURE_XGZ) || defined(USE_PRESSURE_1WIRE) || defined(USE_PRESSURE_MPX)
  jsonFieldFloat(out, first, "prvl", s.pressure, 2);
#endif
  jsonFieldFloat(out, first, "isspd", s.i2cStepperSpeed, 3);
  jsonFieldBool(out, first, "bpause", s.beerPaused);
  jsonFieldRaw(out, first, "order", s.beerBrewOrder);
  jsonFieldBool(out, first, "mixer", s.mixer);
  jsonFieldFloat(out, first, "ph", s.cheesePh, 2);
  jsonFieldBool(out, first, "phv", s.cheesePhValid);
  out.print('}');
}

BLYNK_READ(V27) {
  static bool inReadHandler = false;
  if (inReadHandler) return;
  inReadHandler = true;
  {
    AjaxTelemetrySnapshot snapshot;
    // Курсор сообщений 0: лента событий здесь не нужна, но снимок общий с /ajax.
    if (captureAjaxTelemetrySnapshot(0, snapshot) == RUNTIME_AJAX_SNAPSHOT_OK) {
      String json;
      json.reserve(512);
      JsonStringPrint sink(json);
      write_blynk_mode_json(sink, snapshot);
      Blynk.virtualWrite(V27, json);
    }
  }
  inReadHandler = false;
}

// ---------------------------------------------------------------------------
// V28..V32: команды веб-форм режимов, которых не было в Blynk. Разбор значений и
// проверки те же, что в web_command() (WebServer.ino); отказы уходят предупреждением
// в V26 через SendMsg, т.к. HTTP-кода ответа у Blynk нет.
// ---------------------------------------------------------------------------
// queue_pending_flag() - static в WebServer.ino (идёт в склейке .ino ПОСЛЕ этого файла),
// а автопрототип для функции с аргументом по умолчанию сборщик не вставляет. Объявляем
// сами без умолчания и зовём с явным bypassBarrier=false.
static bool queue_pending_flag(volatile bool& flag, bool bypassBarrier);

static inline void report_blynk_refusal(uint8_t virtualPin, const char* reason) {
  String message = "Blynk V";
  message += virtualPin;
  message += ": ";
  message += reason;
  SendMsg(message, WARNING_MSG);
}

// ШИМ насоса воды 0..1023 (= /command watert).
BLYNK_WRITE(V28) {
  if (mode_switch_in_progress()) return;
  uint16_t waterPwm = 0;
  NumericParseResult result = parse_control_water_pwm(param.asStr(), waterPwm);
  if (!result.ok()) {
    report_blynk_numeric_error(28, result);
    return;
  }
  if (Samovar_Mode == SAMOVAR_BK_MODE && PowerOn && waterPwm < PWM_LOW_VALUE * 10) {
    report_blynk_refusal(28, "PWM_TOO_LOW");
    return;
  }
  if (!queue_pending_value(pending_water_temp_flag, pending_water_temp_value, waterPwm)) {
    report_blynk_refusal(28, "BUSY");
  }
}

// Скорость подачи НБК: л/ч, 0 = стоп, 8000/9000 = шаг вниз/вверх (= /command pnbk).
BLYNK_WRITE(V29) {
  if (mode_switch_in_progress()) return;
  ControlNbkCommand nbkCommand = {};
  NumericParseResult result = parse_control_nbk(
      param.asStr(), SamSetup.StepperStepMlI2C, nbkCommand);
  if (result.ok() && nbkCommand.kind != CONTROL_NBK_STOP && SamSetup.StepperStepMlI2C == 0) {
    result = numeric_parse_result(NUMERIC_PARSE_INVALID_ARGUMENT);
  }
  if (!result.ok()) {
    report_blynk_numeric_error(29, result);
    return;
  }
  if (!PowerOn) {
    report_blynk_refusal(29, "POWER_OFF");
    return;
  }
  if (!queue_pending_nbk(nbkCommand)) {
    report_blynk_refusal(29, "BUSY");
  }
}

// Автомат воды БК, только включение значением 1 (= /command waterauto).
BLYNK_WRITE(V30) {
  if (mode_switch_in_progress()) return;
  bool state = false;
  NumericParseResult result = parse_exact_bool(param.asStr(), state);
  if (result.ok() && !state) result = numeric_parse_result(NUMERIC_PARSE_NOT_ALLOWED);
  if (!result.ok()) {
    report_blynk_numeric_error(30, result);
    return;
  }
#ifndef USE_WATER_PUMP
  report_blynk_refusal(30, "NO_PUMP");
#else
  if (Samovar_Mode != SAMOVAR_BK_MODE || !PowerOn || ProgramNum >= ProgramLen) {
    report_blynk_refusal(30, "NOT_RUNNING");
    return;
  }
  if (program[ProgramNum].Temp == 0) {
    report_blynk_refusal(30, "NO_SETPOINT");
    return;
  }
  if (!queue_pending_flag(pending_water_auto_flag, false)) {
    report_blynk_refusal(30, "BUSY");
  }
#endif
}

// НБК: зафиксировать текущие параметры как оптимальные, значением 1 (= /command nbkopt).
BLYNK_WRITE(V31) {
  if (mode_switch_in_progress()) return;
  bool state = false;
  NumericParseResult result = parse_exact_bool(param.asStr(), state);
  if (result.ok() && !state) result = numeric_parse_result(NUMERIC_PARSE_NOT_ALLOWED);
  if (!result.ok()) {
    report_blynk_numeric_error(31, result);
    return;
  }
  if (!PowerOn) {
    report_blynk_refusal(31, "POWER_OFF");
    return;
  }
  if (!queue_pending_flag(pending_nbkopt_flag, false)) {
    report_blynk_refusal(31, "BUSY");
  }
}

// Явное питание: 1 - включить (если выключено), 0 - всегда выключить (= /command power=0|1).
// В отличие от тумблера V4 направление задано явно - безопасно при потере связи.
BLYNK_WRITE(V32) {
  if (mode_switch_in_progress()) return;
  bool state = false;
  NumericParseResult result = parse_exact_bool(param.asStr(), state);
  if (!result.ok()) {
    report_blynk_numeric_error(32, result);
    return;
  }
  SamovarCommands command = SAMOVAR_NONE;
  if (state) {
    if (!PowerOn) command = mode_power_on_command(Samovar_Mode);
  } else {
    command = SAMOVAR_POWER_OFF;
  }
  if (command != SAMOVAR_NONE && !queue_samovar_command(command)) {
    report_blynk_refusal(32, "BUSY");
  }
}

#endif
