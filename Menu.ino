LiquidLine lql_back_line(0, 0, "/Back");
LiquidLine lql_time(0, 3, timestr);

LiquidLine welcome_line1(0, 0, welcomeStr1);
LiquidLine welcome_line2(0, 1, welcomeStr2);
LiquidLine welcome_line3(0, 2, welcomeStr3);
LiquidLine welcome_line4(0, 3, welcomeStr4);
LiquidScreen welcome_screen(welcome_line1, welcome_line2, welcome_line3, welcome_line4);

LiquidLine lql_steam_temp(0, 0, "Steam temp: ", SteamSensor.avgTemp);
LiquidLine lql_pipe_temp(0, 1, "Pipe temp: ", PipeSensor.avgTemp);
LiquidLine lql_water_temp(0, 2, "Water temp: ", WaterSensor.avgTemp);
LiquidScreen main_screen(lql_steam_temp, lql_pipe_temp, lql_water_temp, lql_time);

LiquidLine lql_tank_temp(0, 0, "Tank temp: ", TankSensor.avgTemp);
LiquidLine lql_atm(0, 1, "Atm: ", bme_pressure);
//LiquidLine lql_ip(0, 2, "IP: ", ipstr);
LiquidLine lql_w_progress(0, 2, "Progress: ", WthdrwlProgress);
LiquidScreen main_screen1(lql_tank_temp, lql_atm, lql_w_progress, lql_time);

LiquidLine lql_start(0, 0, ">Start: ", startval_text);
//LiquidLine lql_stepper_speed(0, 1, ">Stepper spd: ", CurrrentStepperSpeed);
LiquidLine lql_act_vlm_perh(0, 1, ">Speed l/h: ", ActualVolumePerHour);
LiquidLine lql_reset(0, 2, ">Reset withdrawal:");
LiquidScreen main_screen2(lql_start, lql_act_vlm_perh, lql_reset, lql_time);

LiquidLine lql_volume(0, 0, ">Volume: ", ManualVolume);
LiquidLine lql_manual_stp_spd(0, 1, ">Speed ml/h: ", ManualLiquidRate);
LiquidLine lql_start_manual(0, 2, ">Start manual:");
LiquidScreen manual_screen(lql_volume, lql_manual_stp_spd, lql_start_manual, lql_time);


LiquidLine lql_head_volume(0, 0, ">Head vol, l: ", SamSetup.HeadVolume);
LiquidLine lql_body_volume(0, 1, ">Body vol, l: ", SamSetup.BodyVolume);
LiquidLine lql_setup_liquid_rate_head(0, 2, ">Head vol,l/h:", SamSetup.LiquidRateHead);
LiquidLine lql_setup_liquid_rate_body(0, 3, ">Body vol,l/h:", SamSetup.LiquidRateBody);
LiquidScreen main_screen3(lql_head_volume, lql_body_volume, lql_setup_liquid_rate_head, lql_setup_liquid_rate_body);

LiquidLine lql_get_power(0, 0, ">Get power ", power_text_ptr);
LiquidLine lql_setup(0, 1, "/Setup");
LiquidScreen main_screen4(lql_get_power, lql_setup, lql_time);

LiquidMenu main_menu1(lcd);

LiquidLine lql_setup_steam_temp(0, 0, "^Steam temp: ", SamSetup.DeltaSteamTemp);
LiquidLine lql_setup_pipe_temp(0, 1, "^Pipe temp: ", SamSetup.DeltaPipeTemp);
LiquidLine lql_setup_water_temp(0, 2, "^Water temp: ", SamSetup.DeltaWaterTemp);
LiquidLine lql_setup_tank_temp(0, 3, "^Tank temp: ", SamSetup.DeltaTankTemp);
LiquidScreen setup_temp_screen(lql_setup_steam_temp, lql_setup_pipe_temp, lql_setup_water_temp, lql_setup_tank_temp);

