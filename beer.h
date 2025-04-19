#include <Arduino.h>
#include "Samovar.h"
#include "SamovarMqtt.h"
#include "pumppwm.h"

/**
 * @brief Прочитать конфигурацию из памяти.
 */
void read_config();

/**
 * @brief Получить значение из строки по разделителю.
 * @param data Строка
 * @param separator Разделитель
 * @param index Индекс значения
 * @return Значение (строка)
 */
String getValue(String data, char separator, int index);

/**
 * @brief Запустить сервисные задачи (например, шаговый двигатель).
 */
void startService(void);

/**
 * @brief Остановить сервисные задачи.
 */
void stopService(void);

/**
 * @brief Установить режим питания.
 * @param Mode Режим (строка)
 */
void set_power_mode(String Mode);

/**
 * @brief Проверить ошибки питания и обработать их.
 */
void check_power_error();

/**
 * @brief Установить текущую мощность.
 * @param Volt Мощность (Вольт)
 */
void set_current_power(float Volt);

/**
 * @brief Сохранить текущий профиль настроек.
 */
void save_profile();

/**
 * @brief Завершить программу затирания, выключить нагрев, насос и клапаны.
 */
void beer_finish();

/**
 * @brief Управлять состоянием нагревателя по ПИД-регулятору.
 * @param setpoint Целевая температура
 * @param temp Текущая температура
 */
void set_heater_state(float setpoint, float temp);

/**
 * @brief Установить ШИМ для нагревателя.
 * @param dutyCycle Скважность (0.0 - 1.0)
 */
void set_heater(double dutyCycle);

/**
 * @brief Включить или выключить нагреватель.
 * @param state true — включить, false — выключить
 */
void setHeaterPosition(bool state);

/**
 * @brief Перейти к строке программы с номером num, инициализировать этап.
 * @param num Номер строки программы
 */
void run_beer_program(uint8_t num);

/**
 * @brief Запустить автотюнинг ПИД-регулятора.
 */
void StartAutoTune();

/**
 * @brief Завершить автотюнинг ПИД-регулятора и применить параметры.
 */
void FinishAutoTune();

/**
 * @brief Включить или выключить питание.
 * @param On true — включить, false — выключить
 */
void set_power(bool On);

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
 * @brief Отправить сообщение пользователю.
 * @param m Текст сообщения
 * @param msg_type Тип сообщения
 */
void SendMsg(const String& m, MESSAGE_TYPE msg_type);

/**
 * @brief Получить строковое описание программы затирания.
 * @return Строка с описанием программы
 */
String get_beer_program();

/**
 * @brief Проверить и обработать состояние мешалки и насоса.
 */
void check_mixer_state();

/**
 * @brief Установить состояние мешалки.
 * @param state true — включить, false — выключить
 * @param dir true — реверс, false — прямое вращение
 */
void set_mixer_state(bool state, bool dir);

/**
 * @brief Установить целевое состояние насоса через I2C.
 * @param on 1 — включить, 0 — выключить
 * @return true если успешно
 */
bool set_mixer_pump_target(uint8_t on);

/**
 * @brief Управлять шаговым двигателем по времени.
 * @param spd Скорость
 * @param direction Направление
 * @param time Время работы (мс)
 * @return true если успешно
 */
bool set_stepper_by_time(uint16_t spd, uint8_t direction, uint16_t time);

/**
 * @brief Совершить шаг шаговым двигателем для засыпи хмеля.
 */
void HopStepperStep();

/**
 * @brief Включить или выключить буззер.
 * @param fl true — включить, false — выключить
 */
void set_buzzer(bool fl);

/**
 * @brief Установить ШИМ для насоса.
 * @param duty Значение ШИМ
 */
void set_pump_pwm(float duty);

/**
 * @brief Сбросить счетчик датчиков и состояния процесса.
 */
void reset_sensor_counter(void);

