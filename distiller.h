#include <Arduino.h>
#include "Samovar.h"

void distiller_finish();
void set_power_mode(String Mode);
void set_power(bool On);
void create_data();
void open_valve(bool Val);
void set_pump_pwm(float duty);
void set_pump_speed_pid(float temp);
void set_dist_program(String WProgram);
void run_dist_program(byte num);
String get_dist_program();

#ifdef USE_WATER_PUMP
bool check_boiling();
#endif
void SendMsg(String m, MESSAGE_TYPE msg_type);

void distiller_proc() {

  if (!PowerOn) {
#ifdef USE_MQTT
    SessionDescription.replace(",", ";");
    MqttSendMsg((String)chipId + "," + SamSetup.TimeZone + "," + SAMOVAR_VERSION + "," + get_dist_program() + "," + SessionDescription, "st");
#endif
    set_power(true);
#ifdef SAMOVAR_USE_POWER
    delay(1000);
    set_power_mode(POWER_SPEED_MODE);
#else
    current_power_mode = POWER_SPEED_MODE;
    digitalWrite(RELE_CHANNEL4, SamSetup.rele4);
#endif
    create_data();  //создаем файл с данными
    SteamSensor.Start_Pressure = bme_pressure;
    SendMsg(F("Включен нагрев дистиллятора"), NOTIFY_MSG);
    run_dist_program(0);
    d_s_temp_prev = WaterSensor.avgTemp;
#ifdef SAMOVAR_USE_POWER
    digitalWrite(RELE_CHANNEL4, SamSetup.rele4);
#endif
  }

  if (TankSensor.avgTemp >= SamSetup.DistTemp) {
    distiller_finish();
  }

  //Обрабатываем программу дистилляции
  if (program[ProgramNum].WType == "T" && program[ProgramNum].Speed <= TankSensor.avgTemp) {
    //Если температура куба превысила заданное в программе значение - переходим на следующую строку программы
    run_dist_program(ProgramNum + 1);
  } else if (program[ProgramNum].WType == "A" && program[ProgramNum].Speed >= get_alcohol(TankSensor.avgTemp)) {
    //Если спиртуозность в кубе понизилась до заданного в программе значения - переходим на следующую строку программы
    run_dist_program(ProgramNum + 1);
  } else if (program[ProgramNum].WType == "S" && program[ProgramNum].Speed >= get_alcohol(TankSensor.avgTemp) / get_alcohol(TankSensor.StartProgTemp)) {
    run_dist_program(ProgramNum + 1);
  } else if (program[ProgramNum].WType == "P" && program[ProgramNum].Speed >= get_steam_alcohol(TankSensor.avgTemp)) {
    //Если спиртуозность в кубе понизилась до заданного в программе значения - переходим на следующую строку программы
    run_dist_program(ProgramNum + 1);
  } else if (program[ProgramNum].WType == "R" && program[ProgramNum].Speed >= get_steam_alcohol(TankSensor.avgTemp) / get_steam_alcohol(TankSensor.StartProgTemp)) {
    run_dist_program(ProgramNum + 1);
  }


  //Если Т в кубе больше 90 градусов и включено напряжение, проверяем, что 16 минут температура в кубе не меняется от последнего заполненного значения больше, чем на 0.1 градус
  if (TankSensor.avgTemp > 90 && PowerOn) {
    if (abs(TankSensor.avgTemp - d_s_temp_finish) > 0.1) {
      d_s_temp_finish = TankSensor.avgTemp;
      d_s_time_min = millis();
    } else if ((millis() - d_s_time_min) > 16 * 60 * 1000) {
      SendMsg(F("В кубе не осталось спирта"), NOTIFY_MSG);
      distiller_finish();
    }
  }
}

void IRAM_ATTR distiller_finish() {
#ifdef SAMOVAR_USE_POWER
  digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);
#endif
  SendMsg(F("Дистилляция завершена"), NOTIFY_MSG);
  set_power(false);
  reset_sensor_counter();
}


