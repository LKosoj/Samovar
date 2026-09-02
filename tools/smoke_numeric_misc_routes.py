#!/usr/bin/env python3
import hashlib
import re
import sys
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens, strip_cpp_comments


ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8", errors="ignore")


web = strip_cpp_comments(read("WebServer.ino"))
samovar = strip_cpp_comments(read("Samovar.ino"))


def body(source: str, signature: str) -> str:
    try:
        return extract_function_body(source, signature)
    except ValueError as exc:
        errors.append(str(exc))
        return ""


program = body(web, "void web_program")
calibrate = body(web, "void calibrate_command")
column = body(web, "static void handle_column_params_request")
save = body(web, "void handleSave")
save_allowlist = body(web, "static bool save_param_name_allowed")
recv = body(samovar, "void recvMsg")
loop = body(samovar, "void loop()")
commit_signature = "static OperationError commit_profile_operation()"
commit_offset = samovar.rfind(commit_signature)
commit = body(samovar[commit_offset:], commit_signature) if commit_offset >= 0 else ""
process_signature = "static void process_profile_operation()"
process_offset = samovar.rfind(process_signature)
process = body(samovar[process_offset:], process_signature) if process_offset >= 0 else ""

require_ordered_tokens(
    "program request allowlist and metadata queue",
    program,
    [
        "for (size_t index = 0; index < request->params(); index++)",
        "!known || !param->isPost() || param->isFile()",
        'request_param_count(request, "vless")',
        'request_param_count(request, "Descr")',
        'char descriptionValue[251] = "";',
        "parse_control_vless(",
        "description.length() > 250",
        "metadataFlags |= PROFILE_OPERATION_METADATA_DESCRIPTION;",
        "queue_profile_operation(",
    ],
    errors,
)
for token in ["BoilerVolume =", "heatLossCalculated =", "heatStartMillis ="]:
    if token in program:
        errors.append(f"web_program mutates runtime before loop: {token}")
require_ordered_tokens(
    "profile owner applies program metadata after race checks",
    process + commit,
    [
        "PROFILE_OPERATION_REQUIRE_PROGRAM_IDLE",
        "program_update_session_active()",
        "commit_profile_operation();",
        "runtime_state_lock(pdMS_TO_TICKS(500))",
        "program_commit(active_profile_operation.program);",
        "SessionDescription = escapedDescription;",
        "BoilerVolume = active_profile_operation.boilerVolume;",
    ],
    errors,
)

require_ordered_tokens(
    "calibration exact schema and typed queue",
    calibrate,
    [
        "startCount + finishCount != 1",
        "startCount == 1 ? speedCount != 1 : speedCount != 0",
        "parse_control_calibration_speed(",
        "OperationId operationId = 0;",
        "PendingLocalCalCmd command = {};",
        "queue_pending_local_cal(command, operationId)",
        "checked_step_speed_to_mlh(",
        "queue_pending_i2ccal(command, operationId)",
        "send_operation_accepted(request, operationId);",
    ],
    errors,
)
if "CurrrentStepperSpeed =" in calibrate or ".toInt()" in calibrate:
    errors.append("calibrate handler mutates/narrows speed before loop")

for token in [
    "input->isFile() || input->isPost()",
    "parse_exact_enum(input->value().c_str(), allowed, 3, parsed)",
    'build_error_envelope("argument", "mat", "Invalid mat")',
    'build_error_envelope("argument", "diam", "Invalid diam")',
    "column_diam_allowed(parsed)",
    "calculate_column_etalon(material, diamInches)",
]:
    if token not in column:
        errors.append(f"column material/diam gate missing: {token}")

for token in ["parseLongSafe", "parseFloatSafe", ".toInt()", ".toFloat()"]:
    if token in save:
        errors.append(f"handleSave contains legacy conversion: {token}")
