#!/usr/bin/env python3
"""Статический контракт регистрации отдельного режима сыроварения."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


samovar_h = (ROOT / "Samovar.h").read_text(encoding="utf-8")
samovar_ino = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
registry = (ROOT / "mode_registry.h").read_text(encoding="utf-8")
power = (ROOT / "power_regulator.h").read_text(encoding="utf-8")
web = (ROOT / "WebServer.ino").read_text(encoding="utf-8")
lua = (ROOT / "lua.h").read_text(encoding="utf-8")

require(
    "SAMOVAR_LUA_MODE, SAMOVAR_CHEESE_MODE" in samovar_h,
    "Сырный режим должен быть дописан после LUA без перенумерации старых режимов",
)
require(
    "SAMOVAR_POWER_OFF, SAMOVAR_CHEESE, SAMOVAR_CHEESE_NEXT" in samovar_h,
    "Сырные команды должны быть добавлены после существующих команд",
)
require(
    '#include "cheese.h"' in samovar_ino,
    "Главный sketch не подключает cheese.h",
)
require(
    "{SAMOVAR_CHEESE_MODE," in registry and '"/cheese.htm"' in registry,
    "В mode registry нет отдельной строки и страницы сыроварения",
)
require(
    "SAMOVAR_STATUS_CHEESE" in registry and "SAMOVAR_CHEESE_NEXT" in registry,
    "Реестр не связывает сырный статус с командой следующего этапа",
)
require(
    "Samovar_Mode == SAMOVAR_CHEESE_MODE" in power and
    "outputs &= ~SAFETY_HEATER_OUTPUT_BOOST" in power,
    "Разгонный ТЭН не отделён от сливного клапана в режиме Сыр",
)
require(
    'server.on("/cheese.htm"' in web and
    'send_mode_specific_htm(request, "/cheese.htm", SAMOVAR_CHEESE_MODE)' in web,
    "WebServer не раздаёт отдельную страницу сыроварения",
)
require(
    "lua_pin_reserved_for_cheese_ph" in lua and
    "LUA_PIN is reserved for cheese pH sensor" in lua,
    "Lua может переназначить общий LUA_PIN во время сыроварения",
)
require(
    '"cheese.htm"' in web and '"calibrate_ph.htm"' in web,
    "Новые сырные страницы отсутствуют в списке обновления интерфейса",
)
require(
    "const int32_t allowedModes[] = {0, 1, 2, 3, 4, 5, 6, 7};" in web and
    "allowedModes, 8, requestedModeValue" in web,
    "WebServer не принимает и не сохраняет mode=7",
)
require(
    "#ifdef USE_LUA\ninline bool cheese_lua_result_pending" in
    (ROOT / "cheese.h").read_text(encoding="utf-8"),
    "Lua-тип Cheese просачивается в сборки без USE_LUA",
)
require(
    "Samovar_Mode == SAMOVAR_BEER_MODE ||\n      Samovar_Mode == SAMOVAR_CHEESE_MODE" in samovar_ino,
    "Общий расчёт прогресса не обслуживает Cheese",
)
require(
    "status == SAMOVAR_STATUS_CHEESE && snapshot.powerOn" in samovar_ino,
    "Телеметрия скрывает тип активного этапа Cheese",
)
require(
    "pinMode(LUA_PIN, INPUT);" in (ROOT / "cheese.h").read_text(encoding="utf-8"),
    "При старте Cheese LUA_PIN не возвращается в режим входа",
)
cheese_runtime = (ROOT / "cheese.h").read_text(encoding="utf-8")
for token in (
    "alarm_c_min = 0;",
    "alarm_c_low_min = 0;",
    "currentstepcnt = 0;",
    "beerMixerPauseSinceMs = 0;",
):
    require(token in cheese_runtime, f"Новая строка Cheese не сбрасывает {token}")
require(
    "const bool sensorRequired = kind == CHEESE_STAGE_HEAT_TO_TARGET" in cheese_runtime and
    "if (sensorRequired &&" in cheese_runtime,
    "W/R/S всё ещё зависят от датчика температуры",
)
require(
    "stepper_safe_reverse(true);" in cheese_runtime and
    "stepper_safe_reverse(false);" in cheese_runtime,
    "Дозатор Cheese не восстанавливает штатное направление STEPPER_REVERSE",
)

print("OK: отдельный режим Сыр зарегистрирован без перенумерации старых режимов")
