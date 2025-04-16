#include <Arduino.h>
#include "Samovar.h"

/**
 * @brief Сбросить счетчик датчиков.
 */
void reset_sensor_counter(void);

/**
 * @brief Завершить работу НБК, отправить статистику, выключить нагрев и подачу.
 */
void nbk_finish();

/**
 * @brief Проверить ошибки питания и обработать их.
 */
void check_power_error();

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
 * @brief Установить текущую мощность.
 * @param Volt Мощность (Ватт)
 */
void set_current_power(float Volt);

/**
 * @brief Создать файл с данными текущей сессии.
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
 * @brief Отправить сообщение пользователю.
 * @param m Текст сообщения
 * @param msg_type Тип сообщения
 */
void SendMsg(const String& m, MESSAGE_TYPE msg_type);

/**
 * @brief Проверить, идет ли кипячение.
 * @return true если кипит, иначе false
 */
bool check_boiling();

/**
 * @brief Включить или выключить буззер.
 * @param fl true — включить, false — выключить
 */
void set_buzzer(bool fl);

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
String getValue(String data, char separator, int index);

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
void MqttSendMsg(const String &Str, const char *chart );

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

struct {
  float avgSpeed;
  float totalVolume;
  uint32_t startTime;
  uint32_t lastVolumeUpdate;
} stats;

// === Описание алгоритма работы ===
//
// 1) Разгон (H):
//    - Мощность = 3000 Вт, подача = 1 л/ч (если не задано).
//    - Включение разгонного ТЭНа.
//    - Переход к следующему этапу при достижении T пара >= 85°C.
//    - При захлёбе — останов процесса.
//
// 2) Ручная настройка (S):
//    - Мощность = 500 Вт, подача = 1 л/ч (если не задано).
//    - Переход по кнопке или по времени.
//    - При захлёбе — останов процесса.
//    - Передача текущих М и П в оптимизацию.
//
// 3) Оптимизация (O):
//    - Ждать Ин/2 перед стартом.
//    - Цикл: ждать Ин, корректировать М и П по алгоритму (см. ТЗ).
//    - При захлёбе — завершение оптимизации, переход к работе.
//    - Сохраняются оптимальные Мо и По.
//
// 4) Работа (W):
//    - М = Мо, П = По (или из строки).
//    - Цикл: ждать Ин, корректировать подачу по температуре барды.
//    - При захлёбе — пауза, корректировка Мо, восстановление параметров.
//
// 5) Аварийные ситуации (везде, кроме S):
//    - T пара > 95°C — "Кончилась брага", останов процесса.
//    - Tтса > 60°C или Tводы > 70°C более 60 сек — "Недостаточное охлаждение", останов процесса.
//
// 6) Все этапы, аварии и переходы сопровождаются сообщениями.


// === Новые и переименованные параметры по ТЗ ===

// Инерция колонны (Ин), по умолчанию 180 секунд
#define NBK_COLUMN_INERTIA_DEFAULT 180
uint16_t nbk_column_inertia = NBK_COLUMN_INERTIA_DEFAULT; // секунд

// Допустимая просадка Т барды (dT), по умолчанию 0.5°C
#define NBK_DT_DEFAULT 0.5
float nbk_dT = NBK_DT_DEFAULT;

// Давление захлёба (Дз), по умолчанию 40 мм рт.ст.
#define NBK_OVERFLOW_PRESSURE_DEFAULT 40
float nbk_overflow_pressure = NBK_OVERFLOW_PRESSURE_DEFAULT;

// М — текущая мощность, Вт
float nbk_M = 0;
// Мо — оптимальная мощность, Вт
float nbk_Mo = 0;
// dM — шаг регулирования мощности
float nbk_dM = 5; // по умолчанию 5 Вт

// П — текущая подача браги, л/ч
float nbk_P = 0;
// По — оптимальная подача, л/ч
float nbk_Po = 0;
// dП — шаг регулирования подачи
float nbk_dP = 0.05; // по умолчанию 0.05 л/ч

// Тб — текущая температура барды
float nbk_Tb = 0;
// Тн — температура окончания, по умолчанию 98.5°C
#define NBK_TN_DEFAULT 98.5
float nbk_Tn = NBK_TN_DEFAULT;
// dT — допустимая просадка Тб от Тн (см. выше)
// Тп — температура пара
float nbk_Tp = 0;
// Тводы — температура воды
float nbk_Tvody = 0;
// Д — текущее давление
float nbk_D = 0;
// dД — поправка к Тн по давлению (используется при #define USE_NBK_DELTA_PRESSURE)
float nbk_dD = 0;
// ДУФ — датчик уровня флегмы (логический флаг)
bool nbk_DUF = false;

// === Переменные для этапа оптимизации ===
static uint8_t nbk_opt_iter = 0;
static uint32_t nbk_opt_next_time = 0;
static bool nbk_opt_in_progress = false;

