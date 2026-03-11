#include <Arduino.h>
#include <EEPROM.h>

#include "Samovar.h"
#include "modes/beer/beer_program_codec.h"
#include "modes/dist/dist_program_codec.h"
#include "modes/nbk/nbk_program_codec.h"
#include "modes/rect/rect_program_codec.h"
#include "state/globals.h"
#include "support/process_math.h"
#include "SPIFFSEditor.h"

const char *http_username = "admin";
const char *http_password = "admin";

int get_liquid_volume();
inline String format_float(float v, int d);
void SendMsg(const String& m, MESSAGE_TYPE msg_type);
void read_config();
String get_prf_name();
void save_profile_nvs();

//format bytes
String formatBytes(size_t bytes) {
  if (bytes < 1024) {
    return String(bytes) + "B";
  } else if (bytes < (1024 * 1024)) {
    return String(bytes / 1024.0) + "KB";
  } else if (bytes < (1024 * 1024 * 1024)) {
    return String(bytes / 1024.0 / 1024.0) + "MB";
  } else {
    return String(bytes / 1024.0 / 1024.0 / 1024.0) + "GB";
  }
}

//String get_edit_script(){
//  File f = SPIFFS.open("/edit.htm");
//  if (f) {
//    //нашли файл со скриптом, выполняем
//    String s;
//    s = f.readString();
//    f.close();
//    return s;
//  }
//  return "";
//}

bool exists(String path) {
  File file = SPIFFS.open(path, "r");
  bool yes = file && !file.isDirectory();
  file.close();
  return yes;
}

void save_profile() {
  save_profile_nvs();
}

void load_profile() {
  read_config();
}

String get_prf_name() {
  String fl;
  if (Samovar_CR_Mode == SAMOVAR_BEER_MODE) {
    fl = "/beer.prf";
  } else if (Samovar_CR_Mode == SAMOVAR_DISTILLATION_MODE) {
    fl = "/dist.prf";
  } else if (Samovar_CR_Mode == SAMOVAR_BK_MODE) {
    fl = "/bk.prf";
  } else if (Samovar_CR_Mode == SAMOVAR_NBK_MODE) {
    fl = "/nbk.prf";
  } else {
    fl = "/rectificat.prf";
  }
  return fl;
}
