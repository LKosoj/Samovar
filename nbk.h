#include <Arduino.h>
#include "Samovar.h"

void nbk_finish();
void set_power_mode(String Mode);
void set_power(bool On);
void create_data();
void open_valve(bool Val, bool msg);
void set_pump_pwm(float duty);
void set_pump_speed_pid(float temp);
void SendMsg(String m, MESSAGE_TYPE msg_type);
bool check_boiling();
void set_water_temp(float duty);
String getValue(String data, char separator, int index);
void run_nbk_program(uint8_t num);
bool set_stepper_target(uint16_t spd, uint8_t direction, uint32_t target);
float i2c_get_liguid_rate_by_step(int StepperSpeed);
float i2c_get_speed_from_rate(float volume_per_hour);
float i2c_get_liquid_volume();
uint16_t get_stepper_speed(void);
bool set_stepper_target(uint16_t spd, uint8_t direction, uint32_t target);

// Описание алгоритма работы
// 1) Прогрев на мощности 3000 Вт с подачей браги 3 л/ч до температуры пара 85 гр.Ц.
// 2) Стабилизация 300 сек, с подачей браги 18 л/ч на мощности 2400 Вт. После чего запоминаем температуру внизу колонны Тн.
// 3) Увеличение подачи браги, до 20 л/ч ступенями 0.1 л/ч каждых 5 сек, далее 0.05 л/ч каждых 5 сек, пока температура внизу колонны не просядет на 0.5 гр.Ц от Тн.
// 4) Каждых 5 сек. пока давление не достигнет 20 мм.рт.ст. наращивается мощность ступенями по 5 Вт и если просадка температуры от запомненной Тн внизу колонны менее 0.5 гр.Ц наращивается подача браги ступенями по 0.05 л/ч. В конце убавляем мощность на 100 Вт.
// 5) Работа. Раз в 5 сек: Если Твнизу<Тн-0.5 гр.Ц то уменьшаем подачу браги на 0.05 л/ч, если Твнизу>Тн то увеличиваем подачу браги на 0.05 л/ч.

// При выполнении строк программы осуществляются проверки:
// 1) Работа датчика захлёба - мощность снижаем на 100 Вт и ждём 60 сек.
// 2) Превышение уставки по давлению - мощность снижаем на 10 Вт и ждём 10 сек.
// 3) Т пара>98.1 гр.Ц - Закончилась брага - останавливаем процесс.
// 4) Ттса (спирт) > 60 гр.Ц или Тводы > 70 гр.Ц - не достаточное охлаждение, ждем 60 сек, если не снижается останавливаем процесс.
// 5) Срабатывание датчика недостаточного уровня воды в парогене (LUA pin) - ждем 60 сек, если не восстановится останавливаем процесс.

void IRAM_ATTR isrNBKLS_TICK() {
  nbkls.tick();
}

