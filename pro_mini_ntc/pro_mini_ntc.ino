#include <Arduino.h>
#include <Wire.h>
#include <avr/wdt.h>
#include "OneWireHub.h"
#include "DS18B20.h"
#include <ASOLED.h> //! библиотека дисплея
#include <XGZP6897D.h>  //! библиотека датчика давления

/* С какой характеристикой В(25/100) подключены NTC-термисторы */
//#define B4300    /* B(25/100) = 4300 */
//#define B3988    /* B(25/100) = 3988 */
#define B3950    /* B(25/100) = 3950 */
//#define B3625    /* B(25/100) = 3625 */
//#define B3530    /* B(25/100) = 3530 */
//#define B3492    /* B(25/100) = 3492 */
/* NTC-термисторы c характеристикой B(25/100) = 3380, если все остальные закомментированы */

#define ADS_I2CADDR_1     (0x48)
#define ADS_I2CADDR_2     (0x49)
#define ADS1115_REG_CONFIG_MUX_SINGLE_0     (0x4000)
#define ADS1115_REG_CONFIG_MUX_SINGLE_1     (0x5000)
#define ADS1115_REG_CONFIG_MUX_SINGLE_2     (0x6000)
#define ADS1115_REG_CONFIG_MUX_SINGLE_3     (0x7000)
#define ADS1115_REG_POINTER_CONVERT         (0x00)
#define ADS1115_REG_POINTER_CONFIG          (0x01)
#define ASOled LD // ! Заюзаем уже созданный в библиотеке дисплея объект LD
// Включаем отладку, только если чтото пошло не так :(
//#define SERIAL_DEBUG
//#define SERIAL_TEST_NTC

XGZP6897D mysensor(128); //Объект датчика давления с делителем К=128 //! делитель зависит от диапазона датчика

float pressure, temperature; // переменные для него //!
static char outstr[8]; //строка для вывода цифр на экран //!
float DeltaPress = 0.47; // ! Поправка для датчика давления, равна его среднему значению при отсутствии давления и нулевой поправке
bool W1_Connect_Enable = false;
uint8_t ntcEn[8];
uint32_t millisConvert;
constexpr uint8_t pin_led      { 13 };
constexpr uint8_t pin_onewire  { 2 };
auto hub = OneWireHub(pin_onewire);
auto ds18bP = DS18B20(0x22, 0x22, 0x22, 0x22, 0x22, 0x22, 0x22); // ! Датчик давления
auto ds18b1 = DS18B20(0x28, 0x10, 0x55, 0x44, 0x33, 0x22, 0x01); // 0xD8
auto ds18b2 = DS18B20(0x28, 0x20, 0x55, 0x44, 0x33, 0x22, 0x02); // 0xD7
auto ds18b3 = DS18B20(0x28, 0x30, 0x55, 0x44, 0x33, 0x22, 0x03); // 0xD2
auto ds18b4 = DS18B20(0x28, 0x40, 0x55, 0x44, 0x33, 0x22, 0x04); // 0xC9
auto ds18b5 = DS18B20(0x28, 0x50, 0x55, 0x44, 0x33, 0x22, 0x05); // 0xCC
auto ds18b6 = DS18B20(0x28, 0x60, 0x55, 0x44, 0x33, 0x22, 0x06); // 0xC3
auto ds18b7 = DS18B20(0x28, 0x70, 0x55, 0x44, 0x33, 0x22, 0x07); // 0xC6
auto ds18b8 = DS18B20(0x28, 0x80, 0x55, 0x44, 0x33, 0x22, 0x08); // 0xF5

