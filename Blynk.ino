#ifdef SAMOVAR_USE_BLYNK
BLYNK_READ(V0) {
  vTaskDelay(2);
  Blynk.virtualWrite(V0, SteamSensor.avgTemp);
  vTaskDelay(2);
  Blynk.virtualWrite(V4, PowerOn);
  int i;
  int k;
  if (startval > 0 && startval < 5) i = 1;
  else i = 0;
  Blynk.virtualWrite(V3, i);
  vTaskDelay(2);
  if (PauseOn) k = 1;
  else k = 0;
  Blynk.virtualWrite(V13, k);
}

BLYNK_READ(V1) {
  Blynk.virtualWrite(V1, PipeSensor.avgTemp);
}

BLYNK_READ(V2) {
  Blynk.virtualWrite(V2, WthdrwlProgress);
}

BLYNK_READ(V5) {
  Blynk.virtualWrite(V5, bme_pressure);
}

BLYNK_READ(V6) {
  Blynk.virtualWrite(V6, WaterSensor.avgTemp);
}

BLYNK_READ(V7) {
  Blynk.virtualWrite(V7, TankSensor.avgTemp);
}

BLYNK_READ(V8) {
  Blynk.virtualWrite(V8, get_liquid_volume());
}

BLYNK_READ(V9) {
  Blynk.virtualWrite(V9, ActualVolumePerHour);
}

BLYNK_READ(V10) {
  Blynk.virtualWrite(V10, WthdrwTimeS + "; " + WthdrwTimeAllS);
}

BLYNK_READ(V11) {
  Blynk.virtualWrite(V11, StrCrt);
}

BLYNK_READ(V14) {
  Blynk.virtualWrite(V14, get_Samovar_Status());
}

#ifdef SAMOVAR_USE_POWER
BLYNK_READ(V16) {
  Blynk.virtualWrite(V16, target_power_volt);
}

BLYNK_WRITE(V16)
{
  float Value16 = param.asFloat(); // assigning incoming value from pin V16 to a variable
  set_current_power(Value16);
}
#endif

BLYNK_WRITE(V17)
{
  float Value17 = param.asFloat(); // assigning incoming value from pin V17 to a variable
  set_pump_speed(get_speed_from_rate(Value17), true);
}

BLYNK_WRITE(V13)
{
  pause_withdrawal(!PauseOn);
}

BLYNK_WRITE(V3)
{
  int Value3 = param.asInt(); // assigning incoming value from pin V3 to a variable
  if (Value3 == 1 && PowerOn) menu_samovar_start();
  else samovar_reset();
}
BLYNK_WRITE(V4)
{
  int Value4 = param.asInt(); // assigning incoming value from pin V4 to a variable
  if (Samovar_Mode == SAMOVAR_BEER_MODE) {
    if (!PowerOn) sam_command_sync = SAMOVAR_BEER;
    else sam_command_sync = SAMOVAR_POWER;
  }
  else sam_command_sync = SAMOVAR_POWER;
  //set_power(Value4);
}

#endif