// === Переменные для этапа работы ===
static uint32_t nbk_work_next_time = 0;
static bool nbk_work_in_pause = false;
static uint8_t nbk_work_pause_stage = 0;

void IRAM_ATTR isrNBKLS_TICK() {
  nbkls.tick();
}

// === Прототипы функций для этапов ===
void handle_nbk_stage_heatup();
void handle_nbk_stage_manual();
void handle_nbk_stage_optimization();
void handle_nbk_stage_work();
bool check_nbk_critical_alarms();

void nbk_proc() {
  // Проверка критических аварий (true — авария, процесс завершён)
  if (check_nbk_critical_alarms()) return;

  // Выбор и обработка этапа
  String wtype = program[ProgramNum].WType;
  if (wtype == "H") {
    handle_nbk_stage_heatup();
    return;
  } else if (wtype == "S") {
    handle_nbk_stage_manual();
    return;
  } else if (wtype == "O") {
    handle_nbk_stage_optimization();
    return;
  } else if (wtype == "W") {
    handle_nbk_stage_work();
    return;
  }
  // Для других этапов — оставить старую обработку или добавить новые функции
  vTaskDelay(10 / portTICK_PERIOD_MS);
}

// === Реализация функций этапов ===
// =================================

void handle_nbk_stage_heatup() {
  // Логика этапа разгона (H)
  // Если мощность и подача не заданы — дефолты
  if (program[ProgramNum].Power <= 0) {
    program[ProgramNum].Power = 3000;
  }
  if (program[ProgramNum].Speed <= 0) {
    program[ProgramNum].Speed = 1.0;
  }
  nbk_M = program[ProgramNum].Power;
  nbk_P = program[ProgramNum].Speed;
  set_power(true); // Включаем разгонный ТЭН
  set_current_power(nbk_M);
  set_stepper_target(i2c_get_speed_from_rate(nbk_P), 0, 2147483640);
  if (SteamSensor.avgTemp >= 85) {
    run_nbk_program(ProgramNum + 1);
    return;
  }
  vTaskDelay(200 / portTICK_PERIOD_MS);
}

void handle_nbk_stage_manual() {
  // Логика этапа ручной настройки (S)
  if (program[ProgramNum].Power <= 0) {
    program[ProgramNum].Power = 500;
  }
  if (program[ProgramNum].Speed <= 0) {
    program[ProgramNum].Speed = 1.0;
  }
  nbk_M = program[ProgramNum].Power;
  nbk_P = program[ProgramNum].Speed;
  set_power(true);
  set_current_power(nbk_M);
  set_stepper_target(i2c_get_speed_from_rate(nbk_P), 0, 2147483640);
  // Захлёб на этапе S
#ifdef USE_HEAD_LEVEL_SENSOR
  if (PowerOn && whls.isHolded()) {
    handle_overflow("Захлёб колонны! Остановка этапа ручной настройки.", true, 0);
    return;
  }
#endif
  // Переход по кнопке или по времени (если реализовано)
  if (begintime <= millis()) {
    run_nbk_program(ProgramNum + 1);
    return;
  }
  vTaskDelay(200 / portTICK_PERIOD_MS);
}

