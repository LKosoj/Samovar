#pragma once

#include <Arduino.h>
#include "runtime_helpers.h"
#include "samovar_api.h"
#include "safety_transition.h"

// [П3] lua_heater_channel_raised() определена в lua.h (только когда USE_LUA
// подключает его в этой единице трансляции). Без Lua канал нагрева никогда
// не поднимается мимо PowerOn - подставляем заглушку false.
#ifndef USE_LUA
inline bool lua_heater_channel_raised() { return false; }
#endif

inline void mode_clear_alarm_pause_if_expired() {
  if (alarm_t_min > 0 && safety_deadline_expired(millis(), alarm_t_min)) alarm_t_min = 0;
}

inline void mode_set_alarm_pause_ms(uint32_t delayMs) {
  alarm_t_min = safety_deadline_after(millis(), delayMs);
}

inline bool mode_check_powered_cooling_sensors(const char* modeName) {
  if (!sensor_valid(WaterSensor) && process_sensor_failed(modeName, "воды")) return false;
  if (optional_sensor_failed(ACPSensor) && process_sensor_failed(modeName, "ТСА")) return false;
  return true;
}

inline bool mode_should_open_cooling(bool requirePower, bool includeAcp, bool includeTank) {
  if (valve_status) return false;
  if (requirePower && !PowerOn) return false;
  if (includeAcp && sensor_temp_at_least(ACPSensor, MAX_ACP_TEMP - 5)) return true;
  return includeTank && PowerOn && TankSensor.avgTemp >= OPEN_VALVE_TANK_TEMP;
}

// [П10] Раньше клапан закрывался ТОЛЬКО по остыванию воды охлаждения ниже
// closeTemp: летом (тёплая проточная вода) порог почти никогда не достигается -
// клапан не закрывается вовсе; при уже холодной воде клапан захлопывается СРАЗУ
// по команде "стоп", даже если куб ещё кипяток. Добавлена вторая, независимая
// причина закрытия - куб остыл ниже OPEN_VALVE_TANK_TEMP - 7 (запас 7°C от
// порога открытия, т.е. ниже 70°C), и минимальная выдержка 3 минуты с момента
// выключения нагрева перед закрытием по одной лишь температуре воды.
// tankWasHot взводится, ТОЛЬКО если куб реально грелся в эту сессию (PowerOn и
// датчик валиден, и температура доходила до OPEN_VALVE_TANK_TEMP) - иначе у
// НБК (куб физически не греется, датчик куба может быть всегда ниже 70°C)
// критерий "куб остыл" сработал бы сразу при остановке, минуя выдержку по воде.
inline bool mode_should_close_cooling(float closeTemp, bool requireAcpCoolEnough) {
  // Фронты PowerOn ловим тут же - функция и так вызывается каждый тик всеми
  // режимами независимо от PowerOn, отдельный тикающий хук не нужен.
  static bool modeCoolingWasPowerOn = false;
  static uint32_t modeHeatOffDeadline = 0;
  static bool modeHeatOffDeadlineArmed = false;
  static bool tankWasHot = false;

  if (!modeCoolingWasPowerOn && PowerOn) tankWasHot = false;
  if (modeCoolingWasPowerOn && !PowerOn) {
    modeHeatOffDeadline = safety_deadline_after(millis(), 3UL * 60 * 1000);
    modeHeatOffDeadlineArmed = true;
  }
  if (PowerOn && sensor_valid(TankSensor) && TankSensor.avgTemp >= OPEN_VALVE_TANK_TEMP) {
    tankWasHot = true;
  }
  modeCoolingWasPowerOn = PowerOn;

  if (PowerOn || is_self_test || !valve_status) return false;
  // Пока нагрев ни разу не выключался в этой сессии прошивки, modeHeatOffDeadlineArmed
  // остаётся false - выдержка считается уже прошедшей, как и было до этой правки.
  // Отдельный флаг (а не сравнение дедлайна с 0) нужен, потому что
  // safety_deadline_expired() сравнивает int32-разность millis(): при "0 как
  // сентинел не взведено" критерий ломался бы после ~24.85 суток аптайма
  // (2^31 мс), когда millis() уже сам превысил половину диапазона uint32.
  const bool waterCooledLongEnough =
    WaterSensor.avgTemp <= closeTemp &&
    (!modeHeatOffDeadlineArmed || safety_deadline_expired(millis(), modeHeatOffDeadline));
  const bool tankCooledEnough =
    tankWasHot && sensor_valid(TankSensor) && TankSensor.avgTemp < OPEN_VALVE_TANK_TEMP - 7;
  if (!waterCooledLongEnough && !tankCooledEnough) return false;
  if (!requireAcpCoolEnough) return true;
  return !sensor_configured(ACPSensor) || ACPSensor.avgTemp <= MAX_ACP_TEMP - 10;
}