LiquidLine lql_setup_set_steam_temp(0, 0, "^Set Steam t: ", SamSetup.SetSteamTemp);
LiquidLine lql_setup_set_pipe_temp(0, 1, "^Set Pipe t: ", SamSetup.SetPipeTemp);
LiquidLine lql_setup_set_water_temp(0, 2, "^Set Water t: ", SamSetup.SetWaterTemp);
LiquidLine lql_setup_set_tank_temp(0, 3, "^Set Tank t: ", SamSetup.SetTankTemp);
LiquidScreen setup_set_temp_screen(lql_setup_set_steam_temp, lql_setup_set_pipe_temp, lql_setup_set_water_temp, lql_setup_set_tank_temp);

LiquidLine lql_setup_stepper_stepper_step_ml(0, 0, "^Step/ml: ", SamSetup.StepperStepMl);
LiquidLine lql_setup_stepper_calibrate(0, 1, ">Calibrate: ", calibrate_text_ptr);
LiquidScreen setup_stepper_settings(lql_setup_stepper_stepper_step_ml, lql_setup_stepper_calibrate, lql_time);

LiquidScreen setup_back_screen(lql_back_line, lql_time);

//LiquidMenu setup_menu(lcd);


//LiquidSystem menu(main_menu, setup_menu, 1);

void reset_focus(){
  //return;
  do {
    main_menu1.switch_focus();
  } while (main_menu1.is_callable(1));
}

void set_menu_screen(byte param){
  switch (param){
    case 1: //меню установок
      setup_temp_screen.hide(false);
      setup_set_temp_screen.hide(false);
      setup_stepper_settings.hide(false);
      setup_back_screen.hide(false);
      main_screen.hide(true);
      main_screen1.hide(true);
      main_screen2.hide(true);
      main_screen3.hide(false);
      main_screen4.hide(true);
      manual_screen.hide(true);
      //main_menu1.switch_focus();
      main_menu1.change_screen(&main_screen3);
      break;
    case 2:  //основное меню после включения колонны
      setup_set_temp_screen.hide(true);
      setup_temp_screen.hide(true);
      setup_stepper_settings.hide(true);
      setup_back_screen.hide(true);
      main_screen.hide(false);
      main_screen1.hide(false);
      main_screen2.hide(false);
      main_screen3.hide(false);
      main_screen4.hide(false);
      manual_screen.hide(false);
      //main_menu1.switch_focus();
      main_menu1.change_screen(&main_screen);
      break;
    case 3:  //основное меню до включения колонны
      setup_set_temp_screen.hide(true);
      setup_temp_screen.hide(true);
      setup_stepper_settings.hide(true);
      setup_back_screen.hide(true);
      main_screen.hide(false);
      main_screen1.hide(false);
      main_screen2.hide(true);
      main_screen3.hide(true);
      main_screen4.hide(false);
      manual_screen.hide(true);
      //main_menu1.switch_focus();
      main_menu1.change_screen(&main_screen);
      break;
  }
}

void menu_setup()
{ 
  reset_focus();
  set_menu_screen(1);
  
  //menu.change_menu(setup_menu);
}

// Функция обратного вызова будет прикреплена к back_line.
void setup_go_back() 
{
  reset_focus();
  set_menu_screen(2);

  // Сохраняем изменения в память.
  EEPROM.put(0, SamSetup);
  EEPROM.commit();
  // Данная функция ссылается на необходимое меню.
  //main_menu1.change_menu(main_menu);
}

void writeString(String Str, byte num){
  switch (num){
    case 1: 
      Str.toCharArray(welcomeStrArr1,20);
      break;
    case 2: 
      Str.toCharArray(welcomeStrArr2,20);
      break;
    case 3: 
      Str.toCharArray(welcomeStrArr3,20);
      break;
    case 4: 
      Str.toCharArray(welcomeStrArr4,20);
      break;
    case 0: 
      main_menu1.update();
      break;
  }
  main_menu1.softUpdate();
}

void set_delta_steam_temp_up(){
  SamSetup.DeltaSteamTemp+=0.01 * multiplier;
}
void set_delta_steam_temp_down(){
  SamSetup.DeltaSteamTemp-=0.01 * multiplier;
}
void set_delta_pipe_temp_up(){
  SamSetup.DeltaPipeTemp+=0.01 * multiplier;
}
void set_delta_pipe_temp_down(){
  SamSetup.DeltaPipeTemp-=0.01 * multiplier;
}
void set_delta_water_temp_up(){
  SamSetup.DeltaWaterTemp+=0.01 * multiplier;
}
void set_delta_water_temp_down(){
  SamSetup.DeltaWaterTemp-=0.01 * multiplier;
}
void set_delta_tank_temp_up(){
  SamSetup.DeltaTankTemp+=0.01 * multiplier;
}
void set_delta_tank_temp_down(){
  SamSetup.DeltaTankTemp-=0.01 * multiplier;
}

