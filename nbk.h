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

struct { // Структура для статистики
  float avgSpeed;
  float totalVolume;
  uint32_t startTime;
  uint32_t lastVolumeUpdate;
} stats;
// === Новые и переименованные параметры по ТЗ ===
 // Комменты стараюсь помещать в строке с переменной, тогда при наведении в коде курсора всплывает и он
 #define NBK_COLUMN_INERTIA_DEFAULT 180
 uint16_t nbk_column_inertia = NBK_COLUMN_INERTIA_DEFAULT; // Инерция колонны (Ин), по умолчанию 180 секунд 
 #define NBK_OVERFLOW_PRESSURE_DEFAULT 40
 float nbk_overflow_pressure = NBK_OVERFLOW_PRESSURE_DEFAULT; // Давление захлёба (Дз), по умолчанию 40 мм рт.ст.
 float nbk_M = 0; // М — текущая мощность, Вт
 float nbk_Mo = 0; // Мо — оптимальная мощность, Вт
 float nbk_dM = 100; // dM — шаг регулирования мощности
 float nbk_P = 0; // П — текущая подача браги, л/ч
 float nbk_Po = 0; // По — оптимальная подача, л/ч
 float nbk_dP = 0.5;  // dП — шаг регулирования подачи
 float nbk_Tb = 0; // Тб — текущая температура барды
 #define NBK_TN_DEFAULT 98.5
 float nbk_Tn = NBK_TN_DEFAULT; // Тн — температура окончания, по умолчанию 98.5°C DistTemp
 float nbk_Tp = 0; // Тп — температура пара
 float nbk_Tvody = 0; // Тводы — температура воды
 float nbk_D = 0; // Д — текущее давление
 float nbk_dD = 0; // dД — поправка к Тн по давлению (используется при #define USE_NBK_DELTA_PRESSURE)
 #define NBK_DT_DEFAULT 0.5
 float nbk_dT = NBK_DT_DEFAULT;  // Допустимая просадка Т барды (dT), по умолчанию 0.5°C SetTankTemp
 float nbk_Tp_lim = 81; // Предел температуры пара на этапе Работа для ограничения спиртуозности выхода, см. таблицу объемная доля спирта в паре от Т.
 // === Переменные для этапа оптимизации ===
 static uint8_t nbk_opt_iter = 0;
 static uint32_t nbk_opt_next_time = 0;
 static bool nbk_opt_in_progress = false;
 // === Переменные для этапа работы ===
 static uint32_t nbk_work_next_time = 0;
 static bool nbk_work_in_pause = false;
 static bool workrun = true; // флаг необходимости снижения мощности в Работе после захлёба
 static uint8_t nbk_work_pause_stage = 0;
 static float nbk_Mo_temp=0, nbk_Po_temp=0; // временное хранилище на случай пропуска оптимизации
 
//void IRAM_ATTR isrNBKLS_TICK() {//зачем тут это не знаю
//  nbkls.tick();
//}
// === Прототипы функций для этапов ===
 void handle_nbk_stage_heatup();
 void handle_nbk_stage_manual();
 void handle_nbk_stage_optimization();
 void handle_nbk_stage_work();
 bool check_nbk_critical_alarms();

