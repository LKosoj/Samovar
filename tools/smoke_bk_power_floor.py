#!/usr/bin/env python3
"""Нижняя граница BKPower обязана быть рабочим порогом регулятора, а не нулём.

BKPower - мощность режима "бражная колонна" (БК) после закипания
(BK.h::check_alarm_bk). Если пользователь задаст её ниже рабочего порога
регулятора (power_work_mode_threshold()), set_current_power() сам уводит
регулятор в спящий режим - нагрев пропадает, процесс тихо встаёт.

Три места обязаны быть согласованы:
  1. kSaveFloatFields в WebServer.ino - нижняя граница при сохранении формы.
  2. setupKeyProcessor() в WebServer.ino - отдаёт этот же порог странице
     (переменная шаблона %BKPowerFloor%).
  3. setupNumericSchema в data_raw/setup.htm - клиентская проверка перед
     отправкой формы читает порог с сервера, а не хардкодит число.

Тест пинит СОГЛАСИЕ (что все три места используют именно
power_work_mode_threshold()/%BKPowerFloor%), а не число - число само по себе
меняется от сборки к сборке (KVIC/RMVK: 40, SEM_AVR: 100).
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB_SERVER = ROOT / "WebServer.ino"
SETUP_PAGE = ROOT / "data_raw" / "setup.htm"


def read(path: Path, errors: list[str]) -> str:
    if not path.exists():
        errors.append(f"{path.relative_to(ROOT)}: файл не найден")
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def main() -> int:
    errors: list[str] = []

    web = read(WEB_SERVER, errors)
    setup = read(SETUP_PAGE, errors)
    if not web or not setup:
        for error in errors:
            print(f" - {error}")
        return 1

    # --- (1) kSaveFloatFields: минимум BKPower - вызов, а не литерал -------------
    field_match = re.search(
        r'\{"BKPower",\s*&SetupEEPROM::BKPower,\s*([^,]+),\s*([^}]+)\}', web
    )
    if not field_match:
        errors.append(
            "WebServer.ino: запись BKPower не найдена в kSaveFloatFields"
        )
    else:
        min_expr = field_match.group(1).strip()
        if min_expr != "power_work_mode_threshold()":
            errors.append(
                "WebServer.ino: kSaveFloatFields[BKPower].minValue должно быть "
                f"power_work_mode_threshold(), а не {min_expr!r} - форма снова "
                "примет значение ниже рабочего порога регулятора"
            )

    # --- (2) setupKeyProcessor: ветка BKPowerFloor отдаёт тот же порог ----------
    if 'var == "BKPowerFloor"' not in web:
        errors.append(
            "WebServer.ino: в setupKeyProcessor() нет ветки BKPowerFloor - "
            "странице setup.htm неоткуда взять рабочий порог регулятора"
        )
    elif "return String(power_work_mode_threshold(), 2);" not in web:
        errors.append(
            "WebServer.ino: ветка BKPowerFloor не отдаёт power_work_mode_threshold() "
            "- значение на странице разойдётся с реальным порогом регулятора"
        )

    # --- (3) setup.htm: схема валидации читает порог с сервера ------------------
    schema_match = re.search(r"\{ name: 'BKPower'[^}]*\}", setup)
    if not schema_match:
        errors.append(
            "data_raw/setup.htm: схема setupNumericSchema не содержит поле BKPower"
        )
    elif "Number('%BKPowerFloor%')" not in schema_match.group(0):
        errors.append(
            "data_raw/setup.htm: setupNumericSchema['BKPower'].min не читает "
            f"%BKPowerFloor% с сервера (найдено: {schema_match.group(0)}) - "
            "клиентская проверка снова разойдётся с прошивкой"
        )

    if errors:
        print("BK power floor smoke failed:")
        for error in errors:
            print(f" - {error}")
        return 1
    print("BK power floor smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
