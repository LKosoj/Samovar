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

//Получаем объем отбора
float get_liguid_volume_by_step(int StepCount) {
  static float retval;
  if (SamSetup.StepperStepMl > 0) retval = (float)StepCount / SamSetup.StepperStepMl;
  else retval = 0;
  return retval;
}

//Получаем скорость отбора
float get_liguid_rate_by_step(int StepperSpeed) {
  return get_liguid_volume_by_step(StepperSpeed) * 3.6;
}

float get_speed_from_rate(float volume_per_hour) {
  static float v;
  ActualVolumePerHour = volume_per_hour;
  v = (float)SamSetup.StepperStepMl * (float)volume_per_hour / 3.6;
  if (v < 1) v = 1;
  return v;
}

int get_liquid_volume() {
  return get_liguid_volume_by_step(stepper.getCurrent());
}

void withdrawal(void) {
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

  static float c_temp; //стартовая температура отбора тела с учетом корректировки от давления или без
  c_temp = get_temp_by_pressure(SteamSensor.Start_Pressure, SteamSensor.BodyTemp, bme_pressure);

  //Возвращаем колонну в стабильное состояние, если работает программа отбора тела и температура пара вышла за пределы
  if (program[ProgramNum].WType == "B" && SteamSensor.avgTemp >= c_temp + SteamSensor.SetTemp) {
    //ставим отбор на паузу, если еще не стоит, и задаем время ожидания
    if (!PauseOn && !program_Wait) {
      program_Wait = true;
      pause_withdrawal(true);
      t_min = millis() + SteamSensor.Delay * 1000;
    }
    // если время вышло, еще раз пытаемся дождаться
    if (millis() >= t_min) t_min = millis() + SteamSensor.Delay * 1000;
  } else if (program[ProgramNum].WType == "B" && SteamSensor.avgTemp < SteamSensor.BodyTemp + SteamSensor.SetTemp && millis() >= t_min && t_min > 0) {
    //продолжаем отбор
    t_min = 0;
    program_Wait = false;
    pause_withdrawal(false);
  }

  //Возвращаем колонну в стабильное состояние, если работает программа отбора тела и температура в колонне вышла за пределы
  if (program[ProgramNum].WType == "B" && PipeSensor.avgTemp >= PipeSensor.BodyTemp + PipeSensor.SetTemp) {
    //ставим отбор на паузу, если еще не стоит, и задаем время ожидания
    if (!PauseOn && !program_Wait) {
      program_Wait = true;
      pause_withdrawal(true);
      t_min = millis() + PipeSensor.Delay * 1000;
    }
    // если время вышло, еще раз пытаемся дождаться
    if (millis() >= t_min) t_min = millis() + PipeSensor.Delay * 1000;
  } else if (program[ProgramNum].WType == "B" && PipeSensor.avgTemp < PipeSensor.BodyTemp + PipeSensor.SetTemp && millis() >= t_min && t_min > 0) {
    //продолжаем отбор
    t_min = 0;
    program_Wait = false;
    pause_withdrawal(false);
  }
}

void set_power(bool On) {
  PowerOn = On;
  if (On) {
    digitalWrite(RELE_CHANNEL1, LOW);
    set_menu_screen(2);
    power_text_ptr = (char*)"OFF";

#ifdef SAMOVAR_USE_POWER
    delay(1000);
    set_power_mode(POWER_SPEED_MODE);
#else
    digitalWrite(RELE_CHANNEL4, LOW);
#endif

  } else {
#ifdef SAMOVAR_USE_POWER
    set_power_mode(POWER_SLEEP_MODE);
#else
    digitalWrite(RELE_CHANNEL4, HIGH);
#endif
    samovar_reset();
    digitalWrite(RELE_CHANNEL1, HIGH);
    set_menu_screen(3);
    power_text_ptr = (char*)"ON";
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
    stepper.brake();
    stepper.disable();
    EEPROM.put(0, SamSetup);
    EEPROM.commit();
    read_config;
  } else {
    startval = 100;
    //крутим двигатель, пока не остановят
    if (!stepper.getState()) stepper.setCurrent(0);
    stepper.setMaxSpeed(stpspeed);
    stepper.setTarget(999999999);
  }
}

void pause_withdrawal(bool Pause) {
  if (!stepper.getState() && !PauseOn) return;
  PauseOn = Pause;
  if (Pause) {
    //RemainingDistance = stepper.getTarget() - stepper.getCurrent();
    TargetStepps = stepper.getTarget();
    CurrrentStepps = stepper.getCurrent();
    CurrrentStepperSpeed = stepper.getSpeed();
    stepper.brake();
    stepper.disable();
  }
  else {
    stepper.setMaxSpeed(CurrrentStepperSpeed);
    stepper.setCurrent(CurrrentStepps);
    stepper.setTarget(TargetStepps);
  }
}

