/*
  BME280.cpp
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

#include "Arduino.h"
#include "BME280.h"

/* BME280 object, input the I2C bus and address */
BME280::BME280(TwoWire &bus,uint8_t address){
  _i2c = &bus; // I2C bus
  _address = address; // I2C address
  _useSPI = false; // set to use I2C
}

/* BME280 object, input the SPI bus and chip select pin */
BME280::BME280(SPIClass &bus,uint8_t csPin){
  _spi = &bus; // SPI bus
  _csPin = csPin; // chip select pin
  _useSPI = true; // set to use SPI
}

/* starts communication and sets up the BME280 */
int BME280::begin() {
  if( _useSPI ){ // using SPI for communication
    // setting CS pin to output
    pinMode(_csPin,OUTPUT);
    // setting CS pin low to lock BME280 in SPI mode
    digitalWrite(_csPin,LOW);
    // delay for pin setting to take effect
    delay(1);
    // setting CS pin high
    digitalWrite(_csPin,HIGH);
    // begin SPI communication
    _spi->begin();
  }
  else{ // using I2C for communication
    // starting the I2C bus
    _i2c->begin();
    // setting the I2C clock
    _i2c->setClock(_i2cRate);
  }
  // reset the BME280
  writeRegister(RESET_REG,SOFT_RESET);
  // wait for power up
  delay(10);
  // check the who am i register
  if (readRegisters(WHO_AM_I_REG,1,_buffer) < 0) {
    return -1;
  } else {
    if(_buffer[0]!=0x60) {
      return -2;
    }
  }
  // check that BME280 is not copying trimming parameters
  readRegisters(STATUS_REG,1,_buffer);
  while((_buffer[0] & 0x01)!=0) {
    delay(1);
    readRegisters(STATUS_REG,1,_buffer);
  }
  // read the trimming parameters
  _status = readTrimmingParameters();
  if (_status < 0) {
    return(-3 + _status);
  } 
  // setup sensor to default values
  _status = configureBME280();
  if(_status < 0) {
    return(-4 + _status);
  }
  // successful init, return 1
  return 1;
}

/* sets the pressure oversampling */
int BME280::setPressureOversampling(Sampling pressureSampling) {
  _Psampling = pressureSampling;
  // setup sensor
  if(configureBME280() < 0) {
    return -1;
  }
  // success, return 1
  return 1;  
}

/* sets the temperature oversampling */
int BME280::setTemperatureOversampling(Sampling temperatureSampling) {
  _Tsampling = temperatureSampling;
  // setup sensor
  if(configureBME280() < 0) {
    return -1;
  }
  // success, return 1
  return 1;  
}

/* sets the humidity oversampling */
int BME280::setHumidityOversampling(Sampling humiditySampling) {
  _Hsampling = humiditySampling;
  // setup sensor
  if(configureBME280() < 0) {
    return -1;
  }
  // success, return 1
  return 1;  
}

/* sets the IIR filter coefficient */
int BME280::setIirCoefficient(Iirc iirCoefficient) {
  _iirc = iirCoefficient;
  // setup sensor
  if(configureBME280() < 0) {
    return -1;
  }
  // success, return 1
  return 1; 
}

/* sets the standby time for normal mode */
int BME280::setStandbyTime(Standby standbyTime) {
  _standby = standbyTime;
  // setup sensor
  if(configureBME280() < 0) {
    return -1;
  }
  // success, return 1
  return 1; 
}

/* sets the sensor to normal mode */
int BME280::setNormalMode() {
  _mode = MODE_NORMAL;
  // setup sensor
  if(configureBME280() < 0) {
    return -1;
  }
  // success, return 1
  return 1; 
}

/* sets the sensor to forced mode */
int BME280::setForcedMode() {
  _mode = MODE_FORCED;
  // setup sensor
  if(configureBME280() < 0) {
    return -1;
  }
  // success, return 1
  return 1; 
}

