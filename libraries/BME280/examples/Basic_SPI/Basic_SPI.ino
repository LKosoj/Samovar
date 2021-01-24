/*
Basic_SPI.ino
Brian R Taylor
brian.taylor@bolderflight.com
2017-03-30 

Copyright (c) 2017 Bolder Flight Systems

Permission is hereby granted, free of charge, to any person obtaining a copy of this software 
and associated documentation files (the "Software"), to deal in the Software without restriction, 
including without limitation the rights to use, copy, modify, merge, publish, distribute, 
sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is 
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or 
substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING 
BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND 
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, 
DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, 
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
*/

#include "BME280.h"

/* A BME280 object using SPI chip select pin 10 */
BME280 bme(SPI,10);

void setup() {
  // serial to display data
  Serial.begin(115200);
  while(!Serial){}

  // begin communication with
  // BME280 and set to default
  // sampling, iirc, and standby settings
  if (bme.begin() < 0) {
    Serial.println("Error communicating with sensor, check wiring and I2C address");
    while(1){}
  }
}

void loop() {
  // read the sensor
  bme.readSensor();

  // displaying the data
  Serial.print(bme.getPressure_Pa(),6);
  Serial.print("\t");
  Serial.print(bme.getTemperature_C(),2);
  Serial.print("\t");
  Serial.println(bme.getHumidity_RH(),2);
  delay(100);
}
