#!/usr/bin/env python3
import sys
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]
i2c_file = ROOT / "I2CStepper.h"
samovar_file = ROOT / "Samovar.ino"
web_file = ROOT / "WebServer.ino"

errors = []


def read_text(path: Path) -> str:
    if not path.exists():
        errors.append(f"{path.name} not found")
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


i2c_text = read_text(i2c_file)
samovar_text = read_text(samovar_file)
web_text = read_text(web_file)

if i2c_text:
    try:
        read_block_body = extract_function_body(i2c_text, "inline bool i2c_stepper_read_block")
    except ValueError as exc:
        errors.append(str(exc))
        read_block_body = ""
    if read_block_body:
        require_ordered_tokens(
            "i2c_stepper_read_block start/transaction",
            read_block_body,
            [
                "xSemaphoreTake(xI2CSemaphore",
                "Wire.beginTransmission(address);",
                "Wire.write(reg);",
                "Wire.endTransmission(false) != 0",
                "xSemaphoreGive(xI2CSemaphore);",
                "return false;",
                "Wire.requestFrom(address, len)",
                "bytesRead != len",
                "xSemaphoreGive(xI2CSemaphore);",
                "return false;",
                "data[i] = Wire.read();",
                "xSemaphoreGive(xI2CSemaphore);",
                "return true;",
            ],
            errors,
        )
        if read_block_body.count("Wire.requestFrom(") != 1:
            errors.append("i2c_stepper_read_block must contain exactly one Wire.requestFrom call")
        if "I2C2.readByte" in read_block_body:
            errors.append("i2c_stepper_read_block contains per-byte fallback")

    for signature, block_token in [
        ("inline bool i2c_stepper_read_u16", "i2c_stepper_read_block(address, reg, data, sizeof(data))"),
        ("inline bool i2c_stepper_read_u32", "i2c_stepper_read_block(address, reg, data, sizeof(data))"),
    ]:
        try:
            body = extract_function_body(i2c_text, signature)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if block_token not in body:
            errors.append(f"{signature} does not use block read")
        if "I2C2.readByte" in body:
            errors.append(f"{signature} still uses per-byte I2C2.readByte")

    try:
        refresh_body = extract_function_body(i2c_text, "inline bool i2c_stepper_refresh(I2CStepperDevice& dev, bool force)")
    except ValueError as exc:
        errors.append(str(exc))
        refresh_body = ""
    if refresh_body and "if (!force && i2c_stepper_config_busy(dev)) return dev.present;" not in refresh_body:
        errors.append("i2c_stepper_refresh missing config-busy skip")

