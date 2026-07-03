#pragma once

// Отформатировано так, чтоб сворачивать блоки для меньшего пользования скроллом
 #include <Arduino.h>
 #include "Samovar.h"
	 #include "samovar_api.h"
	 #include "runtime_helpers.h"
	 #include "mode_common.h"
	 #include "program_io.h"
// Новые веянья, platformio вестимо, сворачиваем
 #ifndef SAMOVAR_USE_POWER
 void set_current_power(float Volt){return;};
#endif

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
uint16_t nbk_opt_iter = 0;
uint32_t nbk_opt_next_time = 0;
uint32_t time_speed = 0; // для подсчета литража
bool nbk_opt_in_progress = false;
// === Переменные для этапа работы ===
uint32_t nbk_work_next_time = 0;
uint32_t nbk_overheat_start_time = 0;
bool nbk_work_in_pause = false;
bool workrun = true; // флаг необходимости снижения мощности в Работе после захлёба
uint8_t nbk_work_pause_stage = 0;
float nbk_Mo_temp = 0,
      nbk_Po_temp = 0; // временное хранилище на случай пропуска оптимизации
bool manual_overflow = false; // флаг начавшегося захлёба в работе
bool noDZ_message_sent = false; // флаг сообщения об отсутствии ДЗ
bool nbk_overflow_happened = false; // флаг: в текущей паузе после захлёба (stage W) снижение Mo/Po ещё не применялось

//  === Прототипы функций для этапов ===
void handle_nbk_stage_heatup();
void handle_nbk_stage_manual();
void handle_nbk_stage_optimization();
void handle_nbk_stage_work();
void handle_overflow(const String& msg, bool finish = true, uint32_t pause_ms = 0);

