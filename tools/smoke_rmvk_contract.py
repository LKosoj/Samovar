#!/usr/bin/env python3
import re
import sys
from pathlib import Path

from smoke_helpers import extract_function_body, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []


def read_text(name: str) -> str:
    path = ROOT / name
    if not path.exists():
        errors.append(f"{name} not found")
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


mod_rmv = read_text("mod_rmv.ino")
mod_rmvk = read_text("mod_rmvk.h")
power = read_text("power_regulator.h")
stab = read_text("Stab-avr/Stab-avr.ino")
sem_uart = read_text("Stab-avr/SEM_AVR/SEM_AVR_UART.ino")

if "#define RMVK_ERROR 255" not in mod_rmvk:
    errors.append("mod_rmvk.h must reserve 255 as RMVK_ERROR")

try:
    cmd_body = extract_function_body(
        mod_rmv,
        "uint8_t RMVK_cmd(",
    )
except ValueError as exc:
    errors.append(str(exc))
    cmd_body = ""

if "return rmvk.conn" in cmd_body:
    errors.append("RMVK_cmd must return RMVK_ERROR on timeout/invalid response, not rmvk.conn")

for token in ['rmvk_response_equals(response, "OFF")', "return 0;"]:
    if token not in cmd_body:
        errors.append(f"RMVK_cmd RMVK_ON path missing valid OFF handling token: {token}")

for token in ("heater_uart_enqueue", "powerGeneration", "energizing", "return RMVK_ERROR;"):
    if token not in cmd_body:
        errors.append(f"RMVK_cmd missing epoch-bound UART commit: {token}")

if "uart_write_bytes" in cmd_body:
    errors.append("RMVK_cmd bypasses the epoch-bound UART commit")

if not re.search(r"uart_driver_install\(RMVK_UART,\s*BUF_SIZE \* 2,\s*0,", mod_rmv):
    errors.append("RMVK UART TX buffer must be disabled for bounded uart_tx_chars commits")

if "bool energizing =" in mod_rmvk:
    errors.append("RMVK_cmd must not provide an epoch-less default energizing argument")

for signature in (
    "uint16_t RMVK_get_in_voltge()",
    "uint16_t RMVK_get_out_voltge()",
    "uint16_t RMVK_get_store_out_voltge()",
    "bool RMVK_get_state()",
):
    try:
        body = extract_function_body(mod_rmv, signature)
    except ValueError as exc:
        errors.append(str(exc))
        continue
    if "ret != RMVK_ERROR" not in body:
        errors.append(f"{signature} must update cached state only after ret != RMVK_ERROR")

if re.search(r"\brmvkFn\s*\(", mod_rmv + "\n" + mod_rmvk):
    errors.append("dead rmvkFn must not be defined or declared")

power_code = strip_cpp_comments(power)
if '"AT+' in power_code:
    errors.append("power_regulator.h must not use ASCII AT literals for SEM_AVR Samovar power commands")

if 'SEM_AVR_SAMOVAR_AT_PREFIX = "\\xD0\\x90\\xD0\\xA2"' not in power:
    errors.append("power_regulator.h missing explicit SEM_AVR legacy UTF-8 A/T prefix")

for name, text in {
    "Stab-avr/Stab-avr.ino": stab,
    "Stab-avr/SEM_AVR/SEM_AVR_UART.ino": sem_uart,
}.items():
    if 'SAMOVAR_LEGACY_UTF8_AT "\\xD0\\x90\\xD0\\xA2"' not in text:
        errors.append(f"{name} missing explicit legacy UTF-8 A/T prefix")
    code = strip_cpp_comments(text)
    if '"АТ+' in code:
        errors.append(f"{name} still has visually ambiguous Cyrillic A/T command literal")

if errors:
    print("RMVK contract smoke check failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("RMVK contract smoke check passed")