void set_delta_set_steam_temp_up(){
  SamSetup.SetSteamTemp+=0.01 * multiplier;
}
void set_delta_set_steam_temp_down(){
  SamSetup.SetSteamTemp-=0.01 * multiplier;
}
void set_delta_set_pipe_temp_up(){
  SamSetup.SetPipeTemp+=0.01 * multiplier;
}
void set_delta_set_pipe_temp_down(){
  SamSetup.SetPipeTemp-=0.01 * multiplier;
}
void set_delta_set_water_temp_up(){
  SamSetup.SetWaterTemp+=0.01 * multiplier;
}
void set_delta_set_water_temp_down(){
  SamSetup.SetWaterTemp-=0.01 * multiplier;
}
void set_delta_set_tank_temp_up(){
  SamSetup.SetTankTemp+=0.01 * multiplier;
}
void set_delta_set_tank_temp_down(){
  SamSetup.SetTankTemp-=0.01 * multiplier;
}

void stepper_init_head_speed_up(){
  if (SamSetup.LiquidRateHead < VOLUME_MAX_SPEED){
    SamSetup.LiquidRateHead+=0.01 * multiplier;
  }
  else SamSetup.LiquidRateHead = VOLUME_MAX_SPEED;
}
void stepper_init_head_speed_down(){
  if (SamSetup.LiquidRateHead > 0.01){
    SamSetup.LiquidRateHead-=0.01 * multiplier;
  }
  else SamSetup.LiquidRateHead = 0.01;
}
void stepper_init_body_speed_up(){
  if (SamSetup.LiquidRateBody < VOLUME_MAX_SPEED){
    SamSetup.LiquidRateBody+=0.01 * multiplier;
  }
  else SamSetup.LiquidRateBody = VOLUME_MAX_SPEED;
}
void stepper_init_body_speed_down(){
  if (SamSetup.LiquidRateBody > 0.01){
    SamSetup.LiquidRateBody-=0.01 * multiplier;
  }
  else SamSetup.LiquidRateBody = 0.01;
}
void stepper_step_ml_up(){
  SamSetup.StepperStepMl+=1 * multiplier;
}
void stepper_step_ml_down(){
  if (SamSetup.StepperStepMl > 0) {
    SamSetup.StepperStepMl-=1 * multiplier;
  }
  else SamSetup.StepperStepMl = 0;
}
void set_head_volume_up(){
  SamSetup.HeadVolume +=1 * multiplier;
}
void set_head_volume_down(){
  SamSetup.HeadVolume -=1 * multiplier;
}
void set_body_volume_up(){
  SamSetup.BodyVolume +=10 * multiplier;
}
void set_body_volume_down(){
  SamSetup.BodyVolume -=10 * multiplier;
}
void menu_manual_volume_up(){
  ManualVolume +=1 * multiplier;
}
void menu_manual_volume_down(){
  ManualVolume -=1 * multiplier;
}
void menu_manual_stp_spd_up(){
  ManualLiquidRate +=0.01 * multiplier;
  if (startval == 10) stepper.setMaxSpeed(get_speed_from_rate(ManualLiquidRate));
}
void menu_manual_stp_spd_down(){
  ManualLiquidRate -=0.01 * multiplier;
  if (startval == 10) stepper.setMaxSpeed(get_speed_from_rate(ManualLiquidRate));
}
void menu_start_manual(){
  start_manual();
}
void menu_get_power(){
  reset_focus();
  if (!PowerOn){
    set_power(true);
    set_menu_screen(2);
  } else {
    set_power(false);
    set_menu_screen(3);
  }
}
void menu_calibrate(){
  if (startval > 0) return;
  
  int stpspeed;
  if (StepperMoving){
    calibrate_text_ptr = (char*)"Stop";
    stpspeed = 0;
    }
  else {
    calibrate_text_ptr = (char*)"Start";
    stpspeed = STEPPER_MAX_SPEED;
  }
  pump_calibrate(stpspeed);
}

