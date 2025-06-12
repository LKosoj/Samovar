
static void writeRegister(uint8_t i2cAddress, uint8_t reg, uint16_t value) {  // Запись регистров АЦП
  Wire.beginTransmission(i2cAddress);
  Wire.write((uint8_t)reg);
  Wire.write((uint8_t)(value >> 8));
  Wire.write((uint8_t)(value & 0xFF));
  Wire.endTransmission();
}
static uint16_t r_EAdregister(uint8_t i2cAddress, uint8_t reg) {              // Чтение регистров АЦП
  Wire.beginTransmission(i2cAddress);
  Wire.write((uint8_t)reg);
  Wire.endTransmission();
  Wire.requestFrom(i2cAddress, (uint8_t)2);
  return ((Wire.read() << 8) | Wire.read());
}
uint16_t readADS(uint8_t channel, uint8_t cnt) {                              // Чтение усредненных из количества cnt значений канала АЦП № channel
  if (channel > 7 || cnt == 0) return 0;
  uint8_t ads_i2cAddress = 0;
  uint16_t config = 0b1000010111100011;
  switch (channel) {
    case (0):
      config |= ADS1115_REG_CONFIG_MUX_SINGLE_0;
      ads_i2cAddress = ADS_I2CADDR_1;
      break;
    case (1):
      config |= ADS1115_REG_CONFIG_MUX_SINGLE_1;
      ads_i2cAddress = ADS_I2CADDR_1;
      break;
    case (2):
      config |= ADS1115_REG_CONFIG_MUX_SINGLE_2;
      ads_i2cAddress = ADS_I2CADDR_1;
      break;
    case (3):
      config |= ADS1115_REG_CONFIG_MUX_SINGLE_3;
      ads_i2cAddress = ADS_I2CADDR_1;
      break;
    case (4):
      config |= ADS1115_REG_CONFIG_MUX_SINGLE_0;
      ads_i2cAddress = ADS_I2CADDR_2;
      break;
    case (5):
      config |= ADS1115_REG_CONFIG_MUX_SINGLE_1;
      ads_i2cAddress = ADS_I2CADDR_2;
      break;
    case (6):
      config |= ADS1115_REG_CONFIG_MUX_SINGLE_2;
      ads_i2cAddress = ADS_I2CADDR_2;
      break;
    case (7):
      config |= ADS1115_REG_CONFIG_MUX_SINGLE_3;
      ads_i2cAddress = ADS_I2CADDR_2;
      break;
  }
  uint32_t summ = 0;
  for (uint8_t i = 0; i < cnt; i++) {
    writeRegister(ads_i2cAddress, ADS1115_REG_POINTER_CONFIG, config);  // Write config register to the ADC
    delayMicroseconds(1200);
    summ += r_EAdregister(ads_i2cAddress, ADS1115_REG_POINTER_CONVERT);
  }
  return (uint16_t)(summ / cnt);
}
int32_t computeTemp_15bit(uint16_t adcRez) {                                  // Перевод значения с АЦП в температуру

  if (adcRez > m_adc[0]) return -55000;
  else if (adcRez < m_adc[150]) return 125000;
  else {
    for (int32_t i = 0; i < 150; i++) {
      if (adcRez <= m_adc[i] && adcRez > m_adc[i + 1]) {
        int32_t ra = (uint32_t)(m_adc[i] - adcRez) * 1000 / (m_adc[i] - m_adc[i + 1]);
        return ((i - 25) * 1000 + ra);
      }
    }
  }
  return 0;
}
uint16_t G_to_alc(uint16_t G) {                                               // Перевод плотности *10000 в объёмные проценты спирта
   uint16_t G_alc[51] = {9982, 9945, 9910, 9878, 9848, 9819, 9791, 9764, 9739, 9713, 9686, 9659, 9631, 9602, 9571, 9538, 9504, 9468, 9431, 9392,
                         9352, 9311, 9269, 9226, 9182, 9138, 9094, 9049, 9003, 8957, 8911, 8865, 8818, 8771, 8724, 8677, 8629, 8581, 8532, 8484,
                         8434, 8385, 8335, 8284, 8232, 8180, 8126, 8071, 8014, 7955, 7893};
  if (G > G_alc[0]) return 0;
  else if (G < G_alc[50]) return 1000;
  else {
    for (int32_t i = 0; i < 50; i++) {
      if (G <= G_alc[i] && G > G_alc[i + 1]) return((i*20) + ((G_alc[i] - G)*20) / (G_alc[i] - G_alc[i + 1]));
    }
  }
  return 0;
}
uint16_t Alc_to_G(uint16_t Alc) {                                             // перевод объёмных процентов спирта *100 в плотность *10000
   uint16_t alc_G[39] = {0, 303, 640, 1014, 1416, 1844, 2250, 2632, 2976, 3294, 3595, 3875, 4146, 4409, 4664, 4914, 5164, 5409, 5648, 5887,
                         6126, 6362, 6596, 6830, 7063, 7292, 7518, 7746, 7968, 8192, 8412, 8627, 8838, 9048, 9251, 9449, 9641, 9826, 10000};
  if (Alc > 9999) return 7893;
  else if (Alc == 0 ) return 9982;
  else {
    for (int32_t i = 0; i < 38; i++) {
      if (Alc >= alc_G[i] && Alc < alc_G[i + 1]) return(9982-i*55 - (uint32_t)(((alc_G[i] - Alc)*55) / (alc_G[i] - alc_G[i + 1])));
    }
  }
  return 9982;
}
uint16_t T_to_ADS(float t) {                                                  // Вычисление АДС в зависимости от температуры
  float Rt=R10 * 1000 * exp((1/(t+273.15)-1/298.15)*B25);
  float Rp=1/(1/Rt+1/(R10*1000));
  uint16_t ADS=round(((U33/(R62*1000+Rp))*Rp)/Uref *32768);
  return(ADS);
}
void ADS_Construct() {                                                        // Конструктор характеристики термисторов
  for (int32_t i = 0; i < 150; i++) {
   m_adc[i]=T_to_ADS(i-25);
  }
}
void EEPROM_Init() {                                                          // Инициализация переменных из/в EEPROM
  EEPROM.begin(EEPROM_SIZE);
  if (EEPROM[0]==EepromKey) {           
    EEPROM.get(KTemp_2_EAdr,KTemp_2); EEPROM.get(BaseTemp_2_EAdr,BaseTemp_2); EEPROM.get(PressureBaseADS_EAdr,PressureBaseADS); EEPROM.get(PressureQ_EAdr,PressureQ);
    EEPROM.get(KTemp_3_EAdr,KTemp_3); EEPROM.get(BaseTemp_3_EAdr,BaseTemp_3); EEPROM.get(dPress_3_EAdr,dPress_3); EEPROM.get(HX710B_Mult_EAdr,HX710B_Mult);
    EEPROM.get(KTemp_1_EAdr,KTemp_1); EEPROM.get(BaseTemp_1_EAdr,BaseTemp_1); EEPROM.get(dPress_1_EAdr,dPress_1);
    EEPROM.get(U33_EAdr,U33); EEPROM.get(Uref_EAdr,Uref); EEPROM.get(R62_EAdr,R62); EEPROM.get(R10_EAdr,R10);  EEPROM.get(B25_EAdr,B25); 
    EEPROM.get(m_adc_EAdr,m_adc);
    EEPROM.get(N_dPressAlc_EAdr,N_dPressureAlc); EEPROM.get(k_Alc_T_EAdr,k_Alc_T);  EEPROM.get(k_Alc_EAdr,k_Alc);
    EEPROM.get(PRESSURE_MPX_ENABLE_ADDR, Pressure_enable[2]); EEPROM.get(PRESSURE_HX710B_ENABLE_ADDR, Pressure_enable[3]);
    EEPROM.get(DEFAULT_PRESSURE_ADDR, Pressure_enable[0]); Pressure_enable[0]= Pressure_enable[0]<4 ? Pressure_enable[0] : 0;
    EEPROM.get(XGZP6897D_K_ADDR, XGZP6897D_k); 
   } else {
    EEPROM[0]=EepromKey;
    EEPROM.put(KTemp_2_EAdr,KTemp_2); EEPROM.put(BaseTemp_2_EAdr,BaseTemp_2); EEPROM.put(PressureBaseADS_EAdr,PressureBaseADS); EEPROM.put(PressureQ_EAdr,PressureQ);
    EEPROM.put(KTemp_3_EAdr,KTemp_3); EEPROM.put(BaseTemp_3_EAdr,BaseTemp_3); EEPROM.put(dPress_3_EAdr,dPress_3); EEPROM.put(HX710B_Mult_EAdr,HX710B_Mult);
    EEPROM.put(KTemp_1_EAdr,KTemp_1); EEPROM.put(BaseTemp_1_EAdr,BaseTemp_1); EEPROM.put(dPress_1_EAdr,dPress_1);
    EEPROM.put(U33_EAdr,U33); EEPROM.put(Uref_EAdr,Uref); EEPROM.put(R62_EAdr,R62); EEPROM.put(R10_EAdr,R10);  EEPROM.put(B25_EAdr,B25);
    EEPROM.put(m_adc_EAdr,m_adc);
    EEPROM.put(N_dPressAlc_EAdr,N_dPressureAlc); EEPROM.put(k_Alc_T_EAdr,k_Alc_T); EEPROM.put(k_Alc_EAdr,k_Alc);
    EEPROM.put(PRESSURE_MPX_ENABLE_ADDR, PRESSURE_MPX_ENABLE); EEPROM.put(PRESSURE_HX710B_ENABLE_ADDR, PRESSURE_HX710B_ENABLE); 
    EEPROM.put(DEFAULT_PRESSURE_ADDR, DEFAULT_PRESSURE);
    EEPROM.put(XGZP6897D_K_ADDR, XGZP6897D_k);
    EEPROM.commit();
  }
  EEPROM.end();
}
void ReadPressure() {                                                         // Чтение датчиков давления и запись их в 1Ware хаб, если есть подключение
  if (Pressure_enable[1]) {                                  // Чтение датчика давления I2C
    XGZP.readSensor(temperature[1], pressure[1]); 
    dPt_1 = ((float)temperature[1] - BaseTemp_1) * KTemp_1;
    pressure[1]= ((float)pressure[1]/XGZP6897D_k) * 0.00750063755419211 - dPress_1- dPt_1;
    if (Pressure_enable[0]==1) Temp[0] =pressure[1];
  }  
  if (Pressure_enable[2]) {                                  // Чтение датчика давления на 8 канале АЦП
    ADSt=(float)readADS(7, 16);
    pressure[2] = ((ADSt - PressureBaseADS) * PressureQ);             //чтение датчика и перевод значения в мм.рт.ст
                                                                                      //применение поправки и температурной компенсации (эмпирически)
    Temp[6] = (float)computeTemp_15bit(readADS(6, 4)) / 1000;                         // чтение температуры 7 датчика
    dPt_2 = ((float)Temp[6] - BaseTemp_2) * KTemp_2;                                  // расчет поправки термокомпенсации если используется
    pressure[2]= ((float)pressure[2] - (float)dPress_2) - dPt_2;
    if (Pressure_enable[0]==2) Temp[0] = pressure[2];
  }  
  if (Pressure_enable[3]) {// Чтение датчика давления на АЦП HX710B
    Temp[6] = (float)computeTemp_15bit(readADS(6, 4)) / 1000;                                         // чтение температуры 7 датчика
    dPt_3 = ((float)Temp[6] - BaseTemp_3) * KTemp_3;                                                  // расчет поправки термокомпенсации если используется
    if (HX710B_Obj.is_ready()) pressure[3] = (float)HX710B_Obj.raw2mmHg((int32_t)HX710B_Obj.get_value(4)*HX710B_Mult)-(float)dPress_3-dPt_3;  //чтение датчика, перевод значения в мм.рт.ст, умножение на коэф вранья
                                                                                                      //применение поправки и температурной компенсации (эмпирически)
                                                  
    if (Pressure_enable[0]==3) Temp[0] = (float)pressure[3]; 
  }  
  if (OneWireConnectDetected) {                              // Запись значения давления в виде температуры по 1Ware
    float t = (debug_mode ? Temp_debug[0] : Temp[0]);
    int16_t tempCompute = int16_t(t * 256);  
    ds18bP.scratchpad[3] = tempCompute >> 8;
    ds18bP.scratchpad[2] = tempCompute & 0xff;
    ds18bP.setTemperature(t);
  }
}
void RotatePSensor() {                                                        // Смена активного сенсора давления
    if (digitalRead(BtnUp) == LOW)  { // Меняем датчики давления по кругу по нажатию BtnUp
     switch (Pressure_enable[0]) { 
        case 1: {
        if (Pressure_enable[2]==1) {Pressure_enable[0]=2; break; }
        if (Pressure_enable[3]==1) {Pressure_enable[0]=3; break; }
        }
        case 2: {
        if (Pressure_enable[3]==1) {Pressure_enable[0]=3; break; }
        if (Pressure_enable[1]==1) {Pressure_enable[0]=1; break; }
        }
        case 3: {
        if (Pressure_enable[1]==1) {Pressure_enable[0]=1; break; }
        if (Pressure_enable[2]==1) {Pressure_enable[0]=2; break; }
        }
       }

       LD.clearDisplay();
    } 

} 
void ADS_Init() {
  
    if (Pressure_enable[3] == 1) {         // Если включен в настройках датчик 040DR1 или т.п. с АЦП HX710B
    HX710B_Obj.begin(PinDOUT, PinSCLK);
    HX710B_Obj.set_scale(1);
    HX710B_Obj.set_offset(0);
    //Serial.println("HX710B begin.");
  }  

  if (XGZP.begin()) {                // Инициализация датчика XGZP6897D  
    Pressure_enable[1] = 1;
    //Serial.println("XGZP6897D begin.");
  }
  if (Pressure_enable[0]) {            // Добавляем в хаб 1Ware датчик давления
    hub.attach(ds18bP);
    ds18bP.setTemperature((float)0.0); ds18bP.scratchpad[3] = 0; ds18bP.scratchpad[2] = 0;
    ntcEn[0] = 1;
   } else { // если датчика давления нет заменяем его вывод на дисплей на 4 датчик температуры
    ntcEn[0] = 0;
  }  
  if (readADS(0, 1) < ADS_Trg) {       // Определение подключенных термисторов и инициализация их адресов по 1Ware
     hub.attach(ds18b1);
     ntcEn[1] = 1;
     ds18b1.setTemperature((float)25.0); ds18b1.scratchpad[3] = 25 >> 8; ds18b1.scratchpad[2] = 25 & 0xff;
   } else ntcEn[1] = 0;
   if (readADS(1, 1) < ADS_Trg) {
     hub.attach(ds18b2);
     ntcEn[2] = 1;
     ds18b2.setTemperature((float)25.0); ds18b2.scratchpad[3] = 25 >> 8; ds18b2.scratchpad[2] = 25 & 0xff;
   } else ntcEn[2] = 0;
   if (readADS(2, 1) < ADS_Trg) {
     hub.attach(ds18b3);
     ntcEn[3] = 1;
     ds18b3.setTemperature((float)25.0); ds18b3.scratchpad[3] = 25 >> 8; ds18b3.scratchpad[2] = 25 & 0xff;
   } else ntcEn[3] = 0;
   if (readADS(3, 1) < ADS_Trg) {
     hub.attach(ds18b4);
     ntcEn[4] = 1;
     ds18b4.setTemperature((float)25.0); ds18b4.scratchpad[3] = 25 >> 8; ds18b4.scratchpad[2] = 25 & 0xff;
   } else ntcEn[4] = 0;
   if (readADS(4, 1) < ADS_Trg) {
     hub.attach(ds18b5);
     ntcEn[5] = 1;
     ds18b5.setTemperature((float)25.0); ds18b5.scratchpad[3] = 25 >> 8; ds18b5.scratchpad[2] = 25 & 0xff;
   } else ntcEn[5] = 0;
   if (readADS(5, 1) < ADS_Trg) {  // Выделен под поправку электронного попугая
     ntcEn[6] = 1;
   } else ntcEn[6] = 0;
   if ((readADS(6, 1) < ADS_Trg) /*&& (KTemp_2 == 0)*/) {  // Затействован под температурную компенсацию 
     ntcEn[7] = 1;
   } else ntcEn[7] = 0;
   if ((readADS(7, 1) < ADS_Trg) /*&& (!(Pressure_enable == 2)) && (!(Pressure_enable == 3))*/) {  //Выделен под датчик MPX10DP
     ntcEn[8] = 1;
   } else ntcEn[8] = 0;
   if (!Pressure_enable[0]) ntcEn[0] = ntcEn[4];  // в случае отсутствия датчика давления подмена его на 4 термометр
}
void ADS_Loop() {
  
    hub.poll();   // Обработка запросов по 1Wire
      if (!hub.startConvert) millisConvert = millis() + 50;
    if (hub.startConvert && millisConvert < millis()) {
      if (Pressure_enable[0]) ReadPressure();  // Чтение давления
      uint16_t ad_temp;
      int16_t tempCompute;
      OneWireConnectDetected = true;  //Раз мы сюда попали, значит есть контакт по 1 Ware
      hub.startConvert = false;
      for (int i = 1; i < 9; i++) {
        if (debug_mode ? true : ntcEn[i]) {
          ad_temp = readADS(i - 1, 16);                        // Чтение из АЦП канала i-1, среднее из 16 выборок
          Temp[i] = (float)computeTemp_15bit(ad_temp) / 1000;  // запоминаем для последующего вывода на дисплей
          float t = (debug_mode ? Temp_debug[i] : Temp[i]);
          tempCompute = int16_t(t * 256);
          switch (i) {
            case 1:
              ds18b1.scratchpad[3] = tempCompute >> 8;
              ds18b1.scratchpad[2] = tempCompute & 0xff;
              ds18b1.setTemperature(t);
              break;
            case 2:
              ds18b2.scratchpad[3] = tempCompute >> 8;
              ds18b2.scratchpad[2] = tempCompute & 0xff;
              ds18b2.setTemperature(t);
              break;
            case 3:
              ds18b3.scratchpad[3] = tempCompute >> 8;
              ds18b3.scratchpad[2] = tempCompute & 0xff;
              ds18b3.setTemperature(t);
              break;
            case 4:
              ds18b4.scratchpad[3] = tempCompute >> 8;
              ds18b4.scratchpad[2] = tempCompute & 0xff;
              ds18b4.setTemperature(t);
              break;
            case 5:
              ds18b5.scratchpad[3] = tempCompute >> 8;
              ds18b5.scratchpad[2] = tempCompute & 0xff;
              ds18b5.setTemperature(t);
              break;
          }
        }
      }
      if (!Pressure_enable[0]) Temp[0] = Temp[4];  // в случае отсутствия датчика давления подмена его на 4 термометр
      disp();                                      // Вывод на дисплей
    }
    if (!OneWireConnectDetected) {  // нет соединения по 1Ware, просто выводим цифры
  static unsigned long timeout = millis(); //остальное раз в секунду
  if (millis() - timeout >= 1000) { 
        if ((millis()<3000) || (millis()>10000)) {   // С 3 по 10 секунду ничего не читаем для инициализации 1Ware c Самоваром
        if (Pressure_enable[0]) ReadPressure();      // Чтение давления
        for (int i = 1; i < 8; i++) {                // читаем температуры в массив
          if (ntcEn[i]) Temp[i] = (float)computeTemp_15bit(readADS(i - 1, 16)) / 1000;
        }
        if (!Pressure_enable[0]) Temp[0] = Temp[4];  // в случае отсутствия датчика давления подмена его на 4 термометр
        disp();   }                                  // вывод на дисплей
       timeout = millis();                    // перезапуск секундного таймера
      }
    }
}