#ifndef __SAMOVAR_UI_MENU_INPUT_H_
#define __SAMOVAR_UI_MENU_INPUT_H_

#include <Arduino.h>

#include "ui/menu/screens.h"

#ifndef LCD_UPDATE_TIMEOUT
#define LCD_UPDATE_TIMEOUT 200
#endif

void samovar_reset();
void menu_samovar_start();
void menu_pump_speed_up();
void menu_pump_speed_down();
void menu_setup();
void set_delta_steam_temp_up();
void set_delta_steam_temp_down();
void set_delta_pipe_temp_up();
void set_delta_pipe_temp_down();
void set_delta_water_temp_up();
void set_delta_water_temp_down();
void set_delta_tank_temp_up();
void set_delta_tank_temp_down();
void set_delta_set_steam_temp_up();
void set_delta_set_steam_temp_down();
void set_delta_set_pipe_temp_up();
void set_delta_set_pipe_temp_down();
void set_delta_set_water_temp_up();
void set_delta_set_water_temp_down();
void set_delta_set_tank_temp_up();
void set_delta_set_tank_temp_down();
void stepper_step_ml_up();
void stepper_step_ml_down();
void menu_calibrate();
void menu_calibrate_down();
void menu_program();
void menu_program_back();
void menu_reset_wifi();
void setup_go_back();
void menu_get_power();
void menu_pause();

inline void reset_focus() {
  if (xSemaphoreTake(xI2CSemaphore, (TickType_t)(LCD_UPDATE_TIMEOUT / portTICK_RATE_MS)) == pdTRUE) {
    do {
      main_menu1.switch_focus();
    } while (main_menu1.is_callable(1));
    xSemaphoreGive(xI2CSemaphore);
  }
}

inline void menu_previous_screen() {
  if (xSemaphoreTake(xI2CSemaphore, (TickType_t)(LCD_UPDATE_TIMEOUT / portTICK_RATE_MS)) == pdTRUE) {
    main_menu1.previous_screen();
    xSemaphoreGive(xI2CSemaphore);
  }
}

inline void menu_next_screen() {
  if (xSemaphoreTake(xI2CSemaphore, (TickType_t)(LCD_UPDATE_TIMEOUT / portTICK_RATE_MS)) == pdTRUE) {
    main_menu1.next_screen();
    xSemaphoreGive(xI2CSemaphore);
  }
}

inline void menu_switch_focus() {
  if (xSemaphoreTake(xI2CSemaphore, (TickType_t)(LCD_UPDATE_TIMEOUT / portTICK_RATE_MS)) == pdTRUE) {
    main_menu1.switch_focus();
    xSemaphoreGive(xI2CSemaphore);
  }
}

inline void menu_reset_lcd() {
  if (xSemaphoreTake(xI2CSemaphore, (TickType_t)(LCD_UPDATE_TIMEOUT / portTICK_RATE_MS)) == pdTRUE) {
    lcd.begin(20, 4);
    lcd.init();
    xSemaphoreGive(xI2CSemaphore);
  }
}

inline void change_screen(LiquidScreen* screen) {
  if (xSemaphoreTake(xI2CSemaphore, (TickType_t)(LCD_UPDATE_TIMEOUT / portTICK_RATE_MS)) == pdTRUE) {
    main_menu1.change_screen(screen);
    xSemaphoreGive(xI2CSemaphore);
  }
}

inline void menu_update() {
  if (xSemaphoreTake(xI2CSemaphore, (TickType_t)(LCD_UPDATE_TIMEOUT / portTICK_RATE_MS)) == pdTRUE) {
    main_menu1.update();
    xSemaphoreGive(xI2CSemaphore);
  }
}

inline void menu_softUpdate() {
  if (xSemaphoreTake(xI2CSemaphore, (TickType_t)(LCD_UPDATE_TIMEOUT / portTICK_RATE_MS)) == pdTRUE) {
    main_menu1.softUpdate();
    xSemaphoreGive(xI2CSemaphore);
  }
}

inline void set_menu_screen(uint8_t param) {
  switch (param) {
    case 1:
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
      change_screen(&setup_temp_screen);
      break;
    case 2:
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
      change_screen(&main_screen);
      break;
    case 3:
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
      change_screen(&main_screen);
      break;
    case 4:
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
      change_screen(&setup_program_settings);
      break;
  }
}

inline void bind_menu_input_handlers() {
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
}

inline void encoder_getvalue() {
  bool updscreen = true;

  if (encoder.isRight()) {
    multiplier = 1;
    if (startval == 100) {
      menu_calibrate();
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
    if (startval == 100) {
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
    if (startval == 100) {
      startval = 0;
      menu_calibrate();
    }
    updscreen = false;
    menu_switch_focus();
  }

  CurMin = (millis() / 1000);
  if (OldMin != CurMin) {
    if (CurMin == 120) {
      menu_reset_lcd();
    }

    if (updscreen) menu_softUpdate();

    OldMin = CurMin;
  }
}

inline void setupMenu() {
  lcd.init();
  lcd.begin(LCD_COLUMNS, LCD_ROWS);
  lcd.backlight();
  lcd.clear();

  setup_menu_screen_decimal_places();
  bind_menu_input_handlers();
  setup_menu_screen_progmem();
  register_menu_screens();

  set_menu_screen(3);
  change_screen(&welcome_screen);

  menu_update();
  welcome_screen.hide(true);
}

#endif
