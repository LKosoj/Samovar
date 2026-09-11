#!/usr/bin/env python3
"""Mains-voltage wiring for the program.htm watt<->volt scale.

data/program.htm shows the column power in volts when pwr_unit == 'V'. Physically
P = U**2 / R, so with a heater rated Pmax at Umax the client must render
U = Umax * sqrt(P / Pmax).

mainsVolt used to be a hardcoded client constant that had to match the firmware's
regulator clamp in set_current_power() (power_regulator.h). It no longer does:
mainsVolt is now the real mains voltage from the typed /ui-bootstrap snapshot.
The math
still works with a real mains voltage because heaterMaxPwr is auto-filled as
mainsVolt**2/R on the same page: mainsVolt cancels out of both
wattsToProgramVolts() and programVoltsToWatts(), leaving volts = sqrt(W*R) -
independent of mains voltage. Only the heater-power prefill itself (the honest
max wattage the heater draws on THIS mains) depends on mainsVolt.

set_current_power()'s 230 V clamp is a separate thing: a ceiling on the
regulator's setpoint, not the mains voltage, and this test still pins it at 230
so nobody quietly changes that ceiling without noticing here.

This test pins three things: (1) program.htm reads mainsVolt from /ui-bootstrap;
(2) power_regulator.h's setpoint clamp is still 230 and self-consistent;
(3) WebServer.ino's bootstrap writer serves the typed mainsVoltage field.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROGRAM_PAGE = ROOT / "data_raw" / "program.htm"
POWER_REGULATOR = ROOT / "power_regulator.h"
WEB_SERVER = ROOT / "WebServer.ino"


def fail(errors):
    print("program voltage scale smoke failed:")
    for error in errors:
        print(f" - {error}")
    return 1


def main() -> int:
    errors = []

    for path in (PROGRAM_PAGE, POWER_REGULATOR, WEB_SERVER):
        if not path.exists():
            errors.append(f"{path.relative_to(ROOT)} not found")
    if errors:
        return fail(errors)

    page = PROGRAM_PAGE.read_text(encoding="utf-8", errors="ignore")
    regulator = POWER_REGULATOR.read_text(encoding="utf-8", errors="ignore")
    web_server = WEB_SERVER.read_text(encoding="utf-8", errors="ignore")

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

    # --- client side: mainsVolt comes from bootstrap, not a literal ----------
    if not re.search(r"var\s+mainsVolt\s*=\s*NaN\s*;", page):
        errors.append(
            "data_raw/program.htm: mainsVolt must be neutral until bootstrap"
        )
    if "mainsVolt = data.mainsVoltage;" not in page:
        errors.append(
            "data_raw/program.htm: mainsVolt is not initialized from /ui-bootstrap"
        )

    # Все три формулы обязаны ходить через одну константу. Это не косметика: toVolt()
    # делит на heaterMaxPwr, который сама же страница и заполняет как U**2/R, поэтому
    # U сокращается и результат равен sqrt(W*R) - но ТОЛЬКО пока обе половины берут
    # одно и то же U. Разъехавшиеся половины дают тихую ошибку в U_prefill/U_toVolt раз.
    if "function wattsToProgramVolts(watts, heaterMaxPwr)" not in page:
        errors.append("data_raw/program.htm: wattsToProgramVolts() helper is missing")
    if "function programVoltsToWatts(volts, heaterMaxPwr)" not in page:
        errors.append("data_raw/program.htm: programVoltsToWatts() helper is missing")
    if not re.search(
        r"function programVoltsToWatts\(volts, heaterMaxPwr\) \{\s*"
        r"var ratio = volts / mainsVolt;\s*"
        r"return Math\.round\(heaterMaxPwr \* ratio \* ratio\);",
        page,
    ):
        errors.append(
            "data_raw/program.htm: programVoltsToWatts() must invert wattsToProgramVolts() "
            "with mainsVolt and heaterMaxPwr"
        )
    conversions = re.findall(r"Math\.round\(\s*mainsVolt\s*\*\s*Math\.sqrt\(", page)
    if len(conversions) != 1:
        errors.append(
            "data_raw/program.htm: expected exactly one watt->volt conversion in wattsToProgramVolts() "
            f"(found {len(conversions)})"
        )
    if page.count("wattsToProgramVolts(") < 3:
        errors.append(
            "data_raw/program.htm: wattsToProgramVolts() must be the single formula and used from "
            "display and apply-recommendations paths"
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

    # --- firmware clamp must still be exactly 230 -----------------------------
    # This is now an independent invariant, not one shared with the client: the
    # clamp is a regulator setpoint ceiling, unrelated to the real mains voltage
    # the client renders against.
    if len(firmware_volts) == 1:
        firmware_volt = next(iter(firmware_volts))
        if firmware_volt != 230:
            errors.append(
                f"power_regulator.h: the setpoint clamp is {firmware_volt:g} V, expected 230 V"
            )
    if "const availableMaxVolts = Math.min(mainsVolt, 230);" not in page:
        errors.append(
            "data_raw/program.htm: voltage recommendations do not limit the setpoint to mains or 230 V"
        )
    if "const recommendedMaxVolts = wattsToProgramVolts(recommendedMaxW, heaterMaxPwr);" not in page:
        errors.append(
            "data_raw/program.htm: recommendation precheck no longer uses the same watt-to-volt conversion"
        )

    # --- mainsVoltage is actually wired up in /ui-bootstrap ------------------
    if '"mainsVoltage", snapshot.setup.MainsVoltage' not in web_server:
        errors.append(
            "WebServer.ino: /ui-bootstrap does not serve mainsVoltage"
        )

    if errors:
        return fail(errors)
    print("program voltage scale smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
