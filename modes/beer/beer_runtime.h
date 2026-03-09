#ifndef __SAMOVAR_BEER_RUNTIME_H_
#define __SAMOVAR_BEER_RUNTIME_H_

#include <Arduino.h>
#include <math.h>

#include "Samovar.h"
#include "state/globals.h"
#include "SamovarMqtt.h"
#include "app/messages.h"
#include "app/alarm_control.h"
#include "app/process_common.h"
#include "io/actuators.h"
#include "io/power_control.h"
#include "modes/beer/beer_program_codec.h"
#include "pumppwm.h"
#include "I2CStepper.h"
#include "app/config_apply.h"

void create_data();
void save_profile();

#define TEMP_HISTORY_SIZE 10
#define BOILING_DETECT_THRESHOLD 0.08
#define MIN_BOILING_TEMP 98.0
#define STABLE_WINDOWS_REQUIRED 5
#define MAX_TREND_ABS_PER_SEC 0.02

struct BoilingDetector {
  float tempHistory[TEMP_HISTORY_SIZE];
  uint8_t historyIndex = 0;
  uint8_t samplesFilled = 0;
  bool isBoiling = false;
  unsigned long lastUpdateTime = 0;
  uint8_t stableCount = 0;
};

extern BoilingDetector boilingDetector;

inline void beer_finish();
inline void set_heater_state(float setpoint, float temp);
inline void set_heater(double dutyCycle);
inline void setHeaterPosition(bool state);
inline void run_beer_program(uint8_t num);
inline void StartAutoTune();
inline void FinishAutoTune();
inline void check_mixer_state();
inline void set_mixer_state(bool state, bool dir);
inline void set_mixer(bool On);
inline void HopStepperStep();

static inline void resetBoilingDetector() {
  boilingDetector.historyIndex = 0;
  boilingDetector.samplesFilled = 0;
  boilingDetector.stableCount = 0;
  boilingDetector.isBoiling = false;
  boilingDetector.lastUpdateTime = 0;
  for (int i = 0; i < TEMP_HISTORY_SIZE; i++) boilingDetector.tempHistory[i] = 0;
}

inline bool isBoilingStarted(float currentTemp) {
  unsigned long currentTime = millis();

  if (currentTime - boilingDetector.lastUpdateTime < 1000) {
    return boilingDetector.isBoiling;
  }
  boilingDetector.lastUpdateTime = currentTime;

  boilingDetector.tempHistory[boilingDetector.historyIndex] = currentTemp;
  if (boilingDetector.samplesFilled < TEMP_HISTORY_SIZE) boilingDetector.samplesFilled++;
  boilingDetector.historyIndex = (boilingDetector.historyIndex + 1) % TEMP_HISTORY_SIZE;

  if (boilingDetector.samplesFilled < TEMP_HISTORY_SIZE || currentTemp < MIN_BOILING_TEMP) {
    boilingDetector.stableCount = 0;
    return false;
  }

  float sum = 0.0f;
  for (int i = 0; i < TEMP_HISTORY_SIZE; i++) sum += boilingDetector.tempHistory[i];
  float avg = sum / TEMP_HISTORY_SIZE;

  float varSum = 0.0f;
  for (int i = 0; i < TEMP_HISTORY_SIZE; i++) {
    float d = boilingDetector.tempHistory[i] - avg;
    varSum += d * d;
  }
  float stddev = sqrtf(varSum / TEMP_HISTORY_SIZE);

  int lastIdx = (boilingDetector.historyIndex + TEMP_HISTORY_SIZE - 1) % TEMP_HISTORY_SIZE;
  int firstIdx = boilingDetector.historyIndex;
  float slope = (boilingDetector.tempHistory[lastIdx] - boilingDetector.tempHistory[firstIdx]) /
                float(TEMP_HISTORY_SIZE - 1);

  bool stableNow = (stddev <= BOILING_DETECT_THRESHOLD) && (fabsf(slope) <= MAX_TREND_ABS_PER_SEC);
  if (stableNow) {
    if (boilingDetector.stableCount < 255) boilingDetector.stableCount++;
  } else {
    boilingDetector.stableCount = 0;
  }

  if (boilingDetector.stableCount >= STABLE_WINDOWS_REQUIRED) {
    boilingDetector.isBoiling = true;
    return true;
  }

  return boilingDetector.isBoiling;
}

