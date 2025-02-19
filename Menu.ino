#include "Samovar.h"
#include <LiquidCrystal_I2C.h>
#include <LiquidMenu.h>
#include <Arduino.h>
#include <EEPROM.h>
#include <ESPAsyncWiFiManager.h>

#ifdef USE_MQTT
#include "SamovarMqtt.h"
#endif

void read_config();
void run_program(uint8_t num);
void set_menu_screen(uint8_t param);
void save_profile();
void set_pump_speed(float speed, bool continue_process);
float get_speed_from_rate(float rate);
void pump_calibrate(int stpspeed);
void pause_withdrawal(bool Pause);
void set_pump_pwm(float duty);
void set_pump_speed_pid(float temp);
void set_power(bool On);
void set_buzzer(bool fl);
bool check_boiling();
float get_alcohol(float t);
void check_power_error();
bool column_wetting();
void reset_sensor_counter();
void set_capacity(uint8_t cap);
void set_program(String WProgram);
String get_program(uint8_t s);
void create_data();

const char str_BACK[] PROGMEM = "<BACK";
const char str_Steam_T[] PROGMEM = "Steam T: ";
const char str_Pipe_T[] PROGMEM = "Pipe T: ";
const char str_Water_T[] PROGMEM = "Water T: ";
const char str_Tank_T[] PROGMEM = "Tank T: ";
const char str_Pressure[] PROGMEM = "Atm: ";
const char str_Progress[] PROGMEM = "Progress: ";
const char str_Start[] PROGMEM = ">Start: ";
const char str_Speed[] PROGMEM = ">Speed l/h: ";
const char str_Pause[] PROGMEM = ">Pause: ";
const char str_Reset_W[] PROGMEM = ">Reset withdrawal: ";
const char str_Get_Power[] PROGMEM = ">Get power ";
const char str_Setup[] PROGMEM = "/Setup";
const char str_IP[] PROGMEM = "IP: ";
const char str_Set_Steam_T[] PROGMEM = "Set Steam T: ";
const char str_Set_Pipe_T[] PROGMEM = "Set Pipe T: ";
const char str_Set_Water_T[] PROGMEM = "Set Water T: ";
const char str_Set_Tank_T[] PROGMEM = "Set Tank T: ";
const char str_Step_Ml[] PROGMEM = "^Step/ml: ";
const char str_Calibrate[] PROGMEM = ">Calibrate: ";
const char str_Program[] PROGMEM = "Prog>";
const char str_Type[] PROGMEM = "^Type: ";
const char str_Volume[] PROGMEM = "^Volume: ";
const char str_Capacity[] PROGMEM = "^Capacity: ";
const char str_Temp[] PROGMEM = "^Temp: ";
const char str_Power[] PROGMEM = "^Power: ";
const char str_Reset_WiFi[] PROGMEM = ">Reset WiFi";

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

LiquidLine lql_back_line(0, 10, str_BACK);
LiquidLine lql_time(0, 10, get_timestr);

LiquidLine welcome_line1(0, 0, get_welcomeStr1);
LiquidLine welcome_line2(0, 1, get_welcomeStr2);
LiquidLine welcome_line3(0, 2, get_welcomeStr3);
LiquidLine welcome_line4(0, 3, get_welcomeStr4);
LiquidScreen welcome_screen(welcome_line1, welcome_line2, welcome_line3, welcome_line4);

LiquidLine lql_steam_temp(0, 0, str_Steam_T, SteamSensor.avgTemp);
LiquidLine lql_pipe_temp(0, 1, str_Pipe_T, PipeSensor.avgTemp);
LiquidLine lql_water_temp(0, 2, str_Water_T, WaterSensor.avgTemp);
LiquidScreen main_screen(lql_steam_temp, lql_pipe_temp, lql_water_temp, lql_time);

LiquidLine lql_tank_temp(0, 0, str_Tank_T, TankSensor.avgTemp);
LiquidLine lql_atm(0, 1, str_Pressure, bme_pressure);
LiquidLine lql_w_progress(0, 2, str_Progress, WthdrwlProgress);
LiquidScreen main_screen1(lql_tank_temp, lql_atm, lql_w_progress, lql_time);

LiquidLine lql_start(0, 0, str_Start, get_startval_text);
LiquidLine lql_pump_speed(0, 1, str_Speed, ActualVolumePerHour);
LiquidLine lql_pause(0, 2, str_Pause, get_pause_text);
LiquidLine lql_reset(0, 3, str_Reset_W);
LiquidScreen main_screen2(lql_start, lql_pump_speed, lql_pause, lql_reset);

