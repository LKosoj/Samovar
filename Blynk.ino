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

#ifdef SAMOVAR_USE_POWER
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
  // Причина простоя детектора (DetectorIdleReason) и настройки-выключатели: приложения
  // и сайт показывают то же, что index.htm (detectorIdleText в app.js).
  jsonFieldRaw(out, first, "di", s.detectorIdle);
  if (s.detectorIdle == DETECTOR_IDLE_STEAM_WAIT) {
    jsonFieldRaw(out, first, "dwl", s.detectorWaitLeftSec);
    jsonFieldFloat(out, first, "dws", s.detectorWaitSpan, 2);
  }
  jsonFieldBool(out, first, "ud", s.useDetector);
  jsonFieldBool(out, first, "ua", s.useAutoSpeed);
  jsonFieldBool(out, first, "boil", s.boilingDetected);
  jsonFieldRaw(out, first, "bev", s.boilingEvidence);
  jsonFieldBool(out, first, "bps", s.boilingPrecisionSensorConfigured);
  jsonFieldBool(out, first, "wauto", s.bkWaterAuto);
  jsonFieldFloat(out, first, "wsp", s.bkSteamSetpoint, 1);
  jsonFieldBool(out, first, "valve", s.valveOpen);
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
  jsonFieldBool(out, first, "sp", s.secondPumpEnabled);
  jsonFieldBool(out, first, "spr", s.secondPumpRunning);
  jsonFieldBool(out, first, "bpause", s.beerPaused);
  jsonFieldRaw(out, first, "order", s.beerBrewOrder);
  jsonFieldBool(out, first, "mixer", s.mixer);
  jsonFieldFloat(out, first, "ph", s.cheesePh, 2);
  jsonFieldBool(out, first, "phv", s.cheesePhValid);
  out.print('}');
}

