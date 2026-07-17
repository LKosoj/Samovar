#ifndef __SPIFFSEditor_H_
#define __SPIFFSEditor_H_

#include <FS.h>
#include <ESPAsyncWebServer.h>
#include "Samovar.h"
#include "samovar_api.h"
#include "runtime_helpers.h"

static const char *SPIFFS_EDITOR_UPLOAD_ERROR_ATTR = "spiffs_upload_error";
static const char *SPIFFS_EDITOR_BUSY_PROCESS_ACTIVE = "process_active";
#ifdef USE_LUA
extern volatile bool pending_lua_reload_flag;
static const char *SPIFFS_EDITOR_LUA_RELOAD_BUSY = "lua_reload_busy";
#endif


class SPIFFSEditor: public AsyncWebHandler {
  private:
    fs::FS _fs;
  public:
#ifdef ESP32
    SPIFFSEditor(const fs::FS& fs);
#else
    SPIFFSEditor(const fs::FS& fs = SPIFFS);
#endif
    virtual bool canHandle(AsyncWebServerRequest *request) const override final;
    virtual void handleRequest(AsyncWebServerRequest *request) override final;
    virtual void handleUpload(AsyncWebServerRequest *request, const String& filename, size_t index, uint8_t *data, size_t len, bool final) override final;
    virtual bool isRequestHandlerTrivial() const override final {
      return false;
    }
};

#define SPIFFS_MAXLENGTH_FILEPATH 32
const char *excludeListFile = "/.exclude.files";

typedef struct ExcludeListS {
  char *item;
  ExcludeListS *next;
} ExcludeList;

static ExcludeList *excludes = NULL;

static String spiffsEditorJsonEscape(const String& value) {
  String escaped;
  escaped.reserve(value.length());
  for (size_t i = 0; i < value.length(); i++) {
    char c = value[i];
    if (c == '"' || c == '\\') {
      escaped += '\\';
      escaped += c;
    } else if (c == '\n') {
      escaped += "\\n";
    } else if (c == '\r') {
      escaped += "\\r";
    } else if (c == '\t') {
      escaped += "\\t";
    } else {
      escaped += c;
    }
  }
  return escaped;
}

static bool matchWild(const char *pattern, const char *testee) {
  const char *nxPat = NULL, *nxTst = NULL;

  while (*testee) {
    if (( *pattern == '?' ) || (*pattern == *testee)) {
      pattern++; testee++;
      continue;
    }
    if (*pattern == '*') {
      nxPat = pattern++; nxTst = testee;
      continue;
    }
    if (nxPat) {
      pattern = nxPat + 1; testee = ++nxTst;
      continue;
    }
    return false;
  }
  while (*pattern == '*') {
    pattern++;
  }
  return (*pattern == 0);
}

static bool addExclude(const char *item) {
  size_t len = strlen(item);
  if (!len) {
    return false;
  }
  ExcludeList *e = (ExcludeList *)malloc(sizeof(ExcludeList));
  if (!e) {
    return false;
  }
  e->item = (char *)malloc(len + 1);
  if (!e->item) {
    free(e);
    return false;
  }
  memcpy(e->item, item, len + 1);
  e->next = excludes;
  excludes = e;
  return true;
}

static void loadExcludeList(fs::FS &_fs, const char *filename) {
  static char linebuf[SPIFFS_MAXLENGTH_FILEPATH];
  fs::File excludeFile = _fs.open(filename, "r");
  if (!excludeFile) {
    //addExclude("/*.js.gz");
    return;
  }
#ifdef ESP32
  if (excludeFile.isDirectory()) {
    excludeFile.close();
    return;
  }
#endif
  if (excludeFile.size() > 0) {
    uint8_t idx;
    bool isOverflowed = false;
    while (excludeFile.available()) {
      linebuf[0] = '\0';
      idx = 0;
      int lastChar;
      do {
        lastChar = excludeFile.read();
        if (lastChar != '\r') {
          linebuf[idx++] = (char) lastChar;
        }
      } while ((lastChar >= 0) && (lastChar != '\n') && (idx < SPIFFS_MAXLENGTH_FILEPATH));

      if (isOverflowed) {
        isOverflowed = (lastChar != '\n');
        continue;
      }
      isOverflowed = (idx >= SPIFFS_MAXLENGTH_FILEPATH);
      linebuf[idx - 1] = '\0';
      if (!addExclude(linebuf)) {
        excludeFile.close();
        return;
      }
    }
  }
  excludeFile.close();
}

static bool isExcluded(fs::FS &_fs, const char *filename) {
  if (excludes == NULL) {
    loadExcludeList(_fs, excludeListFile);
  }
  ExcludeList *e = excludes;
  while (e) {
    if (matchWild(e->item, filename)) {
      return true;
    }
    e = e->next;
  }
  return false;
}

