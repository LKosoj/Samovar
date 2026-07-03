#include <asyncHTTPrequest.h>
//#include <ESPping.h>
#include <WiFi.h>

#include "Samovar.h"
#include "samovar_api.h"
#include "FS.h"
#include "sensorinit.h"
#include "column_math.h"
#include "string_utils.h"
#include "runtime_helpers.h"

extern float nbk_M;
extern float nbk_Mo;
extern float nbk_P;
extern float nbk_Po;

static bool queue_pending_flag(volatile bool& flag) {
  bool locked = pending_command_lock(pdMS_TO_TICKS(50));
  if (!locked) return false;
  if (flag) {
    pending_command_unlock(true);
    return false;
  }
  flag = true;
  pending_command_unlock(true);
  return true;
}

static const uint8_t LOG_FLUSH_READY = 0;
static const uint8_t LOG_FLUSH_QUEUED = 1;
static const uint8_t LOG_FLUSH_BUSY = 2;

static uint8_t schedule_log_flush_if_needed() {
  if (log_flush_seq >= log_write_seq) return LOG_FLUSH_READY;
  bool locked = pending_command_lock(pdMS_TO_TICKS(50));
  if (!locked) return LOG_FLUSH_BUSY;
  uint32_t writeSeq = log_write_seq;
  if (log_flush_seq < writeSeq) {
    pending_log_flush_seq = writeSeq;
    pending_log_flush_flag = true;
    pending_command_unlock(true);
    return LOG_FLUSH_QUEUED;
  }
  pending_command_unlock(true);
  return LOG_FLUSH_READY;
}

static bool queue_pending_bool(volatile bool& flag, volatile bool& valueSlot, bool value) {
  bool locked = pending_command_lock(pdMS_TO_TICKS(50));
  if (!locked) return false;
  if (flag) {
    pending_command_unlock(true);
    return false;
  }
  valueSlot = value;
  __sync_synchronize();
  flag = true;
  pending_command_unlock(true);
  return true;
}

static bool queue_pending_float(volatile bool& flag, volatile float& valueSlot, float value) {
  bool locked = pending_command_lock(pdMS_TO_TICKS(50));
  if (!locked) return false;
  if (flag) {
    pending_command_unlock(true);
    return false;
  }
  valueSlot = value;
  __sync_synchronize();
  flag = true;
  pending_command_unlock(true);
  return true;
}

#ifdef USE_LUA
bool queue_pending_string(volatile bool& flag, String& valueSlot, const String& value) {
  bool locked = pending_command_lock(pdMS_TO_TICKS(50));
  if (!locked) return false;
  if (flag) {
    pending_command_unlock(true);
    return false;
  }
  valueSlot = value;
  __sync_synchronize();
  flag = true;
  pending_command_unlock(true);
  return true;
}
#endif

static PendingProgramMode pending_program_mode_for_samovar_mode(SAMOVAR_MODE mode) {
  switch (mode) {
    case SAMOVAR_BEER_MODE:
      return PPM_BEER;
    case SAMOVAR_DISTILLATION_MODE:
      return PPM_DIST;
    case SAMOVAR_NBK_MODE:
      return PPM_NBK;
    default:
      return PPM_RECT;
  }
}

static bool queue_pending_program(PendingProgramMode mode, const String& programText) {
  bool locked = pending_command_lock(pdMS_TO_TICKS(50));
  if (!locked) return false;
  if (pending_save_profile_flag || pending_program_mode != PPM_NONE) {
    pending_command_unlock(true);
    return false;
  }
  pending_program_str = programText;
  __sync_synchronize();
  pending_program_mode = mode;
  pending_command_unlock(true);
  return true;
}

static bool pending_program_slot_busy() {
  bool locked = pending_command_lock(pdMS_TO_TICKS(50));
  if (!locked) return true;
  bool busy = pending_save_profile_flag || pending_program_mode != PPM_NONE;
  pending_command_unlock(true);
  return busy;
}

static void send_program_json_response(AsyncWebServerRequest *request, uint16_t statusCode, bool ok, const String& err, const String& programText) {
  String json;
  json.reserve(programText.length() + err.length() + 48);
  json += "{\"ok\":";
  json += ok ? "true" : "false";
  json += ",\"err\":";
  json += toJsonString(err);
  json += ",\"program\":";
  json += toJsonString(programText);
  json += "}";
  request->send(statusCode, "application/json", json);
}

static bool reject_program_update_if_busy_json(AsyncWebServerRequest *request) {
  if (pending_program_slot_busy()) {
    send_program_json_response(request, 503, false, F("BUSY: предыдущее изменение программы ещё не применено"), String());
    return true;
  }
  if (program_update_session_active()) {
    send_program_json_response(request, 409, false, F("BUSY: программа не изменена, активна сессия режима"), String());
    return true;
  }
  return false;
}

static bool queue_pending_setup_save(const PendingSetupSave& setupSave,
                                     bool hasProgram,
                                     PendingProgramMode programMode,
                                     const String& programText,
                                     bool hasSwitchMode,
                                     SAMOVAR_MODE switchMode,
                                     const char*& busyText) {
  bool locked = pending_command_lock(pdMS_TO_TICKS(50));
  if (!locked) {
    busyText = "BUSY: не удалось запланировать сохранение настроек";
    return false;
  }
  if (pending_save_profile_flag) {
    pending_command_unlock(true);
    busyText = "BUSY: предыдущее сохранение настроек ещё не применено";
    return false;
  }
  if (pending_program_mode != PPM_NONE) {
    pending_command_unlock(true);
    busyText = "BUSY: предыдущее изменение программы ещё не применено";
    return false;
  }
  if (pending_switch_mode_flag) {
    pending_command_unlock(true);
    busyText = "BUSY: смена режима уже запланирована";
    return false;
  }

  pending_setup_save_buf = setupSave;
  if (hasProgram) {
    pending_program_str = programText;
  }
  if (hasSwitchMode) {
    pending_switch_mode_value = switchMode;
  }
  __sync_synchronize();
  pending_save_profile_flag = true;
  if (hasProgram) {
    pending_program_mode = programMode;
  }
  if (hasSwitchMode) {
    pending_switch_mode_flag = true;
  }
  pending_command_unlock(true);
  return true;
}

static bool queue_pending_i2cpump(const PendingI2CPumpCmd& cmd) {
  bool locked = pending_command_lock(pdMS_TO_TICKS(50));
  if (!locked) return false;
  if (pending_i2cpump_flag) {
    pending_command_unlock(true);
    return false;
  }
  pending_i2cpump_buf = cmd;
  __sync_synchronize();
  pending_i2cpump_flag = true;
  pending_command_unlock(true);
  return true;
}

static bool queue_pending_i2cstepper(const PendingI2CStepperCmd& cmd) {
  bool locked = pending_command_lock(pdMS_TO_TICKS(50));
  if (!locked) return false;
  if (pending_i2cstepper_flag) {
    pending_command_unlock(true);
    return false;
  }
  pending_i2cstepper_buf = cmd;
  __sync_synchronize();
  pending_i2cstepper_flag = true;
  pending_command_unlock(true);
  return true;
}

static bool queue_pending_i2ccal(const PendingI2CCalCmd& cmd) {
  bool locked = pending_command_lock(pdMS_TO_TICKS(50));
  if (!locked) return false;
  if (pending_i2ccal_flag) {
    pending_command_unlock(true);
    return false;
  }
  pending_i2ccal_buf = cmd;
  __sync_synchronize();
  pending_i2ccal_flag = true;
  pending_command_unlock(true);
  return true;
}

I2CStepperDevice* select_i2c_stepper_device(AsyncWebServerRequest *request) {
  String device = request->hasArg("device") ? request->arg("device") : "pump";
  device.toLowerCase();
  if (device == "mixer") return &i2cStepperMixer;
  if (device == "pump") return &i2cStepperPump;
  return nullptr;
}

void apply_i2c_stepper_args(AsyncWebServerRequest *request, I2CStepperDevice& dev) {
  if (request->hasArg("mode")) dev.mode = request->arg("mode").toInt();
  if (request->hasArg("relayMask")) dev.relayMask = request->arg("relayMask").toInt() & 0x0F;
  if (request->hasArg("sensorFlags")) dev.sensorFlags = request->arg("sensorFlags").toInt();
  if (request->hasArg("optionFlags")) dev.optionFlags = request->arg("optionFlags").toInt();
  if (request->hasArg("mixerRpm")) dev.mixerRpm = request->arg("mixerRpm").toInt();
  if (request->hasArg("mixerRunSec")) dev.mixerRunSec = request->arg("mixerRunSec").toInt();
  if (request->hasArg("mixerPauseSec")) dev.mixerPauseSec = request->arg("mixerPauseSec").toInt();
  if (request->hasArg("pumpMlHour")) dev.pumpMlHour = request->arg("pumpMlHour").toInt();
  if (request->hasArg("pumpPauseSec")) dev.pumpPauseSec = request->arg("pumpPauseSec").toInt();
  if (request->hasArg("fillingMl")) dev.fillingMl = request->arg("fillingMl").toInt();
  if (request->hasArg("fillingMlHour")) dev.fillingMlHour = request->arg("fillingMlHour").toInt();
  if (request->hasArg("stepsPerMl")) dev.stepsPerMl = request->arg("stepsPerMl").toInt();
  if (request->hasArg("relay") && request->hasArg("state")) {
    uint8_t relay = request->arg("relay").toInt();
    bool state = request->arg("state").toInt();
    if (relay >= 1 && relay <= 4) {
      if (state) dev.relayMask |= (1 << (relay - 1));
      else dev.relayMask &= ~(1 << (relay - 1));
    }
  }
}

bool i2c_stepper_mode_supported(const I2CStepperDevice& dev) {
  if (dev.mode == I2CSTEP_MODE_MIXER) return (dev.caps & I2CSTEPPER_CAP_MIXER) != 0;
  if (dev.mode == I2CSTEP_MODE_PUMP) return (dev.caps & I2CSTEPPER_CAP_PUMP) != 0;
  if (dev.mode == I2CSTEP_MODE_FILLING) return (dev.caps & I2CSTEPPER_CAP_FILLING) != 0;
  return false;
}

bool i2c_stepper_command_supported(const I2CStepperDevice& dev, const String& cmd) {
  if (cmd == "status") return true;
  if (cmd == "relay") return (dev.caps & I2CSTEPPER_CAP_RELAY) != 0;
  if (cmd == "calstart" || cmd == "calfinish") return (dev.caps & I2CSTEPPER_CAP_FILLING) != 0;
  if (cmd == "apply" || cmd == "save" || cmd == "start") return i2c_stepper_mode_supported(dev);
  if (cmd == "stop") return (dev.caps & (I2CSTEPPER_CAP_MIXER | I2CSTEPPER_CAP_PUMP | I2CSTEPPER_CAP_FILLING)) != 0;
  return false;
}

