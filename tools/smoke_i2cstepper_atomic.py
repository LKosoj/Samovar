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
    if loop_body:
        require_ordered_tokens(
            "pending_i2cstepper apply contract",
            loop_body,
            [
                "if (i2c_stepper_config_begin(*dev)) {",
                "dev->mode",
                "i2c_stepper_apply(*dev)",
                "i2c_stepper_refresh(*dev, true);",
                "i2c_stepper_config_end(*dev);",
                "pending_i2cstepper_flag = false;",
            ],
            errors,
        )
    if systicker_body:
        for token in [
            "i2c_stepper_config_busy(i2cStepperMixer) ? i2cStepperMixer.present : i2c_stepper_refresh(i2cStepperMixer)",
            "i2c_stepper_config_busy(i2cStepperPump) ? i2cStepperPump.present : i2c_stepper_refresh(i2cStepperPump)",
        ]:
            if token not in systicker_body:
                errors.append(f"SysTicker I2CStepper refresh does not skip busy device: {token}")
        for token in [
            "i2c_stepper_refresh(i2cStepperMixer, true)",
            "i2c_stepper_refresh(i2cStepperPump, true)",
        ]:
            if token in systicker_body:
                errors.append(f"SysTicker forces I2CStepper refresh while config may be busy: {token}")

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