#define TEMP_HISTORY_SIZE 10  // Размер буфера истории температур
#define BOILING_DETECT_THRESHOLD 0.2  // Порог определения стабилизации температуры
#define MIN_BOILING_TEMP 98.0  // Минимальная температура кипения (с учетом погрешности)

struct BoilingDetector {
    float tempHistory[TEMP_HISTORY_SIZE];
    uint8_t historyIndex = 0;
    bool isBoiling = false;
    unsigned long lastUpdateTime = 0;
};

BoilingDetector boilingDetector;

/**
 * @brief Проверяет, началось ли кипение по истории температур.
 * @param currentTemp Текущая температура
 * @return true, если кипение началось, иначе false
 */
bool isBoilingStarted(float currentTemp) {
    unsigned long currentTime = millis();
    
    // Обновляем историю раз в секунду
    if (currentTime - boilingDetector.lastUpdateTime >= 1000) {
        boilingDetector.lastUpdateTime = currentTime;
        boilingDetector.tempHistory[boilingDetector.historyIndex] = currentTemp;
        boilingDetector.historyIndex = (boilingDetector.historyIndex + 1) % TEMP_HISTORY_SIZE;

        // Проверяем только когда буфер заполнен
        if (currentTemp >= MIN_BOILING_TEMP) {
            float maxDiff = 0;
            float avgTemp = 0;
            
            // Вычисляем среднюю температуру и максимальное отклонение
            for (int i = 0; i < TEMP_HISTORY_SIZE; i++) {
                avgTemp += boilingDetector.tempHistory[i];
            }
            avgTemp /= TEMP_HISTORY_SIZE;
            
            for (int i = 0; i < TEMP_HISTORY_SIZE; i++) {
                float diff = abs(boilingDetector.tempHistory[i] - avgTemp);
                if (diff > maxDiff) maxDiff = diff;
            }
            
            // Если температура стабилизировалась около точки кипения
            if (maxDiff < BOILING_DETECT_THRESHOLD) {
                boilingDetector.isBoiling = true;
                return true;
            }
        }
    }
    
    return boilingDetector.isBoiling;
}

/**
 * @brief Основной цикл запуска процесса затирания. Инициализация и старт программы.
 */
void beer_proc() {
  if (SamovarStatusInt != 2000) return;

  if (startval == 2000 && !PowerOn) {
    boilingDetector.isBoiling = false;
#ifdef USE_MQTT
    SessionDescription.replace(",", ";");
    MqttSendMsg(String(chipId) + "," + SamSetup.TimeZone + "," + SAMOVAR_VERSION + "," + get_beer_program() + "," + SessionDescription, "st");
#endif
    create_data();  //создаем файл с данными
    PowerOn = true;
    set_power(true);
    run_beer_program(0);
  }
  vTaskDelay(10 / portTICK_PERIOD_MS);
}

/**
 * @brief Переход к этапу программы с номером num, обработка сообщений и сброс переменных этапа.
 * @param num Номер этапа программы
 */
void run_beer_program(uint8_t num) {
  if (Samovar_Mode != SAMOVAR_BEER_MODE || !PowerOn) return;
  if (startval == 2000) startval = 2001;
  ProgramNum = num;
  begintime = 0;
  msgfl = true;

  if (program[ProgramNum].WType == "A") {
    StartAutoTune();
  }

  if (ProgramNum > ProgramLen - 1) num = CAPACITY_NUM * 2;

  if (SamSetup.ChangeProgramBuzzer) {
    set_buzzer(true);
  }

  if (num == CAPACITY_NUM * 2) {
    //если num = CAPACITY_NUM * 2 значит мы достигли финала (или процесс сброшен принудительно), завершаем работу
    beer_finish();
  } else {
    String msg = "Переход к строке программы №" + String((num + 1));
    if (program[num].WType == "M") {
      msg += "; Нагрев до температуры засыпи солода: " + String(program[num].Temp) + "°";
    } else if (program[num].WType == "P") {
      msg += "; Температурная пауза: " + String(program[num].Temp) + "°, время: " + String(program[num].Time) + " мин";
    } else if (program[num].WType == "B") {
      msg += "; Кипячение, время: " + String(program[num].Time) + " мин";
    } else if (program[num].WType == "C") {
      msg += "; Охлаждение до температуры: " + String(program[num].Temp) + "°";
    } else if (program[num].WType == "F") {
      msg += "; Ферментация, поддержание температуры: " + String(program[num].Temp) + "°";
    } else if (program[num].WType == "W") {
      msg += "; Режим ожидания";
    }
    SendMsg(msg, NOTIFY_MSG);
  }
  //сбрасываем переменные для мешалки и насоса
  alarm_c_low_min = 0;  //мешалка вкл
  alarm_c_min = 0;  //мешалка пауза
  currentstepcnt = 0; //счетчик циклов мешалки
}

