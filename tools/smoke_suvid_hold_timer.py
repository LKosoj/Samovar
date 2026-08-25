#!/usr/bin/env python3
"""Production-extracted behavioural contract for Suvid S1-S3."""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]
errors = []

HARNESS = r'''
#include <cstdint>
#include <math.h>
#include <iostream>

@HEAT_DELTA@
@REACH_TIMEOUT@
@STOP_RETRY@
@HOLD_BAND@

struct Setup { float SuvidTemp; uint16_t SuvidHoldMinutes; };
static Setup SamSetup{};
struct Tank { float avgTemp; };
static Tank TankSensor{};
@HOLD_STATE@
@DEVIATION_STATE@
// [T24.3] Термостат живёт на уровне файла (suvid.h), виден и check_alarm_suvid(),
// и suvid_tick() - здесь так же, как в продакшене.
static bool suvidHeaterOn = false;

static bool PowerOn = true;
static bool heater_state = false;
static uint32_t fakeMillis = 0;
static uint32_t millis() { return fakeMillis; }
static int heaterCalls = 0;
static bool lastHeater = false;
static void setHeaterPosition(bool value) { heaterCalls++; lastHeater = value; }
// [T28a] check_alarm_suvid() больше не пишет heater_state напрямую - вызывает
// set_heater_state_flag() (единственная точка записи, см. beer.h).
static void set_heater_state_flag(bool state) { heater_state = state; }
static int messages = 0;
static int warnings = 0;
static int alarms = 0;
static void SendMsg(const char*, int type) { messages++; if (type == 1) warnings++; if (type == 0) alarms++; }
static int buzzerCalls = 0;
static void set_buzzer(bool) { buzzerCalls++; }
enum { SAMOVAR_POWER = 1, ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2, SAMOVAR_SUVID_MODE = 6 };
static int Samovar_Mode = SAMOVAR_SUVID_MODE;
static int queueCalls = 0;
static bool queueSucceeds = true;
static bool queue_samovar_command(int) { queueCalls++; return queueSucceeds; }
static float suvid_target_temp() { return SamSetup.SuvidTemp > 0 ? SamSetup.SuvidTemp : 60.0f; }

// [T24.3] check_alarm_suvid() и suvid_tick() - теперь две ОТДЕЛЬНЫЕ продакшен-функции,
// обе вызываемые из loop() независимо (mode_dispatch_loop(), затем suvid_tick()).
// Склеены в раздельные функции (не в одну), чтобы ранний return внутри
// check_alarm_suvid_body() (ветка !PowerOn) не глушил suvid_tick_body(), как и в
// продакшене, где это два независимых вызова.
static void check_alarm_suvid_body() {
@CHECK_ALARM_BODY@
}

static void suvid_tick_body() {
@SUVID_TICK_BODY@
}

static void tick() {
  check_alarm_suvid_body();
  suvid_tick_body();
}

static int failures = 0;
static void check(bool value, const char* text) {
  if (!value) { std::cerr << "FAIL: " << text << '\n'; failures++; }
}
static void reset(uint16_t hold = 0) {
  PowerOn = false; tick();
  SamSetup = {60.0f, hold}; TankSensor.avgTemp = 60.0f; PowerOn = true;
  suvidHold = {}; suvidDeviation = {}; fakeMillis = 0; heaterCalls = 0;
  lastHeater = false; messages = 0; warnings = 0; alarms = 0; buzzerCalls = 0;
  queueCalls = 0; queueSucceeds = true; heater_state = false;
}
static void test_symmetric_band() {
  reset(); TankSensor.avgTemp = 60.0f + HEAT_DELTA + 0.1f; tick();
  check(!lastHeater, "above symmetric band must disable heater");
  TankSensor.avgTemp = 60.0f; tick();
  check(!lastHeater, "inside symmetric band must retain an initially-off heater");
  TankSensor.avgTemp = 60.0f - HEAT_DELTA - 0.1f; tick();
  check(lastHeater, "below setpoint-HEAT_DELTA must enable heater");
  TankSensor.avgTemp = 60.0f; tick();
  check(lastHeater, "inside symmetric band must retain heater state");
  TankSensor.avgTemp = 61.1f; tick();
  check(!lastHeater, "above setpoint+HEAT_DELTA must disable heater");
}
static void test_hold_counts_only_band_time() {
  reset(1); fakeMillis = 1000; tick();
  fakeMillis = 31000; tick();
  check(suvidHold.accumulatedMs == 30000, "first in-band interval must be counted");
  TankSensor.avgTemp = 62.1f; fakeMillis = 61000; tick();
  check(suvidHold.accumulatedMs == 30000, "out-of-band time must not be counted");
  TankSensor.avgTemp = 60.0f; fakeMillis = 91000; tick();
  check(queueCalls == 0,
        "return to the band must not count the preceding out-of-band interval");
  fakeMillis = 121000; tick();
  check(queueCalls == 1 && suvidHold.fired,
        "two confirmed 30-second in-band intervals must complete one-minute hold");
}
static void test_zero_hold_is_indefinite() {
  // [П15] avgTemp==setpoint сразу после reset() - полоса входа достигается на первом же
  // тике. active теперь взводится независимо от SuvidHoldMinutes (иначе проверка
  // отклонения ниже не включилась бы никогда при бессрочном термостате) - но
  // завершение (queueCalls) по-прежнему не должно наступать без заданной выдержки.
  reset(0); for (int i = 0; i < 100; i++) { fakeMillis += 1000; tick(); }
  check(suvidHold.active,
        "REGRESSION П15: reaching the band must start hold tracking even with SuvidHoldMinutes=0 - "
        "otherwise the deviation check never arms for an indefinite thermostat");
  check(queueCalls == 0,
        "SuvidHoldMinutes=0 must keep an indefinite thermostat without an auto-shutoff completion");
}
static void test_no_deviation_warning_before_hold_starts() {
  // [П15, ГЛАВНЫЙ РЕГРЕСС] Разогрев: температура ни разу не попадала в полосу
  // ±HEAT_DELTA, значит "выдержка" ещё не началась. Раньше отклонение проверялось
  // с самого включения питания - каждая сессия начиналась с ложной тревоги.
  reset(); TankSensor.avgTemp = 62.1f; tick();
  fakeMillis = 60000; tick();
  fakeMillis = 600000; tick();
  check(warnings == 0,
        "REGRESSION П15: heat-up deviation before the hold ever starts must not warn (false alarm every session)");
  check(!suvidHold.active, "hold must stay inactive while temperature never entered the band");
}
static void test_deviation_warning_after_hold_starts() {
  // Разогрев завершился (температура дошла до уставки - выдержка началась), после
  // чего температура снова уходит за пределы 2° - это уже реальный повод для тревоги
  // (например, отказ ТЭНа или датчика посреди выдержки), и её по-прежнему нужно ловить.
  reset(); fakeMillis = 1000; tick();
  check(suvidHold.active, "reaching the band must start the hold");
  TankSensor.avgTemp = 62.1f; fakeMillis = 2000; tick();
  check(warnings == 0, "deviation warning must not fire on the very first out-of-tolerance tick");
  fakeMillis = 61999; tick(); check(warnings == 0, "warning must not fire before 60 seconds of deviation");
  fakeMillis = 62000; tick();
  check(warnings == 1, "REGRESSION П15: deviation after the hold has started must still warn at 60 seconds");
  fakeMillis = 123000; tick(); check(warnings == 1, "continuous deviation must warn only once");
  TankSensor.avgTemp = 60.0f; fakeMillis = 124000; tick();
  TankSensor.avgTemp = 62.1f; fakeMillis = 125000; tick();
  fakeMillis = 185000; tick(); check(warnings == 2, "return to tolerance must re-arm warning");
}
static void test_reach_timeout_stops_heating_when_hold_never_starts() {
  // [П15] Выдержка так и не началась (сломанный ТЭН, врущий датчик, слишком
  // большая загрузка). Раньше отсюда уходило только предупреждение, а ТЭН
  // продолжал греть: при застывшем заниженном показании куба уставка недостижима
  // в принципе, и термостат держал бы нагрев вечно. Теперь останавливаем, как
  // beer.h по BEER_BOIL_TIMEOUT_MS.
  reset(); TankSensor.avgTemp = 62.1f; tick();
  fakeMillis = SUVID_REACH_TIMEOUT_MS - 1000; tick();
  check(alarms == 0 && queueCalls == 0, "reach timeout must not fire before the deadline");
  fakeMillis = SUVID_REACH_TIMEOUT_MS; tick();
  check(alarms == 1,
        "REGRESSION П15: failing to reach the hold band within the timeout must raise an alarm");
  check(warnings == 0, "reach timeout must not be a mere warning: it switches the heater off");
  check(queueCalls == 1,
        "REGRESSION: reach timeout must queue the power-off command, not just talk about it");
  check(buzzerCalls == 1, "reach timeout must call the buzzer once");
  // SAMOVAR_POWER - переключатель, и чужая команда в общей очереди может вернуть нагрев
  // обратно. Пока нагрев фактически включён (PowerOn), попытка повторяется - но не чаще
  // SUVID_STOP_RETRY_MS, чтобы обычная задержка исполнения не порождала лишних команд.
  fakeMillis = SUVID_REACH_TIMEOUT_MS + SUVID_STOP_RETRY_MS - 1000; tick();
  check(queueCalls == 1, "a queued stop must not be repeated before the retry delay");
  check(alarms == 1, "the alarm must not repeat");
  fakeMillis = SUVID_REACH_TIMEOUT_MS + SUVID_STOP_RETRY_MS; tick();
  check(queueCalls == 2,
        "REGRESSION: heating still on after the retry delay means the toggle was undone - try again");
  check(alarms == 1, "retries must stay silent: one alarm per session");
}
static void test_reach_timeout_state_clears_once_the_heater_is_off() {
  // Нагрев действительно выключился - состояние сессии сбрасывается, попытки прекращаются,
  // а следующая сессия отсчитывает свой таймаут с нуля.
  reset(); TankSensor.avgTemp = 62.1f; tick();
  fakeMillis = SUVID_REACH_TIMEOUT_MS; tick();
  check(queueCalls == 1 && alarms == 1, "the timeout must fire once");
  PowerOn = false; fakeMillis = SUVID_REACH_TIMEOUT_MS + 1000; tick();
  check(queueCalls == 1, "no attempts once the heater is off");
  check(!suvidHold.reachTimeoutMsgSent && !suvidHold.reachTimeoutStopQueued,
        "REGRESSION: a finished session must not carry the timeout flags into the next one");
  PowerOn = true; fakeMillis = SUVID_REACH_TIMEOUT_MS + 2000; tick();
  check(queueCalls == 1 && alarms == 1,
        "a fresh session must start its own timeout, not fire immediately");
  fakeMillis = SUVID_REACH_TIMEOUT_MS + 2000 + SUVID_REACH_TIMEOUT_MS; tick();
  check(queueCalls == 2 && alarms == 2, "the fresh session must fire after its own full timeout");
}
static void test_reach_timeout_retries_while_the_command_queue_is_busy() {
  // Очередь команд может быть занята: единственная неудачная попытка не должна
  // оставить ТЭН включённым навсегда - повторяем до успеха, а сообщение шлём один раз.
  reset(); TankSensor.avgTemp = 62.1f; queueSucceeds = false; tick();
  fakeMillis = SUVID_REACH_TIMEOUT_MS; tick();
  check(alarms == 1 && queueCalls == 1, "first attempt must alarm and try to stop");
  fakeMillis = SUVID_REACH_TIMEOUT_MS + 1000; tick();
  check(queueCalls == 2, "REGRESSION: a busy queue must not abandon the power-off attempt");
  check(alarms == 1, "the alarm must not repeat on every retry");
  queueSucceeds = true;
  fakeMillis = SUVID_REACH_TIMEOUT_MS + 2000; tick();
  check(queueCalls == 3, "the retry must go through once the queue frees up");
  fakeMillis = SUVID_REACH_TIMEOUT_MS + 3000; tick();
  check(queueCalls == 3, "no further attempts after the command is accepted");
}
static void test_reach_timeout_does_not_fire_once_the_hold_started() {
  // Выдержка началась вовремя - таймаут выхода на режим больше не относится к делу,
  // даже если сессия давно длиннее SUVID_REACH_TIMEOUT_MS.
  reset(); tick();
  check(suvidHold.active, "reaching the band must start the hold");
  fakeMillis = SUVID_REACH_TIMEOUT_MS + 600000; tick();
  check(alarms == 0 && queueCalls == 0,
        "REGRESSION: the reach timeout must not stop a session that already reached the band");
}
static void test_timers_wrap_across_uint32_max() {
  reset(1);
  fakeMillis = UINT32_MAX - 30000U;
  tick();
  fakeMillis = 10000U;
  tick();
  check(suvidHold.accumulatedMs == 40001U,
        "hold must count the in-band interval across uint32 millis wrap");
  fakeMillis = 30000U;
  tick();
  check(queueCalls == 1 && suvidHold.fired,
        "hold must complete after the remaining in-band interval across wrap");

  reset();
  tick();  // avgTemp == setpoint на этот момент - выдержка стартует до скачка millis
  TankSensor.avgTemp = 62.1f;
  fakeMillis = UINT32_MAX - 30000U;
  tick();
  fakeMillis = 29999U;
  tick();
  check(warnings == 1,
        "continuous deviation must warn after 60 seconds across uint32 millis wrap");
}
static void test_queue_failure_is_explicit_without_fallback() {
  reset(1); fakeMillis = 1000; tick(); fakeMillis = 61000; queueSucceeds = false; tick();
  check(queueCalls == 1 && !suvidHold.fired && warnings == 1,
        "busy completion queue must warn and retain pending completion");
  fakeMillis = 62000; queueSucceeds = true; tick();
  check(queueCalls == 2 && suvidHold.fired,
        "pending completion must retry the same graceful command, not a fallback action");
}
static void test_hold_band_survives_temperature_ripple() {
  // [T24.1] "Пила" +-1.5 C вокруг уставки: полоса зачёта (SUVID_HOLD_BAND_C=2.0 C)
  // шире полосы регулирования (HEAT_DELTA=1 C) - тепловая инерция бака качает
  // температуру сильнее, чем успевает отработать реле, и колебание в пределах
  // +-1.5 C не должно постоянно прерывать зачёт выдержки.
  // МУТАЦИЯ: откат SUVID_HOLD_BAND_C к 1.0 обязан уронить эту проверку -
  // колебание +-1.5 C тогда всегда было бы вне узкой полосы, и hold.active
  // не взвёлся бы вовсе (accumulatedMs остался бы 0).
  reset();
  const uint32_t totalSeconds = 200;
  for (uint32_t s = 1; s <= totalSeconds; s++) {
    TankSensor.avgTemp = 60.0f + ((s % 2 == 0) ? 1.5f : -1.5f);
    fakeMillis = s * 1000U;
    tick();
  }
  check(suvidHold.accumulatedMs >= (uint32_t)(totalSeconds * 1000U * 95U / 100U),
        "REGRESSION T24.1: a +-1.5C ripple inside SUVID_HOLD_BAND_C must count at least "
        "95% of elapsed time toward the hold");
}
static void test_tick_respects_mode_guard() {
  // [T24.3] suvid_tick() применяет состояние термостата к нагревателю ТОЛЬКО в
  // режиме Сувид - смена режима не должна дёргать чужой нагреватель тем
  // значением, которое посчитал термостат Сувида.
  reset();
  fakeMillis = 1000; tick();
  heaterCalls = 0;
  suvidHeaterOn = true;  // avgTemp == setpoint (60), термостат этот тик не тронет
  Samovar_Mode = SAMOVAR_SUVID_MODE + 1;  // другой режим
  fakeMillis = 2000; tick();
  check(heaterCalls == 0,
        "REGRESSION T24.3: suvid_tick() must not call setHeaterPosition outside Suvid mode");
  Samovar_Mode = SAMOVAR_SUVID_MODE;
}
int main() {
  test_symmetric_band(); test_hold_counts_only_band_time(); test_zero_hold_is_indefinite();
  test_no_deviation_warning_before_hold_starts(); test_deviation_warning_after_hold_starts();
  test_reach_timeout_stops_heating_when_hold_never_starts();
  test_reach_timeout_state_clears_once_the_heater_is_off();
  test_reach_timeout_retries_while_the_command_queue_is_busy();
  test_reach_timeout_does_not_fire_once_the_hold_started();
  test_timers_wrap_across_uint32_max();
  test_queue_failure_is_explicit_without_fallback();
  test_hold_band_survives_temperature_ripple();
  test_tick_respects_mode_guard();
  return failures == 0 ? 0 : 1;
}
'''


