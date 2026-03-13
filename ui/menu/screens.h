#ifndef __SAMOVAR_UI_MENU_SCREENS_H_
#define __SAMOVAR_UI_MENU_SCREENS_H_

#include <LiquidMenu.h>

#include "state/globals.h"
#include "ui/menu/strings.h"

const char* get_calibrate_text();
const char* get_startval_text();
const char* get_timestr();
const char* get_welcomeStr1();
const char* get_welcomeStr2();
const char* get_welcomeStr3();
const char* get_welcomeStr4();
const char* get_pause_text();
const char* get_power_text();
const char* get_ipstr();

static LiquidLine lql_back_line(0, 10, str_BACK);
static LiquidLine lql_time(0, 10, get_timestr);

static LiquidLine welcome_line1(0, 0, get_welcomeStr1);
static LiquidLine welcome_line2(0, 1, get_welcomeStr2);
static LiquidLine welcome_line3(0, 2, get_welcomeStr3);
static LiquidLine welcome_line4(0, 3, get_welcomeStr4);
static LiquidScreen welcome_screen(welcome_line1, welcome_line2, welcome_line3, welcome_line4);

static LiquidLine lql_steam_temp(0, 0, str_Steam_T, SteamSensor.avgTemp);
static LiquidLine lql_pipe_temp(0, 1, str_Pipe_T, PipeSensor.avgTemp);
static LiquidLine lql_water_temp(0, 2, str_Water_T, WaterSensor.avgTemp);
static LiquidScreen main_screen(lql_steam_temp, lql_pipe_temp, lql_water_temp, lql_time);

static LiquidLine lql_tank_temp(0, 0, str_Tank_T, TankSensor.avgTemp);
static LiquidLine lql_atm(0, 1, str_Pressure, bme_pressure);
static LiquidLine lql_w_progress(0, 2, str_Progress, WthdrwlProgress);
static LiquidScreen main_screen1(lql_tank_temp, lql_atm, lql_w_progress, lql_time);

static LiquidLine lql_start(0, 0, str_Start, get_startval_text);
static LiquidLine lql_pump_speed(0, 1, str_Speed, ActualVolumePerHour);
static LiquidLine lql_pause(0, 2, str_Pause, get_pause_text);
static LiquidLine lql_reset(0, 3, str_Reset_W);
static LiquidScreen main_screen2(lql_start, lql_pump_speed, lql_pause, lql_reset);

static LiquidLine lql_get_power(0, 0, str_Get_Power, get_power_text);
static LiquidLine lql_setup(0, 1, str_Setup);
static LiquidLine lql_ip(0, 2, str_IP, get_ipstr);
static LiquidScreen main_screen4(lql_get_power, lql_setup, lql_ip, lql_time);

static LiquidScreen main_screen5(lql_tank_temp, lql_atm, lql_water_temp, lql_time);

static LiquidLine lql_setup_steam_temp(0, 0, str_Steam_T, SamSetup.DeltaSteamTemp);
static LiquidLine lql_setup_pipe_temp(0, 1, str_Pipe_T, SamSetup.DeltaPipeTemp);
static LiquidLine lql_setup_water_temp(0, 2, str_Water_T, SamSetup.DeltaWaterTemp);
static LiquidLine lql_setup_tank_temp(0, 3, str_Tank_T, SamSetup.DeltaTankTemp);
static LiquidScreen setup_temp_screen(lql_setup_steam_temp, lql_setup_pipe_temp, lql_setup_water_temp, lql_setup_tank_temp);

static LiquidLine lql_setup_set_steam_temp(0, 0, str_Set_Steam_T, SamSetup.SetSteamTemp);
static LiquidLine lql_setup_set_pipe_temp(0, 1, str_Set_Pipe_T, SamSetup.SetPipeTemp);
static LiquidLine lql_setup_set_water_temp(0, 2, str_Set_Water_T, SamSetup.SetWaterTemp);
static LiquidLine lql_setup_set_tank_temp(0, 3, str_Set_Tank_T, SamSetup.SetTankTemp);
static LiquidScreen setup_set_temp_screen(lql_setup_set_steam_temp, lql_setup_set_pipe_temp, lql_setup_set_water_temp, lql_setup_set_tank_temp);