void send_i2c_stepper_json(AsyncWebServerRequest *request, I2CStepperDevice& dev) {
  AsyncResponseStream *response = request->beginResponseStream("application/json");
  response->print('{');
  response->print("\"present\":"); response->print(dev.present ? 1 : 0);
  response->print(",\"address\":"); response->print(dev.address);
  response->print(",\"role\":"); response->print(dev.role);
  response->print(",\"mode\":"); response->print(dev.mode);
  response->print(",\"caps\":"); response->print(dev.caps);
  response->print(",\"status\":"); response->print(dev.status);
  response->print(",\"error\":"); response->print(dev.error);
  response->print(",\"relayMask\":"); response->print(dev.relayMask);
  response->print(",\"sensorFlags\":"); response->print(dev.sensorFlags);
  response->print(",\"optionFlags\":"); response->print(dev.optionFlags);
  response->print(",\"mixerRpm\":"); response->print(dev.mixerRpm);
  response->print(",\"mixerRunSec\":"); response->print(dev.mixerRunSec);
  response->print(",\"mixerPauseSec\":"); response->print(dev.mixerPauseSec);
  response->print(",\"pumpMlHour\":"); response->print(dev.pumpMlHour);
  response->print(",\"pumpPauseSec\":"); response->print(dev.pumpPauseSec);
  response->print(",\"fillingMl\":"); response->print(dev.fillingMl);
  response->print(",\"fillingMlHour\":"); response->print(dev.fillingMlHour);
  response->print(",\"stepsPerMl\":"); response->print(dev.stepsPerMl);
  response->print(",\"remaining\":"); response->print(dev.remaining);
  response->print(",\"currentSpeed\":"); response->print(dev.currentSpeed);
  response->print('}');
  request->send(response);
}

// filter out specific headers from the incoming request
AsyncHeaderFilterMiddleware headerFilter;

void change_samovar_mode() {
  if (Samovar_Mode < SAMOVAR_RECTIFICATION_MODE || Samovar_Mode > SAMOVAR_LUA_MODE) {
    Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
  }
  Samovar_CR_Mode = Samovar_Mode;
}

const char* get_index_page_path() {
  return mode_page_path(Samovar_Mode);
}

void send_index_template_response(AsyncWebServerRequest *request, const char *spiffsPath, const char *cacheControl) {
  String description;
  if (!copy_session_description(description)) {
    request->send(503, "text/plain", "Runtime state busy");
    return;
  }
  String luaButtonList;
  if (!copy_lua_button_list_cache(luaButtonList)) {
    request->send(503, "text/plain", "Runtime state busy");
    return;
  }
  AsyncWebServerResponse *response = request->beginResponse(SPIFFS, spiffsPath, "text/html", false, [description, luaButtonList](const String &var) -> String {
    return indexKeyProcessorWithSnapshots(var, description, luaButtonList);
  });
  response->addHeader("Cache-Control", cacheControl);
  request->send(response);
}

void send_index_page(AsyncWebServerRequest *request) {
  // Главная страница должна соответствовать сохранённому режиму (SamSetup.Mode).
  // Samovar_Mode может временно расходиться (например, после web_command без обновления SamSetup).
  {
    uint16_t cfgMode = SamSetup.Mode;
    if (cfgMode > (uint16_t)SAMOVAR_LUA_MODE) {
      cfgMode = (uint16_t)SAMOVAR_RECTIFICATION_MODE;
    }
    Samovar_Mode = (SAMOVAR_MODE)cfgMode;
  }
  change_samovar_mode();
  send_index_template_response(request, get_index_page_path(), "no-cache, no-store, must-revalidate");
}

// Прямой GET /distiller.htm|beer.htm|… иначе отдаётся через serveStatic без шаблонизатора — %WProgram% не подставляется, в UI «тип программы» пустой.
void send_mode_specific_htm(AsyncWebServerRequest *request, const char *spiffsPath, SAMOVAR_MODE requiredMode) {
  uint16_t m = SamSetup.Mode;
  if (m > (uint16_t)SAMOVAR_LUA_MODE) {
    m = (uint16_t)SAMOVAR_RECTIFICATION_MODE;
  }
  if (m != (uint16_t)requiredMode) {
    request->redirect("/index.htm");
    return;
  }
  Samovar_Mode = (SAMOVAR_MODE)m;
  change_samovar_mode();
  send_index_template_response(request, spiffsPath, "no-cache, no-store, must-revalidate");
}

// Универсальная функция для обработки файлов с поддержкой gzip
void handleFileWithGzip(AsyncWebServerRequest *request, const String &path, const String &contentType, const String &cacheControl = "max-age=5000") {
  if(request->header("Accept-Encoding").indexOf("gzip") != -1 && SPIFFS.exists(path + ".gz")) {
    AsyncWebServerResponse *response = request->beginResponse(SPIFFS, path + ".gz", contentType.c_str());
    response->addHeader("Content-Encoding", "gzip");
    response->addHeader("Cache-Control", cacheControl.c_str());
    request->send(response);
  } else if(SPIFFS.exists(path)) {
    AsyncWebServerResponse *response = request->beginResponse(SPIFFS, path, contentType.c_str());
    response->addHeader("Cache-Control", cacheControl.c_str());
    request->send(response);
  } else {
    request->send(404, "text/plain", "File not found");
  }
}