inline void mode_stop_cooling_pump_if_started() {
#ifdef USE_WATER_PUMP
  if (pump_started) set_pump_pwm(0);
#endif
}

inline bool mode_water_flow_demanded() {
  if (!SamSetup.UseWS) return false;
  if (valve_status) return true;
#ifdef USE_WATER_PUMP
  if (Samovar_Mode == SAMOVAR_BEER_MODE) return beer_cooling_pump_demanded();
  if (Samovar_Mode == SAMOVAR_CHEESE_MODE) return cheese_cooling_pump_demanded();
  return pump_started;
#else
  return false;
#endif
}

inline void mode_request_water_flow_emergency_if_needed() {
#ifdef USE_WATERSENSOR
  if (mode_water_flow_demanded() && WFAlarmCount > WF_ALARM_COUNT) {
    set_buzzer(true);
    request_emergency_stop("Аварийное отключение! Прекращена подача воды.");
  }
#endif
}

// Предельные температуры воды охлаждения/ТСА: при превышении во время работы —
// аварийный останов с перечнем превысивших датчиков. Общий блок четырёх режимов
// (дистилляция, БК, пиво-охлаждение, сувид).
inline void mode_request_overheat_emergency_if_needed() {
  // [П3] Lua мог поднять канал нагрева сырым digitalWrite мимо PowerOn -
  // отсечка по перегреву обязана сработать и тогда.
  if ((WaterSensor.avgTemp >= MAX_WATER_TEMP || sensor_temp_at_least(ACPSensor, MAX_ACP_TEMP)) && (PowerOn || lua_heater_channel_raised())) {
    String s = "";
    if (WaterSensor.avgTemp >= MAX_WATER_TEMP)
      s = s + " Воды";
    if (sensor_temp_at_least(ACPSensor, MAX_ACP_TEMP))
      s = s + " ТСА";
    request_emergency_stop("Аварийное отключение! Превышена максимальная температура" + s);
  }
}

inline bool mode_water_pre_alarm_due() {
  return WaterSensor.avgTemp >= ALARM_WATER_TEMP - 5 && PowerOn && alarm_t_min == 0;
}

inline void mode_update_water_pump_pid(float acpBoostThreshold) {
#ifdef USE_WATER_PUMP
  if (!valve_status) return;
  if (sensor_configured(ACPSensor) && sensor_reading_valid(ACPSensor) && ACPSensor.avgTemp > acpBoostThreshold && ACPSensor.avgTemp > WaterSensor.avgTemp) {
    set_pump_speed_pid(SamSetup.SetWaterTemp + 3);
  } else {
    set_pump_speed_pid(WaterSensor.avgTemp);
  }
#else
  (void)acpBoostThreshold;
#endif
}

#ifdef SAMOVAR_USE_POWER
// [П2] В разгоне (SPEED) target_power_volt == 0 (уставки ещё нет - греет на
// максимум). Взять его за базу для "понизить на N" значит всегда падать в клэмп
// power_work_mode_threshold() одним скачком с реального максимума. Настоящая
// база - фактическое напряжение/мощность регулятора (current_power_volt) -
// её единица уже согласована с PWR_FACTOR/порогом для каждого бэкенда.
inline float mode_water_alarm_power_base() {
  return target_power_volt > 0 ? target_power_volt : current_power_volt;
}
#endif