LiquidLine lql_get_power(0, 0, str_Get_Power, get_power_text);
LiquidLine lql_setup(0, 1, str_Setup);
LiquidLine lql_ip(0, 2, str_IP, get_ipstr);
LiquidScreen main_screen4(lql_get_power, lql_setup, lql_ip, lql_time);

LiquidScreen main_screen5(lql_tank_temp, lql_atm, lql_water_temp, lql_time);

LiquidLine lql_setup_steam_temp(0, 0, str_Steam_T, SamSetup.DeltaSteamTemp);
LiquidLine lql_setup_pipe_temp(0, 1, str_Pipe_T, SamSetup.DeltaPipeTemp);
LiquidLine lql_setup_water_temp(0, 2, str_Water_T, SamSetup.DeltaWaterTemp);
LiquidLine lql_setup_tank_temp(0, 3, str_Tank_T, SamSetup.DeltaTankTemp);
LiquidScreen setup_temp_screen(lql_setup_steam_temp, lql_setup_pipe_temp, lql_setup_water_temp, lql_setup_tank_temp);

LiquidLine lql_setup_set_steam_temp(0, 0, str_Set_Steam_T, SamSetup.SetSteamTemp);
LiquidLine lql_setup_set_pipe_temp(0, 1, str_Set_Pipe_T, SamSetup.SetPipeTemp);
LiquidLine lql_setup_set_water_temp(0, 2, str_Set_Water_T, SamSetup.SetWaterTemp);
LiquidLine lql_setup_set_tank_temp(0, 3, str_Set_Tank_T, SamSetup.SetTankTemp);
LiquidScreen setup_set_temp_screen(lql_setup_set_steam_temp, lql_setup_set_pipe_temp, lql_setup_set_water_temp, lql_setup_set_tank_temp);

LiquidLine lql_setup_stepper_stepper_step_ml(0, 0, str_Step_Ml, SamSetup.StepperStepMl);
LiquidLine lql_setup_stepper_calibrate(0, 1, str_Calibrate, get_calibrate_text);
LiquidLine lql_setup_stepper_program(0, 2, str_Program);
LiquidScreen setup_stepper_settings(lql_setup_stepper_stepper_step_ml, lql_setup_stepper_calibrate, lql_setup_stepper_program, lql_time);

LiquidLine lql_setup_program_WType(0, 0, str_Type, program[0].WType);
LiquidLine lql_setup_program_Volume(0, 1, str_Volume, program[0].Volume);
LiquidLine lql_setup_program_Speed(0, 2, str_Speed, program[0].Speed);
LiquidLine lql_setup_program_capacity_num(0, 3, str_Capacity, program[0].capacity_num);
LiquidLine lql_setup_program_Temp(0, 4, str_Temp, program[0].Temp);
LiquidLine lql_setup_program_Power(0, 5, str_Power, program[0].Power);
LiquidScreen setup_program_settings(lql_setup_program_WType, lql_setup_program_Volume, lql_setup_program_Speed, lql_setup_program_capacity_num);

LiquidLine lql_setup_program_reset_wifi(0, 0, str_Reset_WiFi);
LiquidLine lql_setup_program_back_line(0, 1, str_BACK);
LiquidScreen setup_program_back(lql_setup_program_reset_wifi, lql_setup_program_back_line, lql_time);

LiquidScreen setup_back_screen(lql_back_line, lql_time);

//LiquidMenu setup_menu(lcd);


//LiquidSystem menu(main_menu, setup_menu, 1);

#define LCD_UPDATE_TIMEOUT 200

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

void reset_focus() {
  if ( xSemaphoreTake( xI2CSemaphore, ( TickType_t ) (LCD_UPDATE_TIMEOUT / portTICK_RATE_MS)) == pdTRUE) {
    //return;
    do {
      main_menu1.switch_focus();
    } while (main_menu1.is_callable(1));
    xSemaphoreGive(xI2CSemaphore);
  }
}

void change_screen(LiquidScreen* screen) {
  if ( xSemaphoreTake( xI2CSemaphore, ( TickType_t ) (LCD_UPDATE_TIMEOUT / portTICK_RATE_MS)) == pdTRUE) {
    main_menu1.change_screen(screen);
    xSemaphoreGive(xI2CSemaphore);
  }
}

