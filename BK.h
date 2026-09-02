#pragma once

#include <Arduino.h>
#include "Samovar.h"
#include "samovar_api.h"
#include "runtime_helpers.h"
#include "mode_common.h"

#ifdef USE_WATER_PUMP
#include "pumppwm.h"
#endif

#ifdef USE_MQTT
#include "SamovarMqtt.h"
#endif

// [A1 п.1] Регулятор при старте БК стартует в POWER_SPEED_MODE (разгон на
// максимум). Переход на рабочую мощность SamSetup.BKPower должен произойти РОВНО
// ОДИН РАЗ - по факту закипания. current_power_mode_is(POWER_SPEED_MODE) для этого
// не годится: любой путь, который синхронно дёргает set_current_power() ДО
// закипания (например, пред-авария по воде во время разгона,
// mode_handle_water_pre_alarm_if_due -> mode_water_alarm_power_base), уводит
// регулятор из SPEED навсегда, и переход на BKPower пропускается молча. Флаг
// живёт независимо от текущего режима регулятора: взводится при успешном старте
// нагрева, снимается либо при штатном применении BKPower по кипению, либо (чтобы
// не потерять переход) сразу в момент срабатывания пред-аварии по воде, либо при
// завершении БК.
static bool bk_work_power_pending = false;

// [A1 п.1] Общая точка применения рабочей мощности БК - вызывается и по факту
// кипения, и (если кипение ещё не подтверждено) по пред-аварии воды, чтобы не
// дублировать #ifdef SAMOVAR_USE_POWER дважды.
static void bk_apply_work_power() {
#ifdef SAMOVAR_USE_POWER
  set_current_power(SamSetup.BKPower);
  // [9b] Мощность строки 0, если задана (>0), перекрывает BKPower - тот же
  // принцип "0 = не трогать", что и в apply_program_power_row/run_dist_program.
  // ProgramLen > 0 гарантирует, что program[0] - реальная первая строка (9a
  // распространяет на БК то же правило валидации, что и у DIST: первая
  // ненулевая мощность обязана быть абсолютной).
  if (ProgramLen > 0) apply_program_power_row(program[0].Power);
#else
  set_current_power_mode_value(POWER_WORK_MODE);
  heater_boost_output_off();
#endif
  bk_work_power_pending = false;
  // [9b] Тот же момент, что distiller_proc() отмечает вызовом run_dist_program(0)
  // сразу после старта нагрева - здесь это откладывалось до факта закипания,
  // потому что ДО этого момента BKPower ещё не действует. run_bk_program(0)
  // не трогает program[0] (num>0 внутри неё ложно), а взводит ProgramNum/
  // сообщение/уставку воды.
  run_bk_program(0);
}

// [9b] По образцу run_dist_program (distiller.h): применяет ёмкость/мощность
// ЗАВЕРШИВШЕЙСЯ строки (num-1) при переходе на num, затем взводит уставку
// воды из НОВОЙ строки num. Разделение оправдано так же, как в дистилляции:
// Power/capacity строки - это "что включить, когда её порог достигнут", а
// Temp (уставка пара) - состояние, которое начинает действовать С МОМЕНТА
// входа в строку.
void run_bk_program(uint8_t num) {
  if (num > 0 && num - 1 < ProgramLen) {
    if (!program_type_empty(program[num - 1].WType)) {
      set_capacity(program[num - 1].capacity_num);
#ifdef SAMOVAR_USE_POWER
      apply_program_power_row(program[num - 1].Power);
#endif
    }
  }

  if (num >= ProgramLen || program_type_empty(program[num].WType)) {
    if (ProgramNum < ProgramLen) {
      ProgramNum = ProgramLen;
      SendMsg("Выполнение программ закончилось, продолжение отбора", NOTIFY_MSG);
    }
    return;
  }

  ProgramNum = num;
  SendMsg("Переход к строке программы №" + (String)(num + 1), NOTIFY_MSG);
#ifdef USE_WATER_PUMP
  // [9b] Обнуление таймера ожидания при КАЖДОМ включении авторежима (а не
  // только через кнопку "Автомат") держит инвариант "первая правка ШИМ не
  // раньше чем через BK_WATER_ADJUST_PERIOD_MS" без скачка сразу после
  // перехода на строку с уставкой.
  bk_steam_setpoint = program[num].Temp;
  bk_water_auto = program[num].Temp > 0;
  bk_water_last_adjust_ms = millis();
#endif
}

