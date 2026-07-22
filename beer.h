#pragma once

#include <Arduino.h>
#include "Samovar.h"
#include "samovar_api.h"
#include "runtime_helpers.h"
#include "program_io.h"
#include "SamovarMqtt.h"
#include "pumppwm.h"

#define TEMP_HISTORY_SIZE 10  // Размер буфера истории температур (точек)
#define BOILING_DETECT_THRESHOLD 0.08  // Порог по стандартному отклонению, °C
#define MIN_BOILING_TEMP 98.0  // Минимальная температура кипения (с учетом погрешности)
#define STABLE_WINDOWS_REQUIRED 5 // Кол-во стабильных окон подряд для фиксации кипения
#define MAX_TREND_ABS_PER_SEC 0.02 // Макс. модуль тренда в °C/с для стабильности

struct BoilingDetector {
    float tempHistory[TEMP_HISTORY_SIZE];
    uint8_t historyIndex = 0;
    uint8_t samplesFilled = 0;
    bool isBoiling = false;
    unsigned long lastUpdateTime = 0;
    uint8_t stableCount = 0;
};

BoilingDetector boilingDetector;

static inline void resetBoilingDetector() {
    boilingDetector.historyIndex = 0;
    boilingDetector.samplesFilled = 0;
    boilingDetector.stableCount = 0;
    boilingDetector.isBoiling = false;
    boilingDetector.lastUpdateTime = 0;
    for (int i = 0; i < TEMP_HISTORY_SIZE; i++) boilingDetector.tempHistory[i] = 0;
}

/**
 * @brief Проверяет, началось ли кипение по истории температур.
 *        Алгоритм: раз в секунду добавляет измерение, после заполнения окна
 *        считает среднее, стандартное отклонение и тренд; при малой дисперсии
 *        и малом тренде фиксирует стабильность, после N стабильных окон — кипение.
 * @param currentTemp Текущая температура
 * @return true, если кипение началось, иначе false
 */
bool isBoilingStarted(float currentTemp) {
    unsigned long currentTime = millis();

    // Обновляем историю не чаще раза в секунду
    if (currentTime - boilingDetector.lastUpdateTime < 1000) {
        return boilingDetector.isBoiling;
    }
    boilingDetector.lastUpdateTime = currentTime;

    // Добавляем точку в кольцевой буфер
    boilingDetector.tempHistory[boilingDetector.historyIndex] = currentTemp;
    if (boilingDetector.samplesFilled < TEMP_HISTORY_SIZE) boilingDetector.samplesFilled++;
    boilingDetector.historyIndex = (boilingDetector.historyIndex + 1) % TEMP_HISTORY_SIZE;

    // До заполнения окна и/или пока ниже порога кипения — не детектируем
    if (boilingDetector.samplesFilled < TEMP_HISTORY_SIZE || currentTemp < MIN_BOILING_TEMP) {
        boilingDetector.stableCount = 0;
        return false;
    }

    // Средняя температура окна
    float sum = 0.0f;
    for (int i = 0; i < TEMP_HISTORY_SIZE; i++) sum += boilingDetector.tempHistory[i];
    float avg = sum / TEMP_HISTORY_SIZE;

    // Стандартное отклонение
    float varSum = 0.0f;
    for (int i = 0; i < TEMP_HISTORY_SIZE; i++) {
        float d = boilingDetector.tempHistory[i] - avg;
        varSum += d * d;
    }
    float stddev = sqrtf(varSum / TEMP_HISTORY_SIZE);

    // Тренд: разница между последней и самой старой точкой, сек ~ размер окна-1
    int lastIdx = (boilingDetector.historyIndex + TEMP_HISTORY_SIZE - 1) % TEMP_HISTORY_SIZE;
    int firstIdx = boilingDetector.historyIndex; // самая старая точка
    float slope = (boilingDetector.tempHistory[lastIdx] - boilingDetector.tempHistory[firstIdx]) /
                  float(TEMP_HISTORY_SIZE - 1);

    bool stableNow = (stddev <= BOILING_DETECT_THRESHOLD) && (fabsf(slope) <= MAX_TREND_ABS_PER_SEC);
    if (stableNow) {
        if (boilingDetector.stableCount < 255) boilingDetector.stableCount++;
    } else {
        boilingDetector.stableCount = 0;
    }

    if (boilingDetector.stableCount >= STABLE_WINDOWS_REQUIRED) {
        boilingDetector.isBoiling = true;
        return true;
    }

    return boilingDetector.isBoiling;
}

