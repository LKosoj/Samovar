#ifndef __SAMOVAR_NBK_RUNTIME_H_
#define __SAMOVAR_NBK_RUNTIME_H_

#include "Samovar.h"
#include "state/globals.h"
#include "nbk.h"

inline void nbk_proc() { //главный цикл НБК
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
inline void handle_nbk_stage_heatup() {
    nbk_Tp = SteamSensor.avgTemp; // обновляем
    if (startval == 4000) {
      startval = 4001;
      run_nbk_program(0); //Запуск программ
      SamovarStatusInt = 4000; // Именно в таком порядке
      }
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
inline void handle_nbk_stage_manual() { //Если захлёб, выводим сообщение "Захлёб колонны!", М=1/2, П=1/3 (оставляем от подачи треть, половиним мощность).
  if (overflow() && !manual_overflow) {
      manual_overflow = true;
      nbk_P = nbk_P/3;
      nbk_M = toPower(target_power_volt) / 2;
      set_current_power(fromPower(nbk_M));
      SetSpeed(nbk_P);
      SendMsg(" Подача 1/3, мощность 1/2.", ALARM_MSG);
      vTaskDelay(200 / portTICK_PERIOD_MS);
      return;
  } else if (get_stepper_speed() > 0) manual_overflow = false;
  vTaskDelay(200 / portTICK_PERIOD_MS);
}


//3) "Оптимизация" - автоматическое определение Мо и По.
inline void handle_nbk_stage_optimization() {
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
          nbk_Po *= NBK_OPERATING_RANGE / 100; // отладочная корректировка после захлёба
          nbk_Mo *= NBK_OPERATING_RANGE / 100;
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
#ifdef SAMOVAR_USE_POWER
        SendMsg("Достигнута предельная подача (" + String(nbk_Tp_lim) + "). Результат: " + String(fromPower(nbk_Mo),0) + String(PWR_SIGN), WARNING_MSG);
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
    nbk_opt_next_time = millis() + nbk_column_inertia * 1000; // 3.1) Ждём опять время Ин
  }
  }
  vTaskDelay(200 / portTICK_PERIOD_MS);
}


//4) "Работа" - основной режим
inline void handle_nbk_stage_work() {
 //  4.1) Ждем время Ин - (первая пауза наследована от оптимизации Ин или MULT*Ин если был захлёб)
 //  4.1) если Тб<Тн-dT+dД, то П=П-dП/10, переход на 4.1)
 //  4.2) если захлёб, выводим сообщение "Захлёб колонны!", М=1/2, П=0, ждём время MULT*Ин. После этого Мо=Мо-dM/10. М=Мо, П=По, ждём время 2*Ин, переход на 4.1)
  if (!nbk_work_in_pause ) {// если не на паузе по захлёбу
    // 4.2) если захлёб, выводим сообщение "Захлёб колонны!", М=0, П=0, ждём время MULT*Ин. После этого Мо=Мо-dM/10. М=Мо, П=По, ждём время 2*Ин, переход на 4.1)
    if (overflow()) {
      handle_overflow(" Временное снижение подачи и нагрева.", false, NBK_MULT_PAUSE_OVERFLOW * nbk_column_inertia * 1000); //выводим сообщение "Захлёб колонны!", М=0, П=0, ждём время MULT*Ин.
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
        if ((nbk_P > nbk_Po-0.1) && (nbk_P < nbk_Po+0.1) && (nbk_M > nbk_Mo-5) && (nbk_M < nbk_Mo+5)) {// если небыло вмешательств, теперь из-за преобразований мощность-напряжение-мощность придётся и по мощности сравнение делать с допустимым отклонением
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
inline void run_nbk_program(uint8_t num) {
 // if (Samovar_Mode != SAMOVAR_NBK_MODE || !PowerOn) return; //dranek: лишняя проверка, ломает запуск
   ProgramNum = num;
   t_min = 0;
   alarm_c_min = 0;
   msgfl = true;
   if (ProgramNum > 3) ProgramNum = CAPACITY_NUM * 2; //отключаем излишнее число строк программ
 // Сообщение о переходе между этапами
  if (ProgramNum == 0) {
    //PowerOn=true;// костыль 2 от незапуска по кнопке Включить нагрев
    time_speed = millis();
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
   delay(2500);// Ждем включения нагрева для корректного запуска
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
    SendMsg("Работа: М= " + String(nbk_M,0) + " Вт, П=" + String(nbk_P,1) + " л/ч", NOTIFY_MSG); // Здесь мощность будем писать.
    nbk_work_in_pause = false; // в начале работы паузу после захлёба отключаем
  }
}

// === Проверка критических аварий ===
inline bool check_nbk_critical_alarms() { //вызывается циклично из этого модуля
 /*ТЗ: В строках "Оптимизация", "Работа":
 Тп > 98°C = "Кончилась брага", М=0, П=0, выключить нагрев ИСПРАВИЛ на 98
 В строке "Ручная настройка" это условие не проверяем, т.к. в инструкции будет юстировка датчика Тб по воде*/
  if (alarm_event) { //если авария - в НБК не делаем ничего
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

// === Централизованная обработка захлёба ===
inline void handle_overflow(const String& msg, bool finish, uint32_t pause_ms) {
  nbk_M = nbk_M/2;
  nbk_P = nbk_P/3;
  SetSpeed(nbk_P);
  SendMsg(msg, ALARM_MSG);
  if (finish) {
    SetSpeed(0);
    set_current_power(0);
    run_nbk_program(CAPACITY_NUM * 2);
  } else if (pause_ms > 0) { // Для этапа W: пауза и переход к восстановлению
    set_current_power(fromPower(nbk_Mo/2));// в Работе захлёб некатастрофический, колонну можно не охлаждать
    nbk_work_in_pause = true;
    nbk_work_pause_stage = 1;
    nbk_work_next_time = millis() + pause_ms;
  }
}

#endif