inline void mode_reduce_power_for_water_alarm_by_volts(const String& alarmMessage, float reduceVolts) {
#ifdef SAMOVAR_USE_POWER
  if (WaterSensor.avgTemp >= ALARM_WATER_TEMP) {
    set_buzzer(true);
    SendMsg(alarmMessage, ALARM_MSG);
    set_current_power(reduce_power_by_volts(mode_water_alarm_power_base(), reduceVolts));
  }
#else
  (void)alarmMessage;
  (void)reduceVolts;
#endif
}

// [П6] БК и дистилляция реагируют на критическую (пред-аварийную) температуру воды
// идентично: гудок и предупреждение — безусловно, снижение мощности — опционально
// (SAMOVAR_USE_POWER), затем пауза перед повторной реакцией. Ректификация (alarm.h)
// и НБК (nbk.h) в этой точке различаются по существу (другой текст/уровень сообщения
// при снижении мощности, НБК вообще не снижает мощность и держит вдвое более длинную
// паузу) - туда этот хелпер не переносим.
inline void mode_handle_water_pre_alarm_if_due() {
  if (mode_water_pre_alarm_due()) {
    set_buzzer(true);
    //Если уже реагировали - надо подождать 30 секунд, так как процесс инерционный
    SendMsg(("Критическая температура воды!"), WARNING_MSG);

#ifdef SAMOVAR_USE_POWER
    //Попробуем снизить мощность на 5 В/шагов регулятора, чтобы исключить перегрев колонны.
    mode_reduce_power_for_water_alarm_by_volts("Критическая температура воды! Понижаем " + (String)PWR_MSG + " с " + (String)mode_water_alarm_power_base(), 5);
#endif
    mode_set_alarm_pause_ms(30000);
  }
}

inline void mode_update_water_valve_by_setpoint() {
#ifdef USE_WATER_VALVE
  if (WaterSensor.avgTemp >= SamSetup.SetWaterTemp + 1) {
    digitalWrite(WATER_PUMP_PIN, USE_WATER_VALVE);
  } else if (WaterSensor.avgTemp <= SamSetup.SetWaterTemp - 1) {
    digitalWrite(WATER_PUMP_PIN, !USE_WATER_VALVE);
  }
#endif
}

/**
 * @brief Отменяет запуск процесса из-за ошибки предусловий: сообщение + сброс
 *        статуса в «Ожидание» до того, как режим начал работу.
 */
inline void mode_cancel_process_start(const String& message) {
  SendMsg(message, ALARM_MSG);
  SamovarStatusInt = SAMOVAR_STATUS_IDLE;
  startval = SAMOVAR_STARTVAL_IDLE;
}

/**
 * @brief Закрывает файл лога с диагностикой занятости (WARNING вместо тихой потери).
 */
inline void mode_warn_log_close_failed() {
  if (!request_data_log_close()) SendMsg("Файл лога занят: закрытие пропущено", WARNING_MSG);
}

// [P7 п.3a] Одноразовый флаг явного пользовательского запроса старта нагрева. Взводится
// ТОЛЬКО из mode_apply_power_on_command (mode_registry.h) в ответ на реальную команду
// пользователя; mode_begin_heating_session требует его перед фактическим стартом сессии -
// это отменяет молчаливый авто-рестарт нагрева после отказа регулятора (см. power_regulator.h
// fail_close_regulator_locked / lazy_start_owner_status).
// [P7 F1] Взводится generic-веткой для ЛЮБОГО табличного режима (в т.ч. BEER/NBK, которые
// mode_begin_heating_session не вызывают и поэтому флаг не потребляют) - вместе с флагом
// хранится целевой activeStatus, ради которого он взведён. mode_consume_heating_start_request
// сверяет сохранённый статус с запрошенным: чужой (взведённый для другого режима) или
// устаревший взвод не проходит.
static bool modeHeatingStartRequested = false;
static int16_t modeHeatingStartRequestedStatus = 0;

inline void mode_request_heating_start(int16_t activeStatus) {
  modeHeatingStartRequested = true;
  modeHeatingStartRequestedStatus = activeStatus;
}

