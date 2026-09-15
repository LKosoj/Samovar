#!/usr/bin/env python3
"""Поведенческая проверка [T10]: сброс точки отсчёта статистики объёма на входе в S.

Тест вытаскивает РЕАЛЬНЫЙ блок кода S-ветки run_nbk_program
("if (program[ProgramNum].WType == 'S') { ... }") и РЕАЛЬНОЕ тело SetSpeed —
через extract_braced_block_after / extract_function_body, без переписывания
логики. Харнесс отдельно моделирует принятие составной команды и её
подтверждённое применение.

Регресс, который тест защищает: до задачи 10 time_speed мог оставаться
"протухшим" с момента старта всей программы НБК (ProgramNum==0, ещё на
прогреве H), и первый вызов SetSpeed после входа на Ручную настройку (S)
засчитывал в stats.totalVolume ВЕСЬ прошедший на прогреве интервал, как если
бы всё это время текла жидкость с текущей скоростью подачи. Задача 10
переносит точку отсчёта (time_speed = millis();) на сам момент входа в S,
поэтому SetSpeed сразу после входа обязан прибавить к totalVolume ~0, вне
зависимости от того, сколько времени "протухания" накопилось на прогреве.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body

ROOT = Path(__file__).resolve().parents[1]

ANCHOR_S = "if (program[ProgramNum].WType == 'S') {"
SETSPEED_SIGNATURE = "ActuatorCommandResult SetSpeed(float Speed) {"

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>
#include <cmath>

using ProgramType = char;
enum ActuatorCommandResult {
  ACTUATOR_COMMAND_ACCEPTED = 0,
  ACTUATOR_COMMAND_PENDING,
  ACTUATOR_COMMAND_APPLIED,
  ACTUATOR_COMMAND_FAILED,
};

static uint32_t fakeMillis = 0;
uint32_t millis() { return fakeMillis; }

uint32_t time_speed = 0;
uint32_t begintime = 12345; // заведомо не 0 — проверим, что S-ветка обнуляет

struct StatsProbe {
  float totalVolume;
  float activeVolume;
  uint32_t activeFeedMs;
};
static StatsProbe stats;

struct ProgramRow { float Power; float Speed; };
static ProgramRow program[4];
static uint8_t ProgramNum = 0;

float nbk_P = 0;
uint16_t nbk_opt_iter = 0;
// [Ремонт-2026-09-02 П6] латч захлёба Ручной настройки не должен доживать до нового входа в S.
bool manual_overflow = false;
uint32_t nbk_manual_overflow_until = 0;
enum NbkActuatorDeadlineTarget : uint8_t {
  NBK_ACTUATOR_NO_DEADLINE = 0,
};

static ProgramType currentTypeValue = 'S'; // не 'H' — прогрев уже позади
ProgramType current_program_type() { return currentTypeValue; }

static double liquidRateValue = 60.0; // условная скорость подачи (не 0, чтобы разница во времени была заметна)
double i2c_get_liquid_rate_by_step(uint32_t) { return liquidRateValue; }
struct I2CStepperV3Config { uint32_t stepsPerMl; };
struct I2CStepperV3StatusSnapshot { uint32_t currentSpeedStepsPerSec; };
struct I2CStepperDevice {
  uint8_t address;
  bool present;
  I2CStepperV3Config config;
  I2CStepperV3StatusSnapshot status;
};
static I2CStepperDevice selectedPump = {2, true, {100}, {600}};
I2CStepperDevice* i2c_stepper_selected_pump() { return &selectedPump; }
bool i2c_stepper_refresh(I2CStepperDevice& device) { return device.present; }
static int stepperTargetCalls = 0;
bool set_stepper_target(uint32_t speed, uint8_t, uint32_t, bool requireI2c) {
  stepperTargetCalls++;
  if (!requireI2c) return false;
  selectedPump.status.currentSpeedStepsPerSec = speed;
  return true;
}
bool start_second_i2c_pump(float rate, uint16_t volume) {
  stepperTargetCalls++;
  if (rate <= 0.0f || volume != 0) return false;
  selectedPump.status.currentSpeedStepsPerSec = uint32_t(rate * 10.0f);
  return true;
}

// Конверсия мощности не является предметом этого теста.
float toPower(float v) { return v; }
static int scheduleCalls = 0;
static float scheduledSpeed = 0;
bool nbk_schedule_actuator_command(
    float,
    float speed,
    NbkActuatorDeadlineTarget,
    uint32_t,
    uint16_t) {
  scheduleCalls++;
  scheduledSpeed = speed;
  return true;
}
void nbk_enter_safe_wait(const char*) {}

// Заглушка SetSpeed НЕ переопределяется — сама функция ниже собрана из
// РЕАЛЬНОГО тела SetSpeed (nbk.h), поэтому после подтверждения составной
// команды вызывается настоящая логика учёта статистики.
ActuatorCommandResult SetSpeed(float Speed) {
@SETSPEED_BODY@
}

static void enter_s_stage() {
@S_BODY@
}

static int failures = 0;

static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

// stale_gap_ms — на сколько "протухла" time_speed к моменту входа в S
// (т.е. сколько реально прошло на прогреве H, пока time_speed не трогали).
static void test_no_heatup_leak_for(uint32_t stale_gap_ms) {
  fakeMillis = 10 * 60 * 60 * 1000UL; // произвольная "текущая" точка времени
  time_speed = fakeMillis - stale_gap_ms; // протухшая точка отсчёта с прогрева
  begintime = 12345;
  stats.totalVolume = 0;
  program[0].Power = 500;
  program[0].Speed = 1;
  ProgramNum = 0;
  scheduleCalls = 0;
  stepperTargetCalls = 0;
  // "Застрявший" латч захлёба от предыдущей сессии Ручной настройки.
  manual_overflow = true;
  nbk_manual_overflow_until = fakeMillis + 999999UL;

  enter_s_stage();
  check(!manual_overflow,
        "РЕГРЕСС [П6]: вход в S обязан сбросить латч захлёба прошлой Ручной настройки");
  check(nbk_manual_overflow_until == 0,
        "РЕГРЕСС [П6]: вход в S обязан обнулить дедлайн латча захлёба");
  check(scheduleCalls == 1, "вход в S обязан принять одну составную команду");
  check(stepperTargetCalls == 0,
        "ACCEPTED не должен применять насос до подтверждения регулятора");
  check(SetSpeed(scheduledSpeed) == ACTUATOR_COMMAND_APPLIED,
        "подтверждённый этап S должен применить насос");

  check(begintime == 0, "вход в S обязан сбросить begintime в 0");
  check(time_speed == fakeMillis, "вход в S обязан выставить time_speed = millis() (точку входа), а не оставить протухшее значение");
  // Без фикса приращение было бы ~ liquidRateValue * stale_gap_ms / 3600000,
  // т.е. заметно разным для 10 минут и для 1 минуты. С фиксом SetSpeed видит
  // разницу (millis() на входе в S) - (time_speed, тут же выставленный тем же
  // millis()) = 0, поэтому приращение должно быть РОВНО 0 независимо от
  // stale_gap_ms.
  check(stats.totalVolume == 0.0f,
        "РЕГРЕСС: протухший интервал прогрева не должен попадать в totalVolume после входа в S");
  check(stepperTargetCalls == 1, "вход в S обязан один раз выставить целевую скорость шагового двигателя");
}

int main() {
  test_no_heatup_leak_for(10UL * 60 * 1000); // протухло 10 минут
  test_no_heatup_leak_for(1UL * 60 * 1000);  // протухла 1 минута — другое значение
  if (failures != 0) return 1;
  std::cout << "nbk stats heatup exclusion behaviour checks passed\n";
  return 0;
}
'''


def build_harness(s_body_override: str | None = None) -> str:
    source = (ROOT / "nbk.h").read_text(encoding="utf-8")
    s_body, _ = extract_braced_block_after(source, ANCHOR_S)
    s_body = s_body.replace("\r\n", "\n")
    if s_body_override is not None:
        s_body = s_body_override
    setspeed_body = extract_function_body(source, SETSPEED_SIGNATURE)
    setspeed_body = setspeed_body.replace("\r\n", "\n")

    harness = HARNESS_TEMPLATE.replace("@S_BODY@", s_body)
    harness = harness.replace("@SETSPEED_BODY@", setspeed_body)
    return harness


def compile_and_run(harness: str) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix="samovar-nbk-stats-heatup-exclusion-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "nbk_stats_heatup_exclusion_test.cpp"
        binary = temp / "nbk_stats_heatup_exclusion_test"
        source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            [
                "g++",
                "-std=c++11",
                "-Wall",
                "-Wextra",
                "-Werror",
                str(source),
                "-o",
                str(binary),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            return compile_result
        return subprocess.run(
            [str(binary)], capture_output=True, text=True, check=False
        )


def main() -> int:
    try:
        harness = build_harness()
        s_body, _ = extract_braced_block_after(
            (ROOT / "nbk.h").read_text(encoding="utf-8"), ANCHOR_S
        )
        s_body = s_body.replace("\r\n", "\n")
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    result = compile_and_run(harness)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    if result.returncode != 0:
        return result.returncode

    mutation_anchor = "time_speed = millis();"
    mutated_s = s_body.replace(mutation_anchor, "time_speed = 1;", 1)
    if mutated_s == s_body:
        print("FAIL: S-entry timing mutation anchor missing", file=sys.stderr)
        return 1
    mutated = compile_and_run(build_harness(mutated_s))
    if mutated.returncode == 0:
        print("FAIL: S-entry timing mutation survived", file=sys.stderr)
        return 1
    if "протухший интервал прогрева" not in mutated.stdout + mutated.stderr:
        print("FAIL: S-entry timing mutation failed for an unrelated reason", file=sys.stderr)
        print(mutated.stdout + mutated.stderr, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