void nbk_proc() { //главный цикл НБК
  // dranek Обновление переменных из настроек пока так коряво, надо это делать в другом модуле/ях: при изменении и загрузке
  nbk_column_inertia =  SamSetup.TankDelay > 1 ? SamSetup.TankDelay : NBK_COLUMN_INERTIA_DEFAULT;   // нигде не используется
  nbk_dT = SamSetup.SetTankTemp > 0 ? SamSetup.SetTankTemp : NBK_DT_DEFAULT;              // в Menu.ino(407,410) корректировка// нигде не используется
  nbk_Tn = SamSetup.DistTemp > 0 ? SamSetup.DistTemp : NBK_TN_DEFAULT;                 // используется в BK.h(127) и distiller.h(239) для автоматического окончания дисцилляции
                                              // в logic.h(789,801) для завершения ректификации
  nbk_overflow_pressure = SamSetup.ACPDelay > 1 ? SamSetup.ACPDelay : 25;  // нигде не используется
  nbk_dM =SamSetup.WaterDelay>1 ? SamSetup.WaterDelay : 100;                // нигде не используется

  nbk_dP =SamSetup.DeltaACPTemp; //=  NBK_PUMP_INCREMENT/1000;//(на время отладки) 
                                              // используется в sensorinit.h(232,244) для поправки датчика температуры ТСА
                                              // если там будет 0.1-2 это ничего не сломает, но лучше здесь не использовать
  nbk_Tp_lim = SamSetup.SetACPTemp > 80 ? SamSetup.SetACPTemp : 81; 
  if (check_nbk_critical_alarms()) return; // Проверка критических аварий (true — авария, процесс завершён)
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
  if (startval == 4000) run_nbk_program(0);   //Запуск программ
  //- разгон парогенератора до Тп > 75°C.
  if (SteamSensor.avgTemp >= 75) {
    run_nbk_program(ProgramNum + 1);
    return;
  }
  //Если захлёб (пользователь задал слишком большие М и П), М=0, П=0 (обнуляем нагрев и подачу), 
  //выводим сообщение "Захлёб колонны! Останов программы".
 if (whls.isHolded())
    handle_overflow(
      "Захлёб колонны уже на прогреве: заданы слишком большие мощность и/или подача! Останов программы.", true, 0); 
  vTaskDelay(200 / portTICK_PERIOD_MS);
}
//2) "Ручная настройка" - определение Ин, Тн, Мо и По вручную (инструкция будет)
 //Время не ограничено, переход к следующей строке по кнопке "Следующая программа", 
 //при переходе передаём в Оптимизацию текущие М и П.
