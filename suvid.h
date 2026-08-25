#pragma once

#include <Arduino.h>
#include <math.h>
#include "Samovar.h"
#include "samovar_api.h"
#include "runtime_helpers.h"
#include "mode_common.h"

// Уставка термостата: 0 в настройках — поле не задано, работаем от дефолта 60°.
inline float suvid_target_temp() {
  return SamSetup.SuvidTemp > 0 ? SamSetup.SuvidTemp : 60.0f;
}

// [П15] Максимальное время на выход в рабочую полосу ±HEAT_DELTA от уставки.
// Если за это время выдержка так и не началась - скорее всего сломан ТЭН,
// врёт датчик куба или загрузка слишком велика для нагревателя. Значение по
// аналогии с BEER_BOIL_TIMEOUT_MS в beer.h (тот же класс оборудования - большой
// бак, а не бытовая мультиварка), ориентировочное, подлежит проверке на реальном
// оборудовании.
// Раньше по этому таймауту уходило только предупреждение, и нагрев продолжал
// работать: при отказе датчика куба (застывшее заниженное показание) термостат
// держит ТЭН включённым бесконечно, потому что уставка по такому показанию
// недостижима в принципе. Близнецы в beer.h (BEER_BOIL_TIMEOUT_MS,
// BEER_COOL_TIMEOUT_MS) в такой ситуации останавливают процесс -
// здесь теперь то же самое: сообщение + штатное выключение нагрева.
#define SUVID_REACH_TIMEOUT_MS (60UL * 60UL * 1000UL)

// [T24.1] Полоса зачёта выдержки шире полосы регулирования (HEAT_DELTA): из-за
// тепловой инерции бака температура колеблется вокруг уставки сильнее, чем
// успевает отработать релейный термостат, и зачёт времени по HEAT_DELTA
// постоянно прерывался бы. Термостат (suvidHeaterOn ниже) по-прежнему
// работает по HEAT_DELTA - меняется только критерий "засчитывать ли время".
#define SUVID_HOLD_BAND_C 2.0f

// Через сколько повторять команду выключения, если нагрев всё ещё включён.
// Очередь команд общая на всё устройство: чужая команда (веб, Lua, другой режим),
// разобранная в том же проходе loop(), способна вернуть нагрев обратно. Считать
// "команда поставлена" за "нагрев выключен" поэтому нельзя - иначе одна такая гонка
// оставила бы ТЭН включённым до конца сессии, без повторных попыток и без второго
// сообщения. Повторяется именно SAMOVAR_POWER_OFF (Samovar.ino: set_power(false)), а
// НЕ SAMOVAR_POWER: тот - ПЕРЕКЛЮЧАТЕЛЬ (set_power(!PowerOn)), и пока первая команда
// лежит в очереди неразобранной, вторая, вынутая следом в том же проходе loop(),
// включила бы нагрев обратно - повтор отменял бы сам себя, причём молча
// (reachTimeoutMsgSent уже взведён, второго сообщения не будет). Интервал заметно
// больше периода тика (1 с), чтобы обычная задержка исполнения не порождала лишних
// попыток.
#define SUVID_STOP_RETRY_MS (10UL * 1000UL)

// Выдержка Сувида учитывает только подтверждённое время внутри полосы
// setpoint±HEAT_DELTA. active означает, что температура хотя бы раз вошла в
// полосу ("выдержка началась") - выставляется независимо от SuvidHoldMinutes
// (0 = бессрочный термостат, см. Samovar.h), иначе при бессрочном режиме
// проверка отклонения ниже никогда бы не включалась. active остаётся
// взведённым между выходами из полосы, чтобы накопленное время не терялось;
// inBand отделяет текущий зачёт интервала. sessionStartMs — момент начала
// текущей сессии нагрева, нужен только для таймаута "не вышли на режим";
// sessionStartMsSet - отдельный флаг, а не "sessionStartMs == 0" в качестве
// признака "ещё не установлен" - millis() тоже может быть ровно 0 (см.
// аналогичную пару suvidDeviation.active/sinceMs чуть ниже).
struct SuvidHoldState {
  bool active;
  bool fired;
  bool inBand;
  bool completionWarningSent;
  uint32_t accumulatedMs;
  uint32_t lastTickMs;
  uint32_t sessionStartMs;
  bool sessionStartMsSet;
  bool reachTimeoutMsgSent;
  bool reachTimeoutStopQueued;
  uint32_t reachTimeoutStopMs;
};
static SuvidHoldState suvidHold;