inline bool beer_control_sensor(uint8_t sensorId, const DSSensor*& sensor, const char*& sensorName) {
  switch (sensorId) {
    case 0:
      sensor = &TankSensor;
      sensorName = "куба";
      return true;
    case 1:
      sensor = &WaterSensor;
      sensorName = "воды";
      return true;
    case 2:
      sensor = &PipeSensor;
      sensorName = "царги";
      return true;
    case 3:
      sensor = &SteamSensor;
      sensorName = "пара";
      return true;
    case 4:
      sensor = &ACPSensor;
      sensorName = "ТСА";
      return true;
    default:
      sensor = nullptr;
      sensorName = "";
      return false;
  }
}

/**
 * @brief Проверяет ВСЕ заполненные строки программы затирания при старте: тип
 *        этапа (MPBCFWLA) и корректность номера датчика температуры.
 *        НЕ проверяет физическую доступность датчика (sensor_valid) — это
 *        аппаратная авария, остаётся рантайм-проверкой (process_sensor_failed).
 */
inline bool beer_validate_program(String& errorMessage) {
  if (ProgramLen == 0 || program_type_empty(program[0].WType)) {
    errorMessage = "Ошибка программы Пиво: строка не задана";
    return false;
  }
  for (uint8_t i = 0; i < ProgramLen && i < PROGRAM_END; i++) {
    if (program_type_empty(program[i].WType)) break;
    if (!program_type_one_of(program[i].WType, beer_program_parse_spec().allowedTypes)) {
      errorMessage = "Ошибка программы: неверный тип этапа в строке " + String(i + 1);
      return false;
    }
    const DSSensor* rowSensor = nullptr;
    const char* rowSensorName = "";
    if (!beer_control_sensor(program[i].TempSensor, rowSensor, rowSensorName)) {
      errorMessage = "Ошибка программы: неверный датчик температуры в строке " + String(i + 1);
      return false;
    }
  }
  return true;
}

/**
 * @brief Основной цикл запуска процесса затирания. Инициализация и старт программы.
 */
void beer_proc() {
  if (SamovarStatusInt != SAMOVAR_STATUS_BEER) return;

  if (startval == SAMOVAR_STARTVAL_BEER_START && !PowerOn) {
    String programError;
    if (!beer_validate_program(programError)) {
      mode_cancel_process_start(programError);
      return;
    }
    const DSSensor* controlSensor = nullptr;
    const char* controlSensorName = "";
    beer_control_sensor(program[0].TempSensor, controlSensor, controlSensorName);
    if (!sensor_valid(*controlSensor) && process_sensor_failed("Пиво", controlSensorName)) return;

    // [PKG-B п.4] Пока не завершён OFF-переход нагрева, set_power(true) молча откажет,
    // а create_data() каждый тик зря перезапишет SPIFFS-лог (+MQTT). Отменяем старт.
    if (power_transition_active()) {
      mode_cancel_process_start("Выключение нагрева ещё не завершено. Старт затирания отменён.");
      return;
    }

    // Сброс детектора кипения при запуске процесса
    resetBoilingDetector();
    if (!create_data()) {
      mode_cancel_process_start("Ошибка создания файла лога. Старт затирания отменён.");
      return;
    }
#ifdef USE_MQTT
    String sessionDescription;
    if (!copy_mqtt_session_description(sessionDescription, pdMS_TO_TICKS(50))) {
      mode_cancel_process_start("Описание сессии занято. Старт затирания отменён.");
      mode_warn_log_close_failed();
      return;
    }
    MqttSendMsg(String(chipId) + "," + SamSetup.TimeZone + "," + SAMOVAR_VERSION + "," + get_beer_program() + "," + sessionDescription, "st");
#endif
    set_power(true);
    if (!PowerOn) return;
    run_beer_program(0);
  }
  vTaskDelay(10 / portTICK_PERIOD_MS);
}