inline bool mode_consume_heating_start_request(int16_t activeStatus) {
  if (!modeHeatingStartRequested || modeHeatingStartRequestedStatus != activeStatus) return false;
  modeHeatingStartRequested = false;
  return true;
}

enum ModeHeatingStartResult : uint8_t {
  MODE_HEATING_START_PENDING = 0,
  MODE_HEATING_START_SUCCEEDED,
  MODE_HEATING_START_FAILED,
};

struct ModeHeatingStartState {
  SafetyTransition transition;
  int16_t activeStatus;
  const char* heatingMessage;
#ifdef USE_MQTT
  String mqttProgram;
  String sessionDescription;
#endif
};

static ModeHeatingStartState modeHeatingStart;

inline bool mode_heating_start_pending(int16_t activeStatus) {
  return safety_transition_active(modeHeatingStart.transition) &&
         modeHeatingStart.activeStatus == activeStatus;
}

inline bool mode_heating_start_active() {
  return safety_transition_active(modeHeatingStart.transition);
}

inline void mode_clear_heating_start() {
  safety_transition_cancel(modeHeatingStart.transition);
  modeHeatingStart.activeStatus = 0;
  modeHeatingStart.heatingMessage = nullptr;
#ifdef USE_MQTT
  modeHeatingStart.mqttProgram = String();
  modeHeatingStart.sessionDescription = String();
#endif
}

inline ModeHeatingStartResult mode_fail_heating_start() {
  const bool resetOwnerState = SamovarStatusInt == modeHeatingStart.activeStatus;
  if (PowerOn) set_power(false, false);
  mode_warn_log_close_failed();
  mode_clear_heating_start();
  if (resetOwnerState) {
    SamovarStatusInt = SAMOVAR_STATUS_IDLE;
    startval = SAMOVAR_STARTVAL_IDLE;
  }
  return MODE_HEATING_START_FAILED;
}

inline void cancel_invalid_mode_heating_session() {
  if (!safety_transition_active(modeHeatingStart.transition)) return;
  if (heater_safety_latched() || SamovarStatusInt != modeHeatingStart.activeStatus ||
      !PowerOn) {
    mode_fail_heating_start();
  }
}

inline ModeHeatingStartResult mode_tick_heating_session(int16_t activeStatus) {
  if (!safety_transition_active(modeHeatingStart.transition) ||
      modeHeatingStart.activeStatus != activeStatus) {
    return MODE_HEATING_START_FAILED;
  }
  if (heater_safety_latched() || SamovarStatusInt != activeStatus || !PowerOn) return mode_fail_heating_start();

  if (modeHeatingStart.transition.phase == MODE_HEATING_PHASE_WAIT_POWER) {
    if (power_transition_start_pending()) return MODE_HEATING_START_PENDING;
    safety_transition_advance(
      modeHeatingStart.transition,
      MODE_HEATING_PHASE_WAIT_STABILIZE,
      safety_deadline_after(millis(), 1000)
    );
    return MODE_HEATING_START_PENDING;
  }

  if (!safety_transition_due(modeHeatingStart.transition, millis())) {
    return MODE_HEATING_START_PENDING;
  }
  if (heater_safety_latched() || SamovarStatusInt != activeStatus || !PowerOn) return mode_fail_heating_start();
  SteamSensor.Start_Pressure = bme_pressure;
  if (heater_safety_latched() || SamovarStatusInt != activeStatus || !PowerOn) return mode_fail_heating_start();
#ifdef USE_MQTT
  MqttSendMsg(
    (String)chipId + "," + SamSetup.TimeZone + "," + SAMOVAR_VERSION + "," +
    modeHeatingStart.mqttProgram + "," + modeHeatingStart.sessionDescription,
    "st"
  );
  if (heater_safety_latched() || SamovarStatusInt != activeStatus || !PowerOn) return mode_fail_heating_start();
#endif
  SendMsg(modeHeatingStart.heatingMessage, NOTIFY_MSG);
  mode_clear_heating_start();
  return MODE_HEATING_START_SUCCEEDED;
}

