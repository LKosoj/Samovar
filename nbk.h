#include <Arduino.h>
#include "Samovar.h"

void reset_sensor_counter(void);
void nbk_finish();
void check_power_error();
void set_power_mode(String Mode);
void set_power(bool On);
void set_current_power(float Volt);
void create_data();
void open_valve(bool Val, bool msg);
void set_pump_pwm(float duty);
void set_pump_speed_pid(float temp);
void SendMsg(const String& m, MESSAGE_TYPE msg_type);
bool check_boiling();
void set_buzzer(bool fl);
void set_water_temp(float duty);
String getValue(String data, char separator, int index);
void run_nbk_program(uint8_t num);
bool set_stepper_target(uint16_t spd, uint8_t direction, uint32_t target);
float i2c_get_liquid_rate_by_step(int StepperSpeed);
float i2c_get_speed_from_rate(float volume_per_hour);
float i2c_get_liquid_volume();
uint16_t get_stepper_speed(void);
bool set_stepper_target(uint16_t spd, uint8_t direction, uint32_t target);
void MqttSendMsg(String Str, const char *chart );

struct {
  float avgSpeed;
  float totalVolume;
  uint32_t startTime;
  uint32_t lastVolumeUpdate;
} stats;


// Описание алгоритма работы
// 1) Прогрев на мощности 3000 Вт с подачей браги 3 л/ч до температуры пара 85 гр.Ц.
// 3) Стабилизация 1200 сек, с подачей браги 18 л/ч на мощности 2400 Вт. После чего запоминаем температуру внизу колонны Тн.
// 4) Увеличение подачи браги, до 20 л/ч ступенями 0.1 л/ч каждых 5 сек, далее 0.05 л/ч каждых 5 сек, пока температура внизу колонны не просядет на 0.5 гр.Ц от Тн.
// 5) Каждых 5 сек. пока давление не достигнет 20 мм.рт.ст. наращивается мощность ступенями по 5 Вт и если просадка температуры от запомненной Тн внизу колонны менее 0.5 гр.Ц наращивается подача браги ступенями по 0.05 л/ч. В конце убавляем мощность на 100 Вт.
// 6) Работа. Раз в 5 сек: Если Твнизу<Тн-0.5 гр.Ц то уменьшаем подачу браги на 0.05 л/ч, если Твнизу>Тн то увеличиваем подачу браги на 0.05 л/ч.

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

#if defined(USE_PRESSURE_XGZ) || defined(USE_PRESSURE_1WIRE) || defined(USE_PRESSURE_MPX)
#else
  SendMsg(("Управление НБК не поддерживается вашим оборудованием!"), NOTIFY_MSG);
  nbk_finish();
  return;
#endif

#if defined(SAMOVAR_USE_POWER)
#else
  SendMsg(("Управление НБК не поддерживается вашим оборудованием!"), NOTIFY_MSG);
  nbk_finish();
  return;
