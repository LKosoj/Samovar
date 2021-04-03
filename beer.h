void beer_finish();

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
  Blynk.notify("{DEVICE_NAME} Berr finished");
#endif
  set_power(false);
  reset_sensor_counter();
}

void IRAM_ATTR check_alarm_beer() {

}