/**
 * @brief Переход к этапу программы с номером num, обработка сообщений и сброс переменных этапа.
 * @param num Номер этапа программы
 */
void run_beer_program(uint8_t num) {
  if (Samovar_Mode != SAMOVAR_BEER_MODE || !PowerOn) return;
  if (startval == SAMOVAR_STARTVAL_BEER_START) startval = SAMOVAR_STARTVAL_BEER_HEATING;

  uint8_t targetProgram = num;
  if (ProgramLen == 0 || targetProgram >= ProgramLen || targetProgram >= PROGRAM_END) {
    targetProgram = PROGRAM_END;
    SetScriptOff = 1;
  }

  if (targetProgram > 0 && targetProgram <= PROGRAM_END && program[targetProgram - 1].WType == 'L' && loop_lua_fl) {
    SetScriptOff = 1;
  }

  if (targetProgram == PROGRAM_END) {
    beer_finish();
    return;
  }

  ProgramNum = targetProgram;
  begintime = 0;
  msgfl = true;

  // [п.11] Несмежная строка 'B' — это НОВОЕ кипячение на остывшей жидкости:
  // сбрасываем накопленную историю/стабильность детектора. Смежные 'B'->'B'
  // (продолжение одного кипячения ради разных всыпок хмеля) детектор не трогаем.
  if (program[ProgramNum].WType == 'B' &&
      (ProgramNum == 0 || program_type_at(ProgramNum - 1) != 'B')) {
    resetBoilingDetector();
  }

  if (program[ProgramNum].WType == 'A') {
    StartAutoTune();
  }

  String msg = "Переход к строке программы №" + String((ProgramNum + 1));
  if (program[ProgramNum].WType == 'M') {
    msg += "; Нагрев до температуры засыпи солода: " + String(program[ProgramNum].Temp) + "°";
  } else if (program[ProgramNum].WType == 'P') {
    msg += "; Температурная пауза: " + String(program[ProgramNum].Temp) + "°, время: " + String(program[ProgramNum].Time) + " мин";
  } else if (program[ProgramNum].WType == 'B') {
    msg += "; Кипячение, время: " + String(program[ProgramNum].Time) + " мин";
  } else if (program[ProgramNum].WType == 'C') {
    msg += "; Охлаждение до температуры: " + String(program[ProgramNum].Temp) + "°";
  } else if (program[ProgramNum].WType == 'F') {
    msg += "; Ферментация, поддержание температуры: " + String(program[ProgramNum].Temp) + "°";
  } else if (program[ProgramNum].WType == 'W') {
    msg += "; Режим ожидания";
  }

  if (SamSetup.ChangeProgramBuzzer) {
    set_buzzer(true);
    SendMsg(msg, ALARM_MSG);
  } else {
    SendMsg(msg, NOTIFY_MSG);
  }

  //сбрасываем переменные для мешалки и насоса
  alarm_c_low_min = 0;  //мешалка вкл
  alarm_c_min = 0;  //мешалка пауза
  currentstepcnt = 0; //счетчик циклов мешалки
}

/**
 * @brief Завершает процесс затирания: выключает насос, нагрев, клапаны, сбрасывает состояния.
 */
void beer_finish() {
  if (valve_status) {
    open_valve(false, true);
  }
  // Сброс детектора кипения при завершении процесса
  resetBoilingDetector();
  set_mixer_state(false, false);
#ifdef USE_WATER_PUMP
  set_pump_pwm(0);
  pump_started = false;
#endif
  setHeaterPosition(false);
  heater_state = false;
  ProgramNum = 0;
  startval = SAMOVAR_STARTVAL_IDLE;
  stop_process("Программа затирания завершена");
}

/**
 * @brief Штатно останавливает варку из-за ОШИБКИ КОНФИГУРАЦИИ программы,
 *        обнаруженной в рантайме. В отличие от request_emergency_stop НЕ взводит
 *        аварийную защёлку: достаточно поправить программу и запустить заново.
 */