static void writeRegister(uint8_t i2cAddress, uint8_t reg, uint16_t value) {
  Wire.beginTransmission(i2cAddress);
  Wire.write((uint8_t)reg);
  Wire.write((uint8_t)(value>>8));
  Wire.write((uint8_t)(value & 0xFF));
  Wire.endTransmission();
}
static uint16_t readRegister(uint8_t i2cAddress, uint8_t reg) {
  Wire.beginTransmission(i2cAddress);
  Wire.write((uint8_t)reg);
  Wire.endTransmission();
  Wire.requestFrom(i2cAddress, (uint8_t)2);
  return ((Wire.read() << 8) | Wire.read());  
}
uint16_t readADS(uint8_t channel, uint8_t cnt) {
  if (channel > 7 || cnt == 0) return 0;
  uint8_t ads_i2cAddress = 0;
  uint16_t config = 0b1000010111100011;
  switch (channel) {
    case (0): config |= ADS1115_REG_CONFIG_MUX_SINGLE_0; ads_i2cAddress = ADS_I2CADDR_1; break;
    case (1): config |= ADS1115_REG_CONFIG_MUX_SINGLE_1; ads_i2cAddress = ADS_I2CADDR_1; break;
    case (2): config |= ADS1115_REG_CONFIG_MUX_SINGLE_2; ads_i2cAddress = ADS_I2CADDR_1; break;
    case (3): config |= ADS1115_REG_CONFIG_MUX_SINGLE_3; ads_i2cAddress = ADS_I2CADDR_1; break;
    case (4): config |= ADS1115_REG_CONFIG_MUX_SINGLE_0; ads_i2cAddress = ADS_I2CADDR_2; break;
    case (5): config |= ADS1115_REG_CONFIG_MUX_SINGLE_1; ads_i2cAddress = ADS_I2CADDR_2; break;
    case (6): config |= ADS1115_REG_CONFIG_MUX_SINGLE_2; ads_i2cAddress = ADS_I2CADDR_2; break;
    case (7): config |= ADS1115_REG_CONFIG_MUX_SINGLE_3; ads_i2cAddress = ADS_I2CADDR_2; break;
  }
  uint32_t summ = 0;
  for (uint8_t i=0; i<cnt; i++) {
    writeRegister(ads_i2cAddress, ADS1115_REG_POINTER_CONFIG, config); // Write config register to the ADC
    delayMicroseconds(1200);
    summ += readRegister(ads_i2cAddress, ADS1115_REG_POINTER_CONVERT);
  }
  return (uint16_t)(summ / cnt);
}