// WEB HANDLER IMPLEMENTATION

#ifdef ESP32
SPIFFSEditor::SPIFFSEditor(const fs::FS& fs)
#else
SPIFFSEditor::SPIFFSEditor(const fs::FS& fs)
#endif
  : _fs(fs)
{}

bool SPIFFSEditor::canHandle(AsyncWebServerRequest *request) const {
  if (request->url().equalsIgnoreCase("/edit")) {
    if (request->method() == HTTP_GET) {
      if (request->hasParam("list"))
        return true;
      if (request->hasParam("edit")) {
        String p = request->arg("edit");
        if (p.length() == 0) {
          return false;
        }
        if (p[0] != '/') p = "/" + p;
        //        request->_tempFile = _fs.open(request->arg("edit"), "r");
        //request->_tempFile = _fs.open(p, "r");
        fs::FS& ref = const_cast <fs::FS&>(_fs);
        request->_tempFile = ref.open(p, "r");
        if (!request->_tempFile) {
          return false;
        }
#ifdef ESP32
        if (request->_tempFile.isDirectory()) {
          request->_tempFile.close();
          return false;
        }
#endif
      }
      if (request->hasParam("download")) {
        String p = request->arg("download");
        if (p.length() == 0) {
          return false;
        }
        if (p[0] != '/') p = "/" + p;
        //request->_tempFile = _fs.open(p, "r");
        fs::FS& ref = const_cast <fs::FS&>(_fs);
        request->_tempFile = ref.open(p, "r");
        if (!request->_tempFile) {
          return false;
        }
#ifdef ESP32
        if (request->_tempFile.isDirectory()) {
          request->_tempFile.close();
          return false;
        }
#endif
      }
//      request->addInterestingHeader("If-Modified-Since");
      return true;
    }
    else if (request->method() == HTTP_POST)
      return true;
    else if (request->method() == HTTP_DELETE)
      return true;
    else if (request->method() == HTTP_PUT)
      return true;

  }
  return false;
}