void handle_nbk_stage_manual() {
  // ТЗ: Если захлёб, выводим сообщение "Захлёб колонны!", М=0, П=0 (обнуляем нагрев и подачу).
 #ifdef USE_HEAD_LEVEL_SENSOR
  if (PowerOn && whls.isHolded()) {
      nbk_P = 0;//не прерываем программу, просто обнуляем мощность и подачу
      nbk_M = 0;
      set_current_power(0);
      set_stepper_target(0, 0, 0);
      SendMsg("Захлёб колонны! Подача и мощность обнулены.", ALARM_MSG); 
      return;
  }
 #endif
  vTaskDelay(200 / portTICK_PERIOD_MS);
}
//3) "Оптимизация" - автоматическое определение Мо и По.
void handle_nbk_stage_optimization() {
  if (!nbk_opt_in_progress) { // если еще не инициализировано, дозвол 
	// первый этап инициализации Оптимизации
    // Ждем половину Ин (чтобы пользователь успел пропустить Оптимизацию если захочет, 
    //в этом случае передаём полученные от Ручной настройки М и П в Работу как Мо и По)
    if ((begintime + nbk_column_inertia * 500) < millis()) {// Ждем половину Ин
      vTaskDelay(200 / portTICK_PERIOD_MS);
      return;
    }
    nbk_opt_in_progress = true; // Начальная пауза всё
    begintime = 0; // Сбрасываем отсчет для корректной обработки разницы окончания оптимизации, по захлёбу или нет
    
    // второй этап инициализации Оптимизации
    // Мо=0, По=0 М и П - из строки программы или по-умолчанию: М = разгоннная*0.3 П = 10 л/ч    
      nbk_Mo_temp = 0; //пропуск оптимизации не состоялся, сброс значений
      nbk_Po_temp = 0;     
      nbk_Mo = 0; //Мо=0, По=0
      nbk_Po = 0;
      //передаём в Оптимизацию текущие М и П. (те, что сложились после манипуляций пользователя)
      nbk_M = target_power_volt > 100 ? target_power_volt : 0.3 * 230 * 230 / SamSetup.HeaterResistant; // target_power_volt;// М = разгоннная*0.3, как вариант наследование из Ручной настройки
      nbk_P = get_stepper_speed() > 0 ? i2c_get_liquid_rate_by_step(get_stepper_speed()) : 10; //может тоже пусть лучше наследуется из Ручной настройки если не задана в строке? 
      nbk_M = program[ProgramNum].Power > 0 ? program[ProgramNum].Power : nbk_M; // если только не заданы явно в строке
      nbk_P = program[ProgramNum].Speed > 0 ? program[ProgramNum].Speed : nbk_P;
     set_current_power(nbk_M);
     set_stepper_target(i2c_get_speed_from_rate(nbk_P), 0, 2147483640);
     nbk_opt_next_time = millis() + nbk_column_inertia * 1000; // 3.1) Ждём время Ин (первая пауза)
     SendMsg("Оптимизация начата с параметров: " + String(nbk_M) + " Вт,  " + String(nbk_P) + " л / ч ", NOTIFY_MSG); 
  }

  // Собственно цикл оптимизации
  if (nbk_opt_in_progress && millis() >= nbk_opt_next_time) { //Если есть дозвол и пауза вышла
    #ifdef USE_NBK_DELTA_PRESSURE // задел на будущее
    nbk_dD =0.00001913*nbk_D*nbk_D+ 0.03694*nbk_D; // Поправка по давлению если включена в Samovar_ini.h
    #endif
    nbk_Tb = TankSensor.avgTemp;// - (bme_pressure > 0 ? (760 - bme_pressure) * 0.037 : 0);
    //  3.2) Если захлёб (по ДУФ или ДД), переход на 3.4
     bool overflow = false;
     #ifdef USE_HEAD_LEVEL_SENSOR // ДУФ
     if (whls.isHolded()) overflow = true;
     #endif
     if (pressure_value >= nbk_overflow_pressure) overflow = true; // ДД
     if (overflow) {
      if (nbk_Mo == 0 && nbk_Po == 0) { //было nbk_opt_iter == 0
        // Если захлёб на первых же итерациях  (Мо или По равно нулю), т.е. на
        // введённых пользователем вручную в строке стартовых М и П - выводим
        // сообщение "Заданные вами параметры мощности и скорости слишком
        // велики - оптимизация невозможна, уменьшите их. Останов выполнения
        // программы." 
        handle_overflow("Заданные параметры мощности и скорости слишком велики — оптимизация невозможна. Останов.", true, 0); 
      } else {
        // Если захлёб после нескольких итераций - выводим сообщение "Оптимизация завершена. Найденные параметры: 
        // ММММ Вт, ПП л/ч", полученные Мо и По будут равны последним предзахлёбным - оптимальным, сохраняем для Работы.
        // Переход к строке Работа через паузу 3*Ин (для успокоения колонны после захлёба)
        SendMsg("Захлёб колонны - завершение оптимизации. "
                "Найденные параметры: " +
                  String(nbk_Mo) + " Вт, " + String(nbk_Po) + " л/ч",
                NOTIFY_MSG);
        workrun = false; // первая пауза в Работе без снижения Mo
        run_nbk_program(ProgramNum + 1); // Сначала выставляем новый режим, потом пауза по захлёбу
        handle_overflow("Оптимизация завершена. Переход к этапу 'Работа'.",
                        false,
                        3 * nbk_column_inertia *
                          1000); // Переход к следующему этапу через паузу 3*Ин //TODO мессаги чуть поменял, чтобы логичнее последовательность
      }
      return;
    }
    // Ядро оптимизации
    // 3.3) если Тб >= Тн то (По=П, Мо=М, новая П = П + dП, переход на 3.1) //увеличили подачу, 
    // иначе (новые П = П*0.8, М = М + dM, переход на 3.1) // уменьшили подачу, увеличили мощность
    #ifdef USE_NBK_DELTA_PRESSURE
    nbk_dD =0.00001913*nbk_D*nbk_D+ 0.03694*nbk_D; // Поправка по давлению если включена в Samovar_ini.h
    #endif
    if (nbk_Tb >= nbk_Tn + nbk_dD) {
      nbk_Po = nbk_P;
      nbk_Mo = nbk_M;
      nbk_P += nbk_dP;
      SendMsg("Оптимизация: Тб >= Тн, поэтому увеличиваем подачу. Итерация " + String(nbk_opt_iter+1), NOTIFY_MSG);
    } else {
      nbk_P *= 0.8;
      nbk_M += nbk_dM;
      SendMsg("Оптимизация: Тб < Тн, поэтому увеличиваем мощность. Итерация " + String(nbk_opt_iter + 1), NOTIFY_MSG);
    }
    set_current_power(nbk_M);
    set_stepper_target(i2c_get_speed_from_rate(nbk_P), 0, 2147483640);
    nbk_opt_iter++;
    if (nbk_opt_iter >= 1000) { //dranek:пока 1000 //TODO НЕ ЗАБЫТЬ потом на вменяемые по времени 100-150 поменять)
      SendMsg("Оптимизация завершена по лимиту итераций. Достигнутые параметры: " + String(nbk_Mo) + " Вт, " + String(nbk_Po) + " л/ч", NOTIFY_MSG);
      run_nbk_program(ProgramNum + 1);
      return;
    }
    nbk_opt_next_time = millis() + nbk_column_inertia * 1000; // 3.1) Ждём опять время Ин
  }
  vTaskDelay(200 / portTICK_PERIOD_MS);
}
//4) "Работа" - основной режим
void handle_nbk_stage_work() {
 //  4.1) Ждем время Ин - (первая пауза наследована от оптимизации Ин или 3*Ин если был захлёб)
 //  4.1) если Тб<Тн-dT+dД, то П=П-dП/10, переход на 4.1)
 //  4.2) если захлёб, выводим сообщение "Захлёб колонны!", М=0, П=0, ждём время 3*Ин. После этого Мо=Мо-dM/10. М=Мо, П=По, ждём время 2*Ин, переход на 4.1)
  if (!nbk_work_in_pause && millis() >= nbk_work_next_time) {// если не на паузе по захлёбу и пауза цикла вышла
    nbk_Tb = TankSensor.avgTemp;// - (bme_pressure > 0 ? (760 - bme_pressure) * 0.037 : 0);
    #ifdef USE_NBK_DELTA_PRESSURE
    nbk_dD =0.00001913*nbk_D*nbk_D+ 0.03694*nbk_D; // Поправка по давлению если включена в Samovar_ini.h
    #endif
    //  4.1) если Тб<Тн-dT+dД, то П=П-dП/10, переход на 4.1)
    if (nbk_Tb < nbk_Tn - nbk_dT + nbk_dD) {
      nbk_P -= nbk_dP / 10.0;
      if (nbk_P < 0) nbk_P = 0;
      set_stepper_target(i2c_get_speed_from_rate(nbk_P), 0, 2147483640);
      SendMsg("Работа: Тб < Тн-dT+dД, уменьшаем подачу до: " + String(nbk_P) + " л/ч", NOTIFY_MSG);
    }
    // 4.1.1) если Т пара ниже предела, то П=П-dП/10 (нововведение), ограничение спиртуозности выхода на случай вранья датчика Тб.
    if (nbk_Tp < nbk_Tp_lim) { // чем выше Т, тем ниже % спирта, нам надо снижать %, значит Т поднимать.
                               // 60% это примерно 81 гр.Ц., 50% - 84,4 гр.Ц., 40% - 87.7 гр.Ц 
      nbk_P -= nbk_dP / 10.0;  // для этого по чуть чуть убавляем подачу
      if (nbk_P < 0) nbk_P = 0;
      set_stepper_target(i2c_get_speed_from_rate(nbk_P), 0, 2147483640);
      SendMsg("Работа: Тп ниже предела, поэтому уменьшаем подачу на " + String(nbk_dP/10.0)+ ", до: " + String(nbk_P) + " л/ч" , NOTIFY_MSG); //TODO чуть последовательность изменил, чтобы результат - в конце
    }
    nbk_work_next_time = millis() + nbk_column_inertia * 1000; // задаём следующую проверку через Ин
    // 4.2) если захлёб, выводим сообщение "Захлёб колонны!", М=0, П=0, ждём время 3*Ин. После этого Мо=Мо-dM/10. М=Мо, П=По, ждём время 2*Ин, переход на 4.1)
    bool overflow = false;
   #ifdef USE_HEAD_LEVEL_SENSOR
    if (whls.isHolded()) overflow = true;
   #endif
    if (pressure_value >= nbk_overflow_pressure) overflow = true;
    if (overflow) {
      handle_overflow("Захлёб колонны! Временное обнуление подачи и нагрева.", false, 3 * nbk_column_inertia * 1000); //выводим сообщение "Захлёб колонны!", М=0, П=0, ждём время 3*Ин. //TODO добавил "временное", чтобы не пугать новичка
      return;
    }    
  }
  // Обработка паузы после захлёба
  if (nbk_work_in_pause && millis() >= nbk_work_next_time) {
    if (nbk_work_pause_stage == 1) {
      // После 3*Ин: После этого Мо=Мо-dM/10. М=Мо, П=По,
      if (workrun) nbk_Mo = nbk_Mo - nbk_dM / 10.0; //TODO просто удивился, почему делим на .0) и там выше тоже
      if (!workrun) workrun = true; //если был захлеб в конце оптимизации после первой паузы Mo не снижаем
      if (nbk_Mo < 0) nbk_Mo = 0;
      nbk_M = nbk_Mo;
      nbk_P = nbk_Po;
      set_current_power(nbk_M);
      set_stepper_target(i2c_get_speed_from_rate(nbk_P), 0, 2147483640);
      SendMsg("Работа: возобновление после захлёба, скорректированные параметры: " +
                String(nbk_Mo) + " Вт, " + String(nbk_Po) + " л/ч", NOTIFY_MSG); // TODO Мо может быть не очень понятно, лучше прям новые вывести, кмк
      nbk_work_pause_stage = 2; // ждём время 2*Ин
      nbk_work_next_time = millis() + 2 * nbk_column_inertia * 1000;
    } else if (nbk_work_pause_stage == 2) {
      // После x*Ин: продолжаем работу
      nbk_work_in_pause = false;
      nbk_work_pause_stage = 0;
      nbk_work_next_time = millis() + nbk_column_inertia * 1000; //  4.1) Ждем время Ин
      SendMsg("Работа: продолжаем цикл после паузы.", NOTIFY_MSG); //TODO вот тут не понял, у нас не выведутся один за другим эти "возобновление" и "продрожаем"?
    }
  }
  vTaskDelay(200 / portTICK_PERIOD_MS);
}
// Смена программы
void run_nbk_program(uint8_t num) {
 // if (Samovar_Mode != SAMOVAR_NBK_MODE || !PowerOn) return; // лишняя проверка, ломает запуск
   if (startval == 4000) startval = 4001;
   ProgramNum = num;
   t_min = 0;
   alarm_c_min = 0;
   msgfl = true;
   if (ProgramNum > 3) ProgramNum = CAPACITY_NUM * 2; //отключаем излишнее число строк программ
 // Сообщение о переходе между этапами
  if (ProgramNum == 0) {
    stats.startTime = millis();
    stats.avgSpeed = 0;
    stats.totalVolume = 0;
    SendMsg("Запуск программы НБК. Прогрев", NOTIFY_MSG); //TODO этап 1 = прогрев же? чтобы единообразно называть
  } else if (ProgramNum == CAPACITY_NUM * 2) {
    nbk_finish();
    return;
  } else {
    SendMsg("Переход к строке программы №" + (String)(num + 1) + ". Тип: " + program[num].WType, NOTIFY_MSG);
 }
  // при переходе на Разгон
  if (program[ProgramNum].WType == "H") { 
   workrun = false; // сброс флага необходимости снижения мощности в Работе после захлёба
   begintime = 0;
   set_power(true);   // Если М и П не заданы в строке, то умолчания:М = разгонная П = 1 л/ч 
   if (program[ProgramNum].Power > 0) {
    nbk_M = program[ProgramNum].Power;
    set_current_power(nbk_M);
    } else {
    nbk_M = 230 * 230 / SamSetup.HeaterResistant;
    } // TODO тут, может, тоже трюк с сопротивлением ТЭНа? вдруг, у кого-то нищенские 2 кВт)

   nbk_P = program[ProgramNum].Speed > 0 ? program[ProgramNum].Speed : 1;
   set_stepper_target(i2c_get_speed_from_rate(nbk_P), 0, 2147483640);
  }
  // при переходе на Настройку
   //2) "Ручная настройка" - определение Ин, Тн, Мо и По вручную (инструкция будет)
   //Время не ограничено, переход к следующей строке по кнопке "Следующая программа", 
   //при переходе передаём в Оптимизацию текущие М и П.
   //в каждой строке: если М и П заданы вручную пользователем в текущей строке 
   //- используются они, если не заданы - копируются из предыдущей
  if (program[ProgramNum].WType == "S") { 
    begintime = 0;
    // если параметры есть в строке берём их, иначе минимальные
    nbk_M = program[ProgramNum].Power > 0 ? program[ProgramNum].Power : 500;
    nbk_P = program[ProgramNum].Speed > 0 ? program[ProgramNum].Speed : 1;    
    //set_power(true);
    set_current_power(nbk_M);
    set_stepper_target(i2c_get_speed_from_rate(nbk_P), 0, 2147483640);
  } 
  // при переходе на Оптимизацию
 if (program[ProgramNum].WType == "O") {
      nbk_opt_iter = 0; // в начале оптимизации обнуляем счетчик итераций 
      nbk_opt_in_progress = false; // включили паузу перед оптимизацией
      begintime = millis(); // засекли время для паузы перед оптимизацией
      nbk_Mo_temp = target_power_volt; //запомним на случай пропуска пользователем оптимизации
      nbk_Po_temp = i2c_get_liquid_rate_by_step(get_stepper_speed());
 }
  // при переходе на работу
  // при пропуске Оптимизации пользователем передаём полученные от Ручной настройки М и П в Работу как Мо и По
  // 4) "Работа" - основной режим
  // М=Мо, П=По, либо (если указаны) - из строки программы
  if (program[ProgramNum].WType == "W") {
      if (nbk_Mo_temp > 0 && nbk_Po_temp > 0) { // при пропуске Оптимизации пользователем передаём полученные от Ручной настройки М и П в Работу как Мо и По
        nbk_Mo = nbk_Mo_temp;
        nbk_Po = nbk_Po_temp;
        SendMsg("Оптимизация безрезультатна или пропущена, используются параметры по умолчанию.", WARNING_MSG); //TODO безрезультатна она же только по лимиту операций, не? 
      } else {
        SendMsg("Передача оптимальных параметров в этап 'Работа': Мо=" + String(nbk_Mo) + " Вт, По=" + String(nbk_Po) + " л/ч", NOTIFY_MSG);
      }
    // М=Мо, П=По, либо (если указаны) - из строки программы , если уж ничего нет 500 и 1 (Алексей дополнил)
    nbk_M = (program[ProgramNum].Power > 0) ? program[ProgramNum].Power : (nbk_Mo > 0 ? program[ProgramNum].Power : 500);
    nbk_P = (program[ProgramNum].Speed > 0) ? program[ProgramNum].Speed : (nbk_Po > 0 ? program[ProgramNum].Speed : 1.0);
    set_current_power(nbk_M);
    set_stepper_target(i2c_get_speed_from_rate(nbk_P), 0, 2147483640);
    SendMsg("Начало этапа 'Работа'. Мощность: " + String(nbk_M) + " Вт, Подача: " + String(nbk_P) + " л/ч", NOTIFY_MSG);
    nbk_work_in_pause = false; // в начале работы паузу после захлёба отключаем
  }
}
// === Проверка критических аварий ===
bool check_nbk_critical_alarms() { //вызывается циклично из этого модуля
 /*ТЗ: В строках "Оптимизация", "Работа":  
 Тп > 95°C = "Кончилась брага", М=0, П=0, выключить нагрев
 В строке "Ручная настройка" это условие не проверяем, т.к. в инструкции будет юстировка датчика Тб по воде*/
  static uint32_t overheat_start_time = 0;
  bool is_manual = (program[ProgramNum].WType == "S"); //TODO переменная место в памяти займёт, можно прямо в условие ниже переместить, только там же используется 
  if (!is_manual) {// если не Ручная настройка
    if (SteamSensor.avgTemp > 95.0) { // если Т пара больше 95
      SendMsg("Кончилась брага! Остановка процесса.", ALARM_MSG);
      nbk_M = 0;
      nbk_P = 0;
      set_power(false);
      set_stepper_target(0, 0, 0);
      run_nbk_program(CAPACITY_NUM * 2);//Завершаем программы
      vTaskDelay(200 / portTICK_PERIOD_MS);
      return true; //возвращаем аварию
    }
  }    
    //ТЗ: Во всех "Разгон", "Ручная настройка", "Оптимизация", "Работа":
    //    Ттса > 60°C или Тводы > 70°C в течении 60 сек подряд = "Недостаточное охлаждение" (штатное)
    if (ACPSensor.avgTemp > 60.0 || WaterSensor.avgTemp > 70.0) { 
      if (overheat_start_time == 0) overheat_start_time = millis();
      if (millis() - overheat_start_time > 60000) {//ждем 60 сек
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
    if (ACPSensor.avgTemp > SamSetup.SetACPTemp && ACPSensor.avgTemp > WaterSensor.avgTemp) set_pump_speed_pid(SamSetup.SetWaterTemp + 3);
    else
      set_pump_speed_pid(WaterSensor.avgTemp); // иначе крутим как обычно
  }
 #endif
  }

  //Проверяем, что температурные параметры не вышли за предельные значения
  if ((WaterSensor.avgTemp >= MAX_WATER_TEMP) && PowerOn) { // если перегревается вода
    set_buzzer(true); // пищим
    //Если с температурой проблемы - выключаем нагрев, пусть оператор разбирается
    set_power(false);
    SendMsg(("Аварийное отключение! Превышена максимальная температура воды охлаждения!"), ALARM_MSG);
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
  summary += "Максимальное давление: " + String(bme_prev_pressure) + " мм.рт.ст.\n"; //TODO я бы это воспринял как ДД (хоть что-то ценное), а не ДАД
  summary += "Общий объем браги: " + String(stats.totalVolume, 2) + " л\n";
  summary += "Время работы: " + String(totalTime / 3600.0, 2) + " ч";
  
  SendMsg(summary, NOTIFY_MSG);
}
// === Централизованная обработка захлёба ===
void handle_overflow(const String& msg, bool finish, uint32_t pause_ms) {
  nbk_M = 0;
  nbk_P = 0;
  //set_power(false);
  set_current_power(0);//;dranek: учтем замечание ais77
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
// dranek: С тем, что ниже не разбирался, явно что-то нужное //TODO та самая
// старая программа с давлением и температурой, стопудово вызывается вебсервером
// при запросах (отдать/принять) из морды, потом поправим, причёсывая финально
// H;3;0;3000;0\nS;18;0;2400;0\nO;0;0;0;0\nW;0;0;0;0\n
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