int32_t computeTemp_15bit(uint16_t adcRez) {
/* 
 *  Таблицы суммарного значения АЦП в зависимости от температуры. От большего значения к меньшему
 *  Для построения таблицы использованы следующие парамертры:
 *    R1(T1): 10кОм(25°С)
 *    Схема включения: Ra подключен к U0, Rb параллельно R1(T1)
 *    Ra/Rb: 6.2кОм/10кОм
 *    Напряжения U0/Uref: 3.3В/2.048В
 */
#if defined (B4300)
/*         B25/100: 4300         */
  uint16_t m_adc[151] = {31924, 31877, 31827, 31774, 31719, 31659, 31597, 31531, 31461, 31388, 31310, 31229, 31143, 31052, 30958, 30858, 30754, 30644, 30530, 30410, 30284, 30153, 30016, 29873,
                         29724, 29569, 29408, 29241, 29067, 28886, 28699, 28505, 28304, 28097, 27883, 27662, 27434, 27199, 26958, 26710, 26455, 26194, 25926, 25652, 25372, 25086, 24794, 24496,
                         24193, 23885, 23571, 23254, 22931, 22605, 22274, 21941, 21604, 21264, 20921, 20576, 20230, 19881, 19532, 19182, 18831, 18480, 18129, 17779, 17430, 17082, 16735, 16390,
                         16047, 15706, 15368, 15033, 14702, 14373, 14048, 13727, 13410, 13097, 12788, 12484, 12184, 11889, 11599, 11313, 11033, 10758, 10488, 10223, 9963, 9709, 9460, 9216,
                         8977, 8743, 8515, 8292, 8074, 7861, 7653, 7450, 7252, 7059, 6871, 6687, 6508, 6334, 6164, 5999, 5838, 5681, 5529, 5380, 5236, 5095, 4958, 4825, 4696, 4570, 4448, 4329,
                         4214, 4101, 3992, 3886, 3783, 3683, 3585, 3491, 3399, 3310, 3223, 3139, 3057, 2977, 2900, 2825, 2752, 2681, 2612, 2545, 2480, 2417, 2356, 2296, 2238, 2182, 2127};
#elif defined (B3988)
/*         B25/100: 3988         */
  uint16_t m_adc[151] = {31771, 31718, 31662, 31603, 31541, 31475, 31406, 31334, 31258, 31178, 31095, 31007, 30916, 30820, 30720, 30615, 30505, 30391, 30273, 30149, 30020, 29886, 29747, 29602,
                         29452, 29296, 29135, 28968, 28796, 28617, 28433, 28243, 28048, 27846, 27638, 27425, 27206, 26981, 26750, 26514, 26272, 26024, 25772, 25513, 25250, 24982, 24709, 24431,
                         24149, 23862, 23571, 23277, 22979, 22677, 22372, 22064, 21753, 21440, 21125, 20808, 20489, 20169, 19848, 19525, 19203, 18880, 18557, 18234, 17912, 17590, 17270, 16951,
                         16633, 16317, 16003, 15691, 15381, 15074, 14770, 14469, 14171, 13876, 13584, 13296, 13011, 12731, 12454, 12181, 11912, 11648, 11387, 11131, 10879, 10631, 10388, 10149,
                         9915, 9685, 9459, 9238, 9021, 8808, 8600, 8396, 8197, 8002, 7811, 7624, 7442, 7263, 7089, 6918, 6752, 6589, 6430, 6275, 6124, 5976, 5832, 5691, 5554, 5420, 5289, 5162,
                         5038, 4917, 4798, 4683, 4571, 4462, 4355, 4251, 4150, 4051, 3955, 3862, 3770, 3681, 3595, 3510, 3428, 3348, 3270, 3194, 3120, 3047, 2977, 2908, 2842, 2777, 2713};
#elif defined (B3950)
/*         B25/100: 3950         */
  uint16_t m_adc[151] = {31751, 31697, 31640, 31580, 31517, 31450, 31381, 31308, 31231, 31151, 31066, 30978, 30886, 30789, 30688, 30583, 30473, 30359, 30239, 30115, 29986, 29852, 29712, 29567,
                         29417, 29262, 29101, 28934, 28762, 28584, 28400, 28211, 28015, 27815, 27608, 27396, 27178, 26954, 26724, 26490, 26249, 26004, 25753, 25496, 25235, 24969, 24698, 24423,
                         24143, 23859, 23571, 23280, 22984, 22686, 22384, 22079, 21772, 21462, 21150, 20836, 20521, 20204, 19886, 19567, 19248, 18928, 18609, 18289, 17970, 17652, 17335, 17019,
                         16704, 16391, 16080, 15771, 15464, 15160, 14859, 14560, 14264, 13971, 13682, 13396, 13114, 12835, 12560, 12289, 12021, 11758, 11499, 11244, 10993, 10747, 10504, 10266,
                         10033, 9803, 9578, 9357, 9141, 8928, 8721, 8517, 8317, 8122, 7931, 7744, 7561, 7383, 7208, 7037, 6870, 6707, 6547, 6391, 6239, 6091, 5946, 5804, 5666, 5531, 5400, 5272,
                         5147, 5024, 4905, 4789, 4676, 4566, 4458, 4353, 4251, 4151, 4054, 3959, 3866, 3776, 3689, 3603, 3520, 3438, 3359, 3282, 3207, 3134, 3062, 2992, 2925, 2858, 2794};
#elif defined (B3625)
/*         B25/100: 3625         */
  uint16_t m_adc[151] = {31550, 31490, 31426, 31359, 31289, 31217, 31140, 31061, 30978, 30891, 30801, 30707, 30609, 30507, 30402, 30292, 30178, 30059, 29937, 29810, 29678, 29542, 29401, 29256,
                         29106, 28951, 28792, 28627, 28458, 28284, 28105, 27921, 27733, 27540, 27341, 27138, 26931, 26718, 26501, 26280, 26054, 25823, 25589, 25350, 25107, 24860, 24609, 24355,
                         24097, 23836, 23571, 23304, 23033, 22760, 22485, 22207, 21926, 21644, 21360, 21075, 20788, 20500, 20211, 19922, 19631, 19341, 19050, 18759, 18469, 18179, 17889, 17601,
                         17313, 17027, 16742, 16458, 16176, 15896, 15618, 15342, 15068, 14796, 14527, 14261, 13997, 13736, 13478, 13223, 12971, 12722, 12476, 12233, 11994, 11758, 11526, 11297,
                         11072, 10850, 10631, 10416, 10205, 9997, 9793, 9592, 9395, 9201, 9011, 8824, 8641, 8461, 8285, 8112, 7942, 7776, 7613, 7453, 7297, 7144, 6994, 6847, 6703, 6562, 6424,
                         6289, 6157, 6028, 5901, 5777, 5656, 5538, 5422, 5309, 5198, 5089, 4983, 4880, 4778, 4679, 4583, 4488, 4395, 4305, 4216, 4130, 4046, 3963, 3882, 3803, 3726, 3651, 3577};
#elif defined (B3530)
/*         B25/100: 3530         */
  uint16_t m_adc[151] = {31484, 31421, 31355, 31286, 31215, 31140, 31062, 30980, 30896, 30807, 30715, 30620, 30521, 30417, 30310, 30199, 30084, 29965, 29842, 29714, 29582, 29446, 29305, 29160,
                         29010, 28856, 28697, 28534, 28366, 28193, 28016, 27834, 27648, 27457, 27261, 27061, 26857, 26648, 26435, 26217, 25996, 25770, 25540, 25307, 25069, 24828, 24583, 24335,
                         24084, 23829, 23571, 23311, 23048, 22782, 22514, 22244, 21971, 21697, 21422, 21144, 20866, 20586, 20306, 20024, 19743, 19461, 19178, 18896, 18614, 18332, 18051, 17770,
                         17491, 17212, 16935, 16659, 16384, 16111, 15840, 15571, 15304, 15039, 14776, 14516, 14258, 14003, 13750, 13500, 13253, 13009, 12767, 12529, 12294, 12062, 11833, 11607,
                         11385, 11166, 10950, 10737, 10528, 10322, 10120, 9920, 9725, 9532, 9343, 9157, 8974, 8795, 8619, 8446, 8276, 8110, 7947, 7786, 7629, 7475, 7324, 7176, 7031, 6889, 6750,
                         6613, 6479, 6349, 6220, 6095, 5972, 5851, 5733, 5618, 5505, 5394, 5286, 5180, 5077, 4975, 4876, 4779, 4684, 4591, 4500, 4411, 4324, 4239, 4156, 4074, 3994, 3916, 3840};
#elif defined (B3492)
/*         B25/100: 3492         */
  uint16_t m_adc[151] = {31456, 31392, 31326, 31256, 31184, 31108, 31029, 30947, 30862, 30773, 30680, 30584, 30484, 30381, 30273, 30162, 30046, 29927, 29803, 29675, 29543, 29406, 29266, 29121,
                         28971, 28817, 28659, 28496, 28328, 28156, 27980, 27799, 27613, 27423, 27229, 27030, 26827, 26620, 26408, 26192, 25972, 25749, 25521, 25289, 25054, 24815, 24573, 24327,
                         24078, 23826, 23571, 23314, 23054, 22791, 22526, 22259, 21989, 21719, 21446, 21172, 20897, 20621, 20343, 20066, 19787, 19508, 19229, 18951, 18672, 18393, 18115, 17838,
                         17562, 17286, 17012, 16739, 16468, 16198, 15929, 15663, 15399, 15136, 14876, 14618, 14363, 14110, 13859, 13611, 13366, 13124, 12885, 12648, 12415, 12184, 11957, 11733,
                         11512, 11294, 11079, 10867, 10659, 10454, 10252, 10054, 9858, 9666, 9478, 9292, 9110, 8931, 8755, 8582, 8413, 8246, 8083, 7922, 7765, 7611, 7460, 7311, 7166, 7023, 6883,
                         6746, 6612, 6481, 6352, 6225, 6102, 5981, 5862, 5746, 5632, 5521, 5412, 5305, 5200, 5098, 4998, 4900, 4804, 4710, 4618, 4528, 4440, 4354, 4269, 4187, 4106, 4027, 3950};
#else
/*         B25/100: 3380         */
  uint16_t m_adc[151] = {31370, 31304, 31235, 31163, 31088, 31011, 30930, 30845, 30758, 30667, 30573, 30475, 30373, 30268, 30159, 30047, 29930, 29810, 29685, 29557, 29425, 29288, 29148, 29003,
                         28854, 28701, 28543, 28382, 28216, 28046, 27872, 27693, 27511, 27324, 27133, 26938, 26739, 26536, 26329, 26118, 25903, 25685, 25463, 25238, 25009, 24777, 24542, 24304,
                         24062, 23818, 23571, 23322, 23070, 22816, 22560, 22302, 22042, 21781, 21518, 21254, 20988, 20722, 20454, 20186, 19918, 19649, 19380, 19111, 18842, 18573, 18305, 18038,
                         17771, 17505, 17240, 16976, 16713, 16452, 16192, 15934, 15678, 15423, 15171, 14920, 14672, 14426, 14182, 13941, 13702, 13466, 13232, 13001, 12773, 12548, 12325, 12105,
                         11888, 11674, 11463, 11255, 11050, 10847, 10648, 10452, 10259, 10069, 9882, 9698, 9517, 9339, 9164, 8992, 8822, 8656, 8493, 8333, 8175, 8020, 7868, 7719, 7573, 7429, 7288,
                         7150, 7015, 6881, 6751, 6623, 6497, 6374, 6254, 6135, 6020, 5906, 5795, 5685, 5578, 5474, 5371, 5270, 5172, 5075, 4980, 4888, 4797, 4708, 4621, 4535, 4451, 4370, 4289};
#endif

  if (adcRez > m_adc[0]) return -55000;
  else if (adcRez < m_adc[150]) return 125000;
  else {
    for (int32_t i=0; i<150; i++) {
      if (adcRez <= m_adc[i] && adcRez > m_adc[i+1]) {
        int32_t ra = (uint32_t)(m_adc[i] - adcRez) * 1000 / (m_adc[i] - m_adc[i+1]);
        return ((i-25) * 1000 + ra);
      }
    }
  }
  return 0;
}

