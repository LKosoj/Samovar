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

print("OK: отдельный режим Сыр зарегистрирован без перенумерации старых режимов")
