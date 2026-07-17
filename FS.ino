#include <Arduino.h>
#include <EEPROM.h>

#include "Samovar.h"
#include "samovar_api.h"
#include "runtime_helpers.h"
#include "SPIFFSEditor.h"

static File fileToAppend;
static volatile bool data_log_ready = false;

bool flush_data_log() {
  bool locked = log_file_lock(pdMS_TO_TICKS(500));
  if (!locked) {
    Serial.println(F("data log flush skipped: file busy"));
    return false;
  }
  if (fileToAppend) {
    fileToAppend.flush();
  }
  log_file_unlock(true);
  return true;
}

bool close_data_log() {
  bool locked = log_file_lock(pdMS_TO_TICKS(500));
  if (!locked) {
    Serial.println(F("data log close skipped: file busy"));
    return false;
  }
  data_log_ready = false;
  if (fileToAppend) {
    fileToAppend.close();
  }
  log_file_unlock(true);
  return true;
}

bool request_data_log_close() {
  bool locked = pending_command_lock(pdMS_TO_TICKS(50));
  if (!locked) {
    Serial.println(F("data log close request failed: command busy"));
    return false;
  }
  pending_log_close_flag = true;
  pending_log_flush_flag = false;
  pending_log_flush_seq = 0;
  pending_command_unlock(true);
  return true;
}

bool data_log_close_pending() {
  bool locked = pending_command_lock(pdMS_TO_TICKS(50));
  if (!locked) return true;
  const bool pending = pending_log_close_flag;
  pending_command_unlock(true);
  return pending;
}

void process_pending_data_log_ops() {
  bool hasPendingLogClose = false;
  bool hasPendingLogFlush = false;
  uint32_t logFlushSeq = 0;
  {
    bool locked = pending_command_lock(pdMS_TO_TICKS(50));
    if (!locked) {
      Serial.println(F("data log pending ops skipped: command busy"));
      return;
    }
    if (pending_log_close_flag) {
      hasPendingLogClose = true;
    } else if (pending_log_flush_flag) {
      logFlushSeq = pending_log_flush_seq;
      hasPendingLogFlush = true;
    }
    pending_command_unlock(true);
  }

  if (hasPendingLogClose) {
    if (!close_data_log()) {
      return;
    }
    bool locked = pending_command_lock(pdMS_TO_TICKS(50));
    if (locked) {
      pending_log_close_flag = false;
      pending_log_flush_flag = false;
      pending_log_flush_seq = 0;
      log_flush_seq = log_write_seq;
    }
    pending_command_unlock(locked);
    return;
  }

  if (hasPendingLogFlush) {
    if (!flush_data_log()) {
      return;
    }
    bool locked = pending_command_lock(pdMS_TO_TICKS(50));
    if (locked) {
      if (log_flush_seq < logFlushSeq) {
        log_flush_seq = logFlushSeq;
      }
      if (!pending_log_close_flag && pending_log_flush_flag && pending_log_flush_seq <= logFlushSeq) {
        pending_log_flush_flag = false;
        pending_log_flush_seq = 0;
      }
    }
    pending_command_unlock(locked);
  }
}

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

// Инициализация FFS
FsInitResult FS_init(void) {
  bool formatted = false;
  if (!SPIFFS.begin(false)) {
    Serial.println(F("Не удалось подключиться к файловой системе, форматируем..."));
    if (!SPIFFS.format()) {
      Serial.println(F("Не удалось отформатировать файловую систему, загрузите интерфейс через Arduino"));
      return FS_INIT_MOUNT_FAILED;
    }
    if (!SPIFFS.begin(false)) {
      Serial.println(F("Ошибка файловой системы! Загрузите через Arduino"));
      return FS_INIT_MOUNT_FAILED;
    }
    formatted = true;
  }

  total_byte = SPIFFS.totalBytes();

  //  {
  //    File dir = SPIFFS.open("/");
  //    while (dir.openNextFile()) {
  //      String fileName = dir.name();
  //      //size_t fileSize = dir.size();
  //    }
  //  }

  return formatted ? FS_INIT_FORMATTED : FS_INIT_OK;
}

