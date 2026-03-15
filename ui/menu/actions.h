#ifndef __SAMOVAR_UI_MENU_ACTIONS_H_
#define __SAMOVAR_UI_MENU_ACTIONS_H_

#include <Arduino.h>

#include "Samovar.h"
#include "io/actuators.h"
#include "io/sensor_scan.h"
#include "modes/rect/rect_program_codec.h"
#include "modes/rect/rect_runtime.h"
#include "state/globals.h"
#include "storage/nvs_profiles.h"
#include "storage/nvs_wifi.h"
#include "storage/session_logs.h"
#include "support/process_math.h"
#include "support/safe_parse.h"
#include "ui/menu/strings.h"

#ifdef USE_MQTT
#include "SamovarMqtt.h"
#endif

void detector_on_manual_resume();
void reset_focus();
void set_menu_screen(uint8_t param);
void menu_update();

inline void menu_setup() {
  reset_focus();
  set_menu_screen(1);
}

inline void setup_go_back() {
  reset_focus();
  set_menu_screen(2);
  save_profile_nvs();
  read_config();
}

inline void menu_pump_speed_up() {
  set_pump_speed(get_speed_from_rate(ActualVolumePerHour + 0.01 * multiplier), true);
}

inline void menu_pump_speed_down() {
  set_pump_speed(get_speed_from_rate(ActualVolumePerHour - 0.01 * multiplier), true);
}

inline void set_delta_steam_temp_up() {
  SamSetup.DeltaSteamTemp += 0.01 * multiplier;
}

inline void set_delta_steam_temp_down() {
  SamSetup.DeltaSteamTemp -= 0.01 * multiplier;
}

inline void set_delta_pipe_temp_up() {
  SamSetup.DeltaPipeTemp += 0.01 * multiplier;
}

inline void set_delta_pipe_temp_down() {
  SamSetup.DeltaPipeTemp -= 0.01 * multiplier;
}

inline void set_delta_water_temp_up() {
  SamSetup.DeltaWaterTemp += 0.01 * multiplier;
}

inline void set_delta_water_temp_down() {
  SamSetup.DeltaWaterTemp -= 0.01 * multiplier;
}

inline void set_delta_tank_temp_up() {
  SamSetup.DeltaTankTemp += 0.01 * multiplier;
}

inline void set_delta_tank_temp_down() {
  SamSetup.DeltaTankTemp -= 0.01 * multiplier;
}

inline void set_delta_set_steam_temp_up() {
  SamSetup.SetSteamTemp += 0.01 * multiplier;
}

inline void set_delta_set_steam_temp_down() {
  SamSetup.SetSteamTemp -= 0.01 * multiplier;
}

inline void set_delta_set_pipe_temp_up() {
  SamSetup.SetPipeTemp += 0.01 * multiplier;
}

inline void set_delta_set_pipe_temp_down() {
  SamSetup.SetPipeTemp -= 0.01 * multiplier;
}

inline void set_delta_set_water_temp_up() {
  SamSetup.SetWaterTemp += 0.01 * multiplier;
}

inline void set_delta_set_water_temp_down() {
  SamSetup.SetWaterTemp -= 0.01 * multiplier;
}

inline void set_delta_set_tank_temp_up() {
  SamSetup.SetTankTemp += 0.01 * multiplier;
}

inline void set_delta_set_tank_temp_down() {
  SamSetup.SetTankTemp -= 0.01 * multiplier;
}

inline void stepper_step_ml_up() {
  SamSetup.StepperStepMl += 1 * multiplier;
}

inline void stepper_step_ml_down() {
  if (SamSetup.StepperStepMl > 0) {
    SamSetup.StepperStepMl -= 1 * multiplier;
  } else {
    SamSetup.StepperStepMl = 0;
  }
}

inline void menu_program() {
  reset_focus();
  set_menu_screen(4);
}

inline void menu_program_back() {
  reset_focus();
  set_menu_screen(1);
}

inline void menu_reset_wifi() {
  clear_wifi_credentials();
  ESP.restart();
}

void samovar_reset();