struct SuvidDeviationState { bool active; bool warningSent; uint32_t sinceMs; };
static SuvidDeviationState suvidDeviation;

// [T24.3] Релейный термостат с гистерезисом HEAT_DELTA (Samovar_ini.h). Раньше жил
// как static-переменная внутри check_alarm_suvid() - теперь виден также suvid_tick()
// (Samovar.ino: loop()), которая переносит фактическое применение состояния на
// нагреватель из надзорной задачи (SysTicker, core 0) в loop() (core 1): setHeaterPosition()
// в сборке без SAMOVAR_USE_POWER содержит блокирующую vTaskDelay(50), недопустимую
// внутри 1-секундного тика надзора.
static volatile bool suvidHeaterOn = false;

// Остаток выдержки в секундах; -1, если отсчёт не идёт (см. tick_status_fsm в logic.h).
inline int32_t suvid_hold_remaining_sec() {
  if (!suvidHold.active || SamSetup.SuvidHoldMinutes == 0) return -1;
  const uint32_t totalMs = (uint32_t)SamSetup.SuvidHoldMinutes * 60000UL;
  return suvidHold.accumulatedMs >= totalMs
      ? 0
      : (int32_t)((totalMs - suvidHold.accumulatedMs) / 1000UL);
}

/**
 * @brief Режим Су-вид: надзор датчиков/аварий + релейный термостат по TankSensor.
 * Вызывается из mode_dispatch_alarm (SysTicker, core 0, 1 Гц). У режима нет
 * собственного _proc()/finish() (mode_registry.h: activeStatus=0, как у простоя
 * Ректификации) — поэтому и надзор, и управление нагревом целиком в этом обработчике.
 */
