#ifndef __SAMOVAR_H_
#define __SAMOVAR_H_

#define CONFIG_ASYNC_TCP_RUNNING_CORE 1      // force async_tcp task to be on same core as Arduino app (default is any core)
#define CONFIG_ASYNC_TCP_STACK_SIZE 4096     // reduce the stack size (default is 16K)

#ifndef ESP32
#error This code is designed to run on ESP32 platform, not Arduino nor ESP8266! Please check your Tools->Board setting.
#endif

#define SAMOVAR_VERSION F("6.27")

//#define __SAMOVAR_DEBUG

// Дефолтное значение для I2C шагов/мл (внешний насос)
#ifndef I2C_STEPPER_STEP_ML_DEFAULT
#define I2C_STEPPER_STEP_ML_DEFAULT 16000
#endif

#include <OneWire.h>
#include <DallasTemperature.h>
#include <ESPAsyncWebServer.h>
#include <ESP32Servo.h>
#include <PID_v1.h>
#include <PID_AutoTune_v0.h>
#include <iarduino_I2C_connect.h>
#include <GyverEncoder.h>
#include <GyverButton.h>
#include <ESPmDNS.h>
#include <LiquidMenu.h>

//определение поддерживаемых плат
#define DEVKIT 1
#define LILYGO 2
#define ESP32S3 3


#define BitIsSet(reg, bit) ((reg & (1<<bit)) != 0)

#ifdef __SAMOVAR_DEBUG
#ifndef USE_WEB_SERIAL
//#define USE_WEB_SERIAL                      //использовать библиотеку WebSerial для отладки
#endif
#endif

#define WRITE_PROGNUM_IN_LOG                 // писать в лог номер текущей строки программы

#include "Samovar_ini.h"

#include "user_config_override.h"

#ifndef USE_BODY_TEMP_AUTOSET
#define USE_BODY_TEMP_AUTOSET
#endif

#if ( defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3) )
//https://esp32.jgarrettcorbin.com/
//Если используется SDK >= 3 версии, отключаем использование OTA
#undef USE_UPDATE_OTA
#endif

#include "Samovar_pin.h"


#ifdef USE_PRESSURE_1WIRE
#undef USE_PRESSURE_XGZ
#endif

#ifdef USE_PRESSURE_MPX
#undef USE_PRESSURE_XGZ
#undef USE_PRESSURE_1WIRE
#endif

#ifndef SAM_NO_BEER_PRG
#define SAM_BEER_PRG
#endif

#ifdef USE_WEB_SERIAL
#include <WebSerial.h>
#endif

#ifdef USE_WATER_PUMP
#undef USE_WATER_VALVE
#endif

#ifdef BLYNK_SAMOVAR_TOOL
#ifndef SAMOVAR_USE_BLYNK
#define SAMOVAR_USE_BLYNK
#endif
#endif

#ifdef SAMOVAR_USE_SEM_AVR
#ifndef SAMOVAR_USE_RMVK
#define SAMOVAR_USE_RMVK
#endif
#endif

#ifndef USE_HEAD_LEVEL_SENSOR
#ifndef IGNORE_HEAD_LEVEL_SENSOR_SETTING
#define IGNORE_HEAD_LEVEL_SENSOR_SETTING
#endif
#endif

#ifdef USE_BMP280_ALT
#undef USE_BMP180
#undef USE_BME280
#undef USE_BME680
#ifndef USE_BMP280
#define USE_BMP280
#endif
#endif

#define PWR_FACTOR 1

#ifdef SAMOVAR_USE_RMVK
#undef PWR_FACTOR
#define PWR_FACTOR 2
#ifndef SAMOVAR_USE_POWER
#define SAMOVAR_USE_POWER
#endif
#endif

#ifdef __cplusplus
extern "C" {
#endif

uint8_t temprature_sens_read();

#ifdef __cplusplus
}
#endif

uint8_t temprature_sens_read();

//#define __SAMOVAR_NOT_USE_WDT

//--------------------------------------------------------------------------------------------------------------
//--------------------------------------------------------------------------------------------------------------
//--------------------------------------------------------------------------------------------------------------
//--------------------------------------------------------------------------------------------------------------

