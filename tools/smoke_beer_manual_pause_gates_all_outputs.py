#!/usr/bin/env python3
"""Поведенческая проверка П12: единая точка входа ручной паузы в beer_stage_tick().

[Находка] Раньше пауза обрабатывалась в ПЯТИ разных местах по-разному: 'F'
глушила всё и выходила; 'M'/'P' и 'B' гасили только нагрев; 'C' паузу не
проверяла вообще (клапан и насос охлаждения продолжали работать);
check_mixer_state() паузу тоже не проверяла. Фикс вводит одну точку входа в
beer_stage_tick() сразу ПОСЛЕ beer_update_stage_idle() (простой строки
продолжает копиться) и ДО разбора по типам строки: для M/P/B/C/F ручная
пауза одним вызовом beer_pause_fermentation_outputs() выключает нагрев,
клапан, насос охлаждения и мешалку, и строка не продвигается дальше.

Тест извлекает РЕАЛЬНЫЙ текст этой точки входа из beer_stage_tick() (через
extract_braced_block_after) и РЕАЛЬНЫЕ тела beer_pause_fermentation_outputs()
/ beer_safe_lua_outputs() / beer_set_cooling_outputs() / beer_set_cooling_pump()
(через extract_function_body) - без переписывания логики. Извлечённый гейт
оборачивается в функцию с маркером "после гейта", который наращивается,
только если управление прошло МИМО гейта (т.е. return внутри if не сработал).
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body

ROOT = Path(__file__).resolve().parents[1]

GATE_TOKEN = "if (beerManualPause && (currentType == 'M'"
PAUSE_OUTPUTS_SIGNATURE = "inline bool beer_pause_fermentation_outputs()"
SAFE_OUTPUTS_SIGNATURE = "inline ActuatorCommandResult beer_safe_lua_outputs()"
COOLING_OUTPUTS_SIGNATURE = "inline ActuatorCommandResult beer_set_cooling_outputs(bool active)"
COOLING_PUMP_SIGNATURE = "inline ActuatorCommandResult beer_set_cooling_pump(bool active)"

HARNESS_TEMPLATE = r'''
#include <iostream>
#include <string>

#define USE_WATER_PUMP

enum ActuatorCommandResult {
  ACTUATOR_COMMAND_ACCEPTED = 0,
  ACTUATOR_COMMAND_PENDING,
  ACTUATOR_COMMAND_APPLIED,
  ACTUATOR_COMMAND_FAILED,
};

using ProgramType = char;

static bool beerManualPause = false;
static bool valve_status = false;
static bool beerCoolingPumpActive = false;
static bool heaterOutput = true;
static int heaterCalls = 0;
static int mixerCalls = 0;
static bool lastMixerState = true;
static int abortCalls = 0;
static std::string lastAbortReason;
static int afterGateReached = 0;
static unsigned long beerMixerPauseSinceMs = 0;  // [Дефект 2 code review] см. beer.h
static unsigned long fakeMillis = 1000;
unsigned long millis() { return fakeMillis; }

static ActuatorCommandResult valveResult = ACTUATOR_COMMAND_APPLIED;
static ActuatorCommandResult pumpResult = ACTUATOR_COMMAND_APPLIED;
static ActuatorCommandResult mixerResult = ACTUATOR_COMMAND_APPLIED;

void setHeaterPosition(bool state) {
  heaterOutput = state;
  heaterCalls++;
}

ActuatorCommandResult open_valve(bool state, bool) {
  if (valveResult == ACTUATOR_COMMAND_APPLIED) valve_status = state;
  return valveResult;
}

ActuatorCommandResult set_pump_pwm(float) {
  return pumpResult;
}

ActuatorCommandResult set_mixer_state(bool state, bool) {
  mixerCalls++;
  lastMixerState = state;
  return mixerResult;
}

void request_emergency_stop(const char*) {}

void beer_abort_config_error(const char* reason) {
  abortCalls++;
  lastAbortReason = reason;
}

@COOLING_PUMP@

@COOLING_OUTPUTS@

@SAFE_OUTPUTS@

@PAUSE_OUTPUTS@

static void run_gate(ProgramType currentType) {
  const unsigned long nowMs = millis();
@GATE@
  afterGateReached++;
}

static int failures = 0;
static void check(bool condition, const std::string& message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture() {
  beerManualPause = false;
  valve_status = true;
  beerCoolingPumpActive = true;
  heaterOutput = true;
  heaterCalls = 0;
  mixerCalls = 0;
  lastMixerState = true;
  abortCalls = 0;
  lastAbortReason.clear();
  afterGateReached = 0;
  beerMixerPauseSinceMs = 0;
  fakeMillis = 1000;
  valveResult = ACTUATOR_COMMAND_APPLIED;
  pumpResult = ACTUATOR_COMMAND_APPLIED;
  mixerResult = ACTUATOR_COMMAND_APPLIED;
}

int main() {
  // Гейтуемые типы: M, P, B, C, F - при активной ручной паузе КАЖДЫЙ должен
  // выключить клапан, насос охлаждения, мешалку и нагрев, и НЕ пройти дальше
  // (afterGateReached остаётся 0 - сработал return внутри if).
  const char gatedTypes[] = {'M', 'P', 'B', 'C', 'F'};
  for (char t : gatedTypes) {
    reset_fixture();
    beerManualPause = true;
    run_gate(t);
    check(afterGateReached == 0, std::string("РЕГРЕСС: тип '") + t + "' должен был остановиться на гейте паузы");
    check(!valve_status, std::string("РЕГРЕСС: тип '") + t + "' не закрыл клапан охлаждения на паузе");
    check(!beerCoolingPumpActive, std::string("РЕГРЕСС: тип '") + t + "' не выключил насос охлаждения на паузе");
    check(!heaterOutput && heaterCalls == 1, std::string("РЕГРЕСС: тип '") + t + "' не выключил нагрев на паузе");
    check(mixerCalls == 1 && !lastMixerState, std::string("РЕГРЕСС: тип '") + t + "' не выключил мешалку на паузе");
    check(abortCalls == 0, std::string("тип '") + t + "' не должен был аварийно остановить варку при успешном выключении");
  }

  // Негейтуемые типы: A (автотюнинг) и L (Lua) - пауза их намеренно не
  // трогает, гейт должен пропустить их без вызова выключения исполнителей.
  const char ungatedTypes[] = {'A', 'L'};
  for (char t : ungatedTypes) {
    reset_fixture();
    beerManualPause = true;
    run_gate(t);
    check(afterGateReached == 1, std::string("РЕГРЕСС: тип '") + t + "' не должен гейтиться ручной паузой");
    check(heaterCalls == 0 && mixerCalls == 0, std::string("тип '") + t + "' не должен трогать исполнители из гейта паузы");
  }

  // Контроль: без активной паузы гейт для гейтуемого типа не срабатывает.
  reset_fixture();
  beerManualPause = false;
  run_gate('M');
  check(afterGateReached == 1, "РЕГРЕСС: без активной паузы гейт не должен останавливать обработку строки");
  check(heaterCalls == 0 && mixerCalls == 0, "без паузы гейт не должен трогать исполнители");

  // Отказ исполнителя при паузе - аварийный останов варки (beer_abort_config_error),
  // а не тихий пропуск.
  reset_fixture();
  beerManualPause = true;
  valveResult = ACTUATOR_COMMAND_FAILED;
  run_gate('C');
  check(abortCalls == 1, "РЕГРЕСС: отказ выключения клапана на паузе должен был вызвать beer_abort_config_error");
  check(afterGateReached == 0, "гейт должен был остановиться даже при отказе исполнителя (return после abort)");

  if (failures != 0) return 1;
  std::cout << "beer manual pause single entry point (П12) behaviour checks passed\n";
  return 0;
}
'''


def compile_and_run(harness: str) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-beer-pause-gate-") as temp_dir:
        source = Path(temp_dir) / "beer_pause_gate.cpp"
        binary = Path(temp_dir) / "beer_pause_gate"
        source.write_text(harness, encoding="utf-8")
        compiled = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compiled.returncode:
            return compiled.returncode, compiled.stdout + compiled.stderr
        ran = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        return ran.returncode, ran.stdout + ran.stderr


def main() -> int:
    beer = (ROOT / "beer.h").read_text(encoding="utf-8")
    try:
        stage_body = extract_function_body(beer, "void beer_stage_tick()")
        gate_start = stage_body.find(GATE_TOKEN)
        if gate_start < 0:
            raise ValueError(f"gate token not found: {GATE_TOKEN}")
        _, gate_end = extract_braced_block_after(stage_body, GATE_TOKEN)
        gate_statement = stage_body[gate_start:gate_end]
        pause_outputs = extract_function_body(beer, PAUSE_OUTPUTS_SIGNATURE)
        safe_outputs = extract_function_body(beer, SAFE_OUTPUTS_SIGNATURE)
        cooling_outputs = extract_function_body(beer, COOLING_OUTPUTS_SIGNATURE)
        cooling_pump = extract_function_body(beer, COOLING_PUMP_SIGNATURE)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    harness = (
        HARNESS_TEMPLATE.replace("@COOLING_PUMP@", f"{COOLING_PUMP_SIGNATURE} {{\n{cooling_pump}\n}}")
        .replace("@COOLING_OUTPUTS@", f"{COOLING_OUTPUTS_SIGNATURE} {{\n{cooling_outputs}\n}}")
        .replace("@SAFE_OUTPUTS@", f"{SAFE_OUTPUTS_SIGNATURE} {{\n{safe_outputs}\n}}")
        .replace("@PAUSE_OUTPUTS@", f"{PAUSE_OUTPUTS_SIGNATURE} {{\n{pause_outputs}\n}}")
        .replace("@GATE@", gate_statement)
    )
    code, output = compile_and_run(harness)
    sys.stdout.write(output)
    if code:
        return code

    # Мутация: убираем гейт по типу 'C' (как будто вернули старую дыру, где
    # охлаждение паузу не проверяло) - тест обязан упасть.
    mutant = harness.replace(
        "currentType == 'C' || currentType == 'F'",
        "currentType == 'F'",
        1,
    )
    if mutant == harness:
        print("FAIL: не удалось создать мутацию (снять гейт с 'C')", file=sys.stderr)
        return 1
    code, output = compile_and_run(mutant)
    if code == 0:
        print("FAIL: мутация (снятие гейта с 'C') пережила тест", file=sys.stderr)
        sys.stderr.write(output)
        return 1
    print("Beer manual pause gate mutation ('C' ungated) was rejected as expected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
