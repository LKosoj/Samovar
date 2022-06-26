#include <Arduino.h>
#include "Samovar.h"

void distiller_finish();
void set_power_mode(String Mode);
void set_power(bool On);
void create_data();
void open_valve(bool Val);
void set_pump_pwm(float duty);
void set_pump_speed_pid(float temp);
void SendMsg(String m, MESSAGE_TYPE msg_type);

void distiller_proc() {

  if (!PowerOn) {
#ifdef USE_MQTT
    SessionDescription.replace(",", ";");
    MqttSendMsg((String)chipId + "," + SamSetup.TimeZone + "," + "" + ",Distiller," + SessionDescription, "st");
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
    SendMsg(F("Включен нагрев дистиллятора"), NOTIFY_MSG);
    dist_started = false;
    d_s_temp_prev = WaterSensor.avgTemp;
#ifdef SAMOVAR_USE_POWER
    digitalWrite(RELE_CHANNEL4, SamSetup.rele4);
#endif
  }

  if (TankSensor.avgTemp >= SamSetup.DistTemp) {
    distiller_finish();
  }
}

void IRAM_ATTR distiller_finish() {
#ifdef SAMOVAR_USE_POWER
  digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);
#endif
  SendMsg(F("Дистилляция завершена"), NOTIFY_MSG);
  set_power(false);
  reset_sensor_counter();
}


void IRAM_ATTR check_alarm_distiller() {
  //сбросим паузу события безопасности
  if (alarm_t_min > 0 && alarm_t_min <= millis()) alarm_t_min = 0;

  if (PowerOn && !valve_status && TankSensor.avgTemp >= OPEN_VALVE_TANK_TEMP) {
    open_valve(true);
  }

  if (!valve_status) {
    if (ACPSensor.avgTemp >= MAX_ACP_TEMP - 5) open_valve(true);
  }

  if (!PowerOn && valve_status && WaterSensor.avgTemp <= SamSetup.SetWaterTemp - 20) {
    open_valve(false);
#ifdef USE_WATER_PUMP
    if (pump_started) set_pump_pwm(0);
#endif
  }

#ifdef USE_WATER_PUMP
  //Определяем, что началось кипение - вода охлаждения начала нагреваться
  if (!dist_started && (d_s_temp_prev > WaterSensor.avgTemp || d_s_temp_prev == 0)) {
    d_s_temp_prev = WaterSensor.avgTemp;
  }
  if (!dist_started && WaterSensor.avgTemp - d_s_temp_prev > 15) {
    wp_count = -10;
    dist_started = true;
    SendMsg(F("Началось кипение!"), WARNING_MSG);
  }
  if (!dist_started && abs(WaterSensor.avgTemp - SamSetup.SetWaterTemp) < 3){
    dist_started = true;
    SendMsg(F("Началось кипение!"), WARNING_MSG);
  }

  //Устанавливаем ШИМ для насоса в зависимости от температуры воды
  if (valve_status) {
    if (ACPSensor.avgTemp > 39 && ACPSensor.avgTemp > WaterSensor.avgTemp) set_pump_speed_pid(SamSetup.SetWaterTemp + 3);
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
    SendMsg(F("Аварийное отключение! Прекращена подача воды."), ALARM_MSG);
  }
#endif

  if ((WaterSensor.avgTemp >= ALARM_WATER_TEMP - 5) && PowerOn && alarm_t_min == 0) {
    set_buzzer(true);
    //Если уже реагировали - надо подождать 30 секунд, так как процесс инерционный
    SendMsg(F("Критическая температура воды!"), WARNING_MSG);

#ifdef SAMOVAR_USE_POWER

#ifndef __SAMOVAR_DEBUG
    //Проверим, что заданное напряжение/мощность не сильно отличается от реального (наличие связи с регулятором, пробой семистора)
    if (SamSetup.CheckPower && current_power_mode == POWER_WORK_MODE && abs((current_power_volt - target_power_volt) / current_power_volt) > 0.1) {
      power_err_cnt++;
      if (power_err_cnt > 8) set_current_power(target_power_volt);
      if (power_err_cnt > 10) {
        delay(1000); //Пауза на всякий случай, чтобы прошли все другие команды
        set_buzzer(true);
        set_power(false);
        SendMsg(F("Аварийное отключение! Ошибка управления нагревателем."), ALARM_MSG);
      }
    } else power_err_cnt = 0;
#endif
    if (WaterSensor.avgTemp >= ALARM_WATER_TEMP) {
      set_buzzer(true);
      SendMsg("Критическая температура воды! Напряжение снижено с " + (String)target_power_volt, ALARM_MSG);
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
}