if samovar_text:
    try:
        loop_body = extract_function_body(samovar_text, "void loop()")
    except ValueError as exc:
        errors.append(str(exc))
        loop_body = ""
    try:
        systicker_body = extract_function_body(samovar_text, "void triggerSysTicker")
    except ValueError as exc:
        errors.append(str(exc))
        systicker_body = ""
    try:
        cache_refresh_body = extract_function_body(
            samovar_text, "static void refresh_i2c_stepper_cache(")
    except ValueError as exc:
        errors.append(str(exc))
        cache_refresh_body = ""
    try:
        executor_signature = "static OperationError execute_pending_i2c_stepper("
        executor_offset = samovar_text.rfind(executor_signature)
        if executor_offset < 0:
            raise ValueError(f"function definition not found: {executor_signature}")
        executor_body = extract_function_body(
            samovar_text[executor_offset:], executor_signature)
        owner_body = extract_function_body(
            samovar_text, "static void process_pending_i2c_operations()")
    except ValueError as exc:
        errors.append(str(exc))
        executor_body = ""
        owner_body = ""
    if loop_body:
        require_ordered_tokens(
            "single A-02 loop owner order",
            loop_body,
            [
                "process_profile_operation();",
                "process_pending_i2c_operations();",
                "if (mode_switch_in_progress())",
            ],
            errors,
        )
        if loop_body.count("process_pending_i2c_operations();") != 1:
            errors.append("loop must invoke the A-02 owner exactly once")
        for token in (
            "hasPendingI2CStepper",
            "hasPendingI2CPump",
            "hasPendingLocalCal",
            "hasPendingI2CCal",
            "i2c_stepper_apply(*dev)",
        ):
            if token in loop_body:
                errors.append(f"loop retains obsolete inline I2C executor: {token}")
    if executor_body:
        require_ordered_tokens(
            "candidate-based I2C stepper executor",
            executor_body,
            [
                "i2c_stepper_config_begin(*device)",
                "I2CStepperDevice candidate = *device;",
                "candidate.mode = command.staged.mode;",
                "candidate.stepsPerMl = command.staged.stepsPerMl;",
                'strcmp(command.cmd, "apply") == 0',
                "i2c_stepper_apply(candidate)",
                'strcmp(command.cmd, "calfinish") == 0',
                "i2c_stepper_send_command(",
                "OperationError result = i2c_command_result(commandSucceeded, candidate);",
                "confirm_i2c_candidate(candidate)",
                "if (result == OPERATION_ERROR_NONE) *device = candidate;",
                "i2c_stepper_config_end(*device);",
                "return result;",
            ],
            errors,
        )
        for token in ("save_profile_nvs(", "SamSetup =", "I2CPumpCalibrating ="):
            if token in executor_body:
                errors.append(f"generic I2C stepper executor owns calibration side effect: {token}")
    if owner_body:
        require_ordered_tokens(
            "A-02 claim/execute/terminal owner",
            owner_body,
            [
                "if (pending_i2c_operation_result.pending)",
                "operation_store_finish_locked(",
                "clear_pending_i2c_operation_locked(",
                "pending_i2c_operation_result = {};",
                "return;",
                "mode_switch_in_progress()",
                "pending_i2cstepper_flag",
                "pending_i2cpump_flag",
                "pending_local_cal_flag",
                "pending_i2ccal_flag",
                "operation_store_mark_running_locked(",
                "pending_command_unlock(true);",
                "execute_pending_i2c_stepper(stepperCommand)",
                "publish_pending_i2c_result(",
            ],
            errors,
        )
        if owner_body.count("operation_store_mark_running_locked(") != 1 or \
                owner_body.count("operation_store_finish_locked(") != 1 or \
                owner_body.count("publish_pending_i2c_result(") != 1:
            errors.append("A-02 owner transition/publication callsite count drift")
    if cache_refresh_body:
        require_ordered_tokens(
            "owned I2CStepper cache refresh",
            cache_refresh_body,
            [
                "if (!i2c_stepper_config_begin(device)) return;",
                "i2c_stepper_refresh(device, true)",
                "i2c_stepper_cache.mixer_present = present;",
                "i2c_stepper_cache.pump_present = present;",
                "i2c_stepper_config_end(device);",
            ],
            errors,
        )
        if cache_refresh_body.count("i2c_stepper_config_begin(device)") != 1:
            errors.append("cache refresh must claim device exactly once")
        if cache_refresh_body.count("i2c_stepper_refresh(device, true)") != 1:
            errors.append("cache refresh must perform exactly one forced refresh")
        if cache_refresh_body.count("i2c_stepper_config_end(device);") != 1:
            errors.append("cache refresh must release device exactly once")
        if "i2c_stepper_config_busy(" in cache_refresh_body:
            errors.append("cache refresh retains check-then-refresh TOCTOU")
        claim_guard = "if (!i2c_stepper_config_begin(device)) return;"
        if cache_refresh_body.find("i2c_stepper_cache.") < \
                cache_refresh_body.find(claim_guard) + len(claim_guard):
            errors.append("busy cache refresh path must preserve the previous cache")
    if systicker_body:
        require_ordered_tokens(
            "SysTicker owned I2CStepper refresh",
            systicker_body,
            [
                "refresh_i2c_stepper_cache(i2cStepperMixer);",
                "refresh_i2c_stepper_cache(i2cStepperPump);",
            ],
            errors,
        )
        for token in (
            "i2c_stepper_config_busy(",
            "i2c_stepper_refresh(i2cStepperMixer",
            "i2c_stepper_refresh(i2cStepperPump",
            "i2c_stepper_cache.",
        ):
            if token in systicker_body:
                errors.append(f"SysTicker bypasses owned cache refresh: {token}")

if web_text:
    try:
        i2cstepper_body = extract_function_body(web_text, 'server.on("/i2cstepper"')
    except ValueError as exc:
        errors.append(str(exc))
        i2cstepper_body = ""
    for token in [
        "i2c_stepper_apply(",
        "i2c_stepper_save(",
        "i2c_stepper_start(",
        "i2c_stepper_stop(",
        "i2c_stepper_send_command(",
        "i2c_stepper_write_config(",
    ]:
        if token in i2cstepper_body:
            errors.append(f"/i2cstepper handler contains direct I2C operation: {token}")

if errors:
    print("I2CStepper atomic smoke check failed:")
    for err in errors:
        print(f" - {err}")
    sys.exit(1)

print("I2CStepper atomic smoke check passed")