/* gets data from the BME280 */
int BME280::readSensor() {
  if (_mode == MODE_NORMAL) {
    if (getDataCounts(&_pressureCounts, &_temperatureCounts, &_humidityCounts) < 0) {
      return -1;
    } else {
      compensateTemperature(_temperatureCounts,&_t_fine,&_data.Temp_C);
      compensatePressure(_pressureCounts,_t_fine,&_data.Pressure_Pa);
      compensateHumidity(_humidityCounts,_t_fine,&_data.Humidity_RH);
      return 1;
    }
  }
  if (_mode == MODE_FORCED) {
    /* write command to device */
    if( _useSPI ){
      _spi->beginTransaction(SPISettings(SPI_CLOCK, MSBFIRST, SPI_MODE0)); // begin the transaction
      digitalWrite(_csPin,LOW); // select the BME280 chip
      _spi->transfer(CTRL_MEAS_REG & ~SPI_READ); // write the register address
      _spi->transfer(((_Tsampling << 5) | (_Psampling << 3) | _mode )); // write the data
      digitalWrite(_csPin,HIGH); // deselect the BME280 chip
      _spi->endTransaction(); // end the transaction
    }
    else{
      _i2c->beginTransmission(_address); // open the device
      _i2c->write(CTRL_MEAS_REG); // write the register address
      _i2c->write(((_Tsampling << 5) | (_Psampling << 3) | _mode )); // write the data
      _i2c->endTransmission();
    }
    delayMicroseconds(10);
    /* check status to see when data is ready */
    readRegisters(STATUS_REG,1,_buffer);
    while((_buffer[0] & 0x08)!=0x08) {
      readRegisters(STATUS_REG,1,_buffer);
    }
    readRegisters(STATUS_REG,1,_buffer);
    while((_buffer[0] & 0x08)!=0x00) {
      readRegisters(STATUS_REG,1,_buffer);
    }
    /* get the data */
    if (getDataCounts(&_pressureCounts, &_temperatureCounts, &_humidityCounts) < 0) {
      return -1;
    } else {
      compensateTemperature(_temperatureCounts,&_t_fine,&_data.Temp_C);
      compensatePressure(_pressureCounts,_t_fine,&_data.Pressure_Pa);
      compensateHumidity(_humidityCounts,_t_fine,&_data.Humidity_RH);
      return 1;
    }
  }
}

/* returns the pressure value, PA */
float BME280::getPressure_Pa(){
  return _data.Pressure_Pa;
}

/* returns the temperature value, C */
float BME280::getTemperature_C(){
  return _data.Temp_C;
}

/* returns the humidity value, RH */
float BME280::getHumidity_RH(){
  return _data.Humidity_RH;
}

/* compensates the temperature measurement from the BME280 */
void BME280::compensateTemperature(int32_t temperatureCounts, int32_t* t_fine, float* temperature) {
  _tvar1=((((temperatureCounts>>3)-((int32_t)_dig_T1<<1)))*((int32_t)_dig_T2))>>11;
  _tvar2=(((((temperatureCounts>>4)-((int32_t)_dig_T1))*((temperatureCounts>>4)-((int32_t)_dig_T1)))>>12)
    *((int32_t)_dig_T3))>>14;
  *t_fine=_tvar1+_tvar2;
  _T=(*t_fine*5+128)>>8;
  *temperature = ((float)_T)/100.0f;
}

/* compensates the pressure measurement from the BME280 */
void BME280::compensatePressure(int32_t pressureCounts, int32_t t_fine, float* pressure) {
  _pvar1=((int64_t)t_fine)-128000;
  _pvar2=_pvar1*_pvar1*(int64_t)_dig_P6;
  _pvar2=_pvar2+((_pvar1*(int64_t)_dig_P5)<<17);
  _pvar2=_pvar2+(((int64_t)_dig_P4)<<35);
  _pvar1=((_pvar1*_pvar1*(int64_t)_dig_P3)>>8)+((_pvar1*(int64_t)_dig_P2)<<12);
  _pvar1=(((((int64_t)1)<<47)+_pvar1))*((int64_t)_dig_P1)>>33;
  if(_pvar1==0) { 
    *pressure = 0.0f;
  } else {
    _p=1048576-pressureCounts;
    _p=(((_p<<31)-_pvar2)*3125)/_pvar1;
    _pvar1=(((int64_t)_dig_P9)*(_p>>13)*(_p>>13))>>25;
    _pvar2=(((int64_t)_dig_P8)*_p)>>19;
    _p=((_p+_pvar1+_pvar2)>>8)+(((int64_t)_dig_P7)<<4);
    *pressure=(float)((uint32_t)_p)/256.0f;
  }
}

