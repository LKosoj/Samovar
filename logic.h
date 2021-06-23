#include <Arduino.h>

#ifdef SAMOVAR_USE_BLYNK
//#define BLYNK_PRINT Serial

#include <BlynkSimpleEsp32.h>
#endif
//**************************************************************************************************************
// Логика работы ректификационной колонны
//**************************************************************************************************************
void menu_samovar_start();
void set_menu_screen(byte param);
void samovar_reset();
void create_data();
void pause_withdrawal(bool Pause);
void read_config();
String inline format_float(float v, int d);
float get_temp_by_pressure(float start_pressure, float start_temp, float current_pressure);
unsigned int hexToDec(String hexString);
void set_current_power(float Volt);
void set_power_mode(String Mode);
void open_valve(bool Val);
void stopService(void);
void startService(void);
void reset_sensor_counter(void);
void set_pump_speed(float pumpspeed, bool continue_process);
void set_pump_pwm(float duty);
void set_pump_speed_pid(float temp);
void set_power(bool On);

//Получить количество разделителей
byte getDelimCount(String data, char separator)
{
  int cnt = 0;
  int maxIndex = data.length() - 1;

  for (int i = 0; i <= maxIndex; i++) {
    if (data.charAt(i) == separator) {
      cnt++;
    }
  }
  return cnt;
}

//Получить подстроку через разделитель
String getValue(String data, char separator, int index)
{
  int found = 0;
  int strIndex[] = { 0, -1 };
  int maxIndex = data.length() - 1;

  for (int i = 0; i <= maxIndex && found <= index; i++) {
    if (data.charAt(i) == separator || i == maxIndex) {
      found++;
      strIndex[0] = strIndex[1] + 1;
      strIndex[1] = (i == maxIndex) ? i + 1 : i;
    }
  }
  return found > index ? data.substring(strIndex[0], strIndex[1]) : "";
}

//Получаем объем отбора
float IRAM_ATTR get_liguid_volume_by_step(int StepCount) {
  static float retval;
  if (SamSetup.StepperStepMl > 0) retval = (float)StepCount / SamSetup.StepperStepMl;
  else retval = 0;
  return retval;
}

//Получаем скорость отбора
float IRAM_ATTR get_liguid_rate_by_step(int StepperSpeed) {
  return round(get_liguid_volume_by_step(StepperSpeed) * 3.6 * 1000) / 1000.00;
}

float IRAM_ATTR get_speed_from_rate(float volume_per_hour) {
  static float v;
  ActualVolumePerHour = volume_per_hour;
  v = round(SamSetup.StepperStepMl * volume_per_hour * 1000 / 3.6) / 1000.00;
  if (v < 1) v = 1;
  return v;
}

int IRAM_ATTR get_liquid_volume() {
  return get_liguid_volume_by_step(stepper.getCurrent());
}