void nbk_proc() {

#if defined(USE_PRESSURE_XGZ) || defined(USE_PRESSURE_1WIRE) || defined (USE_PRESSURE_MPX)
#else
  SendMsg(("Управление НБК не поддерживается вашим оборудованием!"), NOTIFY_MSG);
  nbk_finish();
  return;
#endif

  if (!PowerOn) {
#ifdef USE_MQTT
    SessionDescription.replace(",", ";");
    MqttSendMsg((String)chipId + "," + SamSetup.TimeZone + "," + SAMOVAR_VERSION + ",NBK," + SessionDescription, "st");
#endif
    set_power(true);
#ifdef SAMOVAR_USE_POWER
    delay(1000);
    set_current_power(program[ProgramNum].Power);
#else
    current_power_mode = POWER_SPEED_MODE;
    digitalWrite(RELE_CHANNEL4, SamSetup.rele4);
#endif
    create_data();  //создаем файл с данными
    SteamSensor.Start_Pressure = bme_pressure;
    SendMsg(("Включен нагрев НБК"), NOTIFY_MSG);

    //настраиваем параметры датчика уровня воды в парогене
//    nbkls.setType(LOW_PULL);
//    nbkls.setDebounce(50);  //игнорируем дребезг
//    nbkls.setTickMode(MANUAL);
//    nbkls.setTimeout(60 * 1000);  //время, через которое сработает остановка по уровню воды в парогенераторе
//    //вешаем прерывание на изменение датчика уровня флегмы
//    attachInterrupt(LUA_PIN, isrNBKLS_TICK, CHANGE);

    run_nbk_program(0);
    set_stepper_target(i2c_get_speed_from_rate(program[ProgramNum].Speed), 0, 4294967295);
  }

  //Обрабатываем программу НБК
  if (program[ProgramNum].WType == "H" && SteamSensor.avgTemp >= 85) {
    //Если Т пара больше 85 градусов, переходим к стабилизации НБК
    run_nbk_program(ProgramNum + 1);
  } else if (program[ProgramNum].WType == "S" && begintime <= millis()) {
    //Если прошло 300 секунд с начала стабилизации НБК, переходим к программе выхода на заданную скорость отбора
    run_nbk_program(ProgramNum + 1);
  } else if (program[ProgramNum].WType == "T" && program[ProgramNum].Speed >= get_stepper_speed() && d_s_temp_prev - 0.5 <= TankSensor.avgTemp && TankSensor.avgTemp > 80) {
    //Если достигли заданной скорости и вышли за пределы Т внизу колонны, переходим к программе выхода на заданное давление
    run_nbk_program(ProgramNum + 1);
  } else if (program[ProgramNum].WType == "P" && pressure_value > program[ProgramNum].capacity_num) {
    //Если достигли заданного давления, переходим к рабочей программе
    run_nbk_program(ProgramNum + 1);
  }

  //управляющие воздействия для текущей программы
  if (program[ProgramNum].WType == "T") {
    if (t_min <= millis()) {
      float spdinc;
      if (program[ProgramNum].Speed < get_stepper_speed()) {
        spdinc = NBK_PUMP_INCREMENT * 2;
      } else {
        spdinc = NBK_PUMP_INCREMENT;
      }
      set_stepper_target(get_stepper_speed() + i2c_get_speed_from_rate(spdinc / 1000.00), 0, 4294967295);
    } else {
      t_min = millis() + 5 * 1000;
    }
  } else if (program[ProgramNum].WType == "P") {
    if (t_min <= millis()) {
#ifdef SAMOVAR_USE_SEM_AVR
      //Если регулятор мощности - повышаем на 15 ватт
      set_current_power(target_power_volt + 15);
#else
      //Если регулятор напряжения - снижаем на 2 вольта
      set_current_power(target_power_volt + 2);
#endif
      if (TankSensor.avgTemp >= d_s_temp_prev - 0.5) {
        set_stepper_target(get_stepper_speed() + i2c_get_speed_from_rate(float(NBK_PUMP_INCREMENT) / 1000.00), 0, 4294967295);
      }
    } else {
      t_min = millis() + 5 * 1000;
    }
  } else if (program[ProgramNum].WType == "W") {
    if (t_min <= millis()) {
      if (TankSensor.avgTemp < d_s_temp_prev - 0.5) {
        set_stepper_target(get_stepper_speed() - i2c_get_speed_from_rate(float(NBK_PUMP_INCREMENT) / 1000.00 - 0.0001), 0, 4294967295);
      } else if (TankSensor.avgTemp > d_s_temp_prev) {
        set_stepper_target(get_stepper_speed() + i2c_get_speed_from_rate(float(NBK_PUMP_INCREMENT) / 1000.00), 0, 4294967295);
      }
    } else {
      t_min = millis() + 5 * 1000;
    }
  }

  vTaskDelay(10 / portTICK_PERIOD_MS);
}

void nbk_finish() {
  SendMsg(("Работа НБК завершена"), NOTIFY_MSG);
  set_power(false);
  set_stepper_target(0, 0, 0);
  reset_sensor_counter();
  if (fileToAppend) {
    fileToAppend.close();
  }

}