void handle_nbk_stage_optimization() {
  // Логика этапа оптимизации (O)
  if (!nbk_opt_in_progress) {
    // Ждем окончания паузы перед стартом
    if (begintime > 0 && begintime > millis()) {
      vTaskDelay(200 / portTICK_PERIOD_MS);
      return;
    }
    nbk_opt_in_progress = true;
    nbk_opt_iter = 0;
    nbk_opt_next_time = millis();
    SendMsg("Оптимизация начата", NOTIFY_MSG);
  }
  if (nbk_opt_in_progress && millis() >= nbk_opt_next_time) {
    nbk_Tb = TankSensor.avgTemp;
    // Проверка на захлёб (датчик уровня флегмы или давление)
    bool overflow = false;
#ifdef USE_HEAD_LEVEL_SENSOR
    if (whls.isHolded()) overflow = true;
#endif
    if (pressure_value >= nbk_overflow_pressure) overflow = true;
    if (overflow) {
      if (nbk_opt_iter == 0) {
        handle_overflow("Заданные параметры слишком велики — оптимизация невозможна. Останов.", true, 0);
      } else {
        SendMsg("Оптимизация завершена. Найденные параметры: " + String(nbk_Mo) + " Вт, " + String(nbk_Po) + " л/ч", NOTIFY_MSG);
        handle_overflow("Захлёб колонны во время оптимизации. Переход к этапу 'Работа'.", true, 0);
      }
      nbk_opt_in_progress = false;
      nbk_opt_iter = 0;
      // Переход к следующему этапу через паузу 3*Ин
      begintime = millis() + 3 * nbk_column_inertia * 1000;
      run_nbk_program(ProgramNum + 1);
      return;
    }
    // Основной цикл оптимизации
    if (nbk_Tb >= nbk_Tn) {
      nbk_Po = nbk_P;
      nbk_Mo = nbk_M;
      nbk_P += nbk_dP;
      SendMsg("Оптимизация: Тб >= Тн, увеличиваем подачу. Итерация " + String(nbk_opt_iter+1), NOTIFY_MSG);
    } else {
      nbk_P = nbk_P * 0.8;
      nbk_M += nbk_dM;
      SendMsg("Оптимизация: Тб < Тн, увеличиваем мощность. Итерация " + String(nbk_opt_iter+1), NOTIFY_MSG);
    }
    set_current_power(nbk_M);
    set_stepper_target(i2c_get_speed_from_rate(nbk_P), 0, 2147483640);
    nbk_opt_iter++;
    if (nbk_opt_iter >= 10) {
      SendMsg("Оптимизация завершена по лимиту итераций. Найденные параметры: " + String(nbk_Mo) + " Вт, " + String(nbk_Po) + " л/ч", NOTIFY_MSG);
      handle_overflow("Захлёб колонны во время оптимизации. Переход к этапу 'Работа'.", true, 0);
      nbk_opt_in_progress = false;
      nbk_opt_iter = 0;
      begintime = millis() + 3 * nbk_column_inertia * 1000;
      run_nbk_program(ProgramNum + 1);
      return;
    }
    nbk_opt_next_time = millis() + nbk_column_inertia * 1000;
  }
  vTaskDelay(200 / portTICK_PERIOD_MS);
}

void handle_nbk_stage_work() {
  // Логика этапа работы (W)
  if (!nbk_work_in_pause && nbk_work_next_time == 0) {
    // Инициализация этапа: М=Мо, П=По, если заданы, иначе из строки
    nbk_M = (nbk_Mo > 0) ? nbk_Mo : (program[ProgramNum].Power > 0 ? program[ProgramNum].Power : 500);
    nbk_P = (nbk_Po > 0) ? nbk_Po : (program[ProgramNum].Speed > 0 ? program[ProgramNum].Speed : 1.0);
    set_current_power(nbk_M);
    set_stepper_target(i2c_get_speed_from_rate(nbk_P), 0, 2147483640);
    SendMsg("Начало этапа 'Работа'. Мощность: " + String(nbk_M) + " Вт, Подача: " + String(nbk_P) + " л/ч", NOTIFY_MSG);
    nbk_work_next_time = millis() + nbk_column_inertia * 1000;
  }
  if (!nbk_work_in_pause && millis() >= nbk_work_next_time) {
    nbk_Tb = TankSensor.avgTemp;
    float dD = nbk_dD; // поправка по давлению, если используется
    // Проверка на захлёб
    bool overflow = false;
#ifdef USE_HEAD_LEVEL_SENSOR
    if (whls.isHolded()) overflow = true;
#endif
    if (pressure_value >= nbk_overflow_pressure) overflow = true;
    if (overflow) {
      handle_overflow("Захлёб колонны! Остановка подачи и нагрева.", true, 3 * nbk_column_inertia * 1000);
      return;
    }
    // Основной цикл: корректировка подачи
    if (nbk_Tb < nbk_Tn - nbk_dT + dD) {
      nbk_P -= nbk_dP / 10.0;
      if (nbk_P < 0) nbk_P = 0;
      set_stepper_target(i2c_get_speed_from_rate(nbk_P), 0, 2147483640);
      SendMsg("Работа: Тб < Тн-dT+dД, уменьшаем подачу: " + String(nbk_P) + " л/ч", NOTIFY_MSG);
    }
    nbk_work_next_time = millis() + nbk_column_inertia * 1000;
  }
  // Обработка паузы после захлёба
  if (nbk_work_in_pause && millis() >= nbk_work_next_time) {
    if (nbk_work_pause_stage == 1) {
      // После 3*Ин: корректируем Мо, восстанавливаем параметры
      nbk_Mo = nbk_Mo - nbk_dM / 10.0;
      if (nbk_Mo < 0) nbk_Mo = 0;
      nbk_M = nbk_Mo;
      nbk_P = nbk_Po;
      set_current_power(nbk_M);
      set_stepper_target(i2c_get_speed_from_rate(nbk_P), 0, 2147483640);
      SendMsg("Работа: после захлёба, корректируем Мо и восстанавливаем параметры.", NOTIFY_MSG);
      nbk_work_pause_stage = 2;
      nbk_work_next_time = millis() + 2 * nbk_column_inertia * 1000;
    } else if (nbk_work_pause_stage == 2) {
      // После 2*Ин: продолжаем работу
      nbk_work_in_pause = false;
      nbk_work_pause_stage = 0;
      nbk_work_next_time = millis() + nbk_column_inertia * 1000;
      SendMsg("Работа: продолжаем цикл после паузы.", NOTIFY_MSG);
    }
  }
  vTaskDelay(200 / portTICK_PERIOD_MS);
}