void IRAM_ATTR withdrawal(void) {
  //Определяем, что необходимо сменить режим работы
  if (program_Pause) {
    if (millis() >= t_min) {
      t_min = 0;
      menu_samovar_start();
    }
    return;
  }

  CurrrentStepps = stepper.getCurrent();

  if (TargetStepps == CurrrentStepps && TargetStepps != 0 && (startval == 1 || startval == 2)) {
    menu_samovar_start();
  }

  float c_temp; //стартовая температура отбора тела с учетом корректировки от давления или без
  c_temp = get_temp_by_pressure(SteamSensor.Start_Pressure, SteamSensor.BodyTemp, bme_pressure);

  //Возвращаем колонну в стабильное состояние, если работает программа отбора тела и температура пара вышла за пределы
  if (program[ProgramNum].WType == "B" && (SteamSensor.avgTemp >= c_temp + SteamSensor.SetTemp) && SteamSensor.BodyTemp > 0) {
    //ставим отбор на паузу, если еще не стоит, и задаем время ожидания
    if (!PauseOn && !program_Wait) {
      program_Wait_Type = "(пар)";
      //Если в настройках задан параметр - снижать скорость отбора - снижаем, и напряжение тоже
      if (SamSetup.useautospeed && setautospeed) {
        setautospeed = false;
        CurrrentStepperSpeed = stepper.getSpeed() - round(stepper.getSpeed() / 100 * SamSetup.autospeed);
        set_pump_speed(CurrrentStepperSpeed, false);
#ifdef SAMOVAR_USE_POWER
        set_current_power(target_power_volt - 5);
#endif
        vTaskDelay(50);
      }
      program_Wait = true;
      pause_withdrawal(true);
      t_min = millis() + SteamSensor.Delay * 1000;
    }
    // если время вышло, еще раз пытаемся дождаться
    if (millis() >= t_min) t_min = millis() + SteamSensor.Delay * 1000;
  } else if (program[ProgramNum].WType == "B" && SteamSensor.avgTemp < SteamSensor.BodyTemp + SteamSensor.SetTemp && millis() >= t_min && t_min > 0 && program_Wait) {
    //продолжаем отбор
    setautospeed = true;
    t_min = 0;
    program_Wait = false;
    pause_withdrawal(false);
  }

  c_temp = get_temp_by_pressure(SteamSensor.Start_Pressure, PipeSensor.BodyTemp, bme_pressure);
  //Возвращаем колонну в стабильное состояние, если работает программа отбора тела и температура в колонне вышла за пределы
  if (program[ProgramNum].WType == "B" && (PipeSensor.avgTemp >= c_temp + PipeSensor.SetTemp) && PipeSensor.BodyTemp > 0) {
    program_Wait_Type = "(царга)";
    //ставим отбор на паузу, если еще не стоит, и задаем время ожидания
    if (!PauseOn && !program_Wait) {
      //Если в настройках задан параметр - снижать скорость отбора - снижаем, и напряжение тоже
      if (SamSetup.useautospeed && setautospeed) {
        setautospeed = false;
        CurrrentStepperSpeed = stepper.getSpeed() - round(stepper.getSpeed() / 100 * SamSetup.autospeed);
        set_pump_speed(CurrrentStepperSpeed, false);
#ifdef SAMOVAR_USE_POWER
        set_current_power(target_power_volt - 5);
#endif
        vTaskDelay(50);
      }
      program_Wait = true;
      pause_withdrawal(true);
      t_min = millis() + PipeSensor.Delay * 1000;
    }
    // если время вышло, еще раз пытаемся дождаться
    if (millis() >= t_min) t_min = millis() + PipeSensor.Delay * 1000;
  } else if (program[ProgramNum].WType == "B" && PipeSensor.avgTemp < PipeSensor.BodyTemp + PipeSensor.SetTemp && millis() >= t_min && t_min > 0 && program_Wait) {
    //продолжаем отбор
    setautospeed = true;
    t_min = 0;
    program_Wait = false;
    pause_withdrawal(false);
  }
}

void pump_calibrate(int stpspeed) {
  if (startval != 0 && startval != 100) {
    return;
  }

  if (stpspeed == 0) {
    startval = 0;
    //Сохраняем полученное значение калибровки
    SamSetup.StepperStepMl = round((float)stepper.getCurrent() / 100);
    stopService();
    stepper.brake();
    stepper.disable();
    EEPROM.put(0, SamSetup);
    EEPROM.commit();
    read_config();
  } else {
    startval = 100;
    //крутим двигатель, пока не остановят
    if (!stepper.getState()) stepper.setCurrent(0);
    stepper.setMaxSpeed(stpspeed);
    stepper.setSpeed(stpspeed);
    stepper.setTarget(999999999);
    startService();
  }
}

void IRAM_ATTR pause_withdrawal(bool Pause) {
  if (!stepper.getState() && !PauseOn) return;
  PauseOn = Pause;
  if (Pause) {
    TargetStepps = stepper.getTarget();
    CurrrentStepps = stepper.getCurrent();
    CurrrentStepperSpeed = stepper.getSpeed();
    stopService();
    stepper.brake();
    stepper.disable();
  }
  else {
    stepper.setMaxSpeed(CurrrentStepperSpeed);
    stepper.setSpeed(CurrrentStepperSpeed);
    stepper.setCurrent(CurrrentStepps);
    stepper.setTarget(TargetStepps);
    startService();
  }
}

void IRAM_ATTR set_pump_speed(float pumpspeed, bool continue_process) {
  if (pumpspeed < 1) return;
  if (!(SamovarStatusInt == 10 || SamovarStatusInt == 15 || SamovarStatusInt == 40)) return;

  bool cp = continue_process;
  if (!stepper.getState()) cp = false;

  CurrrentStepperSpeed = pumpspeed;
  ActualVolumePerHour = get_liguid_rate_by_step(CurrrentStepperSpeed);

  stopService();
  stepper.setMaxSpeed(CurrrentStepperSpeed);
  stepper.setSpeed(CurrrentStepperSpeed);
  //Пересчитываем время отбора этой строки программы на текущую скорость
  if (ActualVolumePerHour == 0) program[ProgramNum].Time = 65535;
  else program[ProgramNum].Time = program[ProgramNum].Volume / ActualVolumePerHour / 1000;
  if (cp)
    startService();
}

