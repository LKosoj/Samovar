#include "Samovar.h"
#include "modes/rect/rect_program_codec.h"
#include "modes/rect/rect_runtime.h"
#include "state/globals.h"
#include "app/alarm_control.h"
#include "io/actuators.h"
#include "io/power_control.h"
#include "storage/session_logs.h"
#include "storage/nvs_profiles.h"
#include "storage/nvs_wifi.h"
#include "io/sensor_scan.h"
#include "support/safe_parse.h"
#include "support/process_math.h"
#include "ui/menu/strings.h"
#include "ui/menu/screens.h"
#include "ui/menu/input.h"
#include <LiquidCrystal_I2C.h>
#include <LiquidMenu.h>
#include <Arduino.h>
#include <EEPROM.h>

#ifdef USE_MQTT
#include "SamovarMqtt.h"
#endif

void read_config();
float get_speed_from_rate(float rate);
void set_pump_pwm(float duty);
void set_pump_speed_pid(float temp);
float get_alcohol(float t);
void detector_on_manual_resume();

//LiquidMenu setup_menu(lcd);


//LiquidSystem menu(main_menu, setup_menu, 1);

const char* get_power_text(){
  return power_text_ptr;
}

const char* get_startval_text(){
  return startval_text_val;
}

const char* get_pause_text(){
  return pause_text_ptr;
}

const char* get_timestr(){
  return timestr;
}

const char* get_ipstr(){
  return ipstr;
}

const char* get_calibrate_text(){
  return calibrate_text_ptr;
}

const char* get_welcomeStr1(){
  return welcomeStr1;
}

const char* get_welcomeStr2(){
  return welcomeStr2;
}

const char* get_welcomeStr3(){
  return welcomeStr3;
}

const char* get_welcomeStr4(){
  return welcomeStr4;
}

void menu_setup() {
  reset_focus();
  set_menu_screen(1);
  //menu.change_menu(setup_menu);
}

// Функция обратного вызова будет прикреплена к back_line.
void setup_go_back() {
  reset_focus();
  set_menu_screen(2);

  // Сохраняем изменения в память.
  save_profile_nvs();
  read_config();
  // Данная функция ссылается на необходимое меню.
  //main_menu1.change_menu(main_menu);
}

void writeString(String Str, uint8_t num) {
  switch (num) {
    case 1:
      copyStringSafe(welcomeStrArr1, Str);
      break;
    case 2:
      copyStringSafe(welcomeStrArr2, Str);
      break;
    case 3:
      copyStringSafe(welcomeStrArr3, Str);
      break;
    case 4:
      copyStringSafe(welcomeStrArr4, Str);
      break;
    case 0:
      menu_update();
      break;
  }
  menu_softUpdate();
}

void menu_pump_speed_up() {
  set_pump_speed(get_speed_from_rate(ActualVolumePerHour + 0.01 * multiplier), true);
}
void menu_pump_speed_down() {
  set_pump_speed(get_speed_from_rate(ActualVolumePerHour - 0.01 * multiplier), true);
}

void set_delta_steam_temp_up() {
  SamSetup.DeltaSteamTemp += 0.01 * multiplier;
}
void set_delta_steam_temp_down() {
  SamSetup.DeltaSteamTemp -= 0.01 * multiplier;
}
void set_delta_pipe_temp_up() {
  SamSetup.DeltaPipeTemp += 0.01 * multiplier;
}
void set_delta_pipe_temp_down() {
  SamSetup.DeltaPipeTemp -= 0.01 * multiplier;
}
void set_delta_water_temp_up() {
  SamSetup.DeltaWaterTemp += 0.01 * multiplier;
}
void set_delta_water_temp_down() {
  SamSetup.DeltaWaterTemp -= 0.01 * multiplier;
}
void set_delta_tank_temp_up() {
  SamSetup.DeltaTankTemp += 0.01 * multiplier;
}
void set_delta_tank_temp_down() {
  SamSetup.DeltaTankTemp -= 0.01 * multiplier;
}

