#include <Arduino.h>
#include "Samovar.h"

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
    create_data();                    //создаем файл с данными
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

  if (num == CAPACITY_NUM * 2) {
    //если num = CAPACITY_NUM * 2 значит мы достигли финала (или процесс сброшен принудительно), завершаем работу
    beer_finish();
  } else {
    Msg = "Set prog line " + (String)(num + 1);
#ifdef SAMOVAR_USE_BLYNK
    //Если используется Blynk - пишем оператору
    Blynk.notify("{DEVICE_NAME} " + Msg);
#endif
  }
}

void IRAM_ATTR beer_finish() {
  if (valve_status){
    open_valve(false);
  }
  PowerOn = false;
  heater_state = false;
  startval = 0;
  Msg = "Beer finished";
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
      set_buzzer();
      Msg = "Malt application temperature reached!";
#ifdef SAMOVAR_USE_BLYNK
      //Если используется Blynk - пишем оператору
      Blynk.notify("{DEVICE_NAME} " + Msg);
#endif
    }
    startval = 2002;
  }

  if (program[ProgramNum].WType == "P" && TankSensor.avgTemp >= program[ProgramNum].Temp - 0.1) {
    if (begintime == 0) {
      //Засекаем время для отсчета, сколько держать паузу
      begintime = millis();
      Msg = "Pause temperature reached! Start waiting";
#ifdef SAMOVAR_USE_BLYNK
      //Если используется Blynk - пишем оператору
      Blynk.notify("{DEVICE_NAME} " + Msg);
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
        Msg = "Boiling started!";
#ifdef SAMOVAR_USE_BLYNK
        //Если используется Blynk - пишем оператору
        Blynk.notify("{DEVICE_NAME} " + Msg);
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
      if (current_power_mode != POWER_WORK_MODE) {
        vTaskDelay(200);
        set_power_mode(POWER_WORK_MODE);
        vTaskDelay(800);
      }
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
      set_buzzer();
      msgfl = false;
      Msg = "Bring in the hops!";
#ifdef SAMOVAR_USE_BLYNK
      //Если используется Blynk - пишем оператору
      Blynk.notify("{DEVICE_NAME} " + Msg);
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

    if (tuning) // run the auto-tuner
    {
      if (aTune.Runtime()) // returns 'true' when done
      {
        FinishAutoTune();
      }
    }
    else // Execute control algorithm
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

#ifdef __SAMOVAR_DEBUG
  WriteConsoleLog("dutyCycle = " + String(dutyCycle));
#endif

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

#ifdef __SAMOVAR_DEBUG
  WriteConsoleLog("heater_state = " + String(heater_state));
#endif

  if (state) {
#ifdef SAMOVAR_USE_POWER
    if (current_power_mode != POWER_WORK_MODE) {
      delay(200);
      set_power_mode(POWER_WORK_MODE);
      delay(800);
    }
    //Устанавливаем заданное напряжение
    set_current_power(SamSetup.StbVoltage);
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
      delay(800);
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

void StartAutoTune()
{
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

void FinishAutoTune()
{
  aTune.Cancel();
  tuning = false;

  // Extract the auto-tune calculated parameters
  SamSetup.Kp = aTune.GetKp();
  SamSetup.Ki = aTune.GetKi();
  SamSetup.Kd = aTune.GetKd();

  Serial.print("Kp = ");
  Serial.print(Kp);
  Serial.print("\tKi = ");
  Serial.print(Ki);
  Serial.print("\tKd = ");
  Serial.println(Kd);

  // Re-tune the PID and revert to normal control mode
  heaterPID.SetTunings(SamSetup.Kp, SamSetup.Ki, SamSetup.Kd);
  heaterPID.SetMode(ATuneModeRemember);

  EEPROM.put(0, SamSetup);
  EEPROM.commit();
  read_config();

  set_heater_state(0, 50);
}