String IRAM_ATTR get_Samovar_Status() {
  if (!PowerOn) {
    SamovarStatus = "Выключено";
    SamovarStatusInt = 0;
  } else if (PowerOn && startval == 1 && !PauseOn && !program_Wait) {
    SamovarStatus = "Прг №" + String(ProgramNum + 1);
    SamovarStatusInt = 10;
  } else if (PowerOn && startval == 1 && program_Wait) {
    int s = 0;
    if (t_min > (millis() + 10)) {
      s = (t_min - millis()) / 1000;
    }
    SamovarStatus = "Прг №" + String(ProgramNum + 1) + " пауза " + program_Wait_Type + ". Продолжение через " + (String)s + " сек.";
    SamovarStatusInt = 15;
  } else if (PowerOn && startval == 2) {
    SamovarStatus = "Выполнение программ закончено";
    SamovarStatusInt = 20;
  } else if (PowerOn && startval == 100) {
    SamovarStatus = "Калибровка";
    SamovarStatusInt = 30;
  } else if (PauseOn) {
    SamovarStatus = "Пауза";
    SamovarStatusInt = 40;
  } else if (PowerOn && startval == 0 && !stepper.getState()) {
    if (SamovarStatusInt != 51 && SamovarStatusInt != 52) {
      SamovarStatus = "Разгон колонны";
      SamovarStatusInt = 50;
    } else if (SamovarStatusInt == 51) {
      SamovarStatus = "Разгон завершен. Стабилизация/Работа на себя";
    } else if (SamovarStatusInt == 52) {
      SamovarStatus = "Стабилизация завершена/Работа на себя";
    }
  } else if (SamovarStatusInt == 1000) {
    SamovarStatus = "Режим дистилляции";
  } else if (SamovarStatusInt == 2000) {
#ifdef SAM_BEER_PRG
    SamovarStatus = "Прг №" + String(ProgramNum + 1) + "; ";
#else
    SamovarStatus = "";
#endif
    if (startval == 2001 && program[ProgramNum].WType == "M") {
      SamovarStatus = SamovarStatus + "Разогрев до температуры засыпи солода";
    } else if (startval == 2002 && program[ProgramNum].WType == "M") {
      SamovarStatus = SamovarStatus + "Ожидание засыпи солода";
    } else if (program[ProgramNum].WType == "P") {
      if (begintime == 0) {
        SamovarStatus = SamovarStatus + "Нагрев до " + String(program[ProgramNum].Temp);
      } else {
        SamovarStatus = SamovarStatus + "Пауза " + String(program[ProgramNum].Time - (millis() - begintime) / 1000 / 60) + " мин";
      }
    } else if (program[ProgramNum].WType == "C") {
      SamovarStatus = SamovarStatus + "Охлаждение до " + String(program[ProgramNum].Temp);
    } else if (program[ProgramNum].WType == "W") {
      SamovarStatus = SamovarStatus + "Ожидание. Нажмите \"Следующая программа\"";
    } else if (program[ProgramNum].WType == "A") {
      SamovarStatus = SamovarStatus + "Автокалибровка. После завершения питание будет выключено";
    } else if (program[ProgramNum].WType == "B") {
      if (begintime == 0) {
        SamovarStatus = SamovarStatus + "; Кипячение - нагрев";
      } else {
        SamovarStatus = SamovarStatus + "; Кипячение " + String(program[ProgramNum].Time - (millis() - begintime) / 1000 / 60) + " мин";
      }
    }
  }

  if (SamovarStatusInt == 10 || SamovarStatusInt == 15 || (SamovarStatusInt == 2000 && PowerOn)) {
    SamovarStatus += "; Осталось:" + WthdrwTimeS + "|" + WthdrwTimeAllS;
  }
  if (SteamSensor.BodyTemp > 0) SamovarStatus += ";Т тела пар:" + format_float(get_temp_by_pressure(SteamSensor.Start_Pressure, SteamSensor.BodyTemp, bme_pressure), 3) + ";Т тела царга:" + format_float(get_temp_by_pressure(SteamSensor.Start_Pressure, PipeSensor.BodyTemp, bme_pressure), 3);

  return SamovarStatus;
}

void IRAM_ATTR set_capacity(byte cap) {
  capacity_num = cap;

#ifdef SERVO_PIN
  int p = ((int)cap * SERVO_ANGLE) / (int)CAPACITY_NUM + servoDelta[cap];
  servo.write(p);
#elif USER_SERVO
  user_set_capacity(cap);
#endif

}

void IRAM_ATTR next_capacity(void) {
  set_capacity(capacity_num + 1);
}