void WebServerInit(void) {

  FS_init();  // Включаем работу с файловой системой

//  HeaderFreeMiddleware spiffsHeaderFree;
//  spiffsHeaderFree.keep("If-Modified-Since");
//  spiffsHeaderFree.keep("Host");
//  // Add any other headers you need to keep
//
//  // Then either add it globally
//  server.addMiddleware(&spiffsHeaderFree);


  server.on("/", HTTP_GET | HTTP_POST, [](AsyncWebServerRequest* request) {
    request->redirect("/index.htm");
  });
  
  server.on("/style.css", HTTP_GET, [](AsyncWebServerRequest *request) {
    handleFileWithGzip(request, "/style.css", "text/css", "max-age=5000");
  });
  //server.serveStatic("/style.css", SPIFFS, "/style.css").setCacheControl("max-age=5000");
  server.on("/minus.png", HTTP_GET, [](AsyncWebServerRequest *request) {
    if (!SPIFFS.exists("/minus.png")) { request->send(404, "text/plain", "Missing /minus.png"); return; }
    AsyncWebServerResponse *response = request->beginResponse(SPIFFS, "/minus.png", emptyString, false, nullptr);
    response->addHeader("Cache-Control", "max-age=604800");
    request->send(response);
  });
  server.on("/plus.png", HTTP_GET, [](AsyncWebServerRequest *request) {
    if (!SPIFFS.exists("/plus.png")) { request->send(404, "text/plain", "Missing /plus.png"); return; }
    AsyncWebServerResponse *response = request->beginResponse(SPIFFS, "/plus.png", emptyString, false, nullptr);
    response->addHeader("Cache-Control", "max-age=614800");
    request->send(response);
  });
  server.on("/favicon.ico", HTTP_GET, [](AsyncWebServerRequest *request) {
    if (!SPIFFS.exists("/favicon.ico")) { request->send(404, "text/plain", "Missing /favicon.ico"); return; }
    AsyncWebServerResponse *response = request->beginResponse(SPIFFS, "/favicon.ico", emptyString, false, nullptr);
    response->addHeader("Cache-Control", "max-age=624800");
    request->send(response);
  });

  server.on("/Red_light.gif", HTTP_GET, [](AsyncWebServerRequest *request) {
    if (!SPIFFS.exists("/Red_light.gif")) { request->send(404, "text/plain", "Missing /Red_light.gif"); return; }
    AsyncWebServerResponse *response = request->beginResponse(SPIFFS, "/Red_light.gif", emptyString, false, nullptr);
    response->addHeader("Cache-Control", "max-age=634800");
    request->send(response);
  });
  server.on("/Green.png", HTTP_GET, [](AsyncWebServerRequest *request) {
    if (!SPIFFS.exists("/Green.png")) { request->send(404, "text/plain", "Missing /Green.png"); return; }
    AsyncWebServerResponse *response = request->beginResponse(SPIFFS, "/Green.png", emptyString, false, nullptr);
    response->addHeader("Cache-Control", "max-age=644800");
    request->send(response);
  });

  //  server.serveStatic("/style.css", SPIFFS, "/style.css");
  //  server.serveStatic("/Red_light.gif", SPIFFS, "/Red_light.gif");
  //  server.serveStatic("/Green.png", SPIFFS, "/Green.png");
  //  server.serveStatic("/minus.png", SPIFFS, "/minus.png");
  //  server.serveStatic("/plus.png", SPIFFS, "/plus.png");
  //  server.serveStatic("/favicon.ico", SPIFFS, "/favicon.ico");

  server.serveStatic("/alarm.mp3", SPIFFS, "/alarm.mp3");
  server.serveStatic("/resetreason.css", SPIFFS, "/resetreason.css").setCacheControl("max-age=1");
  server.serveStatic("/data_old.csv", SPIFFS, "/data_old.csv").setCacheControl("max-age=1");
  server.serveStatic("/prg.csv", SPIFFS, "/prg.csv").setCacheControl("max-age=1");
  server.serveStatic("/state.csv", SPIFFS, "/state.csv").setCacheControl("max-age=1");
  server.serveStatic("/program.htm", SPIFFS, "/program.htm").setTemplateProcessor(indexKeyProcessor).setCacheControl("max-age=1");
  server.on("/chart.htm", HTTP_GET, [](AsyncWebServerRequest *request) {
    send_index_template_response(request, "/chart.htm", "max-age=1");
  });
  server.serveStatic("/calibrate.htm", SPIFFS, "/calibrate.htm").setTemplateProcessor(calibrateKeyProcessor).setCacheControl("max-age=800");
  server.serveStatic("/i2cstepper.htm", SPIFFS, "/i2cstepper.htm").setTemplateProcessor(indexKeyProcessor).setCacheControl("max-age=1");
  server.serveStatic("/manual.htm", SPIFFS, "/manual.htm").setCacheControl("max-age=800");
  server.on("/pong.htm", HTTP_GET, [](AsyncWebServerRequest *request) {
    request->send(200, "text/html; charset=utf-8",
      F("<!DOCTYPE html><html lang=\"ru\"><head><meta charset=\"UTF-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">"
        "<title>Samovar alarm</title><link rel=\"stylesheet\" href=\"style.css\">"
        "</head><body><main><h1>Samovar alarm</h1>"
        "<audio controls autoplay src=\"/alarm.mp3\"></audio>"
        "</main></body></html>"));
  });
  server.serveStatic("/program_fruit.txt", SPIFFS, "/program_fruit.txt").setCacheControl("max-age=1");
  server.serveStatic("/program_grain.txt", SPIFFS, "/program_grain.txt").setCacheControl("max-age=1");
  server.serveStatic("/program_shugar.txt", SPIFFS, "/program_shugar.txt").setCacheControl("max-age=1");
  server.serveStatic("/brewxml.htm", SPIFFS, "/brewxml.htm").setTemplateProcessor(indexKeyProcessor).setCacheControl("max-age=1");
  server.serveStatic("/test.txt", SPIFFS, "/test.txt").setTemplateProcessor(indexKeyProcessor);
  server.serveStatic("/setup.htm", SPIFFS, "/setup.htm").setTemplateProcessor(setupKeyProcessor).setCacheControl("max-age=1");
  //server.serveStatic("/edit", SPIFFS, "/edit.htm");
  // SPIFFSEditor уже обрабатывает /edit с поддержкой gzip в FS.ino

  //#ifdef USE_LUA
  //  server.serveStatic("/btn_button1.lua", SPIFFS, "/btn_button1.lua");
  //  server.serveStatic("/btn_button2.lua", SPIFFS, "/btn_button2.lua");
  //  server.serveStatic("/btn_button3.lua", SPIFFS, "/btn_button3.lua");
  //  server.serveStatic("/btn_button4.lua", SPIFFS, "/btn_button4.lua");
  //  server.serveStatic("/btn_button5.lua", SPIFFS, "/btn_button5.lua");
  //#endif

  server.on("/index.htm", HTTP_GET, [](AsyncWebServerRequest *request) {
    send_index_page(request);
  });

  server.on("/rrlog", HTTP_GET, [](AsyncWebServerRequest *request) {
    request->send(SPIFFS, "/resetreason.css", String());
  });
  // GET|HEAD: chart page и браузеры могут запрашивать HEAD; только GET давал 501 «Handler did not handle».
  // Если лога ещё нет — beginResponse(nullptr) → тот же 501; отдаём пустой CSV с заголовком как в FS.ino.
  server.on("/data.csv", (WebRequestMethodComposite)(HTTP_GET | HTTP_HEAD), [](AsyncWebServerRequest *request) {
    if (schedule_log_flush_if_needed() != LOG_FLUSH_READY) {
      request->send(503, "text/plain", "BUSY");
      return;
    }
    if (!SPIFFS.exists("/data.csv")) {
#ifdef WRITE_PROGNUM_IN_LOG
      request->send(200, "text/csv; charset=utf-8", "Date,Steam,Pipe,Water,Tank,Pressure,ProgNum\r\n");
#else
      request->send(200, "text/csv; charset=utf-8", "Date,Steam,Pipe,Water,Tank,Pressure\r\n");
#endif
      return;
    }
    request->send(SPIFFS, "/data.csv", "text/csv; charset=utf-8");
  });
  server.on("/ajax", HTTP_GET, [](AsyncWebServerRequest *request) {
    send_ajax_json(request);
  });
  server.on("/command", HTTP_POST, [](AsyncWebServerRequest *request) {
    web_command(request);
  });
  server.on("/program", HTTP_POST, [](AsyncWebServerRequest *request) {
    web_program(request);
  });
  server.on("/ajax_col_params", HTTP_GET, [](AsyncWebServerRequest *request) {
    uint8_t mat = 2; // По умолчанию сахар
    if (request->hasParam("mat")) mat = request->getParam("mat")->value().toInt();

    ColumnResults res = calculate_column_etalon(mat);

    String json = "{";
    json += "\"floodPowerW\":" + String(res.floodPowerW, 0) + ",";
    json += "\"workingPowerW\":" + String(res.workingPowerW, 0) + ",";
    json += "\"maxFlowMlH\":" + String(res.maxFlowMlH, 0) + ",";
    json += "\"theoreticalPlates\":" + String(res.theoreticalPlates, 1) + ",";
    json += "\"headsFlowMlH\":" + String(res.headsFlowMlH, 0) + ",";
    json += "\"bodyFlowMinMlH\":" + String(res.bodyFlowMinMlH, 0) + ",";
    json += "\"bodyFlowMaxMlH\":" + String(res.bodyFlowMaxMlH, 0) + ",";
    json += "\"bodyEndFlowMlH\":" + String(res.bodyEndFlowMlH, 0) + ",";
    json += "\"tailsFlowMlH\":" + String(res.tailsFlowMlH, 0) + ",";
    json += "\"headsPowerW\":" + String(res.headsPowerW, 0) + ",";
    json += "\"bodyEndPowerW\":" + String(res.bodyEndPowerW, 0) + ",";
    json += "\"tailsPowerW\":" + String(res.tailsPowerW, 0);
    json += "}";
    request->send(200, "application/json", json);
  });
  server.on("/calibrate", HTTP_GET, [](AsyncWebServerRequest *request) {
    calibrate_command(request);
  });
  server.on("/i2cpump", HTTP_GET, [](AsyncWebServerRequest *request) {
    // [W-4] Без I2C в async: present берём из глобала (SysTicker держит свежим).
    if (!i2cStepperPump.present) {
      request->send(400, "text/plain", "I2C pump not available");
      return;
    }
    if (request->hasArg("stop")) {
      PendingI2CPumpCmd cmd = {};
      cmd.is_stop = true;
      if (!queue_pending_i2cpump(cmd)) {
        request->send(503, "text/plain", "BUSY");
        return;
      }
      request->send(200, "text/plain", "OK");
      return;
    }
    if ((i2cStepperPump.caps & I2CSTEPPER_CAP_FILLING) == 0) {
      request->send(400, "text/plain", "I2C filling mode not available");
      return;
    }
    float speedRate = request->hasArg("speed") ? request->arg("speed").toFloat() : 0.0f;
    float volumeMl = request->hasArg("volume") ? request->arg("volume").toFloat() : 0.0f;
    if (speedRate <= 0 || volumeMl <= 0) {
      request->send(400, "text/plain", "Invalid params");
      return;
    }
    uint16_t stepsPerMl = SamSetup.StepperStepMlI2C > 0 ? SamSetup.StepperStepMlI2C : I2C_STEPPER_STEP_ML_DEFAULT;
    uint32_t targetSteps = (uint32_t)(volumeMl * stepsPerMl);
    // [W-4] Без I2C в async: считаем скорость по SamSetup (блокирующий helper
    //        делает блокирующий i2c_stepper_refresh — нельзя из async).
    uint16_t speedSteps = (uint16_t)i2c_stepper_steps_from_rate(speedRate);
    uint16_t speedMlHour = i2c_stepper_mlh_from_step_speed(speedSteps);
    // [W-4] Откладываем start в loop; параметры вычислены без I2C.
    PendingI2CPumpCmd cmd = {};
    cmd.is_stop       = false;
    cmd.speedSteps    = speedSteps;
    cmd.targetSteps   = targetSteps;
    cmd.targetMl      = volumeMl;
    cmd.fillingMl     = (uint16_t)volumeMl;
    cmd.fillingMlHour = speedMlHour;
    cmd.stepsPerMl    = stepsPerMl;
    if (!queue_pending_i2cpump(cmd)) {
      request->send(503, "text/plain", "BUSY");
      return;
    }
    request->send(200, "text/plain", "OK");
  });
  server.on("/i2cstepper", HTTP_GET, [](AsyncWebServerRequest *request) {
    I2CStepperDevice* dev = select_i2c_stepper_device(request);
    if (!dev) {
      request->send(400, "application/json", "{\"error\":\"bad device\"}");
      return;
    }
    String cmd = request->hasArg("cmd") ? request->arg("cmd") : "status";
    cmd.toLowerCase();

    // [W-4] Без I2C в async: cmd=="status" — отвечаем из глобала (SysTicker держит свежим).
    if (cmd == "status") {
      send_i2c_stepper_json(request, *dev);
      return;
    }

    // [W-4] Командные cmd: проверки без I2C, аргументы в staged-копию, откладываем в loop.
    if (!dev->present) {
      request->send(404, "application/json", "{\"error\":\"I2C device not available\"}");
      return;
    }
    // staged-копия: apply_i2c_stepper_args пишет только в staged, не в глобал —
    // SysTicker не затрёт применённый конфиг до выполнения команды в loop.
    I2CStepperDevice staged = *dev;
    apply_i2c_stepper_args(request, staged);
    if (!i2c_stepper_command_supported(staged, cmd)) {
      request->send(400, "application/json", "{\"error\":\"unsupported I2CStepper command\"}");
      return;
    }
    PendingI2CStepperCmd pendingCmd = {};
    pendingCmd.staged = staged;
    pendingCmd.device_sel = (dev == &i2cStepperMixer) ? 0 : 1;
    strncpy(pendingCmd.cmd, cmd.c_str(), sizeof(pendingCmd.cmd) - 1);
    pendingCmd.cmd[sizeof(pendingCmd.cmd) - 1] = '\0';
    if (!queue_pending_i2cstepper(pendingCmd)) {
      request->send(503, "application/json", "{\"error\":\"BUSY\"}");
      return;
    }
    // Отвечаем pre-command состоянием; UI перечитает статус следующим запросом.
    send_i2c_stepper_json(request, *dev);
  });
  server.on("/getlog", HTTP_GET, [](AsyncWebServerRequest *request) {
    get_data_log(request, "data.csv");
  });
  server.on("/getoldlog", HTTP_GET, [](AsyncWebServerRequest *request) {
    get_data_log(request, "data_old.csv");
  });
#ifdef USE_LUA
  server.on("/lua", HTTP_GET, [](AsyncWebServerRequest *request) {
    if (request->hasArg("script")) {
      if (!queue_pending_string(pending_lua_file_flag, pending_lua_file, request->arg("script"))) {
        request->send(503, "text/plain", "BUSY");
        return;
      }
      request->send(200, "text/html", "OK");
      return;
    }
    if (!queue_pending_flag(pending_lua_start_flag)) {
      request->send(503, "text/plain", "BUSY");
      return;
    }
    request->send(200, "text/html", "OK");
  });
#endif

  server.on("/save", HTTP_POST, [](AsyncWebServerRequest *request) {
    //Serial.println("SAVE");
    handleSave(request);
  });

  server.onFileUpload([](AsyncWebServerRequest *request, const String &filename, size_t index, uint8_t *data, size_t len, bool final) {
    if (!index)
      Serial.printf("UploadStart: %s\n", filename.c_str());
#ifdef __SAMOVAR_DEBUG
    if (len) {
      Serial.write(data, len);
    }
#endif
    if (final)
      Serial.printf("UploadEnd: %s (%u)\n", filename.c_str(), index + len);
  });
  server.onRequestBody([](AsyncWebServerRequest *request, uint8_t *data, size_t len, size_t index, size_t total) {
    if (!index)
      Serial.printf("BodyStart: %u\n", total);
#ifdef __SAMOVAR_DEBUG
    if (len) {
      Serial.write(data, len);
    }
#endif
    if (index + len == total)
      Serial.printf("BodyEnd: %u\n", total);
  });

  headerFilter.filter("If-Modified-Since");
  //  DefaultHeaders::Instance().addHeader("Cache-Control", "no-cache");
  //  DefaultHeaders::Instance().addHeader("Pragma", "no-cache");
  //  DefaultHeaders::Instance().addHeader("Expires", "Thu, 01 Jan 1970 00:00:00 UTC");
  //  DefaultHeaders::Instance().addHeader("Last-Modified", "Mon, 03 Jan 2050 00:00:00 UTC");
  
  server.on("/distiller.htm", HTTP_GET, [](AsyncWebServerRequest *request) {
    send_mode_specific_htm(request, "/distiller.htm", SAMOVAR_DISTILLATION_MODE);
  });
  server.on("/beer.htm", HTTP_GET, [](AsyncWebServerRequest *request) {
    send_mode_specific_htm(request, "/beer.htm", SAMOVAR_BEER_MODE);
  });
  server.on("/bk.htm", HTTP_GET, [](AsyncWebServerRequest *request) {
    send_mode_specific_htm(request, "/bk.htm", SAMOVAR_BK_MODE);
  });
  server.on("/nbk.htm", HTTP_GET, [](AsyncWebServerRequest *request) {
    send_mode_specific_htm(request, "/nbk.htm", SAMOVAR_NBK_MODE);
  });

  // Автоматическая раздача всех файлов из SPIFFS
  server.serveStatic("/", SPIFFS, "/");
  
  server.begin();
#ifdef __SAMOVAR_DEBUG
  Serial.println("HTTP server started");
#endif

#ifndef NOT_USE_INTERFACE_UPDATE
  get_web_interface();
#endif
}

