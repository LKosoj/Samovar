#ifndef __SPIFFSEditor_H_
#define __SPIFFSEditor_H_

#include <FS.h>
#include <ESPAsyncWebServer.h>
#include "Samovar.h"
#include "samovar_api.h"
#include "runtime_helpers.h"

static const char *SPIFFS_EDITOR_UPLOAD_ERROR_ATTR = "spiffs_upload_error";
static const char *SPIFFS_EDITOR_BUSY_PROCESS_ACTIVE = "process_active";
static const char *SPIFFS_EDITOR_UPLOAD_BAD_NAME = "bad_name";
static const char *SPIFFS_EDITOR_UPLOAD_WRITE_FAILED = "write_failed";
static const char *SPIFFS_EDITOR_UPLOAD_COMMITTED = "upload_committed";
static const char *SPIFFS_EDITOR_UPLOAD_TOUCHED = "upload_touched";
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
  JsonStringPrint sink(escaped);
  if (!json_write_escaped(sink, value.c_str(), value.length())) {
    Serial.println(F("spiffsEditorJsonEscape: строка обрезана, не хватило памяти"));
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
    // Тот же xLogFileSemaphore, что у журнала на SysTicker. timeout 0: async_tcp
    // нельзя усыплять в ожидании замка. Не взяли — журнал сейчас в файле, 503.
    if (!log_file_lock(0)) {
      request->send(503, "text/plain", "BUSY");
      return;
    }
    if (request->hasParam("path", true)) {
      String p = request->getParam("path", true)->value();
      if (p[0] != '/') p = "/" + p;
      if (_fs.remove(p)) {
        log_file_unlock(true);
        request->send(200, "", "DELETE: " + request->getParam("path", true)->value());
      } else {
        log_file_unlock(true);
        request->send(500, "text/plain", "DELETE FAILED: " + p);
      }
    } else {
      log_file_unlock(true);
      request->send(404);
    }
  } else if (request->method() == HTTP_POST) {
    if (request->hasParam("data", true, true)) {
      String p = request->getParam("data", true, true)->value();
      if (p[0] != '/') p = "/" + p;
      // handleUpload() не может ответить клиенту сам, поэтому лишь помечает запрос
      // причиной отказа. Любая непустая причина (идёт процесс или барьер смены
      // режима для .lua) означает 503 BUSY.
      String uploadError = request->getAttribute(SPIFFS_EDITOR_UPLOAD_ERROR_ATTR);
      if (uploadError == SPIFFS_EDITOR_UPLOAD_BAD_NAME) {
        request->send(400, "text/plain", "BAD NAME: " + p);
        return;
      }
      if (uploadError == SPIFFS_EDITOR_UPLOAD_WRITE_FAILED) {
        request->send(500, "text/plain", "WRITE FAILED: " + p);
        return;
      }
      if (uploadError.length() > 0) {
        if (request->getAttribute(SPIFFS_EDITOR_UPLOAD_COMMITTED) != "1" &&
            request->getAttribute(SPIFFS_EDITOR_UPLOAD_TOUCHED) == "1" &&
            log_file_lock(0)) {
          _fs.remove(p);
          log_file_unlock(true);
        }
        request->send(503, "text/plain", "BUSY");
        return;
      }
      if (request->getAttribute(SPIFFS_EDITOR_UPLOAD_COMMITTED) != "1") {
        if (log_file_lock(0)) {
          _fs.remove(p);
          log_file_unlock(true);
        }
        request->send(500, "text/plain", "WRITE FAILED: " + p);
        return;
      }
      request->send(200, "", "UPLOADED: " + p);
    }
  } else if (request->method() == HTTP_PUT) {
    if (!log_file_lock(0)) {
      request->send(503, "text/plain", "BUSY");
      return;
    }
    if (request->hasParam("path", true)) {
      String filename = request->getParam("path", true)->value();
      if (filename[0] != '/') filename = "/" + filename;
      if (_fs.exists(filename)) {
        log_file_unlock(true);
        request->send(200);
      } else {
        fs::File f = _fs.open(filename, "w");
        if (f) {
          f.write((uint8_t)0x00);
          f.close();
          log_file_unlock(true);
          request->send(200, "", "CREATE: " + filename);
        } else {
          log_file_unlock(true);
          request->send(500);
        }
      }
    } else {
      log_file_unlock(true);
      request->send(400);
    }
  }
}

