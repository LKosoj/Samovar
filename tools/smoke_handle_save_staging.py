#!/usr/bin/env python3
import re
import sys
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "WebServer.ino"
SAMOVAR = ROOT / "Samovar.ino"

errors = []


def read_file(path: Path) -> str:
    if not path.exists():
        errors.append(f"missing file: {path.relative_to(ROOT)}")
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def require_token(name: str, body: str, token: str) -> None:
    if token not in body:
        errors.append(f"{name} missing token: {token}")


def forbid_token(name: str, body: str, token: str) -> None:
    if token in body:
        errors.append(f"{name} contains forbidden token: {token}")


web_text = read_file(WEB)
samovar_text = read_file(SAMOVAR)

try:
    handle_save_body = extract_function_body(web_text, "void handleSave(AsyncWebServerRequest *request)")
except ValueError as exc:
    errors.append(str(exc))
    handle_save_body = ""

try:
    setup_processor_body = extract_function_body(web_text, "String setupKeyProcessor(const String &var)")
except ValueError as exc:
    errors.append(str(exc))
    setup_processor_body = ""

try:
    send_parse_error_body = extract_function_body(web_text, "static void send_save_parse_error")
except ValueError as exc:
    errors.append(str(exc))
    send_parse_error_body = ""

try:
    parse_long_body = extract_function_body(web_text, "static bool parse_save_long_arg")
except ValueError as exc:
    errors.append(str(exc))
    parse_long_body = ""

try:
    parse_float_body = extract_function_body(web_text, "static bool parse_save_float_arg")
except ValueError as exc:
    errors.append(str(exc))
    parse_float_body = ""

try:
    program_mode_mapper_body = extract_function_body(web_text, "static PendingProgramMode pending_program_mode_for_samovar_mode")
except ValueError as exc:
    errors.append(str(exc))
    program_mode_mapper_body = ""

try:
    queue_setup_body = extract_function_body(web_text, "static bool queue_pending_setup_save")
except ValueError as exc:
    errors.append(str(exc))
    queue_setup_body = ""

try:
    loop_body = extract_function_body(samovar_text, "void loop()")
except ValueError as exc:
    errors.append(str(exc))
    loop_body = ""

if handle_save_body:
    for token in [
        "PendingSetupSave setupSave;",
        "setupSave.staged = SamSetup;",
        "SetupEEPROM& staged = setupSave.staged;",
    ]:
        require_token("handleSave staging", handle_save_body, token)

    direct_setup_assignments = re.findall(r"\bSamSetup\.[A-Za-z_][A-Za-z0-9_]*\s*=", handle_save_body)
    if direct_setup_assignments:
        errors.append("handleSave contains direct SamSetup assignments: " + ", ".join(sorted(set(direct_setup_assignments))))

    for token in [".toInt()", ".toFloat()"]:
        forbid_token("handleSave parse", handle_save_body, token)

    require_ordered_tokens(
        "handleSave parse/apply before queue",
        handle_save_body,
        [
            "SetupEEPROM& staged = setupSave.staged;",
            'apply_save_u16_arg(request, "SteamDelay", staged.SteamDelay, 0, 65535)',
            'apply_save_float_arg(request, "SetPipeTemp", staged.SetPipeTemp, 0.0f, 150.0f)',
            'apply_save_ds_addr_arg(request, "ACPAddr", dsSnapshot, staged.ACPAdress, setupSave.resetSensor.acp)',
            'apply_save_u8_arg(request, "PackDens", staged.PackDens, 0, 100)',
            "queue_pending_setup_save(setupSave, hasProgram, pendingMode, pendingProgramText, hasSwitchMode, requestedMode, busyText)",
        ],
        errors,
    )
    require_ordered_tokens(
        "handleSave WProgram uses shared mode mapper",
        handle_save_body,
        [
            "SAMOVAR_MODE programMode = modeRequested ? requestedMode : Samovar_Mode;",
            "pendingMode = pending_program_mode_for_samovar_mode(programMode);",
            "pendingProgramText = wProgramParam->value();",
        ],
        errors,
    )
    require_ordered_tokens(
        "handleSave busy path returns 503 before success redirect",
        handle_save_body,
        [
            "if (!queue_pending_setup_save(setupSave, hasProgram, pendingMode, pendingProgramText, hasSwitchMode, requestedMode, busyText))",
            'request->send(503, "text/plain", busyText ? busyText : "BUSY");',
            "return;",
            "AsyncWebServerResponse *response = request->beginResponse(301);",
            'response->addHeader("Location", "/");',
            "request->send(response);",
        ],
        errors,
    )

