#!/usr/bin/env python3
"""Первая строка тела сохраняет автокоррекцию, но рост ограничен по обоим датчикам."""
import re
import subprocess
import tempfile
from pathlib import Path

from smoke_helpers import I18N_INCLUDE, extract_braced_block_after, extract_function_body

ROOT = Path(__file__).resolve().parents[1]
HARNESS = I18N_INCLUDE + r'''
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <initializer_list>
using ProgramType=char;
struct String : std::string {
  using std::string::string;
  String(float value):std::string(std::to_string(value)) {}
  String(float value,int):std::string(std::to_string(value)) {}
};
struct Sensor { float avgTemp=0,BodyTemp=0,Start_Pressure=0; } SteamSensor,PipeSensor,WaterSensor,TankSensor;
struct Row { char WType; } program[4];
struct { bool useautospeed=true; uint8_t autospeed=5; } SamSetup;
struct { float currentTrend=0.05f,tempVariance=0,correctionFactor=1; unsigned long lastCorrectionTime=0; int detectorStatus=0; } impurityDetector;
float bme_pressure=760,body_temp_row_base=0,body_temp_pipe_row_base=0;
uint32_t body_temp_capture_deadline=0;
float CurrentBaseSpeedRate=1,ActualVolumePerHour=1;
uint16_t CurrrentStepperSpeed=1000;
uint8_t ProgramNum=1;
const uint8_t PROGRAM_MAX=4;
const int WARNING_MSG=1,NOTIFY_MSG=2,UI_CONTROL_SOURCE_DETECTOR=3;
unsigned resetCount=0,pumpCalls=0;
unsigned long clockMs=100000;
@CONSTANTS@
unsigned long millis() { return clockMs; }
void SendMsg(const std::string&,int) {}
bool program_type_empty(char type) { return type=='\0'; }
bool program_type_one_of(char type,const char* types) { return std::strchr(types,type)!=nullptr; }
char program_type_at(uint8_t n) { return n<PROGRAM_MAX?program[n].WType:'\0'; }
char current_program_type() { return program_type_at(ProgramNum); }
void reset_impurity_detector() {
  resetCount++;
  impurityDetector.currentTrend=0;
  impurityDetector.correctionFactor=1;
  impurityDetector.lastCorrectionTime=millis();
}
float get_speed_from_rate(float rate) { return rate*1000; }
void set_pump_speed(float speed,bool,bool,int) { CurrrentStepperSpeed=speed; pumpCalls++; }
@FUNCTIONS@
void reset_row() { @RESET_ROW@ }
void warning_tick() {
  const unsigned long now=millis();
  const uint8_t currentProgram=ProgramNum;
  const ProgramType currentType=current_program_type();
  const float warningThreshold=0.04f,criticalThreshold=0.1f;
  @WARNING@
}
void check(bool ok,const char* message) {
  if(!ok) { std::fprintf(stderr,"FAIL: %s\n",message); std::exit(1); }
}
void begin(float steam,float pipe) {
  program[0].WType='H';program[1].WType='B';
  ProgramNum=1;
  SteamSensor.avgTemp=steam;PipeSensor.avgTemp=pipe;
  reset_row();
  set_body_temp();
  clockMs+=100000;
  impurityDetector.currentTrend=0.05f;
  pumpCalls=resetCount=0;
  CurrrentStepperSpeed=1000;
  SamSetup.useautospeed=true;
}
int main() {
  for(float steam:{78.f,79.f}) for(float pipe:{75.f,77.f}) {
    begin(steam,pipe);
    check(body_temp_row_base==steam && body_temp_pipe_row_base==pipe,"first capture must save both row baselines");
    SteamSensor.avgTemp=steam+0.125f;PipeSensor.avgTemp=pipe+0.125f;
#ifdef USE_BODY_TEMP_AUTOSET
    check(body_temp_autoset_allowed(),"small rise must preserve the first-body exception");
    warning_tick();
    check(resetCount==1 && pumpCalls==0,"first body must update temperatures instead of reducing speed");
    check(SteamSensor.BodyTemp==steam+0.125f && PipeSensor.BodyTemp==pipe+0.125f,"autoset must capture both current temperatures");
    check(body_temp_row_base==steam && body_temp_pipe_row_base==pipe,"repeated capture must not move either baseline");
    SteamSensor.avgTemp=steam+BODY_TEMP_AUTOSET_MAX_RISE;
    PipeSensor.avgTemp=pipe+BODY_TEMP_AUTOSET_MAX_RISE;
    check(body_temp_autoset_allowed(),"rise exactly at the limit must remain allowed");
#else
    check(!body_temp_autoset_allowed(),"disabled autoset must not update body temperatures");
    warning_tick();
    check(resetCount==0 && pumpCalls==1,"disabled autoset must allow detector speed correction");
#endif
    for(bool pipeOnly:{false,true}) {
      begin(steam,pipe);
      SteamSensor.avgTemp=steam+(pipeOnly?0:0.375f);
      PipeSensor.avgTemp=pipe+(pipeOnly?0.375f:0);
      check(!body_temp_autoset_allowed(),"either sensor above the row limit must forbid autoset");
      warning_tick();
      check(resetCount==0 && pumpCalls==1 && CurrrentStepperSpeed<1000,"over-limit warning must reduce takeoff without resetting detector");
      check(SteamSensor.BodyTemp==steam && PipeSensor.BodyTemp==pipe,"over-limit warning must preserve body temperatures");
    }
    begin(steam,pipe);
    body_temp_row_base=body_temp_pipe_row_base=0;
    check(!body_temp_autoset_allowed(),"uncaptured row must not permit autoset");
    body_temp_row_base=steam;body_temp_pipe_row_base=pipe;
    reset_row();
    check(body_temp_row_base==0 && body_temp_pipe_row_base==0,"new row must clear both baselines");
  }
  // Повторные разрешённые обновления не превращают предел в подвижную цель.
  begin(78,75);
  for(float delta:{0.125f,0.25f,0.375f,0.5f}) {
    PipeSensor.avgTemp=75+delta;
    clockMs+=100000;
    impurityDetector.currentTrend=0.05f;
    const auto before=resetCount;
    warning_tick();
#ifdef USE_BODY_TEMP_AUTOSET
    if(delta<0.3f) check(resetCount==before+1,"first-body exception must remain below limit");
    else check(resetCount==before,"pipe growth must stop repeated detector resets");
#else
    check(resetCount==before,"disabled autoset must never restart detector stabilization");
#endif
  }
}
'''
FUNCTIONS = (
    ("detector", "inline bool body_temp_autoset_allowed()"),
    ("logic", "void set_body_temp()"),
    ("detector", "bool is_first_body_program_after_heads(uint8_t currentProgram, ProgramType currentType)"),
    ("detector", "inline float get_detector_correction_step()"),
    ("detector", "inline bool apply_detector_speed_correction(float baseSpeedRate)"),
)


