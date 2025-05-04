/*
  XGZP6897D.h - Library for using a familly of pressure sensors from CFSensor.com
  I2C sensors
  Created by Francis Sourbier
  GNU GENERAL PUBLIC LICENSE Version 3, 29 June 2007
  This library is free software;
  Released into the public domain
*/
#ifndef XGZP6897D_H
#define XGZP6897D_H
#include <Arduino.h>
//#define debugFS
#define I2C_device_address 0x6D
class XGZP6897D
{
  public:
    XGZP6897D(uint16_t K); // K depends on sensor. See datasheet.
    bool begin();  // true: device responding.  false:device not responding
    // readSensor:
    //  Read temperature (degree Celsius), and pressure (PA)
    //  Return float values
    void readSensor(float &temperature, float &pressure);
    //  readRawSensor:
    //  Return raw integer values for temperature and pressure.
    //  The raw integer value of temperature must be devided by 256 to convert in degree Celsius.
    //  The raw integer value of pressure must be devided by the K factor to convert in Pa.
    void readRawSensor(int16_t &rawTemperature, int32_t &rawPressure);
  private:
    float _K;
    uint8_t _I2C_address;
};

#endif
