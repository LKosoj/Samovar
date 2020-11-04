#ifdef SAMOVAR_USE_BLYNK
//#define BLYNK_PRINT Serial

#include <BlynkSimpleEsp32.h>
#endif
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
  if (TargetStepps == CurrrentStepps && TargetStepps !=0 && (startval == 1 || startval == 2 || startval == 10)){
    samovar_start();
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
  Serial.println("startval=");
  Serial.println(startval);
  if (startval != 0 && startval != 100) {
    return;
  }
  Serial.println("stpspeed=");
  Serial.println(stpspeed);
  
  if (stpspeed == 0){
    startval = 0;
    //Сохраняем полученное значение калибровки
    SamSetup.StepperStepMl = round((float)stepper.getCurrent() / 100);
    stepper.brake();
    stepper.disable();
    EEPROM.put(0, SamSetup);
    EEPROM.commit();
  } else {
    startval = 100;
    //крутим двигатель, пока не остановят
    if (!stepper.getState()) stepper.setCurrent(0);
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

void pause_withdrawal(bool Pause){
  if (!stepper.getState() && !PauseOn) return;
  PauseOn = Pause;
  if (Pause) {
    //RemainingDistance = stepper.getTarget() - stepper.getCurrent();
    TargetStepps = stepper.getTarget();
    CurrrentStepps = stepper.getCurrent();
    CurrrentStepperSpeed = stepper.getSpeed();
    stepper.brake();
    stepper.disable();
  }
  else {
    stepper.setMaxSpeed(CurrrentStepperSpeed);
    stepper.setCurrent(CurrrentStepps);
    stepper.setTarget(TargetStepps);
  }
}

String get_Samovar_Status(){
  if (!PowerOn) {
    SamovarStatus = "Выключено";
    SamovarStatusInt = 0;
  } else if (PowerOn && startval == 1 && !PauseOn) {
    SamovarStatus = "Работает программа №" + String(ProgramNum + 1);
    SamovarStatusInt = 10;
  } else if (PowerOn && startval == 2) {
    SamovarStatus = "Выполнение программ отбора закончено";
    SamovarStatusInt = 10;
  } else if (PowerOn && startval == 100) {
    SamovarStatus = "Калибровка";
    SamovarStatusInt = 20;
  } else if (PowerOn && stepper.getState() && startval == 10 && !PauseOn) {
    SamovarStatus = "Отбор в ручном режиме";
    SamovarStatusInt = 30;
  } else if (PauseOn) {
    SamovarStatus = "Пауза";
    SamovarStatusInt = 40;
  } else if (PowerOn && startval == 0 && !stepper.getState()) {
    SamovarStatus = "Разгон колонны/работа на себя";
    SamovarStatusInt = 50;
  }  
  return SamovarStatus;
}

void set_capacity(byte cap){
  capacity_num = cap;
  int p = ((int)cap*SERVO_ANGLE)/(int)CAPACITY_NUM + servoDelta[cap];
  servo.write(p);
}

void next_capacity(void){
  set_capacity(capacity_num+1);
}

void set_program(String WProgram){
  char c[500];
  WProgram.toCharArray(c,500);
  char *pair = strtok(c, ";");
  int i=0;
  while(pair != NULL and i < CAPACITY_NUM){
    program[i].WType = pair;
    pair = strtok(NULL, ";");
    program[i].Volume = atoi(pair);
    pair = strtok(NULL, ";");
    program[i].Speed = atof(pair);
    pair = strtok(NULL, ";");
    program[i].capacity_num = atoi(pair);
    pair = strtok(NULL, "\n");
    program[i].Temp = atof(pair);
    i++;
    ProgramLen = i;
    pair = strtok(NULL, ";");
    if (!pair and i < CAPACITY_NUM) {
      program[i].WType = "";
    }
  }
}

String get_program(int s){
  String Str = "";
  int k = CAPACITY_NUM;
  if (s == CAPACITY_NUM) {
    s = 0;
  } else {
    k = s + 1;
  }
  for (int i = s; i < k; i++){
    if (program[i].WType == "") {
      i = CAPACITY_NUM + 1;
    } else {
      Str+= program[i].WType + ";";
      Str+= (String)program[i].Volume + ";";
      Str+= (String)program[i].Speed + ";";
      Str+= (String)program[i].capacity_num + ";";
      Str+= (String)program[i].Temp + "\n";
    }
  }
  return Str;
}

void run_program(byte num){
   if (num == CAPACITY_NUM){
    ProgramNum = 0;
    if (fileToAppend) {
      fileToAppend.close();
    }
    stepper.brake();
    stepper.disable();
    stepper.setCurrent(0);
    stepper.setTarget(0);
    set_capacity(0);
   } else {
    set_capacity(program[num].capacity_num);
    stepper.setMaxSpeed(get_speed_from_rate(program[num].Speed));
    TargetStepps = program[num].Volume * SamSetup.StepperStepMl;
    ManualVolume = program[num].Volume;
    ManualLiquidRate = program[num].Speed;
    stepper.setCurrent(0);
    stepper.setTarget(TargetStepps);
    ActualVolumePerHour = program[num].Speed;
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