inline void beer_proc() {
  if (SamovarStatusInt != 2000) return;

  if (startval == 2000 && !PowerOn) {
    resetBoilingDetector();
#ifdef USE_MQTT
    SessionDescription.replace(",", ";");
    MqttSendMsg(String(chipId) + "," + SamSetup.TimeZone + "," + SAMOVAR_VERSION + "," + get_beer_program() + "," + SessionDescription, "st");
#endif
    create_data();
    PowerOn = true;
    set_power(true);
    run_beer_program(0);
  }
  vTaskDelay(10 / portTICK_PERIOD_MS);
}

inline void run_beer_program(uint8_t num) {
  if (Samovar_Mode != SAMOVAR_BEER_MODE || !PowerOn) return;
  if (startval == 2000) startval = 2001;

  uint8_t targetProgram = num;
  if (ProgramLen == 0 || targetProgram >= ProgramLen || targetProgram >= CAPACITY_NUM * 2) {
    targetProgram = CAPACITY_NUM * 2;
    SetScriptOff = 1;
  }

  if (targetProgram > 0 && targetProgram <= CAPACITY_NUM * 2 && program[targetProgram - 1].WType == "L" && loop_lua_fl) {
    SetScriptOff = 1;
  }

  if (targetProgram == CAPACITY_NUM * 2) {
    beer_finish();
    return;
  }

  ProgramNum = targetProgram;
  begintime = 0;
  msgfl = true;

  if (program[ProgramNum].WType == "A") {
    StartAutoTune();
  }

  String msg = "Переход к строке программы №" + String((ProgramNum + 1));
  if (program[ProgramNum].WType == "M") {
    msg += "; Нагрев до температуры засыпи солода: " + String(program[ProgramNum].Temp) + "°";
  } else if (program[ProgramNum].WType == "P") {
    msg += "; Температурная пауза: " + String(program[ProgramNum].Temp) + "°, время: " + String(program[ProgramNum].Time) + " мин";
  } else if (program[ProgramNum].WType == "B") {
    msg += "; Кипячение, время: " + String(program[ProgramNum].Time) + " мин";
  } else if (program[ProgramNum].WType == "C") {
    msg += "; Охлаждение до температуры: " + String(program[ProgramNum].Temp) + "°";
  } else if (program[ProgramNum].WType == "F") {
    msg += "; Ферментация, поддержание температуры: " + String(program[ProgramNum].Temp) + "°";
  } else if (program[ProgramNum].WType == "W") {
    msg += "; Режим ожидания";
  }

  if (SamSetup.ChangeProgramBuzzer) {
    set_buzzer(true);
    SendMsg(msg, ALARM_MSG);
  } else {
    SendMsg(msg, NOTIFY_MSG);
  }

  alarm_c_low_min = 0;
  alarm_c_min = 0;
  currentstepcnt = 0;
}

inline void beer_finish() {
  if (valve_status) {
    open_valve(false, true);
  }
  resetBoilingDetector();
  set_mixer_state(false, false);
#ifdef USE_WATER_PUMP
  set_pump_pwm(0);
  pump_started = false;
#endif
  setHeaterPosition(false);
  PowerOn = false;
  heater_state = false;
  startval = 0;
  stop_process("Программа затирания завершена");
  delay(200);
  delay(1000);
}

