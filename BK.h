#include <Arduino.h>
#include "Samovar.h"

#ifdef USE_WATER_PUMP
#include "pumppwm.h"
#endif

#ifdef USE_MQTT
#include "SamovarMqtt.h"
#endif

/**
 * @brief Завершить работу бражной колонны, отправить уведомление, выключить нагрев и сбросить счетчики.
 */
void bk_finish();

/**
 * @brief Установить режим питания.
 * @param Mode Режим (строка)
 */
void set_power_mode(String Mode);

/**
 * @brief Установить текущую мощность.
 * @param power Мощность (Вт)
 */
void set_current_power(float power);

/**
 * @brief Включить или выключить буззер.
 * @param On true — включить, false — выключить
 */
void set_buzzer(bool On);

/**
 * @brief Сбросить счетчик датчиков.
 */
void reset_sensor_counter();

/**
 * @brief Проверить ошибки питания и обработать их.
 */
void check_power_error();

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
 * @brief Установить температуру воды (ШИМ).
 * @param duty Значение ШИМ
 */
void set_water_temp(float duty) {
#ifdef USE_WATER_PUMP
  bk_pwm = duty;
  if (pump_started) {
    pump_pwm.write(bk_pwm);
    water_pump_speed = bk_pwm;
  }
#else
  SendMsg(("Управление насосом не поддерживается вашим оборудованием"), NOTIFY_MSG);
#endif
}

/**
 * @brief Основной цикл работы бражной колонны. Запускает нагрев, проверяет условия завершения.
 */
void bk_proc() {

  if (!PowerOn) {
#ifdef USE_MQTT
    SessionDescription.replace(",", ";");
    MqttSendMsg((String)chipId + "," + SamSetup.TimeZone + "," + SAMOVAR_VERSION + ",BK," + SessionDescription, "st");
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
    SendMsg(("Включен нагрев бражной колонны"), NOTIFY_MSG);
  }

  if (TankSensor.avgTemp >= SamSetup.DistTemp) {
    bk_finish();
  }
  vTaskDelay(10 / portTICK_PERIOD_MS);
}

/**
 * @brief Проверка и обработка аварийных ситуаций в работе бражной колонны.
 */
void check_alarm_bk() {
  //сбросим паузу события безопасности
  if (alarm_t_min > 0 && alarm_t_min <= millis()) alarm_t_min = 0;

  if (PowerOn && !valve_status && TankSensor.avgTemp >= OPEN_VALVE_TANK_TEMP) {
    open_valve(true, true);
#ifdef USE_WATER_PUMP
    set_pump_pwm(bk_pwm);
#endif
  }

  //Определяем, что началось кипение - вода охлаждения начала нагреваться
  if (current_power_mode == POWER_SPEED_MODE && (check_boiling() || SteamSensor.avgTemp > CHANGE_POWER_MODE_STEAM_TEMP || PipeSensor.avgTemp > CHANGE_POWER_MODE_STEAM_TEMP)) {
#ifdef SAMOVAR_USE_POWER
#ifndef SAMOVAR_USE_SEM_AVR
    set_current_power(45);
#else
    set_current_power(200);
#endif
#else
    current_power_mode = POWER_WORK_MODE;
    digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);
#endif
  }

  if (!PowerOn && !is_self_test && valve_status && WaterSensor.avgTemp <= TARGET_WATER_TEMP - 20) {
    open_valve(false, true);
#ifdef USE_WATER_PUMP
    if (pump_started) set_pump_pwm(0);
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

  if ((WaterSensor.avgTemp >= ALARM_WATER_TEMP - 5) && PowerOn && alarm_t_min == 0) {
    set_buzzer(true);
    //Если уже реагировали - надо подождать 30 секунд, так как процесс инерционный

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
    alarm_t_min = millis() + 30000;
  }
  vTaskDelay(10 / portTICK_PERIOD_MS);
}

void bk_finish() {
  SendMsg(("Работа бражной колонны завершена"), NOTIFY_MSG);
  set_power(false);
  reset_sensor_counter();
}
