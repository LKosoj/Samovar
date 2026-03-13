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
#include "ui/menu/actions.h"
#include <LiquidCrystal_I2C.h>
#include <LiquidMenu.h>
#include <Arduino.h>
#include <EEPROM.h>

#ifdef USE_MQTT
#include "SamovarMqtt.h"
#endif

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
