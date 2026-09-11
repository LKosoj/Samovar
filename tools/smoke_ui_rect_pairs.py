#!/usr/bin/env python3
"""P02: реальные RECT/common точки пар проверяются извлечёнными телами.

Это не модель прошивки: в C++ попадают тела hooks из production source. Заглушки
хранят состояние привода и публикаций, поэтому проверяются принятые переходы,
а не наличие вызова в тексте.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body

ROOT = Path(__file__).resolve().parents[1]


HARNESS = r'''
#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

class String {
 public:
  String() = default;
  String(const char* s) : v(s ? s : "") {}
  const char* c_str() const { return v.c_str(); }
  size_t length() const { return v.length(); }
 private: std::string v;
};
enum { SAMOVAR_RECTIFICATION_MODE = 0, SAMOVAR_BEER_MODE = 2, SAMOVAR_NBK_MODE = 4, SAMOVAR_STARTVAL_BEER_START = 10, PROGRAM_WAIT_NONE = 0 };
enum { NOTIFY_MSG = 2, ALARM_MSG = 0, WARNING_MSG = 1 };
enum { UI_WAIT_MANUAL_RECT = 1, UI_WAIT_MANUAL_BEER = 2, UI_WAIT_RECT_DETECTOR = 5 };
enum { RUNTIME_PAIR_RESUMED = 0, RUNTIME_PAIR_ROW_CHANGE = 1, RUNTIME_PAIR_USER_STOP = 2, RUNTIME_PAIR_PROCESS_END = 3, RUNTIME_PAIR_ERROR = 4 };
static int Samovar_Mode, startval;
static bool PauseOn, PowerOn, alarm_event, program_Wait, program_Pause, beerManualPause;
static bool rectManualPauseActive, rectSecondPumpRunning, rectSecondPumpPaused;
static unsigned long t_min;
static unsigned TargetStepps, CurrrentStepps;
static unsigned short CurrrentStepperSpeed = 12;
static int pairBegin, pairEnd, pauseCalls, startCalls, stopCalls, closeModeCalls;
static int lastEnd = -1, lastClose = -1;
static bool stepperRunning, i2cResumeAccepted = true;
static const char* pause_text_ptr;
static int programWaitType;
static unsigned long millis() { return 100; }
static int pdMS_TO_TICKS(int x) { return x; }
static int stepper_safe_get_state() { return stepperRunning; }
static unsigned stepper_safe_get_target() { return TargetStepps; }
static unsigned stepper_safe_get_current() { return CurrrentStepps; }
static int stepper_safe_get_speed() { return 12; }
static void stepper_safe_stop() { stepperRunning = false; }
static void stepper_safe_set_max_speed(unsigned short) {}
static void stepper_safe_set_current(unsigned v) { CurrrentStepps = v; }
static void stepper_safe_set_target(unsigned v) { TargetStepps = v; }
static void stopService() { stopCalls++; stepperRunning = false; }
static void startService() { startCalls++; stepperRunning = true; }
static void reset_impurity_detector() {}
static bool rect_pause_second_i2c_pump() { rectSecondPumpPaused = rectSecondPumpRunning; return true; }
static bool rect_resume_second_i2c_pump() { return i2cResumeAccepted; }
static void rect_fail_second_i2c_pump(const char*) {}
static void runtime_pair_begin(int, const char*, int) { pairBegin++; }
static void runtime_pair_end(int, int outcome, const char*, int) { pairEnd++; lastEnd = outcome; }
static void runtime_pair_close_mode(int, int outcome, const char*, int) { closeModeCalls++; lastClose = outcome; }
static bool set_program_wait_type(int value, int) { programWaitType = value; return true; }
static void detector_on_manual_resume() {}
static char current_program_type() { return 'B'; }
static void SendMsg(const char*, int) {}
static void SendMsg(const String&, int) {}
template <typename T> static T max(T a, T b) { return a > b ? a : b; }

@PAUSE@
@ENTER@
@RESUME@
@MENU@

static void reset() {
  Samovar_Mode = SAMOVAR_RECTIFICATION_MODE; startval = 10; PauseOn = false; PowerOn = true;
  alarm_event = program_Wait = program_Pause = beerManualPause = rectManualPauseActive = false;
  rectSecondPumpRunning = rectSecondPumpPaused = false; stepperRunning = true; i2cResumeAccepted = true;
  pairBegin = pairEnd = pauseCalls = startCalls = stopCalls = closeModeCalls = 0; lastEnd = lastClose = -1;
  TargetStepps = 100; CurrrentStepps = 4; t_min = 99; programWaitType = 77;
}
static bool check(bool ok, const char* msg) { if (!ok) std::fprintf(stderr, "FAIL: %s\n", msg); return ok; }
static bool test_manual_modes() {
  reset(); enter_manual_pause();
  if (!check(PauseOn && rectManualPauseActive && pairBegin == 1, "RECT ручная пауза должна начать q1")) return false;
  reset(); Samovar_Mode = SAMOVAR_BEER_MODE; startval = 20; enter_manual_pause();
  return check(beerManualPause && !PauseOn && pairBegin == 1, "Beer ручная пауза должна начать только q2");
}
static bool test_rejected_i2c_resume() {
  reset(); PauseOn = true; rectManualPauseActive = true; rectSecondPumpRunning = true; stepperRunning = false; i2cResumeAccepted = false;
  resume_from_pause();
  return check(pairEnd == 0 && rectManualPauseActive && !stepperRunning,
               "отказ I2C продолжения не должен писать RESUMED или запускать отбор");
}
static bool test_menu_beer_manual_pause() {
  reset(); Samovar_Mode = SAMOVAR_BEER_MODE; startval = 20; menu_pause();
  if (!check(beerManualPause && !std::strcmp(pause_text_ptr, "Continue"), "Menu должен поставить Beer на ручную паузу")) return false;
  menu_pause();
  return check(!beerManualPause && !std::strcmp(pause_text_ptr, "Pause") && lastEnd == RUNTIME_PAIR_RESUMED,
               "Menu должен завершить Beer q2 только после снятия флага");
}
int main() {
  if (!test_manual_modes() || !test_rejected_i2c_resume() || !test_menu_beer_manual_pause()) return 1;
  std::puts("RECT/common hook checks passed"); return 0;
}
'''


def block(source: str, token: str) -> str:
    result, _ = extract_braced_block_after(source, token)
    return result


def compile_run(source: str, quiet: bool = False) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-ui-rect-pairs-") as temp:
        root = Path(temp)
        cpp, exe = root / "test.cpp", root / "test"
        cpp.write_text(source, encoding="utf-8")
        build = subprocess.run(["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", str(cpp), "-o", str(exe)], capture_output=True, text=True)
        if build.returncode:
            return build.returncode, build.stderr
        run = subprocess.run([str(exe)], capture_output=True, text=True)
        return run.returncode, run.stdout + run.stderr


def main() -> int:
    logic = (ROOT / "logic.h").read_text(encoding="utf-8")
    menu = (ROOT / "Menu.ino").read_text(encoding="utf-8")
    try:
        source = HARNESS.replace("@PAUSE@", "static void pause_withdrawal(bool Pause) {" + extract_function_body(logic, "void pause_withdrawal(bool Pause)") + "}")
        source = source.replace("@ENTER@", "static void enter_manual_pause() {" + extract_function_body(logic, "void enter_manual_pause()") + "}")
        source = source.replace("@RESUME@", "static void resume_from_pause() {" + extract_function_body(logic, "void resume_from_pause()") + "}")
        source = source.replace("@MENU@", "static void menu_pause() {" + extract_function_body(menu, "void menu_pause()") + "}")
    except ValueError as error:
        print(f"FAIL: source extraction: {error}", file=sys.stderr)
        return 1
    code, output = compile_run(source)
    if code:
        print("FAIL: RECT/common harness:\n" + output, file=sys.stderr)
        return 1
    print(output, end="")
    # Meaningful mutation: successful I2C gate is removed; rejected resume must now
    # violate the behavioural assertion rather than merely fail to compile.
    mutant = source.replace("if (!rect_resume_second_i2c_pump()) {", "if (false) {", 1)
    code, output = compile_run(mutant, quiet=True)
    expected = "отказ I2C продолжения не должен писать RESUMED или запускать отбор"
    if code == 0 or expected not in output:
        print("FAIL: мутация I2C-resume не была отклонена смысловым assert:\n" + output, file=sys.stderr)
        return 1

    # H/T — наблюдение. Извлекаем именно узкую production-ветку и исполняем её
    # при двух типах строки; hooks пары/паузы отсутствуют из-за факта, а не константы.
    try:
        ht = block((ROOT / "impurity_detector.h").read_text(encoding="utf-8"), "if (currentType == 'H' || currentType == 'T')")
    except ValueError as error:
        print(f"FAIL: H/T extraction: {error}", file=sys.stderr); return 1
    ht_cpp = r'''#include <cstdio>
struct Detector { int detectorStatus; float correctionFactor; int criticalConfirm; } impurityDetector;
int detector_idle_reason; const int DETECTOR_IDLE_HEADS=1, DETECTOR_IDLE_TAILS=2;
int pairBegin=0, pauseCalls=0; void runtime_pair_begin(int,const char*,int){pairBegin++;} void pause_withdrawal(bool){pauseCalls++;} bool check(bool x,const char*m){if(!x)std::fprintf(stderr,"FAIL: %s\n",m);return x;}
void tick(char currentType) { @BODY@ }
int main(){ impurityDetector={7,3,9}; tick('H'); if(!check(impurityDetector.detectorStatus==0&&impurityDetector.correctionFactor==1&&impurityDetector.criticalConfirm==0&&detector_idle_reason==1&&pairBegin==0&&pauseCalls==0,"H observation must not BEGIN or pause"))return 1; impurityDetector={7,3,9}; tick('T'); return check(impurityDetector.detectorStatus==0&&detector_idle_reason==2&&pairBegin==0&&pauseCalls==0,"T observation must not BEGIN or pause")?0:1; }'''.replace("@BODY@", "if (currentType == 'H' || currentType == 'T') {" + ht + "}")
    code, output = compile_run(ht_cpp)
    if code:
        print("FAIL: H/T observation harness:\n" + output, file=sys.stderr); return 1
    mutant = ht_cpp.replace("detector_idle_reason = currentType == 'H' ? DETECTOR_IDLE_HEADS : DETECTOR_IDLE_TAILS;", "detector_idle_reason = currentType == 'H' ? DETECTOR_IDLE_HEADS : DETECTOR_IDLE_TAILS; runtime_pair_begin(5, \"bad\", 0); pause_withdrawal(true);", 1)
    code, output = compile_run(mutant, quiet=True)
    if code == 0 or "H observation must not BEGIN or pause" not in output:
        print("FAIL: H/T mutation survived behavioural assert:\n" + output, file=sys.stderr); return 1
    print("H/T observation mutation rejected")

    # Аварийный hook также исполняется целиком: отключение питания обязано
    # произойти до ERROR-close, иначе пара ложно описывает ещё работающий аппарат.
    try:
        emergency = extract_function_body((ROOT / "alarm.h").read_text(encoding="utf-8"), "inline void perform_emergency_stop()")
    except ValueError as error:
        print(f"FAIL: emergency extraction: {error}", file=sys.stderr); return 1
    emergency_cpp = r'''#include <cstdio>
#include <cstring>
struct String { String(const char*) {} };
enum { ALARM_MSG=0, SAMOVAR_NBK_MODE=4, RUNTIME_PAIR_ERROR=4, RELE_CHANNEL2=2 };
struct Setup { bool rele2; } SamSetup = {false};
static int Samovar_Mode=0, order=0, powerOffOrder=0, closeOrder=0; static bool alarm_event=false, mixer_status=true;
static bool pending_emergency_stop_flag=true, pending_emergency_stop_reason_flag=true; static char pending_emergency_stop_reason[32]="alarm";
const int EMERGENCY_STOP_REASON_LEN=32; static int emergencyStopMux;
static void portENTER_CRITICAL(int*) {} static void portEXIT_CRITICAL(int*) {}
static void SendMsg(String,int) {} static void nbk_emergency_finish() {} static void set_power(bool on){if(!on)powerOffOrder=++order;}
static void open_valve(bool,bool){} static void stopService(){} static void attempt_i2c_pump_emergency_stop(){}
static void digitalWrite(int,bool){} static void reset_process_state(){} static void cancel_pending_emergency_actions(){}
static void runtime_pair_close_mode(int,int,const char*,int){closeOrder=++order;}
void perform_emergency_stop() { @BODY@ }
int main(){perform_emergency_stop(); if(!(alarm_event&&powerOffOrder>0&&closeOrder>powerOffOrder)){std::fprintf(stderr,"FAIL: аварийный off должен предшествовать ERROR close\\n");return 1;} return 0;}'''.replace("@BODY@", emergency)
    code, output = compile_run(emergency_cpp)
    if code:
        print("FAIL: emergency hook harness:\n" + output, file=sys.stderr); return 1
    mutant = emergency_cpp.replace("set_power(false);", "set_power(true);", 1)
    code, output = compile_run(mutant, quiet=True)
    expected = "аварийный off должен предшествовать ERROR close"
    if code == 0 or expected not in output:
        print("FAIL: emergency-off mutation survived behavioural assert:\n" + output, file=sys.stderr); return 1
    print("emergency off-before-close mutation rejected")

    # PROGRAM_END закрывает активные пары до сброса состояния.
    try:
        program_end = block(logic, "if (num >= PROGRAM_MAX)")
    except ValueError as error:
        print(f"FAIL: run_program hook extraction: {error}", file=sys.stderr); return 1
    program_cpp = r'''#include <cstdio>
#include <cstdint>
enum { SAMOVAR_RECTIFICATION_MODE=0, RUNTIME_PAIR_PROCESS_END=3, RUNTIME_PAIR_ROW_CHANGE=1, RUNTIME_PAIR_ERROR=4, NOTIFY_MSG=2, WARNING_MSG=1, PROGRAM_MAX=10, SAMOVAR_STARTVAL_IDLE=0 };
static uint8_t ProgramNum=4; static int startval=9; static bool rectSecondPumpHeadsRow=true,rectSecondPumpPaused=true; static unsigned TargetStepps=5; static int closeOutcome=-1,closeCalls=0;
static bool rect_stop_second_i2c_pump_if_running(){return true;} static void rect_fail_second_i2c_pump(const char*){} static void runtime_pair_close_mode(int,int o,const char*,int){closeCalls++;closeOutcome=o;}
static void reset_rect_program_pause_state(){} static void stopService(){} static void stepper_safe_stop_reset(){} static void set_capacity(int){} static bool request_data_log_close(){return true;} static void SendMsg(const char*,int){} static void stop_process(const char*){} static unsigned stepper_safe_get_target(){return 42;}
void end_hook(uint8_t num) { @END@ }
bool check(bool x,const char*m){if(!x)std::fprintf(stderr,"FAIL: %s\\n",m);return x;}
int main(){end_hook(PROGRAM_MAX);return check(closeCalls==1&&closeOutcome==RUNTIME_PAIR_PROCESS_END&&ProgramNum==0&&startval==0,"PROGRAM_END must close PROCESS_END before reset")?0:1;}'''.replace("@END@", "if (num >= PROGRAM_MAX) {" + program_end + "}")
    code, output = compile_run(program_cpp)
    if code:
        print("FAIL: run_program hook harness:\n" + output, file=sys.stderr); return 1
    mutant = program_cpp.replace(
        "runtime_pair_close_mode(SAMOVAR_RECTIFICATION_MODE, RUNTIME_PAIR_PROCESS_END,",
        "runtime_pair_close_mode(SAMOVAR_RECTIFICATION_MODE, RUNTIME_PAIR_ERROR,", 1)
    code, output = compile_run(mutant, quiet=True)
    expected = "PROGRAM_END must close PROCESS_END before reset"
    if code == 0 or expected not in output:
        print("FAIL: process-end mutation survived behavioural assert:\n" + output, file=sys.stderr); return 1
    print("process-end outcome mutation rejected")

    try:
        pause_row = block(logic, "else if (program[num].WType == 'P')")
    except ValueError as error:
        print(f"FAIL: P-row extraction: {error}", file=sys.stderr); return 1
    pause_cpp = r'''#include <cstdio>
#include <cstdint>
struct String { String(){} String(const char*){} String(unsigned){} String& operator+=(const String&){return *this;} }; String operator+(String a,const String&){return a;}
enum { UI_WAIT_RECT_PROGRAM_PAUSE=6, NOTIFY_MSG=2 }; struct Row { unsigned Volume; }; static Row program[1]={{17}}; static unsigned num=0; struct Sensor{float BodyTemp;}; static Sensor SteamSensor,PipeSensor,WaterSensor,TankSensor;
static unsigned long now=1000,t_min=0; static bool program_Pause=false; static int pairBegin=0,lastReason=-1,stops=0; static unsigned short CurrrentStepperSpeed=12; static String p_s;
static unsigned long millis(){return now;} static void runtime_pair_begin(int reason,const char*,int){pairBegin++;lastReason=reason;} static void stopService(){stops++;} static void stepper_safe_set_max_speed(int){} static void stepper_safe_stop_reset(){}
void p_hook(){ @BODY@ } bool check(bool x,const char*m){if(!x)std::fprintf(stderr,"FAIL: %s\\n",m);return x;} int main(){p_hook();return check(program_Pause&&pairBegin==1&&lastReason==UI_WAIT_RECT_PROGRAM_PAUSE&&stops==1&&t_min==18000&&CurrrentStepperSpeed==0,"P row must begin q6 and stop withdrawal")?0:1;}'''.replace("@BODY@", pause_row)
    code, output = compile_run(pause_cpp)
    if code:
        print("FAIL: P-row hook harness:\n" + output, file=sys.stderr); return 1
    mutant = pause_cpp.replace("runtime_pair_begin(UI_WAIT_RECT_PROGRAM_PAUSE", "/* no q6 */ runtime_pair_begin(0", 1)
    code, output = compile_run(mutant, quiet=True)
    expected = "P row must begin q6 and stop withdrawal"
    if code == 0 or expected not in output:
        print("FAIL: P-row q6 mutation survived behavioural assert:\n" + output, file=sys.stderr); return 1
    print("P-row q6 mutation rejected")

    try:
        lua_row = block(logic, "if (program[num].WType == 'L')")
    except ValueError as error:
        print(f"FAIL: Lua-row extraction: {error}", file=sys.stderr); return 1
    lua_cpp = r'''#include <cstdio>
#include <cstdint>
#define USE_LUA
struct String { String(){} String(const char*){} String(unsigned){} String& operator+=(const String&){return *this;} }; String operator+(String a,const String&){return a;}
enum { PROGRAM_END=255, UI_WAIT_LUA_KNOWN=23, SAMOVAR_RECTIFICATION_MODE=0, RUNTIME_PAIR_ROW_CHANGE=1, NOTIFY_MSG=2, ALARM_MSG=0 }; static bool accepted=true; static int pairBegin=0,lastReason=-1,stops=0,endCalls=0,closeCalls=0;
static unsigned long millis(){return 50;} static void stopService(){stops++;} static void stepper_safe_stop_reset(){} static bool lua_sequence_stage_begin(unsigned,unsigned long){return accepted;} static void runtime_pair_begin(int reason,const char*,int){pairBegin++;lastReason=reason;} static void runtime_pair_close_mode(int,int,const char*,int){closeCalls++;} static void SendMsg(const String&,int){} static void run_program(uint8_t);
void lua_hook(uint8_t num){ @BODY@ } static void run_program(uint8_t n){endCalls++;if(n==PROGRAM_END)return;} bool check(bool x,const char*m){if(!x)std::fprintf(stderr,"FAIL: %s\\n",m);return x;} int main(){lua_hook(0);if(!check(accepted&&pairBegin==1&&lastReason==UI_WAIT_LUA_KNOWN&&closeCalls==1&&stops==1&&endCalls==0,"accepted Lua row must close old pair then begin q23"))return 1;accepted=false;pairBegin=closeCalls=endCalls=0;lua_hook(0);return check(pairBegin==0&&closeCalls==0&&endCalls==1,"rejected Lua row must not close old pair or begin q23")?0:1;}'''.replace("@BODY@", lua_row)
    code, output = compile_run(lua_cpp)
    if code:
        print("FAIL: Lua-row hook harness:\n" + output, file=sys.stderr); return 1
    mutant = lua_cpp.replace(
        'runtime_pair_close_mode(SAMOVAR_RECTIFICATION_MODE, RUNTIME_PAIR_ROW_CHANGE,\n'
        '                            "Переход к следующей строке", NOTIFY_MSG);',
        '(void)0;', 1)
    code, output = compile_run(mutant, quiet=True)
    expected = "accepted Lua row must close old pair then begin q23"
    if code == 0 or expected not in output:
        print("FAIL: Lua q23 mutation survived behavioural assert:\n" + output, file=sys.stderr); return 1
    print("accepted/rejected Lua row mutation rejected")

    try:
        lua_result = block(logic, "if (program_type_at(ProgramNum) == 'L')")
    except ValueError as error:
        print(f"FAIL: Lua-result extraction: {error}", file=sys.stderr); return 1
    lua_result_cpp = r'''#include <cstdio>
#include <cstdint>
#define USE_LUA
enum { PROGRAM_END=255, UI_WAIT_LUA_KNOWN=23, RUNTIME_PAIR_ROW_CHANGE=1, RUNTIME_PAIR_ERROR=4, NOTIFY_MSG=2, ALARM_MSG=0 };
enum LuaSequenceStageResult { LUA_SEQUENCE_STAGE_NONE, LUA_SEQUENCE_STAGE_ADVANCE, LUA_SEQUENCE_STAGE_TIMEOUT, LUA_SEQUENCE_STAGE_FAILED };
static uint8_t ProgramNum=0,nextValue=3,runValue=99; static LuaSequenceStageResult result=LUA_SEQUENCE_STAGE_ADVANCE; static int endReason=-1,endOutcome=-1,endCalls=0;
static unsigned long millis(){return 9;} static char program_type_at(uint8_t){return 'L';} static LuaSequenceStageResult lua_sequence_stage_tick(unsigned long,unsigned short,uint8_t& n){n=nextValue;return result;} static void runtime_pair_end(int r,int o,const char*,int){endCalls++;endReason=r;endOutcome=o;} static void SendMsg(const char*,int){} static void run_program(uint8_t n){runValue=n;} struct Row { unsigned Time; }; static Row program[1]={{5}};
void lua_result_hook(){ @BODY@ } bool check(bool x,const char*m){if(!x)std::fprintf(stderr,"FAIL: %s\\n",m);return x;} int main(){lua_result_hook();if(!check(endCalls==1&&endReason==23&&endOutcome==1&&runValue==3,"Lua ADVANCE must close q23 as ROW_CHANGE"))return 1;result=LUA_SEQUENCE_STAGE_TIMEOUT;endCalls=0;runValue=99;lua_result_hook();return check(endCalls==1&&endReason==23&&endOutcome==4&&runValue==255,"Lua timeout must close q23 as ERROR")?0:1;}'''.replace("@BODY@", lua_result)
    code, output = compile_run(lua_result_cpp)
    if code:
        print("FAIL: Lua-result hook harness:\n" + output, file=sys.stderr); return 1
    mutant = lua_result_cpp.replace("runtime_pair_end(UI_WAIT_LUA_KNOWN", "runtime_pair_end(0", 1)
    code, output = compile_run(mutant, quiet=True)
    expected = "Lua ADVANCE must close q23 as ROW_CHANGE"
    if code == 0 or expected not in output:
        print("FAIL: Lua-result q23 mutation survived behavioural assert:\n" + output, file=sys.stderr); return 1
    print("Lua q23 result mutation rejected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