void disp() { // Чтение датчика давления и выдача на дисплей
     uint16_t ad_temp;
     int16_t tempCompute; 
     float tempComputeResDS;
              mysensor.readSensor(temperature, pressure); //! чтение датчика давления
            pressure = pressure * 0.00750063755419211 - DeltaPress; //! перевод Паскалей в мм.р.ст и применение поправки

            // tempComputeResDS = (float)computeTemp_15bit(pressure); //! колдунство
            tempCompute = int16_t(pressure * 256);
            ds18bP.scratchpad[3] = tempCompute >> 8; ds18bP.scratchpad[2] = tempCompute & 0xff; ds18bP.setTemperature(pressure);
            
    

                                                      // ! Вывод на дисплей 
            dtostrf((float)(pressure),6, 2, outstr);
            ASOled.printString_12x16(F("Pк= "), 0, 0);
            ASOled.printString_12x16(outstr, 40, 0);
            dtostrf((float)computeTemp_15bit(readADS(0, 16))/1000,6, 2, outstr);
            ASOled.printString_12x16(F("Tп= "), 0, 2);
            ASOled.printString_12x16(outstr, 40, 2);            
            dtostrf((float)computeTemp_15bit(readADS(1, 16))/1000,6, 2, outstr);
            ASOled.printString_12x16(F("Tц= "), 0, 4);
            ASOled.printString_12x16(outstr, 40, 4);     
            dtostrf((float)computeTemp_15bit(readADS(2, 16))/1000,6, 2, outstr);
            ASOled.printString_12x16(F("Tк= "), 0, 6);
            ASOled.printString_12x16(outstr, 40, 6); 
}