void set_delta_set_steam_temp_up() {
  SamSetup.SetSteamTemp += 0.01 * multiplier;
}
void set_delta_set_steam_temp_down() {
  SamSetup.SetSteamTemp -= 0.01 * multiplier;
}
void set_delta_set_pipe_temp_up() {
  SamSetup.SetPipeTemp += 0.01 * multiplier;
}
void set_delta_set_pipe_temp_down() {
  SamSetup.SetPipeTemp -= 0.01 * multiplier;
}
void set_delta_set_water_temp_up() {
  SamSetup.SetWaterTemp += 0.01 * multiplier;
}
void set_delta_set_water_temp_down() {
  SamSetup.SetWaterTemp -= 0.01 * multiplier;
}
void set_delta_set_tank_temp_up() {
  SamSetup.SetTankTemp += 0.01 * multiplier;
}
void set_delta_set_tank_temp_down() {
  SamSetup.SetTankTemp -= 0.01 * multiplier;
}

void stepper_step_ml_up() {
  SamSetup.StepperStepMl += 1 * multiplier;
}
void stepper_step_ml_down() {
  if (SamSetup.StepperStepMl > 0) {
    SamSetup.StepperStepMl -= 1 * multiplier;
  } else
    SamSetup.StepperStepMl = 0;
}

void menu_program() {
  reset_focus();
  set_menu_screen(4);
}
void menu_program_back() {
  reset_focus();
  set_menu_screen(1);
}

void menu_reset_wifi() {
  //Сбрасываем сохраненные настройки WiFi и перегружаем Самовар
  clear_wifi_credentials();
  ESP.restart();
}

void menu_get_power() {
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

void menu_pause() {
  pause_withdrawal(!PauseOn);
  if (PauseOn) pause_text_ptr = (char *)menu_text_continue;
  else {
    pause_text_ptr = (char *)menu_text_pause;
    t_min = 0;
    program_Wait = false;
    detector_on_manual_resume();
  }
}
void menu_calibrate() {
  if (startval > 0 && startval != 100) return;

  int stpspeed = stepper.getSpeed();
  if (startval == 100) {
    stpspeed = stpspeed + stpspeed / 10;
    pump_calibrate(stpspeed);
    return;
  }
  if (StepperMoving) {
    calibrate_text_ptr = (char *)menu_text_stop;
    stpspeed = 0;
  } else {
    startval = 100;
    calibrate_text_ptr = (char *)menu_text_start;
    stpspeed = STEPPER_MAX_SPEED;
  }
  pump_calibrate(stpspeed);
}

void menu_calibrate_down() {
  if (startval == 100) {
    int stpspeed = stepper.getSpeed();
    stpspeed = stpspeed - stpspeed / 10;
    if (stpspeed > 0) pump_calibrate(stpspeed);
    return;
  }
  menu_calibrate();
}
////////////////////////////////////////////////////////////
void menu_samovar_start() {
  if (Samovar_Mode != SAMOVAR_RECTIFICATION_MODE || !PowerOn) return;
  String Str;

  if (startval == 2) startval = 3;
  else if (ProgramNum >= ProgramLen - 1 && startval != 0)
    startval = 2;

  if (startval == 0) {
#ifdef USE_MQTT
    SessionDescription.replace(",", ";");
    MqttSendMsg((String)chipId + "," + SamSetup.TimeZone + "," + SAMOVAR_VERSION + "," + get_program(CAPACITY_NUM * 2) + "," + SessionDescription, "st");
    delay(200);
#endif
    startval = 1;
    Str = menu_text_program_number_first;
    run_program(0);
    ProgramNum = 0;
    create_data();  //создаем файл с данными
  } else if (startval == 1) {
    ProgramNum++;
    Str = String(menu_text_program_number_prefix) + (String)(ProgramNum + 1);
    run_program(ProgramNum);
  } else if (startval == 2) {
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

void samovar_reset() {
  char str[20];
  memcpy(str, menu_text_stopped_padded, sizeof(str));
  memcpy(str, startval_text_val, 20);
  power_text_ptr = (char *)menu_text_power_on;
  reset_focus();
  set_menu_screen(3);
  reset_sensor_counter();
  sam_command_sync = SAMOVAR_NONE;
}
