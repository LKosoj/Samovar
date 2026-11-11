#!/usr/bin/env python3
"""Настоящие пути кипячения, выключения нагрева и смены строки программы."""
import subprocess
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <initializer_list>
struct Setup { bool rele1, rele4, UseST; float StbVoltage; } SamSetup{};
struct Row { char WType; } program[2];
uint8_t ProgramNum=0, beerSkipConfirmProgramNum=0;
int startval=0, shutdownRow=-1;
bool acceleration_heater=false, heater_state=false, boostPin=false, mainPin=false;
bool enableResult=true;
int powerMode=1;
const int POWER_SLEEP_MODE=0, POWER_WORK_MODE=1, portTICK_PERIOD_MS=1;
const int SAFETY_HEATER_OUTPUT_MAIN=1, SAFETY_HEATER_OUTPUT_BOOST=2;
const int RELE_CHANNEL1=1, RELE_CHANNEL4=4;
const int SAMOVAR_STARTVAL_BEER_START=1, SAMOVAR_STARTVAL_BEER_HEATING=2;
enum { ACTUATOR_COMMAND_APPLIED, ACTUATOR_COMMAND_PENDING };
void digitalWrite(int pin,bool value) {
  if(pin==4) { boostPin=value; shutdownRow=ProgramNum; }
  else mainPin=value;
}
void set_current_power(float) { powerMode=POWER_WORK_MODE; }
bool set_current_power_mode_value(int mode) { powerMode=mode; return true; }
void check_power_error() {}
bool current_power_mode_is(int mode) { return powerMode==mode; }
void set_power_mode(int mode) { powerMode=mode; }
bool heater_enable_outputs(int outputs) {
  if(enableResult) {
    if(outputs&SAFETY_HEATER_OUTPUT_BOOST) boostPin=SamSetup.rele4;
    if(outputs&SAFETY_HEATER_OUTPUT_MAIN) mainPin=SamSetup.rele1;
  }
  return enableResult;
}
void vTaskDelay(int) {}
int beer_set_cooling_outputs(bool) { return ACTUATOR_COMMAND_APPLIED; }
char program_type_at(uint8_t i) { return program[i].WType; }
void set_heater_state_flag(bool state) { @FLAG@ }
void heater_boost_output_off() { @OFF@ }
void setHeaterPosition(bool state) { @SET@ }
void boil_tick() { if(SamSetup.UseST) { @BOIL_ON@ } else { @BOIL_OFF@ } }
void transition(uint8_t targetProgram) { @TRANSITION@ }
void check(bool ok,const char* message) {
  if(!ok) { std::fprintf(stderr,"FAIL: %s\n",message); std::exit(1); }
}
void energized(bool flag) {
  boostPin=SamSetup.rele4;
  mainPin=SamSetup.rele1;
  acceleration_heater=flag;
  heater_state=true;
  shutdownRow=-1;
}
int main() {
  for(bool polarity:{false,true}) {
    SamSetup.rele4=SamSetup.rele1=polarity;
    for(bool flag:{false,true}) for(int mode:{POWER_SLEEP_MODE,POWER_WORK_MODE}) {
      energized(flag);
      powerMode=mode;
      setHeaterPosition(false);
      check(boostPin==!polarity,"stop must switch the boost relay off");
      check(!acceleration_heater,"stop must clear the boost flag");
      check(!heater_state,"stop must clear the heater flag");
#ifdef SAMOVAR_USE_POWER
      check(powerMode==POWER_SLEEP_MODE,"stop must put the regulator to sleep");
#else
      check(mainPin==!polarity,"stop must switch the main relay off");
#endif
    }
    // Галочка меняется в процессе, без перезапуска программы.
    SamSetup.UseST=false;
    energized(true);
    boil_tick();
    check(boostPin==!polarity && !acceleration_heater,"disabled UseST must clear relay and flag");
    SamSetup.UseST=true;
    enableResult=true;
    boil_tick();
    check(boostPin==polarity && acceleration_heater,"enabled UseST must set relay and flag");
    SamSetup.UseST=false;
    boil_tick();
    check(boostPin==!polarity && !acceleration_heater,"removed UseST must clear relay and flag");
    SamSetup.UseST=true;
    enableResult=false;
    boil_tick();
    check(!acceleration_heater && boostPin==!polarity,"rejected enable must leave boost off");
    enableResult=true;
    for(char next:{'W','C','P','M','F','B'}) {
      program[0].WType='B';
      program[1].WType=next;
      ProgramNum=0;
      powerMode=POWER_WORK_MODE;
      energized(true);
      transition(1);
      check(ProgramNum==1,"transition must advance the program row");
      if(next=='B') {
        check(boostPin==polarity && acceleration_heater,"adjacent boil rows must keep boost on");
      } else {
        check(boostPin==!polarity && !acceleration_heater,"leaving boil must switch boost off");
        check(shutdownRow==0,"leaving boil must stop heat before changing row");
      }
    }
  }
}
'''


def fragments(beer):
    yes, end = extract_braced_block_after(beer, "if (SamSetup.UseST)")
    no, _ = extract_braced_block_after(beer, "else", end)
    transition = extract_function_body(beer, "void run_beer_program(uint8_t num)")
    start = transition.rindex("if (beer_set_cooling_outputs(false) != ACTUATOR_COMMAND_APPLIED) return;")
    end = transition.index("ProgramNum = targetProgram;", start) + len("ProgramNum = targetProgram;")
    return {
        "@FLAG@": extract_function_body(beer, "void set_heater_state_flag(bool state)"),
        "@OFF@": extract_function_body((ROOT / "power_regulator.h").read_text(), "inline void heater_boost_output_off()"),
        "@SET@": extract_function_body(beer, "void setHeaterPosition(bool state)"),
        "@BOIL_ON@": yes, "@BOIL_OFF@": no, "@TRANSITION@": transition[start:end],
    }


def run(parts, uart):
    source = HARNESS
    for token, code in parts.items():
        source = source.replace(token, code)
    with tempfile.TemporaryDirectory(prefix="samovar-boost-shutdown-") as tmp:
        path = Path(tmp)
        (path / "test.cpp").write_text(source)
        defines = ["-DSAMOVAR_USE_POWER"] if uart else []
        subprocess.run(["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", *defines,
                        str(path / "test.cpp"), "-o", str(path / "test")], check=True)
        return subprocess.run([str(path / "test")], text=True, capture_output=True)


def main():
    parts = fragments((ROOT / "beer.h").read_text())
    for uart in (False, True):
        result = run(parts, uart)
        assert result.returncode == 0, result.stderr
    # Последний вызов относится к ветке выключения; скобки и заглушки не меняем.
    off = parts["@SET@"].rindex("heater_boost_output_off();")
    mutations = (
        ("@SET@", parts["@SET@"][:off] + parts["@SET@"][off:].replace("heater_boost_output_off();", "", 1), "stop must switch"),
        ("@SET@", parts["@SET@"].replace("acceleration_heater = false;", "", 1), "stop must clear the boost flag"),
        ("@BOIL_ON@", parts["@BOIL_ON@"].replace("acceleration_heater = ", "", 1), "enabled UseST must set"),
        ("@BOIL_OFF@", parts["@BOIL_OFF@"].replace("acceleration_heater = false;", "", 1), "disabled UseST must clear"),
        ("@TRANSITION@", parts["@TRANSITION@"].replace("setHeaterPosition(false);", "", 1), "leaving boil must switch"),
    )
    for token, code, expected in mutations:
        assert code != parts[token], "missing mutation target"
        changed = dict(parts)
        changed[token] = code
        result = run(changed, True)
        assert result.returncode and "FAIL: " + expected in result.stderr, result.stderr
    print("Beer boost shutdown: UART/relay, both polarities, live UseST, 6 transitions and 5 mutations passed")


if __name__ == "__main__":
    main()