/**
 * @brief Завершает процесс затирания: выключает насос, нагрев, клапаны, сбрасывает состояния.
 */
void beer_finish() {
  if (valve_status) {
    open_valve(false, true);
  }
  set_mixer_state(false, false);
#ifdef USE_WATER_PUMP
  set_pump_pwm(0);
  pump_started = false;
#endif
  setHeaterPosition(false);
  PowerOn = false;
  heater_state = false;
  startval = 0;
  SendMsg(("Программа затирания завершена"), NOTIFY_MSG);
  delay(200);
  set_power(false);
  reset_sensor_counter();
}

/**
 * @brief Проверяет и управляет состоянием процесса затирания, включая нагрев, охлаждение, паузы и кипячение.
 */
void check_alarm_beer() {

  if (startval <= 2000) return;

  // Если процесс запущен, обеспечиваем корректное состояние флага PowerOn
  if (!PowerOn && startval > 2000) {
    PowerOn = true;
  }

  float temp = 0;
  switch (program[ProgramNum].TempSensor) {
    case 0:
      temp = TankSensor.avgTemp;
      break;
    case 1:
      temp = WaterSensor.avgTemp;
      break;
    case 2:
      temp = PipeSensor.avgTemp;
      break;
    case 3:
      temp = SteamSensor.avgTemp;
      break;
    case 4:
      temp = ACPSensor.avgTemp;
      break;
  }

  //Обрабатываем программу

  //Проверяем, что клапан воды охлаждения не открыт, когда не нужно
  if (program[ProgramNum].WType != "C" && program[ProgramNum].WType != "F" && valve_status && PowerOn) {
    //Закрываем клапан воды
    open_valve(false, false);
  }

  //Если программа - ожидание - ждем, ничего не делаем
  if (program[ProgramNum].WType == "W") {
    if (begintime == 0) {
      begintime = millis();
      setHeaterPosition(false);
      set_mixer_state(false, false);
      open_valve(false, false);
    }
    return;
  }

  //Если режим Автотюнинг
  if (program[ProgramNum].WType == "A") {
    if (tuning) {
      set_heater_state(program[ProgramNum].Temp, temp);
    } else {
      beer_finish();
    }
  }

  //Если режим Засыпь солода или Пауза
  if (program[ProgramNum].WType == "M" || program[ProgramNum].WType == "P") {
    set_heater_state(program[ProgramNum].Temp, temp);
  }

  //Если режим Брага
  if (program[ProgramNum].WType == "F") {
    //Если температура меньше целевой - греем, иначе охлаждаем.
    if (temp < program[ProgramNum].Temp - TankSensor.SetTemp) {
      if (valve_status) {
        //Закрываем клапан воды
        open_valve(false, false);
      }
      //Поддерживаем целевую температуру
      set_heater_state(program[ProgramNum].Temp, temp);
    } else if (temp > program[ProgramNum].Temp + TankSensor.SetTemp) {
      {
        if (!valve_status) {
          //Отключаем нагреватель
          setHeaterPosition(false);
          //Открываем клапан воды
          open_valve(true, false);
        }
      }
    } else {
      //Так как находимся в пределах температурной уставки, не нужно ни греть, ни охлаждать
      //Отключаем нагреватель
      setHeaterPosition(false);
      //Закрываем клапан воды, если температура в кубе чуть меньше температурной уставки, чтобы часто не щелкать клапаном
      if ((temp < program[ProgramNum].Temp + TankSensor.SetTemp - 0.1) && valve_status && PowerOn) {
        open_valve(false, false);
      }
    }
  }

  if (program[ProgramNum].WType == "M" && temp >= program[ProgramNum].Temp - TankSensor.SetTemp) {
    //Достигли температуры засыпи солода. Пишем об этом. Продолжаем поддерживать температуру. Переход с этой строки программы на следующую возможен только в ручном режиме
    if (startval == 2001) {
      set_buzzer(true);
      SendMsg(("Достигнута температура засыпи солода!"), NOTIFY_MSG);
    }
    startval = 2002;
  }

  if (program[ProgramNum].WType == "P" && temp >= program[ProgramNum].Temp - TankSensor.SetTemp) {
    if (begintime == 0) {
      //Засекаем время для отсчета, сколько держать паузу
      begintime = millis();
      SendMsg("Достигнута температурная пауза " + String(program[ProgramNum].Temp) + "°. Ждем " + String(program[ProgramNum].Time) + " минут.", NOTIFY_MSG);
    }
  }

  //Если программа - охлаждение - ждем, когда температура в кубе упадет ниже заданной, и управляем водой для охлаждения
  if (program[ProgramNum].WType == "C") {
    if (begintime == 0) {
      begintime = millis();
      setHeaterPosition(false);
      //Открываем клапан воды
      open_valve(true, false);
#ifdef USE_WATER_PUMP
      set_pump_pwm(1023);
      pump_started = true;
#endif
    }
    if (temp <= program[ProgramNum].Temp) {
      //Если температура упала
      //Закрываем клапан воды
      open_valve(false, false);
#ifdef USE_WATER_PUMP
      set_pump_pwm(0);
      pump_started = false;
#endif
      //запускаем следующую программу
      run_beer_program(ProgramNum + 1);
    }
  }

  //Если программа - кипячение
  if (program[ProgramNum].WType == "B") {
    //Если предыдущая программа была программой кипячения - просто продолжаем кипятить.
    if (begintime == 0 && ProgramNum > 0 && program[ProgramNum - 1].WType == "B") begintime = millis();

    if (begintime == 0) {
      //Определяем начало кипения
      if (isBoilingStarted(temp)) {
        msgfl = true;
        begintime = millis();
        SendMsg(("Начался режим кипячения"), NOTIFY_MSG);
      }
    }

    //Греем до температуры кипения, исходя из того, что датчик в кубе врет не сильно
    if (begintime == 0) {
      set_heater_state(BOILING_TEMP + 5, temp);
    } else {
      //Иначе поддерживаем температуру
      heater_state = true;
#ifdef SAMOVAR_USE_POWER
      //Устанавливаем заданное напряжение
      set_current_power(SamSetup.BVolt);
#else
      current_power_mode = POWER_WORK_MODE;
      digitalWrite(RELE_CHANNEL1, SamSetup.rele1);
#endif
      if (SamSetup.UseST) {
        digitalWrite(RELE_CHANNEL4, SamSetup.rele4);
      } else {
        digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);
      }
    }

    //Проверяем, что еще нужно держать паузу. За 30 секунд до окончания шлем сообщение
    if (begintime > 0 && msgfl && ((float(millis()) - begintime) / 1000 / 60 + 0.5 >= program[ProgramNum].Time)) {
      set_buzzer(true);
      msgfl = false;
      SendMsg(("Засыпьте хмель!"), NOTIFY_MSG);
#ifdef __SAMOVAR_DEBUG
      Serial.println("Засыпьте хмель!");
#endif
      HopStepperStep();
    }
  }

  //Проверяем, что еще нужно держать паузу
  if (begintime > 0 && (program[ProgramNum].WType == "B" || program[ProgramNum].WType == "P") && ((millis() - begintime) / 1000 / 60 >= program[ProgramNum].Time)) {
    //Запускаем следующую программу
    run_beer_program(ProgramNum + 1);
  }
  
  //Обрабатываем мешалку и насос
  check_mixer_state();

  vTaskDelay(10 / portTICK_PERIOD_MS);
}