void FS_register_web_handlers(void) {
  events.onConnect([](AsyncEventSourceClient * client) {
    client->send("hello!", NULL, millis(), 1000);
  });
  server.addHandler(&events);

  // DIY device: /edit stays local-network only and intentionally unauthenticated.
  server.addHandler(new SPIFFSEditor(SPIFFS));

  server.onNotFound([](AsyncWebServerRequest * request) {
    Serial.printf("NOT_FOUND: ");
    if (request->method() == HTTP_GET)
      Serial.printf("GET");
    else if (request->method() == HTTP_POST)
      Serial.printf("POST");
    else if (request->method() == HTTP_DELETE)
      Serial.printf("DELETE");
    else if (request->method() == HTTP_PUT)
      Serial.printf("PUT");
    else if (request->method() == HTTP_PATCH)
      Serial.printf("PATCH");
    else if (request->method() == HTTP_HEAD)
      Serial.printf("HEAD");
    else if (request->method() == HTTP_OPTIONS)
      Serial.printf("OPTIONS");
    else
      Serial.printf("UNKNOWN");
    Serial.printf(" http://%s%s\n", request->host().c_str(), request->url().c_str());

    if (request->contentLength()) {
      Serial.printf("_CONTENT_TYPE: %s\n", request->contentType().c_str());
      Serial.printf("_CONTENT_LENGTH: %u\n", request->contentLength());
    }

    int headers = request->headers();
    int i;
    for (i = 0; i < headers; i++) {
      const AsyncWebHeader *h = request->getHeader(i);
      Serial.printf("_HEADER[%s]: %s\n", h->name().c_str(), h->value().c_str());
    }

    int params = request->params();
    for (i = 0; i < params; i++) {
      const AsyncWebParameter *p = request->getParam(i);
      if (p->isFile()) {
        Serial.printf("_FILE[%s]: %s, size: %u\n", p->name().c_str(), p->value().c_str(), p->size());
      } else if (p->isPost()) {
        Serial.printf("_POST[%s]: %s\n", p->name().c_str(), p->value().c_str());
      } else {
        Serial.printf("_GET[%s]: %s\n", p->name().c_str(), p->value().c_str());
      }
    }

    request->send(404);
  });
  server.onFileUpload([](AsyncWebServerRequest * request, const String & filename, size_t index, uint8_t *data, size_t len, bool final) {
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
  server.onRequestBody([](AsyncWebServerRequest * request, uint8_t *data, size_t len, size_t index, size_t total) {
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
}

bool exists(String path) {
  File file = SPIFFS.open(path, "r");
  bool yes = file && !file.isDirectory();
  file.close();
  return yes;
}

bool create_data() {
  data_log_ready = false;

  //Если режим ректификация, запишем в файл текущую программу отбора
  if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE || Samovar_Mode == SAMOVAR_BEER_MODE || Samovar_Mode == SAMOVAR_DISTILLATION_MODE || Samovar_Mode == SAMOVAR_NBK_MODE) {
    File filePrg = SPIFFS.open("/prg.csv", FILE_WRITE);
    if (!filePrg) {
      Serial.println(F("data log create failed: open prg.csv"));
      return false;
    }
    String programText;
    if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE) {
      programText = get_program(PROGRAM_END);
    } else if (Samovar_Mode == SAMOVAR_BEER_MODE) {
      programText = get_beer_program();
    } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
      programText = get_dist_program();
    } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
      programText = get_nbk_program();
    }
    size_t programWritten = filePrg.println(programText);
    Serial.println(programText);
    filePrg.close();
    if (programWritten == 0) {
      Serial.println(F("data log create failed: write prg.csv"));
      return false;
    }
  }

  //Удаляем старый файл с архивным логом
  bool locked = log_file_lock(portMAX_DELAY);
  if (!locked) {
    Serial.println(F("data log create failed: mutex unavailable"));
    return false;
  }

  if (SPIFFS.exists("/data_old.csv")) {
    if (!SPIFFS.remove("/data_old.csv")) {
      log_file_unlock(true);
      Serial.println(F("data log create failed: remove data_old.csv"));
      return false;
    }
  }
  //Переименовываем файл с логом в архивный (на всякий случай)
  if (SPIFFS.exists("/data.csv")) {
    if (fileToAppend) {
      fileToAppend.close();
    }

    if (!SPIFFS.rename("/data.csv", "/data_old.csv")) {
      log_file_unlock(true);
      Serial.println(F("data log create failed: rename data.csv"));
      return false;
    }
  }
  File fileToWrite = SPIFFS.open("/data.csv", FILE_WRITE);
  if (!fileToWrite) {
    log_file_unlock(true);
    Serial.println(F("data log create failed: open data.csv"));
    return false;
  }
  String str = "Date,Steam,Pipe,Water,Tank,Pressure";
#ifdef WRITE_PROGNUM_IN_LOG
  str += ",ProgNum";
#endif
  size_t headerWritten = fileToWrite.println(str);
  if (headerWritten == 0) {
    fileToWrite.close();
    log_file_unlock(true);
    Serial.println(F("data log create failed: write header"));
    return false;
  }

  fileToWrite.close();

  SteamSensor.PrevTemp = 0;
  PipeSensor.PrevTemp = 0;
  WaterSensor.PrevTemp = 0;
  TankSensor.PrevTemp = 0;
  SteamSensor.LogPrevTemp = 0;
  PipeSensor.LogPrevTemp = 0;
  WaterSensor.LogPrevTemp = 0;
  TankSensor.LogPrevTemp = 0;
  bme_prev_pressure = 0;
  prev_ProgramNum = PROGRAM_END;
  STcnt = 0;

  fileToAppend = SPIFFS.open("/data.csv", FILE_APPEND);
  if (!fileToAppend) {
    log_file_unlock(true);
    Serial.println(F("data log create failed: open append data.csv"));
    return false;
  }
  log_write_seq = 0;
  log_flush_seq = 0;
  {
    bool pendingLocked = pending_command_lock(portMAX_DELAY);
    if (!pendingLocked) {
      fileToAppend.close();
      log_file_unlock(true);
      Serial.println(F("data log create failed: pending mutex unavailable"));
      return false;
    }
    pending_log_close_flag = false;
    pending_log_flush_flag = false;
    pending_log_flush_seq = 0;
    pending_command_unlock(true);
  }
  data_log_ready = true;
  log_file_unlock(true);
  return true;
}

