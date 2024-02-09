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
void SendMsg(String m, MESSAGE_TYPE msg_type);
String get_beer_program();
void check_mixer_state();
void set_mixer_state(bool state, bool dir);
bool set_mixer_pump_target(uint8_t on);
bool set_stepper_by_time(uint16_t spd, uint8_t direction, uint16_t time);
void HopStepperStep();

void beer_proc() {
  if (SamovarStatusInt != 2000) return;

  if (startval == 2000 && !PowerOn) {
#ifdef USE_MQTT
    SessionDescription.replace(",", ";");
    MqttSendMsg((String)chipId + "," + SamSetup.TimeZone + "," + SAMOVAR_VERSION + "," + get_beer_program() + "," + SessionDescription, "st");
#endif
    create_data();  //создаем файл с данными
    PowerOn = true;
    set_power(true);
    run_beer_program(0);
  }
  vTaskDelay(10 / portTICK_PERIOD_MS);
}

void run_beer_program(byte num) {
  if (Samovar_Mode != SAMOVAR_BEER_MODE || !PowerOn) return;
  if (startval == 2000) startval = 2001;
  ProgramNum = num;
  begintime = 0;
  msgfl = true;

  if (program[ProgramNum].WType == "A") {
    StartAutoTune();
  }

  if (ProgramNum > ProgramLen - 1) num = CAPACITY_NUM * 2;

  if (SamSetup.ChangeProgramBuzzer) {
    set_buzzer(true);
  }

  if (num == CAPACITY_NUM * 2) {
    //если num = CAPACITY_NUM * 2 значит мы достигли финала (или процесс сброшен принудительно), завершаем работу
    beer_finish();
  } else {
    SendMsg("Переход к строке программы №" + (String)(num + 1), NOTIFY_MSG);
  }
  //сбрасываем переменные для мешалки и насоса
  alarm_c_low_min = 0;  //мешалка вкл
  alarm_c_min = 0;  //мешалка пауза
  currentstepcnt = 0; //счетчик циклов мешалки
}

void beer_finish() {
  if (valve_status) {
    open_valve(false);
  }
#ifdef USE_WATER_PUMP
  if (pump_started) set_pump_pwm(0);
#endif
  setHeaterPosition(false);
  PowerOn = false;
  heater_state = false;
  startval = 0;
  SendMsg(F("Программа затирания завершена"), NOTIFY_MSG);
  delay(200);
  set_power(false);
  reset_sensor_counter();
}

