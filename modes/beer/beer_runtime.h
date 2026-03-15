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
#include "modes/beer/beer_autotune.h"
#include "modes/beer/beer_heater.h"
#include "modes/beer/beer_mixer.h"
#include "modes/beer/beer_program_codec.h"
#include "storage/session_logs.h"
#include "pumppwm.h"

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
inline void run_beer_program(uint8_t num);

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
  if (SamovarStatusInt != SAMOVAR_STATUS_BEER) return;

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

#endif
