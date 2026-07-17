#!/usr/bin/env python3
"""Единая точка правды по сопротивлению ТЭНа.

Прошивка, форма настроек и страница программы обязаны одинаково отвечать на вопрос
"какому сохранённому сопротивлению можно верить". Раньше ответов было четыре, и все
разные: power_regulator.h откатывался на плоские 4000 Вт, nbk.h на 18 Ом, Samovar.ino
переписывал ноль в 10 Ом, а program.htm верил любому R > 0. Из-за этого одно и то же
значение давало разную мощность в разных режимах, а на R = 1 страница обещала 52900 Вт
там, где прошивка выдавала 4000.

Тест пинит СОГЛАСИЕ, а не числа: границы извлекаются из control_numeric_input.h и
сверяются с теми, что зашиты в обе страницы и в приём формы. Перенастройка диапазона
остаётся правкой в одну строку на каждой стороне; тихое расхождение сторон - нет.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "control_numeric_input.h"
NVS = ROOT / "NVS_Manager.ino"
SETUP_PAGE = ROOT / "data_raw" / "setup.htm"
PROGRAM_PAGE = ROOT / "data_raw" / "program.htm"

# Кто угодно, кроме самой control_numeric_input.h, обязан спрашивать доверенное R у неё,
# а не решать самостоятельно.
FIRMWARE_GLOBS = ("*.h", "*.ino")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def constant(text: str, name: str, errors: list[str]) -> float | None:
    match = re.search(rf"static const float {name} = ([0-9.]+)f;", text)
    if not match:
        errors.append(f"control_numeric_input.h: не найдена константа {name}")
        return None
    return float(match.group(1))


def main() -> int:
    errors: list[str] = []
    source = read(SOURCE)

    low = constant(source, "CONTROL_HEATER_R_MIN", errors)
    high = constant(source, "CONTROL_HEATER_R_MAX", errors)
    default = constant(source, "CONTROL_HEATER_R_DEFAULT", errors)
    if low is None or high is None or default is None:
        for error in errors:
            print(f" - {error}")
        return 1

    if not low < default < high:
        errors.append(
            f"заводское сопротивление {default:g} Ом вне собственного доверенного "
            f"диапазона {low:g}..{high:g} - откат уводил бы в недоверенное значение"
        )

    # Заводское значение обязано совпадать с тем, что реально пишется в NVS: иначе
    # свежее устройство и устройство с испорченной записью считают разную мощность.
    nvs_match = re.search(r"candidate\.HeaterResistant = ([0-9.]+);", read(NVS))
    if not nvs_match:
        errors.append("NVS_Manager.ino: не найдено заводское значение HeaterResistant")
    elif float(nvs_match.group(1)) != default:
        errors.append(
            f"заводское сопротивление разъехалось: control_numeric_input.h говорит "
            f"{default:g} Ом, NVS_Manager.ino пишет {nvs_match.group(1)} Ом"
        )

    # --- никто не принимает решение о доверии самостоятельно ---------------------
    for pattern in FIRMWARE_GLOBS:
        for path in sorted(ROOT.glob(pattern)):
            if path.name == SOURCE.name:
                continue
            text = read(path)
            for match in re.finditer(r"/\s*SamSetup\.HeaterResistant", text):
                line = text[: match.start()].count("\n") + 1
                errors.append(
                    f"{path.name}:{line}: деление на сырое SamSetup.HeaterResistant - "
                    "оно бывает нулём и вне диапазона, нужно trusted_heater_resistance()"
                )
            # Сравнение с чем угодно, не только с литералом: `R > someLimit` - такое же
            # локальное решение о доверии, как `R > 1`, и оно обязано ловиться.
            for match in re.finditer(
                r"SamSetup\.HeaterResistant\s*(?:[<>]=?|[=!]=)\s*[0-9A-Za-z_]", text
            ):
                line = text[: match.start()].count("\n") + 1
                errors.append(
                    f"{path.name}:{line}: локальное решение о доверии к "
                    "SamSetup.HeaterResistant в обход trusted_heater_resistance()"
                )

    # --- загруженный профиль лечится до того, как им начнут пользоваться ---------
    # Ни чтение NVS, ни миграция из EEPROM диапазон не проверяют, а в setup.htm уходит
    # сырое SamSetup.HeaterResistant. Не вылечив профиль на загрузке, получаем расхождение:
    # страница показывает сохранённый мусор, а мощность считается по подставленному
    # заводскому значению. Порядок тут - половина смысла, поэтому пинится он, а не факт.
    boot = read(ROOT / "Samovar.ino")
    heal = boot.find("startupProfile.HeaterResistant = trusted_heater_resistance(")
    publish = boot.find("SamSetup = startupProfile;")
    persist = boot.find("save_profile_nvs(startupProfile)")
    if heal == -1:
        errors.append(
            "Samovar.ino: загруженный профиль не проходит через trusted_heater_resistance() "
            "- сырое R из NVS/EEPROM попадёт в setup.htm мимо расчётов"
        )
    elif publish != -1 and heal > publish:
        errors.append(
            "Samovar.ino: профиль лечится после `SamSetup = startupProfile;` - "
            "в SamSetup успевает попасть недоверенное R"
        )
    elif persist != -1 and heal > persist:
        errors.append(
            "Samovar.ino: профиль лечится после save_profile_nvs() - "
            "мигрированный профиль сохранится в NVS невылеченным"
        )

    # --- приём формы обязан идти через те же константы --------------------------
    web = read(ROOT / "WebServer.ino")
    if not re.search(
        r'apply_save_float_arg\(\s*request,\s*"HeaterR",\s*staged\.HeaterResistant,\s*'
        r"CONTROL_HEATER_R_MIN,\s*CONTROL_HEATER_R_MAX\s*\)",
        web,
    ):
        errors.append(
            "WebServer.ino: приём HeaterR не привязан к CONTROL_HEATER_R_MIN/MAX - "
            "форма примет значение, которому прошивка всё равно не поверит"
        )

    # --- обе страницы обязаны знать тот же диапазон -----------------------------
    setup = read(SETUP_PAGE)
    expected_schema = f"{{ name: 'HeaterR', min: {low:g}, max: {high:g} }}"
    if expected_schema not in setup:
        found = re.search(r"\{ name: 'HeaterR'[^}]*\}", setup)
        errors.append(
            f"data_raw/setup.htm: схема HeaterR не совпадает с прошивкой: ожидалось "
            f"{expected_schema}, найдено {found.group(0) if found else 'ничего'}"
        )

    program = read(PROGRAM_PAGE)
    expected_gate = (
        f"Number.isFinite(heaterResistance) && heaterResistance >= {low:g} "
        f"&& heaterResistance <= {high:g}"
    )
    if expected_gate not in program:
        errors.append(
            f"data_raw/program.htm: условие доверия к R не совпадает с прошивкой: "
            f"ожидалось `{expected_gate}` - иначе страница снова начнёт показывать "
            "мощность, которой прошивка не даст"
        )

    if errors:
        print("heater resistance single source smoke failed:")
        for error in errors:
            print(f" - {error}")
        return 1
    print("heater resistance single source smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