void setup() {
    ASOled.init();                        // Инициализируем OLED дисплей //!
    ASOled.clearDisplay();  // Очищаем, иначе некорректно работает для дисплеев на SH1106 (косяк библиотеки) /!
    ASOled.printString_12x16(F("Запуск..."), 0, 0);

 
#if defined (SERIAL_DEBUG) || defined (SERIAL_TEST_NTC)
  Serial.begin(115200);
  millisConvert = millis();
#endif
  pinMode(pin_led, OUTPUT);
  digitalWrite(pin_led, 1);
  wdt_enable(WDTO_1S);
  Wire.begin();
  hub.attach(ds18bP);  ds18bP.setTemperature((float)85.0); // Добавляем в хаб 1Ware датчик давления
  if (readADS(0, 1) < 32750) {
    hub.attach(ds18b1); ntcEn[0] = 1; ds18b1.setTemperature((float)85.0);
  } else ntcEn[0] = 0;
  if (readADS(1, 1) < 32750) {
    hub.attach(ds18b2); ntcEn[1] = 1; ds18b2.setTemperature((float)85.0);
  } else ntcEn[1] = 0;
  if (readADS(2, 1) < 32750) {
    hub.attach(ds18b3); ntcEn[2] = 1; ds18b3.setTemperature((float)85.0);
  } else ntcEn[2] = 0;
  if (readADS(3, 1) < 32750) {
    hub.attach(ds18b4); ntcEn[3] = 1; ds18b4.setTemperature((float)85.0);
  } else ntcEn[3] = 0;
  if (readADS(4, 1) < 32750) {
    hub.attach(ds18b5); ntcEn[4] = 1; ds18b5.setTemperature((float)85.0);
  } else ntcEn[4] = 0;
  if (readADS(5, 1) < 32750) {
    hub.attach(ds18b6); ntcEn[5] = 1; ds18b6.setTemperature((float)85.0);
  } else ntcEn[5] = 0;
  if (readADS(6, 1) < 32750) {
    hub.attach(ds18b7); ntcEn[6] = 1; ds18b7.setTemperature((float)85.0);
  } else ntcEn[6] = 0;
  if (readADS(7, 1) < 32750) {
    hub.attach(ds18b8); ntcEn[7] = 1; ds18b8.setTemperature((float)85.0);
  } else ntcEn[7] = 0;

#if defined (SERIAL_DEBUG)  || defined (SERIAL_TEST_NTC)
  uint32_t iT = millis() - millisConvert;
  Serial.print("Инициализация длилась: "); Serial.print(iT); Serial.println(" мСек.");
  for (int i=0; i<8; i++) {
    if (ntcEn[i]) {
      Serial.print("Датчик "); Serial.print(i+1); Serial.println(" подключен.");
    }
  }
#endif

  digitalWrite(pin_led, 0);
mysensor.begin(); //! Инициализация манометра
    
}