String indexKeyProcessor(const String &var) {
  if (var == "SteamColor") return (String)SamSetup.SteamColor;
  else if (var == "v")
    return SAMOVAR_VERSION;
  else if (var == "PipeColor")
    return (String)SamSetup.PipeColor;
  else if (var == "WaterColor")
    return (String)SamSetup.WaterColor;
  else if (var == "TankColor")
    return (String)SamSetup.TankColor;
  else if (var == "ACPColor")
    return (String)SamSetup.ACPColor;
  else if (var == "SteamHide") {
    if (SteamSensor.avgTemp > 0) return "false";
    else return "true";
  } else if (var == "PipeHide") {
    if (PipeSensor.avgTemp > 0) return "false";
    else return "true";
  } else if (var == "WaterHide") {
    if (WaterSensor.avgTemp > 0) return "false";
    else return "true";
  } else if (var == "TankHide") {
    if (TankSensor.avgTemp > 0) return "false";
    else return "true";
  } else if (var == "PressureHide") {
    if (bme_pressure > 0) return "false";
    else return "true";
  } else if (var == "ProgNumHide") {
    if (ProgramNum > 0) return "false";
    else return "true";
  } else if (var == "WProgram") {
    if (Samovar_Mode == SAMOVAR_BEER_MODE) return get_beer_program();
    else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) return get_dist_program();
    else if (Samovar_Mode == SAMOVAR_NBK_MODE) return get_nbk_program();
    else
      return get_program(PROGRAM_END);
  } else if (var == "Descr") {
    String description;
    if (!copy_session_description(description)) return F("Runtime state busy");
    return description;
  } else if (var == "videourl")
    return (String)SamSetup.videourl;
  else if (var == "PWM_LV")
    return (String)(PWM_LOW_VALUE * 10);
  else if (var == "PWM_V")
    return (String)bk_pwm;
  else if (var == "pwr_unit")
    return PWR_TYPE;
  else if (var == "pwr_unit_v_only")
    return (String(PWR_TYPE) == "V") ? "block" : "none";
  else if (var == "btn_list") {
#ifdef USE_LUA
    String cachedList;
    bool locked = runtime_state_lock(pdMS_TO_TICKS(50));
    if (locked) {
      cachedList = lua_script_list_cache;
      runtime_state_unlock(true);
    }
    return toJsonString(cachedList);
#else
    return toJsonString(String());
#endif
  } else if (var == "showvideo") {
    if (strlen(SamSetup.videourl) > 0) return "inline";
    else
      return "none";
  } else if (var == "ColDiam")
    return String(SamSetup.ColDiam, 1);
  else if (var == "ColHeight")
    return String(SamSetup.ColHeight, 2);
  else if (var == "PackDens")
    return String(SamSetup.PackDens);
  else if (var == "I2CStepperTab")
    // [W-3] Читаем из кэша (обновляется в SysTicker), без I2C в async.
    return (i2c_stepper_cache.mixer_present || i2c_stepper_cache.pump_present) ? "inline-block" : "none";
  else if (var == "I2CPumpTab")
    return i2c_stepper_cache.pump_present ? "inline-block" : "none";
  else if (var == "HeaterMaxPower") {
    // Расчет мощности ТЭНа: P = U²/R
    float R = SamSetup.HeaterResistant;
    if (R <= 0) return "3500";
    float power = (220 * 220) / R;
    return String((int)power);
  }
  return "";
}

bool copy_lua_button_list_cache(String &buttonList) {
#ifdef USE_LUA
  bool locked = runtime_state_lock(pdMS_TO_TICKS(50));
  if (!locked) return false;
  buttonList = lua_script_list_cache;
  runtime_state_unlock(true);
#else
  buttonList = String();
#endif
  return true;
}

String indexKeyProcessorWithSnapshots(const String &var, const String &description, const String &luaButtonList) {
  if (var == "Descr") return description;
  if (var == "btn_list") return toJsonString(luaButtonList);
  return indexKeyProcessor(var);
}

String setupKeyProcessor(const String &var) {
  static String s;
  s = "";
  if (var == "DeltaSteamTemp") {
    s = format_float(SamSetup.DeltaSteamTemp, 2);
    return s;
  } else if (var == "DeltaPipeTemp") {
    s = format_float(SamSetup.DeltaPipeTemp, 2);
    return s;
  } else if (var == "DeltaWaterTemp") {
    s = format_float(SamSetup.DeltaWaterTemp, 2);
    return s;
  } else if (var == "DeltaTankTemp") {
    s = format_float(SamSetup.DeltaTankTemp, 2);
    return s;
  } else if (var == "DeltaACPTemp") {
    s = format_float(SamSetup.DeltaACPTemp, 2);
    return s;
  } else if (var == "SetSteamTemp") {
    s = format_float(SamSetup.SetSteamTemp, 2);
    return s;
  } else if (var == "SetPipeTemp") {
    float setPipeTemp = isnan(SamSetup.SetPipeTemp) ? 0 : SamSetup.SetPipeTemp;
    s = format_float(setPipeTemp, 2);
    return s;
  } else if (var == "SetWaterTemp") {
    float setWaterTemp = isnan(SamSetup.SetWaterTemp) ? 0 : SamSetup.SetWaterTemp;
    s = format_float(setWaterTemp, 2);
    return s;
  } else if (var == "SetTankTemp") {
    float setTankTemp = isnan(SamSetup.SetTankTemp) ? 0 : SamSetup.SetTankTemp;
    s = format_float(setTankTemp, 2);
    return s;
  } else if (var == "SetACPTemp") {
    float setACPTemp = isnan(SamSetup.SetACPTemp) ? 0 : SamSetup.SetACPTemp;
    s = format_float(setACPTemp, 2);
    return s;
  } else if (var == "StepperStepMl") {
    s = SamSetup.StepperStepMl;
    return s;
  } else if (var == "StepperStepMlI2C") {
    s = SamSetup.StepperStepMlI2C;
    return s;
  } else if (var == "WProgram") {
    if (Samovar_Mode == SAMOVAR_BEER_MODE) return get_beer_program();
    else
      return get_program(PROGRAM_END);
  } else if (var == "Kp") {
    s = format_float(SamSetup.Kp, 3);
    return s;
  } else if (var == "Ki") {
    s = format_float(SamSetup.Ki, 3);
    return s;
  } else if (var == "Kd") {
    s = format_float(SamSetup.Kd, 3);
    return s;
  } else if (var == "StbVoltage") {
    s = SamSetup.StbVoltage;
    return s;
  } else if (var == "SteamDelay") {
    s = SamSetup.SteamDelay;
    return s;
  } else if (var == "PipeDelay") {
    s = SamSetup.PipeDelay;
    return s;
  } else if (var == "WaterDelay") {
    s = SamSetup.WaterDelay;
    return s;
  } else if (var == "TankDelay") {
    s = SamSetup.TankDelay;
    return s;
  } else if (var == "ACPDelay") {
    s = SamSetup.ACPDelay;
    return s;
  } else if (var == "TimeZone") {
    s = SamSetup.TimeZone;
    return s;
  } else if (var == "LogPeriod") {
    s = SamSetup.LogPeriod;
    return s;
  } else if (var == "HeaterR") {
    s = format_float(SamSetup.HeaterResistant, 3);
    return s;
  } else if (var == "videourl") {
    s = SamSetup.videourl;
    return s;
  } else if (var == "blynkauth") {
    s = SamSetup.blynkauth;
    return s;
  } else if (var == "tgtoken") {
    s = SamSetup.tg_token;
    return s;
  } else if (var == "tgchatid") {
    s = SamSetup.tg_chat_id;
    return s;
  } else if (var == "BVolt") {
    s = SamSetup.BVolt;
    return s;
  } else if (var == "DistTimeF") {
    s = SamSetup.DistTimeF;
    return s;
  } else if (var == "MaxPressureValue") {
    s = SamSetup.MaxPressureValue;
    return s;
  } else if (var == "NbkIn") {
    s = SamSetup.NbkIn;
    return s;
  } else if (var == "NbkDelta") {
    s = SamSetup.NbkDelta;
    return s;
  } else if (var == "NbkDM") {
    s = SamSetup.NbkDM;
    return s;
  } else if (var == "NbkDP") {
    s = SamSetup.NbkDP;
    return s;
  } else if (var == "NbkSteamT") {
    s = SamSetup.NbkSteamT;
    return s;
  } else if (var == "NbkOwPress") {
    s = SamSetup.NbkOwPress;
    return s;
  } else if (var == "Checked") {
    if (SamSetup.UsePreccureCorrect) return "checked='true'";
    else
      return "";
  } else if (var == "FLChecked") {
    if (SamSetup.UseHLS) return "checked='true'";
    else
      return "";
#ifdef IGNORE_HEAD_LEVEL_SENSOR_SETTING
  } else if (var == "IgnFL") {
    return F("style="
             "display: none"
             "");
#endif
  } else if (var == "UASChecked") {
    if (SamSetup.useautospeed) return "checked='true'";
    else
      return "";
  } else if (var == "UASHeadsChecked") {
    if (SamSetup.useDetectorOnHeads) return "checked='true'";
    else
      return "";
  } else if (var == "CPBuzz") {
    if (SamSetup.ChangeProgramBuzzer) return "checked='true'";
    else
      return "";
  } else if (var == "CUBuzz") {
    if (SamSetup.UseBuzzer) return "checked='true'";
    else
      return "";
  } else if (var == "CUBBuzz") {
    if (SamSetup.UseBBuzzer) return "checked='true'";
    else
      return "";
  } else if (var == "UseWS") {
    if (SamSetup.UseWS) return "checked='true'";
    else
      return "";
  } else if (var == "UseST") {
    if (SamSetup.UseST) return "checked='true'";
    else
      return "";
  } else if (var == "ChckPwr") {
    if (SamSetup.CheckPower) return "checked='true'";
    else
      return "";
  } else if (var == "autospeed") {
    s = SamSetup.autospeed;
    return s;
  } else if (var == "DistTemp") {
    s = format_float(SamSetup.DistTemp, 2);
    return s;
  } else if (var == "SteamColor") {
    s = SamSetup.SteamColor;
    return s;
  } else if (var == "PipeColor") {
    s = SamSetup.PipeColor;
    return s;
  } else if (var == "WaterColor") {
    s = SamSetup.WaterColor;
    return s;
  } else if (var == "TankColor") {
    s = SamSetup.TankColor;
    return s;
  } else if (var == "ACPColor") {
    s = SamSetup.ACPColor;
    return s;
  } else if (var == "RECT" && (SAMOVAR_MODE)SamSetup.Mode == SAMOVAR_RECTIFICATION_MODE)
    return "selected";
  else if (var == "DIST" && (SAMOVAR_MODE)SamSetup.Mode == SAMOVAR_DISTILLATION_MODE)
    return "selected";
  else if (var == "BEER" && (SAMOVAR_MODE)SamSetup.Mode == SAMOVAR_BEER_MODE)
    return "selected";
  else if (var == "BK" && (SAMOVAR_MODE)SamSetup.Mode == SAMOVAR_BK_MODE)
    return "selected";
  else if (var == "NBK" && (SAMOVAR_MODE)SamSetup.Mode == SAMOVAR_NBK_MODE)
    return "selected";
  else if (var == "SUVID" && (SAMOVAR_MODE)SamSetup.Mode == SAMOVAR_SUVID_MODE)
    return "selected";
  else if (var == "LUA_MODE" && (SAMOVAR_MODE)SamSetup.Mode == SAMOVAR_LUA_MODE)
    return "selected";
  else if (var == "RAL" && !SamSetup.rele1)
    return "selected";
  else if (var == "RAH" && SamSetup.rele1)
    return "selected";
  else if (var == "RBL" && !SamSetup.rele2)
    return "selected";
  else if (var == "RBH" && SamSetup.rele2)
    return "selected";
  else if (var == "RCL" && !SamSetup.rele3)
    return "selected";
  else if (var == "RCH" && SamSetup.rele3)
    return "selected";
  else if (var == "RDL" && !SamSetup.rele4)
    return "selected";
  else if (var == "RDH" && SamSetup.rele4)
    return "selected";
  else if (var == "SteamAddr")
    return get_DSAddressList(getDSAddress(SamSetup.SteamAdress));
  else if (var == "PipeAddr")
    return get_DSAddressList(getDSAddress(SamSetup.PipeAdress));
  else if (var == "WaterAddr")
    return get_DSAddressList(getDSAddress(SamSetup.WaterAdress));
  else if (var == "TankAddr")
    return get_DSAddressList(getDSAddress(SamSetup.TankAdress));
  else if (var == "ACPAddr")
    return get_DSAddressList(getDSAddress(SamSetup.ACPAdress));
  else if (var == "ColDiam")
    return String(SamSetup.ColDiam, 1);
  else if (var == "ColDiam_1.5") {
    if (abs(SamSetup.ColDiam - 1.5f) < 0.01f) return "selected";
    else return "";
  } else if (var == "ColDiam_2.0") {
    if (abs(SamSetup.ColDiam - 2.0f) < 0.01f) return "selected";
    else return "";
  } else if (var == "ColDiam_3.0") {
    if (abs(SamSetup.ColDiam - 3.0f) < 0.01f) return "selected";
    else return "";
  } else if (var == "ColHeight")
    return String(SamSetup.ColHeight, 2);
  else if (var == "ColHeight_0.50") {
    if (abs(SamSetup.ColHeight - 0.50f) < 0.01f) return "selected";
    else return "";
  } else if (var == "ColHeight_0.75") {
    if (abs(SamSetup.ColHeight - 0.75f) < 0.01f) return "selected";
    else return "";
  } else if (var == "ColHeight_1.00") {
    if (abs(SamSetup.ColHeight - 1.00f) < 0.01f) return "selected";
    else return "";
  } else if (var == "ColHeight_1.25") {
    if (abs(SamSetup.ColHeight - 1.25f) < 0.01f) return "selected";
    else return "";
  } else if (var == "ColHeight_1.50") {
    if (abs(SamSetup.ColHeight - 1.50f) < 0.01f) return "selected";
    else return "";
  } else if (var == "ColHeight_1.75") {
    if (abs(SamSetup.ColHeight - 1.75f) < 0.01f) return "selected";
    else return "";
  } else if (var == "ColHeight_2.00") {
    if (abs(SamSetup.ColHeight - 2.00f) < 0.01f) return "selected";
    else return "";
  } else if (var == "ColHeight_2.25") {
    if (abs(SamSetup.ColHeight - 2.25f) < 0.01f) return "selected";
    else return "";
  } else if (var == "ColHeight_2.50") {
    if (abs(SamSetup.ColHeight - 2.50f) < 0.01f) return "selected";
    else return "";
  } else if (var == "PackDens")
    return String(SamSetup.PackDens);
  else if (var == "I2CStepperTab")
    // [W-3] Читаем из кэша (обновляется в SysTicker), без I2C в async.
    return (i2c_stepper_cache.mixer_present || i2c_stepper_cache.pump_present) ? "inline-block" : "none";
  else if (var == "I2CPumpTab")
    return i2c_stepper_cache.pump_present ? "inline-block" : "none";
  return "";
}

