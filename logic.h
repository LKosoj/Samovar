#pragma once

#include <Arduino.h>
#include "Samovar.h"
#include "samovar_api.h"
#include "runtime_helpers.h"
#include "mode_common.h"
#include "program_io.h"

#ifdef SAMOVAR_USE_BLYNK
//#define BLYNK_PRINT Serial

#include <BlynkSimpleEsp32.h>
#endif
//**************************************************************************************************************
// Логика работы ректификационной колонны
//**************************************************************************************************************

//Получить количество разделителей
uint8_t getDelimCount(const String& data, char separator) {
  uint8_t cnt = 0;
  for (char c : data) {
    if (c == separator) {
      ++cnt;
    }
  }
  return cnt;
}

//Получить подстроку через разделитель
String getValue(const String& data, char separator, int index) {
  int found = 0;
  int strIndex[] = { 0, -1 };
  int maxIndex = data.length() - 1;

  for (int i = 0; i <= maxIndex && found <= index; i++) {
    if (data.charAt(i) == separator || i == maxIndex) {
      ++found;
      strIndex[0] = strIndex[1] + 1;
      strIndex[1] = (i == maxIndex) ? i + 1 : i;
    }
  }
  return found > index ? data.substring(strIndex[0], strIndex[1]) : "";
}

// Получить объем отбора
float get_liquid_volume_by_step(float StepCount) {
  return (SamSetup.StepperStepMl > 0) ? (float)StepCount / SamSetup.StepperStepMl : 0;
}

// Получить скорость отбора
float get_liquid_rate_by_step(int StepperSpeed) {
  return round(get_liquid_volume_by_step(StepperSpeed) * 3.6 * 1000) / 1000.00;
}

// Получить скорость из расхода
float get_speed_from_rate(float volume_per_hour) {
  ActualVolumePerHour = volume_per_hour;
  float v = round(SamSetup.StepperStepMl * volume_per_hour * 1000 / 3.6) / 1000.00;
  return (v < 1) ? 1 : v;  // Минимальная скорость 1
}

#include "impurity_detector.h"

#include "alarm.h"

// Получить объем жидкости
int get_liquid_volume() {
  return get_liquid_volume_by_step(stepper_safe_get_current());
}

// Функция для управления отбором
void withdrawal(void) {
  if (!(SamovarStatusInt == SAMOVAR_STATUS_RECT_WITHDRAWAL || SamovarStatusInt == SAMOVAR_STATUS_RECT_AUTOPAUSE || SamovarStatusInt == SAMOVAR_STATUS_PAUSED)) return;

  // ОБРАБОТКА ДЕТЕКТОРА ПРИМЕСЕЙ
  process_impurity_detector();

  //Определяем, что необходимо сменить режим работы
  //По завершению паузы
  if (program_Pause) {
    // [C-13] overflow-safe: беззнаковая разность корректна при переполнении millis()
    if ((int32_t)(millis() - t_min) >= 0) {
      t_min = 0;
      menu_samovar_start();
    }
    return;
  }

  ProgramWaitType currentWaitType = PROGRAM_WAIT_NONE;
  if (program_Wait && !copy_program_wait_type(currentWaitType)) {
    SendMsg("Тип автоматической паузы занят. Проверка отбора пропущена.", WARNING_MSG);
    return;
  }

  //По достижению шаговика цели
  CurrrentStepps = stepper_safe_get_current();

  if (TargetStepps <= CurrrentStepps && TargetStepps != 0 && (startval == SAMOVAR_STARTVAL_RECT_RUNNING || startval == SAMOVAR_STARTVAL_RECT_DONE)) {
    menu_samovar_start();
  }

  //По превышению температуры в программе
  if (program[ProgramNum].Temp != 0) {
    if (program[ProgramNum].Temp > 0 && program[ProgramNum].Temp < 20) {
      if (SteamSensor.avgTemp > (program[ProgramNum].Temp + SteamSensor.StartProgTemp)) {
        menu_samovar_start();
      }
    } else {
      if (SteamSensor.avgTemp > program[ProgramNum].Temp) {
        menu_samovar_start();
      }
    }
  }

  const uint8_t currentProgram = ProgramNum;
  ProgramType currentType = program_type_at(currentProgram);
  bool hasTwoNextPrograms = currentProgram + 2 < ProgramLen;

  // Общая логика паузы отбора по датчику температуры (пар/царга): 1:1 перенесена из
  // прежних раздельных блоков «по пару» и «по царге», отличавшихся только сенсором,
  // типом паузы и текстом сообщений. Возвращает false там, где исходный код делал
  // return из withdrawal() (тип паузы занят), иначе true.
  auto handlePauseBySensor = [&](DSSensor& sensor, ProgramWaitType waitType, const char* sensorLabel) -> bool {
    float c_temp = sensor.BodyTemp;  // датчик уже приведён к шкале с учетом настройки коррекции давления
    //Возвращаем колонну в стабильное состояние, если работает программа отбора тела и температура вышла за пределы или корректируем пределы
    if ((currentType == 'B' || currentType == 'C') && (sensor.avgTemp >= c_temp + sensor.SetTemp) && sensor.BodyTemp > 0) {
#ifdef USE_BODY_TEMP_AUTOSET
      ProgramType prevType = (currentProgram > 0) ? program_type_at(currentProgram - 1) : PROGRAM_TYPE_NONE;
      //Если строка программы - предзахлеб и после есть еще две строки с отбором тела, то корректируем Т тела
      if (hasTwoNextPrograms && currentType == 'C' &&
          (program_type_at(currentProgram + 1) == 'B' || program_type_at(currentProgram + 1) == 'C' || program_type_at(currentProgram + 1) == 'P') &&
          (program_type_at(currentProgram + 2) == 'B' || program_type_at(currentProgram + 2) == 'C')) {
        set_body_temp();
      }
      //Если это первая строка с телом - корректируем Т тела
      else if ((currentProgram > 0) && (currentType == 'B' || currentType == 'C') && prevType == 'H') {
        set_body_temp();
      } else
#endif
        //ставим отбор на паузу, если еще не стоит, и задаем время ожидания
        if (!PauseOn && !program_Wait) {
          if (!set_program_wait_type(waitType, pdMS_TO_TICKS(500))) {
            SendMsg(String("Не удалось установить паузу по ") + sensorLabel + ": тип паузы занят.", WARNING_MSG);
            return false;
          }
          program_Wait = true;
          // Сбрасываем детектор при постановке на паузу - после снятия с паузы сохраненная скорость станет новой базовой
          reset_impurity_detector();
          pause_withdrawal(true);
          t_min = millis() + sensor.Delay * 1000;
          set_buzzer(true);
          SendMsg(String("Пауза по ") + sensorLabel, WARNING_MSG);
        }
      // если время вышло, еще раз пытаемся дождаться
      // [C-13] overflow-safe
      if ((int32_t)(millis() - t_min) >= 0 && sensor.avgTemp >= c_temp + sensor.SetTemp) {
        t_min = millis() + sensor.Delay * 1000;
      }
    // [L-1/M-31] Ветка возобновления паузы: снимаем ТОЛЬКО паузу этого типа ожидания.
    // Без этой проверки ветка срабатывала бы при любом program_Wait_Type (включая паузу
    // другого сенсора и "(Детектор)"), снимала чужую паузу, а соответствующая ветка тут
    // же ставила её снова → осцилляция каждые Delay сек (спам, зуммер, пуски насоса).
    // [C-13] overflow-safe: t_min > 0 — сентинель "таймер установлен"; (int32_t)(millis()-t_min) >= 0 — истёк
    } else if ((currentType == 'B' || currentType == 'C') && sensor.avgTemp < c_temp + sensor.SetTemp && t_min > 0 && (int32_t)(millis() - t_min) >= 0 && program_Wait && currentWaitType == waitType) {
      //продолжаем отбор
      SendMsg(("Продолжаем отбор после автоматической паузы"), NOTIFY_MSG);
      t_min = 0;
      program_Wait = false;
      pause_withdrawal(false);
      // После возобновления с паузы устанавливаем сохраненную скорость как базовую для детектора
      // Вычисляем скорость в л/ч из сохраненной скорости шагов и временно корректируем program[ProgramNum].Speed
      if (SamSetup.useautospeed && currentProgram < PROGRAM_MAX && CurrrentStepperSpeed > 0) {
        float actualRate = get_liquid_rate_by_step(CurrrentStepperSpeed);
        if (actualRate > 0) {
          // Временно корректируем скорость программы на текущую скорость насоса
          // Это позволяет детектору считать текущую скорость базовой (correctionFactor = 1.0)
          program[currentProgram].Speed = actualRate;
          impurityDetector.correctionFactor = 1.0f;
          impurityDetector.lastCorrectionTime = millis();
          // Устанавливаем скорость явно через set_pump_speed для синхронизации
          set_pump_speed(CurrrentStepperSpeed, true);
        }
      }
    }
    return true;
  };

  if (!handlePauseBySensor(SteamSensor, PROGRAM_WAIT_STEAM, "Т пара")) return;
  if (!handlePauseBySensor(PipeSensor, PROGRAM_WAIT_PIPE, "Т царги")) return;

  // Пауза детектора: после истечения таймера возобновляем отбор
  // [L-1/M-31] Эта ветка уже проверяла program_Wait_Type == "(Детектор)" — это корректно.
  // [C-13] overflow-safe: t_min > 0 — сентинель; (int32_t)(millis()-t_min) >= 0 — истёк
  if (program_Wait && currentWaitType == PROGRAM_WAIT_DETECTOR && t_min > 0 && (int32_t)(millis() - t_min) >= 0) {
    SendMsg(("Детектор: Продолжаем отбор после паузы"), NOTIFY_MSG);
    t_min = 0;
    program_Wait = false;
    pause_withdrawal(false);
    detector_on_auto_resume();
  }
  vTaskDelay(10 / portTICK_PERIOD_MS);
}