// === Проверка критических аварий ===
bool check_nbk_critical_alarms() {
  static uint32_t overheat_start_time = 0;
  bool is_manual = (program[ProgramNum].WType == "S");
  if (!is_manual) {
    if (SteamSensor.avgTemp > 95.0) {
      SendMsg("Кончилась брага! Остановка процесса.", ALARM_MSG);
      nbk_M = 0;
      nbk_P = 0;
      set_power(false);
      set_stepper_target(0, 0, 0);
      run_nbk_program(CAPACITY_NUM * 2);
      vTaskDelay(200 / portTICK_PERIOD_MS);
      return true;
    }
    if (ACPSensor.avgTemp > 60.0 || WaterSensor.avgTemp > 70.0) {
      if (overheat_start_time == 0) overheat_start_time = millis();
      if (millis() - overheat_start_time > 60000) {
        SendMsg("Недостаточное охлаждение! Остановка процесса.", ALARM_MSG);
        nbk_M = 0;
        nbk_P = 0;
        set_power(false);
        set_stepper_target(0, 0, 0);
        run_nbk_program(CAPACITY_NUM * 2);
        vTaskDelay(200 / portTICK_PERIOD_MS);
        return true;
      }
    } else {
      overheat_start_time = 0;
    }
  }
  return false;
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

  // Сообщение о переходе между этапами
  if (num == 0) {
    stats.startTime = millis();
    stats.avgSpeed = 0;
    stats.totalVolume = 0;
    SendMsg("Запуск программы НБК. Этап 1", NOTIFY_MSG);
  } else if (num == CAPACITY_NUM * 2) {
    nbk_finish();
    return;
  } else {
    SendMsg("Переход к строке программы №" + (String)(num + 1) + ". Тип: " + program[num].WType, NOTIFY_MSG);
  }

  // === Передача параметров Мо и По после оптимизации ===
  if (ProgramNum > 0 && program[ProgramNum - 1].WType == "O") {
    // Если оптимизация завершена, передаем найденные параметры в этап работы
    if (nbk_Mo > 0 && nbk_Po > 0) {
      SendMsg("Передача оптимальных параметров в этап 'Работа': Мо=" + String(nbk_Mo) + " Вт, По=" + String(nbk_Po) + " л/ч", NOTIFY_MSG);
    } else {
      SendMsg("Оптимизация не дала результата, используются параметры по умолчанию.", WARNING_MSG);
    }
  }

  // === Передача параметров в оптимизацию при переходе с S ===
  if (ProgramNum > 0 && program[ProgramNum - 1].WType == "S") {
    nbk_Mo = nbk_M;
    nbk_Po = nbk_P;
    SendMsg("Передача текущих параметров в оптимизацию: Мо=" + String(nbk_Mo) + " Вт, По=" + String(nbk_Po) + " л/ч", NOTIFY_MSG);
  }

  // === Захлёб на этапе ручной настройки (S) ===
  if (program[ProgramNum].WType == "S") {
#ifdef USE_HEAD_LEVEL_SENSOR
    if (PowerOn && whls.isHolded()) {
      nbk_M = 0;
      nbk_P = 0;
      set_power(false);
      set_stepper_target(0, 0, 0);
      SendMsg("Захлёб колонны! Остановка этапа ручной настройки.", ALARM_MSG);
      run_nbk_program(CAPACITY_NUM * 2);
      return;
    }
#endif
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
    if (program[ProgramNum].Power <= 0) {
      program[ProgramNum].Power = 500;
    }
    if (program[ProgramNum].Speed <= 0) {
      program[ProgramNum].Speed = 1.0;
    }
    nbk_M = program[ProgramNum].Power;
    nbk_P = program[ProgramNum].Speed;
    set_power(true);
    set_current_power(nbk_M);
    set_stepper_target(i2c_get_speed_from_rate(nbk_P), 0, 2147483640);
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
  if (WProgram.length() == 0) return;
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

// === Централизованная обработка захлёба ===
void handle_overflow(const String& msg, bool finish, uint32_t pause_ms) {
  nbk_M = 0;
  nbk_P = 0;
  set_power(false);
  set_stepper_target(0, 0, 0);
  SendMsg(msg, ALARM_MSG);
  if (finish) {
    run_nbk_program(CAPACITY_NUM * 2);
  } else if (pause_ms > 0) {
    // Для этапа W: пауза и переход к восстановлению
    nbk_work_in_pause = true;
    nbk_work_pause_stage = 1;
    nbk_work_next_time = millis() + pause_ms;
  }
}