#endif


  if (!PowerOn) {
    start_pressure = 0;
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
    set_stepper_target(i2c_get_speed_from_rate(program[ProgramNum].Speed), 0, 2147483640);
  }

  uint32_t currentTime = millis();
  if (currentTime - stats.lastVolumeUpdate >= 1000) { // Обновляем каждую секунду
    float currentSpeed = i2c_get_liquid_rate_by_step(get_stepper_speed()); // л/ч
    float seconds = (float)(currentTime - stats.lastVolumeUpdate) / 1000.0;
    stats.totalVolume += (currentSpeed / 3600.0) * seconds;
    stats.lastVolumeUpdate = currentTime;
  }

  //Обрабатываем программу НБК
  if (program[ProgramNum].WType == "H" && SteamSensor.avgTemp >= 85) {
    //Если Т пара больше 85 градусов, переходим к стабилизации НБК
    run_nbk_program(ProgramNum + 1);
  } else if (program[ProgramNum].WType == "S" && begintime <= millis()) {
    //Если прошло 1200 секунд с начала стабилизации НБК, переходим к программе выхода на заданную скорость отбора
    run_nbk_program(ProgramNum + 1);
  } else if (program[ProgramNum].WType == "T") {
    //превысили предельные значения, идем дальше или температура упала ниже дельты
    if (start_pressure > 0 || program[2].Speed < i2c_get_speed_from_rate(get_stepper_speed()) || (d_s_temp_prev - NBK_TEMPERATURE_DELTA <= TankSensor.avgTemp && TankSensor.avgTemp > 80)) {
      run_nbk_program(ProgramNum + 1);
    }
    //Если достигли заданной скорости и вышли за пределы Т внизу колонны, переходим к программе выхода на заданное давление
    run_nbk_program(ProgramNum + 1);
  } else if (program[ProgramNum].WType == "P") {
    // && pressure_value > program[ProgramNum].capacity_num) {
    if (start_pressure > 0 || program[2].Speed < i2c_get_speed_from_rate(get_stepper_speed())) {
      //Если достигли заданного давления, переходим к рабочей программе
      run_nbk_program(ProgramNum + 1);
    }
  } else if (program[ProgramNum].WType == "W") {
    if (pressure_value >= start_pressure + 2 || SteamSensor.avgTemp > 98.1) {
      //превышено давление или температура пара - завершаем работу
      run_nbk_program(ProgramNum + 1);
    }
  }

  //управляющие воздействия для текущей программы
  if (program[ProgramNum].WType == "T") {
    //сохраняем максимальное давление, если не будет давления захлеба - будем считать его максимальным
    if (bme_prev_pressure < pressure_value) {
      bme_prev_pressure = pressure_value;
    }

    if (t_min <= millis()) {
      float spdinc;
      if (program[ProgramNum].Speed < i2c_get_speed_from_rate(get_stepper_speed())) {
        spdinc = NBK_PUMP_INCREMENT * 2;
      } else {
        spdinc = NBK_PUMP_INCREMENT;
      }
      set_stepper_target(get_stepper_speed() + i2c_get_speed_from_rate(spdinc / 1000.00 + 0.0001), 0, 2147483640);
      t_min = millis() + 5 * 1000;
    }
  } else if (program[ProgramNum].WType == "P") {
    //сохраняем максимальное давление, если не будет давления захлеба - будем считать его максимальным
    if (bme_prev_pressure < pressure_value) {
      bme_prev_pressure = pressure_value;
    }

    if (t_min <= millis()) {
#ifdef SAMOVAR_USE_SEM_AVR
      //Если регулятор мощности - повышаем на 5 ватт
      if (target_power_volt + 5 <= program[0].Power) {
        set_current_power(target_power_volt + 5);
      }
#else
      //Если регулятор напряжения - повышаем на 1 вольт
      if (target_power_volt + 1 <= program[0].Power) {
        set_current_power(target_power_volt + 1);
      }
#endif
      if (TankSensor.avgTemp >= d_s_temp_prev - NBK_TEMPERATURE_DELTA) {
        set_stepper_target(get_stepper_speed() + i2c_get_speed_from_rate(float(NBK_PUMP_INCREMENT) / 1000.00 + 0.0001), 0, 2147483640);
      }
      t_min = millis() + 5 * 1000;
    }
  } else if (program[ProgramNum].WType == "W") {
    if (t_min <= millis()) {
      if (TankSensor.avgTemp < d_s_temp_prev - NBK_TEMPERATURE_DELTA) {
        set_stepper_target(get_stepper_speed() - i2c_get_speed_from_rate(float(NBK_PUMP_INCREMENT) / 1000.00 - 0.0001), 0, 2147483640);
      } else if (TankSensor.avgTemp > d_s_temp_prev) {
        set_stepper_target(get_stepper_speed() + i2c_get_speed_from_rate(float(NBK_PUMP_INCREMENT) / 1000.00 + 0.0001), 0, 2147483640);
      }
      t_min = millis() + 5 * 1000;
    }
    if (alarm_c_min <= millis()) {
      uint8_t inc = 0;
      if (start_pressure > 0 && pressure_value > start_pressure) {
#ifdef SAMOVAR_USE_POWER
#ifdef SAMOVAR_USE_SEM_AVR
        //Если регулятор мощности - снижаем на 10 ватт
        inc = -10;
#else
        //если регулятор напряжения - снижаем на 2 вольта
        inc = -2;
#endif
#endif
      } else if (start_pressure - pressure_value > 2) {
#ifdef SAMOVAR_USE_POWER
#ifdef SAMOVAR_USE_SEM_AVR
        //Если регулятор мощности - повышаем на 5 ватт
        inc = 5;
#else
        //если регулятор напряжения - повышаем на 1 вольт
        inc = 1;
#endif
#endif
      }
      if (inc != 0 && target_power_volt + inc <= program[0].Power) {
        set_current_power(target_power_volt + inc);
      }
      alarm_c_min = millis() + 20 * 1000;
    }
  }

  vTaskDelay(200 / portTICK_PERIOD_MS);
}