// Калибровка насоса
PumpCalibrationResult pump_calibrate(int stpspeed) {
  if (startval != SAMOVAR_STARTVAL_IDLE && startval != SAMOVAR_STARTVAL_CALIBRATION) {
    return PUMP_CALIBRATION_INVALID_STATE;
  }

  if (stpspeed == 0) {
    startval = SAMOVAR_STARTVAL_IDLE;
    //Сохраняем полученное значение калибровки
    int32_t currentSteps = stepper_safe_get_current();
    uint32_t stepsPerMl = (currentSteps > 0) ? (uint32_t)round((float)currentSteps / 100) : 0;
    stopService();
    stepper_safe_stop();
    if (stepsPerMl == 0 || stepsPerMl > UINT16_MAX) {
      SendMsg("Ошибка калибровки помпы: неверное количество шагов", ALARM_MSG);
      return PUMP_CALIBRATION_INVALID_RESULT;
    }
    SetupEEPROM profileCandidate{};
    profileCandidate = SamSetup;
    profileCandidate.StepperStepMl = (uint16_t)stepsPerMl;
    const PersistResult persistResult = save_profile_nvs(profileCandidate);
    if (persistResult == PERSIST_OK) {
      SamSetup = profileCandidate;
    } else {
      String message = "Калибровка помпы не сохранена: ";
      message += persist_result_code(persistResult);
      message += ". Результат потерян, повторите калибровку.";
      SendMsg(message, ALARM_MSG);
      return PUMP_CALIBRATION_PROFILE_PERSIST_FAILED;
    }
  } else {
    startval = SAMOVAR_STARTVAL_CALIBRATION;
    //крутим двигатель, пока не остановят
    if (!stepper_safe_get_state()) stepper_safe_set_current(0);
    stepper_safe_set_max_speed(stpspeed);
    //stepper.setSpeed(stpspeed);
    stepper_safe_set_target(999999999);
    startService();
  }
  return PUMP_CALIBRATION_OK;
}

// Пауза отбора
void pause_withdrawal(bool Pause) {
  if (Samovar_Mode != SAMOVAR_RECTIFICATION_MODE) return;
  if (!stepper_safe_get_state() && !PauseOn) return;
  PauseOn = Pause;
  if (Pause) {
    TargetStepps = stepper_safe_get_target();
    CurrrentStepps = stepper_safe_get_current();
    if (CurrrentStepperSpeed < 1) CurrrentStepperSpeed = (uint16_t)max(1, (int)abs((int)stepper_safe_get_speed()));
    stopService();
    stepper_safe_stop();
  } else {
    stepper_safe_set_max_speed(CurrrentStepperSpeed);
    //stepper.setSpeed(CurrrentStepperSpeed);
    stepper_safe_set_current(CurrrentStepps);
    stepper_safe_set_target(TargetStepps);
    startService();
  }
}