void menu_update() {
  if ( xSemaphoreTake( xI2CSemaphore, ( TickType_t ) (LCD_UPDATE_TIMEOUT / portTICK_RATE_MS)) == pdTRUE) {
    main_menu1.update();
    xSemaphoreGive(xI2CSemaphore);
  }
}

void menu_softUpdate() {
  if ( xSemaphoreTake( xI2CSemaphore, ( TickType_t ) (LCD_UPDATE_TIMEOUT / portTICK_RATE_MS)) == pdTRUE) {
    main_menu1.softUpdate();
    xSemaphoreGive(xI2CSemaphore);
  }
}

void menu_previous_screen() {
  if ( xSemaphoreTake( xI2CSemaphore, ( TickType_t ) (LCD_UPDATE_TIMEOUT / portTICK_RATE_MS)) == pdTRUE) {
    main_menu1.previous_screen();
    xSemaphoreGive(xI2CSemaphore);
  }
}

void menu_next_screen() {
  if ( xSemaphoreTake( xI2CSemaphore, ( TickType_t ) (LCD_UPDATE_TIMEOUT / portTICK_RATE_MS)) == pdTRUE) {
    main_menu1.next_screen();
    xSemaphoreGive(xI2CSemaphore);
  }
}

void menu_switch_focus() {
  if ( xSemaphoreTake( xI2CSemaphore, ( TickType_t ) (LCD_UPDATE_TIMEOUT / portTICK_RATE_MS)) == pdTRUE) {
    main_menu1.switch_focus();
    xSemaphoreGive(xI2CSemaphore);
  }
}

void menu_reset_lcd() {
  if ( xSemaphoreTake( xI2CSemaphore, ( TickType_t ) (LCD_UPDATE_TIMEOUT / portTICK_RATE_MS)) == pdTRUE) {
    lcd.begin(20, 4);
    lcd.init();
    xSemaphoreGive(xI2CSemaphore);
  }
}

void set_menu_screen(uint8_t param) {
  switch (param) {
    case 1:  //меню установок
      setup_temp_screen.hide(false);
      setup_set_temp_screen.hide(false);
      setup_stepper_settings.hide(false);
      setup_back_screen.hide(false);
      main_screen.hide(true);
      main_screen1.hide(true);
      main_screen2.hide(true);
      main_screen4.hide(true);
      main_screen5.hide(true);
      setup_program_settings.hide(true);
      setup_program_back.hide(true);
      //main_menu1.switch_focus();
      change_screen(&setup_temp_screen);
      break;
    case 2:  //основное меню после включения колонны
      setup_set_temp_screen.hide(true);
      setup_temp_screen.hide(true);
      setup_stepper_settings.hide(true);
      setup_back_screen.hide(true);
      setup_program_settings.hide(true);
      setup_program_back.hide(true);
      main_screen.hide(false);
      main_screen1.hide(false);
      main_screen2.hide(false);
      main_screen4.hide(false);
      main_screen5.hide(true);
      //main_menu1.switch_focus();
      change_screen(&main_screen);
      break;
    case 3:  //основное меню до включения колонны
      setup_set_temp_screen.hide(true);
      setup_temp_screen.hide(true);
      setup_stepper_settings.hide(true);
      setup_back_screen.hide(true);
      setup_program_settings.hide(true);
      setup_program_back.hide(true);
      main_screen.hide(false);
      main_screen1.hide(false);
      main_screen2.hide(true);
      main_screen4.hide(false);
      main_screen5.hide(true);
      //main_menu1.switch_focus();
      change_screen(&main_screen);
      break;
    case 4:  //меню установки программ
      setup_set_temp_screen.hide(true);
      setup_temp_screen.hide(true);
      setup_stepper_settings.hide(true);
      setup_back_screen.hide(true);
      main_screen.hide(true);
      main_screen1.hide(true);
      main_screen2.hide(true);
      main_screen4.hide(true);
      main_screen5.hide(true);
      setup_program_settings.hide(false);
      setup_program_back.hide(false);
      //main_menu1.switch_focus();
      change_screen(&setup_program_settings);
      break;
  }
  /*
      if ((param == 3 || param == 2) && Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
      main_screen.hide(true);
      main_screen1.hide(true);
      main_screen2.hide(true);
      main_screen5.hide(false);
      change_screen(&main_screen5);
    }
  */
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
  save_profile();
  read_config();
  // Данная функция ссылается на необходимое меню.
  //main_menu1.change_menu(main_menu);
}

