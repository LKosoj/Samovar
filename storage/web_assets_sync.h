#ifndef __SAMOVAR_STORAGE_WEB_ASSETS_SYNC_H__
#define __SAMOVAR_STORAGE_WEB_ASSETS_SYNC_H__

#include <Arduino.h>
#include <WiFi.h>
#include <SPIFFS.h>
#include <asyncHTTPrequest.h>

#include "Samovar.h"
#include "state/globals.h"
#include "state/runtime_types.h"

// Синхронный HTTP GET-запрос
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
      request.abort();
      return "<ERR>";
    }
    vTaskDelay(25 / portTICK_PERIOD_MS);
  }
  vTaskDelay(150 / portTICK_PERIOD_MS);
  if (!request.send()) {
    Serial.println("HTTP GET send() failed");
    request.abort();
    return "<ERR>";
  }
  vTaskDelay(150 / portTICK_PERIOD_MS);
  // Таймаут для ожидания завершения запроса (readyState == 4)
  startTime = millis();
  while (request.readyState() != 4) {
    if (millis() - startTime > timeoutMs) { // Общий таймаут
      Serial.println("Timeout: request not completed within 4 seconds");
      request.abort();
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
    return request.responseText();
  } else {
    Serial.print(F("responseHTTPcode = "));
    Serial.println(request.responseHTTPcode());
    Serial.println("Content " + url + " download error (2)");
    return "<ERR>";
  }
  return "";
}

// Синхронный HTTP POST-запрос
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
      request.abort();
      return "<ERR>";
    }
    vTaskDelay(25 / portTICK_PERIOD_MS);
  }
  vTaskDelay(150 / portTICK_PERIOD_MS);
  request.setReqHeader("Content-Type", getValue(ContentType, ':', 1).c_str());
  if (!request.send(body)) {
    Serial.println("HTTP POST send() failed");
    request.abort();
    return "<ERR>";
  }

  vTaskDelay(150 / portTICK_PERIOD_MS);
  // Таймаут для ожидания завершения запроса (readyState == 4)
  startTime = millis();
  while (request.readyState() != 4) {
    if (millis() - startTime > timeoutMs) { // Общий таймаут
      Serial.println("Timeout: request not completed within 4 seconds");
      request.abort();
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

// Получение веб-файла по имени и типу
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
  } else {
    if (type == GET_CONTENT) {
      return s;
    } else {
      File wf = SPIFFS.open("/" + fn, FILE_WRITE);
      wf.print(s);
      wf.close();
    }
    Serial.println("Done (L=" + String(s.length()) + ")");
  }

  return "";
}

// Обновление веб-интерфейса
void get_web_interface() {
  String version;
  String local_version;
  String s = "";

  version = get_web_file("version.txt", GET_CONTENT);
  if (version == "<ERR>") return;

  Serial.print(F("WEB interface version = "));
  Serial.println(version);

  File fn = SPIFFS.open("/version.txt", FILE_READ);
  if (fn) {
    local_version = fn.readStringUntil('\n');
    fn.close();
  }
  Serial.print(F("Local interface version = "));
  Serial.println(local_version);
  if (version != local_version) {
    s += get_web_file("wifi.htm", SAVE_FILE_OVERRIDE);
    s += get_web_file("index.htm", SAVE_FILE_OVERRIDE);
    s += get_web_file("Green.png", SAVE_FILE_OVERRIDE);
    s += get_web_file("Red_light.gif", SAVE_FILE_OVERRIDE);
    s += get_web_file("alarm.mp3", SAVE_FILE_OVERRIDE);
    s += get_web_file("favicon.ico", SAVE_FILE_OVERRIDE);
    s += get_web_file("minus.png", SAVE_FILE_OVERRIDE);
    s += get_web_file("plus.png", SAVE_FILE_OVERRIDE);

    s += get_web_file("style.css.gz", SAVE_FILE_OVERRIDE);

    s += get_web_file("beer.htm", SAVE_FILE_OVERRIDE);
    s += get_web_file("bk.htm", SAVE_FILE_OVERRIDE);
    s += get_web_file("nbk.htm", SAVE_FILE_OVERRIDE);
    s += get_web_file("brewxml.htm", SAVE_FILE_OVERRIDE);
    s += get_web_file("calibrate.htm", SAVE_FILE_OVERRIDE);
    s += get_web_file("chart.htm", SAVE_FILE_OVERRIDE);
    s += get_web_file("distiller.htm", SAVE_FILE_OVERRIDE);
    s += get_web_file("edit.htm.gz", SAVE_FILE_OVERRIDE);

    s += get_web_file("program.htm", SAVE_FILE_OVERRIDE);
    s += get_web_file("setup.htm", SAVE_FILE_OVERRIDE);

    s += get_web_file("beer.lua", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("bk.lua", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("nbk.lua", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("dist.lua", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("init.lua", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("rectificat.lua", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("script.lua", SAVE_FILE_IF_NOT_EXIST);

    s += get_web_file("btn_rect_button1.lua", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("btn_rect_button2.lua", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("btn_beer_button1.lua", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("btn_beer_button2.lua", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("btn_dist_button1.lua", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("btn_dist_button2.lua", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("btn_bk_button1.lua", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("btn_bk_button2.lua", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("btn_nbk_button1.lua", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("btn_nbk_button2.lua", SAVE_FILE_IF_NOT_EXIST);

    s += get_web_file("program_fruit.txt", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("program_grain.txt", SAVE_FILE_IF_NOT_EXIST);
    s += get_web_file("program_shugar.txt", SAVE_FILE_IF_NOT_EXIST);

    s += get_web_file("version.txt", SAVE_FILE_OVERRIDE);
  }
}

#endif