inline void check_alarm_beer() {
  if (startval <= 2000) return;

  float temp = 0;
  float tempDelta = 0;
  switch (program[ProgramNum].TempSensor) {
    case 0:
      temp = TankSensor.avgTemp;
      tempDelta = TankSensor.SetTemp;
      break;
    case 1:
      temp = WaterSensor.avgTemp;
      tempDelta = WaterSensor.SetTemp;
      break;
    case 2:
      temp = PipeSensor.avgTemp;
      tempDelta = PipeSensor.SetTemp;
      break;
    case 3:
      temp = SteamSensor.avgTemp;
      tempDelta = SteamSensor.SetTemp;
      break;
    case 4:
      temp = ACPSensor.avgTemp;
      tempDelta = ACPSensor.SetTemp;
      break;
    default:
      SendMsg("Ошибка программы: неверный датчик температуры в режиме Пиво", ALARM_MSG);
      beer_finish();
      return;
  }

  if (program[ProgramNum].WType != "C" && program[ProgramNum].WType != "F" && valve_status && PowerOn && program[ProgramNum].WType != "L") {
    open_valve(false, false);
  }

  if (program[ProgramNum].WType == "L") {
    return;
  }

  if (program[ProgramNum].WType == "W") {
    if (begintime == 0) {
      begintime = millis();
      setHeaterPosition(false);
      open_valve(false, false);
    }
    check_mixer_state();
    return;
  }

  if (program[ProgramNum].WType == "A") {
    if (tuning) {
      set_heater_state(program[ProgramNum].Temp, temp);
    } else {
      beer_finish();
    }
  }

  if (program[ProgramNum].WType == "M" || program[ProgramNum].WType == "P") {
    set_heater_state(program[ProgramNum].Temp, temp);
  }

  if (program[ProgramNum].WType == "F") {
    if (temp < program[ProgramNum].Temp - tempDelta) {
      if (valve_status) {
        open_valve(false, false);
      }
      set_heater_state(program[ProgramNum].Temp, temp);
    } else if (temp > program[ProgramNum].Temp + tempDelta) {
      if (!valve_status) {
        setHeaterPosition(false);
        open_valve(true, false);
      }
    } else {
      setHeaterPosition(false);
      if ((temp < program[ProgramNum].Temp + tempDelta - 0.1) && valve_status && PowerOn) {
        open_valve(false, false);
      }
    }
  }

  if (program[ProgramNum].WType == "M" && temp >= program[ProgramNum].Temp - tempDelta) {
    if (startval == 2001) {
      set_buzzer(true);
      SendMsg(("Достигнута температура засыпи солода!"), NOTIFY_MSG);
    }
    startval = 2002;
  }

  if (program[ProgramNum].WType == "P" && temp >= program[ProgramNum].Temp - tempDelta) {
    if (begintime == 0) {
      begintime = millis();
      SendMsg("Достигнута температурная пауза " + String(program[ProgramNum].Temp) + "°. Ждем " + String(program[ProgramNum].Time) + " минут.", NOTIFY_MSG);
    }
  }

  if (program[ProgramNum].WType == "C") {
    if (begintime == 0) {
      begintime = millis();
      setHeaterPosition(false);
      open_valve(true, false);
#ifdef USE_WATER_PUMP
      set_pump_pwm(1023);
      pump_started = true;
#endif
    }
    if (temp <= program[ProgramNum].Temp) {
      open_valve(false, false);
#ifdef USE_WATER_PUMP
      set_pump_pwm(0);
      pump_started = false;
#endif
      run_beer_program(ProgramNum + 1);
    }
  }

  if (program[ProgramNum].WType == "B") {
    if (begintime == 0 && ProgramNum > 0 && program[ProgramNum - 1].WType == "B") begintime = millis();

    if (begintime == 0) {
      if (isBoilingStarted(temp)) {
        msgfl = true;
        begintime = millis();
        SendMsg(("Начался режим кипячения"), NOTIFY_MSG);
      }
    }

    if (begintime == 0) {
      set_heater_state(BOILING_TEMP + 5, temp);
    } else {
      heater_state = true;
#ifdef SAMOVAR_USE_POWER
      set_current_power(SamSetup.BVolt);
#else
      current_power_mode = POWER_WORK_MODE;
      digitalWrite(RELE_CHANNEL1, SamSetup.rele1);
#endif
      if (SamSetup.UseST) {
        digitalWrite(RELE_CHANNEL4, SamSetup.rele4);
      } else {
        digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);
      }
    }

    if (begintime > 0 && msgfl && ((float(millis()) - begintime) / 1000 / 60 + 0.5 >= program[ProgramNum].Time)) {
      set_buzzer(true);
      msgfl = false;
      SendMsg(("Засыпьте хмель!"), NOTIFY_MSG);
#ifdef __SAMOVAR_DEBUG
      Serial.println("Засыпьте хмель!");
#endif
      HopStepperStep();
    }
  }

  if (begintime > 0 && (program[ProgramNum].WType == "B" || program[ProgramNum].WType == "P") && ((millis() - begintime) / 1000 / 60 >= program[ProgramNum].Time)) {
    run_beer_program(ProgramNum + 1);
  }

  check_mixer_state();

  vTaskDelay(10 / portTICK_PERIOD_MS);
}