require_ordered_tokens(
    "save allowlist/source gate precedes staging",
    save,
    [
        "for (size_t index = 0; index < request->params(); index++)",
        "save_param_name_allowed(param->name())",
        'build_error_envelope(\n              "not_allowed", param ? param->name().c_str() : nullptr,\n              "Invalid request field")',
        "!param->isPost() || param->isFile()",
        "request_param_count(request, param->name().c_str()) != 1",
        "SetupEEPROM staged = SamSetup;",
    ],
    errors,
)
# save_param_name_allowed больше не хардкодит name == "...": оно перебирает те же
# таблицы/массивы имён, что применяет handleSave (см. tools/smoke_handle_save_staging.py
# для полной проверки). Здесь просто убеждаемся, что нужные имена всё ещё в источнике
# истины и что старая захардкоженная цепочка сравнений не вернулась.
for source, name in (
    ("kSaveU16Fields", "SteamDelay"),
    ("kSaveSpecialNames", "fullsetup"),
    ("kSaveSpecialNames", "WProgram"),
):
    table_match = re.search(rf"{source}\[\]\s*=\s*\{{(.*?)\}};", web, re.S)
    if not table_match or f'"{name}"' not in table_match.group(1):
        errors.append(f"save allowlist source {source} missing {name}")
if re.search(r'name\s*==\s*"', save_allowlist):
    errors.append("save allowlist still hardcodes a literal name == \"...\" comparison")

require_ordered_tokens(
    "WebSerial fixed strict command",
    recv,
    [
        "len > WEBSERIAL_COMMAND_MAX",
        "data[index] == '\\0'",
        'strcmp(command, "print") == 0',
        'static const char prefix[] = "WFpulseCount=";',
        "parse_bounded_uint16(valueText, 0, UINT16_MAX, value)",
        "if (!result.ok())",
        "water_pulse_count_set(value);",
    ],
    errors,
)
for token in ["String d", ".toInt()", "getValue("]:
    if token in recv:
        errors.append(f"WebSerial contains legacy parser: {token}")

expected_hashes = {
    # [Б7] хэш обновлён: PROGRAM_POWER_ABS_THRESHOLD переехала из power_regulator.h
    # в program_types.h (без изменения существующих enum/struct/inline-функций), а
    # program_io.h::prepare_program_for_mode() под SAMOVAR_USE_POWER стал проверять,
    # что первая строка ректификационной программы задаёт абсолютную мощность -
    # при ошибке draft сбрасывается тем же паттерном, что и остальные reject'ы этой
    # функции, program[] не коммитится (draft isolation A-09 не нарушена).
    # [Ф2] хэш обновлён: разборщик строки ректификации отвергает строку H/B/C/T
    # без объёма и температуры (никогда не завершится) - той же схемой ok=false,
    # что и соседние проверки; draft isolation A-09 не тронута.
    # [П1/П5, 02.09.2026] хэш обновлён: prepare_program_for_mode() для дистилляции
    # требует, чтобы первая строка с ненулевой мощностью была абсолютной уставкой
    # (в разгоне target_power_volt == 0, поправка ушла бы ниже порога), а строки
    # S/R принимают долю в (0,1) вместо (0,1]; отказ - тем же сбросом draft,
    # program[] не коммитится, A-09 не нарушена.
    # [П1 доп.] номер физической строки в сообщении.
    # [БК п.9, 02.09.2026] хэш обновлён: новый формат PROGRAM_FORMAT_BK (пятое поле
    # «Т пара») и общий разбор четырёх полей с DIST; отказы - тем же сбросом draft,
    # program[] не коммитится, A-09 не нарушена.
    "program_io.h": "245665eaa2885aca17be3a66e6038675bec828840358bd355ad5487e867f2516",
    "program_types.h": "78a37ac7beda0a3bf50b0ad2e6682075d038a5c15f99e808c665404e22b9ed2b",
}
for name, expected in expected_hashes.items():
    actual = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
    if actual != expected:
        errors.append(f"frozen A-09 dependency changed: {name} {actual}")

if errors:
    print("Numeric miscellaneous route smoke failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("Numeric miscellaneous route smoke passed")
