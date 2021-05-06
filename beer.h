void beer_finish();
void set_heater(bool state);

void beer_proc() {
  return;
}

void IRAM_ATTR beer_finish() {
  if (fileToAppend) {
    fileToAppend.close();
  }
  Msg = "Beer finished";
#ifdef SAMOVAR_USE_BLYNK
  //Если используется Blynk - пишем оператору
  Blynk.notify("{DEVICE_NAME} Beer finished");
#endif
  set_power(false);
  reset_sensor_counter();
}

void IRAM_ATTR check_alarm_beer() {

}

void set_heater_state(float setpoint, float temp){
  if (setpoint - temp > HEAT_DELTA){
#ifdef SAMOVAR_USE_POWER
    delay(200);
    set_power_mode(POWER_SPEED_MODE);
#else
    current_power_mode = POWER_WORK_MODE;
    digitalWrite(RELE_CHANNEL1, !SamSetup.rele1);
    digitalWrite(RELE_CHANNEL4, SamSetup.rele4);
#endif
  } else {
    regulator.setpoint = setpoint;
    regulator.input = temp;
    set_heater(regulator.getResult());
  }
}

void set_heater(bool state){
  if (state){
#ifdef SAMOVAR_USE_POWER
    if (current_power_mode != POWER_WORK_MODE) {
      delay(200);
      set_power_mode(POWER_WORK_MODE);
      delay(800);
    }
    //Устанавливаем заданное напряжение
    set_current_power(HEATPOWER);
#else
    current_power_mode = POWER_WORK_MODE;
    digitalWrite(RELE_CHANNEL1, !SamSetup.rele1);
    digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);
#endif
  } else {
#ifdef SAMOVAR_USE_POWER
    if (current_power_mode != POWER_WORK_MODE) {
      delay(200);
      set_power_mode(POWER_WORK_MODE);
      delay(800);
    }
    //Устанавливаем заданное напряжение
    set_current_power(0);
#else
    current_power_mode = POWER_WORK_MODE;
    digitalWrite(RELE_CHANNEL1, SamSetup.rele1);
#endif
  }
}

void set_beer_program(String WProgram){
  //H - heat, P - pause, B - boil, Z - zoomer
  char c[500];
  WProgram.toCharArray(c, 500);
  char *pair = strtok(c, ";");
  int i = 0;
  while (pair != NULL and i < CAPACITY_NUM * 2) {
    program[i].WType = pair;
    pair = strtok(NULL, ";");
    program[i].Temp = atof(pair);
    pair = strtok(NULL, "\n");
    program[i].Speed = atof(pair); //Time
    i++;
    ProgramLen = i;
    pair = strtok(NULL, ";");
    if ((!pair || pair == NULL || pair[0] == 13) and i < CAPACITY_NUM * 2) {
      program[i].WType = "";
      break;
    }
  }
}
