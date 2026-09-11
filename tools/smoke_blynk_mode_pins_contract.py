#!/usr/bin/env python3
"""Статическая проверка контракта пинов Blynk V27..V32 (данные режима и команды
веб-форм режимов), см. SamovarServer/SamovarMobile/PIN_SPEC.md §7 и §9.

Что проверяется:
- V27 собирается из общего с /ajax снимка (captureAjaxTelemetrySnapshot) и
  сериализатор читает ТОЛЬКО снимок, а не глобальные переменные - иначе
  вернётся гонка, ради которой снимок вводили.
- V27 отдаёт все ключи JSON, на которые опираются мобильные приложения.
  Пропажа ключа сломает экран режима молча (приложение просто спрячет поле).
- V28..V32: разбор значения -> report_blynk_numeric_error -> return ДО любого
  побочного эффекта; никаких .asInt()/.asFloat().
- #define BLYNK_MAX_SENDBYTES 1024 в Samovar.h (не флаг -D: Arduino IDE их не видит): без него virtualWrite обрезает длинные
  значения (V24 программа, V27 JSON) тихо, по размеру буфера.
"""
import re
import sys
from pathlib import Path

from smoke_helpers import (
    extract_braced_block_after,
    extract_function_body,
    require_ordered_tokens,
    strip_cpp_comments,
)

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []


def read_text(name: str) -> str:
    path = ROOT / name
    if not path.exists():
        errors.append(f"{name} not found")
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def function_body(source: str, signature: str) -> str:
    try:
        return extract_function_body(source, signature)
    except ValueError as exc:
        errors.append(str(exc))
        return ""


blynk = strip_cpp_comments(read_text("Blynk.ino"))
platformio = read_text("platformio.ini")

for forbidden in (".asInt()", ".asFloat()"):
    if forbidden in blynk:
        errors.append(f"Blynk.ino contains forbidden numeric conversion: {forbidden}")

# --- V27: снимок и сериализатор -------------------------------------------
read_body = function_body(blynk, "static void blynk_push_v27()")
require_ordered_tokens(
    "blynk_push_v27",
    read_body,
    [
        "AjaxTelemetrySnapshot snapshot;",
        "captureAjaxTelemetrySnapshot(0, snapshot) == RUNTIME_AJAX_SNAPSHOT_OK",
        "write_blynk_mode_json(sink, snapshot);",
        "Blynk.virtualWrite(V27, json);",
    ],
    errors,
)

writer_body = function_body(
    blynk, "static void write_blynk_mode_json(Print& out, const AjaxTelemetrySnapshot& s)"
)
EXPECTED_KEYS = [
    "st", "pn", "pt", "alc", "salc", "rpa", "ppa", "tr", "rtt", "ptr", "tt",
    "det", "dtr", "di", "dwl", "dws", "ud", "ua", "boil", "bev", "bps", "wauto", "wsp", "wpwm", "wf", "wft",
    "prvl", "isspd", "sp", "spr", "bpause", "order", "mixer", "ph", "phv",
]
found_keys = re.findall(r'jsonField(?:Raw|Float|Bool|String)\(out, first, "([a-z]+)"', writer_body)
for key in EXPECTED_KEYS:
    if key not in found_keys:
        errors.append(f"write_blynk_mode_json misses JSON key: {key}")
duplicates = {key for key in found_keys if found_keys.count(key) > 1}
if duplicates:
    errors.append(f"write_blynk_mode_json emits duplicate keys: {sorted(duplicates)}")

# Сериализатор читает только снимок: каждое значение - s.<поле> или литерал.
for match in re.finditer(r'jsonField(?:Raw|Float|Bool|String)\(out, first, "[a-z]+",\s*([^,)]+)', writer_body):
    value = match.group(1).strip()
    if not value.startswith("s."):
        errors.append(f"write_blynk_mode_json reads outside the snapshot: {value}")
for global_name in ("SamovarStatusInt", "ProgramNum", "PowerOn", "Samovar_Mode", "SamSetup."):
    if global_name in writer_body:
        errors.append(f"write_blynk_mode_json touches global state: {global_name}")
if "writeUiStateJson(out, first, s.ui, s.luaStatus);" not in writer_body:
    errors.append("write_blynk_mode_json must serialize ui from the shared snapshot")