void samovar_start(){
  if (startval == 0) {
    startval = 1;
    startval_text = (char*)"Head";
    stepper.setMaxSpeed(get_speed_from_rate(SamSetup.LiquidRateHead));
    TargetStepps = SamSetup.HeadVolume * SamSetup.StepperStepMl;
    ManualVolume = SamSetup.HeadVolume;
    ManualLiquidRate = SamSetup.LiquidRateHead;
    stepper.setCurrent(0);
    stepper.setTarget(TargetStepps);
    ActualVolumePerHour = SamSetup.LiquidRateHead;
    reset_focus();
    create_data();                    //создаем файл с данными
  }
  else if (startval == 1) {
    startval = 2;
    startval_text = (char*)"Head finish";
    stepper.brake();
    stepper.disable();
    stepper.setCurrent(0);
    stepper.setTarget(0);
    reset_focus();
  }
  else if (startval == 2) {
    startval = 3;
    startval_text = (char*)"Body";
    stepper.setMaxSpeed(get_speed_from_rate(SamSetup.LiquidRateBody));
    TargetStepps = SamSetup.BodyVolume * SamSetup.StepperStepMl;
    ManualVolume = SamSetup.BodyVolume;
    ManualLiquidRate = SamSetup.LiquidRateBody;
    stepper.setCurrent(0);
    stepper.setTarget(TargetStepps);
    ActualVolumePerHour = SamSetup.LiquidRateBody;
    reset_focus();
  }
  else if (startval == 3) {
    startval = 4;
    startval_text = (char*)"Body finish";
    stepper.brake();
    stepper.disable();
    stepper.setCurrent(0);
    stepper.setTarget(0);
    reset_focus();
  }
  else {
    startval = 0;
    startval_text = (char*)"Stoped";
    stepper.brake();
    stepper.disable();
    stepper.setCurrent(0);
    stepper.setTarget(0);
    ActualVolumePerHour = 0;
    reset_focus();
    reset_sensor_counter();
 }
 main_menu1.update();
}

void samovar_reset(){
  startval = 0;
  startval_text = (char*)"Stoped";
  reset_focus();
  reset_sensor_counter();
}