const AsyncWebParameter* get_request_param(AsyncWebServerRequest *request, const char *name) {
  if (!request || !name) return nullptr;
  const AsyncWebParameter *param = request->getParam(name, true);
  if (param) return param;
  return request->getParam(name, false);
}

String calibrateKeyProcessor(const String &var) {
  if (var == "StepperStep") return (String)STEPPER_MAX_SPEED;
  else if (var == "StepperStepMl")
    return (String)(SamSetup.StepperStepMl * 100);
  else if (var == "StepperStepMlI2C")
    return (String)(SamSetup.StepperStepMlI2C * 100);
  else if (var == "I2CPumpTab")
    // [W-3] Читаем из кэша (обновляется в SysTicker), без I2C в async.
    return i2c_stepper_cache.pump_present ? "inline-block" : "none";

  return String();
}

bool is_valid_samovar_mode(long mode) {
  return mode >= SAMOVAR_RECTIFICATION_MODE && mode <= SAMOVAR_LUA_MODE;
}

void stop_active_process_for_mode() {
  if (!PowerOn) return;
  if (!mode_finish_by_status(SamovarStatusInt)) set_power(false);
}

bool reject_program_update_if_busy(AsyncWebServerRequest *request) {
  if (pending_program_slot_busy()) {
    request->send(503, "text/plain", "BUSY: предыдущее изменение программы ещё не применено");
    return true;
  }
  if (program_update_session_active()) {
    request->send(409, "text/plain", "BUSY: программа не изменена, активна сессия режима");
    return true;
  }
  return false;
}

// [W-6] switch_samovar_mode вызывается ТОЛЬКО из loop() через pending_switch_mode_flag.
//        Остановка процесса, Lua и runtime-синхронизация не выполняются из async-контекста.
void switch_samovar_mode(SAMOVAR_MODE requestedMode) {
  stop_active_process_for_mode();

#ifdef USE_LUA
  if (loop_lua_fl) {
    SetScriptOff = true;
    loop_lua_fl = false;
    // Без delay: цикл do_lua_script на core 1 проверит SetScriptOff на следующей итерации.
  }
#endif

  samovar_reset();

  SamSetup.Mode = (uint16_t)requestedMode;
  Samovar_Mode = requestedMode;
  Samovar_CR_Mode = requestedMode;
  load_default_program_for_mode();
  if (SamSetup.flag > 250) SamSetup.flag = 2;
  SamSetup.Mode = (uint16_t)requestedMode;
  Samovar_Mode = requestedMode;
  Samovar_CR_Mode = requestedMode;

#ifdef USE_LUA
  lua_type_script = get_lua_mode_name();
  load_lua_script();
#endif

  change_samovar_mode();
}

void update_checkbox_arg(AsyncWebServerRequest *request, const char* name, bool& value, bool fullSetupForm) {
  if (fullSetupForm || request->hasArg(name)) value = request->hasArg(name);
}

static void send_save_parse_error(AsyncWebServerRequest *request, const char *name) {
  String message = "Invalid ";
  message += name;
  request->send(400, "text/plain", message);
}

static bool save_float_is_finite(float value) {
  return !isnan(value) && !isinf(value);
}

static bool parse_save_long_arg(AsyncWebServerRequest *request, const char *name, long minValue, long maxValue, long& value) {
  String raw = request->arg(name);
  if (!parseLongSafe(raw.c_str(), value) || value < minValue || value > maxValue) {
    send_save_parse_error(request, name);
    return false;
  }
  return true;
}

static bool parse_save_float_arg(AsyncWebServerRequest *request, const char *name, float minValue, float maxValue, float& value) {
  String raw = request->arg(name);
  if (!parseFloatSafe(raw.c_str(), value) || !save_float_is_finite(value) || value < minValue || value > maxValue) {
    send_save_parse_error(request, name);
    return false;
  }
  return true;
}

static bool apply_save_u8_arg(AsyncWebServerRequest *request, const char *name, uint8_t& target, long minValue, long maxValue) {
  if (!request->hasArg(name)) return true;
  long value = 0;
  if (!parse_save_long_arg(request, name, minValue, maxValue, value)) return false;
  target = (uint8_t)value;
  return true;
}

static bool apply_save_u16_arg(AsyncWebServerRequest *request, const char *name, uint16_t& target, long minValue, long maxValue) {
  if (!request->hasArg(name)) return true;
  long value = 0;
  if (!parse_save_long_arg(request, name, minValue, maxValue, value)) return false;
  target = (uint16_t)value;
  return true;
}

static bool apply_save_bool01_arg(AsyncWebServerRequest *request, const char *name, bool& target) {
  if (!request->hasArg(name)) return true;
  long value = 0;
  if (!parse_save_long_arg(request, name, 0, 1, value)) return false;
  target = value != 0;
  return true;
}

static bool apply_save_float_arg(AsyncWebServerRequest *request, const char *name, float& target, float minValue, float maxValue) {
  if (!request->hasArg(name)) return true;
  float value = 0;
  if (!parse_save_float_arg(request, name, minValue, maxValue, value)) return false;
  target = value;
  return true;
}

template <size_t N>
static void apply_save_string_arg(AsyncWebServerRequest *request, const char *name, char (&target)[N]) {
  if (request->hasArg(name)) copyStringSafe(target, request->arg(name));
}

static bool apply_save_ds_addr_arg(AsyncWebServerRequest *request, const char *name, const DSAddressSnapshot& snapshot, uint8_t (&target)[8], bool& resetSensor) {
  if (!request->hasArg(name)) return true;
  long idx = 0;
  if (!parse_save_long_arg(request, name, -1, SAMOVAR_DS_ADDRESS_MAX - 1, idx)) return false;
  DeviceAddress selectedAddress;
  if (idx == -1) {
    set_invalid_ds_address(selectedAddress);
  } else if (idx >= snapshot.count) {
    send_save_parse_error(request, name);
    return false;
  } else {
    CopyDSAddress(snapshot.addr[idx], selectedAddress);
  }
  if (!ds_address_equal(target, selectedAddress)) {
    CopyDSAddress(selectedAddress, target);
    resetSensor = true;
  }
  return true;
}