if program_mode_mapper_body:
    require_ordered_tokens(
        "pending program mode mapper covers distiller and NBK",
        program_mode_mapper_body,
        [
            "case SAMOVAR_BEER_MODE:",
            "return PPM_BEER;",
            "case SAMOVAR_DISTILLATION_MODE:",
            "return PPM_DIST;",
            "case SAMOVAR_NBK_MODE:",
            "return PPM_NBK;",
            "default:",
            "return PPM_RECT;",
        ],
        errors,
    )

if queue_setup_body:
    require_ordered_tokens(
        "queue_pending_setup_save writes payload before flags",
        queue_setup_body,
        [
            "bool locked = pending_command_lock",
            "if (!locked)",
            "if (pending_save_profile_flag)",
            "if (pending_program_mode != PPM_NONE)",
            "if (pending_switch_mode_flag)",
            "pending_setup_save_buf = setupSave;",
            "pending_program_str = programText;",
            "pending_switch_mode_value = switchMode;",
            "__sync_synchronize();",
            "pending_save_profile_flag = true;",
            "pending_program_mode = programMode;",
            "pending_switch_mode_flag = true;",
            "pending_command_unlock(true);",
        ],
        errors,
    )

if send_parse_error_body:
    require_token("send_save_parse_error", send_parse_error_body, 'request->send(400, "text/plain", message);')

if parse_long_body:
    require_ordered_tokens(
        "parse_save_long_arg invalid path",
        parse_long_body,
        [
            "parseLongSafe(raw.c_str(), value)",
            "send_save_parse_error(request, name);",
            "return false;",
        ],
        errors,
    )

if parse_float_body:
    require_ordered_tokens(
        "parse_save_float_arg invalid path",
        parse_float_body,
        [
            "parseFloatSafe(raw.c_str(), value)",
            "save_float_is_finite(value)",
            "send_save_parse_error(request, name);",
            "return false;",
        ],
        errors,
    )

if setup_processor_body:
    for field in ["SetPipeTemp", "SetWaterTemp", "SetTankTemp", "SetACPTemp"]:
        if re.search(rf"\bSamSetup\.{field}\s*=", setup_processor_body):
            errors.append(f"setupKeyProcessor mutates SamSetup.{field}")
    for token in [
        "float setPipeTemp = isnan(SamSetup.SetPipeTemp) ? 0 : SamSetup.SetPipeTemp;",
        "float setWaterTemp = isnan(SamSetup.SetWaterTemp) ? 0 : SamSetup.SetWaterTemp;",
        "float setTankTemp = isnan(SamSetup.SetTankTemp) ? 0 : SamSetup.SetTankTemp;",
        "float setACPTemp = isnan(SamSetup.SetACPTemp) ? 0 : SamSetup.SetACPTemp;",
    ]:
        require_token("setupKeyProcessor display-only NaN formatting", setup_processor_body, token)

if loop_body:
    require_ordered_tokens(
        "loop applies setup-save before mode/program consumers",
        loop_body,
        [
            "if (locked && pending_save_profile_flag)",
            "setupSave = pending_setup_save_buf;",
            "if (hasPendingSetupSave) {",
            "SamSetup = setupSave.staged;",
            "save_profile();",
            "read_config();",
            "apply_pending_setup_sensor_resets(setupSave.resetSensor);",
            "pending_save_profile_flag = false;",
            "if (locked && pending_switch_mode_flag)",
            "switch_samovar_mode(reqMode);",
            "if (locked && pending_program_mode != PPM_NONE)",
            "if (ppm != PPM_NONE) {",
        ],
        errors,
    )

if samovar_text:
    for token in [
        "static PendingProgramMode pending_program_mode_for_samovar_mode(SAMOVAR_MODE mode);",
        "static bool queue_pending_setup_save(const PendingSetupSave& setupSave,",
    ]:
        require_token("Samovar.ino explicit pending prototypes", samovar_text, token)

if errors:
    print("handleSave staging smoke failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("handleSave staging smoke passed")