# --- V28..V32: разбор -> отчёт -> return до побочных эффектов ---------------
handler_contracts = {
    "BLYNK_WRITE(V28)": (
        [
            "if (mode_switch_in_progress()) return;",
            "parse_control_water_pwm(param.asStr(), waterPwm)",
            "if (!result.ok())",
            "report_blynk_numeric_error(28, result);",
            'report_blynk_refusal(28, "PWM_TOO_LOW");',
            "queue_pending_value(pending_water_temp_flag, pending_water_temp_value, waterPwm)",
        ],
        ("queue_pending_value(",),
    ),
    "BLYNK_WRITE(V29)": (
        [
            "if (mode_switch_in_progress()) return;",
            "parse_control_nbk(",
            "param.asStr()",
            "if (!result.ok())",
            "report_blynk_numeric_error(29, result);",
            'report_blynk_refusal(29, "POWER_OFF");',
            "queue_pending_nbk(nbkCommand)",
        ],
        ("queue_pending_nbk(",),
    ),
    "BLYNK_WRITE(V30)": (
        [
            "if (mode_switch_in_progress()) return;",
            "parse_exact_bool(param.asStr(), state)",
            "NUMERIC_PARSE_NOT_ALLOWED",
            "if (!result.ok())",
            "report_blynk_numeric_error(30, result);",
            'report_blynk_refusal(30, "NOT_RUNNING");',
            'report_blynk_refusal(30, "NO_SETPOINT");',
            "queue_pending_flag(pending_water_auto_flag, false)",
        ],
        ("queue_pending_flag(",),
    ),
    "BLYNK_WRITE(V31)": (
        [
            "if (mode_switch_in_progress()) return;",
            "parse_exact_bool(param.asStr(), state)",
            "NUMERIC_PARSE_NOT_ALLOWED",
            "if (!result.ok())",
            "report_blynk_numeric_error(31, result);",
            'report_blynk_refusal(31, "POWER_OFF");',
            "queue_pending_flag(pending_nbkopt_flag, false)",
        ],
        ("queue_pending_flag(",),
    ),
    "BLYNK_WRITE(V32)": (
        [
            "if (mode_switch_in_progress()) return;",
            "parse_exact_bool(param.asStr(), state)",
            "if (!result.ok())",
            "report_blynk_numeric_error(32, result);",
            "mode_power_on_command(Samovar_Mode)",
            "SAMOVAR_POWER_OFF",
            "queue_samovar_command(command)",
        ],
        ("queue_samovar_command(",),
    ),
}

for signature, (ordered, side_effects) in handler_contracts.items():
    body = function_body(blynk, signature)
    require_ordered_tokens(signature, body, ordered, errors)
    try:
        invalid_body, invalid_end = extract_braced_block_after(body, "if (!result.ok())")
    except ValueError as exc:
        errors.append(f"{signature}: {exc}")
        continue
    if "report_blynk_numeric_error(" not in invalid_body:
        errors.append(f"{signature} invalid branch does not report the parse error")
    if "return;" not in invalid_body:
        errors.append(f"{signature} invalid branch does not return before side effects")
    for side_effect in side_effects:
        if side_effect in invalid_body:
            errors.append(f"{signature} invalid branch contains side effect: {side_effect}")
        side_effect_index = body.find(side_effect)
        if 0 <= side_effect_index < invalid_end:
            errors.append(f"{signature} side effect occurs before invalid branch returns: {side_effect}")

# Отказы по состоянию должны быть видны пользователю (V26), а не теряться молча.
refusal_body = function_body(blynk, "static inline void report_blynk_refusal(uint8_t virtualPin, const char* reason)")
if "SendMsg(message, WARNING_MSG);" not in refusal_body:
    errors.append("report_blynk_refusal must deliver the reason via SendMsg(..., WARNING_MSG)")

# queue_pending_flag static в WebServer.ino с аргументом по умолчанию - автопрототипа
# не будет, нужно своё объявление без умолчания.
if "static bool queue_pending_flag(volatile bool& flag, bool bypassBarrier);" not in blynk:
    errors.append("Blynk.ino misses forward declaration of queue_pending_flag without default argument")

# --- буфер отправки Blynk ------------------------------------------------------
samovar_h = read_text("Samovar.h")
if not re.search(r"^#define BLYNK_MAX_SENDBYTES 1024$", samovar_h, re.MULTILINE):
    errors.append("Samovar.h misses #define BLYNK_MAX_SENDBYTES 1024 (long V24/V27 values would be truncated)")
if "-DBLYNK_MAX_SENDBYTES" in platformio:
    errors.append("platformio.ini must not set BLYNK_MAX_SENDBYTES: Arduino IDE ignores -D flags, single source is Samovar.h")

if errors:
    print("Blynk mode pins contract smoke check failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("Blynk mode pins contract smoke check passed")