void beer_abort_config_error(const String& reason) {
  SendMsg(reason, ALARM_MSG);
  beer_finish();
}

/**
 * @brief Проверяет превышение предельных температур воды/ТСА на этапе охлаждения
 *        и инициирует аварийный останов. Надзорная функция alarm-пути (mode_alarm_beer),
 *        работает независимо от каденции beer_stage_tick() в loop().
 */
inline void beer_check_cooling_limits() {
  if (current_program_type() != 'C') return;
  mode_request_overheat_emergency_if_needed();
}

/**
 * @brief Проверяет и управляет состоянием процесса затирания, включая нагрев, охлаждение, паузы и кипячение.
 *        Каденция 1 Гц через внутренний гейт по millis(). Раньше жила в
 *        check_alarm_beer(), вызываемой из SysTicker (ядро 0, alarm-путь);
 *        теперь это beer_stage_tick(), вызываемая из loop() (ядро 1) через
 *        dispatch_loop. Надзор за аварийными температурными лимитами вынесен в
 *        beer_check_cooling_limits() и остаётся в alarm-пути (mode_alarm_beer).
 */
void beer_stage_tick() {
  static unsigned long lastBeerTickMs = 0;
  const unsigned long nowMs = millis();
  if (nowMs - lastBeerTickMs < 1000) return;
  lastBeerTickMs = nowMs;

  if (startval <= SAMOVAR_STARTVAL_BEER_START) return;

  float temp = 0;
  float tempDelta = 0;
  const DSSensor* controlSensor = nullptr;
  const char* controlSensorName = "";
  if (!beer_control_sensor(program[ProgramNum].TempSensor, controlSensor, controlSensorName)) {
    beer_abort_config_error("Ошибка программы: неверный датчик температуры в строке " + String(ProgramNum + 1));
    return;
  }
  if (!sensor_valid(*controlSensor) && process_sensor_failed("Пиво", controlSensorName)) return;
  temp = controlSensor->avgTemp;
  tempDelta = controlSensor->SetTemp;
  ProgramType currentType = current_program_type();

  //Обрабатываем программу

  //Проверяем, что клапан воды охлаждения не открыт, когда не нужно
  if (currentType != 'C' && currentType != 'F' && valve_status && PowerOn && currentType != 'L') {
    //Закрываем клапан воды
    open_valve(false, false);
  }

  //Если тип программы неизвестен или пуст - безопасно выключаем нагрев
  if (currentType != 'L' && currentType != 'W' &&
      currentType != 'A' && currentType != 'M' &&
      currentType != 'P' && currentType != 'F' &&
      currentType != 'C' && currentType != 'B') {
    beer_abort_config_error("Ошибка программы: неизвестный тип этапа в строке " + String(ProgramNum + 1));
    return;
  }

  //Если программа - Lua - ждем, ничего не делаем
  if (currentType == 'L') {
    return;
  }

  //Если программа - ожидание - ждем, ничего не делаем
  if (currentType == 'W') {
    if (begintime == 0) {
      begintime = millis();
      setHeaterPosition(false);
      open_valve(false, false);
    }
    check_mixer_state(); // Управление мешалкой и насосом по параметрам программы
    return;
  }

  //Если режим Автотюнинг
  if (currentType == 'A') {
    if (tuning) {
      set_heater_state(program[ProgramNum].Temp, temp);
    } else {
      if (!queue_samovar_command(SAMOVAR_BEER_NEXT)) {
        request_emergency_stop("Очередь команд занята: завершение автотюнинга пива не поставлено");
      }
    }
    return;
  }

  //Если режим Засыпь солода или Пауза
  if (currentType == 'M' || currentType == 'P') {
    set_heater_state(program[ProgramNum].Temp, temp);
  }

  //Если режим Брага
  if (currentType == 'F') {
    //Если температура меньше целевой - греем, иначе охлаждаем.
    if (temp < program[ProgramNum].Temp - tempDelta) {
      if (valve_status) {
        //Закрываем клапан воды
        open_valve(false, false);
      }
      //Поддерживаем целевую температуру
      set_heater_state(program[ProgramNum].Temp, temp);
    } else if (temp > program[ProgramNum].Temp + tempDelta) {
      {
        if (!valve_status) {
          //Отключаем нагреватель
          setHeaterPosition(false);
          //Открываем клапан воды
          open_valve(true, false);
#ifdef USE_WATER_PUMP
          set_pump_pwm(1023);
          pump_started = true;
#endif
        }
      }
    } else {
      //Так как находимся в пределах температурной уставки, не нужно ни греть, ни охлаждать
      //Отключаем нагреватель
      setHeaterPosition(false);
      //Закрываем клапан воды, если температура в кубе чуть меньше температурной уставки, чтобы часто не щелкать клапаном
      if ((temp < program[ProgramNum].Temp + tempDelta - 0.1) && valve_status && PowerOn) {
        open_valve(false, false);
#ifdef USE_WATER_PUMP
        set_pump_pwm(0);
        pump_started = false;
#endif
      }
    }
  }

  if (currentType == 'M' && temp >= program[ProgramNum].Temp - tempDelta) {
    //Достигли температуры засыпи солода. Пишем об этом. Продолжаем поддерживать температуру. Переход с этой строки программы на следующую возможен только в ручном режиме
    if (startval == SAMOVAR_STARTVAL_BEER_HEATING) {
      set_buzzer(true);
      SendMsg(("Достигнута температура засыпи солода!"), NOTIFY_MSG);
    }
    startval = SAMOVAR_STARTVAL_BEER_WAIT_MALT;
  }

  if (currentType == 'P' && temp >= program[ProgramNum].Temp - tempDelta) {
    if (begintime == 0) {
      //Засекаем время для отсчета, сколько держать паузу
      begintime = millis();
      SendMsg("Достигнута температурная пауза " + String(program[ProgramNum].Temp) + "°. Ждем " + String(program[ProgramNum].Time) + " минут.", NOTIFY_MSG);
    }
  }

  //Если программа - охлаждение - ждем, когда температура в кубе упадет ниже заданной, и управляем водой для охлаждения
  if (currentType == 'C') {
    if (begintime == 0) {
      begintime = millis();
      setHeaterPosition(false);
      //Открываем клапан воды
      open_valve(true, false);
#ifdef USE_WATER_PUMP
      set_pump_pwm(1023);
      pump_started = true;
#endif
    }
    if (temp <= program[ProgramNum].Temp) {
      //Если температура упала
      //Закрываем клапан воды
      open_valve(false, false);
#ifdef USE_WATER_PUMP
      set_pump_pwm(0);
      pump_started = false;
#endif
      //запускаем следующую программу
      run_beer_program(ProgramNum + 1);
    }
  }

  //Если программа - кипячение
  if (currentType == 'B') {
    //Если предыдущая программа была программой кипячения - просто продолжаем кипятить.
    if (begintime == 0 && ProgramNum > 0 && program_type_at(ProgramNum - 1) == 'B') begintime = millis();

    if (begintime == 0) {
      //Определяем начало кипения
      if (isBoilingStarted(temp)) {
        msgfl = true;
        begintime = millis();
        SendMsg(("Начался режим кипячения"), NOTIFY_MSG);
      }
    }

    //Греем до температуры кипения, исходя из того, что датчик в кубе врет не сильно
    if (begintime == 0) {
      set_heater_state(BOILING_TEMP + 5, temp);
    } else {
      //Иначе поддерживаем температуру
      heater_state = true;
#ifdef SAMOVAR_USE_POWER
      //Устанавливаем заданное напряжение
      set_current_power(SamSetup.BVolt);
#else
      set_current_power_mode_value(POWER_WORK_MODE);
      heater_enable_outputs(SAFETY_HEATER_OUTPUT_MAIN);
#endif
      if (SamSetup.UseST) {
        heater_enable_outputs(SAFETY_HEATER_OUTPUT_BOOST);
      } else {
        digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);
      }
    }

    //Проверяем, что еще нужно держать паузу. За 30 секунд до окончания шлем сообщение
    if (begintime > 0 && msgfl && ((float)(millis() - begintime) / 1000 / 60 + 0.5 >= program[ProgramNum].Time)) {  // [C-13] overflow-safe: вычитание до каста
      set_buzzer(true);
      msgfl = false;
      SendMsg(("Засыпьте хмель!"), NOTIFY_MSG);
#ifdef __SAMOVAR_DEBUG
      Serial.println("Засыпьте хмель!");
#endif
      HopStepperStep();
    }
  }

  //Проверяем, что еще нужно держать паузу
  if (begintime > 0 && (currentType == 'B' || currentType == 'P') && ((float)(millis() - begintime) / 60000.0f >= program[ProgramNum].Time)) {
    //Запускаем следующую программу
    run_beer_program(ProgramNum + 1);
  }
  
  //Обрабатываем мешалку и насос
  check_mixer_state();

  vTaskDelay(10 / portTICK_PERIOD_MS);
}

