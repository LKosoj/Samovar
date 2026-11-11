#!/usr/bin/env python3
"""Замкнутая модель котла: мощность прошивки действительно меняет температуру.

Это проверка алгоритма, не модель конкретного устройства. Главный ТЭН даёт
0.5/1/2 °C/мин, разгонный — 0.5/1/2 его мощности; инерция 30/90/180/300 с,
запаздывание датчика 5/30 с и шаг DS18B20 0.0625 °C. Проверяются холодный
старт и последовательные 50→60→70 °C, превышение и последние 10 минут выдержки.
"""
import subprocess
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <initializer_list>
#include "adaptive_pid.h"
#define SAMOVAR_USE_POWER
const int POWER_SLEEP_MODE=0, POWER_WORK_MODE=1, SAFETY_HEATER_OUTPUT_BOOST=2;
enum ActuatorCommandResult { ACTUATOR_COMMAND_APPLIED, ACTUATOR_COMMAND_PENDING, ACTUATOR_COMMAND_FAILED };
struct { float StbVoltage=230, BVolt=230, HeaterHorizon=0; } SamSetup;
AdaptiveHeaterState adaptiveHeaterState{};
uint64_t adaptiveHeaterPowerGeneration=0, nextGeneration=0;
unsigned clockMs=0;
bool acceleration_heater=false, heater_state=false, physicalBoost=false;
int powerMode=POWER_SLEEP_MODE;
float mainDuty=0;
ActuatorCommandResult commandStatus=ACTUATOR_COMMAND_APPLIED;
const float ACCELERATION_HEATER_DELTA=4;
unsigned millis() { return clockMs; }
template<class T> T constrain(T v,T lo,T hi) { return v<lo?lo:(v>hi?hi:v); }
void set_heater_state_flag(bool state) { heater_state=state; }
void heater_boost_output_off() { physicalBoost=false; }
bool heater_enable_outputs(int outputs) {
  if (outputs & SAFETY_HEATER_OUTPUT_BOOST) physicalBoost=true;
  return true;
}
bool current_power_mode_is(int mode) { return powerMode==mode; }
ActuatorCommandResult current_power_command_status(uint64_t generation) {
  return generation==nextGeneration ? commandStatus : ACTUATOR_COMMAND_FAILED;
}
void check_power_error() {}
void persist_heater_horizon(float horizon) { SamSetup.HeaterHorizon=horizon; }
// Модель регулятора принимает напряжение, а не долю мощности: ниже 40 В он спит.
ActuatorCommandResult set_current_power(float voltage,uint64_t* generation=nullptr) {
  *generation=++nextGeneration;
  powerMode=voltage<40 ? POWER_SLEEP_MODE : POWER_WORK_MODE;
  mainDuty=powerMode==POWER_WORK_MODE ? voltage*voltage/(230*230) : 0;
  return commandStatus;
}
void set_power_mode(int mode) { powerMode=mode; if(mode==POWER_SLEEP_MODE) mainDuty=0; }
@STOP@
@REGULATOR@
void drive(float setpoint,float temp,float boostTarget) {
@DRIVE@
}
void check(bool ok,const char* text) {
  if(!ok) { std::fprintf(stderr,"FAIL: %s\n",text); std::exit(1); }
}
void reset(float horizon) {
  adaptive_heater_reset(adaptiveHeaterState,horizon);
  adaptiveHeaterPowerGeneration=0;
  powerMode=POWER_SLEEP_MODE;
  mainDuty=0;
  physicalBoost=acceleration_heater=false;
}
void check_command_observation() {
  reset(300);
  adaptiveHeaterState.boostAllowed=false;
  drive(50,55,50); // Нулевая мощность даёт generation=0 и команду сна.
  check(adaptiveHeaterPowerGeneration==0,"zero output must use the sleep command path");
  clockMs+=1000;
  drive(50,55,50);
  check(adaptiveHeaterState.lastCommandApplied,"confirmed sleep must allow coast measurement");
  powerMode=POWER_WORK_MODE; // Команда сна ещё не выполнена.
  clockMs+=1000;
  drive(50,55,50);
  check(!adaptiveHeaterState.lastCommandApplied,"pending sleep must not count as applied");
  for(auto status : {ACTUATOR_COMMAND_APPLIED,ACTUATOR_COMMAND_PENDING,ACTUATOR_COMMAND_FAILED}) {
    adaptiveHeaterPowerGeneration=nextGeneration=19;
    commandStatus=status;
    clockMs+=1000;
    drive(50,55,50);
    check(adaptiveHeaterState.lastCommandApplied==(status==ACTUATOR_COMMAND_APPLIED),
          "voltage command observation must follow its execution status");
  }
  commandStatus=ACTUATOR_COMMAND_APPLIED;
}
int main() {
  check_command_observation();
  for(float target:{50.f,70.f}) {
    reset(300);
    for(int second=0;second<30;second++) {
      adaptiveHeaterState.lastCommandApplied=true;
      adaptive_heater_step(adaptiveHeaterState,target,target,target-2,4,second*1000);
    }
    check(adaptiveHeaterState.integral==0,"approach must not accumulate holding power far from target");
    reset(300);
    for(int second=30;second<60;second++) {
      adaptiveHeaterState.lastCommandApplied=true;
      adaptive_heater_step(adaptiveHeaterState,target,target,target-0.2f,4,second*1000);
    }
    check(adaptiveHeaterState.integral>0,"hold must compensate heat loss near target");
  }
  float worstPeak[3]={},worstHold[3]={};
  int cases=0;
  for(float tau:{30.f,90.f,180.f,300.f})
  for(float rate:{0.5f,1.f,2.f})
  for(bool sequential:{false,true})
  for(float boostRatio:{0.5f,1.f,2.f})
  for(float sensorLag:{5.f,30.f}) {
    float temperature=20,measured=20,storedHeat=0;
    adaptiveHeaterState={};
    SamSetup.HeaterHorizon=0;
    int row=0;
    for(float target:{50.f,60.f,70.f}) {
      if(!sequential) {
        temperature=measured=20;
        storedHeat=0;
        SamSetup.HeaterHorizon=0;
        adaptiveHeaterState={};
      }
      reset(SamSetup.HeaterHorizon);
      float peak=temperature,holdError=0;
      int held=0,reached=-1,finished=-1;
      for(int second=0;second<18000;second++,clockMs+=1000) {
        drive(target,std::round(measured*16)/16,target);
        // Запасённое тепло отдаётся постепенно; потери растут с температурой.
        const float power=mainDuty+(physicalBoost?boostRatio:0);
        storedHeat+=(power-storedHeat)/tau;
        temperature+=(rate*storedHeat-0.0015f*(temperature-20))/60;
        measured+=(temperature-measured)/sensorLag;
        peak=std::max(peak,temperature);
        if(std::fabs(temperature-target)<=0.2f && reached<0) reached=second;
        if(reached>=0) held++;
        if(held>=1200) holdError=std::max(holdError,std::fabs(temperature-target));
        if(held>=1800) { finished=second; break; }
      }
      const float overshoot=std::max(0.f,peak-target);
      if(finished<0 || overshoot>0.5f || holdError>0.5f) {
        std::fprintf(stderr,"case target=%.0f tau=%.0f rate=%.1f sequence=%d boost=%.1f sensor=%.0f peak=%.3f hold=%.3f duration=%d\n",
                     target,tau,rate,sequential,boostRatio,sensorLag,overshoot,holdError,finished);
      }
      check(finished>=0,"thermal approach must reach the target and finish the hold");
      check(overshoot<=0.5f,"thermal approach overshoot must stay within half a degree");
      check(holdError<=0.5f,"thermal hold must stay within half a degree");
      worstPeak[row]=std::max(worstPeak[row],overshoot);
      worstHold[row]=std::max(worstHold[row],holdError);
      row++; cases++;
    }
  }
  for(int row=0;row<3;row++) std::printf("target=%d worst overshoot=%.3f C, hold error=%.3f C\n",50+row*10,worstPeak[row],worstHold[row]);
  std::printf("%d thermal approaches passed\n",cases);
}
'''


def harness(beer: str) -> str:
    body = extract_function_body(beer, "void set_heater_state(float setpoint, float temp, float boostTarget)")
    drive = body[body.index("const uint32_t nowMs = millis();"):body.index("#else\n  (void)boostTarget;")]
    functions = {
        "@STOP@": "void setHeaterPosition(bool state) {" + extract_function_body(beer, "void setHeaterPosition(bool state)") + "}",
        "@REGULATOR@": "ActuatorCommandResult set_heater_regulator(double dutyCycle,float maximumTarget,uint64_t* generation) {" + extract_function_body(beer, "inline ActuatorCommandResult set_heater_regulator(") + "}",
        "@DRIVE@": drive,
    }
    result = HARNESS
    for token, value in functions.items():
        result = result.replace(token, value)
    return result


def run(beer: str, header: str) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory(prefix="samovar-thermal-approach-") as tmp:
        path = Path(tmp)
        (path / "adaptive_pid.h").write_text(header)
        (path / "test.cpp").write_text(harness(beer))
        subprocess.run(["g++", "-std=c++11", "-O2", "-Wall", "-Wextra", "-Werror", str(path / "test.cpp"), "-o", str(path / "test")], check=True)
        return subprocess.run([str(path / "test")], capture_output=True, text=True)


def main():
    beer = (ROOT / "beer.h").read_text()
    header = (ROOT / "adaptive_pid.h").read_text()
    result = run(beer, header)
    if result.returncode:
        raise SystemExit(result.stderr)
    print(result.stdout, end="")
    mutations = (
        (beer, header.replace("HORIZON_DEFAULT_S = 300.0f", "HORIZON_DEFAULT_S = 60.0f", 1), "thermal approach overshoot"),
        (beer, header.replace(" ||\n      state.predictedTemp >= boostTarget - boostCutoff", "", 1), "thermal approach overshoot"),
        (beer, header.replace("(error < 0.0f || fabsf(setpoint - temp) <= 0.5f)", "true", 1), "approach must not accumulate holding power"),
        (beer.replace(": current_power_mode_is(POWER_SLEEP_MODE);", ": false;", 1), header, "confirmed sleep must allow coast measurement"),
    )
    for changed_beer, changed_header, expected in mutations:
        assert changed_beer != beer or changed_header != header, "mutation target missing"
        result = run(changed_beer, changed_header)
        assert result.returncode and "FAIL: " + expected in result.stderr, result.stderr
    print("Thermal approach and 4 mutation checks passed")


if __name__ == "__main__":
    main()
