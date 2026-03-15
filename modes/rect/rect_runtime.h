#ifndef __SAMOVAR_RECT_RUNTIME_H_
#define __SAMOVAR_RECT_RUNTIME_H_

#include <Arduino.h>

#include "Samovar.h"
#include "state/globals.h"
#include "app/alarm_control.h"
#include "app/process_common.h"
#include "io/actuators.h"
#include "io/power_control.h"
#include "support/format_utils.h"
#include "support/process_math.h"

void menu_samovar_start();
void stopService(void);
void startService(void);
void set_pump_pwm(float duty);
void set_pump_speed_pid(float temp);
void process_impurity_detector();
void reset_impurity_detector();
void detector_on_program_start(const String& wtype);
void detector_on_auto_resume();
void SendMsg(const String& m, MESSAGE_TYPE msg_type);
void pause_withdrawal(bool Pause);
void set_body_temp();

#ifdef COLUMN_WETTING
bool column_wetting();
#endif

inline void withdrawal(void) {
  if (!samovar_status_allows_rectification_withdrawal(SamovarStatusInt)) return;

  // ОБРАБОТКА ДЕТЕКТОРА ПРИМЕСЕЙ
  process_impurity_detector();

  //Определяем, что необходимо сменить режим работы
  //По завершению паузы
  if (program_Pause) {
    if (millis() >= t_min) {
      t_min = 0;
      menu_samovar_start();
    }
    return;
  }

  //По достижению шаговика цели
  CurrrentStepps = stepper.getCurrent();

  if (TargetStepps == CurrrentStepps && TargetStepps != 0 &&
      (startval == SAMOVAR_STARTVAL_RECT_PROGRAM_RUNNING ||
       startval == SAMOVAR_STARTVAL_RECT_PROGRAM_COMPLETE)) {
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

  float c_temp;  //стартовая температура отбора тела с учетом корректировки от давления или без
  c_temp = get_temp_by_pressure(SteamSensor.Start_Pressure, SteamSensor.BodyTemp, bme_pressure);

  //Возвращаем колонну в стабильное состояние, если работает программа отбора тела и температура пара вышла за пределы или корректируем пределы
  if ((program[ProgramNum].WType == "B" || program[ProgramNum].WType == "C") && (SteamSensor.avgTemp >= c_temp + SteamSensor.SetTemp) && SteamSensor.BodyTemp > 0) {
#ifdef USE_BODY_TEMP_AUTOSET
    //Если строка программы - предзахлеб и после есть еще две строки с отбором тела, то корректируем Т тела
    if ((ProgramNum < ProgramLen - 3) && program[ProgramNum].WType == "C" && (program[ProgramNum + 1].WType == "B" || program[ProgramNum + 1].WType == "C" || program[ProgramNum + 1].WType == "P") && (program[ProgramNum + 2].WType == "B" || program[ProgramNum + 2].WType == "C")) {
      set_body_temp();
    }
    //Если это первая строка с телом - корректируем Т тела
    else if ((ProgramNum > 0) && (program[ProgramNum].WType == "B" || program[ProgramNum].WType == "C") && program[ProgramNum - 1].WType == "H") {
      set_body_temp();
    } else
#endif
      //ставим отбор на паузу, если еще не стоит, и задаем время ожидания
      if (!PauseOn && !program_Wait) {
        program_Wait_Type = "(пар)";
        program_Wait = true;
        // Сбрасываем детектор при постановке на паузу - после снятия с паузы сохраненная скорость станет новой базовой
        reset_impurity_detector();
        pause_withdrawal(true);
        t_min = millis() + SteamSensor.Delay * 1000;
        set_buzzer(true);
        SendMsg(("Пауза по Т пара"), WARNING_MSG);
      }
    // если время вышло, еще раз пытаемся дождаться
    if (millis() >= t_min && SteamSensor.avgTemp >= c_temp + SteamSensor.SetTemp) {
      t_min = millis() + SteamSensor.Delay * 1000;
    }
  } else if ((program[ProgramNum].WType == "B" || program[ProgramNum].WType == "C") && SteamSensor.avgTemp < SteamSensor.BodyTemp + SteamSensor.SetTemp && millis() >= t_min && t_min > 0 && program_Wait) {
    //продолжаем отбор
    SendMsg(("Продолжаем отбор после автоматической паузы"), NOTIFY_MSG);
    t_min = 0;
    program_Wait = false;
    pause_withdrawal(false);
    // После возобновления с паузы устанавливаем сохраненную скорость как базовую для детектора
    // Вычисляем скорость в л/ч из сохраненной скорости шагов и временно корректируем program[ProgramNum].Speed
    if (SamSetup.useautospeed && ProgramNum < 30 && CurrrentStepperSpeed > 0) {
      float actualRate = get_liquid_rate_by_step(CurrrentStepperSpeed);
      if (actualRate > 0) {
        // Временно корректируем скорость программы на текущую скорость насоса
        // Это позволяет детектору считать текущую скорость базовой (correctionFactor = 1.0)
        program[ProgramNum].Speed = actualRate;
        impurityDetector.correctionFactor = 1.0f;
        impurityDetector.lastCorrectionTime = millis();
        // Устанавливаем скорость явно через set_pump_speed для синхронизации
        set_pump_speed(CurrrentStepperSpeed, true);
      }
    }
  }

  c_temp = get_temp_by_pressure(SteamSensor.Start_Pressure, PipeSensor.BodyTemp, bme_pressure);
  //Возвращаем колонну в стабильное состояние, если работает программа отбора тела и температура в колонне вышла за пределы или корректируем пределы
  if ((program[ProgramNum].WType == "B" || program[ProgramNum].WType == "C") && (PipeSensor.avgTemp >= c_temp + PipeSensor.SetTemp) && PipeSensor.BodyTemp > 0) {
#ifdef USE_BODY_TEMP_AUTOSET
    if ((ProgramNum < ProgramLen - 3) && program[ProgramNum].WType == "C" && (program[ProgramNum + 1].WType == "B" || program[ProgramNum + 1].WType == "C" || program[ProgramNum + 1].WType == "P") && (program[ProgramNum + 2].WType == "B" || program[ProgramNum + 2].WType == "C")) {
      set_body_temp();
    }
    //Если это первая строка с телом - корректируем Т тела
    else if ((ProgramNum > 0) && (program[ProgramNum].WType == "B" || program[ProgramNum].WType == "C") && program[ProgramNum - 1].WType == "H") {
      set_body_temp();
    } else
#endif
      //ставим отбор на паузу, если еще не стоит, и задаем время ожидания
      if (!PauseOn && !program_Wait) {
        program_Wait_Type = "(царга)";
        program_Wait = true;
        // Сбрасываем детектор при постановке на паузу - после снятия с паузы сохраненная скорость станет новой базовой
        reset_impurity_detector();
        pause_withdrawal(true);
        t_min = millis() + PipeSensor.Delay * 1000;
        set_buzzer(true);
        SendMsg(("Пауза по Т царги"), WARNING_MSG);
      }
    // если время вышло, еще раз пытаемся дождаться
    if (millis() >= t_min && PipeSensor.avgTemp >= c_temp + PipeSensor.SetTemp) {
      t_min = millis() + PipeSensor.Delay * 1000;
    }
  } else if ((program[ProgramNum].WType == "B" || program[ProgramNum].WType == "C") && PipeSensor.avgTemp < PipeSensor.BodyTemp + PipeSensor.SetTemp && millis() >= t_min && t_min > 0 && program_Wait) {
    //продолжаем отбор
    SendMsg(("Продолжаем отбор после автоматической паузы"), NOTIFY_MSG);
    t_min = 0;
    program_Wait = false;
    pause_withdrawal(false);
    // После возобновления с паузы устанавливаем сохраненную скорость как базовую для детектора
    // Вычисляем скорость в л/ч из сохраненной скорости шагов и временно корректируем program[ProgramNum].Speed
    if (SamSetup.useautospeed && ProgramNum < 30 && CurrrentStepperSpeed > 0) {
      float actualRate = get_liquid_rate_by_step(CurrrentStepperSpeed);
      if (actualRate > 0) {
        // Временно корректируем скорость программы на текущую скорость насоса
        // Это позволяет детектору считать текущую скорость базовой (correctionFactor = 1.0)
        program[ProgramNum].Speed = actualRate;
        impurityDetector.correctionFactor = 1.0f;
        impurityDetector.lastCorrectionTime = millis();
        // Устанавливаем скорость явно через set_pump_speed для синхронизации
        set_pump_speed(CurrrentStepperSpeed, true);
      }
    }
  }

  // Пауза детектора: после истечения таймера возобновляем отбор
  if (program_Wait && program_Wait_Type == "(Детектор)" && t_min > 0 && millis() >= t_min) {
    SendMsg(("Детектор: Продолжаем отбор после паузы"), NOTIFY_MSG);
    t_min = 0;
    program_Wait = false;
    pause_withdrawal(false);
    detector_on_auto_resume();
  }
  vTaskDelay(10 / portTICK_PERIOD_MS);
}

inline void pause_withdrawal(bool Pause) {
  if (Samovar_Mode != SAMOVAR_RECTIFICATION_MODE) return;
  if (!stepper.getState() && !PauseOn) return;
  PauseOn = Pause;
  if (Pause) {
    TargetStepps = stepper.getTarget();
    CurrrentStepps = stepper.getCurrent();
    if (CurrrentStepperSpeed < 1) CurrrentStepperSpeed = (uint16_t)max(1, (int)abs((int)stepper.getSpeed()));
    stopService();
    stepper.brake();
    stepper.disable();
  } else {
    stepper.setMaxSpeed(CurrrentStepperSpeed);
    //stepper.setSpeed(CurrrentStepperSpeed);
    stepper.setCurrent(CurrrentStepps);
    stepper.setTarget(TargetStepps);
    startService();
  }
}

inline void run_program(uint8_t num) {
  // Проверяем смену типа программы для сброса детектора
  // Сбрасываем детектор только при переходе:
  // - H (головы) -> B/C (тело/предзахлеб)
  // - B/C (тело/предзахлеб) -> T (хвосты)
  // НЕ сбрасываем при переходе B <-> C (между телом и предзахлебом)
  bool needReset = false;

  if (num < 30 && program[num].WType.length() > 0) {
    String currentType = program[num].WType;

    // Проверяем предыдущую программу, если она существует
    if (num > 0 && program[num - 1].WType.length() > 0) {
      String prevType = program[num - 1].WType;

      // Переход с голов на тело/предзахлеб
      if (prevType == "H" && (currentType == "B" || currentType == "C")) {
        needReset = true;
      }
      // Переход с тела/предзахлеба на хвосты
      else if ((prevType == "B" || prevType == "C") && currentType == "T") {
        needReset = true;
      }
      // Переход с любого другого типа на тело/предзахлеб (если не было B/C)
      else if (prevType != "B" && prevType != "C" && (currentType == "B" || currentType == "C")) {
        needReset = true;
      }
      // Переход с тела/предзахлеба на любой другой тип (кроме B/C)
      else if ((prevType == "B" || prevType == "C") && currentType != "B" && currentType != "C") {
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
  if (ProgramNum < 30 && program[ProgramNum].WType.length() > 0) {
    detector_on_program_start(program[ProgramNum].WType);
  }

  // Сбрасываем детектор только если нужно
  if (needReset) {
    reset_impurity_detector();
  }

  t_min = 0;
  program_Pause = false;
  program_Wait = false;
  PauseOn = false;
  pause_withdrawal(false);

  //запоминаем текущие значения температур
  SteamSensor.StartProgTemp = SteamSensor.avgTemp;
  PipeSensor.StartProgTemp = PipeSensor.avgTemp;
  WaterSensor.StartProgTemp = WaterSensor.avgTemp;
  TankSensor.StartProgTemp = TankSensor.avgTemp;

  String p_s;
  if (num == CAPACITY_NUM * 2) {
    //если num = CAPACITY_NUM * 2 значит мы достигли финала (или отбор сброшен принудительно), завершаем отбор
    ProgramNum = 0;
    stopService();
    stepper.brake();
    stepper.disable();
    stepper.setCurrent(0);
    stepper.setTarget(0);
    set_capacity(0);
    if (fileToAppend) {
      fileToAppend.close();
    }
    stop_process("Выполнение программы завершено.");
  } else {
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
    if (program[num].WType == "C" && alarm_c_low_min == 0) alarm_c_low_min = millis();
#endif
    p_s = "Программа: старт строки  №" + (String)(num + 1);
    if (program[num].WType == "H" || program[num].WType == "B" || program[num].WType == "T" || program[num].WType == "C") {
      if (program[num].WType == "H" || program[num].WType == "T") {
        SteamSensor.BodyTemp = 0;
        PipeSensor.BodyTemp = 0;
        WaterSensor.BodyTemp = 0;
        TankSensor.BodyTemp = 0;
      }
      p_s += ", отбор в ёмкость " + (String)program[num].capacity_num;
      //устанавливаем параметры для текущей программы отбора
      set_capacity(program[num].capacity_num);
      CurrrentStepperSpeed = (uint16_t)get_speed_from_rate(program[num].Speed);
      stepper.setMaxSpeed(CurrrentStepperSpeed);
      //stepper.setSpeed(get_speed_from_rate(program[num].Speed));
      TargetStepps = program[num].Volume * SamSetup.StepperStepMl;
      stepper.setCurrent(0);
      stepper.setTarget(TargetStepps);
      startService();
      ActualVolumePerHour = program[num].Speed;
      if ((program[num].WType == "B" || program[num].WType == "C") && program[num].Temp > 0) {
        SteamSensor.BodyTemp = program[num].Temp;
      }

      //Если у первой программы отбора тела не задана температура, при которой начинать отбор, считаем, что она равна текущей
      //Считаем, что колонна стабильна
      //Итак, текущая температура - это температура, которой Самовар будет придерживаться во время всех программ отобора тела.
      //Если она будет выходить за пределы, заданные в настройках, отбор будет ставиться на паузу, и продолжится после возвращения температуры в колонне к заданному значению.
      if ((program[num].WType == "B" || program[num].WType == "C") && SteamSensor.BodyTemp == 0) {
        set_body_temp();
      }
    } else if (program[num].WType == "P") {
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
      stepper.setMaxSpeed(0);
      CurrrentStepperSpeed = 0;
      //stepper.setSpeed(-1);
      stepper.brake();
      stepper.disable();
      stepper.setCurrent(0);
      stepper.setTarget(0);
    }
  }

  if (SamSetup.ChangeProgramBuzzer) {
    set_buzzer(true);
    SendMsg(p_s, ALARM_MSG);
  } else {
    SendMsg(p_s, NOTIFY_MSG);
  }

  TargetStepps = stepper.getTarget();
}

inline void set_body_temp() {
  reset_impurity_detector();
  if (program[ProgramNum].WType == "B" || program[ProgramNum].WType == "C" || program[ProgramNum].WType == "P") {
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

inline void check_alarm() {
  static bool close_valve_message_sent = false;
  //сбросим паузу события безопасности
  if (alarm_t_min > 0 && alarm_t_min <= millis()) alarm_t_min = 0;

#ifdef SAMOVAR_USE_POWER
  //управляем разгонным тэном
  if (SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_WARMUP &&
      TankSensor.avgTemp <= OPEN_VALVE_TANK_TEMP &&
      PowerOn) {
    if (!acceleration_heater) {
      //включаем разгонный тэн
      digitalWrite(RELE_CHANNEL4, SamSetup.rele4);
      acceleration_heater = true;
    }
  } else {
    if (acceleration_heater) {
      //выключаем разгонный тэн
      digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);
      acceleration_heater = false;
    }
  }
#endif

  //Если используется датчик уровня флегмы в голове
#ifdef USE_HEAD_LEVEL_SENSOR
  if (SamSetup.UseHLS && PowerOn) {
    whls.tick();
    if (whls.isHolded() && alarm_h_min == 0) {
      whls.resetStates();
      if (program[ProgramNum].WType != "C") {
        set_buzzer(true);
        SendMsg(("Сработал датчик захлёба!"), ALARM_MSG);
#ifdef SAMOVAR_USE_POWER
        alarm_c_min = 0;
        alarm_c_low_min = 0;
        prev_target_power_volt = 0;
#endif
      } else {
#ifdef SAMOVAR_USE_POWER
        //запускаем счетчик - TIME_C минут, нужен для возврата заданного напряжения
        alarm_c_min = millis() + 1000 * 60 * TIME_C / 5;
        //счетчик для повышения напряжения сбрасываем
        alarm_c_low_min = 0;
        if (prev_target_power_volt == 0) prev_target_power_volt = target_power_volt;
#endif
      }
#ifdef SAMOVAR_USE_POWER
      SendMsg((String)PWR_MSG + " снижаем с " + (String)target_power_volt, NOTIFY_MSG);
#ifdef SAMOVAR_USE_SEM_AVR
      set_current_power(target_power_volt - target_power_volt / 100 * 3);
#else
      set_current_power(target_power_volt - 1 * PWR_FACTOR);
#endif
#endif
      //Если уже реагировали - надо подождать 40 секунд, так как процесс инерционный
      alarm_h_min = millis() + 1000 * 40;
    }

    if (alarm_h_min > 0 && alarm_h_min <= millis()) {
      whls.resetStates();
      alarm_h_min = 0;
    }
#ifdef SAMOVAR_USE_POWER
    //Если программа - предзахлеб, и сброс напряжения был больше TIME_C минут назад, то возвращаем напряжение к последнему сохраненному - 0.5
    if (alarm_c_min > 0 && alarm_c_min <= millis()) {
      if (program[ProgramNum].WType == "C") {
        if (prev_target_power_volt == 0) {
#ifdef SAMOVAR_USE_SEM_AVR
          prev_target_power_volt = target_power_volt + target_power_volt / 100 * 4;
#else
          prev_target_power_volt = target_power_volt + 2 * PWR_FACTOR;
#endif
        }
#ifdef SAMOVAR_USE_SEM_AVR
        set_current_power(prev_target_power_volt - target_power_volt / 100 * 3);
#else
        set_current_power(prev_target_power_volt - 1 * PWR_FACTOR);
#endif
        SendMsg((String)PWR_MSG + " повышаем до " + (String)target_power_volt, NOTIFY_MSG);
        prev_target_power_volt = 0;
        //запускаем счетчик - TIME_C минут, нужен для повышения текущего напряжения чтобы поймать предзахлеб
        alarm_c_low_min = millis() + 1000 * 60 * TIME_C;
      }
      alarm_c_min = 0;
    }
    //Если программа предзахлеб и давно не было срабатывания датчика - повышаем напряжение
    if (program[ProgramNum].WType == "C") {
      if (alarm_c_low_min > 0 && alarm_c_low_min <= millis()) {
#ifdef SAMOVAR_USE_SEM_AVR
        set_current_power(target_power_volt + target_power_volt / 100 * 1);
#else
        set_current_power(target_power_volt + 0.5 * PWR_FACTOR);
#endif
        alarm_c_low_min = millis() + 1000 * 60 * TIME_C;
      } else if (alarm_c_low_min == 0 && alarm_c_min == 0) {
        alarm_c_low_min = millis() + 1000 * 60 * TIME_C;
      }
    } else alarm_c_low_min = 0;

#endif
  }
  //Если используется датчик уровня флегмы в голове
#endif


#ifdef SAMOVAR_USE_POWER
  check_power_error();
#endif

  if (!valve_status) {
    if (ACPSensor.avgTemp >= MAX_ACP_TEMP - 5) {
      set_buzzer(true);
      open_valve(true, true);
    } else if (TankSensor.avgTemp >= OPEN_VALVE_TANK_TEMP && PowerOn) {
      set_buzzer(true);
      open_valve(true, true);
    }
  }

  if (!PowerOn && !is_self_test && valve_status && WaterSensor.avgTemp <= SamSetup.SetWaterTemp - DELTA_T_CLOSE_VALVE && ACPSensor.avgTemp <= MAX_ACP_TEMP - 10) {
    if (!close_valve_message_sent) {
      open_valve(false, true);
      set_buzzer(true);
      close_valve_message_sent = true;
    }
#ifdef USE_WATER_PUMP
    if (pump_started) set_pump_pwm(0);
#endif
  }
  if (valve_status && close_valve_message_sent) {
    close_valve_message_sent = false;
  }

  //Определяем, что началось кипение - вода охлаждения начала нагреваться
  //check_boiling();

#ifdef USE_WATER_PUMP
  //Устанавливаем ШИМ для насоса в зависимости от температуры воды
  if (valve_status) {
    if (ACPSensor.avgTemp > 39 && ACPSensor.avgTemp > WaterSensor.avgTemp) set_pump_speed_pid(SamSetup.SetWaterTemp + 3);
    else
      set_pump_speed_pid(WaterSensor.avgTemp);
  }
#endif

  //Проверяем, что температурные параметры не вышли за предельные значения
  if ((SteamSensor.avgTemp >= MAX_STEAM_TEMP || WaterSensor.avgTemp >= MAX_WATER_TEMP || TankSensor.avgTemp >= SamSetup.DistTemp || ACPSensor.avgTemp >= MAX_ACP_TEMP) && PowerOn) {
    //Если с температурой проблемы - выключаем нагрев, пусть оператор разбирается
    delay(1000);  //Пауза на всякий случай, чтобы прошли все другие команды
    set_buzzer(true);
    set_power(false);
    String s = "";
    if (SteamSensor.avgTemp >= MAX_STEAM_TEMP) s = s + " Пара";
    else if (WaterSensor.avgTemp >= MAX_WATER_TEMP)
      s = s + " Воды";
    else if (ACPSensor.avgTemp >= MAX_ACP_TEMP)
      s = s + " ТСА";

    if (TankSensor.avgTemp >= SamSetup.DistTemp) {
      //Если температура в кубе превысила заданную, штатно завершаем ректификацию.
      SendMsg(("Лимит максимальной температуры куба. Программа завершена."), NOTIFY_MSG);
    } else
      SendMsg("Аварийное отключение! Превышена максимальная температура" + s, ALARM_MSG);
  }

#ifdef USE_WATERSENSOR
  //Проверим, что вода подается
  if (WFAlarmCount > WF_ALARM_COUNT && PowerOn) {
    set_buzzer(true);
    //Если с водой проблемы - выключаем нагрев, пусть оператор разбирается
    sam_command_sync = SAMOVAR_POWER;
    SendMsg(("Аварийное отключение! Прекращена подача воды."), ALARM_MSG);
  }
#endif

  if ((WaterSensor.avgTemp >= ALARM_WATER_TEMP - 5) && PowerOn && alarm_t_min == 0) {
    set_buzzer(true);
    //Если уже реагировали - надо подождать 30 секунд, так как процесс инерционный
    SendMsg(("Критическая температура воды!"), WARNING_MSG);

#ifdef SAMOVAR_USE_POWER
    if (WaterSensor.avgTemp >= ALARM_WATER_TEMP) {
      set_buzzer(true);
      SendMsg("Критическая температура воды! Ошибка подачи воды. " + (String)PWR_MSG + " снижаем с " + (String)target_power_volt, ALARM_MSG);
      //Попробуем снизить напряжение регулятора на 5 вольт, чтобы исключить перегрев колонны.
#ifdef SAMOVAR_USE_SEM_AVR
      set_current_power(target_power_volt - target_power_volt / 100 * 8);
#else
      set_current_power(target_power_volt - 5 * PWR_FACTOR);
#endif
    }
#endif
    alarm_t_min = millis() + 1000 * 30;
  }

  if (SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_WARMUP &&
      SteamSensor.avgTemp >= CHANGE_POWER_MODE_STEAM_TEMP) {
#ifdef USE_WATER_PUMP
    //Сбросим счетчик насоса охлаждения, что приведет к увеличению потока воды. Дальше уже будет штатно работать PID
    wp_count = -5;
#endif

    bool column_wetting_result = true;
#ifdef COLUMN_WETTING
    // Смачивание насадки колонны
    column_wetting_result = column_wetting();
#endif

    if (column_wetting_result) {

        //достигли заданной температуры на разгоне и смочили насадку (если используется эта функция), переходим на рабочий режим, устанавливаем заданную температуру, зовем оператора
        SamovarStatusInt = SAMOVAR_STATUS_RECTIFICATION_STABILIZING;

        // Инициализируем переменные для проверки стабилизации
        acceleration_temp = 0;

#ifdef COLUMN_WETTING
        // Помечаем, что после стабилизации нужно автоматически перейти к головам
        wetting_autostart = (startval == SAMOVAR_STARTVAL_RECT_IDLE);
#endif

        SendMsg("Разгон завершён. Стабилизация/работа на себя.", NOTIFY_MSG);
        set_buzzer(true);
#ifdef SAMOVAR_USE_POWER
        set_current_power(program[0].Power);
#else
        current_power_mode = POWER_WORK_MODE;
        digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);
#endif
    }
  }

  if (SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_STABILIZING && !boil_started) {
    set_boiling();
    if (boil_started) {
      SendMsg("Спиртуозность " + format_float(alcohol_s, 1), WARNING_MSG);
    }
  }

  //Разгон и стабилизация завершены - шесть минут температура пара не меняется больше, чем на 0.1 градус:
  //https://alcodistillers.ru/forum/viewtopic.php?id=137 - указано 3 замера раз в три минуты.
  if (SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_STABILIZING &&
      SteamSensor.avgTemp > CHANGE_POWER_MODE_STEAM_TEMP) {
    static float prev_stable_temp = 0;  // Предыдущая температура для проверки стабилизации
    float d = SteamSensor.avgTemp - prev_stable_temp;
    d = abs(d);
    if (d < 0.1) {
      acceleration_temp += 1;
      if (acceleration_temp == 60 * 6) {
        SamovarStatusInt = SAMOVAR_STATUS_RECTIFICATION_STABILIZED;
        acceleration_temp = 0;  // Сбрасываем счетчик после установки статуса стабилизации
        prev_stable_temp = 0;  // Сбрасываем предыдущую температуру
        set_buzzer(true);
        SendMsg(("Стабилизация завершена, колонна работает стабильно."), NOTIFY_MSG);
#ifdef COLUMN_WETTING
        if (wetting_autostart && startval == SAMOVAR_STARTVAL_RECT_IDLE) {
          wetting_autostart = false;
          menu_samovar_start();  // Автостарт голов после стабилизации
        }
#endif
      }
    } else {
      acceleration_temp = 0;
      prev_stable_temp = SteamSensor.avgTemp;  // Обновляем предыдущую температуру только при изменении
    }
  }
#ifdef USE_WATER_VALVE
  if (WaterSensor.avgTemp >= SamSetup.SetWaterTemp + 1) {
    digitalWrite(WATER_PUMP_PIN, USE_WATER_VALVE);
  } else if (WaterSensor.avgTemp <= SamSetup.SetWaterTemp - 1) {
    digitalWrite(WATER_PUMP_PIN, !USE_WATER_VALVE);
  }
#endif
}

#ifdef COLUMN_WETTING
inline bool column_wetting() {
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
  };

  // Проверяем, что датчик уровня флегмы установлен
#ifdef USE_HEAD_LEVEL_SENSOR
  if (SamSetup.UseHLS) {
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
    if (whls.isHolded()) {
      SendMsg(("Насадка колонны успешно смочена!"), NOTIFY_MSG);
      reset_wetting_state();
      return true;
    }

    // 2. Превышено максимальное общее время процесса
    if (millis() - total_wetting_time >= max_total_time) {
      SendMsg(("Превышено максимальное время смачивания. Процесс прерван."), WARNING_MSG);
      reset_wetting_state();
      return true;
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
          if (millis() - min_voltage_time >= min_voltage_wait_time) {
            SendMsg(("Превышено время ожидания на минимальном напряжении. Завершаем процесс смачивания."), WARNING_MSG);
            reset_wetting_state();
            return true;
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

#endif
