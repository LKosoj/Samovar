#!/usr/bin/env python3
"""Поведенческая проверка П13: таймауты-предохранители строк 'B' и 'C'.

[Находка] Пока кипение не зафиксировано, beer.h греет на заведомо
недостижимую уставку (BOILING_TEMP + 5) без ограничения по времени - если
датчик куба врёт, объём жидкости мал, крышка не закрыта или порог кипения
(MIN_BOILING_TEMP) недостижим из-за низкого давления, нагрев идёт бесконечно
на полной мощности. Симметрично 'C' ждёт остывания без таймаута.

Фикс: два таймаута по BEER_BOIL_TIMEOUT_MS / BEER_COOL_TIMEOUT_MS (60 минут),
реакция - beer_abort_config_error (снимает мощность через stop_process, но не
взводит аварийную защёлку - это ошибка конфигурации/процесса, а не авария
оборудования).

Тест извлекает РЕАЛЬНЫЙ код из beer.h:
  - для 'B' - вложенный блок определения кипения внутри currentType=='B'
    (isBoilingStarted(...)/else-таймаут), а не всю ветку 'B' целиком (там
    много несвязанных с таймаутом зависимостей - ПИД, SamSetup.BVolt и т.д.);
  - для 'C' - блок таймаута остывания целиком.
Плюс единую точку входа ручной паузы (гейт) из beer_stage_tick(), чтобы
показать, что во время паузы тик до этого кода вообще не доходит - значит,
таймаут не тикает.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body

ROOT = Path(__file__).resolve().parents[1]

GATE_TOKEN = "if (beerManualPause && (currentType == 'M'"
BOIL_DETECT_TOKEN = "if (begintime == 0) {\n      //Определяем начало кипения"
COOL_TIMEOUT_TOKEN = "if (beer_stage_elapsed_ms(millis()) >= BEER_COOL_TIMEOUT_MS) {"

HARNESS_TEMPLATE = r'''
#include <iostream>
#include <string>

using ProgramType = char;

// [П13] Те же значения, что и в beer.h.
#define BEER_BOIL_TIMEOUT_MS (60UL * 60UL * 1000UL)
#define BEER_COOL_TIMEOUT_MS (60UL * 60UL * 1000UL)
constexpr int NOTIFY_MSG = 2;

static bool beerManualPause = false;
static ProgramType currentType = 'B';
static unsigned long beerBoilActiveAccumMs = 0;
static unsigned long beerMixerPauseSinceMs = 0;  // [Дефект 2 code review] см. beer.h
static unsigned long fakeMillis = 0;
unsigned long millis() { return fakeMillis; }

static float temp = 0.0f;
static unsigned long begintime = 0;
static bool boilingReached = false;
bool isBoilingStarted(float) { return boilingReached; }

static bool msgfl = false;
static int sendMsgCalls = 0;
void SendMsg(const char*, int) { sendMsgCalls++; }

static int abortCalls = 0;
static std::string lastAbortReason;
void beer_abort_config_error(const char* reason) {
  abortCalls++;
  lastAbortReason = reason;
}

static int pauseHelperCalls = 0;
bool beer_pause_fermentation_outputs() { pauseHelperCalls++; return true; }

static int afterGateReached = 0;

static void run_boil_tick() {
  const unsigned long nowMs = millis();
@GATE@
  afterGateReached++;
@BOIL_DETECT@
}

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static void reset_fixture() {
  beerManualPause = false;
  currentType = 'B';
  beerBoilActiveAccumMs = 0;
  beerMixerPauseSinceMs = 0;
  fakeMillis = 0;
  temp = 0.0f;
  begintime = 0;
  boilingReached = false;
  msgfl = false;
  sendMsgCalls = 0;
  abortCalls = 0;
  lastAbortReason.clear();
  pauseHelperCalls = 0;
  afterGateReached = 0;
}

int main() {
  // [П13, БЛОКЕР] Недостижимая температура кипения - 3600 тиков по 1с
  // (BEER_BOIL_TIMEOUT_MS / 1000) не должны зафиксировать кипение; на
  // ПОСЛЕДНЕМ тике накопитель достигает порога и должна вызваться
  // beer_abort_config_error (мощность снята через stop_process внутри неё).
  reset_fixture();
  const unsigned long ticksToTimeout = BEER_BOIL_TIMEOUT_MS / 1000;
  for (unsigned long i = 0; i < ticksToTimeout - 1; i++) {
    run_boil_tick();
  }
  check(abortCalls == 0, "РЕГРЕСС: таймаут разгона до кипения сработал раньше срока");
  run_boil_tick();
  check(abortCalls == 1, "РЕГРЕСС: не удалось зафиксировать кипение за 60 минут должно было вызвать beer_abort_config_error");

  // Контроль: если кипение зафиксировано ДО истечения таймаута, аварийного
  // останова быть не должно (обычный, штатный путь).
  reset_fixture();
  boilingReached = true;
  run_boil_tick();
  check(abortCalls == 0, "РЕГРЕСС: штатная фиксация кипения не должна аварийно останавливать варку");
  check(sendMsgCalls == 1, "штатная фиксация кипения должна отправить уведомление ровно один раз");

  // [П13] Пауза не тикает: тик во время активной ручной паузы не доходит до
  // кода определения кипения вовсе (единая точка входа гейтит 'B') - значит,
  // накопитель таймаута не растёт, сколько бы тиков ни было на паузе.
  reset_fixture();
  beerManualPause = true;
  for (int i = 0; i < 100; i++) run_boil_tick();
  check(afterGateReached == 0, "РЕГРЕСС: гейт паузы должен был остановить каждый из 100 тиков");
  check(beerBoilActiveAccumMs == 0, "РЕГРЕСС: таймаут разгона до кипения не должен тикать во время ручной паузы");
  check(abortCalls == 0, "во время ручной паузы таймаут не должен срабатывать");

  // Снятие паузы возвращает обычную работу гейта/таймаута.
  reset_fixture();
  beerManualPause = true;
  run_boil_tick();
  beerManualPause = false;
  run_boil_tick();
  check(afterGateReached == 1, "РЕГРЕСС: после снятия паузы тик должен снова доходить до кода строки");
  check(beerBoilActiveAccumMs == 1000, "РЕГРЕСС: после снятия паузы таймаут должен снова тикать");

  if (failures != 0) return 1;
  std::cout << "beer boil timeout (П13) behaviour checks passed\n";
  return 0;
}
'''


def compile_and_run(harness: str) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-beer-boil-timeout-") as temp_dir:
        source = Path(temp_dir) / "beer_boil_timeout.cpp"
        binary = Path(temp_dir) / "beer_boil_timeout"
        source.write_text(harness, encoding="utf-8")
        compiled = subprocess.run(
            ["g++", "-std=c++11", "-O1", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
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
        # strip_comments=False здесь и ниже: BOIL_DETECT_TOKEN использует текст
        # комментария как landmark, чтобы отличить нужный "if (begintime == 0)"
        # от 4 других таких же условий в beer.h - без комментария неоднозначно.
        stage_body = extract_function_body(beer, "void beer_stage_tick()", strip_comments=False)
        gate_start = stage_body.find(GATE_TOKEN)
        if gate_start < 0:
            raise ValueError(f"gate token not found: {GATE_TOKEN}")
        _, gate_end = extract_braced_block_after(stage_body, GATE_TOKEN)
        gate_statement = stage_body[gate_start:gate_end]

        b_branch, _ = extract_braced_block_after(
            stage_body, "if (currentType == 'B') {", strip_comments=False
        )
        boil_detect, _ = extract_braced_block_after(b_branch, BOIL_DETECT_TOKEN)

        # Наличие таймаута остывания 'C' в исходнике проверяем текстово -
        # поведенчески он уже покрыт smoke_beer_cooling_pump_owner.py
        # (реальный C_BRANCH целиком, включая П14/П13 взаимодействие).
        c_branch, _ = extract_braced_block_after(stage_body, "if (currentType == 'C') {")
        if COOL_TIMEOUT_TOKEN not in c_branch:
            raise ValueError("cooling timeout guard not found in 'C' branch")
        if "beer_abort_config_error" not in c_branch:
            raise ValueError("'C' branch has no beer_abort_config_error call for the cooling timeout")
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    harness = HARNESS_TEMPLATE.replace("@GATE@", gate_statement).replace(
        "@BOIL_DETECT@", boil_detect
    )
    code, output = compile_and_run(harness)
    sys.stdout.write(output)
    if code:
        return code

    # Мутация: убираем проверку порога (как будто таймаут забыли добавить) -
    # тест обязан упасть.
    mutant = harness.replace(
        "if (beerBoilActiveAccumMs >= BEER_BOIL_TIMEOUT_MS) {",
        "if (false && beerBoilActiveAccumMs >= BEER_BOIL_TIMEOUT_MS) {",
        1,
    )
    if mutant == harness:
        print("FAIL: не удалось создать мутацию (снять порог таймаута)", file=sys.stderr)
        return 1
    code, output = compile_and_run(mutant)
    if code == 0:
        print("FAIL: мутация (снятие порога таймаута) пережила тест", file=sys.stderr)
        sys.stderr.write(output)
        return 1
    print("Beer boil timeout threshold mutation was rejected as expected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