// Установить скорость насоса
void set_pump_speed(float pumpspeed, bool continue_process) {
  if (pumpspeed < 1) return;
  if (!(SamovarStatusInt == SAMOVAR_STATUS_RECT_WITHDRAWAL || SamovarStatusInt == SAMOVAR_STATUS_RECT_AUTOPAUSE || SamovarStatusInt == SAMOVAR_STATUS_PAUSED)) return;

  bool cp = continue_process;
  if (!stepper_safe_get_state()) cp = false;

  CurrrentStepperSpeed = pumpspeed;
  ActualVolumePerHour = get_liquid_rate_by_step(CurrrentStepperSpeed);

  stopService();
  stepper_safe_set_max_speed(CurrrentStepperSpeed);
  stepper_safe_set_target(stepper_safe_get_target());
  //stepper.setSpeed(CurrrentStepperSpeed);
  //Пересчитываем время отбора этой строки программы на текущую скорость
  if (ActualVolumePerHour == 0) program[ProgramNum].Time = 65535;
  else
    program[ProgramNum].Time = program[ProgramNum].Volume / ActualVolumePerHour / 1000;
  if (cp)
    startService();
}

// Получить температуру с выбранного датчика для режима пива
float getBeerCurrentTemp() {
  if (SamovarStatusInt != SAMOVAR_STATUS_BEER) return 0.0;
  
  switch (program[ProgramNum].TempSensor) {
    case 0:
      return TankSensor.avgTemp;
    case 1:
      return WaterSensor.avgTemp;
    case 2:
      return PipeSensor.avgTemp;
    case 3:
      return SteamSensor.avgTemp;
    case 4:
      return ACPSensor.avgTemp;
    default:
      return TankSensor.avgTemp;
  }
}

String get_distiller_status_text() {
  String local = "Прг №" + String(ProgramNum + 1) + "; Режим дистилляции";
  if (PowerOn) {
    local += "; Осталось:" + String(get_dist_remaining_time(), 1) + " мин";
    local += "; Общее:" + String(get_dist_predicted_total_time(), 1) + " мин";
  }
  return local;
}

String get_bk_status_text() {
  return F("Режим бражной колонны");
}

String get_nbk_status_text() {
  String local;
  if (startval == SAMOVAR_STARTVAL_NBK_RUNNING) {
    local = "Прг №" + String(ProgramNum + 1) + "; ";
    ProgramType nbkProgramType = current_program_type();
    if (nbkProgramType == 'H') {
      local = local + "Прогрев";
    } else if (nbkProgramType == 'S') {
      local = local + "Настройка";
    } else if (nbkProgramType == 'O') {
      local = local + "Оптимизация";
    } else if (nbkProgramType == 'W') {
      local = local + "Работа";
    }
  }
  return local;
}

String get_beer_status_text() {
#ifdef SAM_BEER_PRG
  String local = "Прг №" + String(ProgramNum + 1) + "; ";
#else
  String local = "";
#endif
  ProgramType currentType = current_program_type();
  if (startval == SAMOVAR_STARTVAL_BEER_HEATING && currentType == 'M') {
    float currentTemp = getBeerCurrentTemp();
    local = local + "Разогрев до температуры засыпи солода";
    if (currentTemp < program[ProgramNum].Temp - 0.5) {
      local += "; Текущая Т: " + String(currentTemp) + "°";
    }
  } else if (startval == SAMOVAR_STARTVAL_BEER_WAIT_MALT && currentType == 'M') {
    local = local + "Ожидание засыпи солода";
  } else if (currentType == 'P') {
    if (begintime == 0) {
      float currentTemp = getBeerCurrentTemp();
      local = local + "Пауза " + String(program[ProgramNum].Temp) + "°; Разогрев";
      if (currentTemp < program[ProgramNum].Temp - 0.5) {
        local += "; Текущая Т: " + String(currentTemp) + "°";
      }
    } else {
      local = local + "Пауза " + String(program[ProgramNum].Temp) + "°";
    }
  } else if (currentType == 'C') {
    float currentTemp = getBeerCurrentTemp();
    local = local + "Охлаждение до " + String(program[ProgramNum].Temp);
    if (currentTemp > program[ProgramNum].Temp + 0.5) {
      local += "; Текущая Т: " + String(currentTemp) + "°";
    }
  } else if (currentType == 'W') {
    local = local + "Ожидание. Нажмите 'Следующая программа'; ";
  } else if (currentType == 'A') {
    local = local + "Автокалибровка. После завершения питание будет выключено";
  } else if (currentType == 'B') {
    if (begintime == 0) {
      local = local + "Кипячение - нагрев";
    } else {
      local = local + "Кипячение " + String(program[ProgramNum].Time) + " мин";
    }
  } else if (currentType == 'F') {
    if (PowerOn) {
      float currentTemp = getBeerCurrentTemp();
      local = local + "Ферментация; Поддерж. Т=" + String(program[ProgramNum].Temp) + "°";
      local += "; Тек: " + String(currentTemp) + "°";
      if (heater_state) {
        local += " (Нагрев)";
      } else {
        local += " (Термостатирование)";
      }
    } else {
      local = local + "Ферментация (остановлена)";
    }
  } else if (currentType == 'L') {
    local = local + "Выполнение Lua скрипта";
  }

  if (PowerOn && (currentType == 'P' || currentType == 'B') && begintime > 0) {
    float progress = ((float)(millis() - begintime) / (program[ProgramNum].Time * 60 * 1000)) * 100;
    if (progress > 100) progress = 100;
    local += "; Прогресс: " + String(progress, 1) + "%";
  }
  return local;
}

// Остановка любого процесса с общим набором действий
void stop_process(String reason) {
  SamovarStatusInt = SAMOVAR_STATUS_IDLE;
  set_power(false);
  reset_sensor_counter();
  SendMsg(reason, NOTIFY_MSG);
}

