#!/usr/bin/env python3
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


blynk = strip_cpp_comments(read_text("Blynk.ino"))

# Arduino IDE помечает функции из пользовательского макроса вокруг BLYNK_READ
# как static и конфликтует с extern-объявлением в BlynkHandlers.h.
if blynk and "BLYNK_READ_SIMPLE" in blynk:
    errors.append("BLYNK_READ_SIMPLE must not be used (Arduino IDE extern/static conflict)")

expected_reads = {
    "V1": "Blynk.virtualWrite(V1, PipeSensor.avgTemp);",
    "V25": "Blynk.virtualWrite(V25, ACPSensor.avgTemp);",
    "V2": "Blynk.virtualWrite(V2, WthdrwlProgress);",
    "V5": "Blynk.virtualWrite(V5, bme_pressure);",
    "V6": "Blynk.virtualWrite(V6, WaterSensor.avgTemp);",
    "V7": "Blynk.virtualWrite(V7, TankSensor.avgTemp);",
    "V8": "Blynk.virtualWrite(V8, get_liquid_volume());",
    "V9": "Blynk.virtualWrite(V9, ActualVolumePerHour);",
    "V15": "Blynk.virtualWrite(V15, ipst);",
    "V19": "Blynk.virtualWrite(V19, SAMOVAR_VERSION);",
    "V20": "Blynk.virtualWrite(V20, Samovar_Mode);",
    "V23": "Blynk.virtualWrite(V23, pressure_value);",
    "V21": 'Blynk.virtualWrite(V21, "Тек:" + (String)current_power_volt + " Цель:" + (String)target_power_volt);',
    "V16": "Blynk.virtualWrite(V16, target_power_volt);",
}

for pin, write in expected_reads.items():
    signature = f"BLYNK_READ({pin})"
    if blynk and f"{signature} {{" not in blynk:
        errors.append(f"{pin} handler lost its literal signature: {signature} {{")
        continue
    try:
        body = extract_function_body(blynk, signature)
    except ValueError as exc:
        errors.append(str(exc))
        continue
    require_ordered_tokens(
        f"{signature} body",
        body,
        [
            "static bool inReadHandler = false;",
            "if (inReadHandler) return;",
            "inReadHandler = true;",
            write,
            "inReadHandler = false;",
        ],
        errors,
    )

for pin in ("V0", "V10", "V11", "V14", "V24"):
    literal_signature = f"BLYNK_READ({pin}) {{"
    if blynk and literal_signature not in blynk:
        errors.append(f"{pin} handler lost its literal signature: {literal_signature}")

if errors:
    print("BLYNK_READ_SIMPLE contract smoke check failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("BLYNK_READ_SIMPLE contract smoke check passed")
