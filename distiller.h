#include <Arduino.h>
#include "Samovar.h"
#include "quality.h"

/**
 * @brief Завершить процесс дистилляции, выключить нагрев и сбросить счетчики.
 */
void distiller_finish();

/**
 * @brief Установить режим питания.
 * @param Mode Режим (строка)
 */
void set_power_mode(String Mode);

/**
 * @brief Включить или выключить питание.
 * @param On true — включить, false — выключить
 */
void set_power(bool On);

/**
 * @brief Создать файл с данными текущей сессии дистилляции.
 */
void create_data();

/**
 * @brief Открыть или закрыть клапан.
 * @param Val true — открыть, false — закрыть
 * @param msg true — отправить сообщение
 */
void open_valve(bool Val, bool msg);

/**
 * @brief Установить ШИМ для насоса.
 * @param duty Значение ШИМ
 */
void set_pump_pwm(float duty);

/**
 * @brief Установить скорость насоса по ПИД-регулированию.
 * @param temp Целевая температура
 */
void set_pump_speed_pid(float temp);

/**
 * @brief Установить программу дистилляции из строки.
 * @param WProgram Строка с программой
 */
void set_dist_program(String WProgram);

/**
 * @brief Перейти к строке программы дистилляции с номером num.
 * @param num Номер строки программы
 */
void run_dist_program(uint8_t num);

/**
 * @brief Получить текущую программу дистилляции в виде строки.
 * @return Строка с программой
 */
String get_dist_program();

/**
 * @brief Сбросить прогноз времени.
 */
void resetTimePredictor();

/**
 * @brief Обновить прогноз времени.
 */
void updateTimePredictor();

/**
 * @brief Получить расчетное оставшееся время.
 * @return Оставшееся время (минуты)
 */
float calculateRemainingTime();

/**
 * @brief Проверить аварийные ситуации дистиллятора.
 */
void check_alarm_distiller();

/**
 * @brief Включить или выключить буззер.
 * @param On true — включить, false — выключить
 */
void set_buzzer(bool On);

/**
 * @brief Установить текущую мощность.
 * @param power Мощность (Ватт)
 */
void set_current_power(float power);

/**
 * @brief Установить скорость насоса.
 * @param speed Скорость
 * @param msg true — отправить сообщение
 */
void set_pump_speed(float speed, bool msg);

/**
 * @brief Установить температуру тела колонны.
 */
void set_body_temp();

/**
 * @brief Получить объем жидкости.
 * @return Объем (мл)
 */
int get_liquid_volume();

/**
 * @brief Получить статус самовара в виде строки.
 * @return Статус (строка)
 */
String get_Samovar_Status();

/**
 * @brief Получить скорость по расходу.
 * @param rate Расход
 * @return Скорость
 */
float get_speed_from_rate(float rate);

/**
 * @brief Получить расчетную спиртуозность по температуре.
 * @param t Температура
 * @return Спиртуозность (%)
 */
float get_alcohol(float t);

/**
 * @brief Получить расчетную спиртуозность пара по температуре.
 * @param t Температура
 * @return Спиртуозность пара (%)
 */
float get_steam_alcohol(float t);

/**
 * @brief Установить емкость.
 * @param cap Номер емкости
 */
void set_capacity(uint8_t cap);

/**
 * @brief Сбросить счетчик датчиков.
 */
void reset_sensor_counter();

/**
 * @brief Проверить ошибки питания и обработать их.
 */
void check_power_error();

/**
 * @brief Установить емкость (дублирующая функция).
 * @param cap Номер емкости
 */
void set_capacity(uint8_t cap);

#ifdef USE_MQTT
#include "SamovarMqtt.h"
#endif

#ifdef USE_WATER_PUMP
/**
 * @brief Проверить, идет ли кипячение.
 * @return true если кипит, иначе false
 */
bool check_boiling();
#endif

/**
 * @brief Отправить сообщение пользователю.
 * @param m Текст сообщения
 * @param msg_type Тип сообщения
 */
void SendMsg(const String& m, MESSAGE_TYPE msg_type);

/**
 * @brief Структура для прогнозирования времени процесса дистилляции.
 */
struct TimePredictor {
    unsigned long startTime;           ///< Время начала процесса
    float initialAlcohol;              ///< Начальное содержание спирта
    float initialTemp;                 ///< Начальная температура
    float lastTemp;                    ///< Последняя температура
    float tempChangeRate;              ///< Скорость изменения температуры
    unsigned long lastUpdateTime;      ///< Время последнего обновления
    float predictedTotalTime;          ///< Прогнозируемое общее время (мин)
    float remainingTime;               ///< Оставшееся время (мин)
};

TimePredictor timePredictor = {0, 0, 0, 0, 0, 0, 0, 0};