void set_program(String WProgram) {
  //  WProgram.trim();
  //  if (WProgram = "") return;
  char c[500];
  WProgram.toCharArray(c, 500);
  char *pair = strtok(c, ";");
  int i = 0;
  while (pair != NULL and i < CAPACITY_NUM * 2) {
    program[i].WType = pair;
    pair = strtok(NULL, ";");
    program[i].Volume = atoi(pair);
    pair = strtok(NULL, ";");
    program[i].Speed = atof(pair);
    pair = strtok(NULL, ";");
    program[i].capacity_num = atoi(pair);
    pair = strtok(NULL, ";");
    program[i].Temp = atof(pair);
    pair = strtok(NULL, "\n");
    program[i].Power = atof(pair);
    if (program[i].WType == "P") {
      program[i].Time = program[i].Volume / 60 / (float)60;
    } else {
      program[i].Time = program[i].Volume / program[i].Speed / 1000;
    }
    i++;
    ProgramLen = i;
    pair = strtok(NULL, ";");
    if ((!pair || pair == NULL || pair[0] == 13) and i < CAPACITY_NUM * 2) {
      program[i].WType = "";
      break;
    }
  }
}

String get_program(int s) {
  String Str = "";
  int k = CAPACITY_NUM * 2;
  if (s == CAPACITY_NUM * 2) {
    s = 0;
  } else {
    k = s + 1;
  }
  for (int i = s; i < k; i++) {
    if (program[i].WType == "") {
      i = CAPACITY_NUM * 2 + 1;
    } else {
      Str += program[i].WType + ";";
      Str += (String)program[i].Volume + ";";
      Str += (String)program[i].Speed + ";";
      Str += (String)program[i].capacity_num + ";";
      Str += (String)program[i].Temp + ";";
      Str += (String)program[i].Power + "\n";
    }
  }
  return Str;
}

void IRAM_ATTR run_program(byte num) {
  t_min = 0;
  program_Pause = false;
  program_Wait = false;
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
    set_power(false);
    Msg = "Program finished!";
#ifdef SAMOVAR_USE_BLYNK
    //Если используется Blynk - пишем оператору
    Blynk.notify("Alert! {DEVICE_NAME} - Program finished!");
#endif

  } else {
#ifdef SAMOVAR_USE_POWER
    if (program[num].Power > 40) {
      set_current_power(program[num].Power);
    } else if (program[num].Power != 0) {
      set_current_power(target_power_volt + program[num].Power);
    }
#endif
    Msg = "Set prog line " + (String)(num + 1);
    if (program[num].WType == "H" || program[num].WType == "B" || program[num].WType == "T" || program[num].WType == "C") {
      Msg +=  ", capacity " + (String)program[num].capacity_num;
      //устанавливаем параметры для текущей программы отбора
      set_capacity(program[num].capacity_num);
      stepper.setMaxSpeed(get_speed_from_rate(program[num].Speed));
      stepper.setSpeed(get_speed_from_rate(program[num].Speed));
      TargetStepps = program[num].Volume * SamSetup.StepperStepMl;
      stepper.setCurrent(0);
      stepper.setTarget(TargetStepps);
      startService();
      ActualVolumePerHour = program[num].Speed;
      SteamSensor.BodyTemp = program[num].Temp;

      //Первая программа отбора тела - запоминаем текущие значения температуры и давления
      if ((program[num].WType == "B" || program[num].WType == "C") && SteamSensor.Start_Pressure == 0) {
        SteamSensor.Start_Pressure = bme_pressure;
        PipeSensor.BodyTemp = PipeSensor.avgTemp;
        WaterSensor.BodyTemp = WaterSensor.avgTemp;
        TankSensor.BodyTemp = TankSensor.avgTemp;
      }

      //Если у первой программы отбора тела не задана температура, при которой начинать отбор, считаем, что она равна текущей
      //Считаем, что колонна стабильна
      //Итак, текущая температура - это температура, которой Самовар будет придерживаться во время всех программ отобора тела.
      //Если она будет выходить за пределы, заданные в настройках, отбор будет ставиться на паузу, и продолжится после возвращения температуры в колонне к заданному значению.
      if ((program[num].WType == "B" || program[num].WType == "C") && SteamSensor.BodyTemp == 0) {
        SteamSensor.BodyTemp = SteamSensor.avgTemp;
      }
    } else if (program[num].WType == "P") {
      //Сбрасываем Т тела, так как при увеличнии напряжения на регуляторе увеличивается Т в царге.
      SteamSensor.BodyTemp = 0;
      PipeSensor.BodyTemp = 0;
      WaterSensor.BodyTemp = 0;
      TankSensor.BodyTemp = 0;

      //устанавливаем параметры ожидания для программы паузы. Время в секундах задано в program[num].Volume
      Msg += ", pause " + (String)program[num].Volume + " sec.";
      t_min = millis() + program[num].Volume * 1000;
      program_Pause = true;
      stopService();
      stepper.setMaxSpeed(-1);
      stepper.setSpeed(-1);
      stepper.brake();
      stepper.disable();
      stepper.setCurrent(0);
      stepper.setTarget(0);
    }
#ifdef SAMOVAR_USE_BLYNK
    //Если используется Blynk - пишем оператору
    Blynk.notify("{DEVICE_NAME} - " + Msg);
#endif

  }
  TargetStepps = stepper.getTarget();
}