static void blynk_push_v27() {
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

// ---------------------------------------------------------------------------
// V36: состояние плат I2CStepper (PIN_SPEC.md §13). Ключ "mixer"/"pump" есть только у
// платы, которая хоть раз ответила после старта: без плат пин не шлётся вовсе, а пропавшая
// плата приходит с present=0. Объект платы - тот же, что отдаёт /i2cstepper?cmd=status.
// ---------------------------------------------------------------------------
static void blynk_push_v36() {
  if (!i2cStepperMixer.everPresent && !i2cStepperPump.everPresent) return;
  String json;
  json.reserve(640);
  JsonStringPrint sink(json);
  sink.print("{\"cal\":");
  sink.print(I2CPumpCalibrating ? 1 : 0);
  if (i2cStepperMixer.everPresent) {
    sink.print(",\"mixer\":");
    write_i2c_stepper_json(sink, i2cStepperMixer);
  }
  if (i2cStepperPump.everPresent) {
    sink.print(",\"pump\":");
    write_i2c_stepper_json(sink, i2cStepperPump);
  }
  sink.print('}');
  Blynk.virtualWrite(V36, json);
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

// ---------------------------------------------------------------------------
// Push вместо опроса (2026-09). Раньше у виджетов проекта стоял frequency=5000: сервер
// раз в 5 с слал 21 команду «vr» одной пачкой, и вся пачка (21 обработчик BLYNK_READ,
// 24 отправки, задержки и захваты замков) выполнялась внутри одного Blynk.run(), т.е.
// одной итерации loop(). Теперь в эталонном проекте frequency=0 (PUSH), обработчиков
// BLYNK_READ нет, и прошивка отдаёт пины сама:
//  - быстрые пины (kBlynkFastPush) - раз в BLYNK_PUSH_PERIOD_MS, по BLYNK_PUSH_PER_TICK
//    штук за итерацию loop(), чтобы не было всплеска;
//  - медленные (blynk_push_slow) - когда значение изменилось, плюс все разом после
//    (пере)подключения (BLYNK_CONNECTED ниже) и раз в BLYNK_PUSH_SLOW_PERIOD_MS: сервер
//    стирает значения виджетов при синхронизации проекта из приложения и при своём
//    перезапуске, а прошивка об этом не узнаёт.
// Старые проекты с опросом продолжают присылать «vr»: библиотека их отбрасывает, а
// значения приходят push-ем с той же периодичностью. V26 (сообщения) и V15/V20-url
// при применении профиля шлются как раньше (Samovar.ino).
// blynk_push_tick() зовётся из tick_blynk() (Samovar.ino) под BlynkLockGuard после
// Blynk.run() - как и BLYNK_WRITE, всё здесь выполняется уже под этим локом.
// ---------------------------------------------------------------------------
#define BLYNK_PUSH_PERIOD_MS 5000UL
#define BLYNK_PUSH_PER_TICK 3
#define BLYNK_PUSH_SLOW_PERIOD_MS 60000UL

static bool s_blynkPushResendAll = true;

// Стейджинг-буферы V34 (строка лога) и V35 (начало сессии), см. T2 blynk-log-channel.md.
// Обе строки формируются в SysTicker/из точек старта процесса (в т.ч. синхронно из
// BLYNK_WRITE(V3), уже под BlynkLockGuard) и складываются здесь под portMUX_TYPE
// (по образцу waterPulseMux, runtime_helpers.h) - короткая атомарная копия между задачами
// разных ядер, без обращения к библиотеке Blynk из пишущей стороны. Реальная отправка -
// только из blynk_push_pending_log_line()/blynk_push_pending_session_start(), вызываемых
// из blynk_push_tick() (loop(), под BlynkLockGuard, взятым tick_blynk()).
// Честный худший случай V34 (T2-review-1.md, [Blynk.ino:366] / [Samovar.ino:752-790]):
// "5," (2) + sessionId uint32_t (10) + "," (1) + statusInt int16_t "-32768" (6) + "," (1)
// = 20 байт префикса;
// format_log_base_fields() (FS.ino): Crt "MM-DD HH:MM:SS" (14) + 4 датчика по
// format_float(,3) "-99999.000" (","+10=11 каждый, 44) + давление format_float(,2)
// "-99999.00" (","+9=10) + WRITE_PROGNUM_IN_LOG "," + (programNum+1) до 3 цифр (4) = 72;
// format_v34_tail_fields() (Samovar.ino), 18 полей через format_float с клампом ±99999
// (current_power_volt теперь тоже - см. фикс WARNING [Samovar.ino:759]): 9 float-полей на
// 2-3 знака по 10-11 байт (ACPSensor.avgTemp 11, ActualVolumePerHour 11,
// current_power_volt 10, WFflowRate 10, get_alcohol 10, get_steam_alcohol 10,
// pressure_value 10, target_fr 10, actual_fr 10 = 92) + temp_delta format_float(,3) (11)
// + detectorStatus/PackDens uint8_t до 3 цифр (","+3=4 каждый, 8) + event_code 0/1 (2)
// + col_height format_float(,2) (10) + col_diameter format_float(,1) (","+8=9)
// + heat_loss format_float(,0) (","+6=7) + program_type 0-1 символ (2)
// + mode (int)Samovar_Mode 0-7 (","+1=2, с запасом до 2 цифр - 3) = 144.
// Итого 20+72+144 = 236 байт. Буфер 288 - запас ~50 байт сверх расчётного максимума.
static portMUX_TYPE s_blynkLogLineMux = portMUX_INITIALIZER_UNLOCKED;
static char s_pendingV34Line[288];
static volatile bool s_pendingV34Ready = false;
static uint32_t s_pendingV34Revision = 0;
#ifdef USE_MQTT
volatile uint32_t blynkLastLargePublishAt = 0;
#endif

// Честный худший случай V35 (T2-review-1.md, [Blynk.ino:370,400-424]): sessionId uint32_t
// (10) + "," (1) + resume "0"/"1" (1) + "," (1) + chipId uint32_t (10) + "," (1)
// + SamSetup.TimeZone uint8_t (3) + "," (1) + SAMOVAR_VERSION "7.00" (4) + "," (1)
// + resetReason - худшее "deepsleep"/"brownout" (9) + "," (1) + description - лимит
// WebServer.ino (250) = 293 байта. Буфер 320 - запас над расчётным максимумом (T2-review-1.md
// рекомендовал минимум 320). Если после этого экранирования "%"->"&#37;"
// (commit_profile_operation(), Samovar.ino) описание всё равно не влезло - строка
// обрезается по границе UTF-8-символа в blynk_stage_session_start() ниже, с логированием.
static portMUX_TYPE s_blynkSessionMux = portMUX_INITIALIZER_UNLOCKED;
static char s_pendingV35Line[320];
static volatile bool s_pendingV35Ready = false;
static uint32_t s_pendingV35Revision = 0;

// Вызывается из Samovar.ino (SysTicker, tick_publish_log_line) - некрупная, без
// библиотечных вызовов Blynk и без BlynkLockGuard. Буфер посчитан на честный худший
// случай (см. комментарий у s_pendingV34Line) - переполнение означает не рост
// какого-то поля сверх ожидаемого, а мусор/рассинхронизацию формата, поэтому такую
// строку не отправляем вовсе (сервер ждёт ровно 25 полей после sessionId,statusInt),
// а не режем её на середине поля.
void blynk_stage_log_line(const String& line) {
  if ((size_t)line.length() > sizeof(s_pendingV34Line) - 1) {
    WriteConsoleLog("V34: строка лога (" + String(line.length()) + " байт) не помещается в буфер (" +
                     String(sizeof(s_pendingV34Line)) + "), не отправлена");
    return;
  }
  portENTER_CRITICAL(&s_blynkLogLineMux);
  strlcpy(s_pendingV34Line, line.c_str(), sizeof(s_pendingV34Line));
  s_pendingV34Revision++;
  s_pendingV34Ready = true;
  portEXIT_CRITICAL(&s_blynkLogLineMux);
}

// Вызывается только из blynk_push_tick() до отправки V35: после этого SysTicker может
// положить новый V34, который должен остаться до следующего тика вместе с новым V35.
static bool blynk_snapshot_pending_log_line(char (&line)[sizeof(s_pendingV34Line)], uint32_t& revision) {
  bool ready;
  portENTER_CRITICAL(&s_blynkLogLineMux);
  ready = s_pendingV34Ready;
  if (ready) {
    strlcpy(line, s_pendingV34Line, sizeof(line));
    revision = s_pendingV34Revision;
  }
  portEXIT_CRITICAL(&s_blynkLogLineMux);
  return ready;
}

// Вызывается только из blynk_push_tick() (loop(), уже под BlynkLockGuard из tick_blynk()).
static void blynk_push_pending_log_line(const char* line, uint32_t revision, bool ready) {
  if (!ready || !Blynk.connected()) return;
  Blynk.virtualWrite(V34, line);
#ifdef USE_MQTT
  blynkLastLargePublishAt = millis();
#endif
  if (!Blynk.connected()) return;
  portENTER_CRITICAL(&s_blynkLogLineMux);
  if (s_pendingV34Ready && s_pendingV34Revision == revision) s_pendingV34Ready = false;
  portEXIT_CRITICAL(&s_blynkLogLineMux);
}

// Вызывается из Samovar.ino (session_begin()) - НЕ берёт BlynkLockGuard: session_begin()
// достижима синхронно из BLYNK_WRITE(V3) (уже под этим локом, мьютекс не рекурсивный) и,
// структурно, из SysTicker (mode_dispatch_alarm -> ... -> menu_samovar_start, сейчас
// недостижимо без COLUMN_WETTING).
// Буфер посчитан на честный худший случай description (см. комментарий у s_pendingV35Line),
// но экранирование "%"->"&#37;" может раздуть описание сверх этого расчёта - в отличие от
// V34 (где переполнение означает мусор в служебных полях), здесь последнее поле - вся
// строка сразу, поэтому режем её по границе UTF-8-символа (не разрывая многобайтовый
// символ), а не отбрасываем целиком, и логируем сам факт обрезания одной строкой.
void blynk_stage_session_start(const String& line) {
  const size_t capacity = sizeof(s_pendingV35Line) - 1;
  if ((size_t)line.length() <= capacity) {
    portENTER_CRITICAL(&s_blynkSessionMux);
    strlcpy(s_pendingV35Line, line.c_str(), sizeof(s_pendingV35Line));
    s_pendingV35Revision++;
    s_pendingV35Ready = true;
    portEXIT_CRITICAL(&s_blynkSessionMux);
    return;
  }
  const char* src = line.c_str();
  size_t cut = capacity;
  // Продолжающий байт UTF-8 - 10xxxxxx (0x80-0xBF); откатываемся, пока не встанем на
  // границу символа (ASCII-байт или начало новой многобайтовой последовательности).
  while (cut > 0 && (static_cast<uint8_t>(src[cut]) & 0xC0) == 0x80) cut--;
  WriteConsoleLog("V35: описание сессии обрезано с " + String(line.length()) + " до " +
                   String(cut) + " байт (буфер " + String(sizeof(s_pendingV35Line)) + ")");
  String truncated = line.substring(0, cut);
  portENTER_CRITICAL(&s_blynkSessionMux);
  strlcpy(s_pendingV35Line, truncated.c_str(), sizeof(s_pendingV35Line));
  s_pendingV35Revision++;
  s_pendingV35Ready = true;
  portEXIT_CRITICAL(&s_blynkSessionMux);
}

// Вызывается только из blynk_push_tick(). Возвращает false, если V35 остался pending: V34
// в таком тике нельзя отправлять раньше начала сессии. Перед самой отправкой V35 форсирует немедленный
// полный resend медленных пинов (blynk_push_slow(true)) -V24 (программа) сервер должен
// получить не позже V35, иначе новая сессия в БД временно останется без программы.
static bool blynk_push_pending_session_start() {
  bool ready;
  char line[sizeof(s_pendingV35Line)];
  uint32_t revision = 0;
  portENTER_CRITICAL(&s_blynkSessionMux);
  ready = s_pendingV35Ready;
  if (ready) {
    strlcpy(line, s_pendingV35Line, sizeof(line));
    revision = s_pendingV35Revision;
  }
  portEXIT_CRITICAL(&s_blynkSessionMux);
  if (!ready) return true;
  if (!Blynk.connected()) return false;
  blynk_push_slow(true);
  if (!Blynk.connected()) return false;
  Blynk.virtualWrite(V35, line);
  if (!Blynk.connected()) return false;
  bool sentCurrent = false;
  portENTER_CRITICAL(&s_blynkSessionMux);
  if (s_pendingV35Ready && s_pendingV35Revision == revision) {
    s_pendingV35Ready = false;
    sentCurrent = true;
  }
  portEXIT_CRITICAL(&s_blynkSessionMux);
  return sentCurrent;
}

BLYNK_CONNECTED() {
  Serial.printf("Blynk connected at_ms=%lu\n", static_cast<unsigned long>(millis()));
  s_blynkPushResendAll = true;
}

BLYNK_DISCONNECTED() {
  // Счётчики из tick_blynk() (Samovar.ino): пропуски тактов по локу и максимальный разрыв
  // между Blynk.run() за это соединение; после вывода обнуляются.
  Serial.printf("Blynk disconnected at_ms=%lu rssi=%d heap=%u lock_skips=%lu run_max_gap_ms=%lu\n",
                static_cast<unsigned long>(millis()), WiFi.RSSI(), ESP.getFreeHeap(),
                static_cast<unsigned long>(blynkTickLockSkips),
                static_cast<unsigned long>(blynkRunMaxGapMs));
  blynkTickLockSkips = 0;
  blynkRunMaxGapMs = 0;
  blynkRunLastMs = 0;
}

// I2CStepper (мешалка/насос): команда строкой в формате параметров /i2cstepper,
// например device=pump&cmd=start&mode=2&pumpMlHour=1200&stepsPerMl=200 (PIN_SPEC.md §13).
// Проверка та же, что у веб-обработчика (parse_i2c_stepper_patch); cmd=status здесь
// не нужен - состояние обеих плат прошивка сама шлёт в V36. Отказ - предупреждение в V26
// с кодом и именем поля, результат виден по V36.
BLYNK_WRITE(V37) {
  if (mode_switch_in_progress()) return;
  I2CStepperParams params;
  const char* errorField = "request";
  NumericParseResult result = numeric_parse_result(NUMERIC_PARSE_OK);
  if (!params.parseQuery(param.asStr())) {
    result = numeric_parse_result(NUMERIC_PARSE_INVALID_ARGUMENT);
  }
  for (size_t index = 0; result.ok() && index < params.params(); index++) {
    const I2CStepperParam* item = params.getParam(index);
    if (!i2c_stepper_known_param(item->name()) ||
        request_param_count(&params, item->name().c_str()) != 1) {
      errorField = item->name().c_str();
      result = numeric_parse_result(NUMERIC_PARSE_INVALID_ARGUMENT);
    }
  }
  const I2CStepperParam* deviceParam = get_request_param(&params, "device");
  const I2CStepperParam* commandParam = get_request_param(&params, "cmd");
  String command = commandParam ? commandParam->value() : String();
  command.toLowerCase();
  I2CStepperDevice* dev = nullptr;
  if (deviceParam && deviceParam->value() == "mixer") dev = &i2cStepperMixer;
  else if (deviceParam && deviceParam->value() == "pump") dev = &i2cStepperPump;
  if (result.ok() && !dev) {
    errorField = "device";
    result = numeric_parse_result(NUMERIC_PARSE_NOT_ALLOWED);
  }
  if (result.ok() && command != "apply" && command != "save" && command != "start" &&
      command != "stop" && command != "calstart" && command != "calfinish" &&
      command != "relay") {
    errorField = "cmd";
    result = numeric_parse_result(NUMERIC_PARSE_NOT_ALLOWED);
  }
  if (result.ok() && !dev->present) {
    report_blynk_refusal(37, "NO_I2C_DEVICE");
    return;
  }
  I2CStepperDevice staged = {};
  if (result.ok()) {
    staged = *dev;
    result = parse_i2c_stepper_patch(&params, command, *dev, staged, errorField);
  }
  if (result.ok() && !i2c_stepper_command_supported(staged, command)) {
    errorField = "cmd";
    result = numeric_parse_result(NUMERIC_PARSE_NOT_ALLOWED);
  }
  if (!result.ok()) {
    String reason = numeric_parse_error_code(result.error);
    reason += ' ';
    reason += errorField;
    report_blynk_refusal(37, reason.c_str());
    return;
  }
  PendingI2CStepperCmd pendingCmd = {};
  pendingCmd.staged = staged;
  pendingCmd.device_sel = dev == &i2cStepperMixer ? 0 : 1;
  strncpy(pendingCmd.cmd, command.c_str(), sizeof(pendingCmd.cmd) - 1);
  OperationId operationId = 0;
  const OperationError queueError = queue_pending_i2cstepper(pendingCmd, operationId);
  if (queueError != OPERATION_ERROR_NONE) {
    report_blynk_refusal(37, queueError == OPERATION_ERROR_LOCK_BUSY
        ? "BUSY" : operation_error_code(queueError));
  }
}

// V33: «отправь все пины заново». Приложение шлёт при запуске и сразу после синхронизации
// проекта (сервер при ней стирает значения виджетов). Значение не важно, виджет не нужен:
// сервер передаёт /update на железо и без него. PIN_SPEC.md §7.
BLYNK_WRITE(V33) {
  s_blynkPushResendAll = true;
}

// V0/V1/V6/V7/V9/V25/V23 больше не отправляются отдельными пинами - сервер получает те же
// значения (Steam/Pipe/Water/Tank/ActualVolumePerHour/ACPSensor/pressure_value) как часть
// 25 полей V34 (см. blynk_stage_log_line ниже, PIN_SPEC.md §2). V2 (WthdrwlProgress) в V34
// не входит - остаётся быстрым пином.
static void blynk_push_v2() { Blynk.virtualWrite(V2, WthdrwlProgress); }
static void blynk_push_v8() { Blynk.virtualWrite(V8, get_liquid_volume()); }
// V21 попадает в kBlynkFastPush только в сборках с регулятором мощности; сама функция
// без #if, иначе автопрототип Arduino даёт «declared static but never defined».
// Текущее напряжение меняется всё время регулирования, поэтому V21 - быстрый пин.
static void __attribute__((unused)) blynk_push_v21() {
  Blynk.virtualWrite(V21, "Тек:" + (String)current_power_volt + " Цель:" + (String)target_power_volt);
}

// V10, V11, V14 - строки под runtime_state_lock; один захват замка на все три.
static void blynk_push_strings() {
  String timesCopy;
  String strCrtCopy;
  String statusCopy;
  bool locked = runtime_state_lock(pdMS_TO_TICKS(50));
  if (locked) {
    timesCopy = WthdrwTimeS + "; " + WthdrwTimeAllS;
    strCrtCopy = StrCrt;
    statusCopy = SamovarStatus;
    runtime_state_unlock(true);
  }
  Blynk.virtualWrite(V10, timesCopy);
  Blynk.virtualWrite(V11, strCrtCopy);
  Blynk.virtualWrite(V14, statusCopy);
}

typedef void (*BlynkPushFn)();
static const BlynkPushFn kBlynkFastPush[] = {
  blynk_push_v2, blynk_push_v8,
#ifdef SAMOVAR_USE_POWER
  blynk_push_v21,
#endif
  blynk_push_strings, blynk_push_v27, blynk_push_v36,
};
static const uint8_t kBlynkFastPushCount = sizeof(kBlynkFastPush) / sizeof(kBlynkFastPush[0]);

// true, если значение изменилось (или force); запоминает новое. Перегрузки вместо
// шаблона: генератор прототипов Arduino/PlatformIO шаблоны в .ino не понимает.
static bool blynk_changed(int& last, int now, bool force) {
  if (!force && last == now) return false;
  last = now;
  return true;
}
static bool blynk_changed(float& last, float now, bool force) {
  if (!force && last == now) return false;
  last = now;
  return true;
}
static bool blynk_changed(uint32_t& last, uint32_t now, bool force) {
  if (!force && last == now) return false;
  last = now;
  return true;
}
static bool blynk_changed(String& last, const String& now, bool force) {
  if (!force && last == now) return false;
  last = now;
  return true;
}

// Отпечаток программы отбора (FNV-1a по program[], тексту Lua и ProgramLen). Считается раз в
// цикл push (~1.5 КБ памяти), чтобы слать V24 только после правки программы, не трогая
// program_io.h (он заморожен smoke-тестами). Рваное чтение параллельно с program_commit()
// даёт лишь один лишний push V24 на следующем цикле.
static uint32_t blynk_program_fingerprint() {
  uint32_t h = 2166136261u;
  const uint8_t* bytes = reinterpret_cast<const uint8_t*>(program);
  for (size_t i = 0; i < sizeof(WProgram) * PROGRAM_END; i++) {
    h = (h ^ bytes[i]) * 16777619u;
  }
  bytes = reinterpret_cast<const uint8_t*>(programTextPool);
  for (size_t i = 0; i < sizeof(programTextPool); i++) {
    h = (h ^ bytes[i]) * 16777619u;
  }
  return (h ^ ProgramLen) * 16777619u;
}

// Медленные пины: шлём только при изменении, все разом при force.
static void blynk_push_slow(bool force) {
  static int lastProcess = -1;
  static int lastPower = -1;
  static int lastPause = -1;
  static String lastIp;
  static int lastMode = -1;
  static uint32_t lastProgramFingerprint = 0;
  static int lastProgramMode = -1;

  const int process = (startval > 0 && startval < 5) ? 1 : 0;
  if (blynk_changed(lastProcess, process, force)) Blynk.virtualWrite(V3, process);
  if (blynk_changed(lastPower, (int)PowerOn, force)) Blynk.virtualWrite(V4, (int)PowerOn);
  if (blynk_changed(lastPause, (int)PauseOn, force)) Blynk.virtualWrite(V13, (int)PauseOn);
  // V5 (давление) убран - дублируется в V34 (25-е поле), см. blynk_stage_log_line ниже.
  char ip[sizeof(ipst)] = {};
  ipst_copy(ip);
  if (blynk_changed(lastIp, String(ip), force)) Blynk.virtualWrite(V15, ip);
  if (blynk_changed(lastMode, (int)Samovar_Mode, force)) Blynk.virtualWrite(V20, Samovar_Mode);
  if (force) Blynk.virtualWrite(V19, SAMOVAR_VERSION);
#ifdef SAMOVAR_USE_POWER
  static float lastTarget = -1e9f;
  if (blynk_changed(lastTarget, (float)target_power_volt, force)) Blynk.virtualWrite(V16, target_power_volt);
#endif
  // Программа: сериализация недешёвая, поэтому только по отпечатку program[] и при смене
  // режима (формат строк зависит от режима).
  const bool programChanged = blynk_changed(lastProgramFingerprint, blynk_program_fingerprint(), force);
  const bool programModeChanged = blynk_changed(lastProgramMode, (int)Samovar_Mode, force);
  if (programChanged || programModeChanged) Blynk.virtualWrite(V24, serialize_program_for_mode(Samovar_Mode));
}

void blynk_push_tick() {
  // V35 раньше V34: если оба накопились к одному тику, сервер должен узнать о сессии
  // до первой строки её лога, иначе он отбросит строку как «сессия неизвестна».
  static unsigned long idleV34At = 0;
  const unsigned long nowIdle = millis();
  const bool idleV34Ready = startval == SAMOVAR_STARTVAL_IDLE && nowIdle - idleV34At >= 5000UL;
  String idleV34Line;
  if (idleV34Ready) idleV34Line = build_idle_v34_line();

  char pendingV34Line[sizeof(s_pendingV34Line)];
  uint32_t pendingV34Revision = 0;
  const bool pendingV34Ready = blynk_snapshot_pending_log_line(pendingV34Line, pendingV34Revision);
  const bool canPushV34 = blynk_push_pending_session_start();  // V35, см. session_begin() (Samovar.ino)
  if (canPushV34) blynk_push_pending_log_line(pendingV34Line, pendingV34Revision, pendingV34Ready);

  // Строка в простое зафиксирована выше до V35 gate: новая сессия, staged после
  // snapshot, не меняет смысл V34, выбранного для этого тика.
  if (canPushV34 && idleV34Ready) {
    idleV34At = nowIdle;
    Blynk.virtualWrite(V34, idleV34Line);
#ifdef USE_MQTT
    blynkLastLargePublishAt = millis();
#endif
  }

  static unsigned long cycleStart = 0;
  static unsigned long slowSentAt = 0;
  static uint8_t next = 0xFF;  // 0xFF - цикл не идёт
  const unsigned long now = millis();
  if (next >= kBlynkFastPushCount) {
    if (!s_blynkPushResendAll && now - cycleStart < BLYNK_PUSH_PERIOD_MS) return;
    cycleStart = now;
    next = 0;
    const bool force = s_blynkPushResendAll || now - slowSentAt >= BLYNK_PUSH_SLOW_PERIOD_MS;
    blynk_push_slow(force);
    if (force) slowSentAt = now;
    s_blynkPushResendAll = false;
  }
  for (uint8_t n = 0; n < BLYNK_PUSH_PER_TICK && next < kBlynkFastPushCount; n++) {
    kBlynkFastPush[next++]();
  }
}

#endif