/* compensates the humidity measurement from the BME280 */
void BME280::compensateHumidity(int32_t humidityCounts, int32_t t_fine, float* humidity) {
  _hv_x1_u32r=(t_fine-((int32_t)76800));
  _hv_x1_u32r=(((((humidityCounts<<14)-(((int32_t)_dig_H4)<<20)-(((int32_t)_dig_H5)*_hv_x1_u32r))+
    ((int32_t)16384))>>15)*(((((((_hv_x1_u32r*((int32_t)_dig_H6))>>10)*
    (((_hv_x1_u32r*((int32_t)_dig_H3))>>11)+((int32_t)32768)))>>10)+
    ((int32_t)2097152))*((int32_t)_dig_H2)+8192)>>14));
  _hv_x1_u32r=(_hv_x1_u32r-(((((_hv_x1_u32r>>15)*(_hv_x1_u32r>>15))>>7)*((int32_t)_dig_H1))>>4));
  _hv_x1_u32r=(_hv_x1_u32r < 0 ? 0 : _hv_x1_u32r);
  _hv_x1_u32r=(_hv_x1_u32r > 419430400 ? 419430400 : _hv_x1_u32r);
  *humidity=(float)((uint32_t)(_hv_x1_u32r>>12))/1024.0f;
}

/* returns counts for temperature, pressure, and humidity */
int BME280::getDataCounts(int32_t* pressureCounts, int32_t* temperatureCounts, int32_t* humidityCounts){
  if (readRegisters(DATA_REG,8,_buffer) < 0) {
    return -1;
  } else {
    *pressureCounts = (int32_t)((((uint32_t)_buffer[0]) << 12) | (((uint32_t)_buffer[1]) << 4) | (((uint32_t)_buffer[2]&0xF0) >> 4));
    *temperatureCounts = (int32_t)((((uint32_t)_buffer[3]) << 12) | (((uint32_t)_buffer[4]) << 4) | (((uint32_t)_buffer[5]&0xF0) >> 4));
    *humidityCounts =  (int32_t)((((uint32_t)_buffer[6]) << 8) + ((uint32_t)_buffer[7]));
    return 1;
  }
}

/* configure the BME280 sensor */
int BME280::configureBME280() {
  // set to sleep mode
  if(writeRegister(CTRL_MEAS_REG,MODE_SLEEP) < 0){
      return -1;
  }
  // humidity sensor configuration
  if(writeRegister(CTRL_HUM_REG,_Hsampling) < 0){
      return -2;
  }
  // standby time, iirc, and spi 3 wire configuration
  if(writeRegister(CONFIG_REG,( (_standby << 5) | (_iirc << 3) | _spi3w_en ) ) < 0){
      return -3;
  }
  // pressure, temperature, mode configuration
  if(writeRegister(CTRL_MEAS_REG, ( (_Tsampling << 5) | (_Psampling << 3) | _mode ) ) < 0){
      return -4;
  }
  // successful configuration, return 1
  return 1;
}

