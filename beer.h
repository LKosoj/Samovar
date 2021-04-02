void beer_finish();

void beer_proc(){
  return;
}

void IRAM_ATTR beer_finish(){
    Msg = "Beer finished";
#ifdef SAMOVAR_USE_BLYNK
    //Если используется Blynk - пишем оператору
    Blynk.notify("{DEVICE_NAME} Berr finished");
#endif
    reset_sensor_counter();
}

void IRAM_ATTR check_alarm_beer() {
  
}
