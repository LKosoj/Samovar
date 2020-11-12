#ifdef SAMOVAR_USE_BLYNK
//#define BLYNK_PRINT Serial

#include <BlynkSimpleEsp32.h>
#endif
//**************************************************************************************************************
// Логика работы ректификационной колонны
//**************************************************************************************************************
void menu_samovar_start();
void set_menu_screen(byte param);
void samovar_reset();
void create_data();
void pause_withdrawal(bool Pause);
void read_config();
String inline format_float(float v, int d);
float get_temp_by_pressure(float start_pressure, float start_temp, float current_pressure);

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
  if (program_Pause){
    if (millis() >= t_min) {
      t_min = 0;
      menu_samovar_start();
    }
    return;
  }
  CurrrentStepps = stepper.getCurrent();
  if (TargetStepps > 0){
    WthdrwlProgress = CurrrentStepps * 100 / TargetStepps;
  } else {
    WthdrwlProgress = 0;
  }
  if (TargetStepps == CurrrentStepps && TargetStepps !=0 && (startval == 1 || startval == 2)){
    menu_samovar_start();
  }

  float c_temp; //стартовая температура отбора тела с учетом корректировки от давления или без
  c_temp = get_temp_by_pressure(SteamSensor.Start_Pressure, SteamSensor.BodyTemp, bme_pressure);
  
  //Возвращаем колонну в стабильное состояние, если работает программа отбора тела и температура пара вышла за пределы
  if (program[ProgramNum].WType == "B" && SteamSensor.avgTemp >= c_temp + SteamSensor.SetTemp){
    //ставим отбор на паузу, если еще не стоит, и задаем время ожидания
    if (!PauseOn && !program_Wait){
      program_Wait = true;
      pause_withdrawal(true);
      t_min = millis() + SteamSensor.Delay * 1000;
    }
    // если время вышло, еще раз пытаемся дождаться
    if (millis() >= t_min) t_min = millis() + SteamSensor.Delay * 1000;
  } else if (program[ProgramNum].WType == "B" && SteamSensor.avgTemp < SteamSensor.BodyTemp + SteamSensor.SetTemp && millis() >= t_min && t_min > 0){
    //продолжаем отбор
    t_min = 0; 
    program_Wait = false;
    pause_withdrawal(false);
  }

  //Возвращаем колонну в стабильное состояние, если работает программа отбора тела и температура в колонне вышла за пределы
  if (program[ProgramNum].WType == "B" && PipeSensor.avgTemp >= PipeSensor.BodyTemp + PipeSensor.SetTemp){
    //ставим отбор на паузу, если еще не стоит, и задаем время ожидания
    if (!PauseOn && !program_Wait){
      program_Wait = true;
      pause_withdrawal(true);
      t_min = millis() + PipeSensor.Delay * 1000;
    }
    // если время вышло, еще раз пытаемся дождаться
    if (millis() >= t_min) t_min = millis() + PipeSensor.Delay * 1000;
  } else if (program[ProgramNum].WType == "B" && PipeSensor.avgTemp < PipeSensor.BodyTemp + PipeSensor.SetTemp && millis() >= t_min && t_min > 0){
    //продолжаем отбор
    t_min = 0; 
    program_Wait = false;
    pause_withdrawal(false);
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
    read_config;
  } else {
    startval = 100;
    //крутим двигатель, пока не остановят
    if (!stepper.getState()) stepper.setCurrent(0);
    stepper.setMaxSpeed(stpspeed);
    stepper.setTarget(999999999);
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
  } else if (PowerOn && startval == 1 && !PauseOn && !program_Wait) {
    SamovarStatus = "Работает программа №" + String(ProgramNum + 1);
    SamovarStatusInt = 10;
  } else if (PowerOn && startval == 1 && program_Wait) {
    int s = 0;
    if (t_min > (millis() + 10)){
      s = (t_min - millis())/1000;
    }
    SamovarStatus = "Программа №" + String(ProgramNum + 1) + " на паузе. Ожидается возврат колонны к заданным параметрам. Осталось " + (String)s + " сек.";
    SamovarStatusInt = 15;
  } else if (PowerOn && startval == 2) {
    SamovarStatus = "Выполнение программ отбора закончено";
    SamovarStatusInt = 20;
  } else if (PowerOn && startval == 100) {
    SamovarStatus = "Калибровка";
    SamovarStatusInt = 30;
  } else if (PauseOn) {
    SamovarStatus = "Пауза";
    SamovarStatusInt = 40;
  } else if (PowerOn && startval == 0 && !stepper.getState()) {
    SamovarStatus = "Разгон колонны/работа на себя";
    SamovarStatusInt = 50;
  }
  if (SteamSensor.BodyTemp > 0) SamovarStatus+=" Температура отбора тела:" + format_float(get_temp_by_pressure(SteamSensor.Start_Pressure, SteamSensor.BodyTemp, bme_pressure),3);
  
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
  while(pair != NULL and i < CAPACITY_NUM * 2){
    program[i].WType = pair;
    pair = strtok(NULL, ";");
    program[i].Volume = atoi(pair);
    pair = strtok(NULL, ";");
    program[i].Speed = atof(pair);
    pair = strtok(NULL, ";");
    program[i].capacity_num = atoi(pair);
    pair = strtok(NULL, ";");
    program[i].Temp = atof(pair);
    pair = strtok(NULL, "\n");
    program[i].Power = atof(pair);
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
  int k = CAPACITY_NUM * 2;
  if (s == CAPACITY_NUM * 2) {
    s = 0;
  } else {
    k = s + 1;
  }
  for (int i = s; i < k; i++){
    if (program[i].WType == "") {
      i = CAPACITY_NUM * 2 + 1;
    } else {
      Str+= program[i].WType + ";";
      Str+= (String)program[i].Volume + ";";
      Str+= (String)program[i].Speed + ";";
      Str+= (String)program[i].capacity_num + ";";
      Str+= (String)program[i].Temp + ";";
      Str+= (String)program[i].Power + "\n";
    }
  }
  return Str;
}