/**
 * @brief Управляет состоянием мешалки и насоса в зависимости от этапа программы и времени.
 */
void check_mixer_state() {
  if (program[ProgramNum].capacity_num > 0) {
    //обрабатываем время включения и управляем мешалкой и насосом

    if (alarm_c_min > 0 && (int32_t)(millis() - alarm_c_min) >= 0) {  // [C-13] overflow-safe
      //завершили паузу мешалки
      alarm_c_min = 0;
      alarm_c_low_min = 0;
      set_mixer_state(false, false);
    }

    if ((alarm_c_low_min > 0) && ((int32_t)(millis() - alarm_c_low_min) >= 0)) {  // [C-13] overflow-safe
      //выключаем мешалку, если alarm_c_min > millis()
      alarm_c_low_min = 0;
      if (alarm_c_min > 0)
        set_mixer_state(false, false);
    }

    if (alarm_c_low_min == 0 && alarm_c_min == 0) {
      //включаем мешалку
      alarm_c_low_min = millis() + program[ProgramNum].Volume * 1000;
      if (program[ProgramNum].Power > 0) alarm_c_min = alarm_c_low_min + program[ProgramNum].Power * 1000;
      currentstepcnt++;
      bool dir = false;
      if (currentstepcnt % 2 == 0 && program[ProgramNum].Speed < 0) dir = true;
      set_mixer_state(true, dir);
    }

  } else {
    if (mixer_status) {
      //если мешалка или насос работают, их нужно выключить, так как в этой строке программы они не нужны
      set_mixer_state(false, false);
    }
  }
}

