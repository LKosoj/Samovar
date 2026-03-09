#ifndef __SAMOVAR_NBK_H_
#define __SAMOVAR_NBK_H_

// Отформатировано так, чтоб сворачивать блоки для меньшего пользования скроллом
 #include <Arduino.h>
 #include "Samovar.h"
 #include "state/globals.h"
 #include "app/alarm_control.h"
 #include "io/actuators.h"
 #include "io/power_control.h"
 #include "support/safe_parse.h"
 #include "support/process_math.h"
// Новые веянья, platformio вестимо, сворачиваем
 /**
 * @brief Сбросить счетчик датчиков.
 */
 void reset_sensor_counter(void);

 /**
 * @brief Завершить работу НБК, отправить статистику, выключить нагрев и подачу.
 */
 void nbk_finish();

 #ifndef SAMOVAR_USE_POWER
 void set_current_power(float Volt){return;};
#endif
 /**
 * @brief Создать файл с данными текущей сессии.
 */
 void create_data();

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
 * @brief Отправить сообщение пользователю.
 * @param m Текст сообщения
 * @param msg_type Тип сообщения
 */
 void SendMsg(const String& m, MESSAGE_TYPE msg_type);

 /**
 * @brief Установить температуру воды.
 * @param duty Целевая температура
 */
 void set_water_temp(float duty);

 /**
 * @brief Получить значение из строки по разделителю.
 * @param data Строка
 * @param separator Разделитель
 * @param index Индекс значения
 * @return Значение (строка)
 */
 String getValue(const String& data, char separator, int index);

 /**
 * @brief Перейти к строке программы с номером num, инициализировать этап.
 * @param num Номер строки программы
 */
 void run_nbk_program(uint8_t num);

 /**
 * @brief Установить целевую скорость шагового двигателя.
 * @param spd Скорость
 * @param direction Направление
 * @param target Целевое значение
 * @return true если успешно
 */
 bool set_stepper_target(uint16_t spd, uint8_t direction, uint32_t target);

 /**
 * @brief Получить расход жидкости по скорости шагового двигателя.
 * @param StepperSpeed Скорость шагового
 * @return Расход (л/ч)
 */
 float i2c_get_liquid_rate_by_step(int StepperSpeed);

 /**
 * @brief Получить скорость шагового двигателя по расходу.
 * @param volume_per_hour Расход (л/ч)
 * @return Скорость шагового
 */
 float i2c_get_speed_from_rate(float volume_per_hour);

 /**
 * @brief Получить текущий объем жидкости.
 * @return Объем (л)
 */
 float i2c_get_liquid_volume();

 /**
 * @brief Получить текущую скорость шагового двигателя.
 * @return Скорость
 */
 uint16_t get_stepper_speed(void);

 /**
 * @brief Отправить MQTT-сообщение.
 * @param Str Строка
 * @param chart Канал/тип
 */

 /**
 * @brief Основной цикл обработки этапов НБК. Вызывает обработку текущего этапа и проверку аварий.
 */
 void nbk_proc();

 /**
 * @brief Обработка этапа разгона (H). Устанавливает параметры, контролирует переход к следующему этапу.
 */
 void handle_nbk_stage_heatup();

 /**
 * @brief Обработка этапа ручной настройки (S). Устанавливает параметры, контролирует захлёб и переход.
 */
 void handle_nbk_stage_manual();

 /**
 * @brief Обработка этапа оптимизации (O). Реализует цикл оптимизации параметров.
 */
 void handle_nbk_stage_optimization();

 /**
 * @brief Обработка этапа работы (W). Реализует цикл регулирования подачи и мощности, обработку захлёба.
 */
 void handle_nbk_stage_work();
 
 /**
 * @brief Проверка критических аварий (перегрев, недостаточное охлаждение). Останавливает процесс при необходимости.
 * @return true если была авария и процесс завершён
 */
 bool check_nbk_critical_alarms();

 /**
 * @brief Централизованная обработка захлёба: сброс параметров, сообщение, завершение или пауза.
 * @param msg Сообщение пользователю
 * @param finish true — завершить процесс, false — только пауза
 * @param pause_ms Длительность паузы (мс), если требуется
 */
 void handle_overflow(const String& msg, bool finish = true, uint32_t pause_ms = 0);

 String get_nbk_program();

