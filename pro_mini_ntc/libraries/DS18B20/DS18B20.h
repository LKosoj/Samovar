// Digital Thermometer
// Works, but without eeprom copy/read and alarm-setting
// DS18B20: 9-12bit, -55 - +85  degC
// DS18S20: 9   bit, -55 - +85  degC
// DS1822:  9-12bit, -55 - +125 degC
// native bus-features: alarm search

#ifndef ONEWIRE_DS18B20_H
#define ONEWIRE_DS18B20_H

#include "OneWireItem.h"

class DS18B20 : public OneWireItem
{
private:

    void updateCRC(void);

    bool ds18s20_mode;

public:

    uint8_t scratchpad[9];

    static constexpr uint8_t family_code { 0x28 }; // is compatible to ds1822 (0x22) and ds18S20 (0x10)

    DS18B20(uint8_t ID1, uint8_t ID2, uint8_t ID3, uint8_t ID4, uint8_t ID5, uint8_t ID6, uint8_t ID7);

    void duty(OneWireHub * hub) final;

    void setTemperature(float value_degC);  // -55 to +125 degC
    void setTemperature(int8_t value_degC); // -55 to +125 degC
    int  getTemperature() const;

    void    setTemperatureRaw(int16_t value_raw);
    int16_t getTemperatureRaw() const;
    static uint8_t crc8(const uint8_t data[], uint8_t data_size, uint8_t crc_init = 0);
};

#endif