/**
 * @brief Установить температуру воды (ШИМ).
 * @param duty Значение ШИМ
 */
void set_water_temp(float duty) {
#ifdef USE_WATER_PUMP
  // [9b] Ручной ввод ШИМ перехватывает управление у авторежима - иначе на
  // следующем тике check_alarm_bk() шаговый регулятор перезапишет то, что
  // оператор только что выставил вручную.
  if (bk_water_auto) {
    bk_water_auto = false;
    SendMsg("Вода дефлегматора: ручное управление", NOTIFY_MSG);
  }
  bk_pwm = duty;
  // Пока идёт плавный пуск насоса (wp_count < 10, pumppwm.h), check_alarm_bk
  // ещё раз запишет стартовое значение поверх этого - ручная уставка
  // применится по окончании пуска, через несколько секунд. Это осознанно:
  // пуск защищает насос, а bk_pwm уже хранит нужное значение.
  if (pump_started) {
    pump_pwm.write(bk_pwm);
    water_pump_speed = bk_pwm;
  }
#else
  SendMsg(("Управление насосом не поддерживается вашим оборудованием"), NOTIFY_MSG);
#endif
}

#ifdef USE_WATER_PUMP
// [9b] Итерация по program[i].Temp с границей ProgramLen - НЕ program[ProgramNum].WType
// (см. tools/smoke_program_type_contract.py: запрет прямого чтения текущего
// типа строки через живой ProgramNum). Здесь читается ДРУГОЕ поле (Temp) и по
// ВСЕМ строкам, а не по текущей - под запрет контракта не подпадает.
static bool bk_program_requires_steam_sensor() {
  for (uint8_t i = 0; i < ProgramLen; i++) {
    if (program[i].Temp > 0) return true;
  }
  return false;
}
#endif

/**
 * @brief Основной цикл работы бражной колонны. Запускает нагрев, проверяет условия завершения.
 */
void bk_proc() {

  if (SamovarStatusInt != SAMOVAR_STATUS_BK) return;

  // [A1 п.2] До первого включения нагрева (PowerOn == false) невалидный или не
  // назначенный датчик куба - это отказ КОМАНДЫ СТАРТА, а не авария процесса:
  // process_sensor_failed() взводит аварийную защёлку (heater_safety_latched()),
  // снимаемую только перезагрузкой, а нагрев ещё ни разу не включался. Отказываем
  // тем же путём, что и distiller.h (PKG-B, П3). Если защёлка уже взведена -
  // не перехватываем, даём дойти до mode_run_heating_start, который откажет
  // штатным сообщением про защёлку.
  if (PowerOn) {
    if (!sensor_valid(TankSensor) && process_sensor_failed("БК", "куба")) return;
  } else if (!sensor_valid(TankSensor) && !heater_safety_latched()) {
    mode_cancel_process_start("БК не запущена: датчик куба не назначен или не отвечает");
    return;
  }

#ifdef USE_WATER_PUMP
  // [9b] Если хотя бы одна строка программы задаёт уставку пара (Temp > 0),
  // датчик пара обязателен - без него авторежим воды не сможет включиться, и
  // колонна либо останется без охлаждения дефлегматора, либо (что хуже)
  // авторежим включится и тут же уйдёт в аварию по process_sensor_failed().
  // Отказ - мягкий, только до первого включения нагрева (симметрично проверке
  // датчика куба выше): !heater_safety_latched() исключает маскирование уже
  // взведённой защёлки, !PowerOn - что это именно КОМАНДА СТАРТА, а не авария
  // внутри уже идущего процесса (внутри процесса невалидный датчик пара при
  // auto ловит process_sensor_failed("БК","пара") в check_alarm_bk).
  if (!PowerOn && !heater_safety_latched() && !sensor_valid(SteamSensor) &&
      bk_program_requires_steam_sensor()) {
    mode_cancel_process_start("БК не запущена: программа требует датчик пара");
    return;
  }
#endif

  if (!PowerOn || mode_heating_start_pending(SAMOVAR_STATUS_BK)) {
    if (mode_run_heating_start(
          SAMOVAR_STATUS_BK,
          "Ошибка создания файла лога. Старт БК отменён.",
          "Описание сессии занято. Старт БК отменён.",
          String("BK"),
          "Включен нагрев бражной колонны",
          false) != MODE_HEATING_START_SUCCEEDED) return;
    bk_work_power_pending = true;
  }

  // [A1 п.6] Плато проверяется ДО DistTemp - для БК это новая функциональность,
  // порядок задан явно в плане (симметрии с distiller.h здесь намеренно нет: там
  // это чистый вынос уже существующего порядка).
  if (dist_plateau_finish_due()) {
    bk_finish();
    return;
  }

  if (TankSensor.avgTemp >= SamSetup.DistTemp) {
    bk_finish();
    return;
  }

  // [9b] Переход по строкам - после обеих проверок финиша (симметрично тому,
  // что финиш всегда важнее продолжения программы), перед задержкой тика.
  // [ревью 02.09.2026] Пока рабочая мощность не применена (разгон до кипения),
  // строки не исполняются: иначе run_bk_program(0) из bk_apply_work_power()
  // откатил бы уже ушедший вперёд ProgramNum и задвоил переключение ёмкости.
  if (PowerOn && !bk_work_power_pending && ProgramNum < ProgramLen &&
      !program_type_empty(program[ProgramNum].WType) &&
      program_threshold_row_done(program[ProgramNum])) {
    run_bk_program(ProgramNum + 1);
  }

  vTaskDelay(10 / portTICK_PERIOD_MS);
}