/**
 * @brief Управляет состоянием мешалки и насоса в зависимости от этапа программы и времени.
 */
void check_mixer_state() {
  if (program[ProgramNum].capacity_num > 0) {
    //обрабатываем время включения и управляем мешалкой и насосом

    if (alarm_c_min > 0 && alarm_c_min <= millis()) {
      //завершили паузу мешалки
      alarm_c_min = 0;
      alarm_c_low_min = 0;
      set_mixer_state(false, false);
    }

    if ((alarm_c_low_min > 0) && (alarm_c_low_min <= millis())) {
      //выключаем мешалку, если alarm_c_min > millis()
      alarm_c_low_min = 0;
      if (alarm_c_min > 0)
        set_mixer_state(false, false);
    }

    if (alarm_c_low_min == 0 && alarm_c_min == 0) {
      //включаем мешалку
      alarm_c_low_min = millis() + program[ProgramNum].Volume * 1000;
      if (program[ProgramNum].Power > 0) alarm_c_min = alarm_c_low_min + program[ProgramNum].Power * 1000;
      currentstepcnt++;
      bool dir = false;
      if (currentstepcnt % 2 == 0 && program[ProgramNum].Speed < 0) dir = true;
      set_mixer_state(true, dir);
    }

  } else {
    if (mixer_status) {
      //если мешалка или насос работают, их нужно выключить, так как в этой строке программы они не нужны
      set_mixer_state(false, false);
    }
  }
}