void run_nbk_program(uint8_t num) {
  if (Samovar_Mode != SAMOVAR_NBK_MODE || !PowerOn) return;
  if (startval == 4000) startval = 4001;
  ProgramNum = num;
  begintime = 0;
  t_min = 0;
  msgfl = true;

  if (ProgramNum > ProgramLen - 1) num = CAPACITY_NUM * 2;

  if (SamSetup.ChangeProgramBuzzer) {
    set_buzzer(true);
  }

  if (num == CAPACITY_NUM * 2) {
    //если num = CAPACITY_NUM * 2 значит мы достигли финала (или процесс сброшен принудительно), завершаем работу
    nbk_finish();
    return;
  } else {
    SendMsg("Переход к строке программы №" + (String)(num + 1), NOTIFY_MSG);
  }

  if (program[ProgramNum].WType == "S") {
    begintime = millis() + 300 * 1000;
    set_stepper_target(i2c_get_speed_from_rate(program[ProgramNum].Speed), 0, 4294967295);
    set_current_power(program[ProgramNum].Power);
  } else if (program[ProgramNum].WType == "T") {
    //Запомним Тниз = d_s_temp_prev
    d_s_temp_prev = TankSensor.avgTemp;
    begintime = 0;
  } else if (program[ProgramNum].WType == "W") {
    //Изменяем на заданную мощность
    set_current_power(target_power_volt + program[ProgramNum].Power);
  }

}