void writeString(String Str, uint8_t num) {
  switch (num) {
    case 1:
      Str.toCharArray(welcomeStrArr1, 20);
      break;
    case 2:
      Str.toCharArray(welcomeStrArr2, 20);
      break;
    case 3:
      Str.toCharArray(welcomeStrArr3, 20);
      break;
    case 4:
      Str.toCharArray(welcomeStrArr4, 20);
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
  AsyncWiFiManager wifiManager(&server, &dns);
  wifiManager.resetSettings();
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
  if (PauseOn) pause_text_ptr = (char *)"Continue";
  else {
    pause_text_ptr = (char *)"Pause";
    t_min = 0;
    program_Wait = false;
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
    calibrate_text_ptr = (char *)"Stop";
    stpspeed = 0;
  } else {
    startval = 100;
    calibrate_text_ptr = (char *)"Start";
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
    Str = "Prg No 1";
    run_program(0);
    ProgramNum = 0;
    create_data();  //создаем файл с данными
  } else if (startval == 1) {
    ProgramNum++;
    Str = "Prg No " + (String)(ProgramNum + 1);
    run_program(ProgramNum);
  } else if (startval == 2) {
    Str = "Prg finish";
    run_program(CAPACITY_NUM * 2);
  } else {
    Str = "Stoped";
    run_program(CAPACITY_NUM * 2);
    reset_sensor_counter();
  }
  Str.toCharArray(startval_text_val, 20);
  reset_focus();
  menu_update();
}

void samovar_reset() {
  char str[20] = "Stoped             ";
  memcpy(str, startval_text_val, 20);
  power_text_ptr = (char *)"ON";
  reset_focus();
  set_menu_screen(3);
  reset_sensor_counter();
  sam_command_sync = SAMOVAR_NONE;
}

void setupMenu() {

  lcd.init();
  lcd.begin(LCD_COLUMNS, LCD_ROWS);
  lcd.backlight();
  lcd.clear();

  //  setup_program_settings.add_line(lql_setup_program_Temp);
  //  setup_program_settings.add_line(lql_setup_program_Power);
  //  setup_program_settings.set_displayLineCount(6);

  //setup_temp_screen.set_displayLineCount(4);
  lql_steam_temp.set_decimalPlaces(2);
  lql_setup_pipe_temp.set_decimalPlaces(2);
  lql_setup_water_temp.set_decimalPlaces(2);
  lql_setup_tank_temp.set_decimalPlaces(2);
  lql_pump_speed.set_decimalPlaces(2);

  // Function to attach functions to LiquidLine objects.
  lql_start.attach_function(1, menu_samovar_start);
  lql_start.attach_function(2, menu_samovar_start);
  lql_reset.attach_function(1, samovar_reset);
  lql_reset.attach_function(2, samovar_reset);

  lql_pump_speed.attach_function(1, menu_pump_speed_up);
  lql_pump_speed.attach_function(2, menu_pump_speed_down);

  lql_setup.attach_function(1, menu_setup);
  lql_setup.attach_function(2, menu_setup);

  lql_setup_steam_temp.attach_function(1, set_delta_steam_temp_up);
  lql_setup_steam_temp.attach_function(2, set_delta_steam_temp_down);
  lql_setup_pipe_temp.attach_function(1, set_delta_pipe_temp_up);
  lql_setup_pipe_temp.attach_function(2, set_delta_pipe_temp_down);
  lql_setup_water_temp.attach_function(1, set_delta_water_temp_up);
  lql_setup_water_temp.attach_function(2, set_delta_water_temp_down);
  lql_setup_tank_temp.attach_function(1, set_delta_tank_temp_up);
  lql_setup_tank_temp.attach_function(2, set_delta_tank_temp_down);

  lql_setup_set_steam_temp.attach_function(1, set_delta_set_steam_temp_up);
  lql_setup_set_steam_temp.attach_function(2, set_delta_set_steam_temp_down);
  lql_setup_set_pipe_temp.attach_function(1, set_delta_set_pipe_temp_up);
  lql_setup_set_pipe_temp.attach_function(2, set_delta_set_pipe_temp_down);
  lql_setup_set_water_temp.attach_function(1, set_delta_set_water_temp_up);
  lql_setup_set_water_temp.attach_function(2, set_delta_set_water_temp_down);
  lql_setup_set_tank_temp.attach_function(1, set_delta_set_tank_temp_up);
  lql_setup_set_tank_temp.attach_function(2, set_delta_set_tank_temp_down);

  lql_setup_stepper_stepper_step_ml.attach_function(1, stepper_step_ml_up);
  lql_setup_stepper_stepper_step_ml.attach_function(2, stepper_step_ml_down);
  lql_setup_stepper_calibrate.attach_function(1, menu_calibrate);
  lql_setup_stepper_calibrate.attach_function(2, menu_calibrate_down);
  lql_setup_stepper_program.attach_function(1, menu_program);
  lql_setup_stepper_program.attach_function(2, menu_program);
  lql_setup_program_back_line.attach_function(1, menu_program_back);
  lql_setup_program_back_line.attach_function(2, menu_program_back);
  lql_setup_program_reset_wifi.attach_function(1, menu_reset_wifi);
  lql_setup_program_reset_wifi.attach_function(2, menu_reset_wifi);

  lql_back_line.attach_function(1, setup_go_back);
  lql_back_line.attach_function(2, setup_go_back);

  lql_get_power.attach_function(1, menu_get_power);
  lql_get_power.attach_function(2, menu_get_power);

  lql_pause.attach_function(1, menu_pause);
  lql_pause.attach_function(2, menu_pause);



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


  main_menu1.add_screen(welcome_screen);
  main_menu1.add_screen(main_screen);
  main_menu1.add_screen(main_screen1);
  main_menu1.add_screen(main_screen2);
  main_menu1.add_screen(main_screen4);
  main_menu1.add_screen(main_screen5);

  //setup_menu.add_screen(setup_temp_screen);
  //setup_menu.add_screen(setup_stepper_settings);
  //setup_menu.add_screen(setup_back_screen);
  main_menu1.add_screen(setup_temp_screen);
  main_menu1.add_screen(setup_set_temp_screen);
  main_menu1.add_screen(setup_stepper_settings);
  main_menu1.add_screen(setup_back_screen);
  main_menu1.add_screen(setup_program_settings);
  main_menu1.add_screen(setup_program_back);

  set_menu_screen(3);
  change_screen(&welcome_screen);

  menu_update();
  welcome_screen.hide(true);
}

void encoder_getvalue() {

  bool updscreen = true;

  encoder.tick();
  // Check all the buttons
  if (encoder.isRight()) {
    multiplier = 1;
    //Если калибровка - энкодером регулируем скорость шагового двигателя
    if (startval == 100) {
      menu_calibrate();
      //updscreen = false;
      return;
    }
    if (!main_menu1.is_callable(1)) {
      updscreen = false;
      menu_next_screen();
    } else {
      updscreen = false;
      main_menu1.call_function(1);
      vTaskDelay(5 / portTICK_PERIOD_MS);
    }
  } else if (encoder.isLeft()) {
    multiplier = 1;
    //Если калибровка - энкодером регулируем скорость шагового двигателя
    if (startval == 100) {
      //updscreen = false;
      menu_calibrate_down();
      return;
    }
    if (!main_menu1.is_callable(2)) {
      updscreen = false;
      menu_previous_screen();
    } else {
      updscreen = false;
      main_menu1.call_function(2);
      vTaskDelay(5 / portTICK_PERIOD_MS);
    }
  } else if (encoder.isRightH()) {
    multiplier = 10;
    updscreen = false;
    main_menu1.call_function(1);
  } else if (encoder.isLeftH()) {
    multiplier = 10;
    updscreen = false;
    main_menu1.call_function(2);
  } else if (encoder.isClick()) {
    //Выход из режима калибровки - нажатие на кнопку.
    if (startval == 100) {
      startval = 0;
      menu_calibrate();
    }
    updscreen = false;
    menu_switch_focus();
  }

  CurMin = (millis() / 1000);
  if (OldMin != CurMin) {
    //периодически инициализируем дисплей, так как он может слетать из-за рассинхронизации I2C
    if (CurMin == 120) {
      menu_reset_lcd();
    }


    //    tcnt++;
    //    if (tcnt == 3) {
    //      tcnt = 0;
    //      BME_getvalue(false);
    //    }

    if (updscreen) menu_softUpdate();

    OldMin = CurMin;
  }
}