struct { // Структура для статистики
  float avgSpeed;
  float totalVolume;
  uint32_t startTime;
  uint32_t lastVolumeUpdate;
} stats;
// === Новые и переименованные параметры по ТЗ ===
#define NBK_COLUMN_INERTIA_DEFAULT 180 // Инерция колонны (Ин), по умолчанию 180 секунд 
#define NBK_OVERFLOW_PRESSURE_DEFAULT 40  // Давление захлёба (Дз), по умолчанию 40 мм рт.ст.
#define NBK_TN_DEFAULT 98.5 // Тн — нижний предел температуры барды, по умолчанию 98.5°C
#define NBK_DT_DEFAULT 0.5 // Допустимая просадка Т барды (dT), по умолчанию 0.5°C
#define NBK_DM_DEFAULT 100 // шаг регулирования мощности
#define NBK_DP_DEFAULT 0.5 // шаг регулирования подачи
#define NBK_TP_DEFAULT 81 // предельная Т пара
#define NBK_OPERATING_RANGE 100 // отладочная, процент использования Mo и Po из оптимизации при переходе в работу.
// Параметры из Samovar_ini.h
// #define NBK_MULT_PAUSE_OVERFLOW 2 // Количество инерций в качестве паузы после захлёба
// #define USE_NBK_DELTA_PRESSURE // Включение коррекции температуры барды по давлению в бардоотводчике
// #define NBK_PUMP_LIMIT 30 // максимальная производительность насоса браги для Оптимизации, л/ч

uint16_t nbk_column_inertia = NBK_COLUMN_INERTIA_DEFAULT; // Инерция колонны (Ин)
float nbk_overflow_pressure = NBK_OVERFLOW_PRESSURE_DEFAULT; // Давление захлёба (Дз)
float nbk_M = 0; // М — текущая мощность, Вт
float nbk_M_max = 3200; // Максимальная мощность ТЭН-а в режиме НБК
float nbk_Mo = 0;   // Мо — оптимальная мощность, Вт
float nbk_dM = NBK_DM_DEFAULT; // dM — шаг регулирования мощности
float nbk_P = 0;    // П — текущая подача браги, л/ч
float nbk_Po = 0;   // По — оптимальная подача, л/ч
float nbk_dP = 0; // dП — шаг регулирования подачи
float nbk_Tb = 0; // Тб — текущая температура барды
float nbk_Tn = NBK_TN_DEFAULT; // Тн — нижний предел температуры барды
float nbk_Tp = 0; // Тп — температура пара
float nbk_Tvody = 0; // Тводы — температура воды
float nbk_dD = 0; // dД — поправка к Тн по давлению (используется при #define USE_NBK_DELTA_PRESSURE)
float nbk_dT = NBK_DT_DEFAULT; // Допустимая просадка Т барды (dT)
float nbk_Tp_lim = NBK_TP_DEFAULT; // Предел температуры пара на этапе Работа
// === Переменные для этапа оптимизации ===
uint8_t nbk_opt_iter = 0;
uint32_t nbk_opt_next_time = 0;
uint32_t time_speed = 0; // для подсчета литража
bool nbk_opt_in_progress = false;
// === Переменные для этапа работы ===
uint32_t nbk_work_next_time = 0;
bool nbk_work_in_pause = false;
bool workrun = true; // флаг необходимости снижения мощности в Работе после захлёба
uint8_t nbk_work_pause_stage = 0;
float nbk_Mo_temp = 0,
      nbk_Po_temp = 0; // временное хранилище на случай пропуска оптимизации
bool manual_overflow = false; // флаг начавшегося захлёба в работе
bool noDZ_message_sent = false; // флаг сообщения об отсутствии ДЗ

//  === Прототипы функций для этапов ===
void handle_nbk_stage_heatup();
void handle_nbk_stage_manual();
void handle_nbk_stage_optimization();
void handle_nbk_stage_work();
bool check_nbk_critical_alarms();