void check_alarm_nbk() {

  if (!PowerOn && !is_self_test && valve_status && WaterSensor.avgTemp <= TARGET_WATER_TEMP - 20) {
    open_valve(false, true);
#ifdef USE_WATER_PUMP
    if (pump_started) set_pump_pwm(0);
#endif
  }

  if (!PowerOn) {
    return;
  }
  //сбросим паузу события безопасности
  if (alarm_t_min > 0 && alarm_t_min <= millis()) alarm_t_min = 0;

  if (PowerOn && !valve_status && TankSensor.avgTemp >= OPEN_VALVE_TANK_TEMP) {
    open_valve(true, true);
#ifdef USE_WATER_PUMP
    set_pump_pwm(bk_pwm);
#endif
  }

  //Проверяем, что температурные параметры не вышли за предельные значения
  if ((WaterSensor.avgTemp >= MAX_WATER_TEMP) && PowerOn) {
    set_buzzer(true);
    //Если с температурой проблемы - выключаем нагрев, пусть оператор разбирается
    set_power(false);
    SendMsg(("Аварийное отключение! Превышена максимальная температура воды охлаждения!"), ALARM_MSG);
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

  //Контролируем воду, 4)
  if (((WaterSensor.avgTemp >= ALARM_WATER_TEMP - 5) || ACPSensor.avgTemp >= 60) && PowerOn && alarm_t_min == 0) {
    set_buzzer(true);
    //Если уже реагировали - надо подождать 60 секунд, так как процесс инерционный

#ifdef SAMOVAR_USE_POWER

    check_power_error();
    if (WaterSensor.avgTemp >= ALARM_WATER_TEMP) {
      set_buzzer(true);
      SendMsg("Критическая температура воды! Понижаем " + (String)PWR_MSG + " с " + (String)target_power_volt, ALARM_MSG);
      //Попробуем снизить напряжение регулятора на 5 вольт, чтобы исключить перегрев колонны.
      set_current_power(target_power_volt - 5);
    }
#elif
    SendMsg(("Критическая температура воды!"), WARNING_MSG);
#endif
    alarm_t_min = millis() + 60000;
  }

  //Контролируем Т пара>98.1 3)
  if ((SteamSensor.avgTemp >= 98.1) && PowerOn) {
    SendMsg(("Брага зкончилась! Остановка"), WARNING_MSG);
    run_nbk_program(CAPACITY_NUM * 2);
  }

  //Работа датчика захлёба - мощность снижаем на 100 Вт и ждём 60 сек. 1)
  //Если используется датчик уровня флегмы в голове
#ifdef USE_HEAD_LEVEL_SENSOR
  if (PowerOn) {
    whls.tick();
    if (whls.isHolded()) {
      //alarm_h_min == 0
      whls.resetStates();
      if (alarm_h_min == 0) {
#ifdef SAMOVAR_USE_POWER
        SendMsg("Сработал датчик захлеба! Понижаем " + (String)PWR_MSG + " с " + (String)target_power_volt, ALARM_MSG);
        //Снижаем напряжение регулятора
#ifdef SAMOVAR_USE_SEM_AVR
        //Если регулятор мощности - снижаем на 100 ватт
        set_current_power(target_power_volt - 100);
#else
        //Если регулятор напряжения - снижаем на 5 вольт
        set_current_power(target_power_volt - 5);
#endif
#endif
        //Запускаем таймер
        alarm_h_min = millis() + 60000;
      } else if (millis() >= alarm_h_min) {
        //подождали, сбросим таймер
        alarm_h_min = 0;
      }
    } else {
      alarm_h_min = 0;
    }
  }
#endif

  //  //Срабатывание датчика недостаточного уровня воды в парогене (LUA pin) 5)
  //  nbkls.tick();
  //  if (nbkls.isHolded()) {
  //    SendMsg(("Не достаточно воды в парогенераторе! Остановка"), WARNING_MSG);
  //    run_nbk_program(CAPACITY_NUM * 2);
  //  }

  //Превышение уставки по давлению - мощность снижаем на 10 Вт и ждём 10 сек. 2)
  if (pressure_value >= program[ProgramNum].TempSensor) {
    if (d_s_time_min == 0) {
      //Снижаем напряжение регулятора
#ifdef SAMOVAR_USE_SEM_AVR
      //Если регулятор мощности - снижаем на 10 ватт
      set_current_power(target_power_volt - 10);
#else
      //Если регулятор напряжения - снижаем на 3 вольта
      set_current_power(target_power_volt - 3);
#endif
      SendMsg(("Высокое давление! Понижаем " + (String)PWR_MSG + " с " + (String)target_power_volt), WARNING_MSG);
      d_s_time_min = millis() + 10 * 1000;
    } else {
      if (d_s_time_min >= millis()) {
        d_s_time_min = 0;
      }
    }
  } else {
    d_s_time_min = 0;
  }

  if (TankSensor.avgTemp >= SamSetup.DistTemp) {
    SendMsg(("Т куба выше Т, заданной в настройках! Остановка"), WARNING_MSG);
    run_nbk_program(CAPACITY_NUM * 2);
  }

  vTaskDelay(10 / portTICK_PERIOD_MS);
}

//H;3;0;3000;24\nS;18;0;2400;24\nT;20;0;0;24\nP;0;20;-100;24\nW;0;0;0;24\n
void set_nbk_program(String WProgram) {
  char c[500];
  WProgram.toCharArray(c, 500);
  char *pair = strtok(c, ";");
  //String MeshTemplate;
  int i = 0;
  while (pair != NULL and i < CAPACITY_NUM * 2) {
    program[i].WType = pair;  // Тип программы
    pair = strtok(NULL, ";");
    program[i].Speed = atof(pair);  //Скорость отбора
    pair = strtok(NULL, ";");
    program[i].capacity_num = atoi(pair); // Целевое давление
    pair = strtok(NULL, ";");
    program[i].Power = atof(pair); // Коррекция мощности
    pair = strtok(NULL, "\n");
    program[i].TempSensor = atof(pair); // Максимальное давление
    i++;
    ProgramLen = i;
    pair = strtok(NULL, ";");
    if ((!pair || pair == NULL || pair[0] == 13) and i < CAPACITY_NUM * 2) {
      program[i].WType = "";
      break;
    }
  }
}

String get_nbk_program() {
  String Str = "";
  int k = CAPACITY_NUM * 2;
  for (uint8_t i = 0; i < k; i++) {
    if (program[i].WType == "") {
      i = CAPACITY_NUM * 2 + 1;
    } else {
      Str += program[i].WType + ";";
      Str += (String)program[i].Speed + ";";
      Str += (String)(int)program[i].capacity_num + ";";
      Str += (String)(int)program[i].Power + ";";
      Str += (String)program[i].TempSensor + "\n";
    }
  }
  return Str;
}
