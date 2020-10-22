#ifdef SAMOVAR_USE_BLYNK
BLYNK_READ(V0){
Blynk.virtualWrite(V0, SteamSensor.avgTemp);
Blynk.virtualWrite(V4, PowerOn);
int i;
int j;
if (startval > 0 && startval < 5) i = 1;
else i = 0;
Blynk.virtualWrite(V3, i);
if (startval == 10) j = 1;
else j = 0;
Blynk.virtualWrite(V12, j);
}

BLYNK_READ(V1){
Blynk.virtualWrite(V1, PipeSensor.avgTemp);
}

BLYNK_READ(V2){
Blynk.virtualWrite(V2, WthdrwlProgress);
}

BLYNK_READ(V5){
Blynk.virtualWrite(V5, bme_pressure);
}

BLYNK_READ(V6){
Blynk.virtualWrite(V6, WaterSensor.avgTemp);
}

BLYNK_READ(V7){
Blynk.virtualWrite(V7, TankSensor.avgTemp);
}

BLYNK_READ(V8){
Blynk.virtualWrite(V8, get_liquid_volume());
}

BLYNK_READ(V9){
Blynk.virtualWrite(V9, ActualVolumePerHour);
}

BLYNK_WRITE(V3)
{
  int Value3 = param.asInt(); // assigning incoming value from pin V3 to a variable
  if (Value3 == 1 && PowerOn) samovar_start();
  else samovar_reset();
}
BLYNK_WRITE(V4)
{
  int Value4 = param.asInt(); // assigning incoming value from pin V4 to a variable
  set_power(Value4);
}

BLYNK_WRITE(V10)
{
  int Value10 = param.asInt(); // assigning incoming value from pin V4 to a variable
  ManualVolume = Value10;
}

BLYNK_WRITE(V11)
{
  int Value11 = param.asFloat(); // assigning incoming value from pin V4 to a variable
  ManualLiquidRate = Value11;
}

BLYNK_WRITE(V12)
{
  int Value12 = param.asInt(); // assigning incoming value from pin V4 to a variable
  if (Value12 == 1) start_manual();
  else samovar_reset();
}
#endif