String append_data() {
  if (!data_log_ready) return "";

  //Если режим ректификация и идет отбор, запишем в файл текущий статус
  STcnt++;
  if ((Samovar_Mode == SAMOVAR_RECTIFICATION_MODE || Samovar_Mode == SAMOVAR_BEER_MODE || Samovar_Mode == SAMOVAR_DISTILLATION_MODE || Samovar_Mode == SAMOVAR_NBK_MODE) && STcnt > 10) {
    String sapd = "P=" + String(ProgramNum + 1);
    if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE) {
      sapd += ";V=" + String(get_liquid_volume());
    } else if (Samovar_Mode == SAMOVAR_BEER_MODE) {
      sapd += ";T=" + WthdrwTimeS;
    }
    bool stateLocked = log_file_lock(pdMS_TO_TICKS(50));
    if (stateLocked) {
      if (!data_log_ready) {
        STcnt = 0;
        log_file_unlock(true);
        return "";
      } else {
        File fileState = SPIFFS.open("/state.csv", FILE_WRITE);
        if (!fileState) {
          Serial.println(F("state log write failed: open state.csv"));
        } else {
          size_t stateWritten = fileState.println(sapd);
          if (stateWritten == 0) {
            Serial.println(F("state log write failed: write state.csv"));
          }
          fileState.close();
        }
      }
      log_file_unlock(true);
    } else {
      Serial.println(F("state log write skipped: file busy"));
    }
    STcnt = 0;
  }

  //Если значения лога совпадают с предыдущим - в файл писать не будем
  float steamTemp = SteamSensor.avgTemp;
  float pipeTemp = PipeSensor.avgTemp;
  float waterTemp = WaterSensor.avgTemp;
  float tankTemp = TankSensor.avgTemp;
  float pressure = bme_pressure;
  uint8_t programNum = ProgramNum;
  uint8_t changedField = 0;

  if (steamTemp != SteamSensor.LogPrevTemp) {
    changedField = 1;
  } else if (pipeTemp != PipeSensor.LogPrevTemp) {
    changedField = 2;
  } else if (waterTemp != WaterSensor.LogPrevTemp) {
    changedField = 3;
  } else if (tankTemp != TankSensor.LogPrevTemp) {
    changedField = 4;
  } else if (bme_prev_pressure != pressure) {
    changedField = 5;
#ifdef WRITE_PROGNUM_IN_LOG
  } else if (prev_ProgramNum != programNum) {
    changedField = 6;
#endif
  }

  if (changedField > 0) {
    String str;
    str = Crt + ",";
    str += format_float(steamTemp, 3);
    str += ",";
    str += format_float(pipeTemp, 3);
    str += ",";
    str += format_float(waterTemp, 3);
    str += ",";
    str += format_float(tankTemp, 3);
    str += ",";
    str += format_float(pressure, 2);

#ifdef WRITE_PROGNUM_IN_LOG
    str += ",";
    str += programNum + 1;
#endif

    bool locked = log_file_lock(pdMS_TO_TICKS(50));
    if (!locked) {
      Serial.println(F("data log append skipped: file busy"));
      return "";
    }
    if (!data_log_ready) {
      log_file_unlock(true);
      return "";
    }
    if (!fileToAppend) {
      data_log_ready = false;
      log_file_unlock(true);
      Serial.println(F("data log append failed: append file closed"));
      return "";
    }
    size_t written = fileToAppend.println(str);
    if (written == 0) {
      log_file_unlock(true);
      Serial.println(F("data log append failed: write data.csv"));
      return "";
    }
    __sync_add_and_fetch(&log_write_seq, 1);

    switch (changedField) {
      case 1: SteamSensor.LogPrevTemp = steamTemp; break;
      case 2: PipeSensor.LogPrevTemp = pipeTemp; break;
      case 3: WaterSensor.LogPrevTemp = waterTemp; break;
      case 4: TankSensor.LogPrevTemp = tankTemp; break;
      case 5: bme_prev_pressure = pressure; break;
#ifdef WRITE_PROGNUM_IN_LOG
      case 6: prev_ProgramNum = programNum; break;
#endif
      default: break;
    }
    log_file_unlock(true);

    {
      static bool memory_warning_sent = false;
      used_byte = SPIFFS.usedBytes();
      if (total_byte - used_byte < 400) {
        //Кончилось место, удалим старый файл. Надо было сохранять раньше
        bool cleanupLocked = log_file_lock(pdMS_TO_TICKS(50));
        if (cleanupLocked) {
          if (SPIFFS.exists("/data_old.csv")) {
            if (!SPIFFS.remove("/data_old.csv")) {
              Serial.println(F("data log cleanup failed: remove data_old.csv"));
            }
          }
          log_file_unlock(true);
        } else {
          Serial.println(F("data log cleanup skipped: file busy"));
        }
      }
      vTaskDelay(10 / portTICK_PERIOD_MS);
      if (total_byte - used_byte < 50) {
        if (!memory_warning_sent) {
          SendMsg("Заканчивается память! Всего: " + String(total_byte) + ", использовано: " + String(used_byte), ALARM_MSG);
          memory_warning_sent = true;
        }
      } else {
        // Сбрасываем флаг, если память освободилась
        memory_warning_sent = false;
      }
    }

    return str;
  }
  return "";
}