/**
 * @brief Включает или выключает мешалку и насос, а также управляет направлением вращения.
 * @param state true — включить, false — выключить
 * @param dir true — реверс, false — прямое вращение
 */
void set_mixer_state(bool state, bool dir) {
  mixer_status = state;
  //Serial.println("State = " + String(state) + "; DIR = " + String(dir) + "; alarm_c_min = " + String(alarm_c_min) + "; alarm_c_low_min = " + String(alarm_c_low_min));
  if (state) {
    //включаем мешалку
    if (BitIsSet(program[ProgramNum].capacity_num, 0)) {
      //включаем реле 2
      digitalWrite(RELE_CHANNEL2, SamSetup.rele2);
      //включаем I2CStepper шаговик
      if (use_I2C_dev == 1) {
        int tm = abs(program[ProgramNum].Volume);
        if (tm == 0) tm = 10;
        bool b = set_stepper_by_time(20, dir, tm);
      }
    }
    if (BitIsSet(program[ProgramNum].capacity_num, 1)) {
#ifdef USE_WATER_PUMP
      //включаем SSD реле
      pump_pwm.write(1023);
#endif
      //включаем I2CStepper реле 1
      if (use_I2C_dev == 1 || use_I2C_dev == 2) {
        bool b = set_mixer_pump_target(1);
      }
    }
  } else {
    //выключаем реле 2
    digitalWrite(RELE_CHANNEL2, !SamSetup.rele2);
#ifdef USE_WATER_PUMP
    //выключаем SSD реле
    pump_pwm.write(0);
#endif
    //выключаем I2CStepper шаговик
    if (use_I2C_dev == 1) {
      bool b = set_stepper_by_time(0, 0, 0);
    }
    //выключаем I2CStepper реле 1
    if (use_I2C_dev == 1 || use_I2C_dev == 2) {
      bool b = set_mixer_pump_target(0);
    }
  }
}

/**
 * @brief Управляет состоянием нагревателя по ПИД-регулятору и логике разгона.
 * @param setpoint Целевая температура
 * @param temp Текущая температура
 */
