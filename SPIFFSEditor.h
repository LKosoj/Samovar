#ifndef SPIFFSEditor_H_
#define SPIFFSEditor_H_

#include <FS.h>

String get_edit_script();

#ifdef USE_LUA
void load_lua_script();
String IRAM_ATTR getValue(String data, char separator, int index);
#endif


class SPIFFSEditor: public AsyncWebHandler {
  private:
    fs::FS _fs;
    String _username;
    String _password;
    bool _authenticated;
    uint32_t _startTime;
  public:
#ifdef ESP32
    SPIFFSEditor(const fs::FS& fs, const String& username = String(), const String& password = String());
#else
    SPIFFSEditor(const String& username = String(), const String& password = String(), const fs::FS& fs = SPIFFS);
#endif
    virtual bool canHandle(AsyncWebServerRequest *request) override final;
    virtual void handleRequest(AsyncWebServerRequest *request) override final;
    virtual void handleUpload(AsyncWebServerRequest *request, const String& filename, size_t index, uint8_t *data, size_t len, bool final) override final;
    virtual bool isRequestHandlerTrivial() override final {
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
SPIFFSEditor::SPIFFSEditor(const fs::FS& fs, const String& username, const String& password)
#else
SPIFFSEditor::SPIFFSEditor(const String& username, const String& password, const fs::FS& fs)
#endif
  : _fs(fs)
  , _username(username)
  , _password(password)
  , _authenticated(false)
  , _startTime(0)
{}

bool SPIFFSEditor::canHandle(AsyncWebServerRequest *request) {
  if (request->url().equalsIgnoreCase("/edit")) {
    if (request->method() == HTTP_GET) {
      if (request->hasParam("list"))
        return true;
      if (request->hasParam("edit")) {
        String p = request->arg("edit");
        if (request->arg("edit")[0] != '/') p = "/" + p;
        //        request->_tempFile = _fs.open(request->arg("edit"), "r");
        request->_tempFile = _fs.open(p, "r");
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
        if (request->arg("edit")[0] != '/') p = "/" + p;
        request->_tempFile = _fs.open(p, "r");
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
      request->addInterestingHeader("If-Modified-Since");
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
  if (_username.length() && _password.length() && !request->authenticate(_username.c_str(), _password.c_str()))
    return request->requestAuthentication();

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
        output += String(entry.name());
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
        //        AsyncWebServerResponse *response = request->beginResponse_P(200, "text/html", edit_htm_gz, edit_htm_gz_len);
        AsyncWebServerResponse *response = request->beginResponse(SPIFFS, "/edit.htm", "text/html");
        //		    AsyncWebServerResponse *response = request->beginResponse(200, "text/html", get_edit_script());
        request->send(response);
      }
    }
  } else if (request->method() == HTTP_DELETE) {
    if (request->hasParam("path", true)) {
      String p = request->getParam("path", true)->value();
      if (p[0] != '/') p = "/" + p;
      _fs.remove(p);
      request->send(200, "", "DELETE: " + request->getParam("path", true)->value());
    } else
      request->send(404);
  } else if (request->method() == HTTP_POST) {
    String p = request->getParam("data", true, true)->value();
    if (p[0] != '/') p = "/" + p;

    if (request->hasParam("data", true, true) && _fs.exists(p))
      request->send(200, "", "UPLOADED: " + p);
    else
      request->send(500);
  } else if (request->method() == HTTP_PUT) {
    if (request->hasParam("path", true)) {
      String filename = request->getParam("path", true)->value();
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
    if (!_username.length() || request->authenticate(_username.c_str(), _password.c_str())) {
      _authenticated = true;

      String p = filename;
      if (filename[0] != '/') p = "/" + filename;

      request->_tempFile = _fs.open(p, "w");
      _startTime = millis();
    }
  }
  if (_authenticated && request->_tempFile) {
    if (len) {
      request->_tempFile.write(data, len);
    }
    if (final) {
      request->_tempFile.close();
#ifdef USE_LUA
      if (getValue(filename, '.', 1) == "lua") {
        load_lua_script();
      }
#endif
    }
  }
}


#endif