inline void check_mixer_state() {
  if (program[ProgramNum].capacity_num > 0) {
    if (alarm_c_min > 0 && alarm_c_min <= millis()) {
      alarm_c_min = 0;
      alarm_c_low_min = 0;
      set_mixer_state(false, false);
    }

    if ((alarm_c_low_min > 0) && (alarm_c_low_min <= millis())) {
      alarm_c_low_min = 0;
      if (alarm_c_min > 0) {
        set_mixer_state(false, false);
      }
    }

    if (alarm_c_low_min == 0 && alarm_c_min == 0) {
      alarm_c_low_min = millis() + program[ProgramNum].Volume * 1000;
      if (program[ProgramNum].Power > 0) alarm_c_min = alarm_c_low_min + program[ProgramNum].Power * 1000;
      currentstepcnt++;
      bool dir = false;
      if (currentstepcnt % 2 == 0 && program[ProgramNum].Speed < 0) dir = true;
      set_mixer_state(true, dir);
    }
  } else {
    if (mixer_status) {
      set_mixer_state(false, false);
    }
  }
}

inline void set_mixer_state(bool state, bool dir) {
  mixer_status = state;
  if (state) {
    if (BitIsSet(program[ProgramNum].capacity_num, 0)) {
      digitalWrite(RELE_CHANNEL2, SamSetup.rele2);
      if (use_I2C_dev == 1) {
        int tm = abs(program[ProgramNum].Volume);
        if (tm == 0) tm = 10;
        bool b = set_stepper_by_time(20, dir, tm);
        (void)b;
      }
    }
    if (BitIsSet(program[ProgramNum].capacity_num, 1)) {
#ifdef USE_WATER_PUMP
      pump_pwm.write(1023);
#endif
      if (use_I2C_dev == 1 || use_I2C_dev == 2) {
        bool b = set_mixer_pump_target(1);
        (void)b;
      }
    }
  } else {
    digitalWrite(RELE_CHANNEL2, !SamSetup.rele2);
#ifdef USE_WATER_PUMP
    pump_pwm.write(0);
#endif
    if (use_I2C_dev == 1) {
      bool b = set_stepper_by_time(0, 0, 0);
      (void)b;
    }
    if (use_I2C_dev == 1 || use_I2C_dev == 2) {
      bool b = set_mixer_pump_target(0);
      (void)b;
    }
  }
}

inline void set_heater_state(float setpoint, float temp) {
#ifdef SAMOVAR_USE_POWER
  if (setpoint - temp > ACCELERATION_HEATER_DELTA && !tuning) {
    if (!acceleration_heater) {
      acceleration_heater = true;
      digitalWrite(RELE_CHANNEL4, SamSetup.rele4);
    }
  } else if (acceleration_heater) {
    digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);
    acceleration_heater = false;
  }
