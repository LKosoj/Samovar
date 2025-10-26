#include <Arduino.h>
#include "Samovar.h"

#ifdef SAMOVAR_USE_BLYNK
//#define BLYNK_PRINT Serial

#include <BlynkSimpleEsp32.h>
#endif
//**************************************************************************************************************
// Логика работы ректификационной колонны
//**************************************************************************************************************
void save_profile();
void menu_samovar_start();
void set_menu_screen(uint8_t param);
void samovar_reset();
void create_data();
void pause_withdrawal(bool Pause);
void read_config();
inline String format_float(float v, int d);
float get_temp_by_pressure(float start_pressure, float start_temp, float current_pressure);
unsigned int hexToDec(String hexString);
void set_current_power(float Volt);
void set_power_mode(String Mode);
void open_valve(bool Val, bool msg);
void stopService(void);
void startService(void);
void reset_sensor_counter(void);
void set_pump_speed(float pumpspeed, bool continue_process);
void set_pump_pwm(float duty);
void set_pump_speed_pid(float temp);
void set_power(bool On);
void set_body_temp();
void set_buzzer(bool fl);
void start_self_test(void);
void stop_self_test(void);
bool check_boiling();
float get_alcohol(float t);
void set_boiling();
bool set_stepper_target(uint16_t spd, uint8_t direction, uint32_t target);

#ifdef SAMOVAR_USE_POWER
// Проверка ошибок питания
void check_power_error();
#endif
#ifdef COLUMN_WETTING
bool column_wetting();
#endif

