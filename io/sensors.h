#ifndef __SAMOVAR_IO_SENSORS_H_
#define __SAMOVAR_IO_SENSORS_H_

#include <Arduino.h>
#include <DallasTemperature.h>

#include "Samovar.h"
#include "state/globals.h"

inline String getDSAddress(DeviceAddress deviceAddress) {
  String dsaddr;
  for (uint8_t j = 0; j < 8; j++) {
    if (deviceAddress[j] < 16) dsaddr += "0";
    dsaddr += String(deviceAddress[j], HEX);
  }
  return dsaddr;
}

inline void printAddress(DeviceAddress deviceAddress) {
  Serial.print(getDSAddress(deviceAddress));
}

inline String get_DSAddressList(String Address) {
  String s = "<option value='-1'>NONE</option>";
  String dsaddr = "";
  for (uint8_t i = 0; i != DScnt; i++) {
    dsaddr = getDSAddress(DSAddr[i]);
    s += "<option value='" + String(i) + "'";
    if (Address == dsaddr) s = s + " " + "selected";
    s = s + ">" + dsaddr + "</option>";
  }
  return s;
}

inline void CopyDSAddress(const uint8_t* DevSAddress, uint8_t* DevTAddress) {
  for (uint8_t dsj = 0; dsj < 8; dsj++) {
    DevTAddress[dsj] = DevSAddress[dsj];
  }
}

//***************************************************************************************************************
// считываем температуры с датчиков DS18B20
//***************************************************************************************************************
inline void DS_getvalue(void) {

  //  SteamSensor.avgTemp += 0.1;
  //  PipeSensor.avgTemp = 50;
  //  WaterSensor.avgTemp += 0.1;
  //  if (WaterSensor.avgTemp > 4) WaterSensor.avgTemp = 25;
  //  if (SteamSensor.avgTemp < 20) SteamSensor.avgTemp = 20;
  //  else {
  //    if (!boil_started)SteamSensor.avgTemp += 1;
  //    else SteamSensor.avgTemp += 0.001;
  //  }
  //  if (TankSensor.avgTemp < 85) TankSensor.avgTemp = 85;
  //  else {
  //    if (!boil_started)TankSensor.avgTemp += 0.2;
  //    else TankSensor.avgTemp += 0.001;
  //  }
  //
  //    SteamSensor.avgTemp += SamSetup.DeltaSteamTemp;
  //    PipeSensor.avgTemp += SamSetup.DeltaPipeTemp;
  //    WaterSensor.avgTemp += SamSetup.DeltaWaterTemp;
  //    TankSensor.avgTemp += SamSetup.DeltaTankTemp;
  //    ACPSensor.avgTemp += SamSetup.DeltaACPTemp;
  //
  //  return;

  float ss, ps, ws, ts, acp;
  float correctT = 0;

  // Считаем корректировку температуры от атмосферного давления.
  // ВАЖНО: применять только если включена настройка "Учитывать атмосферное давление".
  if (SamSetup.UsePreccureCorrect && bme_pressure > 0 && PowerOn) {
    correctT = (760 - bme_pressure) * 0.037;
  }

  ss = correctT + sensors.getTempC(SteamSensor.Sensor);  // считываем температуру с датчика 0
  ps = correctT + sensors.getTempC(PipeSensor.Sensor);   // считываем температуру с датчика 1
  ws = sensors.getTempC(WaterSensor.Sensor);  // считываем температуру с датчика 2
  ts = correctT + sensors.getTempC(TankSensor.Sensor);   // считываем температуру с датчика 3
  acp = sensors.getTempC(ACPSensor.Sensor);   // считываем температуру с датчика 4

#ifdef USE_PRESSURE_1WIRE
  float pv;
  uint8_t p_addr[8] = USE_PRESSURE_1WIRE;
  pv = sensors.getTempC(p_addr);   // считываем давление с расширителя по 1Wire
  if (pv > -120) {
    pressure_value = pv;
    use_pressure_sensor = true;
  } else {
    //pressure_value = -1;
    //use_pressure_sensor = false;
  }

#endif

  //    float randNumber;
  //    randNumber = random(100) / float(500);
  //    if (TankSensor.avgTemp < 87) TankSensor.avgTemp = 89;
  //    if (WaterSensor.avgTemp < 47) WaterSensor.avgTemp = 49;
  //    static float coef = 0;
  //    coef = heater_state ? 0.1 + randNumber : -0.1 - randNumber;
  //    //if (coef > 0.5) coef = 0.5;
  //    //if (coef < -0.5) coef = -0.5;
  //    ts = TankSensor.avgTemp + coef;
  //    ws = WaterSensor.avgTemp + coef;

  sensors.requestTemperatures();

  if (ss > -10) {
    SteamSensor.avgTemp = ss + SamSetup.DeltaSteamTemp;
    SteamSensor.PrevTemp = SteamSensor.avgTemp;
    SteamSensor.ErrCount = 0;
  } else {
    if (SteamSensor.PrevTemp > 0) SteamSensor.ErrCount++;
  }
  if (ps > -10) {
    PipeSensor.avgTemp = ps + SamSetup.DeltaPipeTemp;
    PipeSensor.PrevTemp = PipeSensor.avgTemp;
    PipeSensor.ErrCount = 0;
  } else {
    if (PipeSensor.PrevTemp > 0) PipeSensor.ErrCount++;
  }
  if (ws > -10) {
    WaterSensor.avgTemp = ws + SamSetup.DeltaWaterTemp;
    WaterSensor.PrevTemp = WaterSensor.avgTemp;
    WaterSensor.ErrCount = 0;
  } else {
    if (WaterSensor.PrevTemp > 0) WaterSensor.ErrCount++;
  }
  if (ts > -10) {
    TankSensor.avgTemp = ts + SamSetup.DeltaTankTemp;
    TankSensor.PrevTemp = TankSensor.avgTemp;
    TankSensor.ErrCount = 0;
  } else {
    if (TankSensor.PrevTemp > 0) TankSensor.ErrCount++;
  }
  if (acp > -10) {
    ACPSensor.avgTemp = acp + SamSetup.DeltaACPTemp;
    ACPSensor.PrevTemp = ACPSensor.avgTemp;
    ACPSensor.ErrCount = 0;
  } else {
    if (ACPSensor.PrevTemp > 0) ACPSensor.ErrCount++;
  }

#ifdef __SAMOVAR_DEBUG1
  SteamSensor.avgTemp = SamSetup.DeltaSteamTemp;
  PipeSensor.avgTemp = SamSetup.DeltaPipeTemp;
  WaterSensor.avgTemp = SamSetup.DeltaWaterTemp;
  TankSensor.avgTemp = SamSetup.DeltaTankTemp;
  ACPSensor.avgTemp = SamSetup.DeltaACPTemp;
#endif
}