/**
 * @brief Включает или выключает мешалку и насос, а также управляет направлением вращения.
 * @param state true — включить, false — выключить
 * @param dir true — реверс, false — прямое вращение
 */
void set_mixer_state(bool state, bool dir) {
  mixer_status = state;
  //Serial.println("State = " + String(state) + "; DIR = " + String(dir) + "; alarm_c_min = " + String(alarm_c_min) + "; alarm_c_low_min = " + String(alarm_c_low_min));
  if (state) {
    //включаем мешалку
    if (BitIsSet(program[ProgramNum].capacity_num, 0)) {
      //включаем реле 2
      digitalWrite(RELE_CHANNEL2, SamSetup.rele2);
      //включаем I2CStepper шаговик
	      if (i2c_stepper_mixer_present()) {
	        int tm = abs(program[ProgramNum].Volume);
	        if (tm == 0) tm = 10;
	        set_stepper_by_time(20, dir, tm);
	      }
    }
    if (BitIsSet(program[ProgramNum].capacity_num, 1)) {
#ifdef USE_WATER_PUMP
      //включаем SSD реле
      set_pump_pwm(1023);
#endif
	      //включаем I2CStepper реле 1
	      if (i2c_stepper_mixer_present() || i2c_stepper_pump_present()) {
	        set_mixer_pump_target(1);
	      }
    }
  } else {
    //выключаем реле 2
    digitalWrite(RELE_CHANNEL2, !SamSetup.rele2);
#ifdef USE_WATER_PUMP
    //выключаем SSD реле
    set_pump_pwm(0);
#endif
	    //выключаем I2CStepper шаговик
	    if (i2c_stepper_mixer_present()) {
	      set_stepper_by_time(0, 0, 0);
	    }
	    //выключаем I2CStepper реле 1
	    if (i2c_stepper_mixer_present() || i2c_stepper_pump_present()) {
	      set_mixer_pump_target(0);
	    }
  }
}