/**
 * @brief Проверка и обработка аварийных ситуаций в работе бражной колонны.
 */
void check_alarm_bk() {
  //сбросим паузу события безопасности
  mode_clear_alarm_pause_if_expired();

  if (PowerOn && !mode_check_powered_cooling_sensors("БК")) return;

#ifdef SAMOVAR_USE_POWER
  check_power_error();
#endif

#ifdef USE_WATER_PUMP
  bool coolingOpenedThisTick = false;
#endif

  if (mode_should_open_cooling(false, true, true)) {
    open_valve(true, true);
#ifdef USE_WATER_PUMP
    set_pump_pwm(bk_pwm);
    coolingOpenedThisTick = true;
#endif
  }

#ifdef USE_WATER_PUMP
  // [БК п.3] После переработки плавного пуска (pumppwm.h) насос сам доводит duty
  // до целевого bk_pwm за первые 10 вызовов set_pump_pwm() - сравнение с
  // PWM_LOW_VALUE*40 (старое дефолтное значение bk_pwm) больше не имеет смысла,
  // счётчика wp_count достаточно. Счётчик останавливается на 10, поэтому после
  // пуска bk_pwm переписывается каждый тик - как и раньше, идемпотентно.
  if (!coolingOpenedThisTick && valve_status && pump_started && wp_count <= 10) {
    set_pump_pwm(bk_pwm);
  }
#endif

  // [П4.1] check_boiling() должна вызываться безусловно каждый тик: если внутри if
  // ниже сработает короткое замыкание на Steam/Pipe>39 (режим мощности сменится
  // раньше), сам check_boiling() больше не вызовется и boil_started может навсегда
  // остаться false, из-за чего get_alcohol()/get_steam_alcohol() отдают заглушку 100.
  // check_boiling() возвращает true ТОЛЬКО в тот единственный вызов, когда кипение
  // обнаружено впервые (дальше boil_started=true и guard всегда отдаёт false) -
  // поэтому вызываем её РОВНО ОДИН раз за тик и переиспользуем результат ниже.
  bool boilingNow = check_boiling();

  //Определяем, что началось кипение - вода охлаждения начала нагреваться
  if (bk_work_power_pending && (boilingNow || SteamSensor.avgTemp > CHANGE_POWER_MODE_STEAM_TEMP || PipeSensor.avgTemp > CHANGE_POWER_MODE_STEAM_TEMP)) {
    if (!boilingNow) {
      record_boiling_evidence(
          SteamSensor.avgTemp > CHANGE_POWER_MODE_STEAM_TEMP
              ? BOILING_EVIDENCE_STEAM
              : BOILING_EVIDENCE_PIPE);
    }
    bk_apply_work_power();
  }

  if (mode_should_close_cooling(SamSetup.SetWaterTemp - DELTA_T_CLOSE_VALVE, false)) {
    open_valve(false, true);
    mode_stop_cooling_pump_if_started();
  }

  //Проверяем, что температурные параметры не вышли за предельные значения
  mode_request_overheat_emergency_if_needed();

  //Проверим, что вода подается
  mode_request_water_flow_emergency_if_needed();

  // [A1 п.1] Если рабочая мощность ещё не применена (кипение не подтверждено), а
  // пред-авария по воде вот-вот снизит мощность от текущего фактического
  // напряжения (mode_water_alarm_power_base читает target_power_volt/
  // current_power_volt, НЕ SamSetup.BKPower) - применяем BKPower синхронно
  // ПЕРЕД общим хелпером, чтобы снижение считалось от рабочей точки, а не от
  // разгонного максимума, и чтобы переход не потерялся насовсем.
  if (bk_work_power_pending && mode_water_pre_alarm_due()) {
    bk_apply_work_power();
  }
  mode_handle_water_pre_alarm_if_due();

#ifdef USE_WATER_PUMP
  // [9b] Шаговый регулятор охлаждения дефлегматора. Не в одном if с остальными
  // авариями - process_sensor_failed() не должен прерывать функцию через
  // return (см. mode_request_overheat_emergency_if_needed() выше - её вызовы
  // тоже не гейтятся ранним return).
  if (bk_water_auto) {
    if (!sensor_valid(SteamSensor)) {
      // [Решение владельца] Пропавший датчик пара во время авторежима - авария,
      // а не откат в ручной режим: process_sensor_failed синхронно останавливает
      // нагрев с защёлкой, как при отказе датчика куба.
      process_sensor_failed("БК", "пара");
    } else if (valve_status && wp_count >= 10 &&
               (uint32_t)(millis() - bk_water_last_adjust_ms) >= BK_WATER_ADJUST_PERIOD_MS) {
      bk_water_last_adjust_ms = millis();
      float diff = SteamSensor.avgTemp - bk_steam_setpoint;
      if (diff >= BK_WATER_DEADBAND) {
        bk_pwm += BK_WATER_PWM_STEP;
      } else if (diff <= -BK_WATER_DEADBAND && WaterSensor.avgTemp < ALARM_WATER_TEMP - 5) {
        // Защита по воде важнее уставки пара: если вода уже в пред-аварийной
        // зоне (>= ALARM_WATER_TEMP - 5), шаг ВНИЗ запрещён - см. ветку выше,
        // где шаг ВВЕРХ (diff >= DEADBAND) не имеет такого ограничения вовсе.
        bk_pwm -= BK_WATER_PWM_STEP;
      }
      bk_pwm = constrain(bk_pwm, PWM_LOW_VALUE * 10, 1023);
      set_pump_pwm(bk_pwm);
    }
  }
#endif
  vTaskDelay(10 / portTICK_PERIOD_MS);
}

