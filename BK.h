#include <Arduino.h>
#include "Samovar.h"

void bk_finish();
void set_power_mode(String Mode);
void set_power(bool On);
void create_data();
void open_valve(bool Val);
void set_pump_pwm(float duty);
void set_pump_speed_pid(float temp);
void PrepareMsg(String m);

void set_water_temp(float duty){
#ifdef USE_WATER_PUMP
  bk_pwm = duty;
  if (pump_started){
    pump_pwm.write(bk_pwm);
  }
#endif
}

void bk_proc() {

  if (!PowerOn) {
#ifdef USE_MQTT
    SessionDescription.replace(",", ";");
    SessionDescription.replace("%", "&#37;");
    MqttSendMsg((String)chipId + "," + SamSetup.TimeZone + "," + vr + ",BK," + SessionDescription, "st");
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
    PrepareMsg("Включен нагрев бражной колонны");
#ifdef SAMOVAR_USE_BLYNK
    //Если используется Blynk - пишем оператору
    Blynk.notify("{DEVICE_NAME} - " + Msg);
#endif
  }

  if (TankSensor.avgTemp >= SamSetup.DistTemp) {
    bk_finish();
  }
}

void IRAM_ATTR bk_finish() {
  PrepareMsg("Работа бражной колонны завершена");
#ifdef SAMOVAR_USE_BLYNK
  //Если используется Blynk - пишем оператору
  Blynk.notify("{DEVICE_NAME} - " + Msg);
#endif
  set_power(false);
  reset_sensor_counter();
}


void IRAM_ATTR check_alarm_bk() {
  //сбросим паузу события безопасности
  if (alarm_t_min > 0 && alarm_t_min <= millis()) alarm_t_min = 0;

  if (PowerOn && !valve_status && TankSensor.avgTemp >= OPEN_VALVE_TANK_TEMP) {
    open_valve(true);
#ifdef USE_WATER_PUMP
    set_pump_pwm(bk_pwm);
#endif
  }

  if (!PowerOn && valve_status && WaterSensor.avgTemp <= TARGET_WATER_TEMP - 20) {
    open_valve(false);
#ifdef USE_WATER_PUMP
    if (pump_started) set_pump_pwm(0);
#endif
  }

  //Проверяем, что температурные параметры не вышли за предельные значения
  if ((WaterSensor.avgTemp >= MAX_WATER_TEMP) && PowerOn) {
    set_buzzer(true);
    //Если с температурой проблемы - выключаем нагрев, пусть оператор разбирается
    set_power(false);
    PrepareMsg("Аварийное отключение! Превышена максимальная температура воды охлаждения!");
#ifdef SAMOVAR_USE_BLYNK
    //Если используется Blynk - пишем оператору
    Blynk.notify("Тревога! {DEVICE_NAME} - " + Msg);
#endif
  }

#ifdef USE_WATERSENSOR
  //Проверим, что вода подается
  if (WFAlarmCount > WF_ALARM_COUNT && PowerOn) {
    set_buzzer(true);
    //Если с водой проблемы - выключаем нагрев, пусть оператор разбирается
    sam_command_sync = SAMOVAR_POWER;
    PrepareMsg("Аварийное отключение! Прекращена подача воды.");
#ifdef SAMOVAR_USE_BLYNK
    //Если используется Blynk - пишем оператору
    Blynk.notify("Тревога! {DEVICE_NAME} - " + Msg);
#endif
  }
#endif

  if ((WaterSensor.avgTemp >= ALARM_WATER_TEMP - 5) && PowerOn && alarm_t_min == 0) {
    set_buzzer(true);
    //Если уже реагировали - надо подождать 30 секунд, так как процесс инерционный
    PrepareMsg("Критическая температура воды!");
#ifdef SAMOVAR_USE_BLYNK
    //Если используется Blynk - пишем оператору
    Blynk.notify("Предупреждение! {DEVICE_NAME} - " + Msg);
#endif

#ifdef SAMOVAR_USE_POWER

#ifndef __SAMOVAR_DEBUG
  //Проверим, что заданное напряжение/мощность не сильно отличается от реального (наличие связи с регулятором, пробой семистора)
  if (SamSetup.CheckPower && current_power_mode == POWER_WORK_MODE && abs((current_power_volt - target_power_volt)/current_power_volt) > 0.1) {
    power_err_cnt++;
    if (power_err_cnt > 8) set_current_power(target_power_volt);
    if (power_err_cnt > 10) {
      delay(1000); //Пауза на всякий случай, чтобы прошли все другие команды
      set_buzzer(true);
      set_power(false);
      PrepareMsg("Аварийное отключение! Ошибка управления нагревателем.");
#ifdef SAMOVAR_USE_BLYNK
      //Если используется Blynk - пишем оператору
    Blynk.notify("Тревога! {DEVICE_NAME} - " + Msg);
#endif
    }
  } else power_err_cnt = 0;
#endif
    if (WaterSensor.avgTemp >= ALARM_WATER_TEMP) {
      set_buzzer(true);
      PrepareMsg("Критическая температура воды! Напряжение снижено с " + (String)target_power_volt);
#ifdef SAMOVAR_USE_BLYNK
      //Если используется Blynk - пишем оператору
    Blynk.notify("Тревога! {DEVICE_NAME} - " + Msg);
#endif
      //Попробуем снизить напряжение регулятора на 5 вольт, чтобы исключить перегрев колонны.
      set_current_power(target_power_volt - 5);
    }
#endif
    alarm_t_min = millis() + 30000;
  }
}