bool overflow(){
  if (PowerOn) {
   #ifdef USE_HEAD_LEVEL_SENSOR
      if (head_level_sensor_holded()) {
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
  ProgramType currentType = current_program_type();
  if (currentType != 'H') { //Иначе в среднюю скорость попадает 1л/ч прогрева
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

bool nbk_stage_sensors_valid(ProgramType wtype) {
  if (wtype == 'H') {
    if (!sensor_valid(SteamSensor) && process_sensor_failed("НБК", "пара")) return false;
  }
  if (wtype == 'O' || wtype == 'W') {
    if (!sensor_valid(SteamSensor) && process_sensor_failed("НБК", "пара")) return false;
    if (!sensor_valid(TankSensor) && process_sensor_failed("НБК", "куба")) return false;
  }
  return true;
}

void nbk_proc() { //главный цикл НБК
 #ifndef SAMOVAR_USE_POWER
  static bool noPowerAlarmSent = false;
  if (!noPowerAlarmSent) {
    SendMsg("Работа НБК невозможна - отсутствует регулятор напряжения.", ALARM_MSG);
    noPowerAlarmSent = true;
  }
  return;
 #endif
  // Обновление переменных из настроек (на случай, если пользователь их изменил в процессе)
  nbk_column_inertia =  SamSetup.NbkIn > 1 ? SamSetup.NbkIn : NBK_COLUMN_INERTIA_DEFAULT;
  nbk_dT = SamSetup.NbkDelta > 0 ? SamSetup.NbkDelta : NBK_DT_DEFAULT;
  nbk_Tn = SamSetup.DistTemp > 0 ? SamSetup.DistTemp : NBK_TN_DEFAULT;
  nbk_overflow_pressure = SamSetup.NbkOwPress > 1 ? SamSetup.NbkOwPress : NBK_OVERFLOW_PRESSURE_DEFAULT;
  nbk_dM = SamSetup.NbkDM > 1 ? SamSetup.NbkDM : NBK_DM_DEFAULT;
  nbk_dP = SamSetup.NbkDP > 0 ? SamSetup.NbkDP : NBK_DP_DEFAULT;
  nbk_Tp_lim = SamSetup.NbkSteamT > 80 ? SamSetup.NbkSteamT : NBK_TP_DEFAULT;
  nbk_M_max = SamSetup.HeaterResistant > 1 ? (230 * 230 / SamSetup.HeaterResistant) : nbk_M_max; // Максимальная мощность ТЭН-а в режиме НБК

  if (startval == 4000) {
    run_nbk_program(0);
    return;
  }

  if (ProgramNum >= NBK_PROGRAM_MAX || ProgramNum >= ProgramLen || ProgramNum >= PROGRAM_MAX) {
    request_emergency_stop("Ошибка программы НБК: номер строки вне диапазона");
    return;
  }

  ProgramType wtype = program[ProgramNum].WType; // Выбор и обработка этапа
  if (program_type_empty(wtype)) {
    request_emergency_stop("Ошибка программы НБК: строка не задана");
    return;
  }
  if (!nbk_stage_sensors_valid(wtype)) return;

  if (wtype == 'H') {
    handle_nbk_stage_heatup();
    return;
  } else if (wtype == 'S') {
    handle_nbk_stage_manual();
    return;
  } else if (wtype == 'O') {
    handle_nbk_stage_optimization();
    return;
  } else if (wtype == 'W') {
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
void handle_nbk_stage_manual() { //Если захлёб, выводим сообщение "Захлёб колонны!", М=1/2, П=1/3 (оставляем от подачи треть, половиним мощность).
  bool hasOverflow = overflow();
  if (hasOverflow && !manual_overflow) {
      manual_overflow = true;
      nbk_P = nbk_P/3;
      nbk_M = toPower(target_power_volt) / 2;
      set_current_power(fromPower(nbk_M));
      SetSpeed(nbk_P);
      SendMsg(" Подача 1/3, мощность 1/2.", ALARM_MSG);
      vTaskDelay(200 / portTICK_PERIOD_MS);
      return;
  } else if (!hasOverflow) manual_overflow = false;
  vTaskDelay(200 / portTICK_PERIOD_MS);
}


//3) "Оптимизация" - автоматическое определение Мо и По.
void handle_nbk_stage_optimization() {
  if (!nbk_opt_in_progress) { // Ждем 30 сек чтобы пользователь успел пропустить Оптимизацию если захочет,
    //в этом случае передаём полученные от Ручной настройки М и П в Работу как Мо и По
    if ((millis() - begintime) < 30000) {  // [C-13] overflow-safe: ещё в пределах 30 с от begintime
      vTaskDelay(200 / portTICK_PERIOD_MS);
      return;
    }

    #ifndef USE_HEAD_LEVEL_SENSOR //даём время пользователю задать вручную параметры в "Работе", если не задал - передадутся те, что были в Настройке
      if (!noDZ_message_sent) {
        SendMsg("Оптимизация невозможна - отсутствует датчик захлёба. Установите вручную нужные параметры в программе этапа Работа и нажмите кнопку Следующая программа. Автоматический переход к Работе произойдёт через 10 минут", ALARM_MSG);
      }
      noDZ_message_sent = true;
      if ((millis() - begintime) < 600000) {  // [C-13] overflow-safe: ещё в пределах 10 мин от begintime
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
     nbk_opt_next_time = mode_deadline_from_now((uint32_t)(nbk_column_inertia * NBK_MULT_PAUSE_OVERFLOW / 3.0f * 1000)); // Ждём время NBK_MULT_PAUSE_OVERFLOW/3 * Ин (первая пауза)
#ifdef SAMOVAR_USE_POWER
     SendMsg("Оптимизация начата с: " + String(fromPower(nbk_M),0) + String(PWR_SIGN) + ",  " + String(nbk_P,1) + " л/ч ", NOTIFY_MSG);
#endif
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
          nbk_Po *= NBK_OPERATING_RANGE / 100.0f; // отладочная корректировка после захлёба
          nbk_Mo *= NBK_OPERATING_RANGE / 100.0f;
#ifdef SAMOVAR_USE_POWER
          SendMsg(" Оптимум: " + String(fromPower(nbk_Mo),0) + String(PWR_SIGN) + ",  " +
          String(nbk_Po,1) + " л/ч", WARNING_MSG);
#endif
          run_nbk_program(ProgramNum + 1); // Сначала выставляем новую строку, потом пауза по захлёбу
          handle_overflow(
            "Оптимизация завершена.",
            false,NBK_MULT_PAUSE_OVERFLOW * nbk_column_inertia * 1000); // Переход к следующему этапу через паузу MULT*Ин
        }
        return;
     }

    if (mode_deadline_expired(nbk_opt_next_time)) {//Если пауза на инерцию вышла
    nbk_Tb = TankSensor.avgTemp;
    // Ядро оптимизации
    // 3.3) если Тб >= Тн то (По=П, Мо=М, новая П = П + dП, переход на 3.1) //увеличили подачу,
    // иначе (новые П = П*0.9, М = М + dM, переход на 3.1) // уменьшили подачу, увеличили мощность
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
#ifdef SAMOVAR_USE_POWER
        SendMsg("Достигнута предельная подача (" + String(NBK_PUMP_LIMIT) + " л/ч). Результат: " + String(fromPower(nbk_Mo),0) + String(PWR_SIGN), WARNING_MSG);
#endif
        run_nbk_program(ProgramNum + 1);
        return;
      }
      String msg; msg.reserve(128);
      msg += "Оптимизация: Тб >= Тн (";
      msg += String(nbk_Tn + nbk_dD, 1);
      msg += "), увеличиваем подачу. Итерация ";
      msg += nbk_opt_iter + 1;
      SendMsg(msg, NOTIFY_MSG);
    } else {
      if ((nbk_M + nbk_dM) > nbk_M_max) {
        SendMsg("Достигнута предельная мощность. (" + String(nbk_M ,0) + "+dM>" + String(nbk_M_max,0)  + " Вт.). Результат: " + String(nbk_Po,1) + " л/ч.", WARNING_MSG);
        run_nbk_program(ProgramNum + 1);
        return;
      }
      nbk_P *= 0.9;
      nbk_M += nbk_dM;
      if (nbk_Tp < nbk_Tp_lim) {
        String msg; msg.reserve(128);
        msg += "Оптимизация: Тп < Тп мин(";
        msg += String(nbk_Tp_lim,1);
        msg += "), увеличиваем ";
        msg += PWR_MSG;
        msg += ". Итерация ";
        msg += nbk_opt_iter + 1;
        SendMsg(msg, NOTIFY_MSG);
      } else {
        String msg; msg.reserve(128);
        msg += "Оптимизация: Тб < Тн(";
        msg += String(nbk_Tn + nbk_dD,1);
        msg += "), увеличиваем ";
        msg += PWR_MSG;
        msg += ". Итерация ";
        msg += nbk_opt_iter + 1;
        SendMsg(msg, NOTIFY_MSG);
      }
    }
    set_current_power(fromPower(nbk_M));
    SetSpeed(nbk_P);
    nbk_opt_iter++;
    if (nbk_opt_iter >= 300) {
#ifdef SAMOVAR_USE_POWER
      SendMsg("Достигнут лимит итераций. Результат: " + String(fromPower(nbk_Mo),0) + String(PWR_SIGN) + ", " + String(nbk_Po,1) + " л/ч", WARNING_MSG);
#endif
      run_nbk_program(ProgramNum + 1);
      return;
    }
    nbk_opt_next_time = mode_deadline_from_now((uint32_t)nbk_column_inertia * 1000); // 3.1) Ждём опять время Ин
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
      handle_overflow(" Временное снижение подачи и нагрева.", false, NBK_MULT_PAUSE_OVERFLOW * nbk_column_inertia * 1000); //выводим сообщение "Захлёб колонны!", М=0, П=0, ждём время MULT*Ин.
      return;
    }
    if (mode_deadline_expired(nbk_work_next_time))  {// если пауза на инерцию вышла
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
      String msg; msg.reserve(128);
      msg += "Работа: Тб < Тн-dT (";
      msg += String(nbk_Tn - nbk_dT + nbk_dD, 1);
      msg += "), снижаем подачу на ";
      msg += String(nbk_dP / 10.0, 1);
      msg += ", до: ";
      msg += String(nbk_P, 1);
      msg += " л/ч";
      SendMsg(msg, NOTIFY_MSG);
    } else if (nbk_Tp < nbk_Tp_lim) {
      String msg; msg.reserve(128);
      msg += "Работа: Тп ниже предела (";
      msg += String(nbk_Tp_lim, 1);
      msg += "), снижаем подачу на ";
      msg += String(nbk_dP / 10.0, 1);
      msg += ", до: ";
      msg += String(nbk_P, 1);
      msg += " л/ч";
      SendMsg(msg, NOTIFY_MSG);
    }
    nbk_work_next_time = mode_deadline_from_now((uint32_t)nbk_column_inertia * 1000); // задаём следующую проверку через Ин
  }
 }
  // Обработка паузы после захлёба
  if (nbk_work_in_pause && mode_deadline_expired(nbk_work_next_time)) {
    if (nbk_work_pause_stage == 1) {
      // После 3*Ин: После этого Мо=Мо-dM/10. М=Мо, П=По,
      if (workrun) {
        if (nbk_overflow_happened) { // снижаем Mo/Po только если пауза вызвана захлёбом, а не вмешательством пользователя
          nbk_Mo -= nbk_dM / 10.0; // на 1/10 шага убавляем мощность
          nbk_Po -= nbk_dP / 10.0; // на 1/10 шага убавляем подачу;
        }
      }
      nbk_overflow_happened = false; // сброс флага в любом случае (workrun или нет)
      if (!workrun) workrun = true; //если был захлеб в конце оптимизации после первой паузы, Mo не снижаем
      if (nbk_Mo < 0) nbk_Mo = 0;
      if (nbk_Po < 0) nbk_Po = 0;
      nbk_M = nbk_Mo;
      nbk_P = nbk_Po;
      set_current_power(fromPower(nbk_M));
      SetSpeed(nbk_P);

      String msg; msg.reserve(128);
      msg += "Работа: возобновление после захлёба, скорректированные параметры: ";
      msg += String(fromPower(nbk_Mo),0);
#ifdef SAMOVAR_USE_POWER
      msg += PWR_SIGN;
#endif
      msg += ", ";
      msg += String(nbk_Po,1);
      msg += " л/ч";
      SendMsg(msg, NOTIFY_MSG);
      nbk_work_pause_stage = 2; // ждём время 2*NBK_MULT_PAUSE_OVERFLOW/3 * Ин
      nbk_work_next_time = mode_deadline_from_now((uint32_t)(2.0f * NBK_MULT_PAUSE_OVERFLOW / 3.0f * nbk_column_inertia * 1000));
    } else if (nbk_work_pause_stage == 2) { // после MULT*Ин: продолжаем работу
      nbk_work_in_pause = false;
      nbk_work_pause_stage = 0;
      nbk_work_next_time = mode_deadline_from_now((uint32_t)nbk_column_inertia * 1000); // ждем время Ин
      SendMsg("Работа: продолжаем цикл после паузы.", NOTIFY_MSG);
    }
  }
  vTaskDelay(200 / portTICK_PERIOD_MS);
}

// Смена программы
void run_nbk_program(uint8_t num) {
 // if (Samovar_Mode != SAMOVAR_NBK_MODE || !PowerOn) return; //dranek: лишняя проверка, ломает запуск
  t_min = 0;
  alarm_c_min = 0;
  msgfl = true;
  if (num == 0) {
    nbk_overheat_start_time = 0;
  }
  if (num >= PROGRAM_END || num >= NBK_PROGRAM_MAX) {
    nbk_finish();
    return;
  }
  if (num >= ProgramLen || program_type_empty(program[num].WType)) {
    request_emergency_stop(num == 0 ? "Программа НБК не задана" : "Ошибка программы НБК: строка не задана");
    return;
  }
  if (!nbk_stage_sensors_valid(program[num].WType)) return;
  ProgramNum = num;
  if (num == 0 && startval == 4000) {
    startval = 4001;
  }
 // Сообщение о переходе между этапами
  if (ProgramNum == 0) {
    //PowerOn=true;//TODO костыль 2 от незапуска по кнопке Включить нагрев
    time_speed = millis();
    stats.startTime = millis();
    stats.avgSpeed = 0;
    stats.totalVolume = 0;
    if (!create_data()) {
      SendMsg("Ошибка создания файла лога. Старт НБК отменён.", ALARM_MSG);
      ProgramNum = 0;
      startval = 0;
      SamovarStatusInt = 0;
      return;
    }
    SendMsg("Запуск программы НБК. Прогрев", NOTIFY_MSG);
    #ifdef USE_MQTT
    String sessionDescription;
    if (!copy_mqtt_session_description(sessionDescription, portMAX_DELAY)) {
      SendMsg("Описание сессии занято. Старт НБК отменён.", ALARM_MSG);
      ProgramNum = 0;
      startval = 0;
      SamovarStatusInt = 0;
      if (!request_data_log_close()) SendMsg("Файл лога занят: закрытие пропущено", WARNING_MSG);
      return;
    }
    MqttSendMsg(String(chipId) + "," + SamSetup.TimeZone + "," + SAMOVAR_VERSION + "," + get_nbk_program() + "," + sessionDescription, "st");
    #endif
  } else {
    SendMsg("Переход к строке №" + (String)(num + 1) + ". Тип: " + program_type_to_string(program[num].WType), NOTIFY_MSG);
  }
  // при переходе на Разгон
  if (program[ProgramNum].WType == 'H') {
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
  if (program[ProgramNum].WType == 'S') {
    begintime = 0;
    // если параметры есть в строке берём их, иначе минимальные
    nbk_M = program[ProgramNum].Power > 0 ? toPower(program[ProgramNum].Power) : 500;
    nbk_P = program[ProgramNum].Speed > 0 ? program[ProgramNum].Speed : 1;
    //set_power(true);
    set_current_power(fromPower(nbk_M));
    SetSpeed(nbk_P);
  }
  // при переходе на Оптимизацию
 if (program[ProgramNum].WType == 'O') {
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
  if (program[ProgramNum].WType == 'W') {
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
	    nbk_overflow_happened = false; // [M-10] сбрасываем guard при старте/рестарте цикла Работа
	    nbk_work_next_time = mode_deadline_from_now((uint32_t)nbk_column_inertia * 1000);
	  }
}


// === Проверка критических аварий ===
bool check_nbk_critical_alarms() { //вызывается циклично из этого модуля
 /*ТЗ: В строках "Оптимизация", "Работа":
 Тп > 98°C = "Кончилась брага", М=0, П=0, выключить нагрев ИСПРАВИЛ на 98
 В строке "Ручная настройка" это условие не проверяем, т.к. в инструкции будет юстировка датчика Тб по воде*/
  if (SamovarStatusInt != 4000 || !PowerOn || startval < 4001) {
    nbk_overheat_start_time = 0;
    return false;
  }
  if (alarm_event) { //если авария - в НБК не делаем ничего
    return true;
  }

  if (!mode_check_powered_cooling_sensors("НБК")) return true;

  if (ProgramNum >= NBK_PROGRAM_MAX || ProgramNum >= ProgramLen || ProgramNum >= PROGRAM_END) {
    request_emergency_stop("Ошибка программы НБК: номер строки вне диапазона");
    return true;
  }
  ProgramType currentType = current_program_type();
  if (program_type_empty(currentType)) {
    request_emergency_stop("Ошибка программы НБК: пустая строка программы");
    return true;
  }

  if (currentType != 'S') { // если не Ручная настройка
    if (SteamSensor.avgTemp > 98.0) { // если Т пара больше 98
      request_emergency_stop("Кончилась брага! Останов.");
      return true; //возвращаем аварию
    }
  }
    //ТЗ: Во всех "Разгон", "Ручная настройка", "Оптимизация", "Работа":
    //    Ттса > 60°C или Тводы > 70°C в течении 60 сек подряд = "Недостаточное охлаждение" (штатное)
    if (sensor_temp_at_least(ACPSensor, 60.0f) || WaterSensor.avgTemp > MAX_WATER_TEMP) {
      if (nbk_overheat_start_time == 0) nbk_overheat_start_time = millis();
      if (millis() - nbk_overheat_start_time > 60000) {//ждем 60 сек
        request_emergency_stop("Недостаточное охлаждение! Останов.");
        return true;
      }
    } else {
      nbk_overheat_start_time = 0; // сброс счетчика времени, ситуация выправилась
    }

  return false;
}


// === Тоже Проверка критических аварий === в основном по воде
void check_alarm_nbk() {// вызывается из Samovar.ino, надо разобраться что оставить, я уже кой чего поубирал
  // Если нагрев выключен и это не самотестирование и вода включена и Т воды на 20 и более гр. ниже уставки
  if (mode_should_close_cooling(TARGET_WATER_TEMP - 20, false)) {
    open_valve(false, true); //призыв закрыть воду либо закрытие клапана
    mode_stop_cooling_pump_if_started(); // стоп водяной насос
  }

  if (!PowerOn) { // нет нагрева - больше ничего не проверяем
    return;
  }

  //сбросим паузу события безопасности
  mode_clear_alarm_pause_if_expired();

  // Если нагрев включен и вода и температура в бардоотвотчике больше уставки включения воды
  if (mode_should_open_cooling(true, false, true)) {
    open_valve(true, true); // призыв включить воду или открытие клапана
  }

  // регулируем водяной насос
  //Устанавливаем ШИМ для насоса в зависимости от температуры воды
  // Если Т в ТСА больше предела и Т в ТСА больше Т воды (?) - крутим водяной насос усерднее, будто Т воды выше на 3 гр.
  mode_update_water_pump_pid(SamSetup.SetACPTemp);

  //Проверим, что вода подается
  mode_request_water_flow_emergency_if_needed(); //датчик протока сломался уже

  if (mode_water_pre_alarm_due()) {
    set_buzzer(true);
    SendMsg(("Критическая температура воды!"), WARNING_MSG);
    mode_set_alarm_pause_ms(60000);
  }

  vTaskDelay(10 / portTICK_PERIOD_MS);
}


inline void nbk_close_data_log() {
  if (!request_data_log_close()) SendMsg("Файл лога занят: закрытие пропущено", WARNING_MSG);
}

void nbk_finish_common(bool resetWorkState) {
  SendMsg("Работа НБК завершена", NOTIFY_MSG);
  SetSpeed(0);
  nbk_overheat_start_time = 0;
  // Вычислить и отправить статистику
  uint32_t totalTime = stats.startTime > 0 ? (millis() - stats.startTime) / 1000 : 0; // в секундах
  if (totalTime > 0) {
    stats.avgSpeed = (stats.totalVolume * 3600.0) / (float)totalTime;
  } else {
    stats.avgSpeed = 0;
  }

  if (stats.startTime > 0) {
    String summary = "";//"Итоги работы НБК:\n";
    summary += "Пропущено браги " + String(stats.totalVolume, 2) + " л ";
    summary += "со средней скоростью " + String(stats.avgSpeed, 2) + " л/ч ";
    summary += "за: " + String(totalTime / 3600.0, 2) + " ч.";
    SendMsg(summary, NOTIFY_MSG);
  }
  ProgramNum = 0;
  startval = 0;
  SamovarStatusInt = 0;
  if (resetWorkState) {
    nbk_M = 0;
    nbk_P = 0;
  }
  stats.startTime = 0;
  stats.avgSpeed = 0;
  stats.totalVolume = 0;
}

// Окончание программы НБК
void nbk_finish() {
  nbk_finish_common(false);
  delay(1000);
  set_power(false);
  reset_sensor_counter();
  nbk_close_data_log();
}

void nbk_emergency_finish() {
  if (stats.startTime == 0 && startval < 4001 && !PowerOn) {
    ProgramNum = 0;
    startval = 0;
    SamovarStatusInt = 0;
    nbk_M = 0;
    nbk_P = 0;
    return;
  }

  nbk_finish_common(true);
  nbk_close_data_log();
}
// === Централизованная обработка захлёба ===
void handle_overflow(const String& msg, bool finish, uint32_t pause_ms) {
  nbk_M = nbk_M/2;
  nbk_P = nbk_P/3;
  SetSpeed(nbk_P);
  SendMsg(msg, ALARM_MSG);
  if (finish) {
    nbk_M = 0;
    nbk_P = 0;
    request_emergency_stop("");
  } else if (pause_ms > 0) { // Для этапа W: пауза и переход к восстановлению
    set_current_power(fromPower(nbk_Mo/2));// в Работе захлёб некатастрофический, колонну можно не охлаждать
    nbk_work_in_pause = true;
    nbk_work_pause_stage = 1;
    nbk_work_next_time = mode_deadline_from_now(pause_ms);
    nbk_overflow_happened = true; // захлёб зафиксирован — guard по снижению Mo/Po должен сработать
  }
}


void set_nbk_program(String WProgram) {
  program_parse_lines(WProgram, nbk_program_parse_spec());
}


String get_nbk_program() {
  return program_serialize_rows(0, PROGRAM_END, program_append_nbk_row);
}