//**************************************************************************************************************
// Режимы работы регулятора напряжения
#define POWER_WORK_MODE F("0")
#define POWER_SPEED_MODE F("1")
#define POWER_SLEEP_MODE F("2")
#define POWER_ERROR_MODE F("3")
//**************************************************************************************************************

#ifdef SAMOVAR_USE_SEM_AVR
#undef PWR_FACTOR
#define PWR_FACTOR 20
#define PWR_MSG F("Мощность")
#define PWR_TYPE F("P")
#define PWR_SIGN F("Вт")

#ifndef RMVK_DEFAULT_READ_TIMEOUT
#define RMVK_DEFAULT_READ_TIMEOUT 1100 // Таймаут по умолчанию (мс)
#endif
#ifndef RMVK_READ_DELAY
#define RMVK_READ_DELAY 300 // Задержка между запросами (мс)
#endif

#else
#ifdef SAMOVAR_USE_POWER
#define PWR_MSG F("Напряжение")
#define PWR_TYPE F("V")
#define PWR_SIGN F("В")
#else
#define PWR_MSG ""
#define PWR_TYPE ""
#endif
#endif

#ifndef SAMOVAR_USE_POWER_START_TIME
#define SAMOVAR_USE_POWER_START_TIME 2000
#endif

#ifndef LUA_BEER
#define LUA_BEER ""
#endif

#ifndef LUA_DIST
#define LUA_DIST ""
#endif

#ifndef LUA_BK
#define LUA_BK ""
#endif

#ifndef LUA_NBK
#define LUA_NBK ""
#endif

#ifndef LUA_RECT
#define LUA_RECT ""
#endif

#define USE_LittleFS

// Флаг USE_CRASH_HANDLER теперь берется из user_config_override.h

#ifdef USE_LittleFS
//#pragma message ("USE LITTLEFS")
#ifdef ESP_ARDUINO_VERSION
#include <LittleFS.h>
#define SPIFFS LittleFS
#else
#include <LITTLEFS.h>
#define SPIFFS LITTLEFS
#endif
#else
#pragma message ("USE SPIFFS")
#include <SPIFFS.h>
#endif

#include <FS.h>
#include <errno.h>
#include <stdlib.h>

#include "state/config_types.h"
#include "state/runtime_types.h"
#include "src/core/state/mode_codes.h"
#include "src/core/state/status_codes.h"
#include "support/safe_parse.h"

void writeString(String Str, uint8_t num);
void WriteConsoleLog(String StringLogMsg);

// Ограничение длины входной строки программ перед парсингом
#ifndef MAX_PROGRAM_INPUT_LEN
#define MAX_PROGRAM_INPUT_LEN 1024
#endif

//**************************************************************************************************************
// Описание переменных
//**************************************************************************************************************

#define DRIVER_STEP_TIME 4

#ifdef USE_STEPPER_ACCELERATION
#define GS_FAST_PROFILE 10
#else
#define GS_NO_ACCEL
#endif

#include <GyverStepper2.h>

#ifdef COLUMN_WETTING
#ifndef USE_HEAD_LEVEL_SENSOR
#undef COLUMN_WETTING
#endif
#endif

#ifdef USE_EXPANDER
#include <PCF8575.h>
#endif

#ifdef USE_ANALOG_EXPANDER
#include "PCF8591.h"
#endif

#ifdef WHLS_HIGH_PULL
#ifndef USE_HEAD_LEVEL_SENSOR
#define USE_HEAD_LEVEL_SENSOR
#endif
#endif

#ifdef SAMOVAR_USE_POWER
#define TIME_C 4                                                // Время ожидания в минутах для программы режима предзахлеба
#endif

#include "state/globals.h"

#ifdef USE_WEB_SERIAL
//WebSerialClass WebSerial;
#endif

// Глобальная функция остановки процесса
void stop_process(String reason);

#ifdef USE_MQTT
void MqttSendMsg(const String &Str, const char *chart, int version = 3);
#endif

#endif