void nbk_finish() {
  SendMsg(("Работа НБК завершена"), NOTIFY_MSG);
  set_power(false);
  set_stepper_target(0, 0, 0);
  reset_sensor_counter();
  if (fileToAppend) {
    fileToAppend.close();
  }
  // Вычислить и отправить статистику
  uint32_t totalTime = (millis() - stats.startTime) / 1000; // в секундах
  if (totalTime > 0) {
    stats.avgSpeed = (stats.totalVolume * 3600.0) / (float)totalTime;
  } else {
    stats.avgSpeed = 0;
  }
  
  String summary = "Итоги работы НБК:\n";
  summary += "Средняя скорость: " + String(stats.avgSpeed, 2) + " л/ч\n";
  summary += "Текущая мощность: " + String(target_power_volt) + "\n";
  summary += "Максимальное давление: " + String(bme_prev_pressure) + " мм.рт.ст.\n";
  summary += "Общий объем: " + String(stats.totalVolume, 2) + " л\n";
  summary += "Время работы: " + String(totalTime / 3600.0, 2) + " ч";
  
  SendMsg(summary, NOTIFY_MSG);
}

void run_nbk_program(uint8_t num) {
  if (Samovar_Mode != SAMOVAR_NBK_MODE || !PowerOn) return;
  if (startval == 4000) startval = 4001;
  ProgramNum = num;
  begintime = 0;
  t_min = 0;
  alarm_c_min = 0;
  msgfl = true;

  if (num == 0) {
    stats.startTime = millis();
    stats.avgSpeed = 0;
    stats.totalVolume = 0;
  }

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

  //Изменяем на заданную мощность
#ifdef SAMOVAR_USE_POWER
#ifdef SAMOVAR_USE_SEM_AVR
  if (program[ProgramNum].Power > 0 && program[ProgramNum].Power < 500) {
#else
  if (program[ProgramNum].Power > 0 && program[ProgramNum].Power < 50) {
#endif
    if (target_power_volt + program[ProgramNum].Power <= program[0].Power) {
      set_current_power(target_power_volt + program[ProgramNum].Power);
    }
  } else {
    set_current_power(program[ProgramNum].Power);
  }
#endif
  //Запомним Тниз = d_s_temp_prev
  if (program[ProgramNum].Temp > 0) {
    d_s_temp_prev = program[ProgramNum].Temp;
  } else {
    d_s_temp_prev = TankSensor.avgTemp;
  }

  if (program[ProgramNum].WType == "S") {
    begintime = millis() + 1200 * 1000;
    //Если задана скорость - устанавливаем или абсолютнуюю или относительную
    if (program[ProgramNum].Speed != 0) {
      if (abs(program[ProgramNum].Speed) < 3 && (i2c_get_speed_from_rate(get_stepper_speed()) + program[ProgramNum].Speed) <= program[2].Speed) {
        set_stepper_target(i2c_get_speed_from_rate(i2c_get_speed_from_rate(get_stepper_speed()) + program[ProgramNum].Speed), 0, 2147483640);
      } else {
        set_stepper_target(i2c_get_speed_from_rate(program[ProgramNum].Speed), 0, 2147483640);
      }
    }
  } else if (program[ProgramNum].WType == "T") {
    //Запомним Тниз = d_s_temp_prev
    d_s_temp_prev = TankSensor.avgTemp;
    begintime = 0;
  } else if (program[ProgramNum].WType == "P") {
    //Если задана скорость - устанавливаем или абсолютнуюю или относительную
    if (program[ProgramNum].Speed != 0) {
      if (abs(program[ProgramNum].Speed) < 3 && (i2c_get_speed_from_rate(get_stepper_speed()) + program[ProgramNum].Speed) <= program[2].Speed) {
        set_stepper_target(i2c_get_speed_from_rate(i2c_get_speed_from_rate(get_stepper_speed()) + program[ProgramNum].Speed), 0, 2147483640);
      } else {
        set_stepper_target(i2c_get_speed_from_rate(program[ProgramNum].Speed), 0, 2147483640);
      }
    }
  } else if (program[ProgramNum].WType == "W") {
    //Если задана температура, установим Тниз = d_s_temp_prev
    if (program[ProgramNum].Temp > 0) {
      d_s_temp_prev = program[ProgramNum].Temp;
    }
    //Если задана скорость - устанавливаем или абсолютнуюю или относительную
    if (program[ProgramNum].Speed != 0) {
      if (abs(program[ProgramNum].Speed) < 3 && (i2c_get_speed_from_rate(get_stepper_speed()) + program[ProgramNum].Speed) <= program[2].Speed) {
        set_stepper_target(i2c_get_speed_from_rate(i2c_get_speed_from_rate(get_stepper_speed()) + program[ProgramNum].Speed), 0, 2147483640);
      } else {
        set_stepper_target(i2c_get_speed_from_rate(program[ProgramNum].Speed), 0, 2147483640);
      }
    }
    //Определяем давление захлеба
    //Если задано в программе - берем из программы
    if (program[ProgramNum].capacity_num > 0) {
      start_pressure = program[ProgramNum].capacity_num;
    } else {
      //Если не поймали захлеб - берем максимальное, которое было, иначе давление захлеба - 2
      if (start_pressure == 0) {
        //Если перешли на программу W а давление = 0, берем максимальное, которое было
        if (program[ProgramNum].WType == "W") {
          start_pressure = bme_prev_pressure;
        }
      } else {
        //Если программа W, скинем Дн на 2 единицы и будем использовать его для ориентира
        if (program[ProgramNum].WType == "W") {
          start_pressure = start_pressure - 2;
        }
      }
    }
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
  //Устанавливаем ШИМ для насоса в зависимости от температуры воды
  if (valve_status) {
    if (ACPSensor.avgTemp > SamSetup.SetACPTemp && ACPSensor.avgTemp > WaterSensor.avgTemp) set_pump_speed_pid(SamSetup.SetWaterTemp + 3);
    else
      set_pump_speed_pid(WaterSensor.avgTemp);
  }
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
#else
    SendMsg(("Критическая температура воды!"), WARNING_MSG);
#endif
    alarm_t_min = millis() + 60000;
  }

  //Контролируем Т пара>98.1 3)
  if ((SteamSensor.avgTemp >= 98.1) && PowerOn) {
    SendMsg(("Брага зкончилась! Остановка"), WARNING_MSG);
    run_nbk_program(CAPACITY_NUM * 2);
  }

  //Работа датчика захлёба - мощность снижаем на 100 Вт и ждём 15 сек. 1)
  //Если используется датчик уровня флегмы в голове
#ifdef USE_HEAD_LEVEL_SENSOR
  if (PowerOn) {
    whls.tick();
    if (whls.isHolded()) {
      //Получили давление захлеба
      start_pressure = pressure_value;

      SendMsg("Сработал датчик захлеба! Дн=" + (String)start_pressure + "; С=" + (String)i2c_get_speed_from_rate(get_stepper_speed()) + "; М=" + (String)target_power_volt, ALARM_MSG);
      //set_alarm();

      whls.resetStates();
      if (alarm_h_min <= millis()) {
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
        //снижаем скорость подачи
        set_stepper_target(get_stepper_speed() - i2c_get_speed_from_rate(float(NBK_PUMP_INCREMENT) / 1000.00 - 0.0001), 0, 2147483640);
        //Запускаем таймер
        alarm_h_min = millis() + 15 * 1000;
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
  if (start_pressure != 0 && pressure_value >= start_pressure) {
    if (d_s_time_min <= millis()) {
      //Снижаем напряжение регулятора
#ifdef SAMOVAR_USE_POWER
        SendMsg("Сработал датчик захлеба! Понижаем " + (String)PWR_MSG + " с " + (String)target_power_volt, ALARM_MSG);
        //Снижаем напряжение регулятора
#ifdef SAMOVAR_USE_SEM_AVR
        //Если регулятор мощности - снижаем на 25 ватт
        set_current_power(target_power_volt - 25);
#else
        //Если регулятор напряжения - снижаем на 3 вольта
        set_current_power(target_power_volt - 3);
#endif
      SendMsg(("Высокое давление! Понижаем " + (String)PWR_MSG + " с " + (String)target_power_volt), WARNING_MSG);
#endif

      d_s_time_min = millis() + 10 * 1000;
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

//H;3;0;3000;0\nS;18;0;2400;0\nT;20;0;0;0\nP;0;20;-100;0\nW;0;0;0;0\n
//program[0].Power - максимальная мощность
//program[2].Speed - максимальная скорость
//start_pressure - давление захлеба
void set_nbk_program(String WProgram) {
  char c[500] = {0};
  WProgram.toCharArray(c, 500);
  char* pair = strtok(c, ";");
  //String MeshTemplate;
  int i = 0;
  while (pair != NULL and i < CAPACITY_NUM * 2) {
    program[i].WType = pair;  // Тип программы
    pair = strtok(NULL, ";");
    program[i].Speed = atof(pair);  //Скорость отбора
    pair = strtok(NULL, ";");
    program[i].capacity_num = atoi(pair);  // Целевое давление
    pair = strtok(NULL, ";");
    program[i].Power = atof(pair);  // Коррекция мощности
    pair = strtok(NULL, "\n");
    program[i].Temp = atof(pair);  // Температура Тн
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
      Str += (String)program[i].Temp + "\n";
    }
  }
  return Str;
}