void check_alarm_beer() {

  if (startval <= 2000) return;

  float temp;
  switch (program[ProgramNum].TempSensor) {
    case 0:
      temp = TankSensor.avgTemp;
      break;
    case 1:
      temp = WaterSensor.avgTemp;
      break;
    case 2:
      temp = PipeSensor.avgTemp;
      break;
    case 3:
      temp = SteamSensor.avgTemp;
      break;
    case 4:
      temp = ACPSensor.avgTemp;
      break;
  }

  //Обрабатываем программу

  //Проверяем, что клапан воды охлаждения не открыт, когда не нужно
  if (program[ProgramNum].WType != "C" and program[ProgramNum].WType != "F" and valve_status && PowerOn) {
    //Закрываем клапан воды
    open_valve(false);
    SendMsg(F("Закрыт клапан воды охлаждения!"), NOTIFY_MSG);
  }

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
      set_heater_state(program[ProgramNum].Temp, temp);
    } else {
      beer_finish();
    }
  }

  //Если режим Засыпь солода или Пауза
  if (program[ProgramNum].WType == "M" || program[ProgramNum].WType == "P") {
    set_heater_state(program[ProgramNum].Temp, temp);
  }

  //Если режим Брага
  if (program[ProgramNum].WType == "F") {
    //Если температура меньше целевой - греем, иначе охлаждаем.
    if (temp <= program[ProgramNum].Temp - TankSensor.SetTemp) {
      if (valve_status) {
        //Закрываем клапан воды
        open_valve(false);
        SendMsg(F("Закрыт клапан воды охлаждения!"), NOTIFY_MSG);
      }
      //Поддерживаем целевую температуру
      set_heater_state(program[ProgramNum].Temp, temp);
    } else if (temp >= program[ProgramNum].Temp + TankSensor.SetTemp) {
      {
        if (!valve_status) {
          //Отключаем нагреватель
          setHeaterPosition(false);
          //Открываем клапан воды
          open_valve(true);
          SendMsg(F("Открыт клапан воды охлаждения!"), NOTIFY_MSG);
        }
      }
    } else {
      //Так как находимся в пределах температурной уставки, не нужно ни греть, ни охлаждать
      //Отключаем нагреватель
      setHeaterPosition(false);
      //Закрываем клапан воды, если температура в кубе чуть меньше температурной уставки, чтобы часто не щелкать клапаном
      if ((temp < program[ProgramNum].Temp + TankSensor.SetTemp - 0.1) && valve_status && PowerOn) {
        open_valve(false);
        SendMsg(F("Закрыт клапан воды охлаждения!"), NOTIFY_MSG);
      }
    }
  }

  if (program[ProgramNum].WType == "M" && temp >= program[ProgramNum].Temp - TankSensor.SetTemp) {
    //Достигли температуры засыпи солода. Пишем об этом. Продолжаем поддерживать температуру. Переход с этой строки программы на следующую возможен только в ручном режиме
    if (startval == 2001) {
      set_buzzer(true);
      SendMsg(F("Достигнута температура засыпи солода!"), NOTIFY_MSG);
    }
    startval = 2002;
  }

  if (program[ProgramNum].WType == "P" && temp >= program[ProgramNum].Temp - TankSensor.SetTemp) {
    if (begintime == 0) {
      //Засекаем время для отсчета, сколько держать паузу
      begintime = millis();
      SendMsg(F("Достигнута температурная пауза. Ждем завершения."), NOTIFY_MSG);
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
      SendMsg(F("Открыт клапан воды охлаждения!"), NOTIFY_MSG);
#ifdef USE_WATER_PUMP
      if (pump_started) set_pump_pwm(1023);
#endif
    }
    if (temp <= program[ProgramNum].Temp) {
      //Если температура упала
      //Закрываем клапан воды
      open_valve(false);
      SendMsg(F("Закрыт клапан воды охлаждения!"), NOTIFY_MSG);
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
      if (abs(temp - BOILING_TEMP) <= 0.5) {
        msgfl = true;
        begintime = millis();
        SendMsg(F("Начался режим кипячения"), NOTIFY_MSG);
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
      current_power_mode = POWER_WORK_MODE;
      digitalWrite(RELE_CHANNEL1, SamSetup.rele1);
#endif
      if (SamSetup.UseST) {
        digitalWrite(RELE_CHANNEL4, SamSetup.rele4);
      } else {
        digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);
      }
    }

    //Проверяем, что еще нужно держать паузу. За 30 секунд до окончания шлем сообщение
    if (begintime > 0 && msgfl && ((float(millis()) - begintime) / 1000 / 60 + 0.5 >= program[ProgramNum].Time)) {
      set_buzzer(true);
      msgfl = false;
      SendMsg(F("Засыпьте хмель!"), NOTIFY_MSG);
#ifdef __SAMOVAR_DEBUG
      Serial.println("Засыпьте хмель!");
#endif
      HopStepperStep();
    }

    //Проверяем, что еще нужно держать паузу
    if (begintime > 0 && ((millis() - begintime) / 1000 / 60 >= program[ProgramNum].Time)) {
      //Запускаем следующую программу
      run_beer_program(ProgramNum + 1);
    }
  }
  //Обрабатываем мешалку и насос
  check_mixer_state();

  vTaskDelay(10 / portTICK_PERIOD_MS);
}

