/*
  BME280.h
  Brian R Taylor
  brian.taylor@bolderflight.com

  Copyright (c) 2017 Bolder Flight Systems

  This program is free software: you can redistribute it and/or modify
  it under the terms of the GNU General Public License as published by
  the Free Software Foundation, either version 3 of the License, or
  (at your option) any later version.

  This program is distributed in the hope that it will be useful,
  but WITHOUT ANY WARRANTY; without even the implied warranty of
  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
  GNU General Public License for more details.

  You should have received a copy of the GNU General Public License
  along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/

#ifndef BME280_h
#define BME280_h

#include "Arduino.h"
#include "Wire.h"  // I2C library
#include "SPI.h"   // SPI library

class BME280{
  public:
    enum Sampling
    {
      SAMPLING_X1   = 0x01,
      SAMPLING_X2   = 0x02,
      SAMPLING_X4   = 0x03,
      SAMPLING_X8   = 0x04,
      SAMPLING_X16  = 0x05
    };
    enum Iirc
    {
      IIRC_OFF = 0x00,
      IIRC_2 = 0x01,
      IIRC_4 = 0x02,
      IIRC_8 = 0x03,
      IIRC_16 = 0x04
    };
    enum Standby
    {
      STANDBY_0_5_MS = 0x00,
      STANDBY_62_5_MS = 0x01,
      STANDBY_125_MS = 0x02,
      STANDBY_250_MS = 0x03,
      STANDBY_500_MS = 0x04,
      STANDBY_1000_MS = 0x05,
      STANDBY_10_MS = 0x06,
      STANDBY_20_MS = 0x07
    };
    enum Mode
    {
      MODE_SLEEP = 0x00,
      MODE_FORCED = 0x01,
      MODE_NORMAL = 0x03
    };
    BME280(TwoWire &bus,uint8_t address);
    BME280(SPIClass &bus,uint8_t csPin);
    int begin();
    int setPressureOversampling(Sampling pressureSampling);
    int setTemperatureOversampling(Sampling temperatureSampling);
    int setHumidityOversampling(Sampling humiditySampling);
    int setIirCoefficient(Iirc iirCoefficient);
    int setStandbyTime(Standby standbyTime);
    int setNormalMode();
    int setForcedMode();
    int readSensor();
    float getPressure_Pa();
    float getTemperature_C();
    float getHumidity_RH();
  private:
    // struct to hold sensor data
    struct Data {
      float Pressure_Pa;
      float Temp_C;
      float Humidity_RH;
    };
    Data _data;
    // temperature output, int32
    int32_t _t_fine;
    // data output, counts
    int32_t _pressureCounts,_temperatureCounts,_humidityCounts;
    // temperature compensation parameters
    int32_t _tvar1, _tvar2, _T;
    // pressure compensation parameters
    int64_t _pvar1, _pvar2, _p;
    // humidity compensation parameters
    int32_t _hv_x1_u32r;
    // track success of interacting with sensor
    int _status;
    // buffer for reading from sensor
    uint8_t _buffer[8];
    // i2c
    uint8_t _address;
    TwoWire *_i2c;
    const uint32_t _i2cRate = 400000; // 400 kHz
    size_t _numBytes; // number of bytes received from I2C
    // spi
    SPIClass *_spi;
    uint8_t _csPin;
    bool _useSPI;
    const uint8_t SPI_READ = 0x80;
    const uint32_t SPI_CLOCK = 10000000; // 10 MHz
    // trimming parameters
    uint16_t _dig_T1;
    int16_t _dig_T2, _dig_T3;
    uint16_t _dig_P1;
    int16_t _dig_P2, _dig_P3, _dig_P4, _dig_P5, _dig_P6, 
      _dig_P7, _dig_P8, _dig_P9;
    uint8_t _dig_H1, _dig_H3;
    int16_t _dig_H2, _dig_H4, _dig_H5;
    int8_t _dig_H6;
    // BME 280 settings
    Sampling _Tsampling = SAMPLING_X2;
    Sampling _Psampling = SAMPLING_X16;
    Sampling _Hsampling = SAMPLING_X1;
    Iirc _iirc = IIRC_16;
    Standby _standby = STANDBY_0_5_MS;
    Mode _mode = MODE_NORMAL;
    // SPI 3 wire interface
    const uint8_t _spi3w_en = 0x00;
    // BME280 registers
    const uint8_t WHO_AM_I_REG = 0xD0;
    const uint8_t RESET_REG = 0xE0;
    const uint8_t SOFT_RESET = 0xB6;
    const uint8_t CTRL_HUM_REG = 0xF2;
    const uint8_t STATUS_REG = 0xF3;
    const uint8_t CTRL_MEAS_REG = 0xF4;
    const uint8_t CONFIG_REG = 0xF5;
    const uint8_t DATA_REG = 0xF7;
    const uint8_t DIG_T1_REG = 0x88;
    const uint8_t DIG_T2_REG = 0x8A;
    const uint8_t DIG_T3_REG = 0x8C;
    const uint8_t DIG_P1_REG = 0x8E;
    const uint8_t DIG_P2_REG = 0x90;
    const uint8_t DIG_P3_REG = 0x92;
    const uint8_t DIG_P4_REG = 0x94;
    const uint8_t DIG_P5_REG = 0x96;
    const uint8_t DIG_P6_REG = 0x98;
    const uint8_t DIG_P7_REG = 0x9A;
    const uint8_t DIG_P8_REG = 0x9C;
    const uint8_t DIG_P9_REG = 0x9E;
    const uint8_t DIG_H1_REG = 0xA1;
    const uint8_t DIG_H2_REG = 0xE1;
    const uint8_t DIG_H3_REG = 0xE3;
    const uint8_t DIG_H4_REG = 0xE4;
    const uint8_t DIG_H5_REG = 0xE5;
    const uint8_t DIG_H6_REG = 0xE7;
    void compensateTemperature(int32_t temperatureCounts, int32_t* t_fine, float* temperature);
    void compensatePressure(int32_t pressureCounts, int32_t t_fine, float* pressure);
    void compensateHumidity(int32_t humidityCounts, int32_t t_fine, float* humidity);
    int getDataCounts(int32_t* pressureCounts, int32_t* temperatureCounts, int32_t* humidityCounts);
    int configureBME280();
    int readTrimmingParameters();
    int writeRegister(uint8_t subAddress, uint8_t data);
    int readRegisters(uint8_t subAddress, uint8_t count, uint8_t* dest);
};

#endif
