#ifndef __SAMOVAR_DIST_RUNTIME_H_
#define __SAMOVAR_DIST_RUNTIME_H_

#include <Arduino.h>

#include "Samovar.h"
#include "state/globals.h"
#include "app/alarm_control.h"
#include "app/messages.h"
#include "app/process_common.h"
#include "io/actuators.h"
#include "io/power_control.h"
#include "modes/dist/dist_program_codec.h"
#include "modes/dist/dist_time_predictor.h"
#include "storage/session_logs.h"
#include "support/process_math.h"

#ifdef USE_MQTT
#include "SamovarMqtt.h"
#endif

void set_pump_pwm(float duty);
void set_pump_speed_pid(float temp);

inline void distiller_finish();
inline void run_dist_program(uint8_t num);

inline void distiller_proc() {
//    SendMsg("Статус: " + String(SamovarStatusInt) +
//            ", Режим: " + String(Samovar_Mode) +
//            ", PowerOn: " + String(PowerOn), NOTIFY_MSG);

  if (SamovarStatusInt != SAMOVAR_STATUS_DISTILLATION) return;

  if (!PowerOn) {
#ifdef USE_MQTT
    SessionDescription.replace(",", ";");
    MqttSendMsg((String)chipId + "," + SamSetup.TimeZone + "," + SAMOVAR_VERSION + "," + get_dist_program() + "," + SessionDescription, "st");
#endif
    set_power(true);
#ifdef SAMOVAR_USE_POWER
    delay(1000);
    set_power_mode(POWER_SPEED_MODE);
#else
    current_power_mode = POWER_SPEED_MODE;
    digitalWrite(RELE_CHANNEL4, SamSetup.rele4);
#endif
    create_data();
    SteamSensor.Start_Pressure = bme_pressure;
    SendMsg(("Включен нагрев дистиллятора"), NOTIFY_MSG);
    run_dist_program(0);
    d_s_temp_prev = WaterSensor.avgTemp;
#ifdef SAMOVAR_USE_POWER
    digitalWrite(RELE_CHANNEL4, SamSetup.rele4);
#endif
    resetTimePredictor();
  }

  updateTimePredictor();

  if (TankSensor.avgTemp >= SamSetup.DistTemp) {
    distiller_finish();
  }

  if (ProgramNum < ProgramLen && program[ProgramNum].WType.length() > 0) {
    if (program[ProgramNum].WType == "T" && program[ProgramNum].Speed <= TankSensor.avgTemp) {
      run_dist_program(ProgramNum + 1);
    } else if (program[ProgramNum].WType == "A" && program[ProgramNum].Speed >= get_alcohol(TankSensor.avgTemp)) {
      run_dist_program(ProgramNum + 1);
    } else if (program[ProgramNum].WType == "S" && program[ProgramNum].Speed >= get_alcohol(TankSensor.avgTemp) / get_alcohol(TankSensor.StartProgTemp)) {
      run_dist_program(ProgramNum + 1);
    } else if (program[ProgramNum].WType == "P" && program[ProgramNum].Speed >= get_steam_alcohol(TankSensor.avgTemp)) {
      run_dist_program(ProgramNum + 1);
    } else if (program[ProgramNum].WType == "R" && program[ProgramNum].Speed >= get_steam_alcohol(TankSensor.avgTemp) / get_steam_alcohol(TankSensor.StartProgTemp)) {
      run_dist_program(ProgramNum + 1);
    }
  }

  if (TankSensor.avgTemp > 90 && PowerOn && SamSetup.DistTimeF > 0) {
    if (abs(TankSensor.avgTemp - d_s_temp_finish) > 0.1) {
      d_s_temp_finish = TankSensor.avgTemp;
      d_s_time_min = millis();
    } else if ((millis() - d_s_time_min) > SamSetup.DistTimeF * 60 * 1000) {
      SendMsg(("В кубе не осталось спирта"), NOTIFY_MSG);
      distiller_finish();
    }
  }

  vTaskDelay(10 / portTICK_PERIOD_MS);
}

inline void distiller_finish() {
#ifdef SAMOVAR_USE_POWER
  digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);
#endif
  String timeMsg = "Дистилляция завершена. Общее время: " + String(int((millis() - timePredictor.startTime) / 60000)) + " мин.";
  stop_process(timeMsg);
}

inline void run_dist_program(uint8_t num) {
  if (num >= ProgramLen || program[num].WType.length() == 0) {
    if (ProgramNum < ProgramLen) {
      ProgramNum = ProgramLen;
    }
    SendMsg("Выполнение программ закончилось, продолжение отбора", NOTIFY_MSG);
    return;
  }

  ProgramNum = num;

  SendMsg("Переход к строке программы №" + (String)(num + 1), NOTIFY_MSG);
  resetTimePredictor();

  SteamSensor.StartProgTemp = SteamSensor.avgTemp;
  PipeSensor.StartProgTemp = PipeSensor.avgTemp;
  WaterSensor.StartProgTemp = WaterSensor.avgTemp;
  TankSensor.StartProgTemp = TankSensor.avgTemp;

  if (num > 0) {
    set_capacity(program[num - 1].capacity_num);
    if (program[num - 1].WType.length() > 0) {
#ifdef SAMOVAR_USE_POWER
#ifdef SAMOVAR_USE_SEM_AVR
      if (abs(program[num - 1].Power) > 400 && program[num - 1].Power > 0) {
#else
      if (abs(program[num - 1].Power) > 40 && program[num - 1].Power > 0) {
#endif
        set_current_power(program[num - 1].Power);
      } else if (program[num - 1].Power != 0) {
        set_current_power(target_power_volt + program[num - 1].Power);
      }
#endif
    }
  }
}

#endif