def definition(source, token):
    start = source.find(token)
    if start < 0:
        raise ValueError(f"missing {token}")
    end = source.find("};", start)
    if end < 0:
        raise ValueError(f"unterminated {token}")
    return source[start:end + 2]


def main():
    source = (ROOT / "suvid.h").read_text(encoding="utf-8")
    ini = (ROOT / "Samovar_ini.h").read_text(encoding="utf-8")
    body = extract_function_body(source, "inline void check_alarm_suvid")
    # [T24.3] suvidHeaterOn переехал на уровень файла (виден также suvid_tick()) -
    # старый якорь "static bool suvidHeaterOn = false;" внутри тела функции исчез.
    # "if (!PowerOn) {" - следующая стабильная строка, отмечающая начало того же
    # блока термостата/выдержки, что и раньше.
    start = body.find("if (!PowerOn) {")
    if start < 0:
        raise ValueError("thermostat anchor missing")
    snippet = body[start:]
    tick_body = extract_function_body(source, "inline void suvid_tick()")
    require_ordered_tokens("Suvid S1-S3 order", snippet, [
        "if (!PowerOn)", "suvidHold = {false, false, false, false, 0, 0, 0, false, false, false, 0};",
        "setpoint - HEAT_DELTA", "setpoint + HEAT_DELTA",
        "inHoldBand", "suvidHold.active", "deviation > SUVID_HOLD_BAND_C",
        "now - suvidDeviation.sinceMs", "SUVID_REACH_TIMEOUT_MS",
        "holdMs > 0", "suvidHold.accumulatedMs", "queue_samovar_command(SAMOVAR_POWER)",
    ], errors)
    if "setHeaterPosition" not in tick_body:
        errors.append("suvid_tick() must apply the thermostat state via setHeaterPosition")
    if "program[" in snippet:
        errors.append("Suvid hold must not read the shared program buffer")
    if "request_emergency_stop" in snippet:
        errors.append("Suvid hold must not use an emergency fallback")
    if errors:
        for error in errors: print(f"FAIL: {error}", file=sys.stderr)
        return 1
    heat = next(line.strip() for line in ini.splitlines() if line.startswith("#define HEAT_DELTA"))
    reach_timeout = next(line.strip() for line in source.splitlines() if line.startswith("#define SUVID_REACH_TIMEOUT_MS"))
    stop_retry = next(line.strip() for line in source.splitlines() if line.startswith("#define SUVID_STOP_RETRY_MS"))
    hold_band = next(line.strip() for line in source.splitlines() if line.startswith("#define SUVID_HOLD_BAND_C"))
    code = HARNESS.replace("@HEAT_DELTA@", heat).replace("@REACH_TIMEOUT@", reach_timeout)
    code = code.replace("@STOP_RETRY@", stop_retry)
    code = code.replace("@HOLD_BAND@", hold_band)
    code = code.replace("@HOLD_STATE@", definition(source, "struct SuvidHoldState") + "\nstatic SuvidHoldState suvidHold;")
    code = code.replace("@DEVIATION_STATE@", definition(source, "struct SuvidDeviationState") + "\nstatic SuvidDeviationState suvidDeviation;")
    code = code.replace("@CHECK_ALARM_BODY@", snippet)
    code = code.replace("@SUVID_TICK_BODY@", tick_body)
    with tempfile.TemporaryDirectory(prefix="samovar-suvid-s1-s3-") as temp:
        temp_path = Path(temp)

        def compile_and_run(name, source_code, show_output=True):
            cpp = temp_path / f"{name}.cpp"
            binary = temp_path / name
            cpp.write_text(source_code, encoding="utf-8")
            result = subprocess.run(
                ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
                 str(cpp), "-o", str(binary)],
                capture_output=True,
                text=True,
            )
            if result.returncode:
                sys.stderr.write(result.stderr)
                return result.returncode
            return subprocess.run(
                [str(binary)],
                capture_output=not show_output,
                text=True,
            ).returncode

        result = compile_and_run("production", code)
        if result:
            return result

        mutant = code.replace(
            "if (TankSensor.avgTemp <= setpoint - HEAT_DELTA) suvidHeaterOn = true;",
            "if (TankSensor.avgTemp <= setpoint) suvidHeaterOn = true;",
            1,
        )
        if compile_and_run("mutant_band_lower_limit", mutant, False) == 0:
            print("FAIL: lower-band mutation survived Suvid S1 harness", file=sys.stderr)
            return 1
        mutant = code.replace(
            "suvidHold.inBand = false;",
            "suvidHold.inBand = suvidHold.inBand;",
            1,
        )
        if compile_and_run("mutant_hold_pause", mutant, False) == 0:
            print("FAIL: out-of-band hold pause mutation survived Suvid S1 harness", file=sys.stderr)
            return 1
        mutant = code.replace(
            "suvidHold.accumulatedMs += now - suvidHold.lastTickMs;",
            "suvidHold.accumulatedMs += now >= suvidHold.lastTickMs ? now - suvidHold.lastTickMs : 0;",
            1,
        )
        if mutant == code:
            print("FAIL: unable to build Suvid hold wrap mutation", file=sys.stderr)
            return 1
        if compile_and_run("mutant_hold_wrap", mutant, False) == 0:
            print("FAIL: hold wrap mutation survived Suvid S1 harness", file=sys.stderr)
            return 1
        mutant = code.replace(
            "(uint32_t)(now - suvidDeviation.sinceMs)",
            "(now >= suvidDeviation.sinceMs ? now - suvidDeviation.sinceMs : 0U)",
            1,
        )
        if mutant == code:
            print("FAIL: unable to build Suvid deviation wrap mutation", file=sys.stderr)
            return 1
        if compile_and_run("mutant_deviation_wrap", mutant, False) == 0:
            print("FAIL: deviation wrap mutation survived Suvid S1 harness", file=sys.stderr)
            return 1
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