//функция корректировки температуры кипения спирта в зависимости от давления
float IRAM_ATTR get_temp_by_pressure(float start_pressure, float start_temp, float current_pressure) {
  if (start_temp == 0) return 0;

  //скорректированная температура кипения спирта при текущем давлении
  static float c_temp;

  if (SamSetup.UsePreccureCorrect) {
    //идеальная температура кипения спирта при текущем давлении
    float i_temp;
    //температурная дельта
    float d_temp;

    i_temp = current_pressure * 0.038 + 49.27;
    d_temp = start_temp - start_pressure * 0.038 - 49.27; //учитываем поправку на погрешность измерения датчиков
    c_temp = i_temp + d_temp; // получаем текущую температуру кипения при переданном давлении с учетом поправки
  }
  else {
    //Используем сохраненную температуру отбора тела без корректировки
    c_temp = start_temp;
  }

  return c_temp;
}

void IRAM_ATTR set_body_temp() {
  if (program[ProgramNum].WType == "B" || program[ProgramNum].WType == "P") {
    SteamSensor.BodyTemp = SteamSensor.avgTemp;
    PipeSensor.BodyTemp = PipeSensor.avgTemp;
    WaterSensor.BodyTemp = WaterSensor.avgTemp;
    TankSensor.BodyTemp = TankSensor.avgTemp;
    Msg = "Body Steam T=" + String(SteamSensor.BodyTemp) + " Pipe=" + String(PipeSensor.BodyTemp);
#ifdef SAMOVAR_USE_BLYNK
    //Если используется Blynk - пишем оператору
    Blynk.notify("Warning! {DEVICE_NAME} " + Msg);
#endif
  } else {
    Msg = "Can't set body temp.";
#ifdef SAMOVAR_USE_BLYNK
    //Если используется Blynk - пишем оператору
    Blynk.notify("Warning! {DEVICE_NAME} " + Msg);
#endif
  }
}

