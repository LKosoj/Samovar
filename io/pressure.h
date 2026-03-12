#ifndef __SAMOVAR_IO_PRESSURE_H_
#define __SAMOVAR_IO_PRESSURE_H_

#include <Arduino.h>

#include "Samovar.h"
#include "state/globals.h"

#ifdef USE_BME680
#define BME_STRING "BME680"
#include <Adafruit_BME680.h>
inline Adafruit_BME680& pressure_bme_device() {
  static Adafruit_BME680 bme;
  return bme;
}
#endif

#ifdef USE_BMP180
#include <Adafruit_BMP085_U.h>
#define BME_STRING "BMP180"
inline Adafruit_BMP085_Unified& pressure_bme_device() {
  static Adafruit_BMP085_Unified bme;
  return bme;
}
#endif

#ifdef USE_BMP280
#include <Adafruit_BMP280.h>
#define BME_STRING "BMP280"
inline Adafruit_BMP280& pressure_bme_device() {
  static Adafruit_BMP280 bme;
  return bme;
}
#endif

#ifdef USE_BME280
#include <Adafruit_BME280.h>
#define BME_STRING "BME280"
inline Adafruit_BME280& pressure_bme_device() {
  static Adafruit_BME280 bme;
  return bme;
}
#endif

#ifdef USE_PRESSURE_XGZ
#include <XGZP6897D.h>
inline XGZP6897D& pressure_sensor_device() {
  static XGZP6897D pressure_sensor(USE_PRESSURE_XGZ);
  return pressure_sensor;
}
#endif

//***************************************************************************************************************
// считываем параметры с датчика BME680
//***************************************************************************************************************
inline void BME_getvalue(bool fl) {
  (void)fl;
  if (!bmefound) {
    bme_temp = -1;
    bme_pressure = -1;
    return;
  }
  if (xSemaphoreTake(xI2CSemaphore, (TickType_t)(50 / portTICK_RATE_MS)) == pdTRUE) {
#ifdef BME_STRING
    auto& bme = pressure_bme_device();
#endif
#ifdef USE_BME680
    // Tell BME680 to begin measurement.
    if (bme.beginReading() == 0) {
      return;
    }

    if (!bme.endReading()) {
      return;
    }

    bme_temp = bme.temperature;
    bme_pressure = bme.pressure / 100 * 0.75;
    //bme_humidity = bme.humidity;

    //filtered_val += (val - filtered_val) * 0.01;
#endif

#ifdef USE_BMP180
    sensors_event_t event;
    bme.getEvent(&event);
    if (event.pressure) {
      bme_pressure = event.pressure * 0.75;
      float temp;
      bme.getTemperature(&temp);
      bme_temp = temp;
    }
#endif

#ifdef USE_BMP280
    bme_temp = bme.readTemperature();
    bme_pressure = bme.readPressure() / 100 * 0.75;
#endif

#ifdef USE_BME280
    bme_temp = bme.readTemperature();
    bme_pressure = bme.readPressure() / 100 * 0.75;
#endif
    xSemaphoreGive(xI2CSemaphore);
  }
}

//***************************************************************************************************************
// считываем параметры с датчика XGZP6897D или MPX5010D
//***************************************************************************************************************
#if defined(USE_PRESSURE_XGZ) || defined(USE_PRESSURE_MPX)
inline void pressure_sensor_get() {
  if (!use_pressure_sensor) {
    pressure_value = -1;
    return;
  }
  float t;
#ifdef USE_PRESSURE_XGZ
  auto& pressure_sensor = pressure_sensor_device();
  if (xSemaphoreTake(xI2CSemaphore, (TickType_t)(30 / portTICK_RATE_MS)) == pdTRUE) {
    pressure_sensor.readSensor(t, pressure_value);
    xSemaphoreGive(xI2CSemaphore);
  }
  pressure_value = pressure_value / 133.32; //переводим паскали в мм. рт. столба
  pressure_value = (old_pressure_value + pressure_value) / 2;
  old_pressure_value = pressure_value;
#elif defined(USE_PRESSURE_MPX)
  pressure_value = (analogRead(LUA_PIN) - 36.7) / 12;
  pressure_value = (old_pressure_value + pressure_value) / 2;
  old_pressure_value = pressure_value;
#else
  pressure_value = -1;
#endif
}
#endif

inline void pressure_sensor_init() {
#ifdef __SAMOVAR_DEBUG
  Serial.println("Pressure sensor initialization");
#endif
#ifdef BME_STRING
  auto& bme = pressure_bme_device();
  writeString((String)BME_STRING + " init...     ", 3);
  delay(800);

#ifdef USE_BMP280_ALT
  if (!bme.begin(BMP280_ADDRESS_ALT, BMP280_CHIPID)) {
#else
#ifdef USE_BMP180
  if (!bme.begin(BMP085_MODE_STANDARD)) {
#else
  if (!bme.begin()) {
#endif
#endif
    writeString((String)BME_STRING + " not found     ", 3);
#ifdef __SAMOVAR_DEBUG
    Serial.println((String)BME_STRING + " not found");
#endif
    bmefound = false;
    //Serial.println(F("Could not find a valid BME680 sensor, check wiring!"));
  } else {
#ifdef USE_BME680
    // Set up oversampling and filter initialization
    bme.setTemperatureOversampling(BME680_OS_2X);
    bme.setHumidityOversampling(BME680_OS_2X);
    bme.setPressureOversampling(BME680_OS_4X);
    bme.setIIRFilterSize(BME680_FILTER_SIZE_3);
#endif

#ifdef USE_BMP280_1
    bme.setSampling(Adafruit_BMP280::MODE_FORCED,     /* Operating Mode. */
                    Adafruit_BMP280::SAMPLING_X1,     /* Temp. oversampling */
                    Adafruit_BMP280::SAMPLING_X4,     /* Pressure oversampling */
                    Adafruit_BMP280::FILTER_X2,       /* Filtering. */
                    Adafruit_BMP280::STANDBY_MS_500); /* Standby time. */

#endif
#ifdef USE_BME280_1
    bme.setSampling(Adafruit_BME280::MODE_FORCED,
                    Adafruit_BME280::SAMPLING_X1,  // temperature
                    Adafruit_BME280::SAMPLING_X4,  // pressure
                    Adafruit_BME280::SAMPLING_X1,  // humidity
                    Adafruit_BME280::FILTER_OFF);

#endif
  }
#else
  bmefound = false;
#endif

  use_pressure_sensor = false;
#ifdef USE_PRESSURE_XGZ
#ifdef __SAMOVAR_DEBUG
  Serial.println("Init pressure sensor");
#endif
  auto& pressure_sensor = pressure_sensor_device();
  if (!pressure_sensor.begin())  // initialize and check the device
  {
    use_pressure_sensor = false;
#ifdef __SAMOVAR_DEBUG
    Serial.println("Device not responding.");
#endif
  } else use_pressure_sensor = true;

#endif

#ifdef USE_PRESSURE_MPX
  use_pressure_sensor = true;
#endif

#ifdef USE_PRESSURE_1WIRE
  use_pressure_sensor = true;
#endif
}

#endif