void SendMsg(const String &m, MESSAGE_TYPE msg_type);

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
String getValue(String data, char separator, int index) {
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

// Получить объем жидкости
int get_liquid_volume() {
  return get_liquid_volume_by_step(stepper.getCurrent());
}

// Установить сигнализацию
void set_alarm() {
  // выключаем питание, выключаем воду, взводим флаг аварии
  if (PowerOn) {
    sam_command_sync = SAMOVAR_POWER;
  }
  set_power(false);
  alarm_event = true;
  open_valve(false, true);
  stopService();
  set_stepper_target(0, 0, 0);
#ifdef USE_WATER_PUMP
  set_pump_pwm(0);
#endif
  SendMsg(("Аварийное отключение!"), ALARM_MSG);
}

// Функция для управления отбором
void withdrawal(void) {
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

  if (TargetStepps == CurrrentStepps && TargetStepps != 0 && (startval == 1 || startval == 2)) {
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
    if (program[ProgramNum].WType == "C" && (ProgramNum < ProgramLen - 3) && (program[ProgramNum + 1].WType == "B" || program[ProgramNum + 1].WType == "C" || program[ProgramNum + 1].WType == "P") && (program[ProgramNum + 2].WType == "B" || program[ProgramNum + 2].WType == "C")) {
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
        //Если в настройках задан параметр - снижать скорость отбора - снижаем, и напряжение тоже
        if (SamSetup.useautospeed && setautospeed) {
          setautospeed = false;
          CurrrentStepperSpeed = stepper.getSpeed() - round(stepper.getSpeed() / 100 * SamSetup.autospeed);
          set_pump_speed(CurrrentStepperSpeed, false);
#ifdef SAMOVAR_USE_POWER
          if (program[ProgramNum].WType == "B" && SamSetup.useautopowerdown) {
#ifdef SAMOVAR_USE_SEM_AVR
            set_current_power(target_power_volt - target_power_volt / 100 * 3);
#else
            set_current_power(target_power_volt - 3 * PWR_FACTOR);
#endif
          }
#endif
          vTaskDelay(10 / portTICK_PERIOD_MS);
        }
        program_Wait = true;
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
    setautospeed = true;
    t_min = 0;
    program_Wait = false;
    pause_withdrawal(false);
  }

  c_temp = get_temp_by_pressure(SteamSensor.Start_Pressure, PipeSensor.BodyTemp, bme_pressure);
  //Возвращаем колонну в стабильное состояние, если работает программа отбора тела и температура в колонне вышла за пределы или корректируем пределы
  if ((program[ProgramNum].WType == "B" || program[ProgramNum].WType == "C") && (PipeSensor.avgTemp >= c_temp + PipeSensor.SetTemp) && PipeSensor.BodyTemp > 0) {
#ifdef USE_BODY_TEMP_AUTOSET
    if (program[ProgramNum].WType == "C" && (ProgramNum < ProgramLen - 3) && (program[ProgramNum + 1].WType == "B" || program[ProgramNum + 1].WType == "C" || program[ProgramNum + 1].WType == "P") && (program[ProgramNum + 2].WType == "B" || program[ProgramNum + 2].WType == "C")) {
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
        //Если в настройках задан параметр - снижать скорость отбора - снижаем, и напряжение тоже
        if (SamSetup.useautospeed && setautospeed) {
          setautospeed = false;
          CurrrentStepperSpeed = stepper.getSpeed() - round(stepper.getSpeed() / 100 * SamSetup.autospeed);
          set_pump_speed(CurrrentStepperSpeed, false);
#ifdef SAMOVAR_USE_POWER
          if (program[ProgramNum].WType == "B" && SamSetup.useautopowerdown) {
#ifdef SAMOVAR_USE_SEM_AVR
            set_current_power(target_power_volt - target_power_volt / 100 * 3);
#else
            set_current_power(target_power_volt - 3 * PWR_FACTOR);
#endif
          }
#endif
          vTaskDelay(10 / portTICK_PERIOD_MS);
        }
        program_Wait = true;
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
    setautospeed = true;
    t_min = 0;
    program_Wait = false;
    pause_withdrawal(false);
  }
  vTaskDelay(10 / portTICK_PERIOD_MS);
}

// Калибровка насоса
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
    save_profile();
    read_config();
  } else {
    startval = 100;
    //крутим двигатель, пока не остановят
    if (!stepper.getState()) stepper.setCurrent(0);
    stepper.setMaxSpeed(stpspeed);
    //stepper.setSpeed(stpspeed);
    stepper.setTarget(999999999);
    startService();
  }
}

// Пауза отбора
void pause_withdrawal(bool Pause) {
  if (Samovar_Mode != SAMOVAR_RECTIFICATION_MODE) return;
  if (!stepper.getState() && !PauseOn) return;
  PauseOn = Pause;
  if (Pause) {
    TargetStepps = stepper.getTarget();
    CurrrentStepps = stepper.getCurrent();
    CurrrentStepperSpeed = stepper.getSpeed();
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

// Установить скорость насоса
void set_pump_speed(float pumpspeed, bool continue_process) {
  if (pumpspeed < 1) return;
  if (!(SamovarStatusInt == 10 || SamovarStatusInt == 15 || SamovarStatusInt == 40)) return;

  bool cp = continue_process;
  if (!stepper.getState()) cp = false;

  CurrrentStepperSpeed = pumpspeed;
  ActualVolumePerHour = get_liquid_rate_by_step(CurrrentStepperSpeed);

  stopService();
  stepper.setMaxSpeed(CurrrentStepperSpeed);
  stepper.setTarget(stepper.getTarget());
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
  if (SamovarStatusInt != 2000) return 0.0;
  
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

// Получить статус Самовара
String get_Samovar_Status() {
  if (!PowerOn) {
    SamovarStatus = F("Выключено");
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
    SamovarStatus = F("Выполнение программы завершено");
    SamovarStatusInt = 20;
  } else if (PowerOn && startval == 100) {
    SamovarStatus = F("Калибровка");
    SamovarStatusInt = 30;
  } else if (PauseOn) {
    SamovarStatus = F("Пауза");
    SamovarStatusInt = 40;
  } else if (PowerOn && startval == 0 && !stepper.getState()) {
    if (SamovarStatusInt != 51 && SamovarStatusInt != 52) {
      SamovarStatus = F("Разгон колонны");
      SamovarStatusInt = 50;
    } else if (SamovarStatusInt == 51) {
      SamovarStatus = F("Разгон завершен. Стабилизация/Работа на себя");
    } else if (SamovarStatusInt == 52) {
      SamovarStatus = F("Стабилизация завершена/Работа на себя");
    }
  } else if (SamovarStatusInt == 1000) {
    SamovarStatus = F("Режим дистилляции");
  } else if (SamovarStatusInt == 3000) {
    SamovarStatus = F("Режим бражной колонны");
  } else if (SamovarStatusInt == 4000) {
    if (startval == 4001) {
      SamovarStatus = "Прг №" + String(ProgramNum + 1) + "; ";
      if (program[ProgramNum].WType == "H") {
        SamovarStatus = SamovarStatus + "Прогрев";
      } else if (program[ProgramNum].WType == "S") {
        SamovarStatus = SamovarStatus + "Настройка";
      } else if (program[ProgramNum].WType == "O") {
        SamovarStatus = SamovarStatus + "Оптимизация";
      } else if (program[ProgramNum].WType == "W") {
        SamovarStatus = SamovarStatus + "Работа";
      }
    }
  } else if (SamovarStatusInt == 2000) {
#ifdef SAM_BEER_PRG
    SamovarStatus = "Прг №" + String(ProgramNum + 1) + "; ";
#else
    SamovarStatus = "";
#endif
    if (startval == 2001 && program[ProgramNum].WType == "M") {
      float currentTemp = getBeerCurrentTemp();
      SamovarStatus = SamovarStatus + "Разогрев до температуры засыпи солода";
      if (currentTemp < program[ProgramNum].Temp - 0.5) {
        SamovarStatus += "; Текущая Т: " + String(currentTemp) + "°";
      }
    } else if (startval == 2002 && program[ProgramNum].WType == "M") {
      SamovarStatus = SamovarStatus + "Ожидание засыпи солода";
    } else if (program[ProgramNum].WType == "P") {
      if (begintime == 0) {
        float currentTemp = getBeerCurrentTemp();
        SamovarStatus = SamovarStatus + "Пауза " + String(program[ProgramNum].Temp) + "°; Разогрев";
        if (currentTemp < program[ProgramNum].Temp - 0.5) {
          SamovarStatus += "; Текущая Т: " + String(currentTemp) + "°";
        }
      } else {
        SamovarStatus = SamovarStatus + "Пауза " + String(program[ProgramNum].Temp) + "°";
      }
    } else if (program[ProgramNum].WType == "C") {
      float currentTemp = getBeerCurrentTemp();
      SamovarStatus = SamovarStatus + "Охлаждение до " + String(program[ProgramNum].Temp);
      if (currentTemp > program[ProgramNum].Temp + 0.5) {
        SamovarStatus += "; Текущая Т: " + String(currentTemp) + "°";
      }
    } else if (program[ProgramNum].WType == "W") {
      SamovarStatus = SamovarStatus + "Ожидание. Нажмите 'Следующая программа'; ";
    } else if (program[ProgramNum].WType == "A") {
      SamovarStatus = SamovarStatus + "Автокалибровка. После завершения питание будет выключено";
    } else if (program[ProgramNum].WType == "B") {
      if (begintime == 0) {
        SamovarStatus = SamovarStatus + "Кипячение - нагрев";
      } else {
        SamovarStatus = SamovarStatus + "Кипячение " + String(program[ProgramNum].Time) + " мин";
      }
    } else if (program[ProgramNum].WType == "F") {
      float currentTemp = getBeerCurrentTemp();
      SamovarStatus = SamovarStatus + "Ферментация; Поддержание температуры " + String(program[ProgramNum].Temp) + "°";
      SamovarStatus += "; Текущая Т: " + String(currentTemp) + "°";
    } else if (!PowerOn) {
      SamovarStatus = "Выключено";
    }

    if (PowerOn && (program[ProgramNum].WType == "P" || program[ProgramNum].WType == "B") && begintime > 0) {
      float progress = ((float)(millis() - begintime) / (program[ProgramNum].Time * 60 * 1000)) * 100;
      if (progress > 100) progress = 100;
      SamovarStatus += "; Прогресс: " + String(progress, 1) + "%";
    }
  }

  if (SamovarStatusInt == 10 || SamovarStatusInt == 15 || (SamovarStatusInt == 2000 && PowerOn)) {
    SamovarStatus += "; Осталось:" + WthdrwTimeS + "|" + WthdrwTimeAllS;
  }
  if (SteamSensor.BodyTemp > 0) {
    SamovarStatus += ";Т тела пар:" + format_float(get_temp_by_pressure(SteamSensor.Start_Pressure, SteamSensor.BodyTemp, bme_pressure), 3) + ";Т тела царга:" + format_float(get_temp_by_pressure(SteamSensor.Start_Pressure, PipeSensor.BodyTemp, bme_pressure), 3);
  }

  return SamovarStatus;
}

// Установить емкость
void set_capacity(uint8_t cap) {
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
void set_program(String WProgram) {
  //  WProgram.trim();
  //  if (WProgram.length() == 0) return;
  char c[500] = {0};
  WProgram.toCharArray(c, 500);
  char *pair = strtok(c, ";");
  int i = 0;
  while (pair != NULL && i < CAPACITY_NUM * 2) {
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
    if ((!pair || pair == NULL || pair[0] == 13) && i < CAPACITY_NUM * 2) {
      program[i].WType = "";
      break;
    }
  }
}

// Получить программу
String get_program(uint8_t s) {
  String Str = "";
  uint8_t k = CAPACITY_NUM * 2;
  if (s == CAPACITY_NUM * 2) {
    s = 0;
  } else {
    k = s + 1;
  }
  for (uint8_t i = s; i < k; i++) {
    if (program[i].WType.length() == 0) {
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

// Запустить программу
void run_program(uint8_t num) {
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
    set_power(false);
    SendMsg(("Выполнение программы завершено."), NOTIFY_MSG);
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
      stepper.setMaxSpeed(get_speed_from_rate(program[num].Speed));
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

void check_alarm() {
  static bool close_valve_message_sent = false;
  //сбросим паузу события безопасности
  if (alarm_t_min > 0 && alarm_t_min <= millis()) alarm_t_min = 0;

#ifdef SAMOVAR_USE_POWER
  //управляем разгонным тэном
  if (SamovarStatusInt == 50 && TankSensor.avgTemp <= OPEN_VALVE_TANK_TEMP && PowerOn) {
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
      set_current_power(target_power_volt - target_power_volt / 100 * 2);
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
  if (valve_status && close_valve_message_sent)  {
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

  if (SamovarStatusInt == 50 && SteamSensor.avgTemp >= CHANGE_POWER_MODE_STEAM_TEMP) {
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
        SamovarStatusInt = 51;

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

  if (SamovarStatusInt == 51 && !boil_started) {
    set_boiling();
    if (boil_started) {
      SendMsg("Спиртуозность " + format_float(alcohol_s, 1), WARNING_MSG);
    }
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
        set_buzzer(true);
        SendMsg(("Стабилизация завершена, колонна работает стабильно."), NOTIFY_MSG);
      }
    } else {
      acceleration_temp = 0;
      SteamSensor.PrevTemp = SteamSensor.avgTemp;
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

void open_valve(bool Val, bool msg = true) {
  if (Val && !alarm_event) {
    valve_status = true;
    if (msg) {
      SendMsg(("Откройте подачу воды!"), WARNING_MSG);
    } else {
      SendMsg(("Открыт клапан воды охлаждения!"), NOTIFY_MSG);
    }
    digitalWrite(RELE_CHANNEL3, SamSetup.rele3);
  } else {
    valve_status = false;
    if (msg) {
      SendMsg(("Закройте подачу воды!"), WARNING_MSG);
    } else {
      SendMsg(("Закрыт клапан воды охлаждения!"), NOTIFY_MSG);
    }
    digitalWrite(RELE_CHANNEL3, !SamSetup.rele3);
  }
}

void triggerBuzzerTask(void *parameter) {
  TickType_t beep = 400 / portTICK_RATE_MS;
  TickType_t silent = 600 / portTICK_RATE_MS;
  int tick_buzz = 0;

  while (true) {
    if (BuzzerTaskFl) {
      digitalWrite(BZZ_PIN, HIGH);
      vTaskDelay(beep / portTICK_PERIOD_MS);
      digitalWrite(BZZ_PIN, LOW);
      tick_buzz++;
      if (tick_buzz > 5) BuzzerTaskFl = false;
    }
    vTaskDelay(silent / portTICK_PERIOD_MS);
  }
}

void set_buzzer(bool fl) {
  if (fl && SamSetup.UseBuzzer) {
    if (BuzzerTask == NULL) {
      BuzzerTaskFl = true;
      //Запускаем таск для пищалки
      xTaskCreatePinnedToCore(
        triggerBuzzerTask, /* Function to implement the task */
        "BuzzerTask",      /* Name of the task */
        800,               /* Stack size in words */
        NULL,              /* Task input parameter */
        0,                 /* Priority of the task */
        &BuzzerTask,       /* Task handle. */
        1);                /* Core where the task should run */
    }
  } else {
    if (BuzzerTask != NULL && !BuzzerTaskFl) {
      vTaskDelete(BuzzerTask);
      BuzzerTask = NULL;
      digitalWrite(BZZ_PIN, LOW);
    }
  }
}

void set_power(bool On) {
  if (alarm_event && On) {
    return;
  }
  PowerOn = On;
  if (On) {
    digitalWrite(RELE_CHANNEL1, SamSetup.rele1);
    set_menu_screen(2);
    power_text_ptr = (char *)"OFF";

#ifdef SAMOVAR_USE_SEM_AVR
    vTaskDelay(3000 / portTICK_PERIOD_MS);
#endif

#ifdef SAMOVAR_USE_POWER
    vTaskDelay(SAMOVAR_USE_POWER_START_TIME / portTICK_PERIOD_MS);
    set_power_mode(POWER_SPEED_MODE);
#else
    current_power_mode = POWER_SPEED_MODE;
    digitalWrite(RELE_CHANNEL4, SamSetup.rele4);
#endif
  } else {
    digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);
    acceleration_heater = false;
#ifdef SAMOVAR_USE_POWER
    vTaskDelay(700 / portTICK_PERIOD_MS);
    set_power_mode(POWER_SLEEP_MODE);
    vTaskDelay(200 / portTICK_PERIOD_MS);
#else
    current_power_mode = POWER_SLEEP_MODE;
#endif
    power_text_ptr = (char *)"ON";
    sam_command_sync = SAMOVAR_RESET;
    digitalWrite(RELE_CHANNEL1, !SamSetup.rele1);
  }
}

float get_steam_alcohol(float t) {
  if (!boil_started) return 100;

  float r;
  float t1;
  float s;
  float k;
  uint8_t t0;

  t1 = t;
  t = get_temp_by_pressure(0, t, bme_pressure);

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
  t = get_temp_by_pressure(0, t, bme_pressure);
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
    boil_temp = TankSensor.avgTemp;
    alcohol_s = get_alcohol(TankSensor.avgTemp);
#ifdef USE_WATER_PUMP
    wp_count = -10;
#endif
    //    }
  }
}

bool check_boiling() {
  if (boil_started || !PowerOn || !valve_status || TankSensor.avgTemp < 70) {
    return false;
  }

  //учтем задержку в 60 секунд до начала процесса определения кипения, чтобы датчик температуры воды успел остыть, если он нагрелся
  if (b_t_time_delay == 0 || (b_t_time_delay + 60 * 1000 > millis())) {
    if (b_t_time_delay == 0) {
      b_t_time_delay = millis();
    }
    return false;
  }

  //Если минимальная температура воды охлаждения больше текущей, то запоминаем её
  if (d_s_temp_prev > WaterSensor.avgTemp || d_s_temp_prev == 0) {
    d_s_temp_prev = WaterSensor.avgTemp;
  }
  //Определяем, что началось кипение - вода охлаждения начала нагреваться
  if (WaterSensor.avgTemp - d_s_temp_prev > 8 || SteamSensor.avgTemp > CHANGE_POWER_MODE_STEAM_TEMP) {
    set_boiling();
  }
  //Если температура воды охлаждения близка к заданной, то кипение началось
  if (abs(WaterSensor.avgTemp - SamSetup.SetWaterTemp) < 3 && WaterSensor.avgTemp - d_s_temp_prev > 2) {
    set_boiling();
  }
  //Проверяем, что температура в кубе не менялась более 0.1 градуса в течение 50 секунд, если менялась, то кипение не началось
  if (TankSensor.avgTemp - b_t_temp_prev > 0.1) {
    b_t_temp_prev = TankSensor.avgTemp;
    b_t_time_min = millis();
  } else if ((millis() - b_t_time_min) > 50 * 1000 && b_t_time_min > 0) {
    set_boiling();
  }
  if (boil_started) {
    SendMsg("Началось кипение в кубе! Спиртуозность " + format_float(alcohol_s, 1), WARNING_MSG);
  }
  return boil_started;
}

void start_self_test(void) {
  is_self_test = true;
  SendMsg(("Запуск самотестирования."), NOTIFY_MSG);
  open_valve(true, true);
#ifdef USE_WATER_PUMP
  //включаем насос воды
  set_pump_pwm((PWM_START_VALUE + 20) * 10);
#endif
  //включаем шаговый двигатель
  stopService();
  stepper.setMaxSpeed(get_speed_from_rate(1));
  //stepper.setSpeed(get_speed_from_rate(1));
  TargetStepps = 100 * SamSetup.StepperStepMl;
  stepper.setCurrent(0);
  stepper.setTarget(TargetStepps);
  startService();
  //включаем сервопривод
  set_capacity(1);
  while (capacity_num != 0 && capacity_num < 5) {
    vTaskDelay(3000 / portTICK_PERIOD_MS);
    next_capacity();
  }
  vTaskDelay(15000 / portTICK_PERIOD_MS);
  stop_self_test();
  SendMsg(("Самотестирование закончено."), NOTIFY_MSG);
}

void stop_self_test(void) {
#ifdef USE_WATER_PUMP
  //выключаем насос воды
  set_pump_pwm(0);
#endif
  open_valve(false, true);
  set_capacity(0);
  stopService();
  is_self_test = false;
  reset_sensor_counter();
}

//////////////////////////////////////////////////////////////////////////////////////////////////////////////
// SAMOVAR_USE_POWER
//////////////////////////////////////////////////////////////////////////////////////////////////////////////
#ifdef SAMOVAR_USE_POWER
#ifndef SAMOVAR_USE_RMVK
void triggerPowerStatus(void *parameter) {
  int i;
  String resp;
  while (true) {
    //T3EA3E80
    if (PowerOn) {
      Serial2.flush();
      vTaskDelay(300 / portTICK_PERIOD_MS);
      if (Serial2.available()) {
        resp = Serial2.readStringUntil('\r');
        i = resp.indexOf("T");
        if (i < 0) {
          vTaskDelay(50 / portTICK_PERIOD_MS);
          resp = Serial2.readStringUntil('\r');
        }
        resp = resp.substring(i, resp.length());
#ifdef __SAMOVAR_DEBUG
        WriteConsoleLog("RESP_T =" + resp.substring(0, 1));
#endif
        if (resp.substring(0, 1) == "T" && resp.length() == 8 ) {
#ifdef KVIC_DEBUG
          String r = resp;
#endif
          resp = resp.substring(1, 9);
#ifdef __SAMOVAR_DEBUG
          WriteConsoleLog("RESP_F =" + resp.substring(1, 7));
          WriteConsoleLog("RESP_MODE =" + resp.substring(6, 7));
#endif
          int cpv = hexToDec(resp.substring(0, 3));
          //Если напряжение больше 249 или меньше 10 - не корректно получено значение от регулятора, оставляем старое значение
          if (cpv > 30 && cpv < 2490) {
            current_power_volt = cpv / 10.0F;
            target_power_volt = hexToDec(resp.substring(3, 6)) / 10.0F;
            current_power_mode = resp.substring(6, 7);
            vTaskDelay(100 / portTICK_PERIOD_MS);
          }
#ifdef KVIC_DEBUG
            //Serial.println(r);
            if (cpv < 300 || cpv > 2400)
            {
                r+=";" + String(cpv) + ";" + String(target_power_volt) + ";" + String(current_power_mode);
                SendMsg(("НАПРЯЖЕНИЕ!!!: " + r), NOTIFY_MSG);
            }
#endif
        }
      }
    } else {
      vTaskDelay(400 / portTICK_PERIOD_MS);
    }
  }
}
#else
void triggerPowerStatus(void *parameter) {
  String resp;
  uint16_t v;
  while (true) {
    if (PowerOn) {
#ifdef SAMOVAR_USE_SEM_AVR
      if (xSemaphoreTake(xSemaphoreAVR, (TickType_t)((RMVK_DEFAULT_READ_TIMEOUT) / portTICK_RATE_MS)) == pdTRUE) {
        vTaskDelay(RMVK_READ_DELAY / 10 / portTICK_PERIOD_MS);
        Serial2.flush();
        vTaskDelay(10 / portTICK_RATE_MS);
        Serial2.print("АТ+SS?\r");
        for (int i = 0; i < 2; i++) {
          vTaskDelay(RMVK_READ_DELAY / portTICK_RATE_MS);
          if (Serial2.available()) {
            current_power_mode = Serial2.readStringUntil('\r');
#ifdef __SAMOVAR_DEBUG
            WriteConsoleLog("CPM=" + current_power_mode);
#endif
            break;
          }
        }
        xSemaphoreGive(xSemaphoreAVR);
      }
      vTaskDelay(RMVK_READ_DELAY / 5 / portTICK_PERIOD_MS);
      if (xSemaphoreTake(xSemaphoreAVR, (TickType_t)((RMVK_DEFAULT_READ_TIMEOUT) / portTICK_RATE_MS)) == pdTRUE) {
        vTaskDelay(RMVK_READ_DELAY / 10 / portTICK_PERIOD_MS);
        Serial2.flush();
        vTaskDelay(10 / portTICK_RATE_MS);
        Serial2.print("АТ+VO?\r");
        for (int i = 0; i < 2; i++) {
          vTaskDelay(RMVK_READ_DELAY / portTICK_RATE_MS);
          if (Serial2.available()) {
            resp = Serial2.readStringUntil('\r');
#ifdef __SAMOVAR_DEBUG
            WriteConsoleLog("CPV=" + resp);
#endif
            current_power_volt = resp.toInt();
            break;
          }
        }
        xSemaphoreGive(xSemaphoreAVR);
      }
      vTaskDelay(RMVK_READ_DELAY / 5 / portTICK_PERIOD_MS);
      if (xSemaphoreTake(xSemaphoreAVR, (TickType_t)((RMVK_DEFAULT_READ_TIMEOUT) / portTICK_RATE_MS)) == pdTRUE) {
        vTaskDelay(RMVK_READ_DELAY / 10 / portTICK_PERIOD_MS);
        Serial2.flush();
        vTaskDelay(10 / portTICK_RATE_MS);
        Serial2.print("АТ+VS?\r");
        for (int i = 0; i < 2; i++) {
          vTaskDelay(RMVK_READ_DELAY / portTICK_RATE_MS);
          if (Serial2.available()) {
            resp = Serial2.readStringUntil('\r');
#ifdef __SAMOVAR_DEBUG
            WriteConsoleLog("TPV=" + resp);
#endif
            v = resp.toInt();
            if (v != 0) {
              target_power_volt = v;
            }
            break;
          }
        }
        xSemaphoreGive(xSemaphoreAVR);
      }
      vTaskDelay(RMVK_READ_DELAY / 5 / portTICK_PERIOD_MS);
#else
      current_power_volt = RMVK_get_out_voltge();
      vTaskDelay(RMVK_READ_DELAY / portTICK_PERIOD_MS);
      v = RMVK_get_store_out_voltge();
      vTaskDelay(RMVK_READ_DELAY / portTICK_PERIOD_MS);
      rmvk.on = RMVK_get_state() > 0;
      if (v != 0) {
        target_power_volt = v;
      }
#endif
    }
    vTaskDelay(RMVK_READ_DELAY / 5 / portTICK_PERIOD_MS);
  }
}
#endif

void check_power_error() {
#ifndef __SAMOVAR_DEBUG
  //Проверим, что заданное напряжение/мощность не сильно отличается от реального (наличие связи с регулятором, пробой семистора)
  if (SamSetup.CheckPower && current_power_mode == POWER_WORK_MODE && current_power_volt > 0 && abs((current_power_volt - target_power_volt) / current_power_volt) > 2) {
    power_err_cnt++;
    //if (power_err_cnt == 2) SendMsg(("Ошибка регулятора!"), ALARM_MSG);
    if (power_err_cnt > 6) set_current_power(target_power_volt);
    if (power_err_cnt > 12) {
      delay(1000);  //Пауза на всякий случай, чтобы прошли все другие команды
      set_buzzer(true);
      set_power(false);
      SendMsg(("Аварийное отключение! Ошибка управления нагревателем."), ALARM_MSG);
    }
  } else
#endif
    power_err_cnt = 0;
}


//получаем текущие параметры работы регулятора напряжения
void get_current_power() {
  if (!PowerOn) {
    current_power_volt = 0;
    target_power_volt = 0;
    current_power_mode = "N";
    current_power_p = 0;
    return;
  }
#ifndef SAMOVAR_USE_SEM_AVR
  //Считаем мощность V*V*K/R, K = 0,98~1
  current_power_p = current_power_volt * current_power_volt / SamSetup.HeaterResistant;
#else
  current_power_p = target_power_volt;
#endif
}

//устанавливаем напряжение для регулятора напряжения
void set_current_power(float Volt) {
  if (!PowerOn) return;
#ifdef __SAMOVAR_DEBUG
  WriteConsoleLog("Set current power =" + (String)Volt);
#endif
  //vTaskDelay(100 / portTICK_PERIOD_MS); 5.13
#ifndef SAMOVAR_USE_SEM_AVR
  if (Volt < 40) {
#else
  if (Volt < 100) {
#endif
    set_power_mode(POWER_SLEEP_MODE);
    return;
  } else {
    set_power_mode(POWER_WORK_MODE);
    //vTaskDelay(100/portTICK_PERIOD_MS);
  }
  target_power_volt = Volt;
  vTaskDelay(100 / portTICK_PERIOD_MS);
#ifdef SAMOVAR_USE_RMVK
#ifndef SAMOVAR_USE_SEM_AVR
  RMVK_set_out_voltge(Volt);
#else
  if (xSemaphoreTake(xSemaphoreAVR, (TickType_t)((RMVK_DEFAULT_READ_TIMEOUT * 3) / portTICK_RATE_MS)) == pdTRUE) {
    String Cmd;
    int V = Volt;
    if (V < 100) Cmd = "0";
    else
      Cmd = "";
    Cmd = Cmd + (String)V;
    vTaskDelay(RMVK_READ_DELAY / 10 / portTICK_PERIOD_MS);
    Serial2.print("АТ+VS=" + Cmd + "\r");
    vTaskDelay(RMVK_READ_DELAY / portTICK_PERIOD_MS);
    xSemaphoreGive(xSemaphoreAVR);
  }
#endif
#else
  String hexString = String((int)(Volt * 10), HEX);
  Serial2.print("S" + hexString + "\r");
#endif
  target_power_volt = Volt;
}

void set_power_mode(String Mode) {
  if (current_power_mode == Mode) return;
  current_power_mode = Mode;
  vTaskDelay(50 / portTICK_PERIOD_MS);
#ifdef SAMOVAR_USE_RMVK
  if (Mode == POWER_SLEEP_MODE) {
#ifdef SAMOVAR_USE_SEM_AVR
    if (xSemaphoreTake(xSemaphoreAVR, (TickType_t)((RMVK_DEFAULT_READ_TIMEOUT * 3) / portTICK_RATE_MS)) == pdTRUE) {
      vTaskDelay(RMVK_READ_DELAY / 10 / portTICK_PERIOD_MS);
      Serial2.print("АТ+ON=0\r");
      vTaskDelay(RMVK_READ_DELAY / portTICK_PERIOD_MS);
      xSemaphoreGive(xSemaphoreAVR);
    }
#else
    RMVK_set_on(0);
#endif
  } else if (Mode == POWER_SPEED_MODE) {
#ifdef __SAMOVAR_DEBUG
    WriteConsoleLog("Set power mode=" + Mode);
#endif
#ifdef SAMOVAR_USE_SEM_AVR
    if (xSemaphoreTake(xSemaphoreAVR, (TickType_t)((RMVK_DEFAULT_READ_TIMEOUT * 7) / portTICK_RATE_MS)) == pdTRUE) {
      vTaskDelay(RMVK_READ_DELAY / 6 / portTICK_PERIOD_MS);
      Serial2.flush();
      Serial2.print("АТ+ON=1\r");
      vTaskDelay(RMVK_READ_DELAY / portTICK_PERIOD_MS);
      Serial2.flush();
      xSemaphoreGive(xSemaphoreAVR);
    }
#else
    RMVK_set_on(1);
    vTaskDelay(RMVK_READ_DELAY / portTICK_PERIOD_MS);
    RMVK_set_out_voltge(MAX_VOLTAGE);
    vTaskDelay(RMVK_READ_DELAY / portTICK_PERIOD_MS);
#endif
  }
#else
  Serial2.print("M" + Mode + "\r");
  vTaskDelay(300 / portTICK_PERIOD_MS);
#endif
}

unsigned int hexToDec(String hexString) {
  unsigned int decValue = 0;
  int nextInt;

  for (uint8_t i = 0; i < hexString.length(); i++) {

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

#ifdef COLUMN_WETTING
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