void bk_finish() {
  ProgramNum = 0;
  startval = SAMOVAR_STARTVAL_IDLE;
  bk_work_power_pending = false;
  stop_process("Работа бражной колонны завершена");
}

#ifdef USE_WATER_PUMP
// [9b] Кнопка "Автомат" (WebServer.ino, действие waterauto). web_command()
// проверяет предусловия ДО постановки pending-флага (в async_tcp), но между
// этим и вызовом здесь (в loop()) процесс мог уже закончиться или строка
// программы - смениться, поэтому ниже те же проверки повторяются по факту.
// "Без скачка": bk_pwm не трогаем, только взводим auto и уставку с точки
// текущего ШИМ - следующий шаг регулятора отталкивается от факта, а не от
// произвольного стартового значения.
void bk_water_auto_resume() {
  // [9b, CRITICAL-фикс ревью] Старый guard `ProgramNum >= ProgramLen` не ловит
  // завершение через bk_finish(): там ProgramNum=0, а ProgramLen НЕ обнуляется -
  // между проверками web_command() (async_tcp) и этим тиком (loop()) процесс
  // мог уже закончиться. Проверяем ещё и статус/PowerOn - тот же признак
  // "процесс идёт", что и в check_alarm_bk() (см. `if (SamovarStatusInt !=
  // SAMOVAR_STATUS_BK) return;` выше).
  if (!PowerOn || SamovarStatusInt != SAMOVAR_STATUS_BK || ProgramNum >= ProgramLen) return;
  if (program[ProgramNum].Temp == 0) return;   // [9b] строка без уставки - не включаем
  bk_steam_setpoint = program[ProgramNum].Temp;
  bk_water_auto = true;
  bk_water_last_adjust_ms = millis();
}
#endif

// [9b] Общая точка сброса состояния авторежима воды - вызывается из
// reset_process_state() (sensorinit.h, включён ПОСЛЕ BK.h). Объявлена без
// #ifdef USE_WATER_PUMP, чтобы reset_process_state() могла звать её
// безусловно в обеих сборках (сама она приводов не касается вовсе).
void bk_reset_water_auto() {
  bk_water_auto = false;
  bk_steam_setpoint = 0.0f;
  bk_water_last_adjust_ms = 0;
}
