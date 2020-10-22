//**************************************************************************************************************
// Логика работы ректификационной колонны
//**************************************************************************************************************
void samovar_start();
void set_menu_screen(byte param);
void samovar_reset();
void create_data();

//Получаем объем отбора
float get_liguid_volume_by_step(int StepperSpeed){
  float retval = 0;
  if (SamSetup.StepperStepMl > 0) retval = (float)StepperSpeed / SamSetup.StepperStepMl;
  return retval;
}

//Получаем скорость отбора
float get_liguid_rate_by_step(int StepperSpeed){
  return get_liguid_volume_by_step(StepperSpeed) * 3.6;
}

float get_speed_from_rate(float volume_per_hour){
  float v;
  ActualVolumePerHour = volume_per_hour;
  v = (float)SamSetup.StepperStepMl * (float)volume_per_hour / 3.6;
  if (v < 1) v = 1;
  return v;
}

int get_liquid_volume(){
  return get_liguid_volume_by_step(stepper.getCurrent());
}

void withdrawal(void){
  //Определяем, что необходимо сменить режим работы
  CurrrentStepps = stepper.getCurrent();
  if (TargetStepps > 0){
    WthdrwlProgress = CurrrentStepps * 100 / TargetStepps;
  } else {
    WthdrwlProgress = 0;
  }
  if (TargetStepps == CurrrentStepps && TargetStepps !=0 && (startval == 1 || startval == 3 || startval == 10)){
    samovar_start();
    if (FullAuto && startval != 0) {
      samovar_start();
    }
  }
}

void set_power(bool On){
  PowerOn = On;
  if (On) {
      digitalWrite(RELE_CHANNEL1, LOW);
      set_menu_screen(2);
      power_text_ptr = (char*)"OFF";
  } else {
      samovar_reset();
      digitalWrite(RELE_CHANNEL1, HIGH);
      set_menu_screen(3);
      power_text_ptr = (char*)"ON";
  }
}

void pump_calibrate(int stpspeed){
  if (startval != 0) return;
  if (stpspeed == 0){
    //Сохраняем полученное значение калибровки
    SamSetup.StepperStepMl = round((float)stepper.getCurrent() / 100);
    stepper.brake();
    stepper.disable();
    EEPROM.put(0, SamSetup);
    EEPROM.commit();
  } else {
    //крутим двигатель, пока не остановят
    stepper.setCurrent(0);
    stepper.setMaxSpeed(stpspeed);
    stepper.setTarget(999999999);
  }
}

void start_manual(){
  startval = 10;
  stepper.setMaxSpeed(get_speed_from_rate(ManualLiquidRate));
  if (!StepperMoving){
    create_data();                    //создаем файл с данными
    stepper.setCurrent(0);
    TargetStepps = ManualVolume * SamSetup.StepperStepMl;
    stepper.setTarget(TargetStepps);
  }
}

/*   
//***********************************************************************************************************************
// Управляем клапаном отбора по температуре пара перед дефлегматором
//***********************************************************************************************************************
  if(SetTemp1 != 0)                                           // если не ручной режим управления клапаном
  { 
    if (digitalRead(valve) == true)                           // если клапан закрыт
     { 
       if(millis()- paus >= Delay1 * 1000)                   // если время задержки вышло (Delay1 задаётся в секундах),
        { 
          if (SteamTemp < SetTemp1)                           // если температура ниже уставки
           { 
             digitalWrite(valve, LOW);                        // включаем клапан (лог. 0)
             Serial.println("Valve is OPENED automatically");
           }
          else paus = millis();                              // если температура всё ещё выше уставки, заводим таймер снова
        }
     }          
    else                                                      // если клапан открыт
       { 
         if (SteamTemp >= SetTemp1)                           // если температура выше уставки,
          { 
            digitalWrite(valve, HIGH );                       // выключаем клапан отбора
            Serial.println("Valve is CLOSED automatically");
            paus = millis();                                 // заводим таймер
          }
       }
  }

//***************************************************************************************************************************
// Управляем клапаном отбора по температуре пара в царге на 2/3 колонны
//***************************************************************************************************************************
  if(SetTemp2 != 0)                                           // если не ручной режим управления клапаном
  { 
    if (digitalRead(valve) == true)                           // если клапан закрыт
     { 
       if(millis()- paus >= Delay2 * 1000)                   // если время задержки вышло (Delay2 задаётся в секундах),
        { 
          if (PipeTemp < SetTemp2)                            // если температура ниже уставки
           { 
             digitalWrite(valve, LOW);                        // включаем клапан (лог. 0)
             Serial.println("Valve is OPENED automatically");
           }
          else paus = millis();                              // если температура всё ещё выше уставки, заводим таймер снова
        }
     }          
    else                                                      // если клапан открыт
       { 
         if (PipeTemp >= SetTemp2)                            // если температура выше уставки,
          { 
            digitalWrite(valve, HIGH );                       // выключаем клапан отбора
            Serial.println("Valve is CLOSED automatically");
            paus = millis();                                 // заводим таймер
          }
       }
  }
*/