void handleSave(AsyncWebServerRequest *request) {
  if (!request) {
    return;
  }
  if (get_request_param(request, "WProgram") && reject_program_update_if_busy(request)) {
    return;
  }
  /*
       int params = request->params();
        for(int i=0;i<params;i++){
          AsyncWebParameter* p = request->getParam(i);
          Serial.print(p->name().c_str());
          Serial.print("=");
          Serial.println(p->value().c_str());
        }
        //return;
  */

  bool fullSetupForm = request->hasArg("fullsetup");
  bool modeRequested = false;
  SAMOVAR_MODE requestedMode = Samovar_Mode;
  {
    const AsyncWebParameter *modeParam = get_request_param(request, "mode");
    if (modeParam) {
      String modeArg = modeParam->value();
      long requestedModeValue = 0;
      if (!parseLongSafe(modeArg.c_str(), requestedModeValue) || !is_valid_samovar_mode(requestedModeValue)) {
        request->send(400, "text/plain", "Invalid mode");
        return;
      }
      modeRequested = true;
      requestedMode = (SAMOVAR_MODE)requestedModeValue;
    }
  }

  PendingSetupSave setupSave;
  setupSave.staged = SamSetup;
  memset(&setupSave.resetSensor, 0, sizeof(setupSave.resetSensor));
  SetupEEPROM& staged = setupSave.staged;
  DSAddressSnapshot dsSnapshot;
  copy_ds_address_snapshot(dsSnapshot);
  if (modeRequested) {
    staged.Mode = (int)requestedMode;
  }

  if (!apply_save_u16_arg(request, "SteamDelay", staged.SteamDelay, 0, 65535)) return;
  if (!apply_save_u16_arg(request, "PipeDelay", staged.PipeDelay, 0, 65535)) return;
  if (!apply_save_u16_arg(request, "WaterDelay", staged.WaterDelay, 0, 65535)) return;
  if (!apply_save_u16_arg(request, "TankDelay", staged.TankDelay, 0, 65535)) return;
  if (!apply_save_u16_arg(request, "ACPDelay", staged.ACPDelay, 0, 65535)) return;

  if (!apply_save_float_arg(request, "DeltaSteamTemp", staged.DeltaSteamTemp, -1000.0f, 1000.0f)) return;
  if (!apply_save_float_arg(request, "DeltaPipeTemp", staged.DeltaPipeTemp, -1000.0f, 1000.0f)) return;
  if (!apply_save_float_arg(request, "DeltaWaterTemp", staged.DeltaWaterTemp, -1000.0f, 1000.0f)) return;
  if (!apply_save_float_arg(request, "DeltaTankTemp", staged.DeltaTankTemp, -1000.0f, 1000.0f)) return;
  if (!apply_save_float_arg(request, "DeltaACPTemp", staged.DeltaACPTemp, -1000.0f, 1000.0f)) return;
  if (!apply_save_float_arg(request, "SetSteamTemp", staged.SetSteamTemp, 0.0f, 150.0f)) return;
  if (!apply_save_float_arg(request, "SetPipeTemp", staged.SetPipeTemp, 0.0f, 150.0f)) return;
  if (!apply_save_float_arg(request, "SetWaterTemp", staged.SetWaterTemp, 0.0f, 150.0f)) return;
  if (!apply_save_float_arg(request, "SetTankTemp", staged.SetTankTemp, 0.0f, 150.0f)) return;
  if (!apply_save_float_arg(request, "SetACPTemp", staged.SetACPTemp, 0.0f, 150.0f)) return;
  if (!apply_save_float_arg(request, "Kp", staged.Kp, 0.0f, 100000.0f)) return;
  if (!apply_save_float_arg(request, "Ki", staged.Ki, 0.0f, 100000.0f)) return;
  if (!apply_save_float_arg(request, "Kd", staged.Kd, 0.0f, 100000.0f)) return;
  if (!apply_save_float_arg(request, "StbVoltage", staged.StbVoltage, 0.0f, 10000.0f)) return;
  if (!apply_save_float_arg(request, "BVolt", staged.BVolt, 0.0f, 10000.0f)) return;
  if (!apply_save_u8_arg(request, "DistTimeF", staged.DistTimeF, 0, 255)) return;
  if (!apply_save_float_arg(request, "MaxPressureValue", staged.MaxPressureValue, 0.0f, 10000.0f)) return;
  if (!apply_save_u16_arg(request, "StepperStepMl", staged.StepperStepMl, 0, 65535)) return;
  if (!apply_save_u16_arg(request, "StepperStepMlI2C", staged.StepperStepMlI2C, 0, 65535)) return;
  if (request->hasArg("stepperstepml")) {
    long stepsPer100Ml = 0;
    if (!parse_save_long_arg(request, "stepperstepml", 0, 6553500, stepsPer100Ml)) return;
    staged.StepperStepMl = (uint16_t)(stepsPer100Ml / 100);
  }

  update_checkbox_arg(request, "useflevel", staged.UseHLS, fullSetupForm);
  update_checkbox_arg(request, "usepressure", staged.UsePreccureCorrect, fullSetupForm);
  update_checkbox_arg(request, "useautospeed", staged.useautospeed, fullSetupForm);
  update_checkbox_arg(request, "useDetectorOnHeads", staged.useDetectorOnHeads, fullSetupForm);
  update_checkbox_arg(request, "ChangeProgramBuzzer", staged.ChangeProgramBuzzer, fullSetupForm);
  update_checkbox_arg(request, "UseBuzzer", staged.UseBuzzer, fullSetupForm);
  update_checkbox_arg(request, "UseBBuzzer", staged.UseBBuzzer, fullSetupForm);
  update_checkbox_arg(request, "UseWS", staged.UseWS, fullSetupForm);
  update_checkbox_arg(request, "UseST", staged.UseST, fullSetupForm);
  update_checkbox_arg(request, "CheckPower", staged.CheckPower, fullSetupForm);

  if (!apply_save_u8_arg(request, "autospeed", staged.autospeed, 0, 99)) return;
  if (!apply_save_float_arg(request, "DistTemp", staged.DistTemp, 0.0f, 150.0f)) return;
  if (!apply_save_u8_arg(request, "TimeZone", staged.TimeZone, 0, 23)) return;
  if (!apply_save_u8_arg(request, "LogPeriod", staged.LogPeriod, 1, 255)) return;
  if (!apply_save_float_arg(request, "HeaterR", staged.HeaterResistant, 0.001f, 10000.0f)) return;
  if (!apply_save_float_arg(request, "NbkIn", staged.NbkIn, 0.0f, 100000.0f)) return;
  if (!apply_save_float_arg(request, "NbkDelta", staged.NbkDelta, 0.0f, 100000.0f)) return;
  if (!apply_save_float_arg(request, "NbkDM", staged.NbkDM, 0.0f, 100000.0f)) return;
  if (!apply_save_float_arg(request, "NbkDP", staged.NbkDP, 0.0f, 100000.0f)) return;
  if (!apply_save_float_arg(request, "NbkSteamT", staged.NbkSteamT, 0.0f, 150.0f)) return;
  if (!apply_save_float_arg(request, "NbkOwPress", staged.NbkOwPress, 0.0f, 100000.0f)) return;

  apply_save_string_arg(request, "videourl", staged.videourl);
  apply_save_string_arg(request, "blynkauth", staged.blynkauth);
  apply_save_string_arg(request, "tgtoken", staged.tg_token);
  apply_save_string_arg(request, "tgchatid", staged.tg_chat_id);
  apply_save_string_arg(request, "SteamColor", staged.SteamColor);
  apply_save_string_arg(request, "PipeColor", staged.PipeColor);
  apply_save_string_arg(request, "WaterColor", staged.WaterColor);
  apply_save_string_arg(request, "TankColor", staged.TankColor);
  apply_save_string_arg(request, "ACPColor", staged.ACPColor);

  if (!apply_save_bool01_arg(request, "rele1", staged.rele1)) return;
  if (!apply_save_bool01_arg(request, "rele2", staged.rele2)) return;
  if (!apply_save_bool01_arg(request, "rele3", staged.rele3)) return;
  if (!apply_save_bool01_arg(request, "rele4", staged.rele4)) return;

  if (!apply_save_ds_addr_arg(request, "SteamAddr", dsSnapshot, staged.SteamAdress, setupSave.resetSensor.steam)) return;
  if (!apply_save_ds_addr_arg(request, "PipeAddr", dsSnapshot, staged.PipeAdress, setupSave.resetSensor.pipe)) return;
  if (!apply_save_ds_addr_arg(request, "WaterAddr", dsSnapshot, staged.WaterAdress, setupSave.resetSensor.water)) return;
  if (!apply_save_ds_addr_arg(request, "TankAddr", dsSnapshot, staged.TankAdress, setupSave.resetSensor.tank)) return;
  if (!apply_save_ds_addr_arg(request, "ACPAddr", dsSnapshot, staged.ACPAdress, setupSave.resetSensor.acp)) return;

  if (!apply_save_float_arg(request, "ColDiam", staged.ColDiam, 0.1f, 10.0f)) return;
  if (!apply_save_float_arg(request, "ColHeight", staged.ColHeight, 0.01f, 10.0f)) return;
  if (!apply_save_u8_arg(request, "PackDens", staged.PackDens, 0, 100)) return;

  bool hasProgram = false;
  PendingProgramMode pendingMode = PPM_NONE;
  String pendingProgramText;
  if (const AsyncWebParameter *wProgramParam = get_request_param(request, "WProgram")) {
    SAMOVAR_MODE programMode = modeRequested ? requestedMode : Samovar_Mode;
    pendingMode = pending_program_mode_for_samovar_mode(programMode);
    pendingProgramText = wProgramParam->value();
    hasProgram = true;
  }

  bool hasSwitchMode = modeRequested &&
      (SamSetup.Mode != (uint16_t)requestedMode ||
       Samovar_Mode != requestedMode);

  const char *busyText = nullptr;
  if (!queue_pending_setup_save(setupSave, hasProgram, pendingMode, pendingProgramText, hasSwitchMode, requestedMode, busyText)) {
    request->send(503, "text/plain", busyText ? busyText : "BUSY");
    return;
  }

  get_task_stack_usage();
  AsyncWebServerResponse *response = request->beginResponse(301);
  response->addHeader("Location", "/");
  response->addHeader("Cache-Control", "no-cache");
  request->send(response);
  // is_reboot обрабатывается в loop() — рестарт выполнится после отправки ответа.
}

static const AsyncWebParameter* get_web_command_param(AsyncWebServerRequest *request, const char *name) {
  if (!request || !name) return nullptr;
  return request->getParam(name, true);
}

static bool web_command_has_arg(AsyncWebServerRequest *request, const char *name) {
  return get_web_command_param(request, name) != nullptr;
}

static String web_command_arg(AsyncWebServerRequest *request, const char *name) {
  const AsyncWebParameter *param = get_web_command_param(request, name);
  return param ? param->value() : String();
}

static String get_web_command_key(AsyncWebServerRequest *request) {
  if (web_command_has_arg(request, "start")) return "start";
  if (web_command_has_arg(request, "power")) return "power";
  if (web_command_has_arg(request, "setbodytemp")) return "setbodytemp";
  if (web_command_has_arg(request, "reset")) return "reset";
  if (web_command_has_arg(request, "reboot")) return "reboot";
  if (web_command_has_arg(request, "resetwifi")) return "resetwifi";
  if (web_command_has_arg(request, "startst")) return "startst";
  if (web_command_has_arg(request, "rescands")) return "rescands";
  if (web_command_has_arg(request, "stopst")) return "stopst";
  if (web_command_has_arg(request, "mixer")) return String("mixer=") + web_command_arg(request, "mixer");
  if (web_command_has_arg(request, "pnbk")) return String("pnbk=") + web_command_arg(request, "pnbk");
  if (web_command_has_arg(request, "nbkopt")) return "nbkopt";
  if (web_command_has_arg(request, "distiller")) return String("distiller=") + web_command_arg(request, "distiller");
  if (web_command_has_arg(request, "startbk")) return String("startbk=") + web_command_arg(request, "startbk");
  if (web_command_has_arg(request, "startnbk")) return String("startnbk=") + web_command_arg(request, "startnbk");
  if (web_command_has_arg(request, "watert")) return String("watert=") + web_command_arg(request, "watert");
  if (web_command_has_arg(request, "pumpspeed")) return String("pumpspeed=") + web_command_arg(request, "pumpspeed");
  if (web_command_has_arg(request, "pause")) return "pause";
#ifdef SAMOVAR_USE_POWER
  if (web_command_has_arg(request, "voltage")) return String("voltage=") + web_command_arg(request, "voltage");
#endif
#ifdef USE_LUA
  if (web_command_has_arg(request, "lua")) return String("lua=") + web_command_arg(request, "lua");
  if (web_command_has_arg(request, "luastr")) return "luastr";
#endif
  return "";
}

static bool web_command_parse_float(AsyncWebServerRequest *request, const char *name, float& value) {
  if (!web_command_has_arg(request, name)) return false;
  String raw = web_command_arg(request, name);
  return parseFloatSafe(raw.c_str(), value);
}

static void send_web_command_response(AsyncWebServerRequest *request, int status, const char *text) {
  request->send(status, "text/plain", text);
}

