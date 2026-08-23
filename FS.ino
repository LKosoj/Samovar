#include <Arduino.h>
#include <EEPROM.h>

#include "Samovar.h"
#include "samovar_api.h"
#include "program_io.h"
#include "runtime_helpers.h"
#include "SPIFFSEditor.h"

static File fileToAppend;
static volatile bool data_log_ready = false;

// Секунд между снимками состояния (/state.csv). Счётчик STcnt тикает раз в секунду
// из SysTicker; подробности - у process_state_snapshot() ниже.
static const uint8_t STATE_SNAPSHOT_PERIOD_S = 30;

// ACPSensor сознательно не пишется в data.csv (заголовок "...,Tank,Pressure"),
// поэтому циклы лога идут по первым четырём элементам sensorList
// (Steam,Pipe,Water,Tank), а не по всем DS_SENSOR_COUNT.
static const uint8_t DS_LOGGED_SENSOR_COUNT = 4;

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
  PendingCommandLockGuard guard;
  if (!guard) {
    Serial.println(F("data log close request failed: command busy"));
    return false;
  }
  pending_log_close_flag = true;
  pending_log_flush_flag = false;
  pending_log_flush_seq = 0;
  return true;
}

bool data_log_close_pending() {
  PendingCommandLockGuard guard;
  if (!guard) return true;
  return pending_log_close_flag;
}