void set_heater_state(float setpoint, float temp) {
#ifdef SAMOVAR_USE_POWER
  //Если дельта большая и не тюнинг, включаем разгонный тэн, иначе выключаем
  if (setpoint - temp > ACCELERATION_HEATER_DELTA && !tuning) {
    if (!acceleration_heater) {
      acceleration_heater = true;
      digitalWrite(RELE_CHANNEL4, SamSetup.rele4);
    }
  } else {
    if (acceleration_heater) {
      digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);
      acceleration_heater = false;
    }
  }
#endif

  if (setpoint - temp > HEAT_DELTA && !tuning) {
    heater_state = true;
#ifdef SAMOVAR_USE_POWER
    vTaskDelay(5 / portTICK_PERIOD_MS);
    //set_power_mode(POWER_SPEED_MODE);
    set_current_power(SamSetup.BVolt);
#else
    current_power_mode = POWER_WORK_MODE;
    digitalWrite(RELE_CHANNEL1, SamSetup.rele1);
    digitalWrite(RELE_CHANNEL4, SamSetup.rele4);
#endif
  } else {
    heaterPID.SetMode(AUTOMATIC);
    Setpoint = setpoint;
    Input = temp;

    if (tuning)  // run the auto-tuner
    {
      if (aTune.Runtime())  // returns 'true' when done
      {
        FinishAutoTune();
      }
    } else  // Execute control algorithm
    {
      heaterPID.Compute();
    }
    set_heater(Output / 100);
  }
}

/**
 * @brief Устанавливает скважность ШИМ для нагревателя.
 * @param dutyCycle Скважность (0.0 - 1.0)
 */
void set_heater(double dutyCycle) {
  static uint32_t oldTime = 0;
  static uint32_t periodTime = 0;

  uint32_t newTime = millis();
  uint32_t offTime = periodInSeconds * 1000 * (dutyCycle);

  if (newTime < oldTime) {
    periodTime += (UINT32_MAX - oldTime + newTime);
  } else {
    periodTime += (newTime - oldTime);
  }
  oldTime = newTime;

  if (periodTime < offTime) {
    if (dutyCycle > 0.0) setHeaterPosition(true);
  } else if (periodTime >= periodInSeconds * 1000) {
    periodTime = 0;
    if (dutyCycle > 0.0) setHeaterPosition(true);
  } else {
    setHeaterPosition(false);
  }
}

/**
 * @brief Включает или выключает нагреватель (реле).
 * @param state true — включить, false — выключить
 */
void setHeaterPosition(bool state) {
  heater_state = state;

  if (state) {
#ifdef SAMOVAR_USE_POWER
    //Устанавливаем заданное напряжение
    set_current_power(SamSetup.StbVoltage);

    check_power_error();
#else
    current_power_mode = POWER_WORK_MODE;
    digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);
    digitalWrite(RELE_CHANNEL1, SamSetup.rele1);
    vTaskDelay(50 / portTICK_PERIOD_MS);
#endif
  } else {
#ifdef SAMOVAR_USE_POWER
    if (current_power_mode != POWER_SLEEP_MODE) {
      //delay(200); 5.13
      set_power_mode(POWER_SLEEP_MODE);
    }
    //Устанавливаем заданное напряжение
    //set_current_power(0);
#else
    current_power_mode = POWER_WORK_MODE;
    digitalWrite(RELE_CHANNEL1, !SamSetup.rele1);
    digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);
#endif
  }
}

/**
 * @brief Возвращает строковое описание текущей программы затирания.
 * @return Строка с описанием программы
 */
String get_beer_program() {
  String Str = "";
  int k = CAPACITY_NUM * 2;
  for (uint8_t i = 0; i < k; i++) {
    if (program[i].WType.length() == 0) {
      i = CAPACITY_NUM * 2 + 1;
    } else {
      Str += program[i].WType + ";";
      Str += (String)program[i].Temp + ";";
      Str += (String)(int)program[i].Time + ";";
      Str += (String)program[i].capacity_num + "^" + program[i].Speed + "^" + program[i].Volume + "^" + program[i].Power + ";";
      Str += (String)program[i].TempSensor + "\n";
    }
  }
  return Str;
}

