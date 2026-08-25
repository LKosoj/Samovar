#!/usr/bin/env python3
"""Страж: mode_common.h::mode_request_overheat_emergency_if_needed() НЕ должна
сравнивать SteamSensor с MAX_STEAM_TEMP.

[24.08.2026] Такую отсечку уже пытались добавить (операнд
sensor_temp_at_least(SteamSensor, MAX_STEAM_TEMP) в OR-условии + " Пара" в
тексте сообщения) - код-ревью признало правку ошибочной, её откатили. Тест
фиксирует это решение, чтобы попытка не повторилась молча.

Почему это ошибка, по фактам из кода:
  - MAX_STEAM_TEMP = 98.8°C - порог РЕКТИФИКАЦИИ. Он уже применяется по
    назначению в alarm.h:285 (check_alarm()), где пар идёт по колонне и
    физически не должен быть горячее 98.8.
  - mode_request_overheat_emergency_if_needed() - общий хелпер, его зовут БК
    (BK.h:121) и дистилляция (distiller.h:203), а также пиво, сувид, Lua.
    В БК и дистилляции штатное завершение процесса идёт по температуре КУБА:
    TankSensor.avgTemp >= SamSetup.DistTemp (BK.h:52, distiller.h:117),
    дефолт DistTemp = 99.9°C (Samovar_ini.h:57, DEFAULT_DIST_TEMP). Пока куб
    доходит до 99.9, температура пара из куба штатно поднимается к 99-100°C -
    то есть общая отсечка 98.8 сработала бы РАНЬШЕ штатного финиша и
    превратила бы нормальное окончание перегонки в аварийный останов с
    защёлкой (alarm_event, сбрасывается только перезагрузкой) и зуммером.
  - Для того же физического признака в НБК прошивка трактует "Тп > 98°C" не
    как аварию, а как мягкое завершение "Кончилась брага" (nbk.h:1266,
    1291-1297) - это подтверждает, что рост температуры пара тут штатный, а
    не аномальный.

Тест не компилирует харнесс - он текстовый: извлекает тело функции через
extract_function_body (tools/smoke_helpers.py) и проверяет, что в нём нет
токенов SteamSensor и MAX_STEAM_TEMP.
"""
import sys
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

OVERHEAT_SIGNATURE = "inline void mode_request_overheat_emergency_if_needed()"

errors: list[str] = []

source = (ROOT / "mode_common.h").read_text(encoding="utf-8")

try:
    body = extract_function_body(source, OVERHEAT_SIGNATURE)
except ValueError as error:
    errors.append(str(error))
    body = ""

if body:
    for forbidden in ("SteamSensor", "MAX_STEAM_TEMP"):
        if forbidden in body:
            errors.append(
                "mode_request_overheat_emergency_if_needed() снова сравнивает пар с "
                f"{forbidden} - эта отсечка уже отклонена code review 24.08.2026 "
                "(см. докстринг этого теста и SOLUTIONS_2026-08-24.md, п.6 "
                "'Уровень 3'): MAX_STEAM_TEMP=98.8 - порог ректификации "
                "(alarm.h:285), а в БК/дистилляции пар штатно доходит до "
                "99-100°C РАНЬШЕ, чем куб до SamSetup.DistTemp=99.9 "
                "(BK.h:52, distiller.h:117) - общая отсечка ложно сработает "
                "раньше штатного финиша и уйдёт в аварийный останов с защёлкой."
            )

if errors:
    print("steam cutoff must not live in common alarm smoke failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print("steam cutoff not in common alarm smoke passed")
