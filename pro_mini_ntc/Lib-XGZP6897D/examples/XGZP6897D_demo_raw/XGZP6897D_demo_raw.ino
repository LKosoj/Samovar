//  Example for XGZP6897D library
//  Simple read of temperature and pressure with a CFSensor I2C sensor
//  such as XGZP6897D
//  Reading raw values if floating point computations must be avoided.
#include <XGZP6897D.h>

/*
   K value for XGZP6897D. It depend on the pressure range of the sensor.
   Table found in the data sheet from CFSensor.com
    https://cfsensor.com/product-category/i2c-sensor/https://cfsensor.com/product-category/i2c-sensor/
  pressure_range (kPa)   K value
  131<P≤260               32
  65<P≤131                64
  32<P≤65                 128
  16<P≤32                 256
  8<P≤16                  512
  4<P≤8                   1024
  2≤P≤4                   2048
  1≤P<2                   4096
  P<1                     8192
  the K value is selected according to the positive pressure value only,
  like -100～100kPa,the K value is 64.
*/

// K value for a XGZP6897D  -1000-1000Pa
#define K 1024 // see table above for the correct value for your sensor, according to the sensitivity.

// create the sensor object, passing the correct K value.
XGZP6897D mysensor(K);
int16_t temperature;
int32_t pressure;

void setup() {
  Serial.begin(9600);
  if (!mysensor.begin())  // initialize and check the device
  {
    Serial.println("Device not responding.");
    while (true) delay(10);
  }
}

void loop()
{
  // read the raw values for temperature and pressure
  mysensor.readRawSensor(temperature, pressure);
  //  we can avoid floating point computations if we don't need precision
  //  and if the size of the sketch is an issue.
  temperature = temperature / 256;
  pressure = pressure / K;
  Serial.print(temperature); Serial.print("C\t ");
  Serial.print(pressure); Serial.print("Pa");
  Serial.println();
  delay(1000);
}