void check_mixer_state() {
  if (program[ProgramNum].capacity_num > 0) {
    //обрабатываем время включения и управляем мешалкой и насосом

    if (alarm_c_min > 0 && alarm_c_min <= millis()) {
      //завершили паузу мешалки
      alarm_c_min = 0;
      alarm_c_low_min = 0;
      set_mixer_state(false, false);
    }

    if ((alarm_c_low_min > 0) && (alarm_c_low_min <= millis())) {
      //выключаем мешалку, если alarm_c_min > millis()
      alarm_c_low_min = 0;
      if (alarm_c_min > 0)
        set_mixer_state(false, false);
    }

    if (alarm_c_low_min == 0 && alarm_c_min == 0) {
      //включаем мешалку
      alarm_c_low_min = millis() + program[ProgramNum].Volume * 60 * 1000;
      if (program[ProgramNum].Power > 0) alarm_c_min = alarm_c_low_min + program[ProgramNum].Power * 60 * 1000;
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

void set_mixer_state(bool state, bool dir) {
  mixer_status = state;
  //Serial.println("State = " + String(state) + "; DIR = " + String(dir) + "; alarm_c_min = " + String(alarm_c_min) + "; alarm_c_low_min = " + String(alarm_c_low_min));
  if (state) {
    //включаем мешалку
    if (BitIsSet(program[ProgramNum].capacity_num, 0)) {
      //включаем реле 2
      digitalWrite(RELE_CHANNEL2, SamSetup.rele2);
#ifdef USE_WATER_PUMP
      //включаем SSD реле
      pump_pwm.write(1023);
#endif
      //включаем I2CStepper шаговик
      if (use_I2C_dev == 1) {
        int tm = abs(program[ProgramNum].Volume);
        if (tm == 0) tm = 600;
        bool b = set_stepper_by_time(20, dir, tm);
      }
    }
    if (BitIsSet(program[ProgramNum].capacity_num, 1)) {
      //включаем I2CStepper реле 1
      if (use_I2C_dev == 1 || use_I2C_dev == 2) {
        bool b = set_mixer_pump_target(1);
      }
    }
  } else {
    //выключаем реле 2
    digitalWrite(RELE_CHANNEL2, !SamSetup.rele2);
#ifdef USE_WATER_PUMP
    //выключаем SSD реле
    pump_pwm.write(0);
#endif
    //выключаем I2CStepper шаговик
    if (use_I2C_dev == 1) {
      bool b = set_stepper_by_time(0, 0, 0);
    }
    //выключаем I2CStepper реле 1
    if (use_I2C_dev == 1 || use_I2C_dev == 2) {
      bool b = set_mixer_pump_target(0);
    }
  }
}

void set_heater_state(float setpoint, float temp) {
#ifdef SAMOVAR_USE_POWER
  //Если дельта большая и не тюнинг, включаем разгонный тэн, иначе выключаем
  if (setpoint - temp > ACCELERATION_HEATER_DELTA && !tuning) {
    if (!acceleration_heater) {
      acceleration_heater = true;
      digitalWrite(RELE_CHANNEL4, SamSetup.rele4);
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
    delay(50);
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

    check_power_error();
#else
    current_power_mode = POWER_WORK_MODE;
    digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);
    digitalWrite(RELE_CHANNEL1, SamSetup.rele1);
    vTaskDelay(100 / portTICK_PERIOD_MS);
#endif
  } else {
#ifdef SAMOVAR_USE_POWER
    if (current_power_mode != POWER_SLEEP_MODE) {
      //delay(200); 5.13
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
  for (byte i = 0; i < k; i++) {
    if (program[i].WType == "") {
      i = CAPACITY_NUM * 2 + 1;
    } else {
      Str += program[i].WType + ";";
      Str += (String)program[i].Temp + ";";
      Str += (String)(int)program[i].Time + ";";
      Str += (String)program[i].capacity_num + "^" + program[i].Speed + "^" + program[i].Volume + "^" + program[i].Power + ";";
      Str += (String)program[i].TempSensor + "\n";
    }
  }
  return Str;
}

void set_beer_program(String WProgram) {
  //M - malt application temp, P - pause, B - boil, C - cool
  char c[500];
  WProgram.toCharArray(c, 500);
  char *pair = strtok(c, ";");
  //String MeshTemplate;
  int i = 0;
  while (pair != NULL and i < CAPACITY_NUM * 2) {
    program[i].WType = pair;
    pair = strtok(NULL, ";");
    program[i].Temp = atof(pair);
    pair = strtok(NULL, ";");
    program[i].Time = atof(pair);
    pair = strtok(NULL, ";");
    //разберем шаблон для насоса/мешалки по частям
    program[i].capacity_num = getValue(pair, '^', 0).toInt();  //Тип устройства - 1 - мешалка, 2 - насос, 3 - мешалка и насос одновременно
    program[i].Speed = getValue(pair, '^', 1).toInt();         //Направление вращения, если задано отрицательное значение - мешалка после паузы меняет направление вращения
    program[i].Volume = getValue(pair, '^', 2).toInt();        //Время включения в мин
    program[i].Power = getValue(pair, '^', 3).toInt();         //Время выключения в мин
    pair = strtok(NULL, "\n");
    program[i].TempSensor = atoi(pair);

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

void set_mixer(bool On) {
  set_mixer_state(On, false);
}

//Крутим шаговым двигателем на заданное количество шагов
void HopStepperStep() {
  stopService();
  stepper.brake();
  stepper.disable();
  stepper.setMaxSpeed(200); //скорость движения шагового двигателя
  //stepper.setSpeed(200);    //скорость движения шагового двигателя, должна быть равна предыдущей
  TargetStepps = 360 / 1.8 * 16 / 20;  //16 - множитель на драйвере двигателя. 20 - количество отверстий по целому кругу (если бы они занимали всю окружность)
  stepper.setCurrent(0);
  stepper.setTarget(TargetStepps);
  stepper.enable();
  startService();
}