/**
 * @brief Устанавливает программу затирания из строки.
 * @param WProgram Строка с описанием программы
 */
void set_beer_program(String WProgram) {
  //M - malt application temp, P - pause, B - boil, C - cool
  char c[500] = {0};
  WProgram.toCharArray(c, 500);
  char *pair = strtok(c, ";");
  //String MeshTemplate;
  int i = 0;
  while (pair != NULL && i < CAPACITY_NUM * 2) {
    program[i].WType = pair;
    pair = strtok(NULL, ";");
    program[i].Temp = atof(pair);
    pair = strtok(NULL, ";");
    program[i].Time = atof(pair);
    pair = strtok(NULL, ";");
    //разберем шаблон для насоса/мешалки по частям
    program[i].capacity_num = getValue(pair, '^', 0).toInt();  //Тип устройства - 1 - мешалка, 2 - насос, 3 - мешалка и насос одновременно
    program[i].Speed = getValue(pair, '^', 1).toInt();         //Направление вращения, если задано отрицательное значение - мешалка после паузы меняет направление вращения
    program[i].Volume = getValue(pair, '^', 2).toInt();        //Время включения в секундах
    program[i].Power = getValue(pair, '^', 3).toInt();         //Время выключения в секундах
    pair = strtok(NULL, "\n");
    program[i].TempSensor = atoi(pair);

    i++;
    ProgramLen = i;
    pair = strtok(NULL, ";");
    if ((!pair || pair == NULL || pair[0] == 13) && i < CAPACITY_NUM * 2) {
      program[i].WType = "";
      break;
    }
  }
}

/**
 * @brief Запускает автотюнинг ПИД-регулятора.
 */
void StartAutoTune() {
  // REmember the mode we were in
  ATuneModeRemember = heaterPID.GetMode();

  Output = 50;

  aTune.SetControlType(1);

  // set up the auto-tune parameters
  aTune.SetNoiseBand(aTuneNoise);
  aTune.SetOutputStep(aTuneStep);
  aTune.SetLookbackSec((int)aTuneLookBack);
  tuning = true;
}

/**
 * @brief Завершает автотюнинг ПИД-регулятора, применяет параметры и сохраняет профиль.
 */
void FinishAutoTune() {
  aTune.Cancel();
  tuning = false;

  // Extract the auto-tune calculated parameters
  SamSetup.Kp = aTune.GetKp();
  SamSetup.Ki = aTune.GetKi();
  SamSetup.Kd = aTune.GetKd();

  WriteConsoleLog("Kp = " + (String)Kp);
  WriteConsoleLog("Ki = " + (String)Ki);
  WriteConsoleLog("Kd = " + (String)Kd);

  // Re-tune the PID and revert to normal control mode
  heaterPID.SetTunings(SamSetup.Kp, SamSetup.Ki, SamSetup.Kd);
  heaterPID.SetMode(ATuneModeRemember);

  save_profile();
  read_config();

  set_heater_state(0, 50);
}

/**
 * @brief Включает или выключает мешалку (обертка для set_mixer_state).
 * @param On true — включить, false — выключить
 */
void set_mixer(bool On) {
  set_mixer_state(On, false);
}

/**
 * @brief Совершает шаг шаговым двигателем для засыпи хмеля.
 */
void HopStepperStep() {
  stopService();
  stepper.brake();
  stepper.disable();
  stepper.setMaxSpeed(200); //скорость движения шагового двигателя
  //stepper.setSpeed(200);    //скорость движения шагового двигателя, должна быть равна предыдущей
  TargetStepps = 360 / 1.8 * 16 / 20;  //16 - множитель на драйвере двигателя. 20 - количество отверстий по целому кругу (если бы они занимали всю окружность)
  stepper.setCurrent(0);
  stepper.setTarget(TargetStepps);
  stepper.enable();
  startService();
}
