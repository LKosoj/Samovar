#include <Arduino.h>
#include "Samovar.h"

void save_profile();
void beer_finish();
void set_heater_state(float setpoint, float temp);
void set_heater(double dutyCycle);
void setHeaterPosition(bool state);
void run_beer_program(byte num);
void StartAutoTune();
void FinishAutoTune();
void set_power(bool On);
void create_data();
void open_valve(bool Val);

void beer_proc() {
  if (SamovarStatusInt != 2000) return;

  if (startval == 2000 && !PowerOn) {
    create_data();  //создаем файл с данными
    PowerOn = true;
    set_power(true);
    run_beer_program(0);
  }
}

void IRAM_ATTR run_beer_program(byte num) {
  if (startval == 2000) startval = 2001;
  ProgramNum = num;
  begintime = 0;
  if (program[ProgramNum].WType == "A") {
    StartAutoTune();
  }

  if (ProgramNum > ProgramLen - 1) num = CAPACITY_NUM * 2;

  if (SamSetup.ChangeProgramBuzzer){
    set_buzzer(true);
  }

  if (num == CAPACITY_NUM * 2) {
    //если num = CAPACITY_NUM * 2 значит мы достигли финала (или процесс сброшен принудительно), завершаем работу
    beer_finish();
  } else {
    Msg = "Переход к строке программы №" + (String)(num + 1);
#ifdef SAMOVAR_USE_BLYNK
    //Если используется Blynk - пишем оператору
    Blynk.notify("{DEVICE_NAME} " + Msg);
#endif
  }
}

void IRAM_ATTR beer_finish() {
  if (valve_status) {
    open_valve(false);
  }
#ifdef USE_WATER_PUMP
  if (pump_started) set_pump_pwm(0);
#endif
  PowerOn = false;
  heater_state = false;
  startval = 0;
  Msg = "Программа затирания завершена";
#ifdef SAMOVAR_USE_BLYNK
  //Если используется Blynk - пишем оператору
  Blynk.notify("{DEVICE_NAME} " + Msg);
#endif
  set_power(false);
  reset_sensor_counter();
}