String get_Samovar_Status() {
  if (!PowerOn) {
    SamovarStatus = "Выключено";
    SamovarStatusInt = 0;
  } else if (PowerOn && startval == 1 && !PauseOn && !program_Wait) {
    SamovarStatus = "Работает программа №" + String(ProgramNum + 1);
    SamovarStatusInt = 10;
  } else if (PowerOn && startval == 1 && program_Wait) {
    int s = 0;
    if (t_min > (millis() + 10)) {
      s = (t_min - millis()) / 1000;
    }
    SamovarStatus = "Программа №" + String(ProgramNum + 1) + " на паузе. Ожидается возврат колонны к заданным параметрам. Осталось " + (String)s + " сек.";
    SamovarStatusInt = 15;
  } else if (PowerOn && startval == 2) {
    SamovarStatus = "Выполнение программ отбора закончено";
    SamovarStatusInt = 20;
  } else if (PowerOn && startval == 100) {
    SamovarStatus = "Калибровка";
    SamovarStatusInt = 30;
  } else if (PauseOn) {
    SamovarStatus = "Пауза";
    SamovarStatusInt = 40;
  } else if (PowerOn && startval == 0 && !stepper.getState()) {
    SamovarStatus = "Разгон колонны/работа на себя";
    SamovarStatusInt = 50;
  }

  if (SamovarStatusInt == 10 || SamovarStatusInt == 15) {
    SamovarStatus += " До конца текущей строки программы: " + WthdrwTimeS;
    SamovarStatus += " До конца текущей программы: " + WthdrwTimeAllS;
  }
  if (SteamSensor.BodyTemp > 0) SamovarStatus += " Температура отбора тела:" + format_float(get_temp_by_pressure(SteamSensor.Start_Pressure, SteamSensor.BodyTemp, bme_pressure), 3);

  return SamovarStatus;
}

void set_capacity(byte cap) {
  capacity_num = cap;
  int p = ((int)cap * SERVO_ANGLE) / (int)CAPACITY_NUM + servoDelta[cap];
  servo.write(p);
}

void next_capacity(void) {
  set_capacity(capacity_num + 1);
}