static LiquidLine lql_setup_stepper_stepper_step_ml(0, 0, str_Step_Ml, SamSetup.StepperStepMl);
static LiquidLine lql_setup_stepper_calibrate(0, 1, str_Calibrate, get_calibrate_text);
static LiquidLine lql_setup_stepper_program(0, 2, str_Program);
static LiquidScreen setup_stepper_settings(lql_setup_stepper_stepper_step_ml, lql_setup_stepper_calibrate, lql_setup_stepper_program, lql_time);

static LiquidLine lql_setup_program_WType(0, 0, str_Type, program[0].WType);
static LiquidLine lql_setup_program_Volume(0, 1, str_Volume, program[0].Volume);
static LiquidLine lql_setup_program_Speed(0, 2, str_Speed, program[0].Speed);
static LiquidLine lql_setup_program_capacity_num(0, 3, str_Capacity, program[0].capacity_num);
static LiquidLine lql_setup_program_Temp(0, 4, str_Temp, program[0].Temp);
static LiquidLine lql_setup_program_Power(0, 5, str_Power, program[0].Power);
static LiquidScreen setup_program_settings(
  lql_setup_program_WType,
  lql_setup_program_Volume,
  lql_setup_program_Speed,
  lql_setup_program_capacity_num
);

static LiquidLine lql_setup_program_reset_wifi(0, 0, str_Reset_WiFi);
static LiquidLine lql_setup_program_back_line(0, 1, str_BACK);
static LiquidScreen setup_program_back(lql_setup_program_reset_wifi, lql_setup_program_back_line, lql_time);

static LiquidScreen setup_back_screen(lql_back_line, lql_time);

inline void setup_menu_screen_decimal_places() {
  lql_steam_temp.set_decimalPlaces(2);
  lql_setup_pipe_temp.set_decimalPlaces(2);
  lql_setup_water_temp.set_decimalPlaces(2);
  lql_setup_tank_temp.set_decimalPlaces(2);
  lql_pump_speed.set_decimalPlaces(2);
}

inline void setup_menu_screen_progmem() {
  lql_steam_temp.set_asProgmem(1);
  lql_pipe_temp.set_asProgmem(1);
  lql_water_temp.set_asProgmem(1);
  lql_tank_temp.set_asProgmem(1);
  lql_atm.set_asProgmem(1);
  lql_w_progress.set_asProgmem(1);
  lql_start.set_asProgmem(1);
  lql_pump_speed.set_asProgmem(1);
  lql_pause.set_asProgmem(1);
  lql_reset.set_asProgmem(1);
  lql_get_power.set_asProgmem(1);
  lql_setup.set_asProgmem(1);
  lql_ip.set_asProgmem(1);
  lql_setup_steam_temp.set_asProgmem(1);
  lql_setup_pipe_temp.set_asProgmem(1);
  lql_setup_water_temp.set_asProgmem(1);
  lql_setup_tank_temp.set_asProgmem(1);
  lql_setup_set_steam_temp.set_asProgmem(1);
  lql_setup_set_pipe_temp.set_asProgmem(1);
  lql_setup_set_water_temp.set_asProgmem(1);
  lql_setup_set_tank_temp.set_asProgmem(1);
  lql_setup_stepper_stepper_step_ml.set_asProgmem(1);
  lql_setup_stepper_calibrate.set_asProgmem(1);
  lql_setup_stepper_program.set_asProgmem(1);
  lql_setup_program_WType.set_asProgmem(1);
  lql_setup_program_Volume.set_asProgmem(1);
  lql_setup_program_Speed.set_asProgmem(1);
  lql_setup_program_capacity_num.set_asProgmem(1);
  lql_setup_program_Temp.set_asProgmem(1);
  lql_setup_program_Power.set_asProgmem(1);
  lql_setup_program_reset_wifi.set_asProgmem(1);
  lql_setup_program_back_line.set_asProgmem(1);
}

inline void register_menu_screens() {
  main_menu1.add_screen(welcome_screen);
  main_menu1.add_screen(main_screen);
  main_menu1.add_screen(main_screen1);
  main_menu1.add_screen(main_screen2);
  main_menu1.add_screen(main_screen4);
  main_menu1.add_screen(main_screen5);
  main_menu1.add_screen(setup_temp_screen);
  main_menu1.add_screen(setup_set_temp_screen);
  main_menu1.add_screen(setup_stepper_settings);
  main_menu1.add_screen(setup_back_screen);
  main_menu1.add_screen(setup_program_settings);
  main_menu1.add_screen(setup_program_back);
}

#endif