void setupMenu(){
  startval_text = (char*)"Stoped";
  startval = 0;

  ActualVolumePerHour = 0;

  lcd.init();
  lcd.begin(20, 4);
  lcd.backlight();
  lcd.clear();

  //setup_temp_screen.set_displayLineCount(4);
  lql_steam_temp.set_decimalPlaces(2);
  lql_setup_pipe_temp.set_decimalPlaces(2);
  lql_setup_water_temp.set_decimalPlaces(2);
  lql_setup_tank_temp.set_decimalPlaces(2);
  lql_act_vlm_perh.set_decimalPlaces(2);

  // Function to attach functions to LiquidLine objects.
  lql_start.attach_function(1, samovar_start);
  lql_start.attach_function(2, samovar_start);
  lql_reset.attach_function(1, samovar_reset);
  lql_reset.attach_function(2, samovar_reset);
  
  lql_setup.attach_function(1, menu_setup);
  lql_setup.attach_function(2, menu_setup);
  
  lql_setup_steam_temp.attach_function(1, set_delta_steam_temp_up);
  lql_setup_steam_temp.attach_function(2, set_delta_steam_temp_down);
  lql_setup_pipe_temp.attach_function(1, set_delta_pipe_temp_up);
  lql_setup_pipe_temp.attach_function(2, set_delta_pipe_temp_down);
  lql_setup_water_temp.attach_function(1, set_delta_water_temp_up);
  lql_setup_water_temp.attach_function(2, set_delta_water_temp_down);
  lql_setup_tank_temp.attach_function(1, set_delta_tank_temp_up);
  lql_setup_tank_temp.attach_function(2, set_delta_tank_temp_down);

  lql_setup_set_steam_temp.attach_function(1, set_delta_set_steam_temp_up);
  lql_setup_set_steam_temp.attach_function(2, set_delta_set_steam_temp_down);
  lql_setup_set_pipe_temp.attach_function(1, set_delta_set_pipe_temp_up);
  lql_setup_set_pipe_temp.attach_function(2, set_delta_set_pipe_temp_down);
  lql_setup_set_water_temp.attach_function(1, set_delta_set_water_temp_up);
  lql_setup_set_water_temp.attach_function(2, set_delta_set_water_temp_down);
  lql_setup_set_tank_temp.attach_function(1, set_delta_set_tank_temp_up);
  lql_setup_set_tank_temp.attach_function(2, set_delta_set_tank_temp_down);

  lql_head_volume.attach_function(1, set_head_volume_up);
  lql_head_volume.attach_function(2, set_head_volume_down);
  lql_body_volume.attach_function(1, set_body_volume_up);
  lql_body_volume.attach_function(2, set_body_volume_down);

  lql_setup_liquid_rate_head.attach_function(1, stepper_init_head_speed_up);
  lql_setup_liquid_rate_head.attach_function(2, stepper_init_head_speed_down);
  lql_setup_liquid_rate_body.attach_function(1, stepper_init_body_speed_up);
  lql_setup_liquid_rate_body.attach_function(2, stepper_init_body_speed_down);

  lql_setup_stepper_stepper_step_ml.attach_function(1, stepper_step_ml_up);
  lql_setup_stepper_stepper_step_ml.attach_function(2, stepper_step_ml_down);
  lql_setup_stepper_calibrate.attach_function(1, menu_calibrate);
  lql_setup_stepper_calibrate.attach_function(2, menu_calibrate);

  lql_back_line.attach_function(1, setup_go_back);
  lql_back_line.attach_function(2, setup_go_back);

  lql_get_power.attach_function(1, menu_get_power);
  lql_get_power.attach_function(2, menu_get_power);

  lql_volume.attach_function(1, menu_manual_volume_up);
  lql_volume.attach_function(2, menu_manual_volume_down);
  lql_manual_stp_spd.attach_function(1, menu_manual_stp_spd_up);
  lql_manual_stp_spd.attach_function(2, menu_manual_stp_spd_down);
  lql_start_manual.attach_function(1, menu_start_manual);
  lql_start_manual.attach_function(2, menu_start_manual);

  main_menu1.add_screen(welcome_screen);
  main_menu1.add_screen(main_screen);
  main_menu1.add_screen(main_screen1);
  main_menu1.add_screen(main_screen2);
  main_menu1.add_screen(main_screen3);
  main_menu1.add_screen(manual_screen);
  main_menu1.add_screen(main_screen4);

  //setup_menu.add_screen(setup_temp_screen);
  //setup_menu.add_screen(setup_stepper_settings);  
  //setup_menu.add_screen(setup_back_screen);
  main_menu1.add_screen(setup_temp_screen);
  main_menu1.add_screen(setup_set_temp_screen);
  main_menu1.add_screen(setup_stepper_settings);  
  main_menu1.add_screen(setup_back_screen);

  set_menu_screen(3);
  main_menu1.change_screen(&welcome_screen);
  
  main_menu1.update();
  
  //delay(2000);
  welcome_screen.hide(true);

}

void encoder_getvalue(){

  Crt = CurrentTime();
  StrCrt = Crt.substring(6) + "   " + millis2time();
  StrCrt.toCharArray(tst,20);
  if (OldCrt != Crt){
    OldCrt = Crt;
    main_menu1.softUpdate();
  }

  // Check all the buttons
  if (encoder.isRight()) {
    if (!main_menu1.is_callable(1)){
      main_menu1.next_screen();
    }
    else {
      multiplier = 1;
      main_menu1.call_function(1);
    }
  }
  if (encoder.isLeft()) {
    if (!main_menu1.is_callable(2)){
      main_menu1.previous_screen();
    }
    else {
      multiplier = 1;
      main_menu1.call_function(2);
    }
  }
  if (encoder.isRightH()) {
    multiplier = 10;
    main_menu1.call_function(1);
  }
  if (encoder.isLeftH()) {
    multiplier = 10;
    main_menu1.call_function(2);
  }
  if (encoder.isClick()) {
      main_menu1.switch_focus();
  }
}