inline void scan_ds_adress() {
  sensors.begin();  // стартуем датчики температуры

  uint8_t dc = 0;

  while (sensors.getAddress(DSAddr[dc], dc)) {
    sensors.setResolution(DSAddr[dc], 12);  // устанавливаем разрешение для датчика
    dc++;
    if (dc > 5) break;
  }

  DScnt = dc;

  // определяем устройства на шине
#ifdef __SAMOVAR_DEBUG
  Serial.print("Locating DS18B20...");
  Serial.print("Found ");
  Serial.print(DScnt, DEC);
  Serial.println(" devices.");
#endif

#ifdef __SAMOVAR_DEBUG
  Serial.print("1 Sensor Address: ");  // пишем адрес датчика 0
  printAddress(DSAddr[0]);
  Serial.println();
  Serial.print("2 Sensor Address: ");  // пишем адрес датчика 1
  printAddress(DSAddr[1]);
  Serial.println();
  Serial.print("3 Sensor Address: ");  // пишем адрес датчика 2
  printAddress(DSAddr[2]);
  Serial.println();
  Serial.print("4 Sensor Address: ");  // пишем адрес датчика 3
  printAddress(DSAddr[3]);
  Serial.println();
  Serial.print("5 Sensor Address: ");  // пишем адрес датчика 4
  printAddress(DSAddr[4]);
  Serial.println();
  Serial.print("6 Sensor Address: ");  // пишем адрес датчика 5
  printAddress(DSAddr[5]);
  Serial.println();
#endif

  sensors.setWaitForConversion(false);  // работаем в асинхронном режиме
  sensors.requestTemperatures();
  //delay(750);

#ifdef __SAMOVAR_DEBUG
  Serial.print("1 Sensor Resolution: ");  // пишем разрешение для датчика 0
  Serial.print(sensors.getResolution(DSAddr[0]), DEC);
  Serial.println();
  Serial.print("2 Sensor Resolution: ");  // пишем разрешение для датчика 1
  Serial.print(sensors.getResolution(DSAddr[1]), DEC);
  Serial.println();
  Serial.print("3 Sensor Resolution: ");  // пишем разрешение для датчика 2
  Serial.print(sensors.getResolution(DSAddr[2]), DEC);
  Serial.println();
  Serial.print("4 Sensor Resolution: ");  // пишем разрешение для датчика 3
  Serial.print(sensors.getResolution(DSAddr[3]), DEC);
  Serial.println();
  Serial.print("5 Sensor Resolution: ");  // пишем разрешение для датчика 3
  Serial.print(sensors.getResolution(DSAddr[4]), DEC);
  Serial.println();
#endif
}

#endif