void IRAM_ATTR check_alarm_beer() {
  if (startval <= 2000) return;

  //Обрабатываем программу

  //Если программа - ожидание - ждем, ничего не делаем
  if (program[ProgramNum].WType == "W") {
    if (begintime == 0) {
      begintime = millis();
      setHeaterPosition(false);
    }
    return;
  }

  //Если режим Автотюнинг
  if (program[ProgramNum].WType == "A") {
    if (tuning) {
      set_heater_state(program[ProgramNum].Temp, TankSensor.avgTemp);
    } else {
      beer_finish();
    }
  }

  //Если режим Засыпь солода или Пауза
  if (program[ProgramNum].WType == "M" || program[ProgramNum].WType == "P") {
    set_heater_state(program[ProgramNum].Temp, TankSensor.avgTemp);
  }

  if (program[ProgramNum].WType == "M" && TankSensor.avgTemp >= program[ProgramNum].Temp - 0.1) {
    //Достигли температуры засыпи солода. Пишем об этом. Продолжаем поддерживать температуру. Переход с этой строки программы на следующую возможен только в ручном режиме
    if (startval == 2001) {
      set_buzzer(true);
      Msg = "Достигнута температура засыпи солода!";
#ifdef SAMOVAR_USE_BLYNK
      //Если используется Blynk - пишем оператору
      Blynk.notify("Предупреждение! {DEVICE_NAME} - " + Msg);
#endif
    }
    startval = 2002;
  }

  if (program[ProgramNum].WType == "P" && TankSensor.avgTemp >= program[ProgramNum].Temp - 0.1) {
    if (begintime == 0) {
      //Засекаем время для отсчета, сколько держать паузу
      begintime = millis();
      Msg = "Достигнута температурная пауза. Ждем завершения.";
#ifdef SAMOVAR_USE_BLYNK
      //Если используется Blynk - пишем оператору
      Blynk.notify("Предупреждение! {DEVICE_NAME} - " + Msg);
#endif
    }
    //Проверяем, что еще нужно держать паузу
    if ((millis() - begintime) / 1000 / 60 >= program[ProgramNum].Time) {
      //Запускаем следующую программу
      run_beer_program(ProgramNum + 1);
    }
  }

  //Если программа - охлаждение - ждем, когда температура в кубе упадет ниже заданной, и управляем водой для охлаждения
  if (program[ProgramNum].WType == "C") {
    if (begintime == 0) {
      begintime = millis();
      setHeaterPosition(false);
      //Открываем клапан воды
      open_valve(true);
#ifdef USE_WATER_PUMP
      if (pump_started) set_pump_pwm(1023);
#endif
    }
    if (TankSensor.avgTemp <= program[ProgramNum].Temp) {
      //Если температура упала
      //Закрываем клапан воды
      open_valve(false);
      //запускаем следующую программу
      run_beer_program(ProgramNum + 1);
    }
  }

  //Если программа - кипячение
  if (program[ProgramNum].WType == "B") {
    //Если предыдущая программа была программой кипячения - просто продолжаем кипятить.
    if (begintime == 0 && ProgramNum > 0 && program[ProgramNum - 1].WType == "B") begintime = millis();

    if (begintime == 0) {
      //Если температура в кубе достигла температуры кипения, засекаем время
      if (abs(TankSensor.avgTemp - BOILING_TEMP) <= 0.5) {
        msgfl = true;
        begintime = millis();
        Msg = "Начался режим кипячения";
#ifdef SAMOVAR_USE_BLYNK
        //Если используется Blynk - пишем оператору
      Blynk.notify("Предупреждение! {DEVICE_NAME} - " + Msg);
#endif
      }
    }

    //Греем до температуры кипения, исходя из того, что датчик в кубе врет не сильно
    if (begintime == 0) {
      set_heater_state(BOILING_TEMP + 5, TankSensor.avgTemp);
    } else {
      //Иначе поддерживаем температуру
      heater_state = true;
#ifdef SAMOVAR_USE_POWER
      //Устанавливаем заданное напряжение
      set_current_power(SamSetup.StbVoltage);
#else
      current_power_mode = POWER_WORK_MODE;
      digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);
      digitalWrite(RELE_CHANNEL1, SamSetup.rele1);
#endif
    }

    //Проверяем, что еще нужно держать паузу. За 30 секунд до окончания шлем сообщение
    if (begintime > 0 && msgfl && ((float(millis()) - begintime) / 1000 / 60 + 0.5 >= program[ProgramNum].Time)) {
      set_buzzer(true);
      msgfl = false;
      Msg = "Засыпьте хмель!";
#ifdef SAMOVAR_USE_BLYNK
      //Если используется Blynk - пишем оператору
      Blynk.notify("Предупреждение! {DEVICE_NAME} - " + Msg);
#endif
    }

    //Проверяем, что еще нужно держать паузу
    if (begintime > 0 && ((millis() - begintime) / 1000 / 60 >= program[ProgramNum].Time)) {
      //Запускаем следующую программу
      run_beer_program(ProgramNum + 1);
    }
  }
}

void set_heater_state(float setpoint, float temp) {
  if (setpoint - temp > HEAT_DELTA && !tuning) {
    heater_state = true;
#ifdef SAMOVAR_USE_POWER
    delay(200);
    set_power_mode(POWER_SPEED_MODE);
#else
    current_power_mode = POWER_WORK_MODE;
    digitalWrite(RELE_CHANNEL1, SamSetup.rele1);
    digitalWrite(RELE_CHANNEL4, SamSetup.rele4);
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
    set_heater(Output / 100);
  }
}

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