void web_command(AsyncWebServerRequest *request) {
  static uint32_t last_command_time = 0;
  static String last_command_key;
  String commandKey = get_web_command_key(request);
  bool bypassThrottle = web_command_has_arg(request, "reset") || web_command_has_arg(request, "reboot") || web_command_has_arg(request, "resetwifi");
  if (!bypassThrottle && commandKey.length() > 0 && commandKey == last_command_key && millis() - last_command_time < 1500) {
    send_web_command_response(request, 429, "IGNORED");
    return;
  }
  auto markAccepted = [&]() {
    if (!bypassThrottle && commandKey.length() > 0) {
      last_command_key = commandKey;
      last_command_time = millis();
    }
  };

  if (web_command_has_arg(request, "start")) {
    if (!PowerOn) {
      send_web_command_response(request, 409, "POWER_OFF");
      return;
    }
    SamovarCommands command = mode_start_command(Samovar_Mode);
    if (!queue_samovar_command(command)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  } else if (web_command_has_arg(request, "power")) {
    SamovarCommands command = SAMOVAR_POWER;
    if (!PowerOn) command = mode_power_on_command(Samovar_Mode);
    if (!queue_samovar_command(command)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  } else if (web_command_has_arg(request, "setbodytemp")) {
    if (!queue_samovar_command(SAMOVAR_SETBODYTEMP)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  } else if (web_command_has_arg(request, "reset")) {
    if (!queue_samovar_reset_command()) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  } else if (web_command_has_arg(request, "reboot")) {
    if (!queue_pending_flag(is_reboot)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
    markAccepted();
    request->send(200, "text/plain", "OK");
    return;
  } else if (web_command_has_arg(request, "resetwifi")) {
    if (!queue_pending_flag(pending_reset_wifi_flag)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
    markAccepted();
    request->send(200, "text/plain", "OK");
    return;
  } else if (web_command_has_arg(request, "startst")) {
    if (!queue_samovar_command(SAMOVAR_SELF_TEST)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  } else if (web_command_has_arg(request, "rescands")) {
    if (samovar_process_active()) {
      send_web_command_response(request, 409, "BUSY");
      return;
    }
    if (!queue_pending_flag(pending_rescan_ds_flag)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  } else if (web_command_has_arg(request, "stopst")) {
    if (!queue_pending_flag(pending_stop_self_test_flag)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  } else if (web_command_has_arg(request, "mixer")) {
    long mixerValue = 0;
    String raw = web_command_arg(request, "mixer");
    if (!parseLongSafe(raw.c_str(), mixerValue)) {
      send_web_command_response(request, 400, "BAD_REQUEST");
      return;
    }
    if (!queue_pending_bool(pending_mixer_flag, pending_mixer_on, mixerValue == 1)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  } else if (web_command_has_arg(request, "pnbk")) {
    if (!PowerOn) {
      send_web_command_response(request, 409, "POWER_OFF");
      return;
    }
    float pnbkValue = 0;
    if (!web_command_parse_float(request, "pnbk", pnbkValue)) {
      send_web_command_response(request, 400, "BAD_REQUEST");
      return;
    }
    if (!queue_pending_float(pending_pnbk_flag, pending_pnbk_value, pnbkValue)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  } else if (web_command_has_arg(request, "nbkopt")) {
    if (!PowerOn) {
      send_web_command_response(request, 409, "POWER_OFF");
      return;
    }
    if (!queue_pending_flag(pending_nbkopt_flag)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  } else if (web_command_has_arg(request, "distiller")) {
    SamovarCommands command = (web_command_arg(request, "distiller").toInt() == 1) ? SAMOVAR_DISTILLATION : SAMOVAR_POWER;
    if (!queue_samovar_command(command)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  } else if (web_command_has_arg(request, "startbk")) {
    SamovarCommands command = (web_command_arg(request, "startbk").toInt() == 1) ? SAMOVAR_BK : SAMOVAR_POWER;
    if (!queue_samovar_command(command)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  } else if (web_command_has_arg(request, "startnbk")) {
    SamovarCommands command = (web_command_arg(request, "startnbk").toInt() == 1) ? SAMOVAR_NBK : SAMOVAR_POWER;
    if (!queue_samovar_command(command)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  } else if (web_command_has_arg(request, "watert")) {
    float waterTemp = 0;
    if (!web_command_parse_float(request, "watert", waterTemp)) {
      send_web_command_response(request, 400, "BAD_REQUEST");
      return;
    }
    if (!queue_pending_float(pending_water_temp_flag, pending_water_temp_value, waterTemp)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  } else if (web_command_has_arg(request, "pumpspeed")) {
    float pumpSpeed = 0;
    if (!web_command_parse_float(request, "pumpspeed", pumpSpeed) || pumpSpeed <= 0) {
      send_web_command_response(request, 400, "BAD_REQUEST");
      return;
    }
    if (!queue_pending_float(pending_pump_speed_flag, pending_pump_speed_rate, pumpSpeed)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  } else if (web_command_has_arg(request, "pause")) {
    SamovarCommands command = PauseOn ? SAMOVAR_CONTINUE : SAMOVAR_PAUSE;
    if (!queue_samovar_command(command)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  }
#ifdef SAMOVAR_USE_POWER
  else if (web_command_has_arg(request, "voltage")) {
    if (!PowerOn) {
      send_web_command_response(request, 409, "POWER_OFF");
      return;
    }
    float voltage = 0;
    if (!web_command_parse_float(request, "voltage", voltage) || voltage < 0) {
      send_web_command_response(request, 400, "BAD_REQUEST");
      return;
    }
    if (!queue_pending_float(pending_voltage_flag, pending_voltage_value, voltage)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  }
#endif
#ifdef USE_LUA
  else if (web_command_has_arg(request, "lua")) {
    if (!queue_pending_string(pending_lua_file_flag, pending_lua_file, web_command_arg(request, "lua"))) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  } else if (web_command_has_arg(request, "luastr")) {
    String lstr = web_command_arg(request, "luastr");
    lstr.replace("^", " ");
    if (!queue_pending_string(pending_lua_flag, pending_lua_str, lstr)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  }
#endif
  else {
    send_web_command_response(request, 400, "BAD_REQUEST");
    return;
  }
  markAccepted();
  request->send(200, "text/plain", "OK");
}
void web_program(AsyncWebServerRequest *request) {
  String responseProgram;
  if (request->hasArg("Descr")) {
    String description = request->arg("Descr");
    description.replace("%", "&#37;");
    if (!set_session_description_value(description, pdMS_TO_TICKS(500))) {
      send_program_json_response(request, 503, false, F("BUSY: описание сессии занято"), String());
      return;
    }
  }
  const AsyncWebParameter *wProgramParam = get_request_param(request, "WProgram");
  if (wProgramParam) {
    if (reject_program_update_if_busy_json(request)) {
      return;
    }
    // [C-3] Вынесено в loop(): set_*_program пишет program[], читаемый из SysTicker.
    //        Отвечаем текущим содержимым программы (до применения); UI
    //        синхронизируется при следующем запросе после цикла loop.
    PendingProgramMode pendingMode = pending_program_mode_for_samovar_mode(Samovar_Mode);
    if (Samovar_Mode == SAMOVAR_BEER_MODE) {
      responseProgram = get_beer_program();
    } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
      responseProgram = get_dist_program();
    } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
      responseProgram = get_nbk_program();
    } else {
      responseProgram = get_program(PROGRAM_END);
    }
    if (!queue_pending_program(pendingMode, wProgramParam->value())) {
      send_program_json_response(request, 503, false, F("BUSY: предыдущее изменение программы ещё не применено"), String());
      return;
    }
  }
  if (request->hasArg("vless")) {
    BoilerVolume = request->arg("vless").toFloat();
    if (BoilerVolume <= 0) BoilerVolume = 30.0f; // Защита: если 0, считаем 30л
    heatLossCalculated = false; // Сбрасываем расчет при смене объема
    heatStartMillis = 0;
  }
  send_program_json_response(request, 200, true, String(), responseProgram);
}

void calibrate_command(AsyncWebServerRequest *request) {
  bool cl = false;
  bool isI2C = false;
  if (request->hasArg("pump")) {
    String pump = request->arg("pump");
    pump.toLowerCase();
    if (pump == "i2c") isI2C = true;
  }
  if (request->params() >= 1) {
    if (request->hasArg("stpstep")) {
      CurrrentStepperSpeed = request->arg("stpstep").toInt();
    }
    if (!isI2C) {
      if (request->hasArg("start") && startval == 0) {
        if (!queue_samovar_command(CALIBRATE_START)) {
          request->send(503, "text/plain", "BUSY");
          return;
        }
      }
      if (request->hasArg("finish") && startval == 100) {
        if (!queue_samovar_command(CALIBRATE_STOP)) {
          request->send(503, "text/plain", "BUSY");
          return;
        }
        cl = true;
      }
    } else if (i2cStepperPump.present) {
      // [W-4] I2C-операции откладываем в loop(); present берём из глобала без I2C.
      if (request->hasArg("start") && !I2CPumpCalibrating) {
        PendingI2CCalCmd cmd = {};
        cmd.is_finish  = false;
        cmd.pumpMlHour = i2c_stepper_mlh_from_step_speed(CurrrentStepperSpeed);
        cmd.stepsPerMl = i2c_stepper_steps_per_ml();
        cmd.cmdSpeed   = CurrrentStepperSpeed;
        if (!queue_pending_i2ccal(cmd)) {
          request->send(503, "text/plain", "BUSY");
          return;
        }
      }
      if (request->hasArg("finish") && I2CPumpCalibrating) {
        PendingI2CCalCmd cmd = {};
        cmd.is_finish = true;
        if (!queue_pending_i2ccal(cmd)) {
          request->send(503, "text/plain", "BUSY");
          return;
        }
        // [C-10/W-8] save_profile() сделает loop() в ветке pending_i2ccal ПОСЛЕ refresh
        //            (порядок важен: иначе в NVS попадёт старый StepperStepMlI2C).
        cl = true;
      }
    }
  }
  // [W-1] Убран vTaskDelay(5): delay/блокировка в async-обработчике недопустима.
  if (cl) {
    int s = 0;
    if (!isI2C) {
      s = round((float)stepper_safe_get_current() / 100) * 100;
    } else {
      s = SamSetup.StepperStepMlI2C * 100;
    }
    request->send(200, "text/plain", (String)s);
  } else
    request->send(200, "text/plain", "OK");
}

void get_data_log(AsyncWebServerRequest *request, String fn) {
  if (schedule_log_flush_if_needed() != LOG_FLUSH_READY) {
    request->send(503, "text/plain", "BUSY");
    return;
  }
  AsyncWebServerResponse *response;
  if (SPIFFS.exists("/" + fn)) {
    response = request->beginResponse(SPIFFS, "/" + fn, String(), true);
  } else {
    response = request->beginResponse(400, "text/plain", "");
  }
  response->addHeader(F("Content-Type"), F("application/octet-stream"));
  response->addHeader(F("Content-Description"), F("File Transfer"));
  response->addHeader(F("Content-Disposition"), "attachment; filename=\"" + fn + "\"");
  response->addHeader(F("Pragma"), F("public"));
  response->addHeader(F("Cache-Control"), F("no-cache"));
  request->send(response);
}

// Сравнение версии веб-интерфейса: без нормализации сервер часто отдаёт CRLF, в SPIFFS после записи
// readStringUntil('\n') оставляет '\r' в локальной строке — условие «не совпадает» выполняется при каждой загрузке.
static void normalize_web_if_version_string(String& v) {
  v.trim();
  v.replace("\r", "");
}

static bool write_web_file_atomic(const String& path, const String& content) {
  String tmpPath = path + ".tmp";
  String backupPath = path + ".bak";

  SPIFFS.remove(tmpPath);
  SPIFFS.remove(backupPath);

  File wf = SPIFFS.open(tmpPath, FILE_WRITE);
  if (!wf) {
    Serial.println("WEB interface write failed, open tmp: " + tmpPath);
    SPIFFS.remove(tmpPath);
    return false;
  }

  size_t written = wf.write((const uint8_t*)content.c_str(), content.length());
  wf.close();
  if (written != content.length()) {
    Serial.println("WEB interface write failed, partial tmp: " + tmpPath);
    SPIFFS.remove(tmpPath);
    return false;
  }

  File rf = SPIFFS.open(tmpPath, FILE_READ);
  if (!rf) {
    Serial.println("WEB interface write failed, reopen tmp: " + tmpPath);
    SPIFFS.remove(tmpPath);
    return false;
  }
  size_t tmpSize = rf.size();
  rf.close();
  if (tmpSize != content.length()) {
    Serial.println("WEB interface write failed, tmp size: " + tmpPath);
    SPIFFS.remove(tmpPath);
    return false;
  }

  bool hadFinal = SPIFFS.exists(path);
  if (hadFinal && !SPIFFS.rename(path, backupPath)) {
    Serial.println("WEB interface write failed, backup final: " + path);
    SPIFFS.remove(tmpPath);
    return false;
  }

  if (!SPIFFS.rename(tmpPath, path)) {
    Serial.println("WEB interface write failed, install tmp: " + path);
    SPIFFS.remove(tmpPath);
    if (hadFinal && !SPIFFS.rename(backupPath, path)) {
      Serial.println("WEB interface rollback failed: " + path);
    }
    return false;
  }

  if (hadFinal) {
    SPIFFS.remove(backupPath);
  }
  return true;
}

static bool web_file_content_empty_invalid(const String& fn, get_web_type type, const String& content) {
  if (content.length() != 0) {
    return false;
  }
  if (type == GET_CONTENT || type == SAVE_FILE_OVERRIDE || type == SAVE_FILE_IF_NOT_EXIST) {
    Serial.println("WEB interface download failed, empty body: " + fn);
    return true;
  }
  return false;
}

void get_web_interface() {
  String version;
  String local_version;

  version = get_web_file("version.txt", GET_CONTENT);
  if (version == "<ERR>") {
    Serial.println("WEB interface update failed on version.txt");
    return;
  }
  normalize_web_if_version_string(version);

  Serial.print(F("WEB interface version = "));
  Serial.println(version);

  File fn = SPIFFS.open("/version.txt", FILE_READ);
  if (fn) {
    local_version = fn.readString();
    fn.close();
    normalize_web_if_version_string(local_version);
  }
  Serial.print(F("Local interface version = "));
  Serial.println(local_version);
  if (version != local_version) {
    bool updateOk = true;
    auto updateFile = [&](String fn, get_web_type type) {
      if (!updateOk) return;
      String result = get_web_file(fn, type);
      if (result == "<ERR>") {
        Serial.println("WEB interface update failed on " + fn);
        updateOk = false;
      }
    };

    updateFile("index.htm", SAVE_FILE_OVERRIDE);
    updateFile("Green.png", SAVE_FILE_OVERRIDE);
    updateFile("Red_light.gif", SAVE_FILE_OVERRIDE);
    updateFile("alarm.mp3", SAVE_FILE_OVERRIDE);
    updateFile("favicon.ico", SAVE_FILE_OVERRIDE);
    updateFile("minus.png", SAVE_FILE_OVERRIDE);
    updateFile("plus.png", SAVE_FILE_OVERRIDE);

    //s += get_web_file("style.css", SAVE_FILE_OVERRIDE);
    updateFile("style.css.gz", SAVE_FILE_OVERRIDE);

    updateFile("beer.htm", SAVE_FILE_OVERRIDE);
    updateFile("bk.htm", SAVE_FILE_OVERRIDE);
    updateFile("nbk.htm", SAVE_FILE_OVERRIDE);
    updateFile("brewxml.htm", SAVE_FILE_OVERRIDE);
    updateFile("calibrate.htm", SAVE_FILE_OVERRIDE);
    updateFile("chart.htm", SAVE_FILE_OVERRIDE);
    updateFile("distiller.htm", SAVE_FILE_OVERRIDE);
    updateFile("i2cstepper.htm", SAVE_FILE_OVERRIDE);
    //s += get_web_file("edit.htm", SAVE_FILE_OVERRIDE);
    updateFile("edit.htm.gz", SAVE_FILE_OVERRIDE);

    updateFile("program.htm", SAVE_FILE_OVERRIDE);
    updateFile("setup.htm", SAVE_FILE_OVERRIDE);

    updateFile("beer.lua", SAVE_FILE_IF_NOT_EXIST);
    updateFile("bk.lua", SAVE_FILE_IF_NOT_EXIST);
    updateFile("nbk.lua", SAVE_FILE_IF_NOT_EXIST);
    updateFile("dist.lua", SAVE_FILE_IF_NOT_EXIST);
    updateFile("init.lua", SAVE_FILE_IF_NOT_EXIST);
    updateFile("rectificat.lua", SAVE_FILE_IF_NOT_EXIST);
    updateFile("script.lua", SAVE_FILE_IF_NOT_EXIST);

    updateFile("btn_rect_button1.lua", SAVE_FILE_IF_NOT_EXIST);
    updateFile("btn_rect_button2.lua", SAVE_FILE_IF_NOT_EXIST);
    updateFile("btn_beer_button1.lua", SAVE_FILE_IF_NOT_EXIST);
    updateFile("btn_beer_button2.lua", SAVE_FILE_IF_NOT_EXIST);
    updateFile("btn_dist_button1.lua", SAVE_FILE_IF_NOT_EXIST);
    updateFile("btn_dist_button2.lua", SAVE_FILE_IF_NOT_EXIST);
    updateFile("btn_bk_button1.lua", SAVE_FILE_IF_NOT_EXIST);
    updateFile("btn_bk_button2.lua", SAVE_FILE_IF_NOT_EXIST);
    updateFile("btn_nbk_button1.lua", SAVE_FILE_IF_NOT_EXIST);
    updateFile("btn_nbk_button2.lua", SAVE_FILE_IF_NOT_EXIST);



    updateFile("program_fruit.txt", SAVE_FILE_IF_NOT_EXIST);
    updateFile("program_grain.txt", SAVE_FILE_IF_NOT_EXIST);
    updateFile("program_shugar.txt", SAVE_FILE_IF_NOT_EXIST);

    if (updateOk) {
      // Версию уже скачали в начале функции — записываем нормализованную строку, без повторного HTTP.
      String versionMarker = version + "\n";
      if (!write_web_file_atomic("/version.txt", versionMarker)) {
        Serial.println("WEB interface update failed on version marker; local version marker was not changed.");
        updateOk = false;
      }
    }

    if (!updateOk) {
      Serial.println("WEB interface update aborted; local version marker was not changed.");
    }
  }
}

String get_web_file(String fn, get_web_type type) {
  if (type == SAVE_FILE_IF_NOT_EXIST && SPIFFS.exists("/" + fn)) {
    Serial.println("File " + fn + " already exist.");
    return "";
  }

  String url = "http://web.samovar-tool.ru/" + String(SAMOVAR_VERSION) + "/" + fn + "?" + micros();
  Serial.print("url = ");
  Serial.println(url);

  String s = http_sync_request_get(url);

  if (s == "<ERR>") {
    return s;
  } else if (web_file_content_empty_invalid(fn, type, s)) {
    return "<ERR>";
  } else {
    if (type == GET_CONTENT) {
      return s;
    } else {
      if (!write_web_file_atomic("/" + fn, s)) {
        return "<ERR>";
      }
      //Serial.print("responseText = ");
      //Serial.println(s);
    }
    Serial.println("Done (L=" + String(s.length()) + ")");
  }

  return "";
}

static void abort_http_request(void* requestPtr) {
  asyncHTTPrequest* request = static_cast<asyncHTTPrequest*>(requestPtr);
  request->abort();

  uint32_t abortStartTime = millis();
  while (request->readyState() != 4 && millis() - abortStartTime < 1000) {
    vTaskDelay(25 / portTICK_PERIOD_MS);
  }
}

String http_sync_request_get(String url) {
  asyncHTTPrequest request;
  request.setDebug(false);
  const uint32_t timeoutMs = 8000;
  request.setTimeout(8); // Таймаут восемь секунд (внутренний по отсутствию активности)
  if (!request.open("GET", url.c_str())) {
    Serial.println("HTTP GET open() failed");
    return "<ERR>";
  }
  
  unsigned long startTime = millis();
  while (request.readyState() < 1) {
    if (millis() - startTime > timeoutMs) { // Общий таймаут
      Serial.println("Timeout: readyState never reached 1");
      abort_http_request(&request);
      return "<ERR>";
    }
    vTaskDelay(25 / portTICK_PERIOD_MS);
  }
  vTaskDelay(150 / portTICK_PERIOD_MS);
  if (!request.send()) {
    Serial.println("HTTP GET send() failed");
    abort_http_request(&request);
    return "<ERR>";
  }
  vTaskDelay(150 / portTICK_PERIOD_MS);
  // Таймаут для ожидания завершения запроса (readyState == 4)
  startTime = millis();
  while (request.readyState() != 4) {
    if (millis() - startTime > timeoutMs) { // Общий таймаут
      Serial.println("Timeout: request not completed within 8 seconds");
      abort_http_request(&request);
      return "<ERR>";
    }
    vTaskDelay(25 / portTICK_PERIOD_MS);
  }
  vTaskDelay(60 / portTICK_PERIOD_MS);
  if (request.responseHTTPcode() >= 0) {
    if (request.responseHTTPcode() != 200) {
      Serial.print(F("responseHTTPcode = "));
      Serial.println(request.responseHTTPcode());
      Serial.println("Content " + url + " download error");
      return "<ERR>";
    }
    String response = request.responseText();
    size_t expectedLength = request.responseLength();
    if (expectedLength > 0 && response.length() != expectedLength) {
      Serial.println("Content " + url + " incomplete: " + String(response.length()) + "/" + String(expectedLength));
      return "<ERR>";
    }
    return response;
  } else {
    Serial.print(F("responseHTTPcode = "));
    Serial.println(request.responseHTTPcode());
    Serial.println("Content " + url + " download error (2)");
    return "<ERR>";
  }  
  return "";
}

String http_sync_request_post(String url, String body, String ContentType) {
  asyncHTTPrequest request;
  request.setDebug(false);
  const uint32_t timeoutMs = 8000;
  request.setTimeout(8);  //Таймаут восемь секунд (внутренний по отсутствию активности)

  if (!request.open("POST", url.c_str())) {  //URL
    Serial.println("HTTP POST open() failed");
    return "<ERR>";
  }
  unsigned long startTime = millis();
  while (request.readyState() < 1) {
    if (millis() - startTime > timeoutMs) { // Общий таймаут
      Serial.println("Timeout: readyState never reached 1");
      abort_http_request(&request);
      return "<ERR>";
    }
    vTaskDelay(25 / portTICK_PERIOD_MS);
  }
  vTaskDelay(150 / portTICK_PERIOD_MS);
  request.setReqHeader("Content-Type", getValue(ContentType, ':', 1).c_str());
  if (!request.send(body)) {
    Serial.println("HTTP POST send() failed");
    abort_http_request(&request);
    return "<ERR>";
  }

  vTaskDelay(150 / portTICK_PERIOD_MS);
  // Таймаут для ожидания завершения запроса (readyState == 4)
  startTime = millis();
  while (request.readyState() != 4) {
    if (millis() - startTime > timeoutMs) { // Общий таймаут
      Serial.println("Timeout: request not completed within 8 seconds");
      abort_http_request(&request);
      return "<ERR>";
    }
    vTaskDelay(25 / portTICK_PERIOD_MS);
  }
  vTaskDelay(60 / portTICK_PERIOD_MS);
  if (request.responseHTTPcode() >= 0) {
    return request.responseText();
  } else {
    return "<ERR>";
  }
}
