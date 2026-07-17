#!/usr/bin/env python3
import re
import sys
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "WebServer.ino"
SAMOVAR = ROOT / "Samovar.ino"
errors: list[str] = []


def read_file(path: Path) -> str:
    if not path.exists():
        errors.append(f"missing file: {path.relative_to(ROOT)}")
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def body(source: str, signature: str, *, last: bool = False) -> str:
    try:
        if last:
            offset = source.rfind(signature)
            if offset < 0:
                raise ValueError(f"function not found: {signature}")
            return extract_function_body(source[offset:], signature)
        return extract_function_body(source, signature)
    except ValueError as error:
        errors.append(str(error))
        return ""


web_text = read_file(WEB)
samovar_text = read_file(SAMOVAR)
handle_save = body(web_text, "void handleSave(AsyncWebServerRequest *request)")
queue = body(web_text, "static OperationError queue_profile_operation(")
commit = body(samovar_text, "static OperationError commit_profile_operation()", last=True)
process = body(samovar_text, "static void process_profile_operation()", last=True)
loop = body(samovar_text, "void loop()")
setup_processor = body(web_text, "String setupKeyProcessor(const String &var)")
parse_long = body(web_text, "static bool parse_save_long_arg")
parse_float = body(web_text, "static bool parse_save_float_arg")
save_allowlist = body(web_text, "static bool save_param_name_allowed")

if handle_save:
    require_ordered_tokens(
        "handleSave validates and stages before one compound queue",
        handle_save,
        [
            "for (size_t index = 0; index < request->params(); index++)",
            "save_param_name_allowed(param->name())",
            "request_param_count(request, param->name().c_str()) != 1",
            "const SAMOVAR_MODE sourceMode = Samovar_Mode;",
            "SetupEEPROM staged = SamSetup;",
            "uint8_t sensorResetMask = 0;",
            'apply_save_u16_arg(request, "SteamDelay", staged.SteamDelay, 0, 65535)',
            'apply_save_float_arg(request, "SetPipeTemp", staged.SetPipeTemp, 0.0f, 150.0f)',
            'apply_save_ds_addr_arg(request, "ACPAddr", dsSnapshot, staged.ACPAdress, PROFILE_SENSOR_RESET_ACP, sensorResetMask)',
            'apply_save_u8_arg(request, "PackDens", staged.PackDens, 0, 100)',
            "const bool hasSwitchMode = modeRequested",
            "prepare_program_for_mode(",
            "prepare_default_program_for_mode(",
            "queue_profile_operation(",
            "send_save_operation_accepted(request, operationId);",
        ],
        errors,
    )
    require_ordered_tokens(
        "explicit WProgram is validated before publication",
        handle_save,
        [
            'wProgramCount == 1 ? get_request_param(request, "WProgram") : nullptr',
            "wProgramCount == 1 && (!wProgramParam || wProgramParam->isFile())",
            "prepare_program_for_mode(",
            "wProgramParam->value(),",
            "programDraft);",
            "if (!result.ok())",
            "programDraftPtr = &programDraft;",
            "wProgramCount == 1,",
        ],
        errors,
    )
    if re.search(r"\bSamSetup\.[A-Za-z_][A-Za-z0-9_]*\s*=", handle_save):
        errors.append("handleSave mutates SamSetup before loop owner commit")
    for forbidden in (
        ".toInt()",
        ".toFloat()",
        "beginResponse(301",
        "queue_pending_setup_save",
        "PendingSetupSave",
        "pending_program_str",
    ):
        if forbidden in handle_save:
            errors.append(f"handleSave contains obsolete/unsafe token: {forbidden}")

if queue:
    require_ordered_tokens(
        "queue_profile_operation atomically reserves and publishes POD",
        queue,
        [
            "bool locked = pending_command_lock(pdMS_TO_TICKS(50));",
            "profile_operation_phase_load() != PROFILE_OPERATION_EMPTY",
            "mode_switch_in_progress()",
            "requireProgramIdle && program_update_session_active()",
            "operation_store_reserve_locked(",
            "reset_profile_operation_slot();",
            "active_profile_operation.id = reservedId;",
            "active_profile_operation.programAction = programAction;",
            "profile_operation_phase_store(PROFILE_OPERATION_QUEUED);",
            "operationId = reservedId;",
            "pending_command_unlock(true);",
        ],
        errors,
    )
    for token in (
        "kind == OPERATION_KIND_SAVE && metadataFlags != 0",
        "kind == OPERATION_KIND_PROGRAM",
        "settings || sensorResetMask != 0 || modeChange",
    ):
        if token not in queue:
            errors.append(f"queue_profile_operation missing invalid-combination guard: {token}")

if commit:
    require_ordered_tokens(
        "profile commit persists before publishing owner state",
        commit,
        [
            "save_profile_nvs(active_profile_operation.settings)",
            "if (persistResult != PERSIST_OK)",
            "SamSetup = active_profile_operation.settings;",
            "program_commit(active_profile_operation.program);",
            "apply_setup_sensor_fields(active_profile_operation.sensorResetMask);",
            "if (hasSettings) apply_config_runtime();",
        ],
        errors,
    )

if process:
    require_ordered_tokens(
        "loop owner lifecycle",
        process,
        [
            "operation_store_mark_running_locked(",
            "PROFILE_OPERATION_RUNNING",
            "PROFILE_OPERATION_REQUIRE_PROGRAM_IDLE",
            "OPERATION_ERROR_CANCELLED",
            "switch_samovar_mode(",
            "set_profile_operation_terminal(",
            "publish_profile_operation_terminal();",
        ],
        errors,
    )
    if "ProfileOperationSlot" in process:
        errors.append("process_profile_operation copies the compound DTO to loop stack")

if loop and loop.count("process_profile_operation();") != 1:
    errors.append("loop must call process_profile_operation exactly once")

if save_allowlist:
    for name in ("fullsetup", "mode", "WProgram", "SteamDelay", "PackDens"):
        if f'name == "{name}"' not in save_allowlist:
            errors.append(f"save allowlist missing {name}")

for name, parse_body, parser in (
    ("parse_save_long_arg", parse_long, "parse_bounded_long"),
    ("parse_save_float_arg", parse_float, "parse_bounded_float"),
):
    if parse_body:
        require_ordered_tokens(
            name,
            parse_body,
            [
                "request_param_count(request, name) != 1",
                parser,
                "send_save_parse_error(request, name, result.error);",
                "return false;",
            ],
            errors,
        )

if setup_processor:
    for field in ("SetPipeTemp", "SetWaterTemp", "SetTankTemp", "SetACPTemp"):
        if re.search(rf"\bSamSetup\.{field}\s*=", setup_processor):
            errors.append(f"setupKeyProcessor mutates SamSetup.{field}")

if errors:
    print("handleSave staging smoke failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("handleSave staging smoke passed")
