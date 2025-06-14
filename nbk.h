// Отформатировано так, чтоб сворачивать блоки для меньшего пользования скроллом
 #include <Arduino.h>
 #include "Samovar.h"
// Новые веянья, platformio вестимо, сворачиваем
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
  stats.totalVolume += i2c_get_liquid_rate_by_step(get_stepper_speed()) * (millis() - time_speed) / 3600000.0;
  if (Speed == 0) set_stepper_target(0, 0, 0); 
  else
  set_stepper_target(i2c_get_speed_from_rate(Speed), 0, 2147483640);
 time_speed = millis();
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
  } while (abs(guess - prev_guess) > 0.001);
  return guess;
}
 #endif
float fromPower(float value) { // конвертер из мощности: W => ( V | W )
 #ifdef SAMOVAR_USE_SEM_AVR
    return value;
 #else
      float R = SamSetup.HeaterResistant > 1 ? SamSetup.HeaterResistant : 18;
      return SQRT(value * R);
 #endif
  }

void nbk_proc() { //главный цикл НБК
  if (check_nbk_critical_alarms()) return; // Проверка критических аварий (true — авария, процесс завершён)
  // Обновление переменных из настроек (на случай, если пользователь их изменил в процессе)
  nbk_column_inertia =  SamSetup.NbkIn > 1 ? SamSetup.NbkIn : NBK_COLUMN_INERTIA_DEFAULT;
  nbk_dT = SamSetup.NbkDelta > 0 ? SamSetup.NbkDelta : NBK_DT_DEFAULT;
  nbk_Tn = SamSetup.DistTemp > 0 ? SamSetup.DistTemp : NBK_TN_DEFAULT;
  nbk_overflow_pressure = SamSetup.NbkOwPress > 1 ? SamSetup.NbkOwPress : NBK_OVERFLOW_PRESSURE_DEFAULT;
  nbk_dM = SamSetup.NbkDM > 1 ? SamSetup.NbkDM : NBK_DM_DEFAULT; 
  nbk_dP = SamSetup.NbkDP > 0 ? SamSetup.NbkDP : NBK_DP_DEFAULT; 
  nbk_Tp_lim = SamSetup.NbkSteamT > 80 ? SamSetup.NbkSteamT : NBK_TP_DEFAULT;
  nbk_M_max = SamSetup.HeaterResistant > 1 ? (230 * 230 / SamSetup.HeaterResistant) : nbk_M_max; // Максимальная мощность ТЭН-а в режиме НБК
  // TODO Samovar_ini.h
  //  1) убрать NBK_TEMPERATURE_DELTA (переехало в сетап)
  //  2) заменить
  //  Параметры для НБК
  // #define NBK_MULT_PAUSE_OVERFLOW 2 // количество инерций в качестве паузы после захлёба 
  // #define NBK_PUMP_LIMIT 30 // максимальная производительность насоса браги для Оптимизации, л/ч 
  // #define NBK_DEFAULT_PROGRAM "H;1;0\nS;10;2000\nO;0;0\nW;0;0\n" //программа НБК по-умолчанию (ватты)
  // //#define NBK_DEFAULT_PROGRAM "H;1;0\nS;10;167\nO;0;0\nW;0;0\n" //программа НБК по-умолчанию (вольты, для ТЭН 14 Ом)
  // //#define USE_NBK_DELTA_PRESSURE // Включение коррекции температуры барды по давлению в бардоотводчике

  String wtype = program[ProgramNum].WType; // Выбор и обработка этапа

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
  vTaskDelay(10 / portTICK_PERIOD_MS);
}
// === Реализация функций этапов ===
// =================================
// 1) "Разгон" - разгон парогенератора до Тп > 75°C. 
void handle_nbk_stage_heatup() {
    nbk_Tp = SteamSensor.avgTemp; // обновляем
  if (startval == 4000) run_nbk_program(0);   //Запуск программ
  //- разгон парогенератора до Тп > 75°C.
  if (nbk_Tp >= 75) {
    run_nbk_program(ProgramNum + 1);
    return;
  }
  //Если захлёб (пользователь задал слишком большие М и П), М=0, П=0 (обнуляем нагрев и подачу), 
  //выводим сообщение "Захлёб колонны! Останов программы".
 if (overflow()){
    handle_overflow(
      " На прогреве заданы слишком большие " + String(PWR_MSG) + " и/или подача! Останов программы.", true, 0); 
}
  vTaskDelay(200 / portTICK_PERIOD_MS);
}
//2) "Ручная настройка" - определение Ин, Тн, Мо и По вручную (в инструкции)
 //Время не ограничено, переход к следующей строке по кнопке "Следующая программа", 
 //при переходе передаём в Оптимизацию текущие М и П.