void IRAM_ATTR check_alarm() {
  //сбросим паузу события безопасности
  if (alarm_t_min > 0 && alarm_t_min <= millis()) alarm_t_min = 0;

#ifdef USE_HEAD_LEVEL_SENSOR
  if (alarm_h_min > 0 && alarm_h_min <= millis()) {
    whls.resetStates();
    alarm_h_min = 0;
  }
#ifdef SAMOVAR_USE_POWER
  //Если программа - предзахлеб, и сброс напряжения был больше 8 минут назад, то возвращаем напряжение к последнему сохраненному - 0.5
  if (alarm_c_min > 0 && alarm_c_min <= millis()) {
    if (program[ProgramNum].WType == "C") {
      set_current_power(prev_target_power_volt - 0.5);
    } else {
      alarm_c_min = 0;
    }
  }
#endif
#endif

  if (!valve_status) {
    if (ACPSensor.avgTemp >= MAX_ACP_TEMP) open_valve(true);
    else if (TankSensor.avgTemp >= OPEN_VALVE_TANK_TEMP && PowerOn) {
      open_valve(true);
    }
  }

  if (!PowerOn && valve_status && WaterSensor.avgTemp <= TARGET_WATER_TEMP - 15 && ACPSensor.avgTemp <= MAX_ACP_TEMP - 10) {
    open_valve(false);
#ifdef USE_WATER_PUMP
    if (pump_started) set_pump_pwm(0);
#endif
  }

#ifdef USE_WATER_PUMP
  //Устанавливаем ШИМ для насоса в зависимости от температуры воды
  if (valve_status) {
    if (ACPSensor.avgTemp > 39 && ACPSensor.avgTemp > WaterSensor.avgTemp) set_pump_speed_pid(WaterSensor.avgTemp);
    else set_pump_speed_pid(WaterSensor.avgTemp);
  }
#endif

  //Проверяем, что температурные параметры не вышли за предельные значения
  if ((SteamSensor.avgTemp >= MAX_STEAM_TEMP || WaterSensor.avgTemp >= MAX_WATER_TEMP || TankSensor.avgTemp >= SamSetup.DistTemp || ACPSensor.avgTemp >= MAX_ACP_TEMP) && PowerOn) {
    //Если с температурой проблемы - выключаем нагрев, пусть оператор разбирается
    delay(1000);
    set_power(false);
    String s = "";
    if (SteamSensor.avgTemp >= MAX_STEAM_TEMP) s = s + " Steam";
    else if (WaterSensor.avgTemp >= MAX_WATER_TEMP) s = s + " Water";
    else if (ACPSensor.avgTemp >= MAX_ACP_TEMP) s = s + " ACP";

    if (TankSensor.avgTemp >= SamSetup.DistTemp) {
      //Если температура в кубе превысила заданную, штатно завершаем ректификацию.
      Msg = "Tank temp limit. Program finish.";
    } else  Msg = "Emergency power OFF! Temperature error" + s;

#ifdef SAMOVAR_USE_BLYNK
    //Если используется Blynk - пишем оператору
    Blynk.notify("Alarm! {DEVICE_NAME} " + Msg);
#endif
  }

#ifdef USE_WATERSENSOR
  //Проверим, что вода подается
  if (WFAlarmCount > WF_ALARM_COUNT && PowerOn) {
    //Если с водой проблемы - выключаем нагрев, пусть оператор разбирается
    sam_command_sync = SAMOVAR_POWER;
    Msg = "Emergency power OFF! Water error";
#ifdef SAMOVAR_USE_BLYNK
    //Если используется Blynk - пишем оператору
    Blynk.notify("Alarm! {DEVICE_NAME} " + Msg);
#endif
  }
#endif

  if ((WaterSensor.avgTemp >= ALARM_WATER_TEMP - 5) && PowerOn && alarm_t_min == 0) {
    //Если уже реагировали - надо подождать 30 секунд, так как процесс инерционный
    Msg = "Water temp is critical!";
#ifdef SAMOVAR_USE_BLYNK
    //Если используется Blynk - пишем оператору
    Blynk.notify("Warning! {DEVICE_NAME} water temp is critical!");
#endif

#ifdef SAMOVAR_USE_POWER
    if (WaterSensor.avgTemp >= ALARM_WATER_TEMP) {
      Msg = "Water temp is critical! Water error. Voltage down from " + (String)target_power_volt;
#ifdef SAMOVAR_USE_BLYNK
      //Если используется Blynk - пишем оператору
      Blynk.notify("Alarm! {DEVICE_NAME} " + Msg);
#endif
      //Попробуем снизить напряжение регулятора на 5 вольт, чтобы исключить перегрев колонны.
      set_current_power(target_power_volt - 5);
    }
#endif
    alarm_t_min = millis() + 1000 * 30;
  }

  //Если используется датчик уровня флегмы в голове
#ifdef USE_HEAD_LEVEL_SENSOR
  whls.tick();
  if (whls.isHolded() && alarm_h_min == 0) {
    whls.resetStates();
    if (program[ProgramNum].WType != "C") {
      Msg = "Head level alarm!";
    } else {
#ifdef SAMOVAR_USE_POWER
      //запускаем счетчик - 7 минут, нужен для возврата заданного напряжения
      alarm_c_min = millis() + 1000 * 60 * 7;
#endif
    }
#ifdef SAMOVAR_USE_POWER
    Msg = Msg + " Voltage down from " + (String)target_power_volt;
    set_current_power(target_power_volt - 2);
#endif
#ifdef SAMOVAR_USE_BLYNK
    //Если используется Blynk - пишем оператору
    Blynk.notify("Alarm! {DEVICE_NAME} " + Msg);
#endif
    //Если уже реагировали - надо подождать 40 секунд, так как процесс инерционный
    alarm_h_min = millis() + 1000 * 40;
  }
#endif

  if (SteamSensor.avgTemp >= CHANGE_POWER_MODE_STEAM_TEMP && SamovarStatusInt == 50) {
#ifdef USE_WATER_PUMP
    //Сбросим счетчик насоса охлаждения, что приведет к увеличению потока воды. Дальше уже будет штатно работать PID
    wp_count = 0;
#endif
    //достигли заданной температуры на разгоне, переходим на рабочий режим, устанавливаем заданную температуру, зовем оператора
    Msg = "Working mode set!";
    SamovarStatusInt = 51;
#ifdef SAMOVAR_USE_BLYNK
    //Если используется Blynk - пишем оператору
    Blynk.notify("Alert! {DEVICE_NAME} - " + Msg);
#endif
#ifdef SAMOVAR_USE_POWER
    set_current_power(program[0].Power);
#else
    current_power_mode = POWER_WORK_MODE;
    digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);
#endif
  }

  //Разгон и стабилизация завершены - шесть минут температура пара не меняется больше, чем на 0.1 градус:
  //https://alcodistillers.ru/forum/viewtopic.php?id=137 - указано 3 замера раз в три минуты.
  if ((SamovarStatusInt == 51 || SamovarStatusInt == 52) && SteamSensor.avgTemp > CHANGE_POWER_MODE_STEAM_TEMP) {
    float d = SteamSensor.avgTemp - SteamSensor.PrevTemp;
    d = abs(d);
    if (d < 0.1) {
      acceleration_temp += 1;
      if (acceleration_temp == 60 * 6) {
        SamovarStatusInt = 52;
        Msg = "Acceleration is complete.";
#ifdef SAMOVAR_USE_BLYNK
        //Если используется Blynk - пишем оператору
        Blynk.notify("{DEVICE_NAME} - " + Msg);
#endif
      }
    } else {
      acceleration_temp = 0;
      SteamSensor.PrevTemp = SteamSensor.avgTemp;
    }
  }