inline void check_alarm_suvid() {
  mode_clear_alarm_pause_if_expired();

  // Датчики проверяем только при активном процессе (PowerOn) — иначе неподключённый
  // датчик куба порол бы аварийный останов каждую секунду в простое (см. check_alarm()
  // в alarm.h для Ректификации — тот же принцип для режима с activeStatus=0).
  // Вода и ТСА в Сувиде опциональны (термостат работает и без охлаждения контура) —
  // авария только если датчик заявлен и невалиден. Куб (TankSensor) обязателен:
  // без него термостату не по чему регулировать нагрев.
  if (PowerOn) {
    if (optional_sensor_failed(WaterSensor) && process_sensor_failed("Сувид", "воды")) return;
    if (optional_sensor_failed(ACPSensor) && process_sensor_failed("Сувид", "ТСА")) return;
    if (!sensor_valid(TankSensor) && process_sensor_failed("Сувид", "куба")) return;
  }

#ifdef SAMOVAR_USE_POWER
  check_power_error();
#endif

  mode_request_overheat_emergency_if_needed();
  mode_request_water_flow_emergency_if_needed();

  if (!PowerOn) {
    suvidHeaterOn = false;  // холодный старт следующей сессии: не наследовать состояние реле
    set_heater_state_flag(false);
    suvidHold = {false, false, false, false, 0, 0, 0, false, false, false, 0};
    suvidDeviation = {false, false, 0};
    return;
  }
  const float setpoint = suvid_target_temp();
  if (TankSensor.avgTemp <= setpoint - HEAT_DELTA) suvidHeaterOn = true;
  else if (TankSensor.avgTemp >= setpoint + HEAT_DELTA) suvidHeaterOn = false;
  // Фактическое применение к нагревателю (heater_state, setHeaterPosition()) -
  // в suvid_tick() (loop(), core 1), не здесь: см. комментарий у suvidHeaterOn выше.

  const uint32_t now = millis();
  if (!suvidHold.sessionStartMsSet) {
    suvidHold.sessionStartMs = now;
    suvidHold.sessionStartMsSet = true;
  }
  const float deviation = fabsf(TankSensor.avgTemp - setpoint);
  const bool inHoldBand = deviation <= SUVID_HOLD_BAND_C;

  // Взводим active независимо от SuvidHoldMinutes (см. комментарий у struct
  // SuvidHoldState) - это единственное место, где выясняется, что выдержка
  // "началась".
  if (!suvidHold.active && inHoldBand) {
    suvidHold.active = true;
    suvidHold.inBand = true;
    suvidHold.lastTickMs = now;
  } else if (suvidHold.active) {
    if (inHoldBand) {
      if (suvidHold.inBand) suvidHold.accumulatedMs += now - suvidHold.lastTickMs;
      suvidHold.inBand = true;
      suvidHold.lastTickMs = now;
    } else {
      suvidHold.inBand = false;
    }
  }

  // [П15] Отклонение проверяем только ПОСЛЕ начала выдержки. До этого момента
  // идёт обычный разогрев, когда большое отклонение - норма (вода ещё
  // греется), а не авария. Раньше проверка шла с самого включения питания,
  // поэтому каждая сессия начиналась с ложной тревоги - пользователи
  // привыкали её игнорировать и рисковали пропустить настоящий отказ
  // ТЭНа/датчика. Пока выдержка не началась - следим за таймаутом ниже.
  if (suvidHold.active) {
    if (deviation > SUVID_HOLD_BAND_C) {
      if (!suvidDeviation.active) {
        suvidDeviation.active = true;
        suvidDeviation.sinceMs = now;
      }
      if (!suvidDeviation.warningSent &&
          (uint32_t)(now - suvidDeviation.sinceMs) >= 60000UL) {
        SendMsg("Сувид: температура отклоняется от уставки более чем на 2° уже 60 сек.", WARNING_MSG);
        suvidDeviation.warningSent = true;
      }
    } else {
      suvidDeviation = {false, false, 0};
    }
  } else if ((uint32_t)(now - suvidHold.sessionStartMs) >= SUVID_REACH_TIMEOUT_MS) {
    // Сообщение - один раз (ALARM_MSG, а не WARNING_MSG: нагрев принудительно
    // выключается, пользователь должен узнать об этом наверняка). Команда выключения -
    // до тех пор, пока нагрев фактически не выключился: неудачная постановка (очередь
    // занята) повторяется на следующем тике, успешная - через SUVID_STOP_RETRY_MS, если
    // нагрев всё ещё включён. Штатное выключение, а не request_emergency_stop:
    // это отказ оборудования или конфигурации, а не мгновенная опасность -
    // аварийная защёлка потребовала бы ручного сброса (см. beer_abort_config_error
    // в beer.h, тот же класс ситуации).
    if (!suvidHold.reachTimeoutMsgSent) {
      SendMsg("Сувид: не вышли на рабочую температуру за 60 минут, нагрев выключается. Проверьте ТЭН, датчик куба и объём загрузки.", ALARM_MSG);
      set_buzzer(true);
      suvidHold.reachTimeoutMsgSent = true;
    }
    // Управление доходит сюда только при PowerOn (иначе возврат выше), то есть нагрев
    // всё ещё включён: повторяем, пока он действительно не выключится.
    if (!suvidHold.reachTimeoutStopQueued ||
        (uint32_t)(now - suvidHold.reachTimeoutStopMs) >= SUVID_STOP_RETRY_MS) {
      if (queue_samovar_command(SAMOVAR_POWER_OFF)) {
        suvidHold.reachTimeoutStopQueued = true;
        suvidHold.reachTimeoutStopMs = now;
      }
    }
  }

  const uint32_t holdMs = (uint32_t)SamSetup.SuvidHoldMinutes * 60000UL;
  if (holdMs > 0 && !suvidHold.fired && suvidHold.active && suvidHold.accumulatedMs >= holdMs) {
    set_buzzer(true);
    if (queue_samovar_command(SAMOVAR_POWER_OFF)) {
      SendMsg("Сувид: выдержка завершена, нагрев выключен.", NOTIFY_MSG);
      suvidHold.fired = true;
    } else if (!suvidHold.completionWarningSent) {
      SendMsg("Сувид: выдержка завершена, но штатное выключение не поставлено: очередь команд занята.", WARNING_MSG);
      suvidHold.completionWarningSent = true;
    }
  }
}

/**
 * @brief [T24.3] Применяет к нагревателю состояние, вычисленное термостатом
 *        check_alarm_suvid() (SysTicker, core 0). Вызывается из loop() (core 1),
 *        а не из надзорной задачи: setHeaterPosition() в сборке без SAMOVAR_USE_POWER
 *        блокируется на vTaskDelay(50), что недопустимо внутри 1-секундного тика
 *        аварийного надзора.
 */
inline void suvid_tick() {
  if (Samovar_Mode != SAMOVAR_SUVID_MODE) return;
  setHeaterPosition(suvidHeaterOn);
}