void loop() {
#ifndef SERIAL_TEST_NTC  

  hub.poll();
  wdt_reset();
  

    
  if (!hub.startConvert) millisConvert = millis() + 50;
  if (hub.startConvert && millisConvert < millis()) {
    uint16_t ad_temp;
    int16_t tempCompute; 
    float tempComputeResDS;
    
    W1_Connect_Enable = true; //! Есть контакт по 1 Ware
    hub.startConvert = false;
    digitalWrite(pin_led, 1);
    for(int i=0; i<8; i++) {
      if (ntcEn[i]) {
        ad_temp = readADS(i, 16);
        tempComputeResDS = (float)computeTemp_15bit(ad_temp) / 1000;
        tempCompute = int16_t(tempComputeResDS * 256);
#ifdef SERIAL_DEBUG
        Serial.print(ad_temp); Serial.print("  Температура датчика "); Serial.print(i+1); Serial.print(": "); Serial.print(tempComputeResDS, 3); Serial.println(" гр.С");
#endif
        switch (i) {
          case 0: ds18b1.scratchpad[3] = tempCompute >> 8; ds18b1.scratchpad[2] = tempCompute & 0xff; ds18b1.setTemperature(tempComputeResDS); break;
          case 1: ds18b2.scratchpad[3] = tempCompute >> 8; ds18b2.scratchpad[2] = tempCompute & 0xff; ds18b2.setTemperature(tempComputeResDS); break;
          case 2: ds18b3.scratchpad[3] = tempCompute >> 8; ds18b3.scratchpad[2] = tempCompute & 0xff; ds18b3.setTemperature(tempComputeResDS); break;
          case 3: ds18b4.scratchpad[3] = tempCompute >> 8; ds18b4.scratchpad[2] = tempCompute & 0xff; ds18b4.setTemperature(tempComputeResDS); break;
          case 4: ds18b5.scratchpad[3] = tempCompute >> 8; ds18b5.scratchpad[2] = tempCompute & 0xff; ds18b5.setTemperature(tempComputeResDS); break;
          case 5: ds18b6.scratchpad[3] = tempCompute >> 8; ds18b6.scratchpad[2] = tempCompute & 0xff; ds18b6.setTemperature(tempComputeResDS); break;
          case 6: ds18b7.scratchpad[3] = tempCompute >> 8; ds18b7.scratchpad[2] = tempCompute & 0xff; ds18b7.setTemperature(tempComputeResDS); break;
          case 7: ds18b8.scratchpad[3] = tempCompute >> 8; ds18b8.scratchpad[2] = tempCompute & 0xff; ds18b8.setTemperature(tempComputeResDS); break;
        }
      }
    }


 disp(); // Вывод на дисплей
   digitalWrite(pin_led, 0); 

    
  }
if (!W1_Connect_Enable) {  //нет соединения по 1Ware, просто выводим цифры
if ((millis() % 1000) == 0) {      // ! Раз в секунду
 disp(); // Вывод на дисплей
   } }
#else


  Serial.println();
  uint32_t tm = millis() + 1000;
  for(int i=0; i<8; i++) {
    if (ntcEn[i]) {
      int16_t ad_temp = readADS(i, 16);
      Serial.print("ADC = "); Serial.print(ad_temp);
      Serial.print("  |  T"); Serial.print(i+1); Serial.print(" = "); Serial.print((float)computeTemp_15bit(ad_temp)/1000-3.3, 3);
      Serial.print("  |  Time convert (millis) = "); Serial.println(millis() + 1000 - tm);
      computeTemp_15bit(ad_temp);
      
                  }
                          }
   
  while (tm > millis()) {
    wdt_reset();
  }

#endif

}