#ifdef USE_WATER_VALVE
  if (WaterSensor.avgTemp >= TARGET_WATER_TEMP + 1) {
    digitalWrite(WATER_PUMP_PIN, USE_WATER_VALVE);
  } else if (WaterSensor.avgTemp <= TARGET_WATER_TEMP - 1) {
    digitalWrite(WATER_PUMP_PIN, !USE_WATER_VALVE);
  }
#endif
}

void IRAM_ATTR open_valve(bool Val) {
  valve_status = Val;
  if (Val) {
    Msg = "Open cooling water!";
#ifdef SAMOVAR_USE_BLYNK
    //Если используется Blynk - пишем оператору
    Blynk.notify("Warning! {DEVICE_NAME} " + Msg);
#endif
    digitalWrite(RELE_CHANNEL3, SamSetup.rele3);
  } else {
    Msg = "Close cooling water!";
#ifdef SAMOVAR_USE_BLYNK
    //Если используется Blynk - пишем оператору
    Blynk.notify("Warning! {DEVICE_NAME} " + Msg);
#endif
    digitalWrite(RELE_CHANNEL3, !SamSetup.rele3);
  }
}

void IRAM_ATTR triggerBuzzerTask(void * parameter) {
  TickType_t beep = 200 / portTICK_RATE_MS;
  TickType_t silent = 800 / portTICK_RATE_MS;
  int i = 0;

  while (true) {
    digitalWrite(BZZ_PIN, HIGH);
    vTaskDelay(beep);
    digitalWrite(BZZ_PIN, LOW);
    vTaskDelay(silent);
    i++;
    if (i > 10) BuzzerTaskFl = false;
  }
}

void set_buzzer() {
  if (BuzzerTask == NULL) {
    BuzzerTaskFl = true;
    //Запускаем таск для пищалки
    xTaskCreatePinnedToCore(
      triggerBuzzerTask, /* Function to implement the task */
      "BuzzerTask", /* Name of the task */
      1000,  /* Stack size in words */
      NULL,  /* Task input parameter */
      0,  /* Priority of the task */
      &BuzzerTask,  /* Task handle. */
      1); /* Core where the task should run */
  }
}

void IRAM_ATTR set_power(bool On) {
  PowerOn = On;
  if (On) {
    digitalWrite(RELE_CHANNEL1, SamSetup.rele1);
    set_menu_screen(2);
    power_text_ptr = (char*)"OFF";

#ifdef SAMOVAR_USE_POWER
    vTaskDelay(600);
    set_power_mode(POWER_SPEED_MODE);
#else
    current_power_mode = POWER_SPEED_MODE;
    digitalWrite(RELE_CHANNEL4, SamSetup.rele4);
#endif
  } else {
#ifdef SAMOVAR_USE_POWER
    vTaskDelay(1000);
    set_power_mode(POWER_SLEEP_MODE);
#else
    current_power_mode = POWER_SLEEP_MODE;
    digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);
#endif
    power_text_ptr = (char*)"ON";
    sam_command_sync = SAMOVAR_RESET;
    digitalWrite(RELE_CHANNEL1, !SamSetup.rele1);
  }
}

