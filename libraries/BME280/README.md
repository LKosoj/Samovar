# BME280
Arduino library for communicating with the [BME280](https://www.bosch-sensortec.com/bst/products/all_products/bme280) environmental sensor.

# License
This library is licensed under the GPLV3. Please contact us at [support@bolderflight.com](mailto:support@bolderflight.com) to obtain other licenses.

# Description
The Bosch Sensortec [BME280](https://www.bosch-sensortec.com/bst/products/all_products/bme280) is an integrated environmental sensor, which combines high linearity, high accuracy sensors for pressure, temperature, and humidity in a compact LGA package. The humidity sensor features an extremely fast response time and high accuracy over a wide temperature range. The pressure sensor is an absolute barometric pressure sensor with features exceptionally high accuracy and resolution at very low noise. The integrated temperature sensor has been optimized for very low noise and high resolution. Pressure, temperature, and humidity measurements can be useful for applications involving unmanned vehicles (indicated and true airspeed, altitude, and density altitude), indoor navigation (floor detection), outdoor navigation (altitudes and airspeeds, dead-reckoning, GPS time to first fix improvements) as well as weather monitoring and home automation.

The [BME280](https://www.bosch-sensortec.com/bst/products/all_products/bme280) samples pressure and temperature to 20 bit resolution and humidity to 16 bit resolution. The [BME280](https://www.bosch-sensortec.com/bst/products/all_products/bme280) features programmable oversampling, IIR filtering, and standby time between samples. The BME280 supports both I2C and SPI communication.

# Usage
This library supports both I2C and SPI commmunication with the BME280.

## Installation
Simply clone or download this library into your Arduino/libraries folder.

## Function Description
This library supports both I2C and SPI communication with the BME280. The *BME280* object declaration is overloaded with different declarations for I2C and SPI communication. All other functions remain the same. 

### I2C Object Declaration

**BME280(TwoWire &bus,uint8_t address)**
A BME280 object should be declared, specifying the I2C bus and the BME280 I2C address. The BME280 I2C address will be 0x76 if the SDO pin is grounded or 0x77 if the SDO pin is pulled high. For example, the following code declares a BME280 object called *bme* with a BME280 sensor located on I2C bus 0 with a sensor address of 0x76 (SDO grounded).

```C++
BME280 bme(Wire,0x76);
```

### SPI Object Declaratioon

**BME280(SPIClass &bus,uint8_t csPin)**
A BME280 object should be declared, specifying the SPI bus and the chip select pin used. Multiple BME280 or other SPI objects could be used on the same SPI bus, each with their own chip select pin. The chip select pin can be any available digital pin. For example, the following code declares a BME280 object called *bme* with a BME280 sensor located on SPI bus 0 with chip select pin 10.

```C++
BME280 bme(SPI,10);
```

### Common Setup Functions
The following functions are used to setup the BME280 sensor. These should be called once before data collection, typically this is done in the Arduino *void setup()* function. The *begin* function should always be used. Optionally, the *setPressureOversampling*, *setTemperatureOversampling*, *setHumidityOversampling*, *setIirCoefficient* and *setStandbyTime* functions can be used, following *begin*, to setup the oversampling, IIR filtering, and standby times. The optional *setForcedMode* and *setNormalMode* functions can be used to change the sensor to forced or normal mode. If these optional functions are not used, oversampling, IIR filtering, and standby times are set to default values and normal mode is used, which should be good for a wide range of applications, and are discussed in greater detail below.

**int begin()**
This should be called in your setup function. It initializes communication with the BME280 and sets up the sensor for reading data. This function returns a positive value on a successful initialization and returns a negative value on an unsuccesful initialization. If unsuccessful, please check your wiring or try resetting power to the sensor. The following is an example of setting up the BME280.

```C++
int status;
status = bme.begin();
```

The BME280 features programmable oversampling, IIR filtering, and standby time between samples. By default, these are set to the following values:

| Settings        |                                              |
| ---             | ---                                          |
| Oversampling    | pressure x 16, temperature x 2, humidity x 1 |
| IIR Coefficient | 16                                           |
| Standby Time    | 0.5 ms                                       |

| Performance      |         |
| ---              | ---     |
| Data Output Rate | 25 Hz   |
| Filter Bandwidth | 0.53 Hz |
| Response Time    | 0.88 s  |

Optionally, the *setPressureOversampling*, *setTemperatureOversampling*, *setHumidityOversampling*, *setIirCoefficient* and *setStandbyTime* functions can be used, following *begin*, to change these settings from their default values. For much more information on the settings and performance implications, please refer to the [BME280 datasheet](https://github.com/bolderflight/BME280/blob/master/docs/BME280-Datasheet.pdf).

**(optional) int setPressureOversampling(Sampling pressureSampling)**
This is an optional function to set the pressure oversampling to values other than the default. The following enumerated oversampling settings are supported:

| Oversampling Name | Oversampling Value |
| ---               | ---                |
| SAMPLING_X1       | 1                  |
| SAMPLING_X2       | 2                  |
| SAMPLING_X4       | 4                  |
| SAMPLING_X8       | 8                  |
| SAMPLING_X16      | 16                 |

Below is an example of selecting an oversampling value of 4 for pressure. This function returns a positive value on success and a negative value on failure.

```C++
int status;
status = bme.setPressureOversampling(BME280::SAMPLING_X4);
```

**(optional) int setTemperatureOversampling(Sampling temperatureSampling)**
This is an optional function to set the temperature oversampling to values other than the default. Below is an example of selecting an oversampling value of 2 for temperature. This function returns a positive value on success and a negative value on failure.

```C++
int status;
status = bme.setTemperatureOversampling(BME280::SAMPLING_X2);
```

**(optional) int setHumidityOversampling(Sampling humiditySampling)**
This is an optional function to set the humidity oversampling to values other than the default. Below is an example of selecting an oversampling value of 2 for humidity. This function returns a positive value on success and a negative value on failure.

```C++
int status;
status = bme.setHumidityOversampling(BME280::SAMPLING_X2);
```

**(optional) int setIirCoefficient(Iirc iirCoefficient)**
This is an optional function to set the IIR filter coefficient to a value other than the default. This filter is applied to all measurements. The filter is given by the following equation:

*data_filtered = (data_filtered_old &ast; (filter_coefficient - 1) + data) / filter_coefficient*

The following enumerated filter coefficients are supported:

| IIR Filter Coefficient Name | IIR Filter Coefficient Value | Samples to reach 75% of step response |
| ---                         | ---                          | ---                                   |
| IIRC_OFF                    | 1                            | 1                                     |
| IIRC_X2                     | 2                            | 2                                     |
| IIRC_X4                     | 4                            | 5                                     |
| IIRC_X8                     | 8                            | 11                                    |
| IIRC_X16                    | 16                           | 22                                    |

Below is an example of selecting an IIR filter coefficient of 4. This function returns a positive value on success and a negative value on failure.

```C++
int status;
status = bme.setIirCoefficient(BME280::IIRC_X4);
```

**(optional) int setStandbyTime(Standby standbyTime)**
This is an optional function to set the standby time to a value other than the default. This standby time is applied to all measurements. It is used in normal mode to set the time spent idle between taking measurements. 

The following enumerated standby times are supported:

| Standby Time Name | Standby Time  |
| ---               | ---           |
| STANDBY_0_5_MS    | 0.5 ms        |
| STANDBY_10_MS     | 10 ms         |
| STANDBY_20_MS     | 20 ms         |
| STANDBY_62_5_MS   | 62.5 ms       |
| STANDBY_125_MS    | 125 ms        |
| STANDBY_250_MS    | 250 ms        |
| STANDBY_500_MS    | 500 ms        |
| STANDBY_1000_MS   | 1000 ms       |

Below is an example of selecting a standby time of 10 ms. This function returns a positive value on success and a negative value on failure.

```C++
int status;
status = bme.setStandbyTime(BME280::STANDBY_10_MS);
```

**(optional) int setForcedMode()**
This is an optional function to set the operational mode of the sensor to forced mode. The BME280 has two modes of operation, normal and forced. In normal mode, the sensor takes regular measurements at intervals set by the standby time. When the *readSensor* function is called, detailed below, it simply gets the most recent data values from the sensor. In forced mode, when the *readSensor* function called, the sensor is commanded to collect data, the microcontroller waits for the data to become available, and then gets the data from the sensor. Forced mode is useful for taking measurements at a very low rate (i.e. taking pressure measurements once per minute for a weather station) and for taking measurements that need to be tightly synchronized with the microcontroller. It is recommended not to use the IIR filtering built in to the BME280 in forced mode. The advantage of normal mode is that it reduces the microcontroller workload.

Normal mode is set by default. This function switches the BME280 into forced mode. The data collection process remains the same; however, the time necessary for *readSensor* is significantly greater in forced mode than normal mode. Below is an example of selecting forced mode. This function returns a positive value on success and a negative value on failure.

```C++
int status;
status = bme.setForcedMode();
```

**(optional) int setNormalMode()**
This is an optional function to set the operational mode of the sensor to normal mode. Please see the discussion above, in *setForcedMode*, describing the operational modes of the sensor. Normal mode is set by default. This function would be used after the BME280 is switched to forced mode to set the sensor back to normal mode. Below is an example of selecting normal mode. This function returns a positive value on success and a negative value on failure.

```C++
int status;
status = bme.setNormalMode();
```

### Common Data Collection Functions
The functions below are used to collect data from the BME280 sensor. Data is returned scaled to engineering units. Pressure data is returned in units of Pascal (Pa), temperature data in units of degrees Celsius (C), and humidity in units of percent relative humidity (%RH). *readSensor* is used to read the sensor and store the newest data in a buffer, it should be called every time you would like to retrieve data from the sensor. *getPressure_Pa*, *getTemperature_C*, and *getHumidity_RH* return the pressure, temperature, and humidity values from that buffer.

**int readSensor()** reads the sensor and stores the newest data in a buffer, it should be called every time you would like to retrieve data from the sensor. This function returns a positive value on success and a negative value on failure.

```C++
bme.readSensor();
```

**float getPressure_Pa()** gets the pressure value from the data buffer and returns it in units of Pascal.

```C++
float pressure;
pressure = bme.getPressure_Pa();
```

**float getTemperature_C()** gets the temperature value from the data buffer and returns it in units of degrees Celsius.

```C++
float temperature;
temperature = bme.getTemperature_C();
```

**float getHumidity_RH()** gets the humidity value from the data buffer and returns it in units of percent relative humidity.

```C++
float humidity;
humidity = bme.getHumidity_RH();
```

## Example List
* **Basic_I2C**: demonstrates declaring a *BME280* object, initializing the sensor, and collecting data. I2C is used to communicate with the BME280 sensor.
* **Basic_SPI**: demonstrates declaring a *BME280* object, initializing the sensor, and collecting data. SPI is used to communicate with the BME280 sensor.

# Wiring and Pullups 
Please refer to the [BME280 datasheet](https://github.com/bolderflight/BME280/blob/master/docs/BME280-Datasheet.pdf) and your microcontroller's pinout diagram. This library was developed using the [Adafruit Breakout Board](https://www.adafruit.com/products/2652). This library should work well for other breakout boards or embedded sensors, please refer to your vendor's pinout diagram.

## I2C

The BME280 pins should be connected as:
   * VDD: this should be a 1.7V to 3.6V power source. The Adafruit breakout includes voltage regulation enabling a 3-5V range.
   * GND: ground.
   * VDDIO: digital I/O supply voltage. This should be between 1.2V and 3.6V. The Adafruit breakout board connects VDDIO so this is not broken out to a pin.
   * SDI: connect to SDA.
   * SCK: connect to SCL.
   * SDO: ground to select I2C address 0x76. Pull high to VDD to select I2C address 0x77.
   * CSB: connect to VDD.

4.7 kOhm resistors should be used as pullups on SDA and SCL, these resistors should pullup with a 3.3V source.

## SPI

The BME280 pins should be connected as:
   * VDD: this should be a 1.7V to 3.6V power source. The Adafruit breakout includes voltage regulation enabling a 3-5V range.
   * GND: ground.
   * VDDIO: digital I/O supply voltage. This should be between 1.2V and 3.6V. The Adafruit breakout board connects VDDIO so this is not broken out to a pin.
   * SDI: connect to MOSI.
   * SCK: connect to SCK.
   * SDO: connect to MISO.
   * CSB: connect to chip select pin. Pin 10 was used in the code snippets in this document and the included examples, but any digital I/O pin can be used.
