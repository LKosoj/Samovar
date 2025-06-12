// Инициализация OLED
void initOLED() {
  #ifdef ENABLE_OLED_DISPLAY
  LD.init();
  //LD.clearDisplay();
  LD.setFont(Font_12x16);
  LD.printString("           ", 1, 0);
  LD.printString("          ", 1, 2);
  LD.printString(" Start... ", 1, 4);
  LD.printString("          ", 1, 6);
  #endif
}
bool EnterPressed(){            
  #ifdef ENABLE_OLED_DISPLAY                                              // Нажатие Enter с контролем последующего отпускания
 if (digitalRead(BtnEnter) == LOW) 
        { if (BtnEnterFlg == false) {BtnEnterFlg = true; return(true); 
		                     } else return(false);
   } else 	{ BtnEnterFlg = false; return(false); }
  #endif
   return(false);  
}
bool SelectPressed(){          
  #ifdef ENABLE_OLED_DISPLAY                                               // Нажатие Select с контролем последующего отпускания
 if (digitalRead(BtnSel) == LOW) 
        { if (BtnSelFlg == false) {BtnSelFlg = true; return(true); 
		                     } else return(false);
   } else 	{ BtnSelFlg = false; return(false); }
  #endif
  return(false);
}
void Caption(uint8_t Cap, uint8_t Str){                                       // Вывод сообщений на дисплей
    #ifdef ENABLE_OLED_DISPLAY
  switch (Cap) {                                                              // (для экономии памяти ардуины, первое число в комментариях - количество вызовов)
      case 1: LD.printString_6x8(F("Настройка д. давлен."), 1, Str); break; //1 Cap_NastrDD = 1;
      case 2: LD.printString_6x8(F("Датчик XGZP6897D I2C"), 1, Str); break; //3 Cap_XGZP6897D = 2;
      case 3: LD.printString_6x8(F("Датчик MPX5010DP АЦП"), 1, Str); break; //3 Cap_MPX5010DP = 3;
      case 4: LD.printString_6x8(F("Датчик на АЦП HX710B"), 1, Str); break; //3 Cap_HX710B = 4;
      case 5: LD.printString_6x8(F("Настройка термист."), 1, Str); break; //12 Cap_NastrNTC = 5;
      case 6: LD.printString_6x8(F("Настройка э.попугая."), 1, Str); break; //4 Cap_NastrEP = 6;
     
      case 21: LD.printString_6x8(F("Настр. базового ADS "), 1, Str); break; //1 Cap_NastrBasADS = 21;
      case 22: LD.printString_6x8(F("Настройка смещения 0"), 1, Str); break; //2 Cap_NastrOffset0 = 22;
      case 23: LD.printString_6x8(F("Настр.коэф.термокомп"), 1, Str); break; //3 Cap_NastrKtk = 23;
      case 25: LD.printString_6x8(F("Расчет В25/100"), 1, Str); break; //5 Cap_RaschB25 = 25;
      case 26: LD.printString_6x8(F("B25 расчитанный/тек."), 1, Str); break; //1 Cap_B25Rasch_Current = 26;
      case 27: LD.printString_6x8(F("N датчика давления"), 1, Str); break; //2 Cap_N_DP = 27;
      case 28: LD.printString_6x8(F("Корр. по t. 0-выкл"), 1, Str); break; //1 Cap_K_cor_po_t = 28;
      case 30: LD.printString_6x8(F("Настройка не треб."), 1, Str); break; //1 Cap_NastrNoNeed = 30;
      case 31: LD.printString_6x8(F("Цена разр.АЦП, квант"), 1, Str); break; //1 Cap_Quant = 31;
      case 32: LD.printString_6x8(F("Установка множителя"), 1, Str); break; //1 Cap_SetMult = 32;
      case 33: LD.printString_6x8(F("Сброс всех настроек?"), 1, Str); break; //1 Cap_EEPROM_0 = 33
      case 34: LD.printString_6x8(F("Сохранить настройки?"), 1, Str); break; //1 Cap_EEPROM_1 = 34
      
      case 51: LD.printString_6x8(F("Подайте 0 мм.рт.ст. "), 1, Str); break; //3 Cap_0mmg = 51;
      case 52: LD.printString_6x8(F("Подайте 30 мм.рт.ст."), 1, Str); break; //1 Cap_30mmg = 52;
      case 53: LD.printString_6x8(F("Подайте 50 мм.рт.ст."), 1, Str); break; //1 Cap_50mmg = 53;
      case 54: LD.printString_6x8(F("Ent-Начать,Sel-Проп."), 1, Str); break; //4 Cap_NextQ = 54;
      case 56: LD.printString_6x8(F("Напряжение 3.3 В"), 1, Str); break; //1 Cap_U33 = 56;
      case 57: LD.printString_6x8(F("Референс. напряжение"), 1, Str); break; //1 Cap_Uref = 57;
      case 60: LD.printString_6x8(F("Залейте раствор, %"), 1, Str); break; //1 Cap_Fill_Sort = 60;
      case 63: LD.printString_6x8(F("Нагрейте датчик 36.6"), 1, Str); break; //3 Cap_Burn_P_36_6 = 63;
      case 64: LD.printString_6x8(F("Сохранить? (Enter)"), 1, Str); break; //2 Cap_SaveQ = 64;
      case 65: LD.printString_6x8(F("Расч.кривую термист?"), 1, Str); break; //1 Cap_NextCalc = 65;
      case 66: LD.printString_6x8(F("Резистор 6.2 кОм"), 1, Str); break; //1 Cap_R_62kOm = 66;
      case 67: LD.printString_6x8(F("Резистор 10 кОм"), 1, Str); break; //1 Cap_R_10kOm = 67;
      
      case 81: LD.printString_6x8(F("Зап.-Ent. След.-Sel"), 1, Str); break; //21 Menu_Write_Next = 81;
      case 82: LD.printString_6x8(F(" Да -Ent. След.-Sel"), 1, Str); break; //2 Menu_Yes_Next = 82;
      case 83: LD.printString_6x8(F("Зап-Ent.След-Sel,-/+"), 1, Str); break; //5 Menu_Write_Next_PgUp_PgDn = 83;
      case 84: LD.printString_6x8(F(" Dwn (-),    Up (+) "), 1, Str); break; //6 Menu_PgUp_PgDn = 84;
      case 85: LD.printString_6x8(F(" След.-Sel"), 1, Str); break; //4 Menu_Next = 85;
      case 86: LD.printString_6x8(F("Ent.-Настр.Sel-Верн."), 1, Str); break; //1 Menu_Nastr = 86;
        }        
  #endif
}
void PrintPar(const char* Name, uint8_t Str, uint8_t r, float Par){               // Вывод на дисплей переменной
 #ifdef ENABLE_OLED_DISPLAY
 if (Rec) {LD.printString_12x16(Name, 0, Str); } else  {LD.printString_12x16(F("Rec"), 0, Str); Rec=1;} // печатаем название, если перед этим была запись в EEPROM, печатаем 1 раз Rec
 dtostrf((float)Par, 6, r, outstr); 
 LD.printString_12x16(outstr, 48, Str);
 #endif
}
bool Select(){                                                                // Переход на следующий экран по Select с очисткой экрана
  #ifdef ENABLE_OLED_DISPLAY
   if (SelectPressed()) {          // Переключение на следующий экран по кнопке BtnSel
       DispMode++; 
       LD.clearDisplay();  
       return(true);
       }   
  #endif
  return(false);  
}
void EnterJump(uint8_t disp){                                                 // переход по Enter на экран № disp
  #ifdef ENABLE_OLED_DISPLAY
 if (EnterPressed()) {DispMode=disp; LD.clearDisplay();}
  #endif
}
void InputPar(float& Par, float dPar) {                                       // Диалог ввода параметра
  #ifdef ENABLE_OLED_DISPLAY
	 if (digitalRead(BtnUp) == LOW)  Par += dPar;  // Коррекция параметра кнопками
   if (digitalRead(BtnDwn) == LOW) Par -= dPar;
  #endif
}
void PrintTemp(uint8_t i, const char* Name, uint8_t Str){                         // Вывод на дисплей температуры № i
  #ifdef ENABLE_OLED_DISPLAY
  LD.printString_12x16(Name, 0, Str);
  if (ntcEn[i]) {dtostrf((float)Temp[i], 6, 2, outstr); LD.printString_12x16(outstr, 48, Str);} else LD.printString_12x16(F("----"), 60, Str);
  #endif
}
void PrintTempSmall(uint8_t i, const char* Name, uint8_t Str, uint8_t Col){                         // Вывод на дисплей температуры № i
  #ifdef ENABLE_OLED_DISPLAY
  LD.printString_6x8(Name, Col, Str);
  if (ntcEn[i]) {dtostrf((float)Temp[i], 6, 2, outstr); LD.printString_6x8(outstr, Col+25, Str);} else LD.printString_6x8(F("------"), Col+25, Str);
  #endif
}
void spiker(){                    // Зуммер по повышению температуры в кубе выше уставки
  if ((ntcEn[spk_on])&&(T_target<=Temp[spk_on])) { 
  if (spk_count>0){
   if (spk_trigger==1) spk_trigger=0; else spk_trigger=1;
   digitalWrite(pin_spk, spk_trigger); 
   //dtostrf((float)spk_trigger, 6, 0, outstr); LD.printString_6x8(outstr, 48, 6);
   spk_count--;
   } else 
   { digitalWrite(pin_spk, 0); spk_on=-1; }
   } else digitalWrite(pin_spk, 0);
}
void disp() {                                                                 // Вывод на дисплей страниц отображения и настроек 
  #ifdef ENABLE_OLED_DISPLAY
    if (spk_on>-1) spiker();                     // Попищим
 //-----------------------------------------Константы для диалогов-------------------------------------
      const uint8_t //Номера сообщений диалога
      Cap_NastrDD = 1, //Настройка д. давлен.
      Cap_XGZP6897D = 2, //Датчик XGZP6897D I2C
      Cap_MPX5010DP = 3, //Датчик MPX5010DP АЦП
      Cap_HX710B = 4, //Датчик на АЦП HX710B
      Cap_NastrNTC = 5, //Настройка термист.
      Cap_NastrEP = 6, //Настройка э.попугая.
     
      Cap_NastrBasADS = 21, //Настр. базового ADS 
      Cap_NastrOffset0 = 22, //Настройка смещения 0
      Cap_NastrKtk = 23, //Настр.коэф.термокомп
      Cap_RaschB25 = 25, //Расчет В25/100
      Cap_B25Rasch_Current = 26, //B25 расчитанный/тек.
      Cap_N_DP = 27, //N датчика давления
      Cap_K_cor_po_t = 28, //Высота столба, см
      Cap_NastrNoNeed = 30, //Настройка не треб.
      Cap_Quant = 31, //Цена разр.АЦП, квант
      Cap_SetMult = 32, //Установка множителя
      Cap_EEPROM_0 = 33, //Сброс настроек?
      Cap_EEPROM_1 = 34, //Сохранить настройки?


      Cap_0mmg = 51, //Подайте 0 мм.рт.ст. 
      Cap_30mmg = 52, //Подайте 30 мм.рт.ст.
      Cap_50mmg = 53, //Подайте 50 мм.рт.ст.
      Cap_NextQ = 54, //Ent-Начать,Sel-Проп.
      Cap_U33 = 56, //Напряжение 3.3 В
      Cap_Uref = 57, //Референс. напряжение
      Cap_Fill_Sort = 60, //Залейте раствор, %
      Cap_Burn_P_36_6 = 63, //Нагрейте датчик 36.6
      Cap_SaveQ = 64, //Сохранить? (Enter)
      Cap_NextCalc = 65, //Расч.кривую термист?
      Cap_R_62kOm = 66, //Резистор 6.2 кОм
      Cap_R_10kOm = 67, //Резистор 10 кОм
      
      Menu_Write_Next = 81, //Зап.-Ent. След.-Sel
      Menu_Yes_Next = 82, // Да -Ent. След.-Sel
      Menu_Write_Next_PgUp_PgDn = 83, //Зап-Ent.След-Sel,+/-
      Menu_PgUp_PgDn = 84, // Up (+),    Dwn (-) 
      Menu_Next = 85, // След.-Sel
      Menu_Nastr = 86; // Ent.-Настр.Sel-Верн.
 switch (DispMode) {                                           // Экраны дисплея
  case 0: {                             // Экран Основной
    RotatePSensor();                             // Меняем датчики давления по кругу по нажатию BtnUp
    switch (Pressure_enable[0]) {
      case 0: PrintTemp(0, "Тв= ", 0); break;    
      case 1: PrintTemp(0, "Pк1 ", 0); break;
      case 2: PrintTemp(0, "Pк2 ", 0); break;
      case 3: PrintTemp(0, "Pк3 ", 0); 
    }
    PrintTemp(1, "Tп= ", 2); 
    PrintTemp(2, "Tц= ", 4);
    PrintTemp(3, "Tк= ", 6);
    if (EnterPressed()) {        // Фиксация нуля текущего датчика давления понажатию BtnEnter без записи в EEPROM
      switch (Pressure_enable[0]) {
      case 1: dPress_1 = pressure[1] + dPress_1; LD.clearDisplay(); break;         // Убираем дрейф нуля датчика давления I2C
      case 2: PressureBaseADS =(float)readADS(7, 16); LD.clearDisplay(); break;         // Убираем дрейф нуля датчика давления на 8 канале АЦП
      case 3: dPress_3 = pressure[3] + dPress_3; LD.clearDisplay(); break;         // Убираем дрейф нуля датчика давления на АЦП HX710B
      }
    }
  } Select(); break;
  case 1: {                             // Экран температуры с 4 по 7
    PrintTemp(4, "Тв= ", 0);
    PrintTemp(5, "TСА ", 2); 
    if (N_dPressureAlc) {
      if (pressure[N_dPressureAlc]>5) 
       {Alc=(float)G_to_alc((uint16_t)(k_Alc*pressure[N_dPressureAlc]))/10;    // Рассчет объемного содержания спирта, %
       Alc_T=Alc+(20-Temp[6])*k_Alc_T;                                         // Простенькая и совсем не точная коррекция по температуре
       PrintPar("Alc%",4,1,Alc_T);} else LD.printString_12x16(F("Alc%  --- "), 0, 4);
      } else PrintTemp(6, "Тep ", 4);
    //PrintTemp(7, "Тtk ", 6);
    Caption(Menu_Nastr,7);
    if (SelectPressed()) {          // Переключение на экран 99 по кнопке BtnSel
     DispMode=99; 
     LD.clearDisplay();  
     } 
    if (EnterPressed()) {      // По нажатию BtnDwn переход на экран настроек давления если есть активный датчик давления, иначе на экран настроек характеристик термисторов
      if (Pressure_enable[0]) DispMode = 2; else DispMode = 7;
      LD.clearDisplay();
      }
    ADSt1 = ADSt; if (Pressure_enable[3]) if (HX710B_Obj.is_ready()) Pressure3Temp = (float)HX710B_Obj.raw2mmHg((int32_t)HX710B_Obj.get_value(4));
  } break; 
    case 99:{                             //Экран настройки срабатывания зуммера по превышению уставки датчика
   LD.printString_12x16(F("SPK:"), 1, 0); 
   //if (spk_on==1) LD.printString_12x16(F(" ON"), 48, 0); else LD.printString_12x16(F("OFF"), 48, 0);
   
   if (EnterPressed()) {spk_on++; if (spk_on>5) spk_on=-1; else spk_count=spk_max_count + spk_max_count;}
   LD.printString_12x16(F("Уст."), 1, 2);
   InputPar(T_target, 1);
   dtostrf((float)T_target, 6, 0, outstr); 
   LD.printString_12x16(outstr, 48, 2);
   LD.printString_6x8(F("Ent., +/-, Sel.-exit"), 1, 7);
   
    switch (spk_on) {
      case -1:{LD.printString_12x16(F(" OFF"), 48, 0);} break;
      case 0:{LD.printString_12x16(F("   P"), 48, 0);} break;
      case 1:{LD.printString_12x16(F("  Tп"), 48, 0);} break;
      case 2:{LD.printString_12x16(F("  Tц"), 48, 0);} break;
      case 3:{LD.printString_12x16(F("  Tк"), 48, 0);} break;  
      case 4:{LD.printString_12x16(F("  Tв"), 48, 0);} break; 
      case 5:{LD.printString_12x16(F("Tтса"), 48, 0);} break;     
    }
    //dtostrf((float)spk_on, 6, 0, outstr); LD.printString_12x16(outstr, 48, 0);
    if (spk_on>-1) PrintTempSmall(spk_on, "Par=", 4, 1); else LD.printString_12x16(F("           "), 1, 4);
    
   //dtostrf((float)spk_count, 6, 0, outstr); LD.printString_6x8(outstr, 1, 6);
    if (SelectPressed()) {          // Переключение на экран 100 по кнопке BtnSel
     DispMode=100; 
     LD.clearDisplay(); 
  } } break; 
  case 100: {                             // Экран всех измерений для 2.4" дисплеев
    if (Pressure_enable[1]==1)  { LD.printString_6x8("P1  ", 1, 0); dtostrf((float)pressure[1], 6, 2, outstr); LD.printString_6x8(outstr, 26, 0);}
    if (Pressure_enable[2]==1)  { LD.printString_6x8("P2  ", 1, 1); dtostrf((float)pressure[2], 6, 2, outstr); LD.printString_6x8(outstr, 26, 1);} 
    if (Pressure_enable[3]==1)  { LD.printString_6x8("P3  ", 64, 0); dtostrf((float)pressure[3], 6, 2, outstr); LD.printString_6x8(outstr, 89, 0);} 
    //LD.printString_6x8(F("--------------------"), 1, 2);
    PrintTempSmall(1, "Tп= ", 2, 1); 
    PrintTempSmall(2, "Tц= ", 3, 1);
    PrintTempSmall(3, "Tк= ", 4, 1);
    PrintTempSmall(4, "Тв= ", 3, 64);
    PrintTempSmall(5, "TСА ", 4, 64);
    LD.printString_6x8(F("--------------------"), 1, 5);
    if (N_dPressureAlc) {
      if (pressure[N_dPressureAlc]>5) 
       {Alc=(float)G_to_alc((uint16_t)(k_Alc*pressure[N_dPressureAlc]))/10;    // Расчет объемного содержания спирта, %
       Alc_T=Alc+(20-Temp[6])*k_Alc_T;                                         // Простенькая и совсем не точная коррекция по температуре
       LD.printString_6x8("Alc%", 1,6); dtostrf((float)Alc_T, 5, 1, outstr); LD.printString_6x8(outstr, 26, 67);} 
       else LD.printString_6x8(F("Alc%  --- "), 1, 6);
      #ifdef ENABLE_WIFI
       if (WiFi.status() == WL_CONNECTED) { // Если подключены к WiFi выводим IP и RSSI
        LD.printString_6x8( WiFi.localIP().toString().c_str(),1,7); 
        LD.printString_6x8(("R " + String(WiFi.RSSI())).c_str(),94,7);
       }
      #endif
      } 
      PrintTempSmall(6, "Тep ", 6, 64);    
    if (SelectPressed()) {          // Переключение на экран 0 по кнопке BtnSel
     DispMode=0; 
     LD.clearDisplay();  
     }   
    if (EnterPressed()) {        // Фиксация нуля текущего датчика давления понажатию BtnEnter без записи в EEPROM
      switch (Pressure_enable[0]) {
      case 1: dPress_1 = pressure[1] + dPress_1; LD.clearDisplay(); break;         // Убираем дрейф нуля датчика давления I2C
      case 2: PressureBaseADS =(float)readADS(7, 16); LD.clearDisplay(); break;         // Убираем дрейф нуля датчика давления на 8 канале АЦП
      case 3: dPress_3 = pressure[3] + dPress_3; LD.clearDisplay(); break;         // Убираем дрейф нуля датчика давления на АЦП HX710B
      }
    }
  } break; 
  case 2: {                             // Экран настройка датчиков давления запрос пропуска
    B25t=B25;
    RotatePSensor();                             // Меняем датчики давления по кругу по нажатию BtnUp
    Caption(Cap_NastrDD,0); Caption(Cap_NextQ,7); Caption(Cap_N_DP,2);
    PrintPar("   N",4, 0,(float)Pressure_enable[0]);
    EnterJump(4); // переход к датчикам давления
   } if (Select()) DispMode=7;  // Переход к NTC
    break; 
  case 4: {                             // Экран для настройки множителя или кванта датчика давления
    float Qr, Mr;
    RotatePSensor();          // Меняем датчики давления по кругу по нажатию BtnUp, далее по Select
    switch (Pressure_enable[0]) {
      case 1: 
        Caption(Cap_XGZP6897D,0); Caption(Cap_NastrNoNeed,2); Caption(Menu_Next,6); 
        break;
      case 2: 
        Caption(Cap_MPX5010DP,0); Caption(Cap_Quant,1); Caption(Cap_50mmg,2); Caption(Menu_Write_Next,7);
        PrintPar("Q=  ",3, 6,PressureQ); 
        if ((ADSt - ADSt1)>10) PrintPar("Qr= ", 5, 6, (50/(ADSt - ADSt1))); else PrintPar("Qr= ", 5, 6, PressureQ);
        if (EnterPressed()) {
                    PressureQ =(50/(ADSt - ADSt1));
                    EEPROM.put(PressureQ_EAdr,PressureQ); 
                    Rec = 0;
                   }
        break;
      case 3: 
        Caption(Cap_HX710B,0); Caption(Cap_SetMult,1); Caption(Cap_30mmg,2); Caption(Menu_Write_Next,7);
        if (HX710B_Obj.is_ready()) {
          Mr = (float)HX710B_Obj.raw2mmHg((int32_t)HX710B_Obj.get_value(2));
          if (Mr>1) Mr = 30 / (Mr - Pressure3Temp); else Mr = HX710B_Mult;
          }
        PrintPar("M=  ", 3, 2, HX710B_Mult); PrintPar("Мr= ", 5, 2, Mr);
        if (EnterPressed()) {
                     HX710B_Mult = Mr;
                     EEPROM.put(HX710B_Mult_EAdr,HX710B_Mult);
                     Rec = 0;}
        } 
  } Select(); break;
  case 5: {                             // Экран для настройки смещения или базовой АДС датчика давления + запись базовой температуры
   RotatePSensor();          // Меняем датчики давления по кругу по нажатию BtnUp, далее по Select
   switch (Pressure_enable[0]) {
      case 1:
       Caption(Cap_XGZP6897D,0); Caption(Cap_NastrOffset0,1); Caption(Cap_0mmg,2); Caption(Menu_Write_Next,7);
       PrintPar("dP= ", 3, 2, dPress_1); PrintPar("P=  ", 5, 2, pressure[1] + dPt_1);
	     if (EnterPressed()) {
                   dPress_1 = pressure[1] + dPress_1 + dPt_1;
                   EEPROM.put(dPress_1_EAdr,dPress_1);
                   Rec = 0;
                   BaseTemp_1=temperature[1]; EEPROM.put(BaseTemp_1_EAdr,BaseTemp_1);
                   return;}
        break;
      case 2:
	     Caption(Cap_MPX5010DP,0); Caption(Cap_NastrBasADS,1); Caption(Cap_0mmg,2); Caption(Menu_Write_Next,7);
       PrintPar("ADS ", 3, 0, ADSt); PrintPar("ADSb", 5, 0, PressureBaseADS);
       if (EnterPressed()) {
                   PressureBaseADS = ADSt; // По нажатию BtnEnter запись АДС
                   EEPROM.put(PressureBaseADS_EAdr,PressureBaseADS);
                   Rec = 0;
                   BaseTemp_2=Temp[6]; EEPROM.put(BaseTemp_2_EAdr,BaseTemp_2);
                   return;} 
        break;
      case 3: 
       Caption(Cap_HX710B,0); Caption(Cap_NastrOffset0,1); Caption(Cap_0mmg,2); Caption(Menu_Write_Next,7);
       PrintPar("dP= ", 3, 2, dPress_3); PrintPar("P=  ", 5, 2, pressure[3] + dPt_3);
       if (EnterPressed()) {
                   dPress_3 = pressure[3] + dPress_3 + dPt_3;
                   EEPROM.put(dPress_3_EAdr,dPress_3);
                   Rec = 0;
                   BaseTemp_3=Temp[6]; EEPROM.put(BaseTemp_3_EAdr,BaseTemp_3);
                   return;}
    }
  } Select(); break; 
  case 6: {                             // Экран для настройки коэффициента термокомпенсации датчика давления
    switch (Pressure_enable[0]) {
     case 1:   //Для датчика 1
       Caption(Cap_XGZP6897D,0); Caption(Cap_NastrKtk,1); Caption(Cap_Burn_P_36_6,2); Caption(Menu_Write_Next_PgUp_PgDn,7);
       InputPar(KTemp_1, 0.01);
       PrintPar("Ktк=", 3, 2, KTemp_1); PrintPar("P=  ", 5, 2, pressure[1]);
       if (EnterPressed()) {
                   EEPROM.put(KTemp_1_EAdr,KTemp_1);  
                   Rec = 0;
                   }
       break;
     case 2:         //Для датчика на 8 канале АЦП
       Caption(Cap_MPX5010DP,0); Caption(Cap_NastrKtk,1); Caption(Cap_Burn_P_36_6,2); Caption(Menu_Write_Next_PgUp_PgDn,7);
       InputPar(KTemp_2, 0.01);
       PrintPar("Ktк=", 3, 2, KTemp_2); PrintPar("P=  ", 5, 2, pressure[2]);
       if (EnterPressed()) {
                   EEPROM.put(KTemp_2_EAdr,KTemp_2);  
                   Rec = 0;
                   }
       break;
     case 3:   //Для датчика на АЦП HX710B
       Caption(Cap_HX710B,0); Caption(Cap_NastrKtk,1); Caption(Cap_Burn_P_36_6,2); Caption(Menu_Write_Next_PgUp_PgDn,7);
       InputPar(KTemp_3, 0.01); 
       PrintPar("Ktк=", 3, 2, KTemp_3); PrintPar("P=  ", 5, 2, pressure[3]);
       if (EnterPressed()) {
                   EEPROM.put(KTemp_3_EAdr,KTemp_3);
                   Rec = 0;
                   }
    }
  } Select(); break;//  далее по Select
  case 7: {                             // Экран настройка характеристик термисторов запрос рассчета B25
       Caption(Cap_NastrNTC,0); Caption(Cap_RaschB25,2); Caption(Cap_NextQ,6); 
       B25t=B25;
       EnterJump(9); // переход к B25/100  
  } if (Select()) DispMode=14; //  переход к NTC
    break; 
  case 9: {                             // Экран настройка характеристик термисторов настройка T25
       Caption(Cap_NastrNTC,0); Caption(Cap_RaschB25,1); Caption(Menu_Next,6); Caption(Menu_PgUp_PgDn,7);
       InputPar(T25, 0.1);
       PrintPar("T25=", 3, 1, T25); 
  } Select(); break;
  case 10:  {                           // Экран настройка характеристик термисторов настройка R25
       Caption(Cap_NastrNTC,0); Caption(Cap_RaschB25,1); Caption(Menu_Next,6); Caption(Menu_PgUp_PgDn,7);
       InputPar(R25, 0.01);
       PrintPar("R25=", 3, 2, R25); 
  } Select();  break;
  case 11:  {                           // Экран настройка характеристик термисторов настройка T100
       Caption(Cap_NastrNTC,0); Caption(Cap_RaschB25,1); Caption(Menu_Next,6); Caption(Menu_PgUp_PgDn,7);
       InputPar(T100, 0.1);
       PrintPar("T100", 3, 1, T100);
  } Select();  break;
  case 12:  {                           // Экран настройка характеристик термисторов настройка R100
       B25t=round((log(R25*1000)-log(R100*1000))/(1/(T25+273.15)-1/(T100+273.15)));      
       Caption(Cap_NastrNTC,0); Caption(Cap_RaschB25,1); Caption(Menu_Next,6); Caption(Menu_PgUp_PgDn,7);
       InputPar(R100, 0.001);
       PrintPar("R100", 2, 3, R100); PrintPar("В25 ", 4, 0, B25t);
  }  Select(); break;
  case 13:  {                           // Экран Запрос на сохранение В25
         Caption(Cap_NastrNTC,0); Caption(Cap_B25Rasch_Current,1); Caption(Cap_SaveQ,2); Caption(Menu_Write_Next_PgUp_PgDn,7);
         InputPar(B25t, 1);
         PrintPar("B25r", 3, 0, B25t); PrintPar("В25 ", 5, 0, B25);
         if (EnterPressed()) {B25 = B25t; EEPROM.put(B25_EAdr,B25); Rec = 0;}
  } Select();  break;
  case 14:  {                           // Экран настройка характеристик термисторов запрос рассчета кривой 
       Caption(Cap_NastrNTC,0); Caption(Cap_NextCalc,4); Caption(Cap_NextQ,6); 
       EnterJump(16); // переход к NTC
  } if (Select()) DispMode=21; //  переход к попугаю
    break; 
  case 16:  {                           // Экран настройка характеристик термисторов U3.3 
       Caption(Cap_NastrNTC,0); Caption(Cap_U33,1); Caption(Menu_Write_Next,6); Caption(Menu_PgUp_PgDn,7);
       InputPar(U33, 0.01);
       PrintPar("U33=", 3, 2, U33);
       if (EnterPressed()) {EEPROM.put(U33_EAdr,U33); Rec = 0;}
  } Select(); break;
  case 17:  {                           // Экран настройка характеристик термисторов Uref
       Caption(Cap_NastrNTC,0); Caption(Cap_Uref,1); Caption(Menu_Write_Next,6); Caption(Menu_PgUp_PgDn,7);
       InputPar(Uref, 0.001);
       PrintPar("Urf=", 3, 3, Uref);
       if (EnterPressed()) {EEPROM.put(Uref_EAdr,Uref); Rec = 0;}
  } Select(); break;
  case 18:  {                           // Экран настройка характеристик термисторов R10 
       Caption(Cap_NastrNTC,0); Caption(Cap_R_10kOm,1); Caption(Menu_Write_Next,6); Caption(Menu_PgUp_PgDn,7);
       InputPar(R10, 0.001);
       PrintPar("R10=", 3, 3, R10);
       if (EnterPressed()) {EEPROM.put(R10_EAdr,R10); Rec = 0;}
  } Select(); break;
  case 19:  {                           // Экран настройка характеристик термисторов R62
       Caption(Cap_NastrNTC,0); Caption(Cap_R_62kOm,1); Caption(Menu_Write_Next,6); Caption(Menu_PgUp_PgDn,7);
       InputPar(R62, 0.001);
       PrintPar("R62=", 3, 3, R62);
       if (EnterPressed()) {EEPROM.put(R62_EAdr,R62);  Rec = 0;}
  } Select(); break;
  case 20:  {                           // Экран настройка характеристик термисторов запрос сохранения результатов расчёта 
       Caption(Cap_NastrNTC,0); Caption(Cap_SaveQ,1);
       InputPar(Ttemp, 1);
       if (Ttemp>125) Ttemp=-25; if (Ttemp<-25) Ttemp=125;
       PrintPar("T=  ", 2, 1, Ttemp); PrintPar("ADSr", 4, 0, (float)T_to_ADS(Ttemp)); PrintPar("ADS ", 6, 0, (float)m_adc[static_cast<int>(round(Ttemp)+25)]);
       if (EnterPressed()) { ADS_Construct(); EEPROM.put(m_adc_EAdr,m_adc);  Rec = 0;};
  } Select();  break;  
  case 21:  {                           // Экран настройка электронного попугая запрос начала 
       Caption(Cap_NastrEP,0); Caption(Cap_NextQ,6); 
       EnterJump(23); // переход к попугаю 
  } if (Select()) DispMode=26;  // переход в сброс EEPROM
    break; 
  case 23:  {                           // Экран настройка электронного попугая номер датчика давления
       Caption(Cap_NastrEP,0); Caption(Cap_N_DP,1); Caption(Menu_Write_Next,7);
       if (digitalRead(BtnUp) == LOW)  N_dPressureAlc++; //!!!!!!!!!!!!!!!!!!!!!!!!!!!!надо переделать
       if (N_dPressureAlc>3) N_dPressureAlc=0; 
       if (!Pressure_enable[N_dPressureAlc]) N_dPressureAlc++; //.......!!!!!!!!!!!!!!
       PrintPar("   N", 4, 0, N_dPressureAlc); 
       if (EnterPressed()) { EEPROM.put(N_dPressAlc_EAdr,N_dPressureAlc); Rec = 0;};
  } Select(); break;
  case 24:  {                           // Экран настройка электронного попугая включение/отключение термокоррекции
       Caption(Cap_NastrEP,0); Caption(Cap_K_cor_po_t,1); Caption(Menu_Write_Next,7);
       InputPar(k_Alc_T, 0.3);
       if (k_Alc_T<-0.1) k_Alc_T=0.3;
       if (k_Alc_T>0.4) k_Alc_T=0.0;
       PrintPar("  Kt", 4, 1, k_Alc_T);
       if (EnterPressed()) {EEPROM.put(k_Alc_T_EAdr,k_Alc_T); Rec = 0;}
  } Select(); break;  
  case 25:  {                           // Экран настройка электронного попугая калибровка с сортировкой
       Caption(Cap_NastrEP,0); Caption(Cap_Fill_Sort,1); Caption(Menu_Write_Next_PgUp_PgDn,7);
       InputPar(Alc_tar, 1);
       if (Alc_tar<0) Alc_tar=100;
       if (Alc_tar>100) Alc_tar=0;
       PrintPar("Sor%", 2, 1, Alc_tar);
       if (pressure[N_dPressureAlc]>0.2) {
         PrintPar("kG/P", 5, 1, (Alc_to_G((uint16_t)(Alc_tar*100))/pressure[N_dPressureAlc])); //K_alc
         if (EnterPressed()) { 
          k_Alc=Alc_to_G((uint16_t)(Alc_tar*100))/pressure[N_dPressureAlc]; EEPROM.put(k_Alc_EAdr,k_Alc);  Rec = 0;}
          } 
        else LD.printString_12x16(F(" Нет давл. "), 0, 5); 
  } Select();  break;  
  case 26:  {                           // Сохранить настройки?
   Caption(Cap_EEPROM_1,2); Caption(Menu_Yes_Next,6);
   if (EnterPressed()) { EEPROM.commit(); EEPROM.end(); } // Save EEPROM
  } if (Select()) DispMode=27;  // переход в начало
    break;   
  case 27:  {                           // Сбросить настройки на дефолтные?
   Caption(Cap_EEPROM_0,2); Caption(Menu_Yes_Next,6);
   if (EnterPressed()) { EEPROM[0]=EEPROM[0]+1; EEPROM_Init(); EEPROM.end(); ESP.reset(); } // Soft reset
  } if (Select()) DispMode=0;  // переход в начало
    break; 
 }
  #endif
}