def run(detector, logic, enabled):
    sources = {"detector": detector, "logic": logic}
    functions = '\n'.join(signature+' {'+extract_function_body(sources[name], signature)+'}' for name, signature in FUNCTIONS)
    constants = '\n'.join(re.findall(r'^static const [^;]+;', detector, flags=re.MULTILINE))
    config = (ROOT/'Samovar_ini.h').read_text()
    constants += '\n'+re.search(r'^#define BODY_TEMP_AUTOSET_MAX_RISE[^\n]+',config,re.MULTILINE)[0]
    row = extract_function_body(logic,'void run_program(uint8_t num)')
    start=row.index('body_temp_row_base = 0;')
    end=row.index('body_temp_capture_deadline = 0;',start)+len('body_temp_capture_deadline = 0;')
    warning,_=extract_braced_block_after(detector,'if (!PauseOn && !isDetectorPause)')
    source=HARNESS.replace('@CONSTANTS@',constants).replace('@FUNCTIONS@',functions).replace('@RESET_ROW@',row[start:end]).replace('@WARNING@',warning)
    with tempfile.TemporaryDirectory(prefix='samovar-body-limit-') as tmp:
        path=Path(tmp)
        (path/'test.cpp').write_text(source)
        flags=['-DUSE_BODY_TEMP_AUTOSET'] if enabled else []
        subprocess.run(['g++','-std=c++11','-Wall','-Wextra','-Werror',*flags,str(path/'test.cpp'),'-o',str(path/'test')],check=True)
        return subprocess.run([str(path/'test')],text=True,capture_output=True)


def main():
    detector=(ROOT/'impurity_detector.h').read_text()
    logic=(ROOT/'logic.h').read_text()
    for enabled in (False,True):
        result=run(detector,logic,enabled)
        assert result.returncode==0,result.stderr
    mutations = (
        (detector.replace(' &&\n         PipeSensor.avgTemp <= body_temp_pipe_row_base + BODY_TEMP_AUTOSET_MAX_RISE', '', 1), logic, True, 'either sensor above the row limit'),
        (detector.replace('SteamSensor.avgTemp <= body_temp_row_base + BODY_TEMP_AUTOSET_MAX_RISE &&\n         ', '', 1), logic, True, 'either sensor above the row limit'),
        (detector, logic.replace('      body_temp_pipe_row_base = PipeSensor.BodyTemp;', '', 1), True, 'first capture must save both'),
        (detector, logic.replace('  body_temp_pipe_row_base = 0;', '', 1), True, 'new row must clear both'),
        (detector.replace('#ifdef USE_BODY_TEMP_AUTOSET\n', '', 1).replace('#else\n  return false;\n#endif', '', 1), logic, False, 'disabled autoset must not update'),
        (detector.replace('if (isFirstBodyProgram && body_temp_autoset_allowed())', 'if (isFirstBodyProgram && body_temp_autoset_allowed() && false)', 1), logic, True, 'first body must update'),
        (detector, logic.replace('if (body_temp_row_base <= 0.0f)', 'if (true)', 1), True, 'repeated capture must not move'),
    )
    for changed_detector, changed_logic, enabled, expected in mutations:
        assert changed_detector != detector or changed_logic != logic, 'mutation target missing'
        result=run(changed_detector,changed_logic,enabled)
        assert result.returncode and 'FAIL: '+expected in result.stderr,result.stderr
    print('Both-sensor body autoset limits, preserved first-body exception and 7 mutation checks passed')


if __name__=='__main__':
    main()