void setHeaterPosition(bool state) {
  heater_state = state;

  if (state) {
#ifdef SAMOVAR_USE_POWER
    //Устанавливаем заданное напряжение
    set_current_power(SamSetup.StbVoltage);

#ifndef __SAMOVAR_DEBUG
  //Проверим, что заданное напряжение/мощность не сильно отличается от реального (наличие связи с регулятором, пробой семистора)
  if (SamSetup.CheckPower && current_power_mode == POWER_WORK_MODE && abs((current_power_volt - target_power_volt)/current_power_volt) > 0.1) {
    power_err_cnt++;
    //if (power_err_cnt > 8) set_current_power(target_power_volt);
    if (power_err_cnt > 10) {
      delay(1000); //Пауза на всякий случай, чтобы прошли все другие команды
      set_power(false);
      Msg = "Аварийное отключение! Ошибка управления нагревателем.";
#ifdef SAMOVAR_USE_BLYNK
      //Если используется Blynk - пишем оператору
    Blynk.notify("Тревога! {DEVICE_NAME} - " + Msg);
#endif
    }
  } else power_err_cnt = 0;
#endif

#else
    current_power_mode = POWER_WORK_MODE;
    digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);
    digitalWrite(RELE_CHANNEL1, SamSetup.rele1);
    vTaskDelay(200);
#endif
  } else {
#ifdef SAMOVAR_USE_POWER
    if (current_power_mode != POWER_SLEEP_MODE) {
      delay(200);
      set_power_mode(POWER_SLEEP_MODE);
    }
    //Устанавливаем заданное напряжение
    //set_current_power(0);
#else
    current_power_mode = POWER_WORK_MODE;
    digitalWrite(RELE_CHANNEL1, !SamSetup.rele1);
    digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);
#endif
  }
}

String get_beer_program() {
  String Str = "";
  int k = CAPACITY_NUM * 2;
  for (int i = 0; i < k; i++) {
    if (program[i].WType == "") {
      i = CAPACITY_NUM * 2 + 1;
    } else {
      Str += program[i].WType + ";";
      Str += (String)program[i].Temp + ";";
      Str += (String)(int)program[i].Time + "\n";
    }
  }
  return Str;
}

void set_beer_program(String WProgram) {
  //M - malt application temp, P - pause, B - boil, C - cool
  char c[500];
  WProgram.toCharArray(c, 500);
  char *pair = strtok(c, ";");
  int i = 0;
  while (pair != NULL and i < CAPACITY_NUM * 2) {
    program[i].WType = pair;
    pair = strtok(NULL, ";");
    program[i].Temp = atof(pair);
    pair = strtok(NULL, "\n");
    program[i].Time = atof(pair);
    i++;
    ProgramLen = i;
    pair = strtok(NULL, ";");
    if ((!pair || pair == NULL || pair[0] == 13) and i < CAPACITY_NUM * 2) {
      program[i].WType = "";
      break;
    }
  }
}

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

void FinishAutoTune() {
  aTune.Cancel();
  tuning = false;

  // Extract the auto-tune calculated parameters
  SamSetup.Kp = aTune.GetKp();
  SamSetup.Ki = aTune.GetKi();
  SamSetup.Kd = aTune.GetKd();

  WriteConsoleLog("Kp = " + (String)Kp);
  WriteConsoleLog("Ki = " + (String)Ki);
  WriteConsoleLog("Kd = " + (String)Kd);

  // Re-tune the PID and revert to normal control mode
  heaterPID.SetTunings(SamSetup.Kp, SamSetup.Ki, SamSetup.Kd);
  heaterPID.SetMode(ATuneModeRemember);

  save_profile();
  read_config();

  set_heater_state(0, 50);
}

void IRAM_ATTR set_mixer(bool On) {
  mixer_status = On;
  if (On) {
    digitalWrite(RELE_CHANNEL2, SamSetup.rele2);
  } else {
    digitalWrite(RELE_CHANNEL2, !SamSetup.rele2);
  }
}
