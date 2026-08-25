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
]:
    if token not in column:
        errors.append(f"column material gate missing: {token}")

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
    # [T29] хэш обновлён: program_commit()/program_clear()/program_serialize_rows()
    # теперь защищены спинлоком configMux (см. tools/smoke_lock_order.py).
    "program_io.h": "d16285cf721f1ec41315d85a1bb673d5df231b4450a389825be4ddc0de02832c",
    "program_types.h": "8e9a8a991b6d4a1e10ddcaf574c7e48cfe2f1cdb20e12601b040f28075466f12",
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