// Продвигает FSM статуса и обновляет кэш SamovarStatus.
// Вызывается из секундного гейта triggerSysTicker (core 0) — раз в секунду.
// Веб и Blynk читают кэш SamovarStatus напрямую под runtime_state_lock.
String tick_status_fsm() {
  // Строим статус в локальную переменную; под замком — только финальное присваивание кэша.
  String local;
  // Если питание выключено и нет активного режима - показываем "Выключено"
  if (!PowerOn && SamovarStatusInt == SAMOVAR_STATUS_IDLE) {
    local = F("Выключено");
  } else if (PowerOn && startval == SAMOVAR_STARTVAL_RECT_RUNNING && !PauseOn && !program_Wait) {
    local = "Прг №" + String(ProgramNum + 1);
    SamovarStatusInt = SAMOVAR_STATUS_RECT_WITHDRAWAL;
  } else if (PowerOn && startval == SAMOVAR_STARTVAL_RECT_RUNNING && program_Wait) {
    int s = 0;
    // [C-13] overflow-safe: t_min ещё в будущем если (int32_t)(t_min - millis()) > 10.
    //        millis() читаем один раз в локаль, иначе второй вызов мог бы дать
    //        отрицательный остаток между двумя замерами.
    int32_t rem = (int32_t)(t_min - millis());
    if (rem > 10) {
      s = rem / 1000;
    }
    String waitTypeText;
    if (!copy_program_wait_type_text(waitTypeText)) {
      waitTypeText = F("(ошибка)");
      SendMsg("Не удалось прочитать тип автоматической паузы.", WARNING_MSG);
    }
    local = "Прг №" + String(ProgramNum + 1) + " пауза " + waitTypeText + ". Продолжение через " + (String)s + " сек.";
    SamovarStatusInt = SAMOVAR_STATUS_RECT_AUTOPAUSE;
  } else if (PowerOn && startval == SAMOVAR_STARTVAL_RECT_DONE) {
    local = F("Выполнение программы завершено");
    SamovarStatusInt = SAMOVAR_STATUS_RECT_PROGRAM_DONE;
  } else if (PowerOn && startval == SAMOVAR_STARTVAL_CALIBRATION) {
    local = F("Калибровка");
    SamovarStatusInt = SAMOVAR_STATUS_RECT_CALIBRATION;
  } else if (PauseOn) {
    local = F("Пауза");
    SamovarStatusInt = SAMOVAR_STATUS_PAUSED;
  } else if (PowerOn && Samovar_Mode == SAMOVAR_SUVID_MODE) {
    // Сувид — термостат без колонны и шаговика: ветка «Разгон колонны» ниже к нему неприменима.
    local = "Сувид; Поддерж. Т=" + String(suvid_target_temp()) + "°; Тек: " + String(TankSensor.avgTemp) + "°";
    if (heater_state) {
      local += " (Нагрев)";
    } else {
      local += " (Термостатирование)";
    }
  } else if (PowerOn && startval == SAMOVAR_STARTVAL_IDLE && !stepper_safe_get_state()) {
    // [PKG-B п.2] При активном nbk-переходе (в т.ч. мягком финише FINISH_WAIT: нагрев ещё
    // включён, startval=0) НЕ захватываем статус 50 — иначе finishOwnerValid (требует
    // SamovarStatusInt==0) ложнеет и мягкий финиш срывается в аварийное отключение нагрева.
    // nbk_transition_active() истинна только в режиме НБК, ректификацию это не затрагивает.
    if (SamovarStatusInt != SAMOVAR_STATUS_RECT_STABILIZING && SamovarStatusInt != SAMOVAR_STATUS_RECT_STABLE && !nbk_transition_active()) {
      local = F("Разгон колонны");
      SamovarStatusInt = SAMOVAR_STATUS_RECT_ACCEL;
    } else if (SamovarStatusInt == SAMOVAR_STATUS_RECT_STABILIZING) {
      local = F("Разгон завершен. Стабилизация/Работа на себя");
    } else if (SamovarStatusInt == SAMOVAR_STATUS_RECT_STABLE) {
      local = F("Стабилизация завершена/Работа на себя");
    }
  } else {
    mode_status_by_status(SamovarStatusInt, local);
  }

  if (SamovarStatusInt == SAMOVAR_STATUS_RECT_WITHDRAWAL || SamovarStatusInt == SAMOVAR_STATUS_RECT_AUTOPAUSE || (SamovarStatusInt == SAMOVAR_STATUS_BEER && PowerOn)) {
    // [C-2/2c] WthdrwTimeS/WthdrwTimeAllS пишутся SysTicker под замком → читаем под
    // тем же замком. Блок короткий и не перекрывается с финальным блоком записи кэша.
    String localWtS, localWtAllS;
    {
      bool locked = runtime_state_lock(pdMS_TO_TICKS(50));
      if (locked) {
        localWtS = WthdrwTimeS;
        localWtAllS = WthdrwTimeAllS;
        runtime_state_unlock(true);
      }
    }
    local += "; Осталось:" + localWtS + "|" + localWtAllS;
  }
  if (SteamSensor.BodyTemp > 0) {
    local += ";Т тела пар:" + format_float(SteamSensor.BodyTemp, 3) + ";Т тела царга:" + format_float(PipeSensor.BodyTemp, 3);
  }

  // [C-2] Под замком обновляем кэш SamovarStatus; веб/Blynk читают его отдельно.
  {
    bool locked = runtime_state_lock(pdMS_TO_TICKS(50));
    if (locked) {
      SamovarStatus = local;
      runtime_state_unlock(true);
    }
  }
  return local;
}

// Получить статус Самовара из кэша (без побочных эффектов на FSM).
String get_Samovar_Status() {
  String status;
  bool locked = runtime_state_lock(pdMS_TO_TICKS(50));
  if (locked) {
    status = SamovarStatus;
    runtime_state_unlock(true);
  }
  return status;
}

// Установить емкость
void set_capacity(uint8_t cap) {
  if (cap > CAPACITY_NUM) return;
  capacity_num = cap;

#ifdef SERVO_PIN
  int p = ((int)cap * SERVO_ANGLE) / (int)CAPACITY_NUM + servoDelta[cap];
  servo.write(p);
#elif USER_SERVO
  user_set_capacity(cap);
#endif
}

// Переход к следующей емкости
void next_capacity(void) {
  set_capacity(capacity_num + 1);
}

// Установить программу
ProgramParseResult set_program(const String& WProgram) {
  return program_parse_lines(WProgram, rect_program_parse_spec());
}

// Получить программу
String get_program(uint8_t s) {
  uint8_t k = PROGRAM_END;
  if (s == PROGRAM_END) {
    s = 0;
  } else {
    k = s + 1;
  }
  return program_serialize_rows(s, k, program_append_rect_row);
}

static void reset_rect_program_pause_state() {
  t_min = 0;
  program_Pause = false;
  program_Wait = false;
  PauseOn = false;
  if (!set_program_wait_type(PROGRAM_WAIT_NONE, pdMS_TO_TICKS(500))) {
    SendMsg("Не удалось сбросить тип автоматической паузы.", WARNING_MSG);
  }
  pause_withdrawal(false);
}

