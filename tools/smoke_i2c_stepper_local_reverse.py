#!/usr/bin/env python3
"""T25.3: локальная (без I2C-платы) ветка set_stepper_target() обязана
переносить параметр direction на физическую полярность DIR через
stepper_safe_reverse() - иначе направление молча теряется, когда I2C-степпер
не отвечает, хотя I2C-ветка этой же функции его честно применяет через
I2CSTEPPER_FLAG_DIRECTION.

Компилирует РЕАЛЬНОЕ тело set_stepper_target(), извлечённое из I2CStepper.h,
с моком stepper_safe_*/stopService/startService, которые пишут в общий лог
вызовов - так проверяется и факт вызова reverse(), и его значение, и порядок
(между stopService() и startService(), до stepper_safe_set_motion()).
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []

i2c_text = (ROOT / "I2CStepper.h").read_text(encoding="utf-8", errors="ignore")

try:
    set_target_body = extract_function_body(i2c_text, "inline bool set_stepper_target(")
except ValueError as exc:
    errors.append(str(exc))
    set_target_body = ""

if errors:
    print("i2c_stepper local reverse smoke failed to extract source:")
    for err in errors:
        print(f" - {err}")
    sys.exit(1)

HARNESS = r'''
#include <cstdint>
#include <iostream>
#include <string>
#include <vector>

using TickType_t = int;

#define I2CSTEPPER_FLAG_DIRECTION 0x04
enum I2CStepMode { I2CSTEP_MODE_PUMP = 2, I2CSTEP_MODE_FILLING = 3 };

struct I2CStepperDevice {
  bool present = false;
  uint8_t address = 0;
  uint8_t role = 0;
  uint8_t mode = 0;
  uint8_t caps = 0;
  uint8_t status = 0;
  uint8_t error = 0;
  uint8_t relayMask = 0;
  uint8_t sensorFlags = 0;
  uint8_t optionFlags = 0;
  uint8_t commandSeq = 0;
  uint8_t ackSeq = 0;
  uint16_t mixerRpm = 0;
  uint16_t mixerRunSec = 0;
  uint16_t mixerPauseSec = 0;
  uint16_t pumpMlHour = 0;
  uint16_t pumpPauseSec = 0;
  uint16_t fillingMl = 0;
  uint16_t fillingMlHour = 0;
  uint16_t stepsPerMl = 0;
  uint32_t remaining = 0;
  uint16_t currentSpeed = 0;
  uint8_t refreshFailStreak = 0;
};
static I2CStepperDevice i2cStepperPump;

volatile uint16_t I2CStepperSpeed = 0;
volatile uint16_t CurrrentStepperSpeed = 0;
volatile uint16_t I2CPumpCmdSpeed = 0;
volatile uint32_t I2CPumpTargetSteps = 0;
volatile float I2CPumpTargetMl = 0;

// Управляет тем, идёт ли set_stepper_target() в I2C-ветку или в локальную -
// в этом тесте всегда false, чтобы гарантированно проверять локальный путь
// (тот самый, где T25.3 чинит потерю direction).
static bool refreshShouldSucceed = false;
inline bool i2c_stepper_refresh(I2CStepperDevice&, bool = false, TickType_t = 0) {
  return refreshShouldSucceed;
}

// I2C-ветка тела функции не выполняется в этом тесте (refresh всегда
// возвращает false), но должна компилироваться - поэтому мок присутствует.
inline bool i2c_stepper_config_begin(const I2CStepperDevice&) { return true; }
inline void i2c_stepper_config_end(const I2CStepperDevice&) {}
inline bool i2c_stepper_stop(I2CStepperDevice&) { return true; }
inline bool i2c_stepper_start(I2CStepperDevice&) { return true; }
inline uint16_t i2c_stepper_mlh_from_step_speed(uint16_t) { return 0; }
inline uint16_t i2c_stepper_steps_per_ml() { return 1; }
inline uint16_t i2c_stepper_ml_from_steps(uint32_t) { return 0; }

static std::vector<std::string> callLog;

void stopService(void) { callLog.push_back("stopService"); }
void startService(void) { callLog.push_back("startService"); }

inline void stepper_safe_reverse(bool val) {
  callLog.push_back(val ? "reverse:1" : "reverse:0");
}
inline void stepper_safe_set_motion(float speed, int32_t current, int32_t target) {
  callLog.push_back("set_motion:" + std::to_string((int)speed) + "," +
                     std::to_string(current) + "," + std::to_string(target));
}
inline void stepper_safe_stop_reset() { callLog.push_back("stop_reset"); }

inline bool set_stepper_target(
    uint16_t spd,
    uint8_t direction,
    uint32_t target,
    bool requireI2c) {
@SET_STEPPER_TARGET_BODY@
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static int index_of(const std::string& token) {
  for (size_t i = 0; i < callLog.size(); i++) {
    if (callLog[i] == token) return (int)i;
  }
  return -1;
}

int main() {
  refreshShouldSucceed = false;

  // Ожидания зависят от STEPPER_REVERSE: этот флаг компенсирует физическую проводку
  // (sensorinit.h), поэтому локальная ветка обязана инвертировать смысл direction.
  // Харнесс собирается дважды - без флага и с ним, иначе ветка #ifdef не проверяется.
#ifdef STEPPER_REVERSE
  const std::string expectDirNonZero = "reverse:0";
  const std::string expectDirZero = "reverse:1";
#else
  const std::string expectDirNonZero = "reverse:1";
  const std::string expectDirZero = "reverse:0";
#endif

  // direction=1 (ненулевое значение) - I2C-ветка в этом же файле трактует это
  // как "выставить I2CSTEPPER_FLAG_DIRECTION"; локальная ветка обязана
  // передать тот же смысл в reverse(direction != 0) при отсутствии STEPPER_REVERSE.
  callLog.clear();
  bool ok1 = set_stepper_target(50, 1, 1000, false);
  check(ok1, "local branch must report success when I2C is unavailable and requireI2c is false");
  check(index_of(expectDirNonZero) >= 0, "reverse must map direction!=0 per STEPPER_REVERSE");
  check(index_of("stopService") >= 0 && index_of(expectDirNonZero) > index_of("stopService"),
        "reverse must be called after stopService (motor already stopped)");
  check(index_of("set_motion:50,0,1000") >= 0 &&
        index_of(expectDirNonZero) < index_of("set_motion:50,0,1000"),
        "reverse must be called before stepper_safe_set_motion (see spec: right before it)");
  check(index_of("startService") >= 0 &&
        index_of("set_motion:50,0,1000") < index_of("startService"),
        "startService must run after set_motion");

  // direction=0 - reverse must reflect false, not stay stuck at the previous value.
  callLog.clear();
  bool ok2 = set_stepper_target(50, 0, 1000, false);
  check(ok2, "local branch must report success for direction=0 too");
  check(index_of(expectDirZero) >= 0, "reverse must map direction==0 per STEPPER_REVERSE");
  check(index_of(expectDirNonZero) < 0, "direction=0 must not log the opposite reverse value");

  // spd=0 - stop path; reverse is not part of the spec here, only stop_reset.
  callLog.clear();
  bool ok3 = set_stepper_target(0, 1, 1000, false);
  check(ok3, "stop path (spd=0) must report success");
  check(index_of("stop_reset") >= 0, "spd=0 must call stepper_safe_stop_reset");

  if (failures != 0) return 1;
  std::cout << "i2c_stepper local reverse checks passed\n";
  return 0;
}
'''


def build_source() -> str:
    return HARNESS.replace("@SET_STEPPER_TARGET_BODY@", set_target_body)


def run() -> None:
    compiler = shutil.which("g++")
    if compiler is None:
        errors.append("g++ is required for the i2c_stepper local reverse harness")
        return
    with tempfile.TemporaryDirectory(prefix="samovar-i2c-local-reverse-") as tmp:
        tmp_path = Path(tmp)
        source_path = tmp_path / "local_reverse.cpp"
        source_path.write_text(build_source(), encoding="utf-8")
        # Две сборки: без STEPPER_REVERSE и с ним. Без второй ветка #ifdef в
        # set_stepper_target() не компилируется ни разу, и поломка инверсии
        # (та самая, что защищает компенсацию проводки) прошла бы незамеченной.
        for label, extra in (("default", []), ("STEPPER_REVERSE", ["-DSTEPPER_REVERSE"])):
            binary = tmp_path / f"local_reverse_{label}"
            compile_result = subprocess.run(
                [compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror"] + extra +
                [str(source_path), "-o", str(binary)],
                capture_output=True,
                text=True,
                check=False,
            )
            if compile_result.returncode != 0:
                errors.append(f"local reverse harness compile failed ({label}):\n" +
                              compile_result.stdout + compile_result.stderr)
                continue
            run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
            if run_result.returncode != 0:
                errors.append(f"local reverse harness runtime checks failed ({label}):\n" +
                              run_result.stdout + run_result.stderr)


run()

if errors:
    print("i2c_stepper local reverse smoke failed:")
    for err in errors:
        print(f" - {err}")
    sys.exit(1)

print("i2c_stepper local reverse smoke passed")
