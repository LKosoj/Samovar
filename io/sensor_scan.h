#ifndef __SAMOVAR_IO_SENSOR_SCAN_H_
#define __SAMOVAR_IO_SENSOR_SCAN_H_

#include <Arduino.h>

#include "Samovar.h"
#include "state/globals.h"
#include "app/status_text.h"
#include "io/actuators.h"
#include "io/power_control.h"
#include "io/pressure.h"
#include "io/sensors.h"
#include "mod_rmvk.h"
#include "pumppwm.h"

void load_default_program_for_mode();
void stopService(void);
void writeString(String Str, uint8_t num);
inline void reset_sensor_counter(void);

inline void sensor_init(void) {
  pressure_sensor_init();

  writeString("DS1820 init...     ", 3);
  scan_ds_adress();
  writeString("Found " + (String)DScnt + "         ", 4);

  //Для шагового двигателя устанавливаем режим работы - следовать до позиции
  //  stepper.setRunMode(FOLLOW_POS);
  // установка макс. скорости в шагах/сек
  stepper.setMaxSpeed(STEPPER_MAX_SPEED);
  //stepper.setSpeed(0);
  //Драйвер выключится по достижении позиции
  stepper.autoPower(true);
#ifdef STEPPER_REVERSE
  stepper.reverse(true);
#endif

#ifdef USE_WATERSENSOR
  //Настраиваем датчик потока
  pinMode(WATERSENSOR_PIN, INPUT);
#endif

  // Загружаем программу по умолчанию для текущего режима
  load_default_program_for_mode();

#ifdef SAMOVAR_USE_SEM_AVR
  //Если SEM_AVR иницииурем порт
#ifdef __SAMOVAR_DEBUG
  Serial.println("Init SEM_AVR");
#endif
  xSemaphoreAVR = xSemaphoreCreateBinaryStatic(&xSemaphoreBufferAVR);
  xSemaphoreGive(xSemaphoreAVR);
  Serial2.setTimeout(500);
  //Serial2.setRxBufferSize(12);
  Serial2.begin(9600, SERIAL_8N1, RXD2, TXD2);
#define USE_SERIAL
#endif


#ifdef SAMOVAR_USE_RMVK
#ifndef USE_SERIAL
#ifdef __SAMOVAR_DEBUG
  Serial.println("Init RMVK");
#endif
  //Иначе работаем с RMVK
  Serial2.begin(9600, SERIAL_8N1, RXD2, TXD2);
  Serial2.end();
  RMVK_init();
#define USE_SERIAL
#endif
#endif

#ifdef SAMOVAR_USE_POWER
#ifndef USE_SERIAL
#ifdef __SAMOVAR_DEBUG
  Serial.println("Init KVIC");
#endif
  Serial2.setTimeout(300);
  Serial2.setRxBufferSize(0);
#ifdef KVIC_USE_9600
  Serial2.begin(9600, SERIAL_8N1, RXD2, TXD2);
#else
  Serial2.begin(38400, SERIAL_8N1, RXD2, TXD2);
#endif

#define USE_SERIAL
#endif
#endif


#ifdef USE_WATER_PUMP
  init_pump_pwm(WATER_PUMP_PIN, PUMP_PWM_FREQ);
  set_pump_pwm(0);
#endif

  reset_sensor_counter();
  //  regulator.hysteresis = 0.3;
  //  regulator.k = 0.3;
  //  regulator.dT = 4000;    //система инерционная, считаем скорость раз в четыре секунды
  //  regulator.setLimits(0, WindowSize);
  //  regulator.setDirection(REVERSE);
  heaterPID.SetSampleTime(1000);
  heaterPID.SetOutputLimits(0, 100);
  heaterPID.SetTunings(SamSetup.Kp, SamSetup.Ki, SamSetup.Kd);
}

//Обнуляем все счетчики
inline void reset_sensor_counter(void) {
  sam_command_sync = SAMOVAR_NONE;
  stopService();
  stepper.setMaxSpeed(0);
  //stepper.setSpeed(0);
  stepper.brake();
  stepper.disable();
  stepper.setCurrent(0);
  stepper.setTarget(0);
  set_capacity(0);
  alarm_h_min = 0;
  alarm_t_min = 0;
  t_min = 0;
  b_t_temp_prev = 0;
  b_t_time_min = 0;
  b_t_time_delay = 0;
#ifdef SAMOVAR_USE_POWER
  alarm_c_min = 0;
  alarm_c_low_min = 0;
  prev_target_power_volt = 0;
#endif
  d_s_time_min = 0;
  d_s_temp_finish = 0;
  wetting_autostart = false;

  current_power_volt = 0.0;
  target_power_volt = 0.0;
  pressure_value = 0.0;
  old_pressure_value = 0.0;

  ProgramNum = 0;
  SteamSensor.BodyTemp = 0;
  PipeSensor.BodyTemp = 0;
  WaterSensor.BodyTemp = 0;
  TankSensor.BodyTemp = 0;
  ACPSensor.BodyTemp = 0;
  SteamSensor.PrevTemp = 0;
  PipeSensor.PrevTemp = 0;
  WaterSensor.PrevTemp = 0;
  TankSensor.PrevTemp = 0;
  ACPSensor.PrevTemp = 0;


  ActualVolumePerHour = 0;
  SamovarStatusInt = 0;
  startval = 0;
  PauseOn = false;
  program_Wait = false;
  SteamSensor.Start_Pressure = 0;
  WthdrwlProgress = 0;
  TargetStepps = 0;
  I2CPumpTargetSteps = 0;
  I2CPumpTargetMl = 0;
  I2CPumpCmdSpeed = 0;
  I2CPumpCalibrating = false;

  begintime = 0;

  d_s_temp_prev = 0;
  is_self_test = false;

  if (fileToAppend) {
    fileToAppend.close();
  }

  if (bme_pressure < 100) BME_getvalue(false);
  start_pressure = bme_pressure;

  boil_started = false;
  boil_temp = 0;
  alcohol_s = 0;
  b_t_time_delay = 0;

  if (xSemaphore != NULL) xSemaphoreGive(xSemaphore);
#ifdef SAMOVAR_USE_SEM_AVR
  if (xSemaphoreAVR != NULL) xSemaphoreGive(xSemaphoreAVR);
#endif

  set_power(false);
  sam_command_sync = SAMOVAR_NONE;
  get_Samovar_Status();

  bk_pwm = PWM_LOW_VALUE * 40;

#ifdef SAMOVAR_USE_POWER
  power_err_cnt = 0;
#endif

#ifdef USE_LUA
  Lua_status = "";
#endif
}

#endif
