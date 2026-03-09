#ifndef UI_WEB_PAGE_ASSETS_H
#define UI_WEB_PAGE_ASSETS_H

#include <Arduino.h>
#include <ESPAsyncWebServer.h>
#include "Samovar.h"
#include "wifi_htm_gz.h"

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

// Функция для отправки wifi.htm из памяти (gzip архив)
void handleWifiHtmFromMemory(AsyncWebServerRequest *request) {
  AsyncWebServerResponse *response = request->beginResponse(200, "text/html", wifi_htm_gz_data, wifi_htm_gz_data_len);
  response->addHeader("Content-Encoding", "gzip");
  response->addHeader("Cache-Control", "max-age=1");
  request->send(response);
}

#endif // UI_WEB_PAGE_ASSETS_H