inline void menu_get_power() {
  reset_focus();
  if (Samovar_Mode == SAMOVAR_BEER_MODE) {
    if (!PowerOn) {
      set_menu_screen(2);
      sam_command_sync = SAMOVAR_BEER;
    } else {
      set_menu_screen(3);
      samovar_reset();
    }
  } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
    if (!PowerOn) {
      set_menu_screen(2);
      sam_command_sync = SAMOVAR_DISTILLATION;
    } else {
      set_menu_screen(3);
      samovar_reset();
    }
  } else if (Samovar_Mode == SAMOVAR_BK_MODE) {
    if (!PowerOn) {
      set_menu_screen(2);
      sam_command_sync = SAMOVAR_BK;
    } else {
      set_menu_screen(3);
      samovar_reset();
    }
  } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
    if (!PowerOn) {
      set_menu_screen(2);
      sam_command_sync = SAMOVAR_NBK;
    } else {
      set_menu_screen(3);
      samovar_reset();
    }
  } else {
    if (!PowerOn) {
      set_menu_screen(2);
      sam_command_sync = SAMOVAR_POWER;
    } else {
      set_menu_screen(3);
      samovar_reset();
    }
  }
}

inline void menu_pause() {
  pause_withdrawal(!PauseOn);
  if (PauseOn) {
    pause_text_ptr = (char *)menu_text_continue;
  } else {
    pause_text_ptr = (char *)menu_text_pause;
    t_min = 0;
    program_Wait = false;
    detector_on_manual_resume();
  }
}

inline void menu_calibrate() {
  if (startval > SAMOVAR_STARTVAL_RECT_IDLE && startval != SAMOVAR_STARTVAL_CALIBRATION) {
    return;
  }

  int stpspeed = stepper.getSpeed();
  if (startval == SAMOVAR_STARTVAL_CALIBRATION) {
    stpspeed = stpspeed + stpspeed / 10;
    pump_calibrate(stpspeed);
    return;
  }
  if (StepperMoving) {
    calibrate_text_ptr = (char *)menu_text_stop;
    stpspeed = 0;
  } else {
    startval = SAMOVAR_STARTVAL_CALIBRATION;
    calibrate_text_ptr = (char *)menu_text_start;
    stpspeed = STEPPER_MAX_SPEED;
  }
  pump_calibrate(stpspeed);
}

inline void menu_calibrate_down() {
  if (startval == SAMOVAR_STARTVAL_CALIBRATION) {
    int stpspeed = stepper.getSpeed();
    stpspeed = stpspeed - stpspeed / 10;
    if (stpspeed > 0) {
      pump_calibrate(stpspeed);
    }
    return;
  }
  menu_calibrate();
}

inline void menu_samovar_start() {
  if (Samovar_Mode != SAMOVAR_RECTIFICATION_MODE || !PowerOn) {
    return;
  }
  String Str;

  if (startval == SAMOVAR_STARTVAL_RECT_PROGRAM_COMPLETE) {
    startval = SAMOVAR_STARTVAL_RECT_STOPPED;
  } else if (ProgramNum >= ProgramLen - 1 && startval != SAMOVAR_STARTVAL_RECT_IDLE) {
    startval = SAMOVAR_STARTVAL_RECT_PROGRAM_COMPLETE;
  }

  if (startval == SAMOVAR_STARTVAL_RECT_IDLE) {
#ifdef USE_MQTT
    SessionDescription.replace(",", ";");
    MqttSendMsg((String)chipId + "," + SamSetup.TimeZone + "," + SAMOVAR_VERSION + "," + get_program(CAPACITY_NUM * 2) + "," + SessionDescription, "st");
    delay(200);
#endif
    startval = SAMOVAR_STARTVAL_RECT_PROGRAM_RUNNING;
    Str = menu_text_program_number_first;
    run_program(0);
    ProgramNum = 0;
    create_data();
  } else if (startval == SAMOVAR_STARTVAL_RECT_PROGRAM_RUNNING) {
    ProgramNum++;
    Str = String(menu_text_program_number_prefix) + (String)(ProgramNum + 1);
    run_program(ProgramNum);
  } else if (startval == SAMOVAR_STARTVAL_RECT_PROGRAM_COMPLETE) {
    Str = menu_text_program_finish;
    run_program(CAPACITY_NUM * 2);
  } else {
    Str = menu_text_stopped;
    run_program(CAPACITY_NUM * 2);
    reset_sensor_counter();
  }
  copyStringSafe(startval_text_val, Str);
  reset_focus();
  menu_update();
}

inline void samovar_reset() {
  char str[20];
  memcpy(str, menu_text_stopped_padded, sizeof(str));
  memcpy(str, startval_text_val, 20);
  power_text_ptr = (char *)menu_text_power_on;
  reset_focus();
  set_menu_screen(3);
  reset_sensor_counter();
  sam_command_sync = SAMOVAR_NONE;
}

#endif