/**
 * @brief Управляет состоянием нагревателя по ПИД-регулятору и логике разгона.
 * @param setpoint Целевая температура
 * @param temp Текущая температура
 */
void set_heater_state(float setpoint, float temp) {
#ifdef SAMOVAR_USE_POWER
  //Если дельта большая и не тюнинг, включаем разгонный тэн, иначе выключаем
  if (setpoint - temp > ACCELERATION_HEATER_DELTA && !tuning) {
    if (!acceleration_heater) {
      acceleration_heater = heater_enable_outputs(SAFETY_HEATER_OUTPUT_BOOST);
    }
  } else {
    if (acceleration_heater) {
      digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);
      acceleration_heater = false;
    }
  }
#endif

  if (setpoint - temp > HEAT_DELTA && !tuning) {
    heater_state = true;
#ifdef SAMOVAR_USE_POWER
    vTaskDelay(5 / portTICK_PERIOD_MS);
    //set_power_mode(POWER_SPEED_MODE);
    set_current_power(SamSetup.BVolt);
#else
    set_current_power_mode_value(POWER_WORK_MODE);
    heater_enable_outputs(SAFETY_HEATER_OUTPUT_MAIN | SAFETY_HEATER_OUTPUT_BOOST);
#endif
  } else {
    heaterPID.SetMode(AUTOMATIC);
    Setpoint = setpoint;
    Input = temp;

    if (tuning)  // run the auto-tuner
    {
      if (aTune.Runtime())  // returns 'true' when done
      {
        FinishAutoTune();
      }
    } else  // Execute control algorithm
    {
      heaterPID.Compute();
    }
    double dutyCycle = constrain(Output / 100.0, 0.0, 1.0);
#ifdef SAMOVAR_USE_POWER
    set_heater_regulator(dutyCycle);
#else
    set_heater(dutyCycle);
#endif
  }
}

#ifdef SAMOVAR_USE_POWER
/**
 * @brief Управляет UART-регулятором по доле мощности PID без медленного on/off ШИМ.
 * @param dutyCycle Доля мощности (0.0 - 1.0)
 */
inline void set_heater_regulator(double dutyCycle) {
  dutyCycle = constrain(dutyCycle, 0.0, 1.0);
  if (dutyCycle <= 0.0 || SamSetup.StbVoltage <= 0) {
    setHeaterPosition(false);
    return;
  }

#ifdef SAMOVAR_USE_SEM_AVR
  float regulatorTarget = SamSetup.StbVoltage * dutyCycle;
#else
  // PID задает долю мощности; для регулятора напряжения P ~= V^2 / R.
  float regulatorTarget = SamSetup.StbVoltage * sqrtf((float)dutyCycle);
#endif

  heater_state = true;
  set_current_power(regulatorTarget);
  if (current_power_mode_is(POWER_SLEEP_MODE)) {
    heater_state = false;
    return;
  }
  check_power_error();
}
#endif

/**
 * @brief Устанавливает скважность ШИМ для нагревателя.
 * @param dutyCycle Скважность (0.0 - 1.0)
 */
void set_heater(double dutyCycle) {
  static uint32_t oldTime = 0;
  static uint32_t periodTime = 0;

  uint32_t newTime = millis();
  uint32_t offTime = periodInSeconds * 1000 * (dutyCycle);

  if (newTime < oldTime) {
    periodTime += (UINT32_MAX - oldTime + newTime);
  } else {
    periodTime += (newTime - oldTime);
  }
  oldTime = newTime;

  if (periodTime < offTime) {
    if (dutyCycle > 0.0) setHeaterPosition(true);
  } else if (periodTime >= periodInSeconds * 1000) {
    periodTime = 0;
    if (dutyCycle > 0.0) setHeaterPosition(true);
  } else {
    setHeaterPosition(false);
  }
}

/**
 * @brief Включает или выключает нагреватель (реле).
 * @param state true — включить, false — выключить
 */