void run_program(byte num){
   t_min = 0;
   program_Pause = false;
   if (num == CAPACITY_NUM * 2){
    //если num = CAPACITY_NUM * 2 значит мы достигли финала (или отбор сброшен принудительно), завершаем отбор
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
    if (program[num].WType == "H" || program[num].WType == "B"){
      //устанавливаем параметры для текущей программы отбора
      set_capacity(program[num].capacity_num);
      stepper.setMaxSpeed(get_speed_from_rate(program[num].Speed));
      TargetStepps = program[num].Volume * SamSetup.StepperStepMl;
      stepper.setCurrent(0);
      stepper.setTarget(TargetStepps);
      ActualVolumePerHour = program[num].Speed;
      SteamSensor.BodyTemp = program[num].Temp;
      //Происходит магия. Если у первой программы отбора тела не задана температура, при которой начинать отбор, считаем, что она равна текущей
      //Для этого колонна должна после отбора голов поработать несколько минут на паузе
      //(для этого после программы отбора голов надо задать программу с типом P (латинская) и указать время стабилизации колонны в минутах в program[num].Volume)
      //Итак, текущая температура - это температура, которой Самовар будет придерживаться во время всех программ отобора тела.
      //Если она будет выходить за пределы больше заданных в настройках, отбор будет ставиться на паузу, и продолжится после возвращения температуры в колонне к заданному значению.
      if (program[num].WType == "B" && SteamSensor.BodyTemp == 0) {
        SteamSensor.BodyTemp = SteamSensor.avgTemp;
        PipeSensor.BodyTemp = PipeSensor.avgTemp;
        WaterSensor.BodyTemp = WaterSensor.avgTemp;
        TankSensor.BodyTemp = TankSensor.avgTemp;
        SteamSensor.Start_Pressure = bme_pressure;
      }
    } else if (program[num].WType == "P"){
      //устанавливаем параметры ожидания для программы паузы. Время в секундах задано в program[num].Volume
      t_min = millis() + program[num].Volume * 1000;
      program_Pause = true;
      stepper.setSpeed(-1);
      stepper.setMaxSpeed(-1);
      stepper.brake();
      stepper.disable();
      stepper.setCurrent(0);
      stepper.setTarget(0);
    }
   }
}

//функция корректировки температуры кипения спирта в зависимости от давления
float get_temp_by_pressure(float start_pressure, float start_temp, float current_pressure){
  //скорректированная температура кипения спирта при текущем давлении
  float c_temp;

#ifdef USE_PRESSURE_CORRECT
  //идеальная температура кипения спирта при текущем давлении
  float i_temp;
  //температурная дельта
  float d_temp;
  
  i_temp = current_pressure * 0.038 + 49.27;
  d_temp = start_temp - start_pressure * 0.038 - 49.27; //учитываем поправку на погрешность измерения датчиков
  c_temp = i_temp + d_temp; // получаем текущую температуру кипения при переданном давлении с учетом поправки 
#else
  //Используем сохраненную температуру отбора тела без корректировки
  c_temp = start_temp;
#endif

  return c_temp;
}