/**
 * @brief Основной цикл обработки процесса дистилляции.
 *
 * Вызывает обработку текущего этапа, обновляет прогноз времени, контролирует аварии и переходы между этапами.
 */
void distiller_proc() {
//    SendMsg("Статус: " + String(SamovarStatusInt) + 
//            ", Режим: " + String(Samovar_Mode) + 
//            ", PowerOn: " + String(PowerOn), NOTIFY_MSG);
    
  if (SamovarStatusInt != 1000) return;

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
    SendMsg(("Включен нагрев дистиллятора"), NOTIFY_MSG);
    run_dist_program(0);
    d_s_temp_prev = WaterSensor.avgTemp;
#ifdef SAMOVAR_USE_POWER
    digitalWrite(RELE_CHANNEL4, SamSetup.rele4);
#endif
    // Инициализируем систему прогнозирования
    resetTimePredictor();
  }

  // Обновляем прогноз времени
  updateTimePredictor();

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


  //Если Т в кубе больше 90 градусов и включено напряжение и DistTimeF > 0, проверяем, что DistTimeF минут температура в кубе не меняется от последнего заполненного значения больше, чем на 0.1 градус
  if (TankSensor.avgTemp > 90 && PowerOn && SamSetup.DistTimeF > 0) {
    if (abs(TankSensor.avgTemp - d_s_temp_finish) > 0.1) {
      d_s_temp_finish = TankSensor.avgTemp;
      d_s_time_min = millis();
    } else if ((millis() - d_s_time_min) > SamSetup.DistTimeF * 60 * 1000) {
      SendMsg(("В кубе не осталось спирта"), NOTIFY_MSG);
      distiller_finish();
    }
  }

  // // Добавляем оценку качества
  // static unsigned long lastQualityCheck = 0;
  // if (millis() - lastQualityCheck >= 5000) { // Проверяем каждые 5 секунд
  //   lastQualityCheck = millis();
    
  //   QualityParams quality = getQualityAssessment();
    
  //   // Если качество низкое, отправляем предупреждение
  //   if (quality.overallScore < 70) {
  //     SendMsg(("Внимание! Качество отбора снижено: " + String(quality.overallScore, 1) + 
  //             "%. " + quality.recommendation), WARNING_MSG);
  //   }
    
  //   // Если качество критически низкое, можно автоматически корректировать процесс
  //   if (quality.overallScore < 50) {
  //     // Автоматическая коррекция процесса
  //     if (quality.stabilityScore < 50) {
  //       // Уменьшаем мощность для стабилизации
  //       set_current_power(target_power_volt - 5);
  //     }
  //   }
  // }

  vTaskDelay(10 / portTICK_PERIOD_MS);
}

void distiller_finish() {
#ifdef SAMOVAR_USE_POWER
  digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);
#endif
  SendMsg(("Дистилляция завершена. Общее время: " + String(int((millis() - timePredictor.startTime) / 60000)) + " мин."), NOTIFY_MSG);
  set_power(false);
  reset_sensor_counter();
}