void process_pending_data_log_ops() {
  bool hasPendingLogClose = false;
  bool hasPendingLogFlush = false;
  uint32_t logFlushSeq = 0;
  {
    PendingCommandLockGuard guard;
    if (!guard) {
      Serial.println(F("data log pending ops skipped: command busy"));
      return;
    }
    if (pending_log_close_flag) {
      hasPendingLogClose = true;
    } else if (pending_log_flush_flag) {
      logFlushSeq = pending_log_flush_seq;
      hasPendingLogFlush = true;
    }
  }

  if (hasPendingLogClose) {
    if (!close_data_log()) {
      return;
    }
    PendingCommandLockGuard guard;
    if (guard) {
      pending_log_close_flag = false;
      pending_log_flush_flag = false;
      pending_log_flush_seq = 0;
      log_flush_seq = log_write_seq;
    }
    return;
  }

  if (hasPendingLogFlush) {
    if (!flush_data_log()) {
      return;
    }
    PendingCommandLockGuard guard;
    if (guard) {
      if (log_flush_seq < logFlushSeq) {
        log_flush_seq = logFlushSeq;
      }
      if (!pending_log_close_flag && pending_log_flush_flag && pending_log_flush_seq <= logFlushSeq) {
        pending_log_flush_flag = false;
        pending_log_flush_seq = 0;
      }
    }
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

  return formatted ? FS_INIT_FORMATTED : FS_INIT_OK;
}

void FS_register_web_handlers(void) {
  events.onConnect([](AsyncEventSourceClient * client) {
    client->send("hello!", NULL, millis(), 1000);
  });
  server.addHandler(&events);

  // DIY device: /edit stays local-network only and intentionally unauthenticated.
  // Решение владельца от 23.08.2026 (подтверждено): аутентификации в /edit и во всём
  // веб-интерфейсе нет и намеренно не будет без отдельного нового решения владельца.
  // Следствие: любой, кто оказался в локальной сети устройства (Wi-Fi/Ethernet), может
  // анонимно включить нагрев, изменить программу перегонки и загрузить или удалить
  // файлы через редактор - без пароля и без предупреждения. Поэтому устройство
  // рассчитано ТОЛЬКО на доверенную домашнюю сеть и не должно выставляться в интернет
  // (проброс портов, DMZ и т.п.) - это ответственность того, кто его разворачивает, а
  // не прошивки. Добавлять аутентификацию по собственной инициативе не нужно.
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

#ifdef __SAMOVAR_DEBUG
    // Полный дамп заголовков/параметров - это ~45 мс блокировки веб-задачи на КАЖДЫЙ
    // промах по адресу (а промахи обычны и в штатной работе, например favicon от
    // старой вкладки браузера). На горячем пути во время перегона это заметно тормозит
    // интерфейс, поэтому дамп идёт только в отладочной сборке - тот же флаг уже
    // используется чуть ниже в onFileUpload()/onRequestBody() для той же цели.
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
#endif

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

  //Запишем в файл программу текущего режима. Программа есть у всех режимов
  //(serialize_program_for_mode покрывает все четыре формата), поэтому перечислять
  //режимы вручную больше не нужно.
  String programText = serialize_program_for_mode(Samovar_Mode);
  if (programText.length() > 0) {
    File filePrg = SPIFFS.open("/prg.csv", FILE_WRITE);
    if (!filePrg) {
      Serial.println(F("data log create failed: open prg.csv"));
      return false;
    }
    size_t programWritten = filePrg.print(programText);
    Serial.println(programText);
    filePrg.close();
    if (programWritten == 0) {
      Serial.println(F("data log create failed: write prg.csv"));
      return false;
    }
  }

  //Удаляем старый файл с архивным логом
  // Конечный таймаут вместо portMAX_DELAY: бесконечное ожидание вешало задачу навсегда,
  // если журнал в этот момент удерживала другая задача.
  bool locked = log_file_lock(pdMS_TO_TICKS(2000));
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

  for (uint8_t i = 0; i < DS_LOGGED_SENSOR_COUNT; i++) sensorList[i]->PrevTemp = 0;
  for (uint8_t i = 0; i < DS_LOGGED_SENSOR_COUNT; i++) sensorList[i]->LogPrevTemp = 0;
  bme_prev_pressure = 0;
  prev_ProgramNum = PROGRAM_END;
  // Не обнуляем, а взводим: снимок новой сессии нужен сразу, иначе перезагрузка в
  // первые полминуты оставит на диске состояние с выключенным нагревом.
  STcnt = STATE_SNAPSHOT_PERIOD_S;

  fileToAppend = SPIFFS.open("/data.csv", FILE_APPEND);
  if (!fileToAppend) {
    log_file_unlock(true);
    Serial.println(F("data log create failed: open append data.csv"));
    return false;
  }
  log_write_seq = 0;
  log_flush_seq = 0;
  {
    // Конечный таймаут: этот лок берётся уже под log_file_lock, и бесконечное ожидание
    // здесь превращало любую задержку соседней задачи в вечную взаимную блокировку.
    PendingCommandLockGuard pendingGuard(pdMS_TO_TICKS(2000));
    if (!pendingGuard) {
      fileToAppend.close();
      log_file_unlock(true);
      Serial.println(F("data log create failed: pending mutex unavailable"));
      return false;
    }
    pending_log_close_flag = false;
    pending_log_flush_flag = false;
    pending_log_flush_seq = 0;
  }
  data_log_ready = true;
  log_file_unlock(true);
  return true;
}

// ---- Снимок последнего состояния (/state.csv) ----
// Зачем: после незапланированной перезагрузки не терять набранную программу и
// показать владельцу, на чём остановились. Нагрев по снимку НЕ возобновляется,
// восстановление и отчёт живут в Samovar.ino (restore_state_snapshot).
// Формат файла: первая строка - поля key=value через ';', дальше - текст
// программы в формате режима, пригодный для обратного разбора.
static const char* const STATE_SNAPSHOT_FILE = "/state.csv";
// Больше этого не читаем: программа ограничена MAX_PROGRAM_INPUT_LEN, остальное - мусор.
static const size_t STATE_SNAPSHOT_MAX_BYTES = 2048;
// Подпись последней записанной программы. В простое снимок обновляется только при её
// изменении: иначе запись каждые 30 секунд жгла бы флеш круглые сутки впустую.
static uint32_t state_snapshot_program_hash = 0;

static uint32_t state_snapshot_hash_bytes(uint32_t hash, const void* data, size_t len) {
  const uint8_t* bytes = (const uint8_t*)data;
  for (size_t i = 0; i < len; i++) {
    hash ^= bytes[i];
    hash *= 16777619UL;  // FNV-1a
  }
  return hash;
}

static uint32_t state_snapshot_program_signature() {
  uint32_t hash = 2166136261UL;
  const uint8_t mode = (uint8_t)Samovar_Mode;
  hash = state_snapshot_hash_bytes(hash, &mode, sizeof(mode));
  const uint8_t len = (uint8_t)ProgramLen;
  hash = state_snapshot_hash_bytes(hash, &len, sizeof(len));
  // program[] заполняется целыми структурами из обнулённого черновика (program_commit),
  // поэтому байты выравнивания стабильны и подписи не мешают.
  for (uint8_t i = 0; i < PROGRAM_END; i++) {
    hash = state_snapshot_hash_bytes(hash, &program[i], sizeof(WProgram));
  }
  return hash;
}

static String state_snapshot_header() {
  const uint8_t row = (uint8_t)ProgramNum < PROGRAM_END ? (uint8_t)ProgramNum : 0;
  String out = "P=" + String(row + 1);
  out += ";M=" + String((int)Samovar_Mode);
  out += ";S=" + String((int)SamovarStatusInt);
  out += ";W=" + String((int)startval);
  out += ";L=" + String((int)ProgramLen);
  out += ";H=" + String(PowerOn ? 1 : 0);
  out += ";V=" + String(get_liquid_volume());
  out += ";TT=" + format_float(program[row].Temp, 2);
  out += ";TC=" + format_float(TankSensor.avgTemp, 2);
  out += ";TS=" + format_float(SteamSensor.avgTemp, 2);
  // Время - последним полем: строку собирают вне этого файла, её содержимое не под
  // нашим контролем, и разделитель внутри неё не должен ломать разбор остальных полей.
  out += ";T=" + WthdrwTimeS;
  return out;
}

bool write_state_snapshot() {
  const String header = state_snapshot_header();
  const String programText = serialize_program_for_mode(Samovar_Mode);
  bool locked = log_file_lock(pdMS_TO_TICKS(50));
  if (!locked) {
    Serial.println(F("state log write skipped: file busy"));
    return false;
  }
  File fileState = SPIFFS.open(STATE_SNAPSHOT_FILE, FILE_WRITE);
  if (!fileState) {
    log_file_unlock(true);
    Serial.println(F("state log write failed: open state.csv"));
    return false;
  }
  bool written = fileState.println(header) > 0;
  // Каждая строка программы уже заканчивается переводом строки (program_append_*_row).
  if (written && programText.length() > 0) {
    written = fileState.print(programText) > 0;
  }
  fileState.close();
  log_file_unlock(true);
  if (!written) {
    Serial.println(F("state log write failed: write state.csv"));
    return false;
  }
  return true;
}

void process_state_snapshot() {
  STcnt++;
  if (STcnt < STATE_SNAPSHOT_PERIOD_S) return;
  STcnt = 0;
  const uint32_t signature = state_snapshot_program_signature();
  // PowerOn ловит режимы, которые греют без отбора (Пиво/Сувид на выдержке).
  const bool sessionActive = startval != SAMOVAR_STARTVAL_IDLE || PowerOn;
  if (!sessionActive && signature == state_snapshot_program_hash) return;
  if (write_state_snapshot()) state_snapshot_program_hash = signature;
}

// Запомнить программу как уже сохранённую: вызывается после восстановления снимка,
// чтобы простой сразу после загрузки не переписывал файл тем же содержимым.
void state_snapshot_mark_saved() {
  state_snapshot_program_hash = state_snapshot_program_signature();
}

static bool state_snapshot_field(const String& header, const char* key, String& value) {
  const String pattern = String(key) + "=";
  int index = 0;
  const int length = (int)header.length();
  while (index <= length) {
    const int end = header.indexOf(';', index);
    const String token = end < 0 ? header.substring(index) : header.substring(index, end);
    if (token.startsWith(pattern)) {
      value = token.substring(pattern.length());
      return true;
    }
    if (end < 0) break;
    index = end + 1;
  }
  return false;
}

static bool state_snapshot_uint8(const String& header, const char* key, uint8_t& value) {
  String raw;
  if (!state_snapshot_field(header, key, raw)) return false;
  return parse_bounded_uint8(raw.c_str(), 0, 255, value).ok();
}

bool read_state_snapshot(StateSnapshot& snapshot) {
  snapshot = StateSnapshot{};
  bool locked = log_file_lock(pdMS_TO_TICKS(500));
  if (!locked) {
    Serial.println(F("state snapshot read skipped: file busy"));
    return false;
  }
  File fileState = SPIFFS.open(STATE_SNAPSHOT_FILE, FILE_READ);
  if (!fileState) {
    log_file_unlock(true);
    return false;
  }
  if (fileState.size() > STATE_SNAPSHOT_MAX_BYTES) {
    fileState.close();
    log_file_unlock(true);
    Serial.println(F("state snapshot ignored: file too large"));
    return false;
  }
  const String header = fileState.readStringUntil('\n');
  const String programText = fileState.readString();
  fileState.close();
  log_file_unlock(true);

  // Снимок без режима - это файл прежнего формата (только "P=" и объём). Понять,
  // от какой программы он остался, невозможно, поэтому восстанавливать нечего.
  uint8_t mode = 0;
  if (!state_snapshot_uint8(header, "M", mode)) return false;
  snapshot.mode = mode;
  state_snapshot_uint8(header, "P", snapshot.programRow);
  state_snapshot_uint8(header, "L", snapshot.programLen);
  uint8_t power = 0;
  if (state_snapshot_uint8(header, "H", power)) snapshot.powerOn = power != 0;
  snapshot.programText = programText;
  return true;
}

String append_data() {
  if (!data_log_ready) return "";

  // Снимок состояния больше не привязан к журналу: он пишется отдельно из SysTicker
  // (process_state_snapshot), потому что нужен и для режимов без журнала, и когда
  // сессия не запущена, а программа уже набрана.

  //Если значения лога совпадают с предыдущим - в файл писать не будем
  const float sensorTemp[DS_LOGGED_SENSOR_COUNT] = {
      SteamSensor.avgTemp, PipeSensor.avgTemp, WaterSensor.avgTemp, TankSensor.avgTemp};
  float pressure = bme_pressure;
  uint8_t programNum = ProgramNum;
  uint8_t changedField = 0;

  // Побеждает первое изменившееся поле: сперва четыре датчика по порядку
  // (Steam,Pipe,Water,Tank), потом давление, потом номер программы.
  for (uint8_t i = 0; i < DS_LOGGED_SENSOR_COUNT; i++) {
    if (sensorTemp[i] != sensorList[i]->LogPrevTemp) {
      changedField = i + 1;
      break;
    }
  }
  if (changedField == 0) {
    if (bme_prev_pressure != pressure) {
      changedField = 5;
#ifdef WRITE_PROGNUM_IN_LOG
    } else if (prev_ProgramNum != programNum) {
      changedField = 6;
#endif
    }
  }

  if (changedField > 0) {
    String str;
    str = Crt;
    for (uint8_t i = 0; i < DS_LOGGED_SENSOR_COUNT; i++) {
      str += ",";
      str += format_float(sensorTemp[i], 3);
    }
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
      case 1:
      case 2:
      case 3:
      case 4:
        sensorList[changedField - 1]->LogPrevTemp = sensorTemp[changedField - 1];
        break;
      case 5: bme_prev_pressure = pressure; break;
#ifdef WRITE_PROGNUM_IN_LOG
      case 6: prev_ProgramNum = programNum; break;
#endif
      default: break;
    }
    log_file_unlock(true);

    {
      static bool memory_warning_sent = false;
      // usedBytes() у LittleFS не читает готовое число, а обходит все служебные записи ФС.
      // Раз в секунду это лишняя нагрузка на ядро 0, за которым следит сторожевой таймер,
      // поэтому полный пересчёт делаем раз в десять записей, а между ними ведём оценку по
      // фактически записанному — так порог уборки не срабатывает с опозданием.
      static uint8_t space_check_countdown = 0;
      if (space_check_countdown == 0) {
        space_check_countdown = 10;
        used_byte = SPIFFS.usedBytes();
      } else {
        space_check_countdown--;
        used_byte += written;
        // total_byte - used_byte считается в uint32_t: без ограничения оценка сверху дала бы
        // при вычитании огромное «свободно» и отключила бы и уборку, и предупреждение.
        if (used_byte > total_byte) used_byte = total_byte;
      }
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
