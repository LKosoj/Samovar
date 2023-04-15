#include <Arduino.h>
#include "Samovar.h"

void distiller_finish();
void set_power_mode(String Mode);
void set_power(bool On);
void create_data();
void open_valve(bool Val);
void set_pump_pwm(float duty);
void set_pump_speed_pid(float temp);
#ifdef USE_WATER_PUMP
bool check_boiling();
#endif
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
    d_s_temp_prev = WaterSensor.avgTemp;
#ifdef SAMOVAR_USE_POWER
    digitalWrite(RELE_CHANNEL4, SamSetup.rele4);
#endif
  }

  if (TankSensor.avgTemp >= SamSetup.DistTemp) {
    distiller_finish();
  }

  //Если Т в кубе больше 90 градусов и включено напряжение, проверяем, что 16 минут температура в кубе не меняется от последнего заполненного значения больше, чем на 0.1 градус
  if (TankSensor.avgTemp > 90 && PowerOn) {
    if (abs(TankSensor.avgTemp - d_s_temp_finish) > 0.1) {
      d_s_temp_finish = TankSensor.avgTemp;
      d_s_time_min = millis();
    } else if ((millis() - d_s_time_min) > 16 * 60 * 1000) {
     SendMsg(F("В кубе не осталось спирта"), NOTIFY_MSG);
     distiller_finish();
    }
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

  if (!PowerOn && !is_self_test && valve_status && WaterSensor.avgTemp <= SamSetup.SetWaterTemp - DELTA_T_CLOSE_VALVE) {
    open_valve(false);
#ifdef USE_WATER_PUMP
    if (pump_started) set_pump_pwm(0);
#endif
  }

  //Определяем, что началось кипение - вода охлаждения начала нагреваться
  check_boiling();

#ifdef USE_WATER_PUMP

  //Устанавливаем ШИМ для насоса в зависимости от температуры воды
  if (valve_status) {
    if (ACPSensor.avgTemp > SamSetup.SetACPTemp && ACPSensor.avgTemp > WaterSensor.avgTemp) set_pump_speed_pid(SamSetup.SetWaterTemp + 3);
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
    check_power_error();
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