inline ModeHeatingStartResult mode_begin_heating_session(
  int16_t activeStatus,
  const char* createLogError,
  const char* sessionBusyError,
  const String& mqttProgram,
  const char* heatingMessage,
  bool resetHeatLoss
) {
  if (safety_transition_active(modeHeatingStart.transition)) {
    return modeHeatingStart.activeStatus == activeStatus
      ? MODE_HEATING_START_PENDING
      : mode_fail_heating_start();
  }

  // [PKG-B п.7] Нагрев жёстко заблокирован аварийной защёлкой (снимается только перезагрузкой).
  // Явно уведомляем оператора и гасим владение статусом — иначе старт будет молча
  // проваливаться каждый тик, а UI ничего не объяснит.
  if (heater_safety_latched() && SamovarStatusInt == activeStatus) {
    mode_cancel_process_start("Нагрев заблокирован аварийной защитой, требуется перезагрузка");
    return MODE_HEATING_START_FAILED;
  }
  if (PowerOn || SamovarStatusInt != activeStatus || heater_safety_latched()) return MODE_HEATING_START_FAILED;
  if (power_transition_active()) {
    mode_cancel_process_start("Выключение нагрева ещё не завершено. Старт отменён.");
    return MODE_HEATING_START_FAILED;
  }

  // [P7 п.3a] Без явного запроса (mode_request_heating_start) сессию не начинаем - иначе
  // отказ регулятора, молча сбросивший статус в IDLE и тут же снова выставленный где-то
  // выше по стеку, привёл бы к авто-рестарту нагрева без нового действия пользователя.
  if (!mode_consume_heating_start_request(activeStatus)) {
    mode_cancel_process_start("Нагрев не возобновлён автоматически. Требуется повторная команда старта.");
    return MODE_HEATING_START_FAILED;
  }

  if (resetHeatLoss) reset_heat_loss_calculation();
  if (!create_data()) {
    mode_cancel_process_start(createLogError);
    return MODE_HEATING_START_FAILED;
  }

  if (heater_safety_latched() || SamovarStatusInt != activeStatus) {
    mode_warn_log_close_failed();
    return MODE_HEATING_START_FAILED;
  }

#ifdef USE_MQTT
  if (!copy_mqtt_session_description(modeHeatingStart.sessionDescription, pdMS_TO_TICKS(50))) {
    mode_cancel_process_start(sessionBusyError);
    mode_warn_log_close_failed();
    return MODE_HEATING_START_FAILED;
  }
  modeHeatingStart.mqttProgram = mqttProgram;
  if (heater_safety_latched() || SamovarStatusInt != activeStatus) {
    mode_warn_log_close_failed();
    modeHeatingStart.sessionDescription = String();
    modeHeatingStart.mqttProgram = String();
    return MODE_HEATING_START_FAILED;
  }
#else
  (void)mqttProgram;
  (void)sessionBusyError;
#endif

  if (heater_safety_latched() || SamovarStatusInt != activeStatus) {
    mode_warn_log_close_failed();
    return MODE_HEATING_START_FAILED;
  }

  modeHeatingStart.activeStatus = activeStatus;
  modeHeatingStart.heatingMessage = heatingMessage;
  safety_transition_begin(
    modeHeatingStart.transition,
    MODE_HEATING_PHASE_WAIT_POWER,
    0
  );
  set_power(true);
  if (heater_safety_latched() || SamovarStatusInt != activeStatus || !PowerOn) return mode_fail_heating_start();
  return MODE_HEATING_START_PENDING;
}

// [PKG-B п.8] Общая обёртка старта нагрева для distiller/BK: диспетчеризует между
// продолжением уже идущего старта (tick) и началом нового (begin). Возвращает результат;
// пост-обработку успеха (свой колбэк) выполняет вызывающий.
inline ModeHeatingStartResult mode_run_heating_start(
  int16_t activeStatus,
  const char* createLogError,
  const char* sessionBusyError,
  const String& mqttProgram,
  const char* heatingMessage,
  bool resetHeatLoss
) {
  if (mode_heating_start_pending(activeStatus)) {
    return mode_tick_heating_session(activeStatus);
  }
  return mode_begin_heating_session(
    activeStatus, createLogError, sessionBusyError,
    mqttProgram, heatingMessage, resetHeatLoss
  );
}