void setHeaterPosition(bool state) {
  heater_state = state;

  if (state) {
#ifdef SAMOVAR_USE_POWER
    //Устанавливаем заданное напряжение
    set_current_power(SamSetup.StbVoltage);

    check_power_error();
#else
    set_current_power_mode_value(POWER_WORK_MODE);
    digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);
    heater_enable_outputs(SAFETY_HEATER_OUTPUT_MAIN);
    vTaskDelay(50 / portTICK_PERIOD_MS);
#endif
  } else {
#ifdef SAMOVAR_USE_POWER
    if (!current_power_mode_is(POWER_SLEEP_MODE)) {
      //delay(200); 5.13
      set_power_mode(POWER_SLEEP_MODE);
    }
    //Устанавливаем заданное напряжение
    //set_current_power(0);
#else
    set_current_power_mode_value(POWER_WORK_MODE);
    digitalWrite(RELE_CHANNEL1, !SamSetup.rele1);
    digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);
#endif
  }
}

/**
 * @brief Возвращает строковое описание текущей программы затирания.
 * @return Строка с описанием программы
 */
String get_beer_program() {
  return program_serialize_rows(0, PROGRAM_END, program_append_beer_row);
}

/**
 * @brief Устанавливает программу затирания из строки.
 * @param WProgram Строка с описанием программы
 */
ProgramParseResult set_beer_program(const String& WProgram) {
  return program_parse_lines(WProgram, beer_program_parse_spec());
}

/**
 * @brief Запускает автотюнинг ПИД-регулятора.
 */
void StartAutoTune() {
  // REmember the mode we were in
  ATuneModeRemember = heaterPID.GetMode();

  Output = 50;

  aTune.SetControlType(1);

  // set up the auto-tune parameters
  aTune.SetNoiseBand(aTuneNoise);
  aTune.SetOutputStep(aTuneStep);
  aTune.SetLookbackSec((int)aTuneLookBack);
  tuning = true;
}

/**
 * @brief Завершает автотюнинг ПИД-регулятора, применяет параметры и сохраняет профиль.
 */
void FinishAutoTune() {
  aTune.Cancel();
  tuning = false;

  SetupEEPROM profileCandidate{};
  profileCandidate = SamSetup;
  profileCandidate.Kp = aTune.GetKp();
  profileCandidate.Ki = aTune.GetKi();
  profileCandidate.Kd = aTune.GetKd();

  const PersistResult persistResult = save_profile_nvs(profileCandidate);
  if (persistResult == PERSIST_OK) {
    SamSetup = profileCandidate;
    WriteConsoleLog("Kp = " + (String)SamSetup.Kp);
    WriteConsoleLog("Ki = " + (String)SamSetup.Ki);
    WriteConsoleLog("Kd = " + (String)SamSetup.Kd);
  } else {
    String message = "PID autotune не сохранён: ";
    message += persist_result_code(persistResult);
    SendMsg(message, ALARM_MSG);
  }

  heaterPID.SetTunings(SamSetup.Kp, SamSetup.Ki, SamSetup.Kd);
  heaterPID.SetOutputLimits(0, 100);
  heaterPID.SetSampleTime(1000);
  set_heater_state(0, 50);
  heaterPID.SetMode(ATuneModeRemember);
}

/**
 * @brief Включает или выключает мешалку (обертка для set_mixer_state).
 * @param On true — включить, false — выключить
 */
void set_mixer(bool On) {
  set_mixer_state(On, false);
}

/**
 * @brief Совершает шаг шаговым двигателем для засыпи хмеля.
 */
void HopStepperStep() {
  stopService();
  stepper_safe_stop();
  stepper_safe_set_max_speed(200); //скорость движения шагового двигателя
  //stepper.setSpeed(200);    //скорость движения шагового двигателя, должна быть равна предыдущей
  TargetStepps = 360 / 1.8 * 16 / 20;  //16 - множитель на драйвере двигателя. 20 - количество отверстий по целому кругу (если бы они занимали всю окружность)
  stepper_safe_set_current(0);
  stepper_safe_set_target(TargetStepps);
  stepper.enable();
  startService();
}