bool overflow(){
  if (PowerOn) {
   #ifdef USE_HEAD_LEVEL_SENSOR
      whls.tick(); 
      if (whls.isHolded()) {
        whls.resetStates();  
        SendMsg("Захлёб по ДЗ", WARNING_MSG);
        return (true);
      }
   #endif
    if (pressure_value >= nbk_overflow_pressure) {
      SendMsg("Захлёб по ДД", WARNING_MSG);
      return (true); 
    } else return (false);
 } else return (false);
}

void SetSpeed(float Speed) { // Прокладка для подсчета статистики
  uint32_t now = millis();
  if (time_speed == 0) {
    time_speed = now;
  }
  if (program[ProgramNum].WType != "H") { //Иначе в среднюю скорость попадает 1л/ч прогрева
    stats.totalVolume += i2c_get_liquid_rate_by_step(get_stepper_speed()) * (now - time_speed) / 3600000.0;
  }
  time_speed = now;
  if (Speed == 0) set_stepper_target(0, 0, 0); 
  else
  set_stepper_target(i2c_get_speed_from_rate(Speed), 0, 2147483640);
}

float toPower(float value) { // конвертер в мощность ( V | W ) => W
 #ifdef SAMOVAR_USE_SEM_AVR
    return value; // если нечто иное возвращаем неизменным
 #else
      float R = SamSetup.HeaterResistant > 1 ? SamSetup.HeaterResistant : 18;
      return value * value / R; //если от kvic или RVMK пересчитываем в P
 #endif
  }
 #ifndef SAMOVAR_USE_SEM_AVR
float SQRT(float num) { // компилируем только по необходимости
  if (num < 0) {
    return -1.0f;
  }
  if (num == 0) {
      return 0.0f;
  }
  float guess = num;
  float prev_guess;
  do {
    prev_guess = guess;
    guess = (guess + num / guess) / 2;
    delay(3);
  } while (abs(guess - prev_guess) > 0.001);
  return guess;
}
 #endif
float fromPower(float value) { // конвертер из мощности: W => ( V | W )
 #ifdef SAMOVAR_USE_SEM_AVR
    return value;
 #else
      static float prev_W = 0.0f;
      static float prev_V = 0.0f;
      if (value != prev_W) {
          prev_W = value;
          float R = SamSetup.HeaterResistant > 1 && SamSetup.HeaterResistant < 200 ? SamSetup.HeaterResistant : 18;
          prev_V = SQRT(value * R);
      }
      return prev_V;
 #endif
  }


// === Тоже Проверка критических аварий === в основном по воде
void check_alarm_nbk() {// вызывается из Samovar.ino, надо разобраться что оставить, я уже кой чего поубирал
  // Если нагрев выключен и это не самотестирование и вода включена и Т воды на 20 и более гр. ниже уставки
  if (!PowerOn && !is_self_test && valve_status && WaterSensor.avgTemp <= TARGET_WATER_TEMP - 20) {
    open_valve(false, true); //призыв закрыть воду либо закрытие клапана
    #ifdef USE_WATER_PUMP
        if (pump_started) set_pump_pwm(0); // стоп водяной насос
    #endif
  }

  if (!PowerOn) { // нет нагрева - больше ничего не проверяем
    return;
  }

  //сбросим паузу события безопасности
  if (alarm_t_min > 0 && alarm_t_min <= millis()) alarm_t_min = 0;

  // Если нагрев включен и вода и температура в бардоотвотчике больше уставки включения воды
  if (PowerOn && !valve_status && TankSensor.avgTemp >= OPEN_VALVE_TANK_TEMP) {
    open_valve(true, true); // призыв включить воду или открытие клапана
  }

  // регулируем водяной насос
  #ifdef USE_WATER_PUMP
  //Устанавливаем ШИМ для насоса в зависимости от температуры воды
  if (valve_status) { // если вода включена
    // Если Т в ТСА больше предела и Т в ТСА больше Т воды (?) - крутим водяной насос усерднее, будто Т воды выше на 3 гр.
    if (ACPSensor.avgTemp > SamSetup.SetACPTemp && ACPSensor.avgTemp > WaterSensor.avgTemp) set_pump_speed_pid(SamSetup.SetWaterTemp + 3);
    else
      set_pump_speed_pid(WaterSensor.avgTemp); // иначе крутим как обычно
  }
  #endif
  
 #ifdef USE_WATERSENSOR
  //Проверим, что вода подается
  if (WFAlarmCount > WF_ALARM_COUNT && PowerOn) { //датчик протока сломался уже
    set_buzzer(true);
    //Если с водой проблемы - выключаем нагрев, пусть оператор разбирается
    sam_command_sync = SAMOVAR_POWER;
    SendMsg(("Аварийное отключение! Прекращена подача воды."), ALARM_MSG);
  }
 #endif
  if ((WaterSensor.avgTemp >= ALARM_WATER_TEMP - 5) && PowerOn && alarm_t_min == 0) {
    set_buzzer(true);
    SendMsg(("Критическая температура воды!"), WARNING_MSG);
    alarm_t_min = millis() + 60000;
  }
  
  vTaskDelay(10 / portTICK_PERIOD_MS);
}