void SPIFFSEditor::handleRequest(AsyncWebServerRequest *request) {
  if (request->method() == HTTP_GET) {
    if (request->hasParam("list")) {
      String path = request->getParam("list")->value();
#ifdef ESP32
      File dir = _fs.open(path);
#else
      Dir dir = _fs.openDir(path);
#endif
      path = String();
      String output = "[";
#ifdef ESP32
      File entry = dir.openNextFile();
      while (entry) {
#else
      while (dir.next()) {
        fs::File entry = dir.openFile("r");
#endif
        if (isExcluded(_fs, entry.name())) {
#ifdef ESP32
          entry = dir.openNextFile();
#endif
          continue;
        }
        if (output != "[") output += ',';
        output += "{\"type\":\"";
        output += "file";
        output += "\",\"name\":\"";
        output += spiffsEditorJsonEscape(String(entry.name()));
        output += "\",\"size\":";
        output += String(entry.size());
        output += "}";
#ifdef ESP32
        entry = dir.openNextFile();
#else
        entry.close();
#endif
      }
#ifdef ESP32
      dir.close();
#endif
      output += "]";
      request->send(200, "application/json", output);
      output = String();
    }
    else if (request->hasParam("edit") || request->hasParam("download")) {
      String p = request->_tempFile.name();
      if (p[0] != '/') p = "/" + p;
      request->send(request->_tempFile, p, String(), request->hasParam("download"));
    }
    else {
      const char * buildTime = __DATE__ " " __TIME__ " GMT";
      if (request->header("If-Modified-Since").equals(buildTime)) {
        request->send(304);
      } else {
      if(request->header("Accept-Encoding").indexOf("gzip") != -1 && SPIFFS.exists("/edit.htm.gz")) {  
        AsyncWebServerResponse *response = request->beginResponse(SPIFFS, "/edit.htm.gz", "text/html");
        response->addHeader("Content-Encoding", "gzip");
        response->addHeader("Cache-Control", "max-age=5000");
        request->send(response);
      } else {
        AsyncWebServerResponse *response = request->beginResponse(SPIFFS, "/edit.htm", "text/html");
        response->addHeader("Cache-Control", "max-age=5000");
        request->send(response);
      }
      }
    }
  } else if (request->method() == HTTP_DELETE) {
    // Во время процесса (нагрев/перегонка) редактор не трогает ФС: SysTicker на
    // ядре 0 пишет журнал перегонки под xLogFileSemaphore, а редактор из async_tcp
    // на ядре 1 этот лок не берёт, поэтому удаление файла гонялось бы с записью
    // журнала между ядрами. Гейт закрывает два состояния логгера: активный процесс
    // (идёт дозапись/сброс) и ещё не выполненное отложенное закрытие журнала —
    // request_data_log_close() лишь взводит флаг, а реальное закрытие журнала идёт
    // позже тиком SysTicker, и сразу после конца процесса samovar_process_active()
    // уже ложна, но файл ещё закрывается. Тот же гейт стоит на PUT и в handleUpload().
    if (samovar_process_active() || data_log_close_pending()) {
      request->send(503, "text/plain", "BUSY");
      return;
    }
    if (request->hasParam("path", true)) {
      String p = request->getParam("path", true)->value();
      if (p[0] != '/') p = "/" + p;
      _fs.remove(p);
      request->send(200, "", "DELETE: " + request->getParam("path", true)->value());
    } else
      request->send(404);
  } else if (request->method() == HTTP_POST) {
    if (request->hasParam("data", true, true)) {
      String p = request->getParam("data", true, true)->value();
      if (p[0] != '/') p = "/" + p;
      // handleUpload() не может ответить клиенту сам, поэтому лишь помечает запрос
      // причиной отказа. Любая непустая причина (идёт процесс или барьер смены
      // режима для .lua) означает 503 BUSY.
      if (request->getAttribute(SPIFFS_EDITOR_UPLOAD_ERROR_ATTR).length() > 0) {
        request->send(503, "text/plain", "BUSY");
        return;
      }
      if (_fs.exists(p))
        request->send(200, "", "UPLOADED: " + p);
      else
        request->send(500);
    }
  } else if (request->method() == HTTP_PUT) {
    if (samovar_process_active() || data_log_close_pending()) {
      request->send(503, "text/plain", "BUSY");
      return;
    }
    if (request->hasParam("path", true)) {
      String filename = request->getParam("path", true)->value();
      if (filename[0] != '/') filename = "/" + filename;
      if (_fs.exists(filename)) {
        request->send(200);
      } else {
        fs::File f = _fs.open(filename, "w");
        if (f) {
          f.write((uint8_t)0x00);
          f.close();
          request->send(200, "", "CREATE: " + filename);
        } else {
          request->send(500);
        }
      }
    } else
      request->send(400);
  }
}

void SPIFFSEditor::handleUpload(AsyncWebServerRequest *request, const String& filename, size_t index, uint8_t *data, size_t len, bool final) {
  if (!index) {
      // Тот же гейт, что на DELETE/PUT (активный процесс или ещё не закрытый
      // журнал): при нём файл на запись не открываем, иначе запись чанков из
      // async_tcp гоняется с журналом перегонки. Причину читает handleRequest и
      // отвечает 503 BUSY; _tempFile остаётся закрытым, поэтому чанки ниже
      // просто отбрасываются.
      if (samovar_process_active() || data_log_close_pending()) {
        request->setAttribute(SPIFFS_EDITOR_UPLOAD_ERROR_ATTR, SPIFFS_EDITOR_BUSY_PROCESS_ACTIVE);
        return;
      }
      String p = filename;
      if (filename[0] != '/') p = "/" + filename;
      request->_tempFile = _fs.open(p, "w");
    }
    // Процесс может стартовать на ядре 0 уже ПОСЛЕ первого чанка: тогда запись
    // оставшихся чанков снова гонялась бы с журналом перегонки. Перепроверяем
    // гейт на каждом чанке — если процесс поднялся в ходе загрузки, прекращаем
    // запись (закрываем файл, следующие чанки отбрасываются) и помечаем запрос
    // для ответа 503. Частично записанный файл — издержка потоковой записи в сам
    // целевой файл, а не гонка.
    if (request->_tempFile && (samovar_process_active() || data_log_close_pending())) {
      request->_tempFile.close();
      request->setAttribute(SPIFFS_EDITOR_UPLOAD_ERROR_ATTR, SPIFFS_EDITOR_BUSY_PROCESS_ACTIVE);
      return;
    }
    if (request->_tempFile) {
        if (len) {
            request->_tempFile.write(data, len);
        }
        if (final) {
            request->_tempFile.close();
#ifdef USE_LUA
            if (getValue(filename, '.', 1) == "lua") {
                if (mode_switch_in_progress()) {
                    request->setAttribute(SPIFFS_EDITOR_UPLOAD_ERROR_ATTR, SPIFFS_EDITOR_LUA_RELOAD_BUSY);
                } else {
                    bool locked = pending_command_lock(pdMS_TO_TICKS(50));
                    if (locked && !mode_switch_in_progress()) {
                        pending_lua_reload_flag = true;
                    } else {
                        request->setAttribute(SPIFFS_EDITOR_UPLOAD_ERROR_ATTR, SPIFFS_EDITOR_LUA_RELOAD_BUSY);
                    }
                    pending_command_unlock(locked);
                }
            }
#endif
        }
    }
}


#endif