/* read the BME280 trimming parameters */
int BME280::readTrimmingParameters() {
  if (readRegisters(DIG_T1_REG,2,_buffer) < 0 ) {
    return -1;
  } else {
    _dig_T1 = (uint16_t) _buffer[1] << 8 | _buffer[0];
  }
  if (readRegisters(DIG_T2_REG,2,_buffer) < 0) {
    return -2;
  } else {
    _dig_T2 = (int16_t) _buffer[1] << 8 | _buffer[0]; 
  }
  if (readRegisters(DIG_T3_REG,2,_buffer) < 0) {
    return -3;
  } else {
    _dig_T3 = (int16_t) _buffer[1] << 8 | _buffer[0]; 
  }
  if (readRegisters(DIG_P1_REG,2,_buffer) < 0) {
    return -4;
  } else {
    _dig_P1 = (uint16_t) _buffer[1] << 8 | _buffer[0];
  }
  if (readRegisters(DIG_P2_REG,2,_buffer) < 0) {
    return -5;
  } else {
    _dig_P2 = (int16_t) _buffer[1] << 8 | _buffer[0]; 
  }
  if (readRegisters(DIG_P3_REG,2,_buffer) < 0) {
    return -6;
  } else {
    _dig_P3 = (int16_t) _buffer[1] << 8 | _buffer[0]; 
  }
  if (readRegisters(DIG_P4_REG,2,_buffer) < 0) {
    return -7;
  } else {
    _dig_P4 = (int16_t) _buffer[1] << 8 | _buffer[0];
  }
  if (readRegisters(DIG_P5_REG,2,_buffer) < 0) {
    return -8;
  } else {
    _dig_P5 = (int16_t) _buffer[1] << 8 | _buffer[0]; 
  }
  if (readRegisters(DIG_P6_REG,2,_buffer) < 0) {
    return -9;
  } else {
    _dig_P6 = (int16_t) _buffer[1] << 8 | _buffer[0];
  }
  if (readRegisters(DIG_P7_REG,2,_buffer) < 0) {
    return -10;
  } else {
    _dig_P7 = (int16_t) _buffer[1] << 8 | _buffer[0];
  }
  if (readRegisters(DIG_P8_REG,2,_buffer) < 0) {
    return -11;
  } else {
    _dig_P8 = (int16_t) _buffer[1] << 8 | _buffer[0];
  }
  if (readRegisters(DIG_P9_REG,2,_buffer) < 0) {
    return -12;
  } else {
    _dig_P9 = (int16_t) _buffer[1] << 8 | _buffer[0]; 
  }
  if (readRegisters(DIG_H1_REG,1,_buffer) < 0) {
    return -13;
  } else {
    _dig_H1 = _buffer[0];
  }
  if (readRegisters(DIG_H2_REG,2,_buffer) < 0) {
    return -14;
  } else {
    _dig_H2 = (int16_t) _buffer[1] << 8 | _buffer[0]; 
  }
  if (readRegisters(DIG_H3_REG,1,_buffer) < 0) {
    return -15;
  } else {
    _dig_H3 = _buffer[0];
  }
  if (readRegisters(DIG_H4_REG,2,_buffer) < 0) {
    return -16;
  } else {
    _dig_H4 = (int16_t) _buffer[0] << 4 | (_buffer[1]&(0x0F));
  }
  if (readRegisters(DIG_H5_REG,2,_buffer) < 0) {
    return -17;
  } else {
    _dig_H5 = (int16_t) _buffer[1] << 4 | _buffer[0] >> 4;
  }
  if (readRegisters(DIG_H6_REG,1,_buffer) < 0) {
    return -18;
  } else {
    _dig_H6 = (int8_t) _buffer[0];
  }
  return 1;
}

/* writes a byte to BME280 register given a register address and data */
int BME280::writeRegister(uint8_t subAddress, uint8_t data){
  /* write data to device */
  if( _useSPI ){
    _spi->beginTransaction(SPISettings(SPI_CLOCK, MSBFIRST, SPI_MODE0)); // begin the transaction
    digitalWrite(_csPin,LOW); // select the BME280 chip
    _spi->transfer(subAddress & ~SPI_READ); // write the register address
    _spi->transfer(data); // write the data
    digitalWrite(_csPin,HIGH); // deselect the BME280 chip
    _spi->endTransaction(); // end the transaction
  }
  else{
    _i2c->beginTransmission(_address); // open the device
    _i2c->write(subAddress); // write the register address
    _i2c->write(data); // write the data
    _i2c->endTransmission();
  }

  delay(10); 

  /* read back the register */
  readRegisters(subAddress,1,_buffer);
  /* check the read back register against the written register */
  if(_buffer[0] == data) {
    return 1;
  }
  else{
    return -1;
  }
}

/* reads registers from BME280 given a starting register address, number of bytes, and a pointer to store data */
int BME280::readRegisters(uint8_t subAddress, uint8_t count, uint8_t* dest){

  if( _useSPI ){
    // begin the transaction
    _spi->beginTransaction(SPISettings(SPI_CLOCK, MSBFIRST, SPI_MODE0));
    digitalWrite(_csPin,LOW); // select the BME280 chip
    _spi->transfer(subAddress | SPI_READ); // specify the starting register address
    for(uint8_t i = 0; i < count; i++){
      dest[i] = _spi->transfer(0x00); // read the data
    }
    digitalWrite(_csPin,HIGH); // deselect the BME280 chip
    _spi->endTransaction(); // end the transaction
    return 1;
  }
  else{
    _i2c->beginTransmission(_address); // open the device
    _i2c->write(subAddress); // specify the starting register address
    _i2c->endTransmission(false);
    _numBytes = _i2c->requestFrom(_address, count); // specify the number of bytes to receive
    if (_numBytes == count) {
      for(uint8_t i = 0; i < count; i++){ 
        dest[i] = _i2c->read();
      }
      return 1;
    } else {
      return -1;
    }
  }
}
