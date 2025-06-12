# XGZP6897D
Arduino basic library for **XGZP6897D** I2C differential pressure sensor from CFSensor  

This library was developed mainly for the **XGZP6897D** differential pressure sensor but **should be compatible with a wide range of I2C digital pressure sensors from CFSensor.com** (see list of I2C sensor [here](https://cfsensor.com/product-category/i2c-sensor/)) including:  
  
XGZP6899D  
XGZP6847D   
XGZP6857D  
XGZP6859D  
XGZP6869D  
XGZP6877D  
XGZP6887D  
XGZP6858D  

Some sensor are differential (Positive&Vacuum) , some absolute.

These entire sensors share the same I2C address (0x6D), the same registers addresses and the same computation mode for pressure and temperature.  
The computation of the pressure requires a parameter, named K in the documentation that depends on the specific sensor model and its pressure range. Its value is found in the datasheet of the sensor.  
For example, in the datasheet for the **XGZP6897D** we found the following table:  
|Pressure range(kpa)|K(value)|
|---|---|
|131<P≤260 |32|
|65<P≤131| 64|
|32<P≤65 |128|
|16<P≤32 |256|
|8<P≤16| 512|
|4<P≤8 |1024|
|2≤P≤4 |2048|
|1≤P<2 |4096|
|P<1| 8192|  

The K value is selected according to the positive pressure value only, like -100～100kPa,the K value is 64.

## Installation
Easy install from the Arduino library manager or manually.

[See Arduino documentation here](https://docs.arduino.cc/software/ide-v1/tutorials/installing-libraries)

## Interface
See the examples in the examples directory  
`#include <XGZP6897D.h>` 

`XGZP6897D(uint16_t K);`  
Constructor. K is specific to the sensor we use (see above description).  

`bool begin();`  
Initialization. Return true: device responding.  false:device not responding.  

`void readSensor(float &temperature, float &pressure);`   
Return both temperature in degrees Celsius and pressure in Pa (the datasheet is not clear on how to read only one value….)  
Temperature and pressure may be negative.

`void readRawSensor(int16_t &rawTemperature, int32_t &rawPressure);`   
 Return raw integer values for temperature and pressure.  
 The raw integer value of temperature must be devided by 256 to convert in degree Celsius.   
 The raw integer value of pressure must be divided by the K factor to convert in Pa.   

## Platforms
This library has been tested on Arduino UNO, Arduino ProMini, ESP32 and ESP8266.

## Version history
- 1.0.0	Initial release

## Contact
Use the [issues link](XGZP6897D/issues) in this Github repository.