// Белый список расширений загрузки через /edit - защита от СЛУЧАЙНОЙ порчи, а не от
// злоумышленника (аутентификации в устройстве нет по решению владельца, см. FS.ino).
// Список продиктован реальным составом data_raw/: Lua-скрипты режимов и кнопок,
// текстовые программы дистилляции, и ассеты веб-интерфейса (htm/js/css/картинки/звук).
// Страницы интерфейса СОЗНАТЕЛЬНО не исключены: редактор - штатный способ починить
// устройство (перезалить index.htm/app.js после порчи), и списком имён конкретных
// файлов эту возможность было бы легко отнять по ошибке. Отсекаем только заведомо
// постороннее: имя без расширения или с чужим расширением, ".." или второй '/' внутри
// имени (редактор работает с плоским списком файлов), и имя длиннее
// SPIFFS_MAXLENGTH_FILEPATH (не влезет в /.exclude.files).
// tools/build_web_assets.py при сборке кладёт в data/ (то, что реально прошивается)
// сжатые app.js.gz/chart.js.gz/edit.htm.gz/i2cstepper.htm.gz/brewxml.htm.gz/style.css.gz вместо
// сырых файлов - сервер сам подставляет .gz, если рядом нет несжатого файла. Смотрим
// на расширение ДО .gz (для app.js.gz - на "js"), а не добавляем "gz" в allowed:
// иначе прошёл бы любой файл вида *.exe.gz - последний дот стал бы дырой в белом
// списке вместо самого белого списка.
static bool spiffsEditorNameAllowed(const String &path) {
  if (path.length() == 0 || (int)path.length() >= SPIFFS_MAXLENGTH_FILEPATH) return false;
  if (path.indexOf("..") >= 0) return false;
  if (path.indexOf('/', 1) >= 0) return false;
  int dot = path.lastIndexOf('.');
  if (dot < 0 || dot == (int)path.length() - 1) return false;
  String ext = path.substring(dot + 1);
  ext.toLowerCase();
  if (ext == "gz") {
    String withoutGz = path.substring(0, dot);
    int innerDot = withoutGz.lastIndexOf('.');
    if (innerDot < 0 || innerDot == (int)withoutGz.length() - 1) return false;
    ext = withoutGz.substring(innerDot + 1);
    ext.toLowerCase();
  }
  static const char *const allowed[] = {
    "lua", "htm", "js", "css", "txt", "png", "gif", "ico", "mp3"
  };
  for (size_t i = 0; i < sizeof(allowed) / sizeof(allowed[0]); i++) {
    if (ext == allowed[i]) return true;
  }
  return false;
}

void SPIFFSEditor::handleUpload(AsyncWebServerRequest *request, const String& filename, size_t index, uint8_t *data, size_t len, bool final) {
    String p = filename;
    if (filename[0] != '/') p = "/" + filename;
    if (!index) {
      if (!spiffsEditorNameAllowed(p)) {
        request->setAttribute(SPIFFS_EDITOR_UPLOAD_ERROR_ATTR, SPIFFS_EDITOR_UPLOAD_BAD_NAME);
        return;
      }
    }
    if (request->getAttribute(SPIFFS_EDITOR_UPLOAD_ERROR_ATTR).length() > 0) {
      return;
    }

    // Тот же замок, что у журнала. 0 — не ждать в колбэке async_tcp. Файл на
    // каждый чанк открываем/закрываем под замком: иначе между чанками LittleFS
    // снова гоняется с SysTicker. Не взяли замок — 503, без записи.
    if (!log_file_lock(0)) {
      request->setAttribute(SPIFFS_EDITOR_UPLOAD_ERROR_ATTR, SPIFFS_EDITOR_BUSY_PROCESS_ACTIVE);
      return;
    }

    File wf = _fs.open(p, index ? "a" : "w");
    if (!wf) {
      if (index) {
        _fs.remove(p);
      }
      log_file_unlock(true);
      request->setAttribute(SPIFFS_EDITOR_UPLOAD_ERROR_ATTR, SPIFFS_EDITOR_UPLOAD_WRITE_FAILED);
      return;
    }
    request->setAttribute(SPIFFS_EDITOR_UPLOAD_TOUCHED, "1");
    if (len) {
      size_t written = wf.write(data, len);
      if (written != len) {
        wf.close();
        _fs.remove(p);
        log_file_unlock(true);
        request->setAttribute(SPIFFS_EDITOR_UPLOAD_ERROR_ATTR, SPIFFS_EDITOR_UPLOAD_WRITE_FAILED);
        return;
      }
    }
    wf.close();
    log_file_unlock(true);

    if (final) {
      request->setAttribute(SPIFFS_EDITOR_UPLOAD_COMMITTED, "1");
#ifdef USE_LUA
      if (getValue(filename, '.', 1) == "lua") {
        if (mode_switch_in_progress()) {
          request->setAttribute(SPIFFS_EDITOR_UPLOAD_ERROR_ATTR, SPIFFS_EDITOR_LUA_RELOAD_BUSY);
        } else {
          PendingCommandLockGuard guard;
          if (guard && !mode_switch_in_progress()) {
            pending_lua_reload_flag = true;
          } else {
            request->setAttribute(SPIFFS_EDITOR_UPLOAD_ERROR_ATTR, SPIFFS_EDITOR_LUA_RELOAD_BUSY);
          }
        }
      }
#endif
    }
}


#endif