void IRAM_ATTR check_alarm_distiller() {
  //сбросим паузу события безопасности
  if (alarm_t_min > 0 && alarm_t_min <= millis()) alarm_t_min = 0;

  if (PowerOn && !valve_status && TankSensor.avgTemp >= OPEN_VALVE_TANK_TEMP) {
    open_valve(true);
  }

  if (!valve_status) {
    if (ACPSensor.avgTemp >= MAX_ACP_TEMP - 5) open_valve(true);
  }

  if (!PowerOn && !is_self_test && valve_status && WaterSensor.avgTemp <= SamSetup.SetWaterTemp - DELTA_T_CLOSE_VALVE) {
    open_valve(false);
#ifdef USE_WATER_PUMP
    if (pump_started) set_pump_pwm(0);
#endif
  }

  //Определяем, что началось кипение - вода охлаждения начала нагреваться
  check_boiling();

#ifdef USE_WATER_PUMP

  //Устанавливаем ШИМ для насоса в зависимости от температуры воды
  if (valve_status) {
    if (ACPSensor.avgTemp > SamSetup.SetACPTemp && ACPSensor.avgTemp > WaterSensor.avgTemp) set_pump_speed_pid(SamSetup.SetWaterTemp + 3);
    else
      set_pump_speed_pid(WaterSensor.avgTemp);
  }
#endif

  //Проверяем, что температурные параметры не вышли за предельные значения
  if ((WaterSensor.avgTemp >= MAX_WATER_TEMP || ACPSensor.avgTemp >= MAX_ACP_TEMP) && PowerOn) {
    //Если с температурой проблемы - выключаем нагрев, пусть оператор разбирается
    set_buzzer(true);
    set_power(false);
    String s = "";
    if (WaterSensor.avgTemp >= MAX_WATER_TEMP)
      s = s + " Воды";
    else if (ACPSensor.avgTemp >= MAX_ACP_TEMP)
      s = s + " ТСА";
    SendMsg("Аварийное отключение! Превышена максимальная температура" + s, ALARM_MSG);
  }

#ifdef USE_WATERSENSOR
  //Проверим, что вода подается
  if (WFAlarmCount > WF_ALARM_COUNT && PowerOn) {
    set_buzzer(true);
    //Если с водой проблемы - выключаем нагрев, пусть оператор разбирается
    sam_command_sync = SAMOVAR_POWER;
    SendMsg(F("Аварийное отключение! Прекращена подача воды."), ALARM_MSG);
  }
#endif

  if ((WaterSensor.avgTemp >= ALARM_WATER_TEMP - 5) && PowerOn && alarm_t_min == 0) {
    set_buzzer(true);
    //Если уже реагировали - надо подождать 30 секунд, так как процесс инерционный
    SendMsg(F("Критическая температура воды!"), WARNING_MSG);

#ifdef SAMOVAR_USE_POWER
    check_power_error();
    if (WaterSensor.avgTemp >= ALARM_WATER_TEMP) {
      set_buzzer(true);
      SendMsg("Критическая температура воды! Напряжение снижено с " + (String)target_power_volt, ALARM_MSG);
      //Попробуем снизить напряжение регулятора на 5 вольт, чтобы исключить перегрев колонны.
      set_current_power(target_power_volt - 5);
    }
#endif
    alarm_t_min = millis() + 30000;
  }

#ifdef USE_WATER_VALVE
  if (WaterSensor.avgTemp >= SamSetup.SetWaterTemp + 1) {
    digitalWrite(WATER_PUMP_PIN, USE_WATER_VALVE);
  } else if (WaterSensor.avgTemp <= SamSetup.SetWaterTemp - 1) {
    digitalWrite(WATER_PUMP_PIN, !USE_WATER_VALVE);
  }
#endif
}

void run_dist_program(byte num) {
  ProgramNum = num;

  SendMsg("Переход к строке программы №" + (String)(num + 1), NOTIFY_MSG);

  //запоминаем текущие значения температур
  SteamSensor.StartProgTemp = SteamSensor.avgTemp;
  PipeSensor.StartProgTemp = PipeSensor.avgTemp;
  WaterSensor.StartProgTemp = WaterSensor.avgTemp;
  TankSensor.StartProgTemp = TankSensor.avgTemp;

  if (num > 0) set_capacity(program[num - 1].capacity_num);
  
  if (program[num].WType != "") {
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
#endif
  }
}

void set_dist_program(String WProgram) {
  char c[500];
  WProgram.toCharArray(c, 500);
  char *pair = strtok(c, ";");
  //String MeshTemplate;
  int i = 0;
  while (pair != NULL and i < CAPACITY_NUM * 2) {
    program[i].WType = pair;
    pair = strtok(NULL, ";");
    program[i].Speed = atof(pair);  //Value
    pair = strtok(NULL, ";");
    program[i].capacity_num = atoi(pair);
    pair = strtok(NULL, "\n");
    program[i].Power = atof(pair);
    i++;
    ProgramLen = i;
    pair = strtok(NULL, ";");
    if ((!pair || pair == NULL || pair[0] == 13) and i < CAPACITY_NUM * 2) {
      program[i].WType = "";
      break;
    }
  }
}

String get_dist_program() {
  String Str = "";
  int k = CAPACITY_NUM * 2;
  for (byte i = 0; i < k; i++) {
    if (program[i].WType == "") {
      i = CAPACITY_NUM * 2 + 1;
    } else {
      Str += program[i].WType + ";";
      Str += (String)program[i].Speed + ";";
      Str += (String)(int)program[i].capacity_num + ";";
      Str += (String)program[i].Power + "\n";
    }
  }
  return Str;
}
