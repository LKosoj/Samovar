#!/usr/bin/env python3
"""Статическая проверка контракта push-отдачи пинов Blynk (Blynk.ino).

С 2026-09 сервер не опрашивает железо (в эталонном проекте frequency=0): прошивка сама
шлёт пины из blynk_push_tick(), который tick_blynk() (Samovar.ino) зовёт под BlynkLockGuard
после Blynk.run(). Проверяется:
- обработчиков BLYNK_READ не осталось (иначе вернётся двойной путь к тем же данным);
- каждый быстрый пин отдаётся ровно тем выражением, что и раньше (контракт PIN_SPEC.md §2),
  и включён в таблицу kBlynkFastPush;
- быстрые пины шлются порциями (BLYNK_PUSH_PER_TICK), а не все за одну итерацию loop();
- медленные пины (V3, V4, V13, V5, V15, V20, V19, V16, V24) шлются из blynk_push_slow
  только при изменении/force, V24 - по отпечатку program[] (blynk_program_fingerprint),
  program_io.h при этом не трогается (он заморожен другими smoke-тестами);
- после (пере)подключения всё переотправляется (BLYNK_CONNECTED -> s_blynkPushResendAll);
- tick_blynk() зовёт blynk_push_tick() после Blynk.run().
"""
import sys
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []


def read_text(name: str) -> str:
    path = ROOT / name
    if not path.exists():
        errors.append(f"{name} not found")
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def body(source: str, signature: str) -> str:
    try:
        return extract_function_body(source, signature)
    except ValueError as exc:
        errors.append(str(exc))
        return ""


blynk = strip_cpp_comments(read_text("Blynk.ino"))
samovar = strip_cpp_comments(read_text("Samovar.ino"))

if blynk and "BLYNK_READ(" in blynk:
    errors.append("BLYNK_READ handlers must be gone: pins are pushed from blynk_push_tick()")
if blynk and "BLYNK_READ_SIMPLE" in blynk:
    errors.append("BLYNK_READ_SIMPLE must not be used (Arduino IDE extern/static conflict)")

fast_pushes = {
    "blynk_push_v0": "Blynk.virtualWrite(V0, SteamSensor.avgTemp);",
    "blynk_push_v1": "Blynk.virtualWrite(V1, PipeSensor.avgTemp);",
    "blynk_push_v2": "Blynk.virtualWrite(V2, WthdrwlProgress);",
    "blynk_push_v6": "Blynk.virtualWrite(V6, WaterSensor.avgTemp);",
    "blynk_push_v7": "Blynk.virtualWrite(V7, TankSensor.avgTemp);",
    "blynk_push_v8": "Blynk.virtualWrite(V8, get_liquid_volume());",
    "blynk_push_v9": "Blynk.virtualWrite(V9, ActualVolumePerHour);",
    "blynk_push_v25": "Blynk.virtualWrite(V25, ACPSensor.avgTemp);",
    "blynk_push_v23": "Blynk.virtualWrite(V23, pressure_value);",
    "blynk_push_v21": 'Blynk.virtualWrite(V21, "Тек:" + (String)current_power_volt + " Цель:" + (String)target_power_volt);',
    "blynk_push_v27": "Blynk.virtualWrite(V27, json);",
}
if blynk:
    for name, write in fast_pushes.items():
        # V23/V21 объявлены с __attribute__((unused)): в сборках без датчика/регулятора их нет в таблице.
        attr = " __attribute__((unused))" if name in ("blynk_push_v23", "blynk_push_v21") else ""
        fn_body = body(blynk, f"static void{attr} {name}()")
        if fn_body and write not in fn_body:
            errors.append(f"{name} must contain: {write}")
    strings_body = body(blynk, "static void blynk_push_strings()")
    require_ordered_tokens(
        "blynk_push_strings (один захват замка на V10/V11/V14)",
        strings_body,
        [
            "runtime_state_lock(pdMS_TO_TICKS(50))",
            "timesCopy = WthdrwTimeS + \"; \" + WthdrwTimeAllS;",
            "strCrtCopy = StrCrt;",
            "statusCopy = SamovarStatus;",
            "runtime_state_unlock(true);",
            "Blynk.virtualWrite(V10, timesCopy);",
            "Blynk.virtualWrite(V11, strCrtCopy);",
            "Blynk.virtualWrite(V14, statusCopy);",
        ],
        errors,
    )
    if strings_body.count("runtime_state_lock(") != 1:
        errors.append("blynk_push_strings must take runtime_state_lock exactly once")

    table_start = blynk.find("static const BlynkPushFn kBlynkFastPush[] = {")
    table = blynk[table_start: blynk.find("};", table_start)] if table_start >= 0 else ""
    if not table:
        errors.append("kBlynkFastPush table not found")
    for name in list(fast_pushes) + ["blynk_push_strings"]:
        if table and name not in table:
            errors.append(f"{name} missing from kBlynkFastPush")

    slow_body = body(blynk, "static void blynk_push_slow(bool force)")
    for write in [
        "Blynk.virtualWrite(V3, process);",
        "Blynk.virtualWrite(V4, (int)PowerOn);",
        "Blynk.virtualWrite(V13, (int)PauseOn);",
        "Blynk.virtualWrite(V5, bme_pressure);",
        "Blynk.virtualWrite(V15, ipst);",
        "Blynk.virtualWrite(V20, Samovar_Mode);",
        "Blynk.virtualWrite(V19, SAMOVAR_VERSION);",
        "Blynk.virtualWrite(V16, target_power_volt);",
        "Blynk.virtualWrite(V24, serialize_program_for_mode(Samovar_Mode));",
    ]:
        if slow_body and write not in slow_body:
            errors.append(f"blynk_push_slow must contain: {write}")
    if slow_body and "blynk_program_fingerprint()" not in slow_body:
        errors.append("blynk_push_slow must gate V24 by blynk_program_fingerprint()")
    fp_body = body(blynk, "static uint32_t blynk_program_fingerprint()")
    for token in ("sizeof(WProgram) * PROGRAM_END", "ProgramLen"):
        if fp_body and token not in fp_body:
            errors.append(f"blynk_program_fingerprint must cover {token}")

    tick_body = body(blynk, "void blynk_push_tick()")
    require_ordered_tokens(
        "blynk_push_tick (порции, период, переотправка)",
        tick_body,
        [
            "BLYNK_PUSH_PERIOD_MS",
            "blynk_push_slow(s_blynkPushResendAll);",
            "s_blynkPushResendAll = false;",
            "n < BLYNK_PUSH_PER_TICK",
            "kBlynkFastPush[next++]();",
        ],
        errors,
    )
    connected_body = body(blynk, "BLYNK_CONNECTED()")
    if connected_body and "s_blynkPushResendAll = true;" not in connected_body:
        errors.append("BLYNK_CONNECTED must request full resend (s_blynkPushResendAll = true)")

if samovar:
    require_ordered_tokens(
        "tick_blynk зовёт push после Blynk.run()",
        body(samovar, "static void tick_blynk()"),
        ["BlynkLockGuard", "Blynk.run();", "blynk_push_tick();"],
        errors,
    )

if errors:
    print("Blynk push contract smoke check failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("Blynk push contract smoke check passed")