// Запустить программу
void run_program(uint8_t num) {
  if (num >= PROGRAM_MAX) {
    // PROGRAM_END — sentinel завершения; его нельзя публиковать в ProgramNum.
    reset_rect_program_pause_state();
    ProgramNum = 0;
    startval = SAMOVAR_STARTVAL_IDLE;
    stopService();
    stepper_safe_stop_reset();
    set_capacity(0);
    if (!request_data_log_close()) SendMsg("Файл лога занят: закрытие пропущено", WARNING_MSG);
    stop_process("Выполнение программы завершено.");
    TargetStepps = stepper_safe_get_target();
    return;
  }

  // Проверяем смену типа программы для сброса детектора
  // Сбрасываем детектор только при переходе:
  // - H (головы) -> B/C (тело/предзахлеб)
  // - B/C (тело/предзахлеб) -> T (хвосты)
  // НЕ сбрасываем при переходе B <-> C (между телом и предзахлебом)
  bool needReset = false;
  
  if (num < PROGRAM_MAX && !program_type_empty(program[num].WType)) {
    ProgramType currentType = program[num].WType;
    
    // Проверяем предыдущую программу, если она существует
    if (num > 0 && !program_type_empty(program[num - 1].WType)) {
      ProgramType prevType = program[num - 1].WType;
      
      // Переход с голов на тело/предзахлеб
      if (prevType == 'H' && (currentType == 'B' || currentType == 'C')) {
        needReset = true;
      }
      // Переход с тела/предзахлеба на хвосты
      else if ((prevType == 'B' || prevType == 'C') && currentType == 'T') {
        needReset = true;
      }
      // Переход с любого другого типа на тело/предзахлеб (если не было B/C)
      else if (prevType != 'B' && prevType != 'C' && (currentType == 'B' || currentType == 'C')) {
        needReset = true;
      }
      // Переход с тела/предзахлеба на любой другой тип (кроме B/C)
      else if ((prevType == 'B' || prevType == 'C') && currentType != 'B' && currentType != 'C') {
        needReset = true;
      }
      // Переход B <-> C - НЕ сбрасываем (needReset остается false)
    } else {
      // Первый запуск или предыдущая программа не определена - всегда сбрасываем
      needReset = true;
    }
  } else {
    // Если тип текущей программы не определен - сбрасываем
    needReset = true;
  }
  
  ProgramNum = num;
  if (ProgramNum < PROGRAM_MAX && !program_type_empty(program[ProgramNum].WType)) {
    detector_on_program_start(program[ProgramNum].WType);
  }
  
  // Сбрасываем детектор только если нужно
  if (needReset) {
    reset_impurity_detector();
  }
  
  reset_rect_program_pause_state();

  //запоминаем текущие значения температур
  SteamSensor.StartProgTemp = SteamSensor.avgTemp;
  PipeSensor.StartProgTemp = PipeSensor.avgTemp;
  WaterSensor.StartProgTemp = WaterSensor.avgTemp;
  TankSensor.StartProgTemp = TankSensor.avgTemp;

  String p_s;
#ifdef SAMOVAR_USE_POWER
#ifdef SAMOVAR_USE_SEM_AVR
  if (abs(program[num].Power) > 400 && program[num].Power > 0) {
#else
  if (abs(program[num].Power) > 40 && program[num].Power > 0) {
#endif
    set_current_power(program[num].Power);
  } else if (program[num].Power != 0) {
    set_current_power(target_power_volt + program[num].Power);
  }
  vTaskDelay(500 / portTICK_PERIOD_MS);
  // [L-7] alarm_c_low_min = millis() — запоминается момент старта строки предзахлёба;
  // интервал TIME_C добавляется позже в check_alarm() при срабатывании.
  if (program[num].WType == 'C' && alarm_c_low_min == 0) alarm_c_low_min = millis();
#endif
  p_s = "Программа: старт строки  №" + (String)(num + 1);
  if (program[num].WType == 'H' || program[num].WType == 'B' || program[num].WType == 'T' || program[num].WType == 'C') {
    if (program[num].WType == 'H' || program[num].WType == 'T') {
      SteamSensor.BodyTemp = 0;
      PipeSensor.BodyTemp = 0;
      WaterSensor.BodyTemp = 0;
      TankSensor.BodyTemp = 0;
    }
    p_s += ", отбор в ёмкость " + (String)program[num].capacity_num;
    //устанавливаем параметры для текущей программы отбора
    set_capacity(program[num].capacity_num);
    CurrrentStepperSpeed = (uint16_t)get_speed_from_rate(program[num].Speed);
    stepper_safe_set_max_speed(CurrrentStepperSpeed);
    //stepper.setSpeed(get_speed_from_rate(program[num].Speed));
    TargetStepps = (uint32_t)program[num].Volume * (uint32_t)SamSetup.StepperStepMl;
    stepper_safe_set_current(0);
    stepper_safe_set_target(TargetStepps);
    startService();
    ActualVolumePerHour = program[num].Speed;
    // [L-3] Семантика поля Temp строк B/C (согласно UI-документации data/index.htm):
    //   Temp == 0  → не используется (переход только по объёму)
    //   0 < Temp < 20 → дельта: переход на следующую строку, когда
    //                   SteamSensor.avgTemp > StartProgTemp + Temp
    //   Temp >= 20 → абсолютный порог: переход, когда avgTemp > Temp
    // BodyTemp — это отдельная переменная для паузы по превышению температуры
    // (логика pause-by-steam). Устанавливать BodyTemp = program.Temp НЕЛЬЗЯ:
    //   - при Temp >= 20 условие завершения строки (avgTemp > Temp) срабатывает
    //     раньше, чем условие паузы (avgTemp >= BodyTemp + SetTemp), поэтому
    //     пауза по пару никогда не достигается;
    //   - при 0 < Temp < 20 значение кладётся как абсолютная BodyTemp, а не
    //     дельта → условие паузы (avgTemp >= ~0..19 + SetTemp) всегда истинно →
    //     неснимаемая пауза.
    // BodyTemp всегда захватывается автоматически через set_body_temp() из
    // текущей avgTemp при старте строки (см. блок ниже).
    // Поле program.Temp используется ТОЛЬКО в ветке завершения строки в withdrawal().

    //Если у первой программы отбора тела не задана температура, при которой начинать отбор, считаем, что она равна текущей
    //Считаем, что колонна стабильна
    //Итак, текущая температура - это температура, которой Самовар будет придерживаться во время всех программ отобора тела.
    //Если она будет выходить за пределы, заданные в настройках, отбор будет ставиться на паузу, и продолжится после возвращения температуры в колонне к заданному значению.
    if ((program[num].WType == 'B' || program[num].WType == 'C') && SteamSensor.BodyTemp == 0) {
      set_body_temp();
    }
  } else if (program[num].WType == 'P') {
    //Сбрасываем Т тела, так как при изменении напряжения на регуляторе изменяется Т в царге.
    SteamSensor.BodyTemp = 0;
    PipeSensor.BodyTemp = 0;
    WaterSensor.BodyTemp = 0;
    TankSensor.BodyTemp = 0;

    //устанавливаем параметры ожидания для программы паузы. Время в секундах задано в program[num].Volume
    p_s += ", пауза " + (String)program[num].Volume + " сек.";
    t_min = millis() + program[num].Volume * 1000;
    program_Pause = true;
    stopService();
    stepper_safe_set_max_speed(0);
    CurrrentStepperSpeed = 0;
    //stepper.setSpeed(-1);
    stepper_safe_stop_reset();
  }

  if (SamSetup.ChangeProgramBuzzer) {
    set_buzzer(true);
    SendMsg(p_s, ALARM_MSG);
  } else {
    SendMsg(p_s, NOTIFY_MSG);
  }

  TargetStepps = stepper_safe_get_target();
}

//функция корректировки температуры кипения спирта в зависимости от давления
float get_temp_by_pressure(float start_pressure, float start_temp, float current_pressure) {
  if (start_temp == 0) return 0;
  if (current_pressure < 10) return start_temp;

  //скорректированная температура кипения спирта при текущем давлении
  float c_temp;

  if (SamSetup.UsePreccureCorrect) {
    //идеальная температура кипения спирта при текущем давлении
    float i_temp;
    //температурная дельта
    float d_temp;

    i_temp = current_pressure * 0.038 + 49.27;

    if (start_pressure == 0) {
      d_temp = start_temp - 78.15;
    } else {
      d_temp = start_temp - start_pressure * 0.038 - 49.27;  //учитываем поправку на погрешность измерения датчиков
    }
    c_temp = i_temp + d_temp;  // получаем текущую температуру кипения при переданном давлении с учетом поправки
  } else {
    //Используем сохраненную температуру отбора тела без корректировки
    c_temp = start_temp;
  }

  return c_temp;
}

// Установить температуру тела
void set_body_temp() {
  reset_impurity_detector();
  ProgramType currentType = current_program_type();
  if (currentType == 'B' || currentType == 'C' || currentType == 'P') {
    SteamSensor.Start_Pressure = bme_pressure;
    SteamSensor.BodyTemp = SteamSensor.avgTemp;
    PipeSensor.BodyTemp = PipeSensor.avgTemp;
    WaterSensor.BodyTemp = WaterSensor.avgTemp;
    TankSensor.BodyTemp = TankSensor.avgTemp;
    SendMsg("Новые Т тела: пар = " + String(SteamSensor.BodyTemp) + ", царга = " + String(PipeSensor.BodyTemp), WARNING_MSG);
  } else {
    SendMsg(("Не возможно установить Т тела."), WARNING_MSG);
  }
}

#include "valve_buzzer.h"
#include "power_regulator.h"

float get_steam_alcohol(float t) {
  if (!boil_started) return 100;

  float r;
  float t1;
  float s;
  float k;
  uint8_t t0;

  // [L-6/M-26] avgTemp уже нормализован к 760 мм рт. ст. в DS_getvalue()
  // (sensorinit.h: correctT = (760 - bme_pressure) * 0.037, при UsePreccureCorrect).
  // Повторный вызов get_temp_by_pressure() прибавлял бы ту же поправку ещё раз
  // со знаком, противоположным первой (~0.038*(P-760)), → коррекции почти гасились
  // и спиртуозность считалась фактически по сырой температуре.
  // Решение: t1 сохраняем для ветки t > 99.84 (где вызывается get_alcohol(t1) —
  // он тоже исправлен), get_temp_by_pressure() не вызываем — t уже в нужной шкале.
  t1 = t;

  if (t >= 99 && t < 99.84) {
    s = 11.21;
    k = -13;
    t0 = 99;
  } else if (t >= 98 && t < 99) {
    s = 20.744;
    k = -9.84;
    t0 = 98;
  } else if (t >= 97 && t < 98) {
    s = 29.936;
    k = -9;
    t0 = 97;
  } else if (t >= 96 && t < 97) {
    s = 39.781;
    k = -9.6;
    t0 = 96;
  } else if (t >= 95 && t < 96) {
    s = 44.628;
    k = -4.847;
    t0 = 95;
  } else if (t >= 94 && t < 95) {
    s = 49.2775;
    k = -4.65;
    t0 = 94;
  } else if (t >= 93 && t < 94) {
    s = 53.76;
    k = -4.483;
    t0 = 93;
  } else if (t >= 92 && t < 93) {
    s = 57.539;
    k = -3.778;
    t0 = 92;
  } else if (t >= 91 && t < 92) {
    s = 61.22;
    k = -3.682;
    t0 = 91;
  } else if (t >= 90 && t < 91) {
    s = 66.4633;
    k = -5.244;
    t0 = 90;
  } else if (t >= 89 && t < 90) {
    s = 69.334;
    k = -2.87;
    t0 = 89;
  } else if (t >= 88 && t < 89) {
    s = 70.82;
    k = -1.4857;
    t0 = 88;
  } else if (t >= 87 && t < 88) {
    s = 72.42;
    k = -1.6;
    t0 = 87;
  } else if (t >= 86 && t < 87) {
    s = 75.03;
    k = -2.66;
    t0 = 86;
  } else if (t >= 85 && t < 86) {
    s = 77.21;
    k = -2.2;
    t0 = 85;
  } else if (t >= 84 && t < 85) {
    s = 79.88;
    k = -2.67;
    t0 = 84;
  } else if (t >= 83 && t < 84) {
    s = 81.08;
    k = -1.2;
    t0 = 83;
  } else {
    s = 82;
    k = -1;
    t0 = 82;
  }

  if (t > 100) {
    r = 0;
  } else if (t > 99.84) {
    r = get_alcohol(t1);
  } else {
    r = s + k * (t - t0);
  }
  if (r < 0) r = 0;
  return r;
}

float get_alcohol(float t) {
  if (!boil_started) return 100;
  // [L-6/M-26] avgTemp уже нормализован к 760 мм рт. ст. в DS_getvalue(),
  // повторный пересчёт через get_temp_by_pressure() создавал двойную коррекцию.
  float r;
  float k;
  k = (t - 89) / 6.49;

  r = 17.26 - k * (18.32 - k * (7.81 - k * (1.77 - k * (4.81 - k * (2.95 + k * (1.43 - k * (0.8 + 0.05 * k)))))));  // формула Макеода для вычисления крепости
  if (r < 0) r = 0;
  r = float(round(r * 10)) / 10;  // округляем до одного знака после запятой
  return r;

  //reverse
  //t[град]=85,37 - 3,75 * Ti + 1,48 * Ti ^ 2 - 0,32 * Ti ^ 3 +0,41 * Ti ^ 4 - 0,92 * Ti ^ 5 +0,32 * Ti ^ 6 + 0,1 * Ti ^ 7 - 0,05 * Ti ^ 8
  //Где  Ti = ( К%об - 43,15 ) / 30,18
  //более точно
  // Темп=105.47* крепость^-0.065 - применима для растворов крепче 2%мас.
}

void set_boiling() {
  //Учитываем задержку измерения Т кипения
  if (!boil_started) {
    //    if (abs(TankSensor.avgTemp - b_t_temp_prev) > 0.1) {
    //      b_t_temp_prev = TankSensor.avgTemp;
    //      b_t_time_min = millis();
    //    } else if ((millis() - b_t_time_min) > 6 * 1000) {
    //6 секунд не было изменения температуры куба
    //d_s_temp_finish = 0;
    //d_s_time_min = 0;
    //началось кипение, запоминаем Т кипения
    boil_started = true;
    //Проверяем наличие датчика куба (Т >= 2 означает наличие датчика)
    if (TankSensor.avgTemp >= 2) {
      boil_temp = TankSensor.avgTemp;
      alcohol_s = get_alcohol(TankSensor.avgTemp);
    } else {
      //Если датчик куба отсутствует, устанавливаем значения по умолчанию
      boil_temp = 0;
      alcohol_s = 0;
    }
#ifdef USE_WATER_PUMP
    wp_count = -10;
#endif
    //    }
  }
}

bool check_boiling() {
  if (boil_started || !PowerOn || !valve_status) {
    return false;
  }

  //Определяем наличие датчиков (Т < 2 означает отсутствие датчика)
  bool has_tank_sensor = TankSensor.avgTemp >= 2;
  bool has_water_sensor = WaterSensor.avgTemp >= 2;

  //Если оба датчика отсутствуют, не можем определить кипение
  if (!has_tank_sensor && !has_water_sensor) {
    return false;
  }

  //Если есть датчик куба, проверяем минимальную температуру
  if (has_tank_sensor && TankSensor.avgTemp < 70) {
    return false;
  }

  //учтем задержку в 60 секунд до начала процесса определения кипения, чтобы датчик температуры воды успел остыть, если он нагрелся
  // [C-13] overflow-safe: разность millis()-b_t_time_delay < 60000 означает "ещё не прошло 60 сек"
  if (b_t_time_delay == 0 || ((int32_t)(millis() - b_t_time_delay) < 60 * 1000)) {
    if (b_t_time_delay == 0) {
      b_t_time_delay = millis();
    }
    return false;
  }

  bool boiling_detected = false;

  if (has_tank_sensor && has_water_sensor) {
    //Оба датчика есть - определяем по совокупности факторов
    
    //Если минимальная температура воды охлаждения больше текущей, то запоминаем её
    if (d_s_temp_prev > WaterSensor.avgTemp || d_s_temp_prev == 0) {
      d_s_temp_prev = WaterSensor.avgTemp;
    }
    
    //Проверяем стабильность температуры в кубе
    bool tank_stable = false;
    if (TankSensor.avgTemp - b_t_temp_prev > 0.1) {
      b_t_temp_prev = TankSensor.avgTemp;
      b_t_time_min = millis();
    } else if ((millis() - b_t_time_min) > 50 * 1000 && b_t_time_min > 0) {
      tank_stable = true;
    }
    
    //Проверяем нагрев воды охлаждения
    bool water_heating = (WaterSensor.avgTemp - d_s_temp_prev > 8) || 
                         (abs(WaterSensor.avgTemp - SamSetup.SetWaterTemp) < 3 && WaterSensor.avgTemp - d_s_temp_prev > 2);
    
    //Кипение определяется при одновременном выполнении ОБОИХ условий (куб стабилен И вода нагревается) или при высокой температуре пара
    if ((tank_stable && water_heating) || SteamSensor.avgTemp > CHANGE_POWER_MODE_STEAM_TEMP) {
      boiling_detected = true;
    }
  } else if (has_tank_sensor) {
    //Только датчик куба - определяем по стабильности температуры в кубе
    if (TankSensor.avgTemp - b_t_temp_prev > 0.1) {
      b_t_temp_prev = TankSensor.avgTemp;
      b_t_time_min = millis();
    } else if ((millis() - b_t_time_min) > 50 * 1000 && b_t_time_min > 0) {
      boiling_detected = true;
    }
    //Также можно использовать температуру пара как дополнительный индикатор
    if (SteamSensor.avgTemp > CHANGE_POWER_MODE_STEAM_TEMP) {
      boiling_detected = true;
    }
  } else if (has_water_sensor) {
    //Только датчик воды - определяем по нагреву воды охлаждения
    if (d_s_temp_prev > WaterSensor.avgTemp || d_s_temp_prev == 0) {
      d_s_temp_prev = WaterSensor.avgTemp;
    }
    if (WaterSensor.avgTemp - d_s_temp_prev > 8) {
      boiling_detected = true;
    }
    if (abs(WaterSensor.avgTemp - SamSetup.SetWaterTemp) < 3 && WaterSensor.avgTemp - d_s_temp_prev > 2) {
      boiling_detected = true;
    }
    //Также можно использовать температуру пара как дополнительный индикатор
    if (SteamSensor.avgTemp > CHANGE_POWER_MODE_STEAM_TEMP) {
      boiling_detected = true;
    }
  }

  if (boiling_detected) {
    set_boiling();
    if (boil_started) {
      if (has_tank_sensor) {
        SendMsg("Началось кипение в кубе! Спиртуозность " + format_float(alcohol_s, 1), WARNING_MSG);
      } else {
        SendMsg("Началось кипение в кубе!", WARNING_MSG);
      }
    }
  }

  return boil_started;
}

#include "selftest.h"

#ifdef COLUMN_WETTING
// [L-36fix] File-scope флаг неудачного смачивания: виден из sensorinit.h (включается после logic.h).
// reset_sensor_counter() сбрасывает его при стопе процесса, обеспечивая корректный
// новый запуск смачивания. В рамках одного прогона после таймаута удерживает false.
bool wetting_failed = false;

// Функция для смачивания насадки колонны
bool column_wetting() {
  // Статические переменные для сохранения состояния между вызовами
  static unsigned long wetting_start_time = 0;
  static unsigned long last_voltage_decrease_time = 0;
  static bool wetting_started = false;
  static bool voltage_decrease_started = false;
  static float initial_voltage = 0;
  static unsigned long total_wetting_time = 0;
  static unsigned long min_voltage_time = 0;

  // Функция сброса всех статических переменных
  auto reset_wetting_state = []() {
    wetting_start_time = 0;
    last_voltage_decrease_time = 0;
    wetting_started = false;
    voltage_decrease_started = false;
    initial_voltage = 0;
    total_wetting_time = 0;
    min_voltage_time = 0;
    wetting_failed = false;  // [L-36] сброс флага неудачи
  };

  // Проверяем, что датчик уровня флегмы установлен
  #ifdef USE_HEAD_LEVEL_SENSOR
  if (SamSetup.UseHLS) {
    // [L-36] После неудачного смачивания удерживаем false до ручного сброса.
    if (wetting_failed) {
      return false;
    }
    // Инициализация процесса смачивания
    if (!wetting_started) {
      SendMsg(("Начало смачивания насадки колонны. Следите за уровнем флегмы!"), WARNING_MSG);
      
      wetting_start_time = millis();
      last_voltage_decrease_time = 0;
      total_wetting_time = millis();
      min_voltage_time = 0;
      wetting_started = true;
      voltage_decrease_started = false;
      //set_power_mode(POWER_WORK_MODE);
      //vTaskDelay(2000 / portTICK_PERIOD_MS);
      if (target_power_volt > 40) {
        initial_voltage = target_power_volt;
      } else {
#ifdef SAMOVAR_USE_SEM_AVR
#ifndef WETTING_POWER
#define WETTING_POWER 2200 //мощность (для SEM_AVR) регулятора при смачивании насадки
#endif
        initial_voltage = WETTING_POWER;
#else
        initial_voltage = 220;
#endif
      }
    }

    // Максимальное время смачивания до начала понижения напряжения - 120 секунд
    unsigned long max_wetting_time = 120 * 1000;
    // Интервал снижения напряжения - 50 секунд
    unsigned long voltage_decrease_interval = 50 * 1000;
    // Минимальное допустимое напряжение (80% от начального)
    float min_voltage = initial_voltage * 0.8;
    // Максимальное общее время процесса смачивания - 20 минут (1200 секунд)
    unsigned long max_total_time = 1200 * 1000;
    // Время ожидания на минимальном напряжении перед автоматическим завершением - 3 минуты
    unsigned long min_voltage_wait_time = 180 * 1000;
    
    // Проверяем условия завершения
    
    // 1. Датчик сработал - смачивание успешно завершено
    if (head_level_sensor_holded()) {
      SendMsg(("Насадка колонны успешно смочена!"), NOTIFY_MSG);
      reset_wetting_state();
      return true;
    }
    
    // 2. Превышено максимальное общее время процесса
    // [L-36] Возвращаем false (не успех!) — оператор должен видеть, что смачивание
    // не завершено. Вызывающий код при false НЕ переходит к стабилизации и НЕ
    // автостартует головы. wetting_failed удерживает false до ручного сброса процесса.
    if (millis() - total_wetting_time >= max_total_time) {
      SendMsg(("Превышено максимальное время смачивания. Смачивание не удалось — остановите процесс вручную."), ALARM_MSG);
      reset_wetting_state();
      wetting_failed = true;  // устанавливаем ПОСЛЕ reset (reset очищает флаг)
      return false;
    }
    
    // Проверяем превышение максимального времени до начала снижения напряжения
    if (millis() - wetting_start_time >= max_wetting_time) {
      // Если время вышло и мы еще не начали снижать напряжение
      if (!voltage_decrease_started) {
        SendMsg(("Начинаем постепенное снижение напряжения"), WARNING_MSG);
        voltage_decrease_started = true;
        last_voltage_decrease_time = millis();
      }
      
      // Проверяем, нужно ли снизить напряжение
      if (voltage_decrease_started && (millis() - last_voltage_decrease_time >= voltage_decrease_interval)) {
        // Снижаем напряжение на 2% от текущего
        float new_voltage = target_power_volt * 0.98;
        
        // Проверяем, не опустились ли мы ниже минимального значения
        if (new_voltage >= min_voltage) {
          set_current_power(new_voltage);
          SendMsg(("Снижение напряжения до " + String(new_voltage)), WARNING_MSG);
          last_voltage_decrease_time = millis();
        } else {
          // Если достигли минимального напряжения
          if (min_voltage_time == 0) {
            min_voltage_time = millis();
            SendMsg(("Достигнуто минимальное напряжение: " + String(min_voltage) + ". Ожидаем срабатывания датчика."), WARNING_MSG);
          }
          
          // 3. Ждем определенное время на минимальном напряжении и завершаем процесс
          // [L-36] Аналогично: возвращаем false — смачивание не было успешным.
          if (millis() - min_voltage_time >= min_voltage_wait_time) {
            SendMsg(("Превышено время ожидания на минимальном напряжении. Смачивание не удалось — остановите процесс вручную."), ALARM_MSG);
            reset_wetting_state();
            wetting_failed = true;  // устанавливаем ПОСЛЕ reset (reset очищает флаг)
            return false;
          }
        }
      }
    }
    
    // Продолжаем процесс смачивания
    return false;
  }
  #endif

  // Если датчик не установлен
  SendMsg(("Датчик уровня флегмы не установлен, смачивание насадки невозможно"), WARNING_MSG);
  reset_wetting_state();
  return true;  // Немедленно завершаем
}
#endif