// Окончание программы НБК
void nbk_finish() {
  SendMsg("Работа НБК завершена", NOTIFY_MSG);
  SetSpeed(0);
  // Вычислить и отправить статистику
  uint32_t totalTime = (millis() - stats.startTime) / 1000; // в секундах
  if (totalTime > 0) {
    stats.avgSpeed = (stats.totalVolume * 3600.0) / (float)totalTime;
  } else {
    stats.avgSpeed = 0;
  }
  
  String summary = "";//"Итоги работы НБК:\n";
  summary += "Пропущено браги " + String(stats.totalVolume, 2) + " л ";
  summary += "со средней скоростью " + String(stats.avgSpeed, 2) + " л/ч ";
  summary += "за: " + String(totalTime / 3600.0, 2) + " ч.";
  SendMsg(summary, NOTIFY_MSG);
  delay(1000);
  set_power(false);
  reset_sensor_counter();
  if (fileToAppend) {
    fileToAppend.close();
  }
}

void set_nbk_program(String WProgram) {
  for (int j = 0; j < CAPACITY_NUM * 2; j++) {
    program[j].WType = "";
  }
  ProgramLen = 0;

  if (WProgram.length() == 0) return;
  if (WProgram.length() > MAX_PROGRAM_INPUT_LEN) {
    SendMsg("Ошибка программы: слишком длинная строка (nbk)", ALARM_MSG);
    return;
  }

  char input[MAX_PROGRAM_INPUT_LEN + 1] = {0};
  copyStringSafe(input, WProgram);

  int i = 0;
  char* saveLine = nullptr;
  char* line = strtok_r(input, "\n", &saveLine);
  while (line && i < CAPACITY_NUM * 2) {
    size_t lineLen = strlen(line);
    while (lineLen > 0 && (line[lineLen - 1] == '\r' || line[lineLen - 1] == ' ' || line[lineLen - 1] == '\t')) {
      line[--lineLen] = '\0';
    }
    if (lineLen == 0) {
      line = strtok_r(NULL, "\n", &saveLine);
      continue;
    }

    char* saveTok = nullptr;
    char* tokType = strtok_r(line, ";", &saveTok);
    char* tokSpeed = strtok_r(NULL, ";", &saveTok);
    char* tokPower = strtok_r(NULL, ";", &saveTok);
    char* tokExtra = strtok_r(NULL, ";", &saveTok);

    float speed = 0;
    float power = 0;
    bool ok = tokType && tokType[0] != '\0' &&
              tokSpeed && tokPower &&
              !tokExtra &&
              parseFloatSafe(tokSpeed, speed) &&
              parseFloatSafe(tokPower, power);

    if (!ok) {
      for (int j = 0; j < CAPACITY_NUM * 2; j++) program[j].WType = "";
      ProgramLen = 0;
      SendMsg("Ошибка программы: неверный формат строки nbk", ALARM_MSG);
      return;
    }

    program[i].WType = tokType;
    program[i].Speed = speed;
    program[i].Power = power;

    i++;
    ProgramLen = i;
    line = strtok_r(NULL, "\n", &saveLine);
  }

  if (i < CAPACITY_NUM * 2) {
    program[i].WType = "";
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
      Str += (String)(int)program[i].Power + "\n";
    }
  }
  return Str;
}

#endif
