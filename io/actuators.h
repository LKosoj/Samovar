#ifndef __SAMOVAR_ACTUATORS_H_
#define __SAMOVAR_ACTUATORS_H_

#include <Arduino.h>

#include "Samovar_ini.h"
#include "src/core/state/mode_codes.h"
#include "src/core/state/status_codes.h"
#include "state/globals.h"
#include "storage/nvs_profiles.h"
#include "support/format_utils.h"
#include "support/process_math.h"

void read_config();
void stopService(void);
void startService(void);
void SendMsg(const String& m, MESSAGE_TYPE msg_type);

#ifdef USER_SERVO
void user_set_capacity(uint8_t cap);
#endif

inline void pump_calibrate(int stpspeed) {
  if (startval != SAMOVAR_STARTVAL_RECT_IDLE && startval != SAMOVAR_STARTVAL_CALIBRATION) {
    return;
  }

  if (stpspeed == 0) {
    startval = SAMOVAR_STARTVAL_RECT_IDLE;
    SamSetup.StepperStepMl = round((float)stepper.getCurrent() / 100);
    stopService();
    stepper.brake();
    stepper.disable();
    save_profile_nvs();
    read_config();
  } else {
    startval = SAMOVAR_STARTVAL_CALIBRATION;
    if (!stepper.getState()) stepper.setCurrent(0);
    stepper.setMaxSpeed(stpspeed);
    stepper.setTarget(999999999);
    startService();
  }
}

inline void set_pump_speed(float pumpspeed, bool continue_process) {
  if (pumpspeed < 1) return;
  if (!samovar_status_allows_rectification_withdrawal(SamovarStatusInt)) return;

  bool cp = continue_process;
  if (!stepper.getState()) cp = false;

  CurrrentStepperSpeed = pumpspeed;
  ActualVolumePerHour = get_liquid_rate_by_step(CurrrentStepperSpeed);

  stopService();
  stepper.setMaxSpeed(CurrrentStepperSpeed);
  stepper.setTarget(stepper.getTarget());
  if (ActualVolumePerHour == 0) {
    program[ProgramNum].Time = 65535;
  } else {
    program[ProgramNum].Time = program[ProgramNum].Volume / ActualVolumePerHour / 1000;
  }
  if (cp) {
    startService();
  }
}

inline void set_capacity(uint8_t cap) {
  capacity_num = cap;

#ifdef SERVO_PIN
  int p = ((int)cap * SERVO_ANGLE) / (int)CAPACITY_NUM + servoDelta[cap];
  servo.write(p);
#elif USER_SERVO
  user_set_capacity(cap);
#endif
}

inline void next_capacity(void) {
  set_capacity(capacity_num + 1);
}

inline void open_valve(bool Val, bool msg = true) {
  if (Val && !alarm_event) {
    valve_status = true;
    if (msg) {
      SendMsg(("Откройте подачу воды!"), WARNING_MSG);
    } else {
      SendMsg(("Открыт клапан воды охлаждения!"), NOTIFY_MSG);
    }
    digitalWrite(RELE_CHANNEL3, SamSetup.rele3);
  } else {
    valve_status = false;
    if (msg) {
      SendMsg(("Закройте подачу воды!"), WARNING_MSG);
    } else {
      SendMsg(("Закрыт клапан воды охлаждения!"), NOTIFY_MSG);
    }
    digitalWrite(RELE_CHANNEL3, !SamSetup.rele3);
  }
}

inline void set_boiling() {
  if (!boil_started) {
    boil_started = true;
    if (TankSensor.avgTemp >= 2) {
      boil_temp = TankSensor.avgTemp;
      alcohol_s = get_alcohol(TankSensor.avgTemp);
    } else {
      boil_temp = 0;
      alcohol_s = 0;
    }
#ifdef USE_WATER_PUMP
    wp_count = -10;
#endif
  }
}

inline bool check_boiling() {
  if (boil_started || !PowerOn || !valve_status) {
    return false;
  }

  bool has_tank_sensor = TankSensor.avgTemp >= 2;
  bool has_water_sensor = WaterSensor.avgTemp >= 2;

  if (!has_tank_sensor && !has_water_sensor) {
    return false;
  }

  if (has_tank_sensor && TankSensor.avgTemp < 70) {
    return false;
  }

  if (b_t_time_delay == 0 || (b_t_time_delay + 60 * 1000 > millis())) {
    if (b_t_time_delay == 0) {
      b_t_time_delay = millis();
    }
    return false;
  }

  bool boiling_detected = false;

  if (has_tank_sensor && has_water_sensor) {
    if (d_s_temp_prev > WaterSensor.avgTemp || d_s_temp_prev == 0) {
      d_s_temp_prev = WaterSensor.avgTemp;
    }

    bool tank_stable = false;
    if (TankSensor.avgTemp - b_t_temp_prev > 0.1) {
      b_t_temp_prev = TankSensor.avgTemp;
      b_t_time_min = millis();
    } else if ((millis() - b_t_time_min) > 50 * 1000 && b_t_time_min > 0) {
      tank_stable = true;
    }

    bool water_heating = (WaterSensor.avgTemp - d_s_temp_prev > 8) ||
                         (abs(WaterSensor.avgTemp - SamSetup.SetWaterTemp) < 3 && WaterSensor.avgTemp - d_s_temp_prev > 2);

    if ((tank_stable && water_heating) || SteamSensor.avgTemp > CHANGE_POWER_MODE_STEAM_TEMP) {
      boiling_detected = true;
    }
  } else if (has_tank_sensor) {
    if (TankSensor.avgTemp - b_t_temp_prev > 0.1) {
      b_t_temp_prev = TankSensor.avgTemp;
      b_t_time_min = millis();
    } else if ((millis() - b_t_time_min) > 50 * 1000 && b_t_time_min > 0) {
      boiling_detected = true;
    }
    if (SteamSensor.avgTemp > CHANGE_POWER_MODE_STEAM_TEMP) {
      boiling_detected = true;
    }
  } else if (has_water_sensor) {
    if (d_s_temp_prev > WaterSensor.avgTemp || d_s_temp_prev == 0) {
      d_s_temp_prev = WaterSensor.avgTemp;
    }
    if (WaterSensor.avgTemp - d_s_temp_prev > 8) {
      boiling_detected = true;
    }
    if (abs(WaterSensor.avgTemp - SamSetup.SetWaterTemp) < 3 && WaterSensor.avgTemp - d_s_temp_prev > 2) {
      boiling_detected = true;
    }
    if (SteamSensor.avgTemp > CHANGE_POWER_MODE_STEAM_TEMP) {
      boiling_detected = true;
    }
  }

  if (boiling_detected) {
    set_boiling();
    if (boil_started) {
      if (has_tank_sensor) {
        SendMsg("Началось кипение в кубе! Спиртуозность " + format_float(alcohol_s, 1), WARNING_MSG);
      } else {
        SendMsg("Началось кипение в кубе!", WARNING_MSG);
      }
    }
  }

  return boil_started;
}

#endif