void check_alarm_distiller() {
  //сбросим паузу события безопасности
  if (alarm_t_min > 0 && alarm_t_min <= millis()) alarm_t_min = 0;

  if (!valve_status) {
    if (ACPSensor.avgTemp >= MAX_ACP_TEMP - 5) {
      set_buzzer(true);
      open_valve(true, true);
    }
    else if (TankSensor.avgTemp >= OPEN_VALVE_TANK_TEMP && PowerOn) {
      set_buzzer(true);
      open_valve(true, true);
    }
  }

  if (!PowerOn && !is_self_test && valve_status && WaterSensor.avgTemp <= SamSetup.SetWaterTemp - DELTA_T_CLOSE_VALVE) {
    open_valve(false, true);
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
    SendMsg(("Аварийное отключение! Прекращена подача воды."), ALARM_MSG);
  }
#endif

  if ((WaterSensor.avgTemp >= ALARM_WATER_TEMP - 5) && PowerOn && alarm_t_min == 0) {
    set_buzzer(true);
    //Если уже реагировали - надо подождать 30 секунд, так как процесс инерционный
    SendMsg(("Критическая температура воды!"), WARNING_MSG);

#ifdef SAMOVAR_USE_POWER
    check_power_error();
    if (WaterSensor.avgTemp >= ALARM_WATER_TEMP) {
      set_buzzer(true);
      SendMsg("Критическая температура воды! Понижаем " + (String)PWR_MSG + " с " + (String)target_power_volt, ALARM_MSG);
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
  vTaskDelay(10 / portTICK_PERIOD_MS);
}

void run_dist_program(uint8_t num) {
  ProgramNum = num;

  if (program[num].WType.length() > 0) {
    SendMsg("Переход к строке программы №" + (String)(num + 1), NOTIFY_MSG);
    // Сбрасываем прогноз при переходе к новой программе
    resetTimePredictor();
  } else {
    SendMsg("Выполнение программ закончилось, продолжение отбора", NOTIFY_MSG);
  }

  //запоминаем текущие значения температур
  SteamSensor.StartProgTemp = SteamSensor.avgTemp;
  PipeSensor.StartProgTemp = PipeSensor.avgTemp;
  WaterSensor.StartProgTemp = WaterSensor.avgTemp;
  TankSensor.StartProgTemp = TankSensor.avgTemp;

  if (num > 0) {
    set_capacity(program[num - 1].capacity_num);
    if (program[num - 1].WType.length() > 0) {
#ifdef SAMOVAR_USE_POWER
#ifdef SAMOVAR_USE_SEM_AVR
      if (abs(program[num - 1].Power) > 400 && program[num - 1].Power > 0) {
#else
      if (abs(program[num - 1].Power) > 40 && program[num - 1].Power > 0) {
#endif
        set_current_power(program[num - 1].Power);
      } else if (program[num - 1].Power != 0) {
        set_current_power(target_power_volt + program[num - 1].Power);
      }
#endif
    }
  }

}

void set_dist_program(String WProgram) {
  char c[500] = {0};
  WProgram.toCharArray(c, 500);
  char *pair = strtok(c, ";");
  //String MeshTemplate;
  int i = 0;
  while (pair != NULL && i < CAPACITY_NUM * 2) {
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
    if ((!pair || pair == NULL || pair[0] == 13) && i < CAPACITY_NUM * 2) {
      program[i].WType = "";
      break;
    }
  }
}

String get_dist_program() {
  String Str = "";
  int k = CAPACITY_NUM * 2;
  for (uint8_t i = 0; i < k; i++) {
    if (program[i].WType.length() == 0) {
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

void resetTimePredictor() {
    timePredictor.startTime = millis();
    timePredictor.initialAlcohol = get_alcohol(TankSensor.avgTemp);
    timePredictor.initialTemp = TankSensor.avgTemp;
    timePredictor.lastTemp = TankSensor.avgTemp;
    timePredictor.lastUpdateTime = millis();
    timePredictor.tempChangeRate = 0;
    timePredictor.predictedTotalTime = 0;
    timePredictor.remainingTime = 0;
}

void updateTimePredictor() {
    unsigned long currentTime = millis();
    float currentTemp = TankSensor.avgTemp;
    float currentAlcohol = get_alcohol(currentTemp);
    
    // Обновляем скорость изменения температуры
    unsigned long timeDelta = (currentTime - timePredictor.lastUpdateTime) / 1000; // в секундах
    if (timeDelta >= 60) { // обновляем каждую минуту
        timePredictor.tempChangeRate = (currentTemp - timePredictor.lastTemp) / (timeDelta / 60.0); // градусов в минуту
        timePredictor.lastTemp = currentTemp;
        timePredictor.lastUpdateTime = currentTime;
        
        // Прогнозируем общее время на основе текущих данных
        float remainingAlcoholDelta = 0;
        float targetTemp = 0;
        
        if (program[ProgramNum].WType == "T") {
            targetTemp = program[ProgramNum].Speed;
            if (timePredictor.tempChangeRate > 0) {
                float tempRemaining = targetTemp - currentTemp;
                timePredictor.remainingTime = tempRemaining / timePredictor.tempChangeRate;
            }
        } 
        else if (program[ProgramNum].WType == "A" || program[ProgramNum].WType == "S") {
            float targetAlcohol = program[ProgramNum].Speed;
            if (program[ProgramNum].WType == "S") {
                targetAlcohol *= get_alcohol(TankSensor.StartProgTemp);
            }
            remainingAlcoholDelta = currentAlcohol - targetAlcohol;
            
            // Прогнозируем на основе скорости изменения спирта
            float alcoholChangeRate = (timePredictor.initialAlcohol - currentAlcohol) / 
                                    ((currentTime - timePredictor.startTime) / 60000.0); // % в минуту
            
            if (alcoholChangeRate > 0) {
                timePredictor.remainingTime = remainingAlcoholDelta / alcoholChangeRate;
            }
        }
        
        // Обновляем общее прогнозируемое время
        float elapsedMinutes = (currentTime - timePredictor.startTime) / 60000.0;
        timePredictor.predictedTotalTime = elapsedMinutes + timePredictor.remainingTime;
        
        // Отправляем информацию о прогнозе
        //String msg = "Прогноз: осталось " + String(int(timePredictor.remainingTime)) + 
        //            " мин. Всего: " + String(int(timePredictor.predictedTotalTime)) + " мин.";
        //SendMsg(msg, NOTIFY_MSG);
    }
}

float calculateRemainingTime() {
    return timePredictor.remainingTime;
}