void handle_nbk_stage_manual() { //Если захлёб, выводим сообщение "Захлёб колонны!", М=1/2, П=0 (обнуляем  подачу, половиним мощность).
  if (overflow() && !manual_overflow) {
      manual_overflow = true;
      nbk_P = 0;
      nbk_M = toPower(target_power_volt) / 2;
      set_current_power(fromPower(nbk_M));
      SetSpeed(0);
      SendMsg(" Подача прекращена, мощность снижаем в 2 раза.", ALARM_MSG); 
      vTaskDelay(200 / portTICK_PERIOD_MS);
      return;
  } else if (get_stepper_speed() > 0) manual_overflow = false;
  vTaskDelay(200 / portTICK_PERIOD_MS);
}
//3) "Оптимизация" - автоматическое определение Мо и По.
void handle_nbk_stage_optimization() {
  if (!nbk_opt_in_progress) { // Ждем 30 сек чтобы пользователь успел пропустить Оптимизацию если захочет, 
    //в этом случае передаём полученные от Ручной настройки М и П в Работу как Мо и По
    if ((begintime + 30000) > millis()) {
      vTaskDelay(200 / portTICK_PERIOD_MS);
      return;
    }

    #ifndef USE_HEAD_LEVEL_SENSOR //даём время пользователю задать вручную параметры в "Работе", если не задал - передадутся те, что были в Настройке
      if (!noDZ_message_sent) {
        SendMsg("Оптимизация невозможна - отсутствует датчик захлёба. Установите вручную нужные параметры в программе этапа Работа и нажмите кнопку Следующая программа. Автоматический переход к Работе произойдёт через 10 минут", ALARM_MSG);
      }
      noDZ_message_sent = true;
      if ((begintime + 600000) > millis()) {
        vTaskDelay(200 / portTICK_PERIOD_MS);
        return;
      }
      run_nbk_program(ProgramNum + 1);
      return;
    #endif

    nbk_opt_in_progress = true; // Пауза на пропуск Оптимизации закончена
    begintime = 0; // Сбрасываем отсчет для корректной обработки разницы окончания оптимизации, по захлёбу или нет
    
    // второй этап инициализации Оптимизации
    // Мо=0, По=0 М и П - из строки программы или по-умолчанию: М = разгоннная*0.3 П = 10 л/ч    
      nbk_Mo_temp = 0; //пропуск оптимизации не состоялся, сброс значений
      nbk_Po_temp = 0;     
      nbk_Mo = 0; //Мо=0, По=0
      nbk_Po = 0;
      //передаём в Оптимизацию текущие М и П. (те, что сложились после манипуляций пользователя в Настройке)
      nbk_M = toPower(target_power_volt) > 100 ? toPower(target_power_volt) : 0.3 * nbk_M_max; 
      nbk_P = get_stepper_speed() > 0 ? i2c_get_liquid_rate_by_step(get_stepper_speed()) : 10;
      nbk_M = program[ProgramNum].Power > 0 ? toPower(program[ProgramNum].Power) : nbk_M; // если только не заданы явно в строке
      nbk_P = program[ProgramNum].Speed > 0 ? program[ProgramNum].Speed : nbk_P;
     set_current_power(fromPower(nbk_M));
     SetSpeed(nbk_P);
     nbk_opt_next_time = millis() + nbk_column_inertia * NBK_MULT_PAUSE_OVERFLOW/3 * 1000; // Ждём время Ин (первая пауза)
     SendMsg("Оптимизация начата с: " + String(fromPower(nbk_M),0) + String(PWR_SIGN) + ",  " + String(nbk_P,1) + " л/ч ", NOTIFY_MSG); 
  }

  // Собственно цикл оптимизации
  if (nbk_opt_in_progress) {
     if (overflow() && !workrun) { // Если захлёб по ДЗ или ДД
        if (nbk_Mo == 0 && nbk_Po == 0) { 
          // Если захлёб на первых же итерациях  (когда Мо или По равны нулю)
          handle_overflow("Заданные параметры " + String(PWR_MSG) + " и Скорость слишком велики — оптимизация невозможна. Останов.", true, 0);
        } else {
          // Если захлёб после нескольких итераций (Мо или По найдены) - мы
          // оптимизировались. Переход к строке Работа через паузу MULT*Ин (для
          // успокоения колонны после захлёба)
          nbk_Po *= NBK_OPERATING_RANGE / 100; // отладочная корректировка после захлёба
          nbk_Mo *= NBK_OPERATING_RANGE / 100;
          SendMsg(" Оптимум: " + String(fromPower(nbk_Mo),0) + String(PWR_SIGN) + ",  " + 
          String(nbk_Po,1) + " л/ч", WARNING_MSG);
          run_nbk_program(ProgramNum + 1); // Сначала выставляем новую строку, потом пауза по захлёбу
          handle_overflow(
            "Оптимизация завершена.",
            false,NBK_MULT_PAUSE_OVERFLOW * nbk_column_inertia * 1000); // Переход к следующему этапу через паузу MULT*Ин
        }
        return;
     }

    if ( millis() >= nbk_opt_next_time ) {//Если пауза на инерцию вышла
    nbk_Tb = TankSensor.avgTemp;    
    // Ядро оптимизации
    // 3.3) если Тб >= Тн то (По=П, Мо=М, новая П = П + dП, переход на 3.1) //увеличили подачу, 
    // иначе (новые П = П*0.8, М = М + dM, переход на 3.1) // уменьшили подачу, увеличили мощность
    #ifdef USE_NBK_DELTA_PRESSURE
      if (pressure_value != -1) {
          nbk_dD = 0.00001913 * pressure_value * pressure_value + 0.03694 * pressure_value; // Поправка по давлению если включена в Samovar_ini.h
      }
    #endif
  
    nbk_M = toPower(target_power_volt);  // Актуализация текущих М и П с учетом возможных воздействий пользователя
    nbk_P = i2c_get_liquid_rate_by_step(get_stepper_speed());
    nbk_Tp = SteamSensor.avgTemp; // обновляем
    if ((nbk_Tb >= nbk_Tn + nbk_dD) && (nbk_Tp >= nbk_Tp_lim)) { // если по барде и пару всё Ок
      nbk_Po = nbk_P;
      nbk_Mo = nbk_M;
      nbk_P += nbk_dP;
      if (nbk_P > NBK_PUMP_LIMIT) {
        SendMsg("Достигнута предельная подача (" + String(nbk_Tp_lim) + "). Результат: " + String(fromPower(nbk_Mo),0) + String(PWR_SIGN), WARNING_MSG);
        run_nbk_program(ProgramNum + 1);
        return;
      }
      SendMsg("Оптимизация: Тб >= Тн ("+ String(nbk_Tn + nbk_dD,1) +"), увеличиваем подачу. Итерация " + String(nbk_opt_iter + 1), NOTIFY_MSG);
    } else {
      if ((nbk_M + nbk_dM) > nbk_M_max) {
        SendMsg("Достигнута предельная мощность. (" + String(nbk_M ,0) + "+dM>" + String(nbk_M_max,0)  + " Вт.). Результат: " + String(nbk_Po,1) + " л/ч.", WARNING_MSG);
        run_nbk_program(ProgramNum + 1);
        return;
      }
      nbk_P *= 0.9;
      nbk_M += nbk_dM;
      if (nbk_Tp < nbk_Tp_lim) {
        SendMsg("Оптимизация: Тп < Тп мин(" + String(nbk_Tp_lim,1) + "), увеличиваем " + String(PWR_MSG) + ". Итерация " + String(nbk_opt_iter + 1), NOTIFY_MSG);
      } else {
        SendMsg("Оптимизация: Тб < Тн(" + String(nbk_Tn + nbk_dD,1) + "), увеличиваем " + String(PWR_MSG) + ". Итерация " + String(nbk_opt_iter + 1), NOTIFY_MSG);
      }
    }
    set_current_power(fromPower(nbk_M));
    SetSpeed(nbk_P);
    nbk_opt_iter++;
    if (nbk_opt_iter >= 300) { 
      SendMsg("Достигнут лимит итераций. Результат: " + String(fromPower(nbk_Mo),0) + String(PWR_SIGN) + ", " + String(nbk_Po,1) + " л/ч", WARNING_MSG);
      run_nbk_program(ProgramNum + 1);
      return;
    }
    nbk_opt_next_time = millis() + nbk_column_inertia * 1000; // 3.1) Ждём опять время Ин
  }
  }
  vTaskDelay(200 / portTICK_PERIOD_MS);
}
//4) "Работа" - основной режим
void handle_nbk_stage_work() {
 //  4.1) Ждем время Ин - (первая пауза наследована от оптимизации Ин или MULT*Ин если был захлёб)
 //  4.1) если Тб<Тн-dT+dД, то П=П-dП/10, переход на 4.1)
 //  4.2) если захлёб, выводим сообщение "Захлёб колонны!", М=1/2, П=0, ждём время MULT*Ин. После этого Мо=Мо-dM/10. М=Мо, П=По, ждём время 2*Ин, переход на 4.1)
  if (!nbk_work_in_pause ) {// если не на паузе по захлёбу
    // 4.2) если захлёб, выводим сообщение "Захлёб колонны!", М=0, П=0, ждём время MULT*Ин. После этого Мо=Мо-dM/10. М=Мо, П=По, ждём время 2*Ин, переход на 4.1)
    if (overflow()) {
      handle_overflow(" Временное обнуление подачи и снижение нагрева.", false, NBK_MULT_PAUSE_OVERFLOW * nbk_column_inertia * 1000); //выводим сообщение "Захлёб колонны!", М=0, П=0, ждём время MULT*Ин.
      return;
    }      
    if (millis() >= nbk_work_next_time)  {// если пауза на инерцию вышла
    nbk_Tp = SteamSensor.avgTemp; // обновляем
    nbk_Tb = TankSensor.avgTemp;
    #ifdef USE_NBK_DELTA_PRESSURE
      if (pressure_value != -1) {
        nbk_dD = 0.00001913 * pressure_value * pressure_value + 0.03694 * pressure_value; // Поправка по давлению если включена в Samovar_ini.h
      } 
    #endif
    nbk_M = toPower(target_power_volt);  // !! Актуализация текущих М и П с учетом возможных воздействий пользователя
    nbk_P = i2c_get_liquid_rate_by_step(get_stepper_speed()); // даже если пользователь не менял вручную теперь может отличаться от Po из-за множественных преобразований
    //  4.1) если Тб<Тн-dT+dД, то П=П-dП/10, переход на 4.1)
    // 4.1.1) если Т пара ниже предела, то П=П-dП/10 (нововведение), ограничение спиртуозности выхода на случай вранья датчика Тб.
     // чем выше Т, тем ниже % спирта, нам надо снижать %, значит Т поднимать.
                               // 60% это примерно 81 гр.Ц., 50% - 84,4 гр.Ц., 40% - 87.7 гр.Ц 
    if ((nbk_Tb < nbk_Tn - nbk_dT + nbk_dD) || (nbk_Tp < nbk_Tp_lim)) { 
        if ((nbk_P > nbk_Po-0.1) && (nbk_P < nbk_Po+0.1) && (nbk_M > nbk_Mo-5) && (nbk_M < nbk_Mo+5)) {// если небыло вмешательств TODO теперь из-за преобразований мощность-напряжение-мощность придётся и по мощности сравнение делать с допустимым отклонением
          nbk_Po -= nbk_dP / 10.0;
        }
      nbk_P = nbk_Po; 
      nbk_M = nbk_Mo;       
      set_current_power(fromPower(nbk_M));
      if (nbk_P < 0) nbk_P = 0;
      SetSpeed(nbk_P);
    }
    if (nbk_Tb < nbk_Tn - nbk_dT + nbk_dD) {
      SendMsg("Работа: Тб < Тн-dT ("+String(nbk_Tn - nbk_dT + nbk_dD,1)+"), снижаем подачу на " + String(nbk_dP / 10.0,1) + ", до: " + String(nbk_P,1) + " л/ч", NOTIFY_MSG);
    } else if (nbk_Tp < nbk_Tp_lim) { 
      SendMsg("Работа: Тп ниже предела (" + String(nbk_Tp_lim,1) + "), снижаем подачу на " + String(nbk_dP/10.0,1)+ ", до: " + String(nbk_P,1) + " л/ч" , NOTIFY_MSG); 
    }    
    nbk_work_next_time = millis() + nbk_column_inertia * 1000; // задаём следующую проверку через Ин
  }
 }
  // Обработка паузы после захлёба
  if (nbk_work_in_pause && millis() >= nbk_work_next_time) {
    if (nbk_work_pause_stage == 1) {
      // После 3*Ин: После этого Мо=Мо-dM/10. М=Мо, П=По,
      if (workrun) {
        if ((nbk_P > nbk_Po-0.1) && (nbk_P < nbk_Po+0.1) && (nbk_M == nbk_Mo)) {// если небыло вмешательств
        nbk_Mo -= nbk_dM / 10.0; // на 1/10 шага убавляем мощность
        nbk_Po -= nbk_dP / 10.0; // на 1/10 шага убавляем подачу;
        }
      }
      if (!workrun) workrun = true; //если был захлеб в конце оптимизации после первой паузы, Mo не снижаем
      if (nbk_Mo < 0) nbk_Mo = 0;
      if (nbk_Po < 0) nbk_Po = 0;
      nbk_M = nbk_Mo;
      nbk_P = nbk_Po;
      set_current_power(fromPower(nbk_M));
      SetSpeed(nbk_P);
      
      SendMsg("Работа: возобновление после захлёба, скорректированные параметры: " + String(fromPower(nbk_Mo),0) + String(PWR_SIGN) + ", " + 
      String(nbk_Po,1) + " л/ч", NOTIFY_MSG);
      nbk_work_pause_stage = 2; // ждём время 2*Ин
      nbk_work_next_time = millis() + 2*(NBK_MULT_PAUSE_OVERFLOW/3) * nbk_column_inertia * 1000;
    } else if (nbk_work_pause_stage == 2) { // после MULT*Ин: продолжаем работу
      nbk_work_in_pause = false;
      nbk_work_pause_stage = 0;
      nbk_work_next_time = millis() + nbk_column_inertia * 1000; // ждем время Ин
      SendMsg("Работа: продолжаем цикл после паузы.", NOTIFY_MSG); 
    } 
  }
  vTaskDelay(200 / portTICK_PERIOD_MS);
}
// Смена программы
void run_nbk_program(uint8_t num) {
 // if (Samovar_Mode != SAMOVAR_NBK_MODE || !PowerOn) return; //dranek: лишняя проверка, ломает запуск
   if (startval == 4000) startval = 4001;
   ProgramNum = num;
   t_min = 0;
   alarm_c_min = 0;
   msgfl = true;
   if (ProgramNum > 3) ProgramNum = CAPACITY_NUM * 2; //отключаем излишнее число строк программ
 // Сообщение о переходе между этапами
  if (ProgramNum == 0) {
    //PowerOn=true;//TODO костыль 2 от незапуска по кнопке Включить нагрев 
    time_speed = 0;
    stats.startTime = millis();
    stats.avgSpeed = 0;
    stats.totalVolume = 0;
    SendMsg("Запуск программы НБК. Прогрев", NOTIFY_MSG);
    #ifdef USE_MQTT
    SessionDescription.replace(",", ";");
    MqttSendMsg(String(chipId) + "," + SamSetup.TimeZone + "," + SAMOVAR_VERSION + "," + get_nbk_program() + "," + SessionDescription, "st");
    #endif
    create_data();  //создаем файл с данными
  } else if (ProgramNum == CAPACITY_NUM * 2) {
    nbk_finish();
    return;
  } else {
    SendMsg("Переход к строке №" + (String)(num + 1) + ". Тип: " + program[num].WType, NOTIFY_MSG);
 }
  // при переходе на Разгон
  if (program[ProgramNum].WType == "H") { 
   workrun = false; // сброс флага необходимости снижения мощности в Работе после захлёба
   begintime = 0;
   set_power(true);   // Если М и П не заданы в строке, то умолчания:М = разгонная П = 1 л/ч 
   delay(2500);//TODO Ждем включения нагрева для корректного запуска
   if (program[ProgramNum].Power > 0) {
    nbk_M = toPower(program[ProgramNum].Power);
    set_current_power(fromPower(nbk_M));
    } else {
    nbk_M = nbk_M_max;
    } 
   nbk_P = program[ProgramNum].Speed > 0 ? program[ProgramNum].Speed : 1;
   SetSpeed(nbk_P);
  }
  // при переходе на Настройку
   //2) "Ручная настройка" - определение Ин, Тн, Мо и По вручную (инструкция будет)
   //Время не ограничено, переход к следующей строке по кнопке "Следующая программа", 
   //при переходе передаём в Оптимизацию текущие М и П.
  if (program[ProgramNum].WType == "S") { 
    begintime = 0;
    // если параметры есть в строке берём их, иначе минимальные
    nbk_M = program[ProgramNum].Power > 0 ? toPower(program[ProgramNum].Power) : 500;
    nbk_P = program[ProgramNum].Speed > 0 ? program[ProgramNum].Speed : 1;    
    //set_power(true);
    set_current_power(fromPower(nbk_M));
    SetSpeed(nbk_P);
  } 
  // при переходе на Оптимизацию
 if (program[ProgramNum].WType == "O") {
      nbk_opt_iter = 0; // в начале оптимизации обнуляем счетчик итераций 
      nbk_opt_in_progress = false; // включили паузу перед оптимизацией
      begintime = millis(); // засекли время для паузы перед оптимизацией
      nbk_Mo_temp = toPower(target_power_volt); //запомним на случай пропуска Оптимизации пользователем или по отсутствию ДЗ
      nbk_Po_temp = i2c_get_liquid_rate_by_step(get_stepper_speed());
      noDZ_message_sent = false;
 }
  // при переходе на работу
  // при пропуске Оптимизации пользователем передаём полученные от Ручной настройки М и П в Работу как Мо и По
  // 4) "Работа" - основной режим
  // М=Мо, П=По, либо (если указаны) - из строки программы
  if (program[ProgramNum].WType == "W") {
      if (nbk_Mo_temp > 0 && nbk_Po_temp > 0) { // при пропуске Оптимизации передаём полученные от Ручной настройки М и П в Работу как Мо и По
        nbk_Mo = nbk_Mo_temp;
        nbk_Po = nbk_Po_temp;
        SendMsg("Оптимизация пропущена. ", WARNING_MSG);  
      }
    // М=Мо, П=По, либо (если указаны) - из строки программы , если уж ничего нет 500 и 1 (Алексей дополнил)
    nbk_M = (program[ProgramNum].Power > 0) ? toPower(program[ProgramNum].Power) : (nbk_Mo > 0 ? nbk_Mo : 500);
    nbk_P = (program[ProgramNum].Speed > 0) ? program[ProgramNum].Speed : (nbk_Po > 0 ? nbk_Po : 1.0);
    nbk_Mo = nbk_M; nbk_Po=nbk_P;// уравниваем на случай чтения из программы и дефолтов
    set_current_power(fromPower(nbk_M));
    SetSpeed(nbk_P);
    SendMsg("Работа: М= " + String(nbk_M,0) + " Вт, П=" + String(nbk_P,1) + " л/ч", NOTIFY_MSG); //TODO Здесь мощность будем писать.
    nbk_work_in_pause = false; // в начале работы паузу после захлёба отключаем
  }
}
// === Проверка критических аварий ===
bool check_nbk_critical_alarms() { //вызывается циклично из этого модуля
 /*ТЗ: В строках "Оптимизация", "Работа":  
 Тп > 98°C = "Кончилась брага", М=0, П=0, выключить нагрев ИСПРАВИЛ на 98
 В строке "Ручная настройка" это условие не проверяем, т.к. в инструкции будет юстировка датчика Тб по воде*/
  if (alarm_event) { //TODO если авария - в НБК не делаем ничего
    return true;
  }
      
  static uint32_t overheat_start_time = 0;
  if (program[ProgramNum].WType != "S") { // если не Ручная настройка
    if (SteamSensor.avgTemp > 98.0) { // если Т пара больше 98
      SendMsg("Кончилась брага! Останов.", ALARM_MSG);
      nbk_M = 0;
      nbk_P = 0;
     // set_power(false);
      SetSpeed(0);
      delay(1000);
      run_nbk_program(CAPACITY_NUM * 2);//Завершаем программы
      vTaskDelay(200 / portTICK_PERIOD_MS);
      return true; //возвращаем аварию
    }
  }
    //ТЗ: Во всех "Разгон", "Ручная настройка", "Оптимизация", "Работа":
    //    Ттса > 60°C или Тводы > 70°C в течении 60 сек подряд = "Недостаточное охлаждение" (штатное)
    if (ACPSensor.avgTemp > 60.0 || WaterSensor.avgTemp > MAX_WATER_TEMP) { 
      if (overheat_start_time == 0) overheat_start_time = millis();
      if (millis() - overheat_start_time > 60000) {//ждем 60 сек
        SendMsg("Недостаточное охлаждение! Останов.", ALARM_MSG);
        nbk_M = 0;
        nbk_P = 0;
        set_power(false);
        SetSpeed(0);
        run_nbk_program(CAPACITY_NUM * 2);
        vTaskDelay(200 / portTICK_PERIOD_MS);
        return true;
      }
    } else {
      overheat_start_time = 0; // сброс счетчика времени, ситуация выправилась
    }

  return false;
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
 // Если нагрев включен и вода и температура в кубе больше уставки включения воды
  if (PowerOn && !valve_status && TankSensor.avgTemp >= OPEN_VALVE_TANK_TEMP) {
    open_valve(true, true); // призыв включить воду или открытие клапана
    // регулируем водяной насос
   #ifdef USE_WATER_PUMP
   //Устанавливаем ШИМ для насоса в зависимости от температуры воды
   if (valve_status) { // если вода включена
     // Если Т в ТСА больше предела и Т в ТСА больше Т воды (?) - крутим водяной насос усерднее, будто Т воды выше на 3 гр.
    if (ACPSensor.avgTemp > SamSetup.NbkSteamT && ACPSensor.avgTemp > WaterSensor.avgTemp) set_pump_speed_pid(SamSetup.SetWaterTemp + 3);
    else
      set_pump_speed_pid(WaterSensor.avgTemp); // иначе крутим как обычно
  }
 #endif
  }
  
 #ifdef USE_WATERSENSOR
  //Проверим, что вода подается
  if (WFAlarmCount > WF_ALARM_COUNT && PowerOn) { //датчик протока сломался уже
    set_buzzer(true);
    //Если с водой проблемы - выключаем нагрев, пусть оператор разбирается
    sam_command_sync = SAMOVAR_POWER;
    SendMsg(("Аварийное отключение! Прекращена подача воды."), ALARM_MSG);
  }
 #endif
    alarm_t_min = millis() + 60000;
  
  vTaskDelay(10 / portTICK_PERIOD_MS);
}
// Окончание программы НБК
void nbk_finish() {
  SendMsg("Работа НБК завершена", NOTIFY_MSG);
  SetSpeed(0);
  //delay(1000);
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
// === Централизованная обработка захлёба ===
void handle_overflow(const String& msg, bool finish, uint32_t pause_ms) {
  nbk_M = 0;
  nbk_P = 0;
  SetSpeed(0);
  SendMsg(msg, ALARM_MSG);
  if (finish) {
    set_current_power(0);
    run_nbk_program(CAPACITY_NUM * 2);
  } else if (pause_ms > 0) { // Для этапа W: пауза и переход к восстановлению
    set_current_power(fromPower(nbk_Mo/2));// в Работе захлёб некатастрофический, колонну можно не охлаждать
    nbk_work_in_pause = true;
    nbk_work_pause_stage = 1;
    nbk_work_next_time = millis() + pause_ms;
  }
}
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
    pair = strtok(NULL, "\n");
    program[i].Power = atof(pair);  // Коррекция мощности
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
      Str += (String)(int)program[i].Power + "\n";
    }
  }
  return Str;
}

// TODO в logic.h (359)
// if (startval == 4001) {
//   SamovarStatus = "Прг №" + String(ProgramNum + 1) + "; ";
//   if (program[ProgramNum].WType == "H") {
//     SamovarStatus = SamovarStatus + "Прогрев";
//   } else if (program[ProgramNum].WType == "S") {
//     SamovarStatus = SamovarStatus + "Настройка";
//   } else if (program[ProgramNum].WType == "O") {
//     SamovarStatus = SamovarStatus + "Оптимизация";
//   } else if (program[ProgramNum].WType == "W") {
//     SamovarStatus = SamovarStatus + "Работа";
//   }
// }