#endif

  if (setpoint - temp > HEAT_DELTA && !tuning) {
    heater_state = true;
#ifdef SAMOVAR_USE_POWER
    vTaskDelay(5 / portTICK_PERIOD_MS);
    set_current_power(SamSetup.BVolt);
#else
    current_power_mode = POWER_WORK_MODE;
    digitalWrite(RELE_CHANNEL1, SamSetup.rele1);
    digitalWrite(RELE_CHANNEL4, SamSetup.rele4);
#endif
  } else {
    heaterPID.SetMode(AUTOMATIC);
    Setpoint = setpoint;
    Input = temp;

    if (tuning) {
      if (aTune.Runtime()) {
        FinishAutoTune();
      }
    } else {
      heaterPID.Compute();
    }
    set_heater(Output / 100);
  }
}

inline void set_heater(double dutyCycle) {
  static uint32_t oldTime = 0;
  static uint32_t periodTime = 0;

  uint32_t newTime = millis();
  uint32_t offTime = periodInSeconds * 1000 * (dutyCycle);

  if (newTime < oldTime) {
    periodTime += (UINT32_MAX - oldTime + newTime);
  } else {
    periodTime += (newTime - oldTime);
  }
  oldTime = newTime;

  if (periodTime < offTime) {
    if (dutyCycle > 0.0) setHeaterPosition(true);
  } else if (periodTime >= periodInSeconds * 1000) {
    periodTime = 0;
    if (dutyCycle > 0.0) setHeaterPosition(true);
  } else {
    setHeaterPosition(false);
  }
}

inline void setHeaterPosition(bool state) {
  heater_state = state;

  if (state) {
#ifdef SAMOVAR_USE_POWER
    set_current_power(SamSetup.StbVoltage);
    check_power_error();
#else
    current_power_mode = POWER_WORK_MODE;
    digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);
    digitalWrite(RELE_CHANNEL1, SamSetup.rele1);
    vTaskDelay(50 / portTICK_PERIOD_MS);
#endif
  } else {
#ifdef SAMOVAR_USE_POWER
    if (current_power_mode != POWER_SLEEP_MODE) {
      set_power_mode(POWER_SLEEP_MODE);
    }
#else
    current_power_mode = POWER_WORK_MODE;
    digitalWrite(RELE_CHANNEL1, !SamSetup.rele1);
    digitalWrite(RELE_CHANNEL4, !SamSetup.rele4);
#endif
  }
}

inline void StartAutoTune() {
  ATuneModeRemember = heaterPID.GetMode();

  Output = 50;

  aTune.SetControlType(1);
  aTune.SetNoiseBand(aTuneNoise);
  aTune.SetOutputStep(aTuneStep);
  aTune.SetLookbackSec((int)aTuneLookBack);
  tuning = true;
}

inline void FinishAutoTune() {
  aTune.Cancel();
  tuning = false;

  SamSetup.Kp = aTune.GetKp();
  SamSetup.Ki = aTune.GetKi();
  SamSetup.Kd = aTune.GetKd();

  WriteConsoleLog("Kp = " + (String)SamSetup.Kp);
  WriteConsoleLog("Ki = " + (String)SamSetup.Ki);
  WriteConsoleLog("Kd = " + (String)SamSetup.Kd);

  heaterPID.SetTunings(SamSetup.Kp, SamSetup.Ki, SamSetup.Kd);
  heaterPID.SetMode(ATuneModeRemember);

  save_profile();
  read_config();

  set_heater_state(0, 50);
}

inline void set_mixer(bool On) {
  set_mixer_state(On, false);
}

inline void HopStepperStep() {
  stopService();
  stepper.brake();
  stepper.disable();
  stepper.setMaxSpeed(200);
  TargetStepps = 360 / 1.8 * 16 / 20;
  stepper.setCurrent(0);
  stepper.setTarget(TargetStepps);
  stepper.enable();
  startService();
}

#endif