//////////////////////////////////////////////////////////////////////////////////////////////////////////////
// SAMOVAR_USE_POWER
//////////////////////////////////////////////////////////////////////////////////////////////////////////////
#ifdef SAMOVAR_USE_POWER
#ifndef SAMOVAR_USE_RMVK
void IRAM_ATTR triggerPowerStatus(void * parameter)  {
  int i;
  String resp;
  while (true) {
    if (PowerOn) {
      if (Serial2.available()) {
        resp = Serial2.readStringUntil('\r');
        i = resp.indexOf("T");
        if (i < 0) {
          resp = Serial2.readStringUntil('\r');
        }
        vTaskDelay(200);
        resp = resp.substring(i, resp.length());
        if (resp.substring(1, 2) == "T") resp = resp.substring(1, 9);
        int cpv = hexToDec(resp.substring(1, 4));
        //Если напряжение больше 300 - не корректно получено значение от регулятора, оставляем старое значение
        if (cpv < 3000) {
          current_power_volt = cpv / 10.0F;
          target_power_volt = hexToDec(resp.substring(4, 7)) / 10.0F;
          current_power_mode = resp.substring(7, 8);
        }
      }
    }
    vTaskDelay(600);
  }
}
#else
void IRAM_ATTR triggerPowerStatus(void * parameter) {
  String resp;
  while (true) {
    if (PowerOn) {
      resp = "";
      Serial2.flush();
      Serial2.print("АТ+VO?\r");
      vTaskDelay(350);
      if (Serial2.available()) {
        resp = Serial2.readStringUntil('\r');
      }
      current_power_volt = resp.toInt();
      Serial2.flush();
      Serial2.print("АТ+VS?\r");
      vTaskDelay(350);
      resp = "";
      if (Serial2.available()) {
        resp = Serial2.readStringUntil('\r');
      }
      target_power_volt = resp.toInt();
    }
    vTaskDelay(100);
  }
}
#endif

//получаем текущие параметры работы регулятора напряжения
void IRAM_ATTR get_current_power() {
  if (!PowerOn) {
    current_power_volt = 0;
    target_power_volt = 0;
    current_power_mode = "N";
    return;
  }
  //Считаем мощность V*V*K/R, K = 0,98~1
  current_power_p = current_power_volt * current_power_volt / SamSetup.HeaterResistant;
}

//устанавливаем напряжение для регулятора напряжения
void IRAM_ATTR set_current_power(float Volt) {
  if (!PowerOn) return;
  vTaskDelay(100);
  prev_target_power_volt = target_power_volt;
  target_power_volt = Volt;
  if (Volt < 40) {
    set_power_mode(POWER_SLEEP_MODE);
    return;
  } else {
    set_power_mode(POWER_WORK_MODE);
    vTaskDelay(800);
  }
  vTaskSuspend(PowerStatusTask);
#ifdef SAMOVAR_USE_RMVK
  String Cmd;
  int V = Volt;
  if (V < 100) Cmd = "0";
  else Cmd = "";
  Cmd = Cmd + (String)V;
  Serial2.print("АТ+VS=" + Cmd + "\r");
#else
  String hexString = String((int)(Volt * 10), HEX);
  Serial2.print("S" + hexString + "\r");
#endif
  vTaskResume(PowerStatusTask);
}

void IRAM_ATTR set_power_mode(String Mode) {
  vTaskSuspend(PowerStatusTask);
  vTaskDelay(50);
  current_power_mode = Mode;
#ifdef SAMOVAR_USE_RMVK
  if (Mode == POWER_SLEEP_MODE) {
    Serial2.print("АТ+ON=0\r");
    //set_current_power(0);
  }
  else if (Mode == POWER_SPEED_MODE) {
    Serial2.print("АТ+ON=1\r");
    //set_current_power(5000);
  }
#else
  Serial2.print("M" + Mode + "\r");
#endif
  vTaskResume(PowerStatusTask);
}

unsigned int IRAM_ATTR hexToDec(String hexString) {
  unsigned int decValue = 0;
  int nextInt;

  for (int i = 0; i < hexString.length(); i++) {

    nextInt = int(hexString.charAt(i));
    if (nextInt >= 48 && nextInt <= 57) nextInt = map(nextInt, 48, 57, 0, 9);
    if (nextInt >= 65 && nextInt <= 70) nextInt = map(nextInt, 65, 70, 10, 15);
    if (nextInt >= 97 && nextInt <= 102) nextInt = map(nextInt, 97, 102, 10, 15);
    nextInt = constrain(nextInt, 0, 15);

    decValue = (decValue * 16) + nextInt;
  }

  return decValue;
}
#endif