void set_program(String WProgram) {
  static char c[500];
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
    program[i].Time = program[i].Volume / program[i].Speed / 1000;
    i++;
    ProgramLen = i;
    pair = strtok(NULL, ";");
    if (!pair and i < CAPACITY_NUM) {
      program[i].WType = "";
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

void run_program(byte num) {
  t_min = 0;
  program_Pause = false;
  if (num == CAPACITY_NUM * 2) {
    //если num = CAPACITY_NUM * 2 значит мы достигли финала (или отбор сброшен принудительно), завершаем отбор
    ProgramNum = 0;
    if (fileToAppend) {
      fileToAppend.close();
    }
    stepper.brake();
    stepper.disable();
    stepper.setCurrent(0);
    stepper.setTarget(0);
    set_capacity(0);
#ifdef SAMOVAR_USE_BLYNK
    //Если используется Blynk - пишем оператору
    Blynk.notify("Alert! {DEVICE_NAME} - Program finished!");
#endif
    
  } else {
    if (program[num].WType == "H" || program[num].WType == "B" || program[num].WType == "T") {
      //устанавливаем параметры для текущей программы отбора
#ifdef SAMOVAR_USE_BLYNK
      //Если используется Blynk - пишем оператору
      Blynk.notify("{DEVICE_NAME} - Set prog line " + (String)(num + 1) + ", capacity " + (String)program[num].capacity_num);
#endif
      set_capacity(program[num].capacity_num);
      stepper.setMaxSpeed(get_speed_from_rate(program[num].Speed));
      TargetStepps = program[num].Volume * SamSetup.StepperStepMl;
      stepper.setCurrent(0);
      stepper.setTarget(TargetStepps);
      ActualVolumePerHour = program[num].Speed;
      SteamSensor.BodyTemp = program[num].Temp;

#ifdef SAMOVAR_USE_POWER
      set_power_mode(POWER_WORK_MODE);
      if (program[num].Power > 40) {
        set_current_power(program[num].Power);
      }
#endif

      //Первая программа отбора тела - запоминаем текущие значения температуры и давления
      if (program[num].WType == "B" && SteamSensor.Start_Pressure == 0) {
        SteamSensor.Start_Pressure = bme_pressure;
        PipeSensor.BodyTemp = PipeSensor.avgTemp;
        WaterSensor.BodyTemp = WaterSensor.avgTemp;
        TankSensor.BodyTemp = TankSensor.avgTemp;
      }

      //Если у первой программы отбора тела не задана температура, при которой начинать отбор, считаем, что она равна текущей
      //Считаем, что колонна стабильна
      //Итак, текущая температура - это температура, которой Самовар будет придерживаться во время всех программ отобора тела.
      //Если она будет выходить за пределы, заданные в настройках, отбор будет ставиться на паузу, и продолжится после возвращения температуры в колонне к заданному значению.
      if (program[num].WType == "B" && SteamSensor.BodyTemp == 0) {
        SteamSensor.BodyTemp = SteamSensor.avgTemp;
      }
    } else if (program[num].WType == "P") {
      //устанавливаем параметры ожидания для программы паузы. Время в секундах задано в program[num].Volume
      t_min = millis() + program[num].Volume * 1000;
      program_Pause = true;
      stepper.setSpeed(-1);
      stepper.setMaxSpeed(-1);
      stepper.brake();
      stepper.disable();
      stepper.setCurrent(0);
      stepper.setTarget(0);
    }
  }
  TargetStepps = stepper.getTarget();
}

//функция корректировки температуры кипения спирта в зависимости от давления
float get_temp_by_pressure(float start_pressure, float start_temp, float current_pressure) {
  //скорректированная температура кипения спирта при текущем давлении
  static float c_temp;

#ifdef USE_PRESSURE_CORRECT
  //идеальная температура кипения спирта при текущем давлении
  static float i_temp;
  //температурная дельта
  static float d_temp;

  i_temp = current_pressure * 0.038 + 49.27;
  d_temp = start_temp - start_pressure * 0.038 - 49.27; //учитываем поправку на погрешность измерения датчиков
  c_temp = i_temp + d_temp; // получаем текущую температуру кипения при переданном давлении с учетом поправки
#else
  //Используем сохраненную температуру отбора тела без корректировки
  c_temp = start_temp;
#endif

  return c_temp;
}

void check_alarm() {
  //сбросим паузу события безопасности
  if (alarm_t_min >= millis()) alarm_t_min = 0;
  if (alarm_h_min >= millis()) alarm_h_min = 0;

  if (!valve_status && TankSensor.avgTemp >= OPEN_VALVE_TANK_TEMP) {
    open_valve(true);
  }

  //Проверяем, что температурные параметры не вышли за предельные значения
  if ((SteamSensor.avgTemp >= MAX_STEAM_TEMP || WaterSensor.avgTemp >= MAX_WATER_TEMP) && PowerOn) {
    //Если с температурой проблемы - выключаем нагрев, пусть оператор разбирается
    set_power(false);
#ifdef SAMOVAR_USE_BLYNK
    //Если используется Blynk - пишем оператору
    Blynk.notify("Alarm! {DEVICE_NAME} emergency power OFF! Temperature error");
#endif
  }

#ifdef USE_WATERSENSOR
  //Проверим, что вода подается
  if (WFAlarmCount > WF_ALARM_COUNT) {
    //Если с водой проблемы - выключаем нагрев, пусть оператор разбирается
    set_power(false);
#ifdef SAMOVAR_USE_BLYNK
    //Если используется Blynk - пишем оператору
    Blynk.notify("Alarm! {DEVICE_NAME} emergency power OFF! Water error");
#endif
  }
#endif

  if ((WaterSensor.avgTemp >= ALARM_WATER_TEMP - 5) && PowerOn && alarm_t_min == 0) {
    //Если уже реагировали - надо подождать 20 секунд, так как процесс инерционный
#ifdef SAMOVAR_USE_BLYNK
    //Если используется Blynk - пишем оператору
    Blynk.notify("Warning! {DEVICE_NAME} water temp is critical!");
#endif

#ifdef SAMOVAR_USE_POWER
    if (WaterSensor.avgTemp >= ALARM_WATER_TEMP) {
#ifdef SAMOVAR_USE_BLYNK
      //Если используется Blynk - пишем оператору
      Blynk.notify("Alarm! {DEVICE_NAME} water temp is critical! Water error. Voltage down from " + (String)target_power_volt);
#endif
      //Попробуем снизить напряжение регулятора на 5 вольт, чтобы исключить перегрев колонны.
      set_current_power(target_power_volt - 5);
    }
#endif
    alarm_t_min = millis() + 20000;
  }

  //Если используется датчик уровня флегмы в голове
#ifdef USE_HEAD_LEVEL_SENSOR
  if (whls.isHolded() && alarm_h_min == 0) {
#ifdef SAMOVAR_USE_BLYNK
    //Если используется Blynk - пишем оператору
    Blynk.notify("Alarm! {DEVICE_NAME} - Head level alarm!");
#endif
#ifdef SAMOVAR_USE_POWER
    set_current_power(target_power_volt - 3);
#endif
    //Если уже реагировали - надо подождать 10 секунд, так как процесс инерционный
    alarm_h_min = millis() + 10000;
  }
#endif

  if (SteamSensor.avgTemp >= CHANGE_POWER_MODE_STEAM_TEMP && current_power_mode == POWER_SPEED_MODE) {
    //достигли заданной температуры на разгоне, переходим на рабочий режим, устанавливаем заданную температуру, зовем оператора
#ifdef SAMOVAR_USE_BLYNK
    //Если используется Blynk - пишем оператору
    Blynk.notify("Alert! {DEVICE_NAME} - working mode set!");
#endif
#ifdef SAMOVAR_USE_POWER
    set_power_mode(POWER_WORK_MODE);
    //Устанавливаем напряжение, заданное в первой строке программы
    set_current_power(program[0].Power);
#else
    digitalWrite(RELE_CHANNEL4, HIGH);
#endif
  }

#ifdef SAMOVAR_USE_BLYNK
  //Если используется Blynk - пишем оператору
  //что разгон и стабилизация завершены - шесть минут температура пара не меняется больше, чем на 0.1 градус:
  //https://alcodistillers.ru/forum/viewtopic.php?id=137 - тут указано 3 замера раз в три минуты.
  if (SamovarStatusInt == 50 && SteamSensor.avgTemp > 70) {
    float d = SteamSensor.avgTemp - SteamSensor.PrevTemp;
    d = abs(d);
    if (d < 0.1) {
      acceleration_temp += 1;
      if (acceleration_temp == 60 * 6) {
        Blynk.notify("{DEVICE_NAME} - Acceleration is complete.");
      }
    } else {
      acceleration_temp = 0;
      SteamSensor.PrevTemp = SteamSensor.avgTemp;
    }
  }
#endif

}

void open_valve(bool Val) {
  valve_status = Val;
  if (Val) {
#ifdef SAMOVAR_USE_BLYNK
    //Если используется Blynk - пишем оператору
    Blynk.notify("Warning! {DEVICE_NAME} - Open cooling water!");
#endif
    digitalWrite(RELE_CHANNEL3, LOW);
  } else {
#ifdef SAMOVAR_USE_BLYNK
    //Если используется Blynk - пишем оператору
    Blynk.notify("Warning! {DEVICE_NAME} - Close cooling water!");
#endif
    digitalWrite(RELE_CHANNEL3, HIGH);
  }
}

//////////////////////////////////////////////////////////////////////////////////////////////////////////////
// SAMOVAR_USE_POWER
//////////////////////////////////////////////////////////////////////////////////////////////////////////////
#ifdef SAMOVAR_USE_POWER
String read_from_serial() {
  String serial_str = "";
  boolean getData;
  getData = false;
  char a;
  while (Serial2.available()) {
    a = Serial2.read();
    //Serial.println(a);
    serial_str += a;
    if (a == '\n') {
      getData = true;
      break;
    }
  }

  int i;
  i = serial_str.indexOf("T");
  if (getData && i >= 0) {
    serial_str = serial_str.substring(i, serial_str.length() - 2);
    String result = serial_str;
    serial_str = "";
    return result;
  } else if (getData && Serial2.available()) {
    return read_from_serial();
  } else if (getData) {
    serial_str = "";
    return "";
  }
  return "";
}

//получаем текущие параметры работы регулятора напряжения
void get_current_power() {
  if (!PowerOn) {
    current_power_volt = 0;
    target_power_volt = 0;
    current_power_mode = "N";
    return;
  }
  String s = read_from_serial();
  if (s != "") {
    static int cpv = hexToDec(s.substring(1, 4));
    //Если напряжение больше 300 - не корректно получено значение от регулятора, оставляем старое значение
    if (cpv < 3000) {
      current_power_volt = cpv / 10.0F;
      target_power_volt = hexToDec(s.substring(4, 7)) / 10.0F;
      current_power_mode = s.substring(7, 8);
      //Считаем мощность V*V*K/R, K = 0,98~1
      current_power_p = current_power_volt * current_power_volt / HEATER_RESISTANT;
    }
  }
}

//устанавливаем напряжение для регулятора напряжения
void set_current_power(float Volt) {
  String hexString = String((int)(Volt * 10), HEX);
  Serial2.print("S" + hexString + "\r");
}

void set_power_mode(String Mode) {
  current_power_mode = Mode;
  Serial2.print("M" + Mode + "\r");
}

unsigned int hexToDec(String hexString) {
  unsigned int decValue = 0;
  static int nextInt;

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
