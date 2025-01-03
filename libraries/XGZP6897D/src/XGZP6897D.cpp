/*
  XGZP6897D.cpp - Library for using a familly of pressure sensors from CFSensor.com
  I2C sensors
  Created by Francis Sourbier
  GNU GENERAL PUBLIC LICENSE Version 3, 29 June 2007
  This library is free software;
  Released into the public domain
*/
#include <XGZP6897D.h>
#include <Wire.h>

//  Descriptor. K depends on the exact model of the sensor. See datasheet and documentation
XGZP6897D::XGZP6897D(uint16_t K, TwoWire* theWire)
{
  _K = K;
  _I2C_address = I2C_device_address;
  _Wire = theWire;
}
//
//
bool XGZP6897D::begin()
{
  _Wire->begin();


  // A basic scanner, see if it ACK's
  _Wire->beginTransmission(_I2C_address);
  if (_Wire->endTransmission() == 0) {
    return true;  // Ok device is responding
  }
  return false; // device not responding
}
//  Return raw integer values for temperature and pressure.
//  The raw integer of temperature must be devided by 256 to convert in degree Celsius
//  The raw integer of pressure must be devided by the K factor to convert in Pa
bool XGZP6897D::readRawSensor(int16_t &rawTemperature, int32_t &rawPressure)
{
  int32_t pressure_adc;
  int16_t  temperature_adc ;
  uint8_t pressure_H, pressure_M, pressure_L, temperature_H, temperature_L;
  uint8_t CMD_reg;
  unsigned long endConversion;
  // start conversion
  _Wire->beginTransmission(_I2C_address);
  _Wire->write(0x30);
  _Wire->write(0x0A);   //start combined conversion pressure and temperature
  if ( _Wire->endTransmission() != 0) return false;
  // wait until the end of conversion (Sco bit in CMD_reg. bit 3)
  endConversion = millis() + 20 ; //  conversion should take 20ms at most...
  do {
    if (millis() > endConversion) return false;
    _Wire->beginTransmission(_I2C_address);
    _Wire->write(0x30);                       //send 0x30 CMD register address
    if (_Wire->endTransmission() != 0) return false;
    if (_Wire->requestFrom(_I2C_address, byte(1)) != 1) return false;;
    CMD_reg = _Wire->read();                //read 0x30 register value
  } while ((CMD_reg & 0x08) > 0);        //loop while bit 3 of 0x30 register copy is 1
  // read temperature and pressure
  _Wire->beginTransmission(_I2C_address);
  _Wire->write(0x06);                        //send pressure high byte register address
  if (_Wire->endTransmission() != 0) return false;
  if (_Wire->requestFrom(_I2C_address, byte(5)) != 5) return false; // read 3 bytes for pressure and 2 for temperature
  pressure_H = _Wire->read();
  pressure_M = _Wire->read();
  pressure_L = _Wire->read();
  temperature_H = _Wire->read();
  temperature_L = _Wire->read();
  pressure_adc = ((uint32_t)pressure_H << 8) + (uint32_t) pressure_M;
  pressure_adc = (pressure_adc << 8) + (uint32_t) pressure_L;
  temperature_adc = ((uint16_t)temperature_H << 8) + (uint16_t) temperature_L;
  // pressure is a signed2 complement style value, on 24bits.
  // need to extend the bit sign on the full 32bits.
  rawPressure = ((pressure_adc << 8) >> 8);
  rawTemperature = temperature_adc;
#ifdef debugFS
  Serial.print(String(pressure_H, HEX));
  Serial.print("," + String(pressure_M, HEX));
  Serial.print("," + String(pressure_L, HEX));
  Serial.print(":" + String(pressure_adc, HEX));
  Serial.print(" – " + String(temperature_H, HEX));
  Serial.print("," + String(temperature_L, HEX));
  Serial.print(":" + String(temperature_adc, HEX));
  Serial.println();
#endif
  return true;
}
//  Read temperature (degree Celsius), and pressure (PA)
//  Return float values
bool XGZP6897D::readSensor(float &temperature, float &pressure)
{
  int32_t rawPressure;
  int16_t  rawTemperature ;
  if (!readRawSensor(rawTemperature, rawPressure)) return false; // timeout ??
  pressure = rawPressure / _K;
  temperature = float(rawTemperature) / 256;
#ifdef debugFS
  Serial.print(" - " + String(temperature) + ":" + String(pressure));
  Serial.println();
#endif
  return true;
}
