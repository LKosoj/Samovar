#!/usr/bin/env python3
"""Client/firmware agreement on the mains voltage used for the watt<->volt scale.

data/program.htm shows the column power in volts when pwr_unit == 'V'. Physically
P = U**2 / R, so with a heater rated Pmax at Umax the client must render
U = Umax * sqrt(P / Pmax). That is only correct while the client's Umax equals the
Umax the firmware actually clamps to in set_current_power() (power_regulator.h):

    maxPower = 230**2 / HeaterResistant     (SAMOVAR_USE_SEM_AVR)
    Volt clamped to 230                     (otherwise)

The page used to hardcode 220 against the firmware's 230: every displayed voltage
was ~4% low and the implied power ~9% low, so the operator set a weaker heat than
the number on screen promised.

This test pins the AGREEMENT, not the number: it extracts the constant from both
sides and requires they match. Re-rating the hardware stays a one-line change on
each side; letting the two drift apart does not.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROGRAM_PAGE = ROOT / "data_raw" / "program.htm"
POWER_REGULATOR = ROOT / "power_regulator.h"


def fail(errors):
    print("program voltage scale smoke failed:")
    for error in errors:
        print(f" - {error}")
    return 1


def main() -> int:
    errors = []

    for path in (PROGRAM_PAGE, POWER_REGULATOR):
        if not path.exists():
            errors.append(f"{path.relative_to(ROOT)} not found")
    if errors:
        return fail(errors)

    page = PROGRAM_PAGE.read_text(encoding="utf-8", errors="ignore")
    regulator = POWER_REGULATOR.read_text(encoding="utf-8", errors="ignore")

    # --- firmware side -------------------------------------------------------
    firmware_volts = set()

    # Сопротивление приходит через trusted_heater_resistance() (control_numeric_input.h):
    # делить на сырое SamSetup.HeaterResistant нельзя, оно бывает нулём и вне диапазона.
    sem_match = re.search(
        r"\(\s*(\d+(?:\.\d+)?)f\s*\*\s*(\d+(?:\.\d+)?)f\s*/\s*"
        r"trusted_heater_resistance\(\s*SamSetup\.HeaterResistant\s*\)\s*\)",
        regulator,
    )
    if not sem_match:
        errors.append("power_regulator.h: the 230**2/R power ceiling is gone or was rewritten")
    else:
        if sem_match.group(1) != sem_match.group(2):
            errors.append(
                "power_regulator.h: the squared ceiling uses two different voltages "
                f"({sem_match.group(1)} and {sem_match.group(2)})"
            )
        firmware_volts.add(float(sem_match.group(1)))
        firmware_volts.add(float(sem_match.group(2)))

    clamp_match = re.search(
        r"if\s*\(\s*Volt\s*>\s*(\d+(?:\.\d+)?)f\s*\)\s*Volt\s*=\s*(\d+(?:\.\d+)?)f\s*;",
        regulator,
    )
    if not clamp_match:
        errors.append("power_regulator.h: the plain Volt clamp is gone or was rewritten")
    else:
        if clamp_match.group(1) != clamp_match.group(2):
            errors.append(
                "power_regulator.h: the clamp compares against one voltage and assigns another "
                f"({clamp_match.group(1)} vs {clamp_match.group(2)})"
            )
        firmware_volts.add(float(clamp_match.group(1)))
        firmware_volts.add(float(clamp_match.group(2)))

    if len(firmware_volts) > 1:
        errors.append(
            "power_regulator.h disagrees with itself about the mains voltage: "
            f"{sorted(firmware_volts)}"
        )

    # --- client side ---------------------------------------------------------
    page_match = re.search(r"var\s+mainsVolt\s*=\s*(\d+(?:\.\d+)?)\s*;", page)
    if not page_match:
        errors.append("data_raw/program.htm: no `var mainsVolt = ...;` declaration")
    client_volt = float(page_match.group(1)) if page_match else None

    # Все три формулы обязаны ходить через одну константу. Это не косметика: toVolt()
    # делит на heaterMaxPwr, который сама же страница и заполняет как U**2/R, поэтому
    # U сокращается и результат равен sqrt(W*R) - но ТОЛЬКО пока обе половины берут
    # одно и то же U. Разъехавшиеся половины дают тихую ошибку в U_prefill/U_toVolt раз.
    conversions = re.findall(r"Math\.round\(\s*mainsVolt\s*\*\s*Math\.sqrt\(", page)
    if len(conversions) != 2:
        errors.append(
            "data_raw/program.htm: expected exactly two watt->volt conversion sites going through "
            f"mainsVolt (found {len(conversions)})"
        )
    if not re.search(r"Math\.round\(\s*mainsVolt\s*\*\s*mainsVolt\s*/\s*heaterResistance\s*\)", page):
        errors.append(
            "data_raw/program.htm: the heater power prefill does not compute mainsVolt**2/R - "
            "toVolt() divides by that value, so a different voltage there silently rescales "
            "every volt the page shows"
        )

    stray = re.findall(r"(\d+(?:\.\d+)?)\s*\*\s*Math\.sqrt\(", page)
    if stray:
        errors.append(
            f"data_raw/program.htm: watt->volt conversion still hardcodes a voltage literal: {stray}"
        )
    stray_square = re.findall(r"(\d{4,})\s*/\s*heaterResistance", page)
    if stray_square:
        errors.append(
            "data_raw/program.htm: the heater power prefill hardcodes a squared voltage literal "
            f"{stray_square} instead of mainsVolt**2 (220**2 = 48400, 230**2 = 52900)"
        )

    # --- the invariant -------------------------------------------------------
    if client_volt is not None and len(firmware_volts) == 1:
        firmware_volt = next(iter(firmware_volts))
        if client_volt != firmware_volt:
            errors.append(
                f"data_raw/program.htm renders volts against {client_volt:g} V while the firmware "
                f"clamps to {firmware_volt:g} V: every displayed voltage is off by "
                f"{abs(client_volt - firmware_volt) / firmware_volt * 100:.1f}% and the implied "
                f"power by {abs(client_volt**2 - firmware_volt**2) / firmware_volt**2 * 100:.1f}%"
            )

    if errors:
        return fail(errors)
    print("program voltage scale smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
