#!/usr/bin/env python3
"""Окно настройки, сборки и прошивки Samovar для Windows."""

import argparse
import ast
import gzip
import ipaddress
import json
import os
import codecs
import io
import queue
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

BOARD_OPTIONS = {
    "ESP32 DevKit": ("DEVKIT", "Samovar"),
    "LILYGO": ("LILYGO", "Samovar"),
    "ESP32-S3": ("ESP32S3", "Samovar_s3"),
}

CHOICE_OPTIONS = {
    "Регулятор мощности": {
        "Не использовать": (),
        "KVIC": ("SAMOVAR_USE_POWER",),
        "РМВ-К": ("SAMOVAR_USE_POWER", "SAMOVAR_USE_RMVK"),
        "SEM_AVR": ("SAMOVAR_USE_POWER", "SAMOVAR_USE_SEM_AVR"),
    },
    "Датчик атмосферного давления": {
        "Не использовать": (),
        "BMP180/BMP085": ("USE_BMP180",),
        "BMP280": ("USE_BMP280",),
        "BMP280, альтернативный адрес": ("USE_BMP280_ALT",),
        "BME280": ("USE_BME280",),
        "BME680": ("USE_BME680",),
    },
    "Датчик давления в колонне": {
        "Не использовать": (),
        "XGZP6897D": ("USE_PRESSURE_XGZ",),
        "1-Wire": ("USE_PRESSURE_1WIRE",),
        "MPX5010D": ("USE_PRESSURE_MPX",),
    },
}


@dataclass(frozen=True)
class ValueSpec:
    macro: str
    label: str
    section: str
    kind: str = "number"


@dataclass(frozen=True)
class BoolSpec:
    macro: str
    label: str
    section: str


@dataclass(frozen=True)
class OptionalSpec:
    macro: str
    label: str
    section: str
    kind: str = "number"


@dataclass(frozen=True)
class DeviceConfigField:
    name: str
    kind: str
    since: int = 1


VALUE_SPECS = (
    ValueSpec("SAMOVAR_HOST", "Имя устройства в сети", "Основные", "text"),
    ValueSpec("ALARM_WATER_TEMP", "Предупреждение по температуре воды, °C", "Температуры"),
    ValueSpec("MAX_WATER_TEMP", "Аварийная температура воды, °C", "Температуры"),
    ValueSpec("MAX_STEAM_TEMP", "Аварийная температура пара, °C", "Температуры"),
    ValueSpec("MAX_ACP_TEMP", "Аварийная температура ТСА, °C", "Температуры"),
    ValueSpec("CHANGE_POWER_MODE_STEAM_TEMP", "Температура перехода из разгона, °C", "Температуры"),
    ValueSpec("OPEN_VALVE_TANK_TEMP", "Температура открытия охлаждения, °C", "Температуры"),
    ValueSpec("DELTA_T_CLOSE_VALVE", "Запас температуры выключения охлаждения, °C", "Температуры"),
    ValueSpec("HEAT_DELTA", "Порог полного нагрева, °C", "Температуры"),
    ValueSpec("ACCELERATION_HEATER_DELTA", "Порог разгонного ТЭНа, °C", "Температуры"),
    ValueSpec("BOILING_TEMP", "Температура кипения пива, °C", "Температуры"),
    ValueSpec("DEFAULT_DIST_TEMP", "Температура завершения дистилляции, °C", "Температуры"),
    ValueSpec("PWM_LOW_VALUE", "Минимальная мощность насоса, %", "Насосы"),
    ValueSpec("PWM_START_VALUE", "Стартовая мощность насоса, %", "Насосы"),
    ValueSpec("WF_CALIBRATION", "Калибровка датчика потока", "Насосы"),
    ValueSpec("WATER_FLOW_MIN_PULSES", "Минимум импульсов потока", "Насосы"),
    ValueSpec("NBK_MULT_PAUSE_OVERFLOW", "Пауза после захлёба, инерций", "НБК"),
    ValueSpec("NBK_PUMP_LIMIT", "Предельная подача насоса, л/ч", "НБК"),
    ValueSpec("NBK_WORK_PRESSURE_RATIO", "Доля рабочего давления", "НБК"),
    ValueSpec("NBK_PRESSURE_MARGIN", "Запас давления, мм рт. ст.", "НБК"),
    ValueSpec("NBK_END_STEAM_RISE", "Рост температуры пара для завершения, °C", "НБК"),
    ValueSpec("SAMOVAR_USE_POWER_START_TIME", "Задержка запуска регулятора, мс", "Регулятор"),
    ValueSpec("LCD_RESET_PERIOD_MS", "Период сброса дисплея, мс", "Оборудование"),
    ValueSpec("PAUSE_RESUME_HYSTERESIS_DELTA", "Гистерезис паузы, °C", "Ректификация"),
    ValueSpec("PROGRAM_ROW_STOP_PAUSE_LIMIT", "Число стоп-пауз строки", "Ректификация"),
    ValueSpec("PROGRAM_ROW_STOP_PAUSE_SPEED_CUT_PCT", "Снижение скорости после стоп-пауз, %", "Ректификация"),
    ValueSpec("PROGRAM_DONE_AUTO_POWEROFF_MIN", "Автовыключение после программы, мин", "Ректификация"),
    ValueSpec("BODY_TEMP_AUTOSET_MAX_RISE", "Предел автоподъёма температуры тела, °C", "Ректификация"),
    ValueSpec("BK_STEAM_SETPOINT_MIN", "Минимальная уставка пара БК, °C", "БК"),
    ValueSpec("BK_STEAM_SETPOINT_MAX", "Максимальная уставка пара БК, °C", "БК"),
    ValueSpec("BK_WATER_ADJUST_PERIOD_MS", "Период регулировки воды БК, мс", "БК"),
    ValueSpec("BK_WATER_DEADBAND", "Мёртвая зона воды БК, °C", "БК"),
    ValueSpec("BK_WATER_PWM_STEP", "Шаг ШИМ воды БК", "БК"),
    ValueSpec("BLYNK_SAMOVAR_TOOL", "Сервер Blynk", "Сеть", "text"),
)

BOOL_SPECS = (
    BoolSpec("SAMOVAR_USE_BLYNK", "Использовать Blynk", "Сеть"),
    BoolSpec("NOT_USE_INTERFACE_UPDATE", "Не обновлять веб-интерфейс автоматически", "Сеть"),
    BoolSpec("USE_UPDATE_OTA", "Разрешить обновление по Wi-Fi", "Сеть"),
    BoolSpec("KVIC_USE_9600", "KVIC: скорость UART 9600", "Регулятор"),
    BoolSpec("KVIC_DEBUG", "Отладочные сообщения KVIC", "Регулятор"),
    BoolSpec("USE_NBK_DELTA_PRESSURE", "Корректировать температуру барды по давлению", "НБК"),
    BoolSpec("USE_NBK_END_BY_STEAM_RISE", "Завершать НБК по росту температуры пара", "НБК"),
    BoolSpec("USE_WATERSENSOR", "Использовать датчик потока воды", "Насосы"),
    BoolSpec("USE_WATER_PUMP", "Управлять насосом воды или мешалкой", "Насосы"),
    BoolSpec("USE_HEAD_LEVEL_SENSOR", "Использовать датчик уровня флегмы", "Датчики"),
    BoolSpec("IGNORE_HEAD_LEVEL_SENSOR_SETTING", "Запретить отключение датчика флегмы в веб-интерфейсе", "Датчики"),
    BoolSpec("WHLS_HIGH_PULL", "Датчик уровня жидкости N-P-N", "Датчики"),
    BoolSpec("USE_ALARM_BTN", "Использовать аварийную кнопку", "Оборудование"),
    BoolSpec("USE_BTN", "Использовать кнопку управления", "Оборудование"),
    BoolSpec("USE_BODY_TEMP_AUTOSET", "Автокоррекция температуры тела", "Ректификация"),
    BoolSpec("USE_LUA", "Использовать Lua", "Оборудование"),
    BoolSpec("USE_STEPPER_ACCELERATION", "Плавный разгон шагового двигателя", "Шаговый двигатель"),
    BoolSpec("STEPPER_REVERSE", "Обратное направление шагового двигателя", "Шаговый двигатель"),
    BoolSpec("COLUMN_WETTING", "Смачивание насадки перед ректификацией", "Ректификация"),
)

OPTIONAL_SPECS = (
    OptionalSpec("USE_WATER_VALVE", "Управление клапаном воды", "Насосы", "token"),
    OptionalSpec("USE_EXPANDER", "Адрес расширителя PCF8575", "Оборудование", "number"),
    OptionalSpec("USE_ANALOG_EXPANDER", "Адрес расширителя PCF8591", "Оборудование", "number"),
    OptionalSpec("I2CStepperStepMl", "Шагов на мл для I2CStepper", "Шаговый двигатель", "number"),
    OptionalSpec("WETTING_POWER", "Мощность смачивания насадки", "Ректификация", "number"),
)

CHOICE_VALUE_SPECS = (
    ValueSpec("USE_PRESSURE_XGZ", "Коэффициент датчика XGZP6897D", "Датчики", "number"),
    ValueSpec("USE_PRESSURE_1WIRE", "Адрес датчика давления 1-Wire", "Датчики", "onewire"),
)


DEVICE_CONFIG_SCHEMA_VERSION = 1
FIRMWARE_BOARD_TOKENS = {
    "DEVKIT": "ESP32 DevKit",
    "LILYGO": "LILYGO",
    "ESP32S3": "ESP32-S3",
}
FIRMWARE_CHOICE_TOKENS = {
    "regulator": {
        "none": "Не использовать",
        "kvic": "KVIC",
        "rmvk": "РМВ-К",
        "sem_avr": "SEM_AVR",
    },
    "atmospheric_sensor": {
        "none": "Не использовать",
        "bmp180": "BMP180/BMP085",
        "bmp280": "BMP280",
        "bmp280_alt": "BMP280, альтернативный адрес",
        "bme280": "BME280",
        "bme680": "BME680",
    },
    "column_pressure_sensor": {
        "none": "Не использовать",
        "xgz": "XGZP6897D",
        "onewire": "1-Wire",
        "mpx": "MPX5010D",
    },
}


def _device_config_fields() -> Tuple[DeviceConfigField, ...]:
    fields = [
        DeviceConfigField("board", "board"),
        DeviceConfigField("servoDelta", "servo"),
    ]
    fields.extend(DeviceConfigField(spec.macro, "value") for spec in VALUE_SPECS)
    fields.extend(DeviceConfigField(spec.macro, "bool") for spec in BOOL_SPECS)
    fields.extend(DeviceConfigField(spec.macro, "optional") for spec in OPTIONAL_SPECS)
    fields.extend(DeviceConfigField(spec.macro, "choice_value") for spec in CHOICE_VALUE_SPECS)
    fields.extend(DeviceConfigField(name, "choice") for name in FIRMWARE_CHOICE_TOKENS)
    fields.extend((
        DeviceConfigField("wifi_ssid", "wifi"),
        DeviceConfigField("wifi_password", "wifi"),
    ))
    return tuple(fields)


DEVICE_CONFIG_FIELDS = _device_config_fields()


@dataclass(frozen=True)
class DeviceConfig:
    firmware_version: str
    settings: Dict[str, object]

SECTIONS = (
    "Основные", "Температуры", "Регулятор", "БК", "НБК", "Датчики",
    "Насосы", "Оборудование", "Шаговый двигатель", "Ректификация", "Сеть",
)

NUMERIC_RE = re.compile(
    r"^(?P<number>[+-]?(?:0[xX][0-9A-Fa-f]+|(?:(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)))"
    r"(?P<suffix>[fFuUlL]{0,3})$"
)
ONEWIRE_RE = re.compile(
    r"^\{\s*0x[0-9A-Fa-f]{2}(?:\s*,\s*0x[0-9A-Fa-f]{2}){7}\s*\}$"
)


class ConfigError(ValueError):
    pass


@dataclass
class MacroLine:
    index: int
    enabled: bool
    value: str
    comment: str
    indent: str


class HeaderDocument:
    def __init__(self, text: str):
        self.trailing_newline = text.endswith("\n")
        self.lines = text.splitlines()

    def find(self, macro: str) -> Optional[MacroLine]:
        pattern = re.compile(
            r"^(?P<indent>\s*)(?P<disabled>//\s*)?#define\s+"
            + re.escape(macro)
            + r"\b(?P<rest>.*)$"
        )
        for index, line in enumerate(self.lines):
            match = pattern.match(line)
            if not match:
                continue
            rest = match.group("rest")
            comment_match = re.search(r"\s+//", rest)
            if comment_match:
                value = rest[:comment_match.start()].strip()
                comment = rest[comment_match.start():]
            else:
                value = rest.strip()
                comment = ""
            return MacroLine(
                index=index,
                enabled=match.group("disabled") is None,
                value=value,
                comment=comment,
                indent=match.group("indent"),
            )
        return None

    def preceding_description(self, index: int) -> str:
        comments = []
        for line in reversed(self.lines[:index]):
            stripped = line.strip()
            if not stripped.startswith("//"):
                break
            comment = stripped[2:].strip()
            if re.fullmatch(r"[*=-]+", comment):
                break
            if comment:
                comments.append(comment)
        return " ".join(reversed(comments))

    def description(self, macro: str) -> str:
        found = self.find(macro)
        if found is None:
            return ""
        if found.comment:
            return found.comment.split("//", 1)[1].strip()
        return self.preceding_description(found.index)

    def set_macro(self, macro: str, enabled: bool, value: str = "") -> None:
        found = self.find(macro)
        if found is None:
            raise ConfigError("В файле не найдена настройка {}".format(macro))
        prefix = found.indent + ("" if enabled else "//") + "#define " + macro
        self.lines[found.index] = prefix + ((" " + value) if value else "") + found.comment

    def set_choice(self, macros: Tuple[str, ...], selected: Tuple[str, ...]) -> None:
        for macro in macros:
            found = self.find(macro)
            if found is None:
                raise ConfigError("В файле не найдена настройка {}".format(macro))
            self.set_macro(macro, macro in selected, found.value)

    def insert_before_final_endif(self, lines: List[str]) -> None:
        for index in range(len(self.lines) - 1, -1, -1):
            if self.lines[index].lstrip().startswith("#endif"):
                self.lines[index:index] = lines
                return
        raise ConfigError("В user_config_override.h не найден завершающий #endif")

    def render(self) -> str:
        return "\n".join(self.lines) + ("\n" if self.trailing_newline else "")


def cpp_string_decode(value: str) -> str:
    try:
        decoded = ast.literal_eval(value)
    except (SyntaxError, ValueError):
        raise ConfigError("Некорректная строка C++: {}".format(value))
    if not isinstance(decoded, str):
        raise ConfigError("Ожидалась строка C++: {}".format(value))
    return decoded


def cpp_string_encode(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("\r", "\\r").replace("\n", "\\n")
    return '"{}"'.format(escaped)


def validate_value(value: str, kind: str, label: str) -> None:
    if kind == "text":
        if not value:
            raise ConfigError("Поле «{}» не должно быть пустым".format(label))
        if "\n" in value or "\r" in value:
            raise ConfigError("Поле «{}» должно занимать одну строку".format(label))
    elif kind == "number":
        if not NUMERIC_RE.fullmatch(value.strip()):
            raise ConfigError("В поле «{}» требуется число".format(label))
    elif kind == "onewire":
        if not ONEWIRE_RE.fullmatch(value.strip()):
            raise ConfigError("В поле «{}» требуется восемь байтов вида 0x12".format(label))
    elif kind == "token":
        if value not in ("LOW", "HIGH"):
            raise ConfigError("В поле «{}» допустимы только LOW или HIGH".format(label))


def numeric_value_for_ui(value: str) -> str:
    match = NUMERIC_RE.fullmatch(value.strip())
    return match.group("number") if match is not None else value


def numeric_value_for_source(value: str, current: str) -> str:
    value_match = NUMERIC_RE.fullmatch(value.strip())
    current_match = NUMERIC_RE.fullmatch(current.strip())
    if value_match is None or current_match is None:
        raise ConfigError("Некорректное числовое значение")
    return value_match.group("number") + current_match.group("suffix")


def atomic_write(path: Path, text: str) -> None:
    mode = path.stat().st_mode if path.exists() else None
    descriptor, temporary_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        if mode is not None:
            os.chmod(temporary_name, mode)
        os.replace(temporary_name, str(path))
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


class SamovarConfig:
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.ini_path = project_root / "Samovar_ini.h"
        self.override_path = project_root / "user_config_override.h"
        self.override_template_path = project_root / "user_config_override.example.h"

    def ensure_override(self) -> None:
        if self.override_path.exists():
            return
        if not self.override_template_path.exists():
            raise ConfigError("Не найден шаблон user_config_override.example.h")
        shutil.copyfile(str(self.override_template_path), str(self.override_path))

    def load(self) -> Dict[str, object]:
        self.ensure_override()
        ini = HeaderDocument(self.ini_path.read_text(encoding="utf-8"))
        override = HeaderDocument(self.override_path.read_text(encoding="utf-8"))
        state: Dict[str, object] = {}

        active_board = "DEVKIT"
        for label, (macro_value, _) in BOARD_OPTIONS.items():
            line = self._board_line(ini, macro_value)
            if line.enabled:
                active_board = label
                break
        state["board"] = active_board if active_board in BOARD_OPTIONS else "ESP32 DevKit"

        for spec in VALUE_SPECS:
            line = self._required_line(ini, spec.macro)
            if spec.macro == "BLYNK_SAMOVAR_TOOL" and not line.enabled:
                state[spec.macro] = ""
                continue
            state[spec.macro] = (
                cpp_string_decode(line.value)
                if spec.kind == "text"
                else numeric_value_for_ui(line.value)
            )
        for spec in BOOL_SPECS:
            state[spec.macro] = self._required_line(ini, spec.macro).enabled
        for spec in OPTIONAL_SPECS:
            line = self._required_line(ini, spec.macro)
            state[spec.macro + ".enabled"] = line.enabled
            state[spec.macro] = (
                numeric_value_for_ui(line.value) if spec.kind == "number" else line.value
            )
        for spec in CHOICE_VALUE_SPECS:
            line = self._required_line(ini, spec.macro)
            state[spec.macro] = (
                numeric_value_for_ui(line.value) if spec.kind == "number" else line.value
            )

        state["regulator"] = self._read_choice(ini, CHOICE_OPTIONS["Регулятор мощности"])
        state["atmospheric_sensor"] = self._read_choice(
            ini, CHOICE_OPTIONS["Датчик атмосферного давления"]
        )
        state["column_pressure_sensor"] = self._read_choice(
            ini, CHOICE_OPTIONS["Датчик давления в колонне"]
        )

        servo_match = re.search(
            r"^\s*int8_t\s+servoDelta\s*\[11\]\s*=\s*\{([^}]*)\}\s*;",
            ini.render(),
            re.MULTILINE,
        )
        if servo_match is None:
            raise ConfigError("В Samovar_ini.h не найден массив servoDelta[11]")
        state["servoDelta"] = ", ".join(part.strip() for part in servo_match.group(1).split(","))

        state["wifi_ssid"] = self._read_override_string(override, "SAMOVAR_WIFI_SSID")
        state["wifi_password"] = self._read_override_string(override, "SAMOVAR_WIFI_PASSWORD")
        return state

    def descriptions(self) -> Dict[str, str]:
        ini = HeaderDocument(self.ini_path.read_text(encoding="utf-8"))
        descriptions = {}
        for spec in VALUE_SPECS + BOOL_SPECS + OPTIONAL_SPECS + CHOICE_VALUE_SPECS:
            description = ini.description(spec.macro)
            if description:
                descriptions[spec.macro] = description

        for index, line in enumerate(ini.lines):
            if re.match(r"^\s*int8_t\s+servoDelta\s*\[11\]", line):
                descriptions["servoDelta"] = ini.preceding_description(index)
                break

        for key, group in (
            ("regulator", "Регулятор мощности"),
            ("atmospheric_sensor", "Датчик атмосферного давления"),
            ("column_pressure_sensor", "Датчик давления в колонне"),
        ):
            options = []
            for label, macros in CHOICE_OPTIONS[group].items():
                description = ""
                for macro in reversed(macros):
                    description = ini.description(macro)
                    if description:
                        break
                if description:
                    options.append("{}: {}".format(label, description))
            if options:
                descriptions[key] = "\n".join(options)
        return descriptions

    def save(self, state: Dict[str, object]) -> None:
        self.ensure_override()
        ini = HeaderDocument(self.ini_path.read_text(encoding="utf-8"))
        override = HeaderDocument(self.override_path.read_text(encoding="utf-8"))

        board = str(state["board"])
        if board not in BOARD_OPTIONS:
            raise ConfigError("Неизвестная плата: {}".format(board))
        selected_board = BOARD_OPTIONS[board][0]
        for macro_value in ("DEVKIT", "LILYGO", "ESP32S3"):
            line = self._board_line(ini, macro_value)
            self._set_board_line(ini, line, macro_value == selected_board)

        for spec in VALUE_SPECS:
            if spec.macro == "BLYNK_SAMOVAR_TOOL":
                continue
            value = str(state[spec.macro]).strip()
            validate_value(value, spec.kind, spec.label)
            current = self._required_line(ini, spec.macro)
            ini.set_macro(
                spec.macro,
                True,
                cpp_string_encode(value)
                if spec.kind == "text"
                else numeric_value_for_source(value, current.value),
            )
        for spec in BOOL_SPECS:
            current = self._required_line(ini, spec.macro)
            ini.set_macro(spec.macro, bool(state[spec.macro]), current.value)

        blynk_server = str(state["BLYNK_SAMOVAR_TOOL"]).strip()
        current_blynk_server = self._required_line(ini, "BLYNK_SAMOVAR_TOOL")
        use_custom_blynk_server = bool(state["SAMOVAR_USE_BLYNK"]) and bool(blynk_server)
        if use_custom_blynk_server:
            validate_value(blynk_server, "text", "Сервер Blynk")
        ini.set_macro(
            "BLYNK_SAMOVAR_TOOL",
            use_custom_blynk_server,
            cpp_string_encode(blynk_server) if use_custom_blynk_server else current_blynk_server.value,
        )
        for spec in OPTIONAL_SPECS:
            value = str(state[spec.macro]).strip()
            validate_value(value, spec.kind, spec.label)
            current = self._required_line(ini, spec.macro)
            source_value = (
                numeric_value_for_source(value, current.value) if spec.kind == "number" else value
            )
            ini.set_macro(spec.macro, bool(state[spec.macro + ".enabled"]), source_value)
        for spec in CHOICE_VALUE_SPECS:
            value = str(state[spec.macro]).strip()
            validate_value(value, spec.kind, spec.label)
            current = self._required_line(ini, spec.macro)
            source_value = (
                numeric_value_for_source(value, current.value) if spec.kind == "number" else value
            )
            ini.set_macro(spec.macro, current.enabled, source_value)

        self._write_choice(ini, "regulator", str(state["regulator"]), "Регулятор мощности")
        self._write_choice(
            ini,
            "atmospheric_sensor",
            str(state["atmospheric_sensor"]),
            "Датчик атмосферного давления",
        )
        self._write_choice(
            ini,
            "column_pressure_sensor",
            str(state["column_pressure_sensor"]),
            "Датчик давления в колонне",
        )

        validate_servo_delta(str(state["servoDelta"]))
        servo_values = [part.strip() for part in str(state["servoDelta"]).split(",")]
        ini_text = re.sub(
            r"(^\s*int8_t\s+servoDelta\s*\[11\]\s*=\s*)\{[^}]*\}(\s*;)",
            r"\g<1>{" + ", ".join(servo_values) + r"}\g<2>",
            ini.render(),
            count=1,
            flags=re.MULTILINE,
        )

        ssid = str(state.get("wifi_ssid", ""))
        password = str(state.get("wifi_password", ""))
        self._validate_wifi(ssid, password)
        self._set_override_string(override, "SAMOVAR_WIFI_SSID", ssid)
        self._set_override_string(override, "SAMOVAR_WIFI_PASSWORD", password)

        atomic_write(self.ini_path, ini_text)
        atomic_write(self.override_path, override.render())

    @staticmethod
    def _required_line(document: HeaderDocument, macro: str) -> MacroLine:
        line = document.find(macro)
        if line is None:
            raise ConfigError("В Samovar_ini.h не найдена настройка {}".format(macro))
        return line

    @staticmethod
    def _board_line(document: HeaderDocument, value: str) -> MacroLine:
        pattern = re.compile(r"^(?P<indent>\s*)(?P<disabled>//\s*)?#define\s+BOARD\s+" + value + r"\b")
        for index, text in enumerate(document.lines):
            match = pattern.match(text)
            if match:
                return MacroLine(index, match.group("disabled") is None, value, "", match.group("indent"))
        raise ConfigError("В Samovar_ini.h не найден вариант платы {}".format(value))

    @staticmethod
    def _set_board_line(document: HeaderDocument, line: MacroLine, enabled: bool) -> None:
        original = document.lines[line.index]
        marker = original.index("#define")
        suffix = original[marker:]
        document.lines[line.index] = line.indent + ("" if enabled else "//") + suffix

    @staticmethod
    def _read_choice(document: HeaderDocument, options: Dict[str, Tuple[str, ...]]) -> str:
        enabled = {
            macro
            for macros in options.values()
            for macro in macros
            if SamovarConfig._required_line(document, macro).enabled
        }
        for label, macros in reversed(tuple(options.items())):
            if macros and set(macros).issubset(enabled):
                return label
        return next(iter(options))

    @staticmethod
    def _write_choice(document: HeaderDocument, state_key: str, selected: str, group: str) -> None:
        options = CHOICE_OPTIONS[group]
        if selected not in options:
            raise ConfigError("Неизвестное значение {}: {}".format(state_key, selected))
        all_macros = tuple(dict.fromkeys(macro for macros in options.values() for macro in macros))
        document.set_choice(all_macros, options[selected])

    @staticmethod
    def _read_override_string(document: HeaderDocument, macro: str) -> str:
        line = document.find(macro)
        if line is None or not line.enabled:
            return ""
        return cpp_string_decode(line.value)

    @staticmethod
    def _set_override_string(document: HeaderDocument, macro: str, value: str) -> None:
        line = document.find(macro)
        if line is None:
            document.insert_before_final_endif(["#define {} {}".format(macro, cpp_string_encode(value))])
        else:
            document.set_macro(macro, True, cpp_string_encode(value))

    @staticmethod
    def _validate_wifi(ssid: str, password: str) -> None:
        if len(ssid.encode("utf-8")) > 32:
            raise ConfigError("SSID Wi-Fi не должен превышать 32 байта")
        password_length = len(password.encode("utf-8"))
        if password_length not in (0,) and not 8 <= password_length <= 64:
            raise ConfigError("Пароль Wi-Fi должен содержать от 8 до 64 байт или быть пустым")
        if not ssid and password:
            raise ConfigError("Нельзя указать пароль Wi-Fi без SSID")


def validate_servo_delta(value: str) -> None:
    values = [part.strip() for part in value.split(",")]
    if len(values) != 11 or any(not re.fullmatch(r"[+-]?\d+", item) for item in values):
        raise ConfigError("Для servoDelta требуется ровно 11 целых чисел через запятую")


def is_unc_path(path: Path) -> bool:
    return str(path).startswith(("\\\\", "//"))


def list_serial_ports(pio_executable: str) -> List[str]:
    result = subprocess.run(
        [pio_executable, "device", "list", "--serial", "--json-output"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ConfigError("Не удалось получить список портов: {}".format(detail))
    try:
        devices = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ConfigError("PlatformIO вернул некорректный список портов") from error
    if not isinstance(devices, list):
        raise ConfigError("PlatformIO вернул некорректный список портов")
    ports = []
    for device in devices:
        port = device.get("port") if isinstance(device, dict) else None
        if isinstance(port, str) and port.strip() and port not in ports:
            ports.append(port)
    return ports


SERIAL_PORT_RE = re.compile(r"^(\\\\\.\\)?COM\d+$|^/dev/", re.IGNORECASE)
NETWORK_PORT_SUFFIX = " — "
ADDRESS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$")


def list_network_devices(pio_executable: str) -> List[str]:
    """Ищет Samovar в локальной сети через mDNS (объявление ArduinoOTA `_arduino._tcp`).

    Возвращает строки вида «192.168.1.37 — samovar (Wi-Fi)»: перед « — » стоит адрес,
    который и уходит в PlatformIO как --upload-port.
    """
    result = subprocess.run(
        [pio_executable, "device", "list", "--mdns", "--json-output"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        lines = [line for line in (result.stderr or result.stdout).splitlines() if re.search(r"[A-Za-zА-Яа-я]", line)]
        detail = lines[-1].strip() if lines else "код {}".format(result.returncode)
        raise ConfigError("Не удалось найти устройства в сети: {}".format(detail))
    try:
        services = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ConfigError("PlatformIO вернул некорректный список сетевых устройств") from error
    if not isinstance(services, list):
        raise ConfigError("PlatformIO вернул некорректный список сетевых устройств")
    devices = []
    for service in services:
        if not isinstance(service, dict) or "_arduino._tcp" not in str(service.get("type", "")):
            continue
        addresses = str(service.get("ip") or "")
        name = str(service.get("name") or "").split(".")[0]
        for address in addresses.split(","):
            address = address.strip()
            if not address:
                continue
            try:
                ipaddress.IPv4Address(address)
            except ValueError:
                continue
            label = network_port_label(address, name)
            if label not in devices:
                devices.append(label)
    return devices


def network_port_label(address: str, name: str = "") -> str:
    return "{}{}{} (Wi-Fi)".format(address, NETWORK_PORT_SUFFIX, name or "samovar").rstrip()


def port_value(port: str) -> str:
    """Из строки списка портов вычленяет сам порт или адрес (часть до « — »)."""
    return port.split(NETWORK_PORT_SUFFIX, 1)[0].strip()


def is_network_port(port: str) -> bool:
    port = port_value(port)
    return bool(port) and not SERIAL_PORT_RE.match(port)


def _required_port(port: str) -> str:
    port = port_value(port)
    if not port:
        raise ConfigError("Выберите порт или устройство в сети")
    return port


def _required_serial_port(port: str, what: str) -> str:
    port = _required_port(port)
    if is_network_port(port):
        raise ConfigError(
            "{} возможно только по USB: выберите COM-порт вместо устройства в сети".format(what)
        )
    return port


def pio_command(pio_executable: str, board: str, action: str, port: str) -> List[str]:
    if board not in BOARD_OPTIONS:
        raise ConfigError("Неизвестная плата: {}".format(board))
    targets = {
        "upload": "upload",
        "uploadfs": "uploadfs",
        "erase": "erase",
    }
    if action not in targets:
        raise ConfigError("Неизвестная команда: {}".format(action))
    if action == "erase":
        port = _required_serial_port(port, "Полная очистка флеша")
    elif is_network_port(port):
        port = resolve_device_address(port_value(port))
    else:
        port = _required_port(port)
    environment = BOARD_OPTIONS[board][1]
    return [
        pio_executable, "run", "-e", environment, "-t", targets[action], "--upload-port", port,
    ]


def esptool_reboot_command(pio_executable: str, port: str) -> List[str]:
    return [
        pio_executable, "pkg", "exec", "-p", "tool-esptoolpy", "--",
        "esptool.py", "--port", _required_serial_port(port, "Перезагрузка ESP"), "run",
    ]


def serial_monitor_command(python_executable: str, script: Path, port: str) -> List[str]:
    return [
        python_executable, str(script), "--serial-monitor",
        _required_serial_port(port, "Монитор порта"),
    ]


def pio_python_executable(pio_executable: str) -> str:
    result = subprocess.run(
        [pio_executable, "system", "info", "--json-output"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        raise ConfigError("Не удалось определить Python PlatformIO: {}".format(
            (result.stderr or result.stdout).strip()
        ))
    try:
        value = json.loads(result.stdout)["python_exe"]["value"]
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise ConfigError("PlatformIO не сообщил путь к Python") from error
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("PlatformIO не сообщил путь к Python")
    return value


def extract_samovar_ip(text: str) -> Optional[str]:
    matches = re.findall(r"(?m)^SAMOVAR:IP=([^\r\n]+)$", text)
    for value in reversed(matches):
        try:
            address = ipaddress.ip_address(value.strip())
        except ValueError:
            continue
        if address.version == 4 and not address.is_unspecified:
            return str(address)
    return None


def extract_samovar_config(line: str) -> Optional[str]:
    payload = line.strip()
    if not payload.startswith("{") or not re.search(
        r'"type"\s*:\s*"samovar_firmware_config"', payload
    ):
        return None
    return payload


def _device_config_fields_by_name() -> Dict[str, DeviceConfigField]:
    fields = {field.name: field for field in DEVICE_CONFIG_FIELDS}
    if len(fields) != len(DEVICE_CONFIG_FIELDS):
        raise ConfigError("В схеме настроек устройства повторяется имя поля")
    return fields


def _device_config_error_keys(label: str, keys) -> ConfigError:
    return ConfigError("{}: {}".format(label, ", ".join(sorted(keys))))


def parse_device_config(payload: str) -> DeviceConfig:
    try:
        response = json.loads(payload)
    except json.JSONDecodeError as error:
        raise ConfigError("Устройство вернуло некорректный JSON настроек") from error
    if not isinstance(response, dict):
        raise ConfigError("Ответ настроек должен быть JSON-объектом")

    expected_response_keys = {"type", "schema", "firmwareVersion", "settings"}
    actual_response_keys = set(response)
    if actual_response_keys != expected_response_keys:
        if actual_response_keys - expected_response_keys:
            raise _device_config_error_keys(
                "Неизвестные ключи ответа настроек", actual_response_keys - expected_response_keys
            )
        raise _device_config_error_keys(
            "В ответе настроек отсутствуют ключи", expected_response_keys - actual_response_keys
        )
    if response["type"] != "samovar_firmware_config":
        raise ConfigError("Неизвестный тип ответа настроек")
    schema = response["schema"]
    if type(schema) is not int or schema < 1:
        raise ConfigError("Некорректная версия схемы настроек")
    if schema > DEVICE_CONFIG_SCHEMA_VERSION:
        raise ConfigError("Версия схемы настроек устройства новее конфигуратора")
    firmware_version = response["firmwareVersion"]
    if not isinstance(firmware_version, str) or not firmware_version.strip():
        raise ConfigError("Устройство не сообщило версию прошивки")
    settings = response["settings"]
    if not isinstance(settings, dict):
        raise ConfigError("Поле settings должно быть JSON-объектом")

    fields = _device_config_fields_by_name()
    required = {name for name, field in fields.items() if field.since <= schema}
    actual = set(settings)
    if actual - required:
        raise _device_config_error_keys(
            "Неизвестные или несовместимые ключи настроек", actual - required
        )
    if required - actual:
        raise _device_config_error_keys("В ответе настроек отсутствуют обязательные поля", required - actual)

    value_specs = {spec.macro: spec for spec in VALUE_SPECS}
    optional_specs = {spec.macro: spec for spec in OPTIONAL_SPECS}
    choice_value_specs = {spec.macro: spec for spec in CHOICE_VALUE_SPECS}
    mapped = {}
    for name in required:
        value = settings[name]
        kind = fields[name].kind
        if kind == "bool":
            if type(value) is not bool:
                raise ConfigError("Поле {} должно быть логическим".format(name))
            mapped[name] = value
        elif kind == "board":
            if not isinstance(value, str):
                raise ConfigError("Поле {} должно быть строкой".format(name))
            if value not in FIRMWARE_BOARD_TOKENS:
                raise ConfigError("Неизвестная плата устройства: {}".format(value))
            mapped[name] = FIRMWARE_BOARD_TOKENS[value]
        elif kind == "choice":
            if not isinstance(value, str):
                raise ConfigError("Поле {} должно быть строкой".format(name))
            choices = FIRMWARE_CHOICE_TOKENS[name]
            if value not in choices:
                raise ConfigError("Неизвестное значение {}: {}".format(name, value))
            mapped[name] = choices[value]
        elif kind == "servo":
            if not isinstance(value, list) or len(value) != 11 or any(type(item) is not int for item in value):
                raise ConfigError("Поле servoDelta должно быть массивом из 11 целых чисел")
            mapped[name] = ", ".join(str(item) for item in value)
            validate_servo_delta(mapped[name])
        elif kind == "value":
            spec = value_specs[name]
            if value is None and name == "BLYNK_SAMOVAR_TOOL":
                mapped[name] = ""
                continue
            if spec.kind == "text":
                if not isinstance(value, str):
                    raise ConfigError("Поле {} должно быть строкой".format(name))
                mapped[name] = value
            else:
                if type(value) not in (int, float):
                    raise ConfigError("Поле {} должно быть числом".format(name))
                mapped[name] = str(value)
            validate_value(mapped[name], spec.kind, spec.label)
        elif kind == "optional":
            spec = optional_specs[name]
            if value is None:
                mapped[name + ".enabled"] = False
            else:
                if not isinstance(value, str):
                    raise ConfigError("Поле {} должно быть строкой или null".format(name))
                validate_value(value, spec.kind, spec.label)
                mapped[name] = value
                mapped[name + ".enabled"] = True
        elif kind == "choice_value":
            if value is None:
                continue
            if not isinstance(value, str):
                raise ConfigError("Поле {} должно быть строкой или null".format(name))
            spec = choice_value_specs[name]
            validate_value(value, spec.kind, spec.label)
            mapped[name] = value
        elif kind == "wifi":
            if value is None:
                mapped[name] = ""
            elif isinstance(value, str):
                mapped[name] = value
            else:
                raise ConfigError("Поле {} должно быть строкой или null".format(name))

    SamovarConfig._validate_wifi(mapped["wifi_ssid"], mapped["wifi_password"])
    return DeviceConfig(firmware_version, mapped)


def fetch_device_config(address: str) -> str:
    address = _required_address(address)
    request = urllib.request.Request("http://{}/firmware-config".format(address), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.read().decode("utf-8")
    except UnicodeDecodeError as error:
        raise ConfigError("Устройство вернуло настройки не в UTF-8") from error
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace").strip()
        raise ConfigError("Samovar ответил с ошибкой {}: {}".format(error.code, detail)) from error
    except urllib.error.URLError as error:
        raise ConfigError("Не удалось подключиться к Samovar: {}".format(error.reason)) from error


def keep_control_lines_after_close(fd: int) -> None:
    """Снимает флаг HUPCL (POSIX): ядро не будет опускать DTR/RTS при закрытии порта.

    Линии остаются выставленными и между сессиями монитора, поэтому следующее открытие
    ничего не переключает - а сбросить плату может только переключение.
    """
    import termios

    try:
        attributes = termios.tcgetattr(fd)
        attributes[2] &= ~termios.HUPCL
        termios.tcsetattr(fd, termios.TCSANOW, attributes)
    except termios.error:
        pass  # у виртуальных портов (pty без tty-настроек и т.п.) снимать нечего


def open_serial_without_reset(serial_module, port: str):
    """Открывает порт так, чтобы схема автосброса ESP32 не увидела «сбросного» сочетания линий.

    Плата сбрасывается, когда DTR снят, а RTS выставлен (транзистор тянет EN к земле);
    режим загрузчика - когда наоборот (IO0 к земле, безвредно для работающей платы).
    Сбрасывает только ПЕРЕХОД через «DTR снят, RTS выставлен»; драйверы меняют линии
    по одной, в порядке, который из программы не виден. Поэтому задача - свести число
    переключений к минимуму.

    - macOS/Linux: ядро при open() выставляет обе линии; мы их не трогаем и снимаем
      флаг HUPCL, чтобы ядро не опускало их при закрытии. Между сессиями линии остаются
      выставленными, и следующее открытие ничего не переключает (нет перехода - нет
      сброса). Единственный переход - первое открытие после прошивки или переподключения
      USB, когда линии опущены кем-то другим (esptool).
    - Windows: драйвер всегда опускает линии при закрытии (DTR первым - это и есть
      сброс), поэтому здесь наоборот: до открытия просим «DTR выставлен, RTS снят» -
      из любого стартового состояния меняется ровно одна линия через безопасную
      сторону; после открытия снимаем DTR. Закрытие из «обе сняты» ничего не переключает.
    """
    connection = serial_module.serial_for_url(
        _required_serial_port(port, "Монитор порта"), 115200, do_not_open=True
    )
    if isinstance(connection, serial_module.Serial):
        connection.exclusive = True
    if os.name == "nt":
        connection.dtr = True
        connection.rts = False
        connection.open()
        connection.dtr = False
    else:
        connection.dtr = True
        connection.rts = True
        connection.open()
        keep_control_lines_after_close(connection.fd)
    return connection


BOOT_BANNER = b"rst:0x"
BOOT_BANNER_WINDOW_S = 3.0


def forward_serial_commands(connection, input_stream) -> None:
    for command in input_stream:
        try:
            connection.write(command.encode("utf-8"))
        except OSError:
            return


def run_serial_monitor(port: str) -> int:
    try:
        import serial
    except ImportError as error:
        raise ConfigError("В Python PlatformIO не найден модуль работы с последовательным портом") from error

    try:
        connection = open_serial_without_reset(serial, port)
    except (OSError, serial.SerialException) as error:
        raise ConfigError("Не удалось открыть последовательный порт {}: {}".format(port, error)) from error
    connection.timeout = 0.2
    threading.Thread(
        target=forward_serial_commands, args=(connection, sys.stdin), daemon=True
    ).start()
    try:
        print("--- Последовательный порт {} | 115200 8-N-1".format(port), flush=True)
        opened_at = time.monotonic()
        while True:
            data = connection.read(256)
            if data:
                print(data.decode("utf-8", errors="replace"), end="", flush=True)
                if BOOT_BANNER in data and time.monotonic() - opened_at < BOOT_BANNER_WINDOW_S:
                    print(
                        "\n!!! ESP32 перезагрузилась при открытии порта. Сообщите разработчику: "
                        "ОС и чип USB-UART платы (CP2102, CH340, ...).",
                        flush=True,
                    )
    except KeyboardInterrupt:
        pass
    except (OSError, serial.SerialException) as error:
        raise ConfigError("Не удалось открыть последовательный порт {}: {}".format(port, error)) from error
    finally:
        if connection.is_open:
            connection.close()
    return 0


def _remote_path(name: str) -> str:
    name = name.strip().replace("\\", "/")
    if not name.startswith("/"):
        name = "/" + name
    if name == "/" or ".." in name or "/" in name[1:] or len(name) >= 32:
        raise ConfigError("Недопустимое имя файла: {}".format(name))
    return name


def decode_remote_text(path: str, payload: bytes) -> str:
    if path.lower().endswith(".gz"):
        try:
            payload = gzip.decompress(payload)
        except OSError as error:
            raise ConfigError("Файл {} повреждён или не является gzip".format(path)) from error
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ConfigError("Файл {} не является текстом UTF-8".format(path)) from error


def encode_remote_text(path: str, text: str) -> bytes:
    payload = text.encode("utf-8")
    return gzip.compress(payload, mtime=0) if path.lower().endswith(".gz") else payload


def prepare_remote_upload(name: str, payload: bytes, remote_names: List[str]) -> Tuple[str, bytes]:
    target = _remote_path(Path(name).name)
    compressed_target = target + ".gz"
    if not target.lower().endswith(".gz") and compressed_target in remote_names:
        return compressed_target, gzip.compress(payload, mtime=0)
    return target, payload


_STRING_RULES = [
    ("string", r'"(?:\\.|[^"\\\n])*"?'),
    ("string", r"'(?:\\.|[^'\\\n])*'?"),
]
_JS_KEYWORDS = (
    "async|await|break|case|catch|class|const|continue|default|delete|do|else|export|extends|"
    "false|finally|for|function|if|import|in|instanceof|let|new|null|of|return|switch|this|throw|"
    "true|try|typeof|undefined|var|void|while|with|yield"
)
_LUA_KEYWORDS = (
    "and|break|do|else|elseif|end|false|for|function|goto|if|in|local|nil|not|or|repeat|return|"
    "then|true|until|while"
)
_LUA_BUILTINS = (
    "print|pairs|ipairs|tostring|tonumber|type|require|pcall|error|select|next|unpack|"
    "string|table|math|os|io|coroutine"
)
_NUMBER = r"\b(?:0[xX][0-9a-fA-F]+|\d+(?:\.\d*)?(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)\b"

SYNTAX_RULES = {
    "js": [
        ("comment", r"//[^\n]*|/\*[\s\S]*?(?:\*/|\Z)"),
        ("string", r"`(?:\\.|[^`\\])*`?"),
    ] + _STRING_RULES + [
        ("keyword", r"\b(?:" + _JS_KEYWORDS + r")\b"),
        ("number", _NUMBER),
        ("property", r"(?<=\.)[A-Za-z_$][\w$]*(?=\s*\()"),
    ],
    "lua": [
        ("comment", "|".join(r"--\[{0}\[[\s\S]*?(?:\]{0}\]|\Z)".format(level) for level in ("", "=", "==")) + r"|--[^\n]*"),
        ("string", "|".join(r"\[{0}\[[\s\S]*?(?:\]{0}\]|\Z)".format(level) for level in ("", "=", "=="))),
    ] + _STRING_RULES + [
        ("keyword", r"\b(?:" + _LUA_KEYWORDS + r")\b"),
        ("property", r"\b(?:" + _LUA_BUILTINS + r")\b"),
        ("number", _NUMBER),
    ],
    "css": [
        ("comment", r"/\*[\s\S]*?(?:\*/|\Z)"),
    ] + _STRING_RULES + [
        ("property", r"(?<![\w-])[-A-Za-z]+(?=\s*:[^{};]*[;}])"),
        ("number", r"(?<![\w.])[-+]?\d+(?:\.\d+)?(?:px|em|rem|%|s|ms|vh|vw|pt|deg)?\b|#[0-9a-fA-F]{3,8}\b"),
        ("keyword", r"@[A-Za-z-]+"),
    ],
    "json": [
        ("property", r'"(?:\\.|[^"\\\n])*"(?=\s*:)'),
        ("string", r'"(?:\\.|[^"\\\n])*"?'),
        ("keyword", r"\b(?:true|false|null)\b"),
        ("number", r"-?" + _NUMBER),
    ],
    "html": [
        ("comment", r"<!--[\s\S]*?(?:-->|\Z)"),
        ("tag", r"<!(?:DOCTYPE|doctype)[^>]*>"),
    ],
}
_HTML_EMBEDDED = re.compile(r"<(script|style)\b[^>]*>([\s\S]*?)</\1\s*>", re.IGNORECASE)
_HTML_TAG = re.compile(r"</?[A-Za-z][\w:-]*(?:\s+[^\s=>/]+(?:\s*=\s*(?:\"[^\"]*\"?|'[^']*'?|[^\s>]+))?)*\s*/?>?")
_HTML_ATTRIBUTE = re.compile(r"([^\s=>/\"']+)(\s*=\s*)?(\"[^\"]*\"?|'[^']*'?|[^\s>]+)?")


def syntax_language(name: str) -> Optional[str]:
    logical_name = name[:-3] if name.lower().endswith(".gz") else name
    return {
        ".htm": "html", ".html": "html", ".js": "js", ".css": "css", ".lua": "lua", ".json": "json",
    }.get(Path(logical_name).suffix.lower())


def _scan(text: str, rules, offset: int = 0) -> List[Tuple[str, int, int]]:
    """Один проход по тексту: на каждой позиции побеждает первое подошедшее правило.

    Поэтому ключевое слово внутри строки или комментария не подсвечивается: правила
    комментариев и строк стоят раньше и «съедают» текст целиком.
    """
    if not rules:
        return []
    groups = [tag for tag, _ in rules]
    combined = re.compile("|".join("(?P<r{}>{})".format(index, pattern) for index, (_, pattern) in enumerate(rules)))
    spans = []
    for match in combined.finditer(text):
        if match.end() == match.start():
            continue
        spans.append((groups[int(match.lastgroup[1:])], offset + match.start(), offset + match.end()))
    return spans


def _html_spans(text: str) -> List[Tuple[str, int, int]]:
    spans = []
    position = 0

    def scan_markup(chunk: str, offset: int) -> None:
        masked = []
        for tag, start, end in _scan(chunk, SYNTAX_RULES["html"], offset):
            spans.append((tag, start, end))
            masked.append((start - offset, end - offset))
        cursor = 0
        for match in _HTML_TAG.finditer(chunk):
            if any(start <= match.start() < end for start, end in masked):
                continue
            body = match.group(0)
            name_end = re.match(r"</?[A-Za-z][\w:-]*", body).end()
            spans.append(("tag", offset + match.start(), offset + match.start() + name_end))
            for attribute in _HTML_ATTRIBUTE.finditer(body, name_end):
                if attribute.group(1) in ("/", ">", "/>"):
                    continue
                spans.append(("property", offset + match.start() + attribute.start(1), offset + match.start() + attribute.end(1)))
                if attribute.group(3):
                    spans.append(("string", offset + match.start() + attribute.start(3), offset + match.start() + attribute.end(3)))
            if body.endswith(">"):
                spans.append(("tag", offset + match.end() - 1, offset + match.end()))

    for embedded in _HTML_EMBEDDED.finditer(text):
        scan_markup(text[position:embedded.start(2)], position)
        language = "js" if embedded.group(1).lower() == "script" else "css"
        spans.extend(_scan(embedded.group(2), SYNTAX_RULES[language], embedded.start(2)))
        position = embedded.end(2)
    scan_markup(text[position:], position)
    spans.sort(key=lambda span: span[1])
    return spans


def syntax_spans(name: str, text: str) -> List[Tuple[str, int, int]]:
    language = syntax_language(name)
    if language is None:
        return []
    if language == "html":
        return _html_spans(text)
    return _scan(text, SYNTAX_RULES[language])


def code_without_literals(name: str, text: str) -> str:
    """Текст той же длины, где комментарии и строки заменены пробелами (переводы строк сохранены)."""
    characters = list(text)
    for tag, start, end in syntax_spans(name, text):
        if tag in ("comment", "string", "property") and (tag != "property" or syntax_language(name) == "json"):
            for index in range(start, end):
                if characters[index] != "\n":
                    characters[index] = " "
    return "".join(characters)


_BRACKET_PAIRS = {")": "(", "]": "[", "}": "{"}


def _line_of(text: str, position: int) -> int:
    return text.count("\n", 0, position) + 1


def check_bracket_balance(code: str) -> Optional[Tuple[int, str]]:
    stack = []
    for position, character in enumerate(code):
        if character in "([{":
            stack.append((character, position))
        elif character in _BRACKET_PAIRS:
            if not stack or stack[-1][0] != _BRACKET_PAIRS[character]:
                return _line_of(code, position), "лишняя закрывающая скобка «{}»".format(character)
            stack.pop()
    if stack:
        character, position = stack[-1]
        return _line_of(code, position), "не закрыта скобка «{}»".format(character)
    return None


_LUA_OPENERS = {"function", "if", "do", "repeat"}


def check_lua_blocks(code: str) -> Optional[Tuple[int, str]]:
    stack = []
    for match in re.finditer(r"\b(function|if|do|repeat|end|until)\b", code):
        word = match.group(1)
        line = _line_of(code, match.start())
        if word in _LUA_OPENERS:
            stack.append((word, line))
        elif word == "until":
            if not stack or stack[-1][0] != "repeat":
                return line, "«until» без «repeat»"
            stack.pop()
        else:
            if not stack or stack[-1][0] == "repeat":
                return line, "лишний «end»"
            stack.pop()
    if stack:
        word, line = stack[-1]
        return line, "нет «end» для «{}» (строка {})".format(word, line)
    return None


def check_syntax(name: str, text: str) -> Optional[Tuple[int, str]]:
    """Быстрая проверка без внешних инструментов: (номер строки, сообщение) или None, если всё в порядке."""
    language = syntax_language(name)
    if language is None:
        return None
    if language == "json":
        try:
            json.loads(text)
        except json.JSONDecodeError as error:
            return error.lineno, error.msg
        return None
    code = code_without_literals(name, text)
    if language == "html":
        for match in _HTML_EMBEDDED.finditer(text):
            inner_name = "x.js" if match.group(1).lower() == "script" else "x.css"
            problem = check_syntax(inner_name, match.group(2))
            if problem:
                return problem[0] + _line_of(text, match.start(2)) - 1, problem[1]
        unclosed = re.search(r"<!--(?![\s\S]*?-->)", text)
        if unclosed:
            return _line_of(text, unclosed.start()), "не закрыт комментарий <!--"
        return None
    for tag, start, end in syntax_spans(name, text):
        if tag == "comment" and text[start:end].startswith("/*") and not text[start:end].endswith("*/"):
            return _line_of(text, start), "не закрыт комментарий /*"
        if tag == "string" and (end - start < 2 or text[end - 1] != text[start]) and text[start] in "\"'`":
            return _line_of(text, start), "не закрыта строка"
    problem = check_bracket_balance(code)
    if problem:
        return problem
    if language == "lua":
        return check_lua_blocks(code)
    return None


def matching_bracket(code: str, position: int) -> Optional[int]:
    """Позиция парной скобки для скобки в position (по тексту без строк и комментариев)."""
    if position < 0 or position >= len(code):
        return None
    character = code[position]
    if character in "([{":
        opener, closer, step = character, {"(": ")", "[": "]", "{": "}"}[character], 1
    elif character in _BRACKET_PAIRS:
        opener, closer, step = character, _BRACKET_PAIRS[character], -1
    else:
        return None
    depth = 0
    index = position
    while 0 <= index < len(code):
        if code[index] == opener:
            depth += 1
        elif code[index] == closer:
            depth -= 1
            if depth == 0:
                return index
        index += step
    return None


def web_editor_url(address: str, path: Optional[str] = None) -> str:
    url = "http://{}/edit".format(address)
    if path:
        url += "?file=" + urllib.parse.quote(path)
    return url


def web_editor_supports(path: Optional[str]) -> bool:
    """Веб-редактор прошивки (/edit) показывает файл как есть и не распаковывает gzip."""
    return bool(path) and not path.lower().endswith(".gz")


def is_text_remote_file(path: str) -> bool:
    logical_path = path[:-3] if path.lower().endswith(".gz") else path
    return Path(logical_path).suffix.lower() in (".htm", ".html", ".js", ".css", ".lua", ".txt", ".json", ".csv")


class SamovarFileClient:
    def __init__(self, address: str):
        self.url = "http://{}".format(address)

    def _request(self, request: urllib.request.Request) -> bytes:
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace").strip()
            raise ConfigError("Samovar ответил с ошибкой {}: {}".format(error.code, detail)) from error
        except urllib.error.URLError as error:
            raise ConfigError("Не удалось подключиться к Samovar: {}".format(error.reason)) from error

    def list_files(self) -> List[Dict[str, object]]:
        payload = self._request(urllib.request.Request(self.url + "/edit?list=/"))
        try:
            files = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ConfigError("Samovar вернул некорректный список файлов") from error
        if not isinstance(files, list):
            raise ConfigError("Samovar вернул некорректный список файлов")
        return files

    def read_file(self, path: str) -> bytes:
        query = urllib.parse.urlencode({"edit": _remote_path(path)})
        return self._request(urllib.request.Request(self.url + "/edit?" + query))

    def upload_file(self, path: str, payload: bytes) -> None:
        path = _remote_path(path)
        boundary = "----SamovarConfiguratorBoundary"
        body = (
            "--{0}\r\nContent-Disposition: form-data; name=\"data\"; filename=\"{1}\"\r\n"
            "Content-Type: application/octet-stream\r\n\r\n".format(boundary, path)
        ).encode("utf-8") + payload + ("\r\n--{}--\r\n".format(boundary)).encode("ascii")
        request = urllib.request.Request(self.url + "/edit", data=body, method="POST")
        request.add_header("Content-Type", "multipart/form-data; boundary=" + boundary)
        self._request(request)

    def create_file(self, path: str) -> None:
        data = urllib.parse.urlencode({"path": _remote_path(path)}).encode("utf-8")
        self._request(urllib.request.Request(self.url + "/edit", data=data, method="PUT"))

    def delete_file(self, path: str) -> None:
        data = urllib.parse.urlencode({"path": _remote_path(path)}).encode("utf-8")
        self._request(urllib.request.Request(self.url + "/edit", data=data, method="DELETE"))


GEOMETRY_RE = re.compile(r"^\d+x\d+(?:[+-]\d+[+-]\d+)?$")
USER_PREFS_PATH = Path.home() / ".samovar_configurator.json"

ACTION_LABELS = {
    "upload": "Прошивка",
    "uploadfs": "Загрузка LittleFS",
    "erase": "Полная очистка флеша",
    "monitor": "Монитор порта",
    "reboot": "Перезагрузка ESP",
}

OTA_FAILURE_HINT = (
    "Подсказка: обновление по Wi-Fi требует, чтобы компьютер и Samovar были в одной сети, "
    "прошивка на устройстве была собрана с включённым «Разрешить обновление по Wi-Fi», "
    "а брандмауэр разрешал python.exe входящие подключения: устройство само подключается "
    "к компьютеру для передачи образа.\n"
)

PACKAGE_INSTALL_HINT = (
    "Скачивание и распаковка пакета: проценты появятся по мере загрузки. Тулчейн для ESP32 "
    "весит сотни мегабайт, при первом запуске это занимает до 10–15 минут (скорость сети и "
    "антивирус). Окно не зависло.\n"
)

ESPTOOL_TRACEBACK_RE = re.compile(r'File "(?P<dir>[^"]*[\\/]tool-esptoolpy[^"\\/]*)[\\/]esptool(?:\.py|[\\/])')
IMPORT_ERROR_RE = re.compile(r"^(ImportError|ModuleNotFoundError): ")


def broken_esptool_package(lines: List[str]) -> Optional[str]:
    """Папка пакета tool-esptoolpy, если в выводе есть его трассировка с ошибкой импорта.

    Зависимости esptool лежат в подпапке _contrib пакета; если их не доставил pip или вычистил
    антивирус, esptool.py падает на импорте. Пакет проще удалить: PlatformIO поставит его заново.
    """
    package = None
    for line in lines:
        match = ESPTOOL_TRACEBACK_RE.search(line)
        if match:
            package = match.group("dir")
        elif package and IMPORT_ERROR_RE.match(line.strip()):
            return package
    return None


def remove_broken_esptool(package_dir: str) -> None:
    path = Path(package_dir)
    if not path.name.startswith("tool-esptoolpy") or not (path / "esptool.py").is_file():
        raise ConfigError("папка {} не похожа на пакет esptool".format(path))
    shutil.rmtree(path)


def _required_address(address: str) -> str:
    address = address.strip()
    if not address:
        raise ConfigError("Укажите IP-адрес или имя устройства в сети")
    if not ADDRESS_RE.fullmatch(address):
        raise ConfigError("Некорректный адрес устройства: {}".format(address))
    return address


def resolve_device_address(address: str) -> str:
    """Возвращает IPv4-адрес устройства: имя (в том числе samovar.local) разрешается на компьютере.

    PlatformIO переключает загрузку на espota (обновление по сети) только когда
    --upload-port выглядит как IPv4-адрес или имя *.local; переменная окружения
    PLATFORMIO_UPLOAD_PROTOCOL при проверке была проигнорирована. Поэтому в команду
    всегда передаётся уже разрешённый IPv4, а pio сам выбирает espota вместо esptool.
    """
    address = _required_address(address)
    try:
        return str(ipaddress.IPv4Address(address))
    except ValueError:
        pass
    try:
        candidates = socket.getaddrinfo(address, None, socket.AF_INET, socket.SOCK_STREAM)
    except OSError as error:
        raise ConfigError("Не удалось определить IP-адрес устройства {}: {}".format(address, error)) from error
    for candidate in candidates:
        resolved = candidate[4][0]
        if isinstance(resolved, str) and resolved:
            return resolved
    raise ConfigError("Не удалось определить IP-адрес устройства {}".format(address))


def terminate_process_tree(process) -> None:
    """Останавливает pio вместе с дочерними процессами (scons, esptool, espota).

    Простой terminate() убивает только pio: дети продолжают работать, держат
    stdout-канал, и окно остаётся «занятым» до их самостоятельного завершения.
    """
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    else:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except OSError:
            process.terminate()


def process_start_options() -> Dict[str, object]:
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    return {"start_new_session": True}


def log_line_tag(line: str) -> Optional[str]:
    if line.startswith("> "):
        return "command"
    lowered = line.lower()
    if re.search(r"\berror\b|\[failed\]|\bfailed\b|\bfatal\b|ошибк|traceback", lowered):
        return "error"
    if re.search(r"\[success\]|\bsuccess\b|успешно|перезагружен|сохранены", lowered):
        return "ok"
    if re.search(r"\bwarning\b|предупрежд", lowered):
        return "warning"
    return None


def load_user_prefs(path: Path = USER_PREFS_PATH) -> Dict[str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    prefs = {key: value for key, value in data.items() if isinstance(value, str)}
    if not GEOMETRY_RE.fullmatch(prefs.get("geometry", "")):
        prefs.pop("geometry", None)
    return prefs


def save_user_prefs(data: Dict[str, str], path: Path = USER_PREFS_PATH) -> None:
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


# Сочетания клавиш, не зависящие от раскладки: в Windows Tk сообщает виртуальный код
# клавиши (латинская буква независимо от раскладки), в X11 и macOS - keysym текущей
# раскладки, поэтому кириллические keysym перечислены отдельно.
SHORTCUT_KEYCODES = {65: "select_all", 67: "copy", 86: "paste", 88: "cut", 90: "undo", 89: "redo", 83: "save"}
SHORTCUT_KEYSYMS = {
    "a": "select_all", "cyrillic_ef": "select_all",
    "c": "copy", "cyrillic_es": "copy",
    "v": "paste", "cyrillic_em": "paste",
    "x": "cut", "cyrillic_che": "cut",
    "z": "undo", "cyrillic_ya": "undo",
    "y": "redo", "cyrillic_en": "redo",
    "s": "save", "cyrillic_yeru": "save",
}
EDIT_EVENTS = {
    "copy": "<<Copy>>", "paste": "<<Paste>>", "cut": "<<Cut>>",
    "select_all": "<<SelectAll>>", "undo": "<<Undo>>", "redo": "<<Redo>>",
}


def shortcut_action(keysym: str, keycode: int, platform: str = sys.platform, state: int = 0) -> Optional[str]:
    # AltGr в Windows приходит как Control+Alt: это ввод символа (ą, ć, ś…), а не сочетание.
    alt_mask = 0x20000 if platform == "win32" else 0x8
    if state & alt_mask:
        return None
    if platform == "win32" and keycode in SHORTCUT_KEYCODES:
        return SHORTCUT_KEYCODES[keycode]
    return SHORTCUT_KEYSYMS.get(keysym.lower())


class EditMenu:
    """Контекстное меню и сочетания клавиш для полей ввода и текстовых областей.

    kind: "entry" - однострочное поле, "text" - редактируемый текст с отменой,
    "readonly" - только чтение (журнал), где доступны копирование и выделение.
    """

    def __init__(self, widget, kind: str, on_save=None, on_clear=None):
        import tkinter as tk

        self.widget = widget
        self.kind = kind
        self.on_save = on_save
        self.on_clear = on_clear
        self.menu = tk.Menu(widget, tearoff=0)
        self.editable = kind != "readonly"
        if kind == "text":
            self.menu.add_command(label="Отменить", accelerator="Ctrl+Z", command=lambda: self.run("undo"))
            self.menu.add_command(label="Повторить", accelerator="Ctrl+Y", command=lambda: self.run("redo"))
            self.menu.add_separator()
        if self.editable:
            self.menu.add_command(label="Вырезать", accelerator="Ctrl+X", command=lambda: self.run("cut"))
        self.menu.add_command(label="Копировать", accelerator="Ctrl+C", command=lambda: self.run("copy"))
        if self.editable:
            self.menu.add_command(label="Вставить", accelerator="Ctrl+V", command=lambda: self.run("paste"))
        self.menu.add_separator()
        self.menu.add_command(label="Выделить всё", accelerator="Ctrl+A", command=lambda: self.run("select_all"))
        if on_clear is not None:
            self.menu.add_separator()
            self.menu.add_command(label="Очистить", command=on_clear)
        if on_save is not None:
            self.menu.add_separator()
            self.menu.add_command(label="Сохранить", accelerator="Ctrl+S", command=on_save)
        widget.bind("<Button-3>", self.popup, add="+")
        if sys.platform == "darwin":
            widget.bind("<Button-2>", self.popup, add="+")
            widget.bind("<Control-Button-1>", self.popup, add="+")
        widget.bind("<Control-KeyPress>", self.key, add="+")

    def has_selection(self) -> bool:
        try:
            if self.kind == "entry":
                return bool(self.widget.selection_present())
            return bool(self.widget.tag_ranges("sel"))
        except Exception:
            return False

    def has_clipboard(self) -> bool:
        try:
            return bool(self.widget.clipboard_get())
        except Exception:
            return False

    def popup(self, event):
        self.widget.focus_set()
        selected = self.has_selection()
        for label, enabled in (
            ("Вырезать", selected and self.editable),
            ("Копировать", selected),
            ("Вставить", self.editable and self.has_clipboard()),
        ):
            try:
                self.menu.entryconfigure(label, state="normal" if enabled else "disabled")
            except Exception:
                pass
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()
        return "break"

    def key(self, event):
        action = shortcut_action(event.keysym, event.keycode, state=getattr(event, "state", 0))
        if action is None:
            return None
        if action == "save":
            if self.on_save is None:
                return None
            self.on_save()
            return "break"
        return self.run(action)

    def run(self, action: str):
        if action in ("cut", "paste") and not self.editable:
            return "break"
        if action in ("undo", "redo"):
            if self.kind != "text":
                return "break"
            try:
                self.widget.event_generate(EDIT_EVENTS[action])
            except Exception:
                pass
            return "break"
        if action == "select_all" and self.kind == "entry":
            self.widget.selection_range(0, "end")
            self.widget.icursor("end")
            return "break"
        self.widget.event_generate(EDIT_EVENTS[action])
        return "break"


def write_readonly(text_widget, text: str, tag: Optional[str] = None, autoscroll: bool = True) -> None:
    text_widget.configure(state="normal")
    if tag:
        text_widget.insert("end", text, tag)
    else:
        text_widget.insert("end", text)
    text_widget.configure(state="disabled")
    if autoscroll:
        text_widget.see("end")


def clear_readonly(text_widget) -> None:
    text_widget.configure(state="normal")
    text_widget.delete("1.0", "end")
    text_widget.configure(state="disabled")


def configure_log_tags(text_widget) -> None:
    from tkinter import font as tkfont

    # Font(font=..., weight=...) игнорирует параметры при заданном font - нужна копия.
    text_widget.command_font = tkfont.nametofont("TkFixedFont").copy()
    text_widget.command_font.configure(weight="bold")
    text_widget.tag_configure("command", foreground="#1a4fa3", font=text_widget.command_font)
    text_widget.tag_configure("error", foreground="#b3261e")
    text_widget.tag_configure("warning", foreground="#8a5a00")
    text_widget.tag_configure("ok", foreground="#1b7f3b")


class Tooltip:
    DELAY_MS = 450

    def __init__(self, widget, text: str):
        self.widget = widget
        self.text = text
        self.window = None
        self.after_id = None
        widget.bind("<Enter>", self.schedule, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<ButtonPress>", self.hide, add="+")

    def schedule(self, _event=None) -> None:
        self.cancel()
        self.after_id = self.widget.after(self.DELAY_MS, self.show)

    def cancel(self) -> None:
        if self.after_id is not None:
            try:
                self.widget.after_cancel(self.after_id)
            except Exception:
                pass
            self.after_id = None

    def show(self, _event=None) -> None:
        self.after_id = None
        if self.window is not None:
            return
        import tkinter as tk
        from tkinter import ttk

        self.window = tk.Toplevel(self.widget)
        self.window.wm_overrideredirect(True)
        x = self.widget.winfo_rootx() + 16
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.window.wm_geometry("+{}+{}".format(x, y))
        ttk.Label(
            self.window,
            text=self.text,
            justify="left",
            wraplength=520,
            relief="solid",
            borderwidth=1,
            padding=6,
        ).pack()

    def hide(self, _event=None) -> None:
        self.cancel()
        if self.window is not None:
            self.window.destroy()
            self.window = None


class FileEditorWindow:
    def __init__(self, parent, address: str):
        import tkinter as tk
        from tkinter import filedialog, messagebox, simpledialog, ttk

        self.tk = tk
        self.filedialog = filedialog
        self.messagebox = messagebox
        self.simpledialog = simpledialog
        self.address = address
        self.client = SamovarFileClient(address)
        self.files = []
        self.current_path = None
        self.check_result = None
        self.check_id = None

        self.window = tk.Toplevel(parent)
        self.window.title("Файлы Samovar — {}".format(address))
        self.window.geometry("1100x700")
        self.window.minsize(760, 480)
        self.window.transient(parent)
        self.window.protocol("WM_DELETE_WINDOW", self.close)

        toolbar = ttk.Frame(self.window, padding=8)
        toolbar.pack(fill="x")
        for text, command in (
            ("Обновить список", self.refresh),
            ("Создать", self.create),
            ("Удалить", self.delete),
            ("Загрузить с компьютера", self.upload),
            ("Скачать на компьютер", self.download),
        ):
            ttk.Button(toolbar, text=text, command=command).pack(side="left", padx=(0, 8))
        self.save_button = ttk.Button(toolbar, text="Сохранить (Ctrl+S)", command=self.save)
        self.save_button.pack(side="right")
        self.web_button = ttk.Button(
            toolbar, text="Веб-редактор (/edit)", command=self.open_in_web_editor, state="disabled"
        )
        self.web_button.pack(side="right", padx=(0, 8))

        content = ttk.Panedwindow(self.window, orient="horizontal")
        content.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        list_frame = ttk.Frame(content)
        editor_frame = ttk.Frame(content)
        content.add(list_frame, weight=1)
        content.add(editor_frame, weight=4)

        list_scroll = ttk.Scrollbar(list_frame)
        list_scroll.pack(side="right", fill="y")
        self.file_list = tk.Listbox(list_frame, yscrollcommand=list_scroll.set, font="TkFixedFont", exportselection=False)
        self.file_list.pack(fill="both", expand=True)
        list_scroll.configure(command=self.file_list.yview)
        self.file_list.bind("<<ListboxSelect>>", self.open_selected)

        editor_scroll = ttk.Scrollbar(editor_frame)
        editor_scroll.pack(side="right", fill="y")
        editor_xscroll = ttk.Scrollbar(editor_frame, orient="horizontal")
        editor_xscroll.pack(side="bottom", fill="x")
        self.gutter = tk.Text(
            editor_frame, width=4, wrap="none", font="TkFixedFont", state="disabled",
            takefocus=0, borderwidth=0, highlightthickness=0, background="#f0f0f0",
            foreground="#808080", padx=4,
        )
        self.gutter.pack(side="left", fill="y")
        self.editor = tk.Text(
            editor_frame, wrap="none", undo=True, font="TkFixedFont",
            yscrollcommand=self._editor_scrolled, xscrollcommand=editor_xscroll.set,
        )
        self.editor.pack(fill="both", expand=True)
        self.editor_scroll = editor_scroll
        editor_scroll.configure(command=self._scroll_both)
        editor_xscroll.configure(command=self.editor.xview)
        self.editor.bind("<KeyRelease>", self._edited)
        self.editor.bind("<ButtonRelease-1>", self._cursor_moved)
        self.editor.bind("<<Modified>>", self._modified)
        self.editor.tag_configure("comment", foreground="#6a9955")
        self.editor.tag_configure("string", foreground="#a31515")
        self.editor.tag_configure("keyword", foreground="#0000cc")
        self.editor.tag_configure("number", foreground="#098658")
        self.editor.tag_configure("tag", foreground="#800000")
        self.editor.tag_configure("property", foreground="#0451a5")
        self.editor.tag_configure("current_line", background="#f5f7fb")
        self.editor.tag_configure("bracket", background="#dbe9ff")
        self.editor.tag_configure("error", background="#ffe0e0")
        self.editor.tag_lower("current_line")
        self.editor.tag_raise("error")
        self.edit_menu = EditMenu(self.editor, "text", on_save=self.save)
        self.window.bind("<Control-KeyPress>", self._window_key)

        self.status = ttk.Label(self.window, text="Выберите файл в списке слева", padding=(8, 2))
        self.status.pack(fill="x")
        self.refresh()

    def _window_key(self, event):
        if shortcut_action(event.keysym, event.keycode, state=getattr(event, "state", 0)) == "save":
            self.save()
            return "break"
        return None

    def _show_error(self, error: Exception) -> None:
        self.messagebox.showerror("Ошибка редактора файлов", str(error), parent=self.window)

    def _set_status(self) -> None:
        if not self.current_path:
            self.status.configure(text="Файл не открыт", foreground="")
            return
        modified = " — изменён, не сохранён" if self.editor.edit_modified() else ""
        if self.check_result:
            line, message = self.check_result
            self.status.configure(
                text="{}{} — строка {}: {}".format(self.current_path, modified, line, message),
                foreground="#b00020",
            )
        elif syntax_language(self.current_path):
            self.status.configure(text="{}{} — синтаксис в порядке".format(self.current_path, modified), foreground="")
        else:
            self.status.configure(text="{}{}".format(self.current_path, modified), foreground="")

    def open_in_web_editor(self) -> None:
        """Тот же файл в /edit прошивки: Ace с подсказками и полноценной проверкой синтаксиса."""
        import webbrowser

        webbrowser.open(web_editor_url(self.address, self.current_path))

    # ------------------------------------------------------------------ подсветка и проверка
    def _editor_scrolled(self, first, last) -> None:
        self.editor_scroll.set(first, last)
        self.gutter.yview_moveto(first)

    def _scroll_both(self, *args) -> None:
        self.editor.yview(*args)
        self.gutter.yview(*args)

    def _update_gutter(self) -> None:
        lines = int(self.editor.index("end-1c").split(".")[0])
        current = int(self.gutter.index("end-1c").split(".")[0]) if self.gutter.get("1.0", "end-1c") else 0
        if current == lines:
            return
        self.gutter.configure(state="normal", width=max(4, len(str(lines)) + 1))
        self.gutter.delete("1.0", "end")
        self.gutter.insert("1.0", "\n".join("{:>{}}".format(number, len(str(lines))) for number in range(1, lines + 1)))
        self.gutter.configure(state="disabled")
        self.gutter.yview_moveto(self.editor.yview()[0])

    def _edited(self, _event=None) -> None:
        self._highlight()
        self._cursor_moved()
        self._schedule_check()

    def _cursor_moved(self, _event=None) -> None:
        self.editor.tag_remove("current_line", "1.0", "end")
        self.editor.tag_remove("bracket", "1.0", "end")
        self.editor.tag_add("current_line", "insert linestart", "insert lineend+1c")
        if not self.current_path:
            return
        text = self.editor.get("1.0", "end-1c")
        code = code_without_literals(self.current_path, text)
        position = len(self.editor.get("1.0", "insert"))
        for candidate in (position - 1, position):
            partner = matching_bracket(code, candidate)
            if partner is not None:
                for index in (candidate, partner):
                    self.editor.tag_add("bracket", "1.0+{}c".format(index), "1.0+{}c".format(index + 1))
                break

    def _schedule_check(self) -> None:
        if self.check_id is not None:
            self.window.after_cancel(self.check_id)
        self.check_id = self.window.after(400, self._run_check)

    def _run_check(self) -> None:
        self.check_id = None
        self.editor.tag_remove("error", "1.0", "end")
        if not self.current_path:
            self.check_result = None
            return
        self.check_result = check_syntax(self.current_path, self.editor.get("1.0", "end-1c"))
        if self.check_result:
            line = self.check_result[0]
            self.editor.tag_add("error", "{}.0".format(line), "{}.0+1l".format(line))
        self._set_status()

    def _modified(self, _event=None) -> None:
        self._set_status()

    def _discard_changes_allowed(self) -> bool:
        if not self.current_path or not self.editor.edit_modified():
            return True
        return self.messagebox.askyesno(
            "Несохранённые изменения",
            "Файл {} изменён. Отбросить изменения?".format(self.current_path),
            parent=self.window,
        )

    def refresh(self) -> None:
        try:
            entries = self.client.list_files()
        except ConfigError as error:
            self._show_error(error)
            return
        self.files = [
            str(entry.get("name")) for entry in entries
            if isinstance(entry, dict) and entry.get("type") == "file" and isinstance(entry.get("name"), str)
        ]
        self.files.sort(key=str.lower)
        self.file_list.delete(0, "end")
        for path in self.files:
            label = path[1:] if path.startswith("/") else path
            if label.lower().endswith(".gz"):
                label = label[:-3] + "  [gzip]"
            self.file_list.insert("end", label)
        if self.current_path in self.files:
            self.file_list.selection_set(self.files.index(self.current_path))

    def _selected_path(self) -> Optional[str]:
        selection = self.file_list.curselection()
        return self.files[selection[0]] if selection else None

    def _load_text(self, path: Optional[str], text: str) -> None:
        self.current_path = path
        self.web_button.configure(state="normal" if web_editor_supports(path) else "disabled")
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", text)
        self.editor.edit_reset()
        self.editor.edit_modified(False)
        self._highlight()
        self._cursor_moved()
        self._run_check()

    def open_selected(self, _event=None) -> None:
        path = self._selected_path()
        if not path or path == self.current_path:
            return
        if not self._discard_changes_allowed():
            self.file_list.selection_clear(0, "end")
            if self.current_path in self.files:
                self.file_list.selection_set(self.files.index(self.current_path))
            return
        if not is_text_remote_file(path):
            self._load_text(None, "")
            self.status.configure(
                text="{}: двоичный файл, доступны только скачивание и удаление".format(path)
            )
            return
        try:
            text = decode_remote_text(path, self.client.read_file(path))
        except ConfigError as error:
            self._show_error(error)
            return
        self._load_text(path, text)

    def save(self) -> None:
        if not self.current_path:
            self.messagebox.showerror("Файл не выбран", "Выберите или создайте файл", parent=self.window)
            return
        try:
            payload = encode_remote_text(self.current_path, self.editor.get("1.0", "end-1c"))
            self.client.upload_file(self.current_path, payload)
        except ConfigError as error:
            self._show_error(error)
            return
        self.editor.edit_modified(False)
        self.status.configure(text="{} — сохранён на устройстве".format(self.current_path))
        self.refresh()

    def create(self) -> None:
        if not self._discard_changes_allowed():
            return
        name = self.simpledialog.askstring("Новый файл", "Имя файла:", parent=self.window)
        if not name:
            return
        try:
            path = _remote_path(name)
            self.client.create_file(path)
        except ConfigError as error:
            self._show_error(error)
            return
        self._load_text(path, "")
        self.refresh()

    def delete(self) -> None:
        path = self._selected_path()
        if not path:
            return
        if not self.messagebox.askyesno("Удаление файла", "Удалить {}?".format(path), parent=self.window):
            return
        try:
            self.client.delete_file(path)
        except ConfigError as error:
            self._show_error(error)
            return
        if self.current_path == path:
            self._load_text(None, "")
        self.refresh()

    def upload(self) -> None:
        filename = self.filedialog.askopenfilename(parent=self.window)
        if not filename:
            return
        try:
            target, payload = prepare_remote_upload(
                Path(filename).name, Path(filename).read_bytes(), self.files
            )
            self.client.upload_file(target, payload)
        except (OSError, ConfigError) as error:
            self._show_error(error)
            return
        self.status.configure(text="{} загружен на устройство".format(target))
        self.refresh()

    def download(self) -> None:
        path = self._selected_path()
        if not path:
            return
        logical_name = Path(path[:-3] if path.lower().endswith(".gz") else path).name
        filename = self.filedialog.asksaveasfilename(initialfile=logical_name, parent=self.window)
        if not filename:
            return
        try:
            payload = self.client.read_file(path)
            if path.lower().endswith(".gz"):
                payload = gzip.decompress(payload)
            Path(filename).write_bytes(payload)
        except (OSError, ConfigError) as error:
            self._show_error(error)
            return
        self.status.configure(text="{} сохранён в {}".format(path, filename))

    def close(self) -> None:
        if self._discard_changes_allowed():
            self.window.destroy()

    def _highlight(self, _event=None) -> None:
        for tag in ("comment", "string", "keyword", "number", "tag", "property"):
            self.editor.tag_remove(tag, "1.0", "end")
        self._update_gutter()
        if not self.current_path:
            return
        text = self.editor.get("1.0", "end-1c")
        for tag, start, end in syntax_spans(self.current_path, text):
            self.editor.tag_add(tag, "1.0+{}c".format(start), "1.0+{}c".format(end))


class ConfiguratorWindow:
    def __init__(self, root, config: SamovarConfig, pio_executable: str):
        import tkinter as tk
        from tkinter import messagebox, ttk

        self.tk = tk
        self.ttk = ttk
        self.messagebox = messagebox
        self.root = root
        self.config = config
        self.pio_executable = pio_executable
        self.process = None
        self.busy = False
        self.active_action = ""
        self.output_queue = queue.Queue()
        self.stop_requested = False
        self.monitor_window = None
        self.monitor_log = None
        self.monitor_stop_button = None
        self.monitor_ip_button = None
        self.monitor_config_button = None
        self.monitor_input = None
        self.device_ip = None
        self.device_config_request_id = 0
        self.active_port_network = False
        self.value_vars = {}
        self.bool_vars = {}
        self.optional_enabled_vars = {}
        self.choice_vars = {}
        self.tooltip_widgets = {}
        self.tooltips = []
        self.edit_menus = []
        self.saved_state = None
        self.recent_lines = []
        self.action_lines = []
        self.partial_line = ""
        self.install_hint_shown = False
        self.esptool_repaired = None
        self.action_started = 0.0
        self.tick_id = None
        self.prefs = load_user_prefs()

        root.title("Настройка и прошивка Samovar")
        root.geometry(self.prefs.get("geometry") or "1280x780")
        root.minsize(1000, 640)
        root.option_add("*tearOff", False)
        root.protocol("WM_DELETE_WINDOW", self.close)

        self._build()
        self._load()
        self.root.after(100, self._drain_output)

    # ------------------------------------------------------------------ построение окна
    def _build(self) -> None:
        ttk = self.ttk
        tk = self.tk
        outer = ttk.Frame(self.root, padding=(10, 8, 10, 6))
        outer.pack(fill="both", expand=True)

        # Слева - настройки и кнопки (ширина по содержимому), справа - журнал на всю высоту.
        paned = ttk.Panedwindow(outer, orient="horizontal")
        paned.pack(fill="both", expand=True)
        left = ttk.Frame(paned)
        right = ttk.Frame(paned)
        paned.add(left, weight=0)
        paned.add(right, weight=1)

        settings = ttk.Labelframe(left, text="Настройки прошивки", padding=(8, 4, 8, 8))
        settings.pack(fill="x")
        section_row = ttk.Frame(settings)
        section_row.pack(fill="x", pady=(4, 6))
        ttk.Label(section_row, text="Раздел").pack(side="left")
        self.section_var = tk.StringVar(value=SECTIONS[0])
        self.section_combo = ttk.Combobox(
            section_row, textvariable=self.section_var, values=SECTIONS, state="readonly", width=22,
        )
        self.section_combo.pack(side="left", padx=(10, 0))
        self.section_combo.bind("<<ComboboxSelected>>", self._section_selected)
        container = ttk.Frame(settings)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)
        section_frames = {}
        section_rows = {}
        for section in SECTIONS:
            frame = ttk.Frame(container, padding=(4, 4, 0, 4))
            frame.grid(row=0, column=0, sticky="nsew")
            frame.columnconfigure(1, weight=1)
            section_frames[section] = frame
            section_rows[section] = 0
        self.section_frames = section_frames

        self.board_var = tk.StringVar()
        self._add_combo(
            section_frames, section_rows, "Основные", "Плата", self.board_var,
            tuple(BOARD_OPTIONS),
        )
        self.servo_var = tk.StringVar()
        self._add_entry(
            section_frames, section_rows, "Оборудование", "Поправки сервопривода (11 чисел)",
            self.servo_var, "servoDelta",
        )

        self.choice_vars["regulator"] = tk.StringVar()
        self._add_combo(
            section_frames, section_rows, "Регулятор", "Тип регулятора",
            self.choice_vars["regulator"], tuple(CHOICE_OPTIONS["Регулятор мощности"]), "regulator",
        )
        self.choice_vars["atmospheric_sensor"] = tk.StringVar()
        self._add_combo(
            section_frames, section_rows, "Датчики", "Атмосферное давление",
            self.choice_vars["atmospheric_sensor"],
            tuple(CHOICE_OPTIONS["Датчик атмосферного давления"]),
            "atmospheric_sensor",
        )
        self.choice_vars["column_pressure_sensor"] = tk.StringVar()
        self._add_combo(
            section_frames, section_rows, "Датчики", "Давление в колонне",
            self.choice_vars["column_pressure_sensor"],
            tuple(CHOICE_OPTIONS["Датчик давления в колонне"]),
            "column_pressure_sensor",
        )

        for spec in VALUE_SPECS:
            variable = tk.StringVar()
            self.value_vars[spec.macro] = variable
            self._add_entry(
                section_frames, section_rows, spec.section, spec.label, variable, spec.macro
            )
        for spec in BOOL_SPECS:
            variable = tk.BooleanVar()
            self.bool_vars[spec.macro] = variable
            row = section_rows[spec.section]
            checkbutton = ttk.Checkbutton(
                section_frames[spec.section], text=spec.label, variable=variable
            )
            checkbutton.grid(
                row=row, column=0, columnspan=2, sticky="w", pady=3
            )
            self._register_tooltip(spec.macro, checkbutton)
            section_rows[spec.section] += 1
        for spec in OPTIONAL_SPECS:
            enabled = tk.BooleanVar()
            value = tk.StringVar()
            self.optional_enabled_vars[spec.macro] = enabled
            self.value_vars[spec.macro] = value
            row = section_rows[spec.section]
            checkbutton = ttk.Checkbutton(
                section_frames[spec.section], text=spec.label, variable=enabled
            )
            checkbutton.grid(
                row=row, column=0, sticky="w", pady=3
            )
            entry = ttk.Entry(section_frames[spec.section], textvariable=value, width=24)
            entry.grid(
                row=row, column=1, sticky="ew", padx=(10, 0), pady=3
            )
            self._install_edit_menu(entry, "entry")
            self._register_tooltip(spec.macro, checkbutton, entry)
            section_rows[spec.section] += 1
        for spec in CHOICE_VALUE_SPECS:
            variable = tk.StringVar()
            self.value_vars[spec.macro] = variable
            self._add_entry(
                section_frames, section_rows, spec.section, spec.label, variable, spec.macro
            )

        self.ssid_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self._add_entry(section_frames, section_rows, "Сеть", "SSID Wi-Fi", self.ssid_var)
        row = section_rows["Сеть"]
        ttk.Label(section_frames["Сеть"], text="Пароль Wi-Fi").grid(row=row, column=0, sticky="w", pady=3)
        password_row = ttk.Frame(section_frames["Сеть"])
        password_row.grid(row=row, column=1, sticky="ew", padx=(10, 0), pady=3)
        password_row.columnconfigure(0, weight=1)
        self.password_entry = ttk.Entry(password_row, textvariable=self.password_var, show="•", width=24)
        self.password_entry.grid(row=0, column=0, sticky="ew")
        self._install_edit_menu(self.password_entry, "entry")
        self.show_password_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            password_row, text="Показать", variable=self.show_password_var,
            command=self._toggle_password,
        ).grid(row=0, column=1, padx=(8, 0))
        section_rows["Сеть"] += 1

        row = section_rows["Оборудование"]
        ttk.Label(
            section_frames["Оборудование"],
            text=(
                "Режим «Сыр»: оператор подключает к LUA_PIN либо PH-4502C, либо "
                "MPX5010DP; к реле №4 — либо клапан слива, либо разгонный ТЭН."
            ),
            wraplength=430,
            foreground="#555555",
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(10, 0))
        section_rows["Оборудование"] += 1
        section_frames[SECTIONS[0]].tkraise()

        # --- устройство: порт USB или адрес в сети, общие кнопки
        usb = ttk.Labelframe(left, text="Устройство", padding=(10, 6, 10, 8))
        usb.pack(fill="x", pady=(10, 0))
        usb.columnconfigure(1, weight=1)
        ttk.Label(usb, text="Порт или адрес").grid(row=0, column=0, sticky="w")
        self.port_var = tk.StringVar(value=self.prefs.get("port", ""))
        self.port_combo = ttk.Combobox(
            usb, textvariable=self.port_var, values=(), state="normal"
        )
        self.port_combo.grid(row=0, column=1, sticky="ew", padx=(10, 0))
        self._install_edit_menu(self.port_combo, "entry")
        self.tooltips.append(Tooltip(
            self.port_combo,
            "COM-порт для прошивки по USB или устройство в сети для обновления по Wi-Fi "
            "(OTA - «по воздуху»). Кнопка «Обновить» ищет и то, и другое; адрес можно "
            "ввести вручную, например 192.168.1.37 или samovar.local.",
        ))
        self.port_refresh_button = ttk.Button(usb, text="Обновить", command=self.refresh_ports)
        self.port_refresh_button.grid(row=0, column=2, padx=(8, 0))
        usb_buttons = self._button_holder(usb)
        self.upload_button = ttk.Button(usb_buttons, text="Прошить", command=lambda: self.start_action("upload"))
        self.fs_button = ttk.Button(usb_buttons, text="Загрузить LittleFS", command=self.start_littlefs)
        self.erase_button = ttk.Button(
            usb_buttons, text="Полностью очистить флеш", command=self.start_flash_erase
        )
        self.monitor_button = ttk.Button(usb_buttons, text="Монитор порта", command=self.open_monitor)
        self.reboot_button = ttk.Button(usb_buttons, text="Перезагрузить ESP", command=self.reboot_esp)
        self.editor_button = ttk.Button(usb_buttons, text="Редактор файлов", command=self.open_file_editor)
        self.browser_button = ttk.Button(usb_buttons, text="Открыть в браузере", command=self.open_in_browser)
        self._grid_buttons(usb_buttons, (
            self.upload_button, self.fs_button, self.erase_button,
            self.monitor_button, self.reboot_button, self.editor_button, self.browser_button,
        ))
        self.tooltips.append(Tooltip(
            self.upload_button,
            "Собрать прошивку и записать её на выбранное устройство: по USB через COM-порт "
            "или по Wi-Fi, если выбран адрес в сети. Настройки сохраняются автоматически.",
        ))
        self.tooltips.append(Tooltip(
            self.fs_button,
            "Собрать образ LittleFS с веб-интерфейсом и записать его по USB или по Wi-Fi. "
            "Файлы и пользовательские данные на устройстве будут заменены.",
        ))
        self.tooltips.append(Tooltip(self.monitor_button, "Показывает вывод устройства (только по USB). Кнопка «Получить IP» в мониторе запрашивает адрес устройства для работы по Wi-Fi."))
        self.tooltips.append(Tooltip(self.editor_button, "Файлы на устройстве через веб-интерфейс. Нужен адрес устройства в сети: выберите его в списке выше или получите через монитор порта."))
        self.port_var.trace_add("write", lambda *_: self._port_changed())
        self.port_combo.bind("<<ComboboxSelected>>", self._network_device_selected)
        self.port_combo.bind("<Return>", self._network_address_entered)

        # --- журнал
        log_box = ttk.Labelframe(right, text="Журнал", padding=(8, 4, 8, 8))
        log_box.pack(fill="both", expand=True, padx=(10, 0))
        log_tools = ttk.Frame(log_box)
        log_tools.pack(fill="x", pady=(0, 4))
        ttk.Button(log_tools, text="Очистить", command=self.clear_log).pack(side="left")
        ttk.Button(log_tools, text="Копировать всё", command=self.copy_log).pack(side="left", padx=(8, 0))
        self.log_autoscroll = tk.BooleanVar(value=True)
        ttk.Checkbutton(log_tools, text="Прокручивать к концу", variable=self.log_autoscroll).pack(side="right")
        log_frame = ttk.Frame(log_box)
        log_frame.pack(fill="both", expand=True)
        scrollbar = ttk.Scrollbar(log_frame)
        scrollbar.pack(side="right", fill="y")
        self.log = tk.Text(
            log_frame, height=8, width=60, wrap="word", yscrollcommand=scrollbar.set,
            font="TkFixedFont", state="disabled",
        )
        self.log.pack(side="left", fill="both", expand=True)
        scrollbar.configure(command=self.log.yview)
        configure_log_tags(self.log)
        self._install_edit_menu(self.log, "readonly", on_clear=self.clear_log)

        # --- нижняя панель: сохранение, остановка, состояние
        bar = ttk.Frame(outer)
        bar.pack(fill="x", pady=(8, 0))
        self.save_button = ttk.Button(bar, text="Сохранить настройки", command=self.save)
        self.save_button.pack(side="left")
        self.stop_button = ttk.Button(bar, text="Остановить", command=self.stop_action, state="disabled")
        self.stop_button.pack(side="left", padx=(8, 0))
        self.dirty_var = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self.dirty_var, foreground="#8a5a00").pack(side="left", padx=(12, 0))
        self.status_var = tk.StringVar(value="Готово")
        ttk.Label(bar, textvariable=self.status_var).pack(side="right")

    def _button_holder(self, parent):
        holder = self.ttk.Frame(parent)
        holder.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        return holder

    @staticmethod
    def _grid_buttons(holder, buttons, columns: int = 3) -> None:
        """Раскладывает кнопки одинаковой ширины сеткой."""
        for index, button in enumerate(buttons):
            row, column = divmod(index, columns)
            button.grid(
                row=row, column=column, sticky="ew",
                padx=(0, 8) if column < columns - 1 else 0, pady=(0, 4),
            )
        for column in range(columns):
            holder.columnconfigure(column, weight=1, uniform="buttons")

    def _section_selected(self, _event=None) -> None:
        self.section_frames[self.section_var.get()].tkraise()
        self.section_combo.selection_clear()

    def _install_edit_menu(self, widget, kind: str, **options) -> None:
        self.edit_menus.append(EditMenu(widget, kind, **options))

    def _register_tooltip(self, key, *widgets) -> None:
        self.tooltip_widgets.setdefault(key, []).extend(widgets)

    def _add_entry(self, frames, rows, section, label, variable, tooltip_key=None) -> None:
        row = rows[section]
        label_widget = self.ttk.Label(frames[section], text=label)
        label_widget.grid(row=row, column=0, sticky="w", pady=3)
        entry = self.ttk.Entry(frames[section], textvariable=variable, width=24)
        entry.grid(
            row=row, column=1, sticky="ew", padx=(10, 0), pady=3
        )
        self._install_edit_menu(entry, "entry")
        if tooltip_key:
            self._register_tooltip(tooltip_key, label_widget, entry)
        rows[section] += 1

    def _add_combo(self, frames, rows, section, label, variable, values, tooltip_key=None) -> None:
        row = rows[section]
        label_widget = self.ttk.Label(frames[section], text=label)
        label_widget.grid(row=row, column=0, sticky="w", pady=3)
        combo = self.ttk.Combobox(
            frames[section], textvariable=variable, values=values, state="readonly"
        )
        combo.grid(
            row=row, column=1, sticky="ew", padx=(10, 0), pady=3
        )
        if tooltip_key:
            self._register_tooltip(tooltip_key, label_widget, combo)
        rows[section] += 1

    def _toggle_password(self) -> None:
        self.password_entry.configure(show="" if self.show_password_var.get() else "•")

    # ------------------------------------------------------------------ загрузка и состояние
    def _load(self) -> None:
        try:
            state = self.config.load()
        except (OSError, ConfigError) as error:
            self.messagebox.showerror("Ошибка чтения настроек", str(error))
            self.root.destroy()
            return
        self.board_var.set(str(state["board"]))
        self.servo_var.set(str(state["servoDelta"]))
        for macro, variable in self.value_vars.items():
            variable.set(str(state[macro]))
        for macro, variable in self.bool_vars.items():
            variable.set(bool(state[macro]))
        for macro, variable in self.optional_enabled_vars.items():
            variable.set(bool(state[macro + ".enabled"]))
        for key, variable in self.choice_vars.items():
            variable.set(str(state[key]))
        self.ssid_var.set(str(state["wifi_ssid"]))
        self.password_var.set(str(state["wifi_password"]))
        self._apply_tooltips()
        self._mark_saved()
        for variable in self._tracked_variables():
            variable.trace_add("write", lambda *_: self._refresh_dirty())
        self._port_changed()
        self.refresh_ports()

    def _tracked_variables(self):
        variables = [self.board_var, self.servo_var, self.ssid_var, self.password_var]
        variables.extend(self.value_vars.values())
        variables.extend(self.bool_vars.values())
        variables.extend(self.optional_enabled_vars.values())
        variables.extend(self.choice_vars.values())
        return variables

    def _apply_tooltips(self) -> None:
        descriptions = self.config.descriptions()
        for key, widgets in self.tooltip_widgets.items():
            description = descriptions.get(key)
            if description:
                self.tooltips.extend(Tooltip(widget, description) for widget in widgets)

    def refresh_ports(self) -> None:
        """Обновляет список: COM-порты сразу, устройства в сети (mDNS, 3 с) — в фоне."""
        try:
            ports = list_serial_ports(self.pio_executable)
        except (OSError, ConfigError) as error:
            self.messagebox.showerror("Ошибка поиска портов", str(error))
            return
        self._apply_port_list(ports, [])
        if self.busy:
            return
        self.port_refresh_button.configure(state="disabled")
        self.status_var.set("Поиск устройств в сети…")

        def search() -> None:
            try:
                devices = list_network_devices(self.pio_executable)
            except (OSError, ConfigError) as error:
                self.output_queue.put(("network_error", str(error)))
                return
            self.output_queue.put(("network", devices))

        threading.Thread(target=search, daemon=True).start()

    def _apply_port_list(self, ports: List[str], devices: List[str]) -> None:
        values = list(ports)
        for label in devices:
            if label not in values:
                values.append(label)
        if self.device_ip and not any(port_value(value) == self.device_ip for value in values):
            values.append(network_port_label(self.device_ip))
        current = self.port_var.get().strip()
        self.port_combo.configure(values=values)
        if not current and values:
            self.port_var.set(values[0])

    def _network_search_done(self, devices: Optional[List[str]], error: str = "") -> None:
        if not self.busy:
            self.port_refresh_button.configure(state="normal")
        if devices is None:
            self._append_log("Поиск устройств в сети не удался: {}\n".format(error), "warning")
            self.status_var.set("Устройства в сети не найдены")
            return
        self._apply_port_list(list(self.port_combo.cget("values")), devices)
        self.status_var.set(
            "Найдено устройств в сети: {}".format(len(devices)) if devices else "Устройства в сети не найдены"
        )

    def _state(self) -> Dict[str, object]:
        state = {macro: variable.get() for macro, variable in self.value_vars.items()}
        state.update({macro: variable.get() for macro, variable in self.bool_vars.items()})
        state.update(
            {macro + ".enabled": variable.get() for macro, variable in self.optional_enabled_vars.items()}
        )
        state.update({key: variable.get() for key, variable in self.choice_vars.items()})
        state.update({
            "board": self.board_var.get(),
            "servoDelta": self.servo_var.get(),
            "wifi_ssid": self.ssid_var.get(),
            "wifi_password": self.password_var.get(),
        })
        return state

    def _mark_saved(self) -> None:
        self.saved_state = self._state()
        self._refresh_dirty()

    def is_dirty(self) -> bool:
        return self.saved_state is not None and self._state() != self.saved_state

    def _refresh_dirty(self) -> None:
        if self.saved_state is None:
            return
        dirty = self.is_dirty()
        self.dirty_var.set("Есть несохранённые изменения" if dirty else "")
        self.root.title("Настройка и прошивка Samovar" + (" *" if dirty else ""))

    def save(self, show_success: bool = True) -> bool:
        try:
            self.config.save(self._state())
        except (OSError, ConfigError) as error:
            self.messagebox.showerror("Настройки не сохранены", str(error))
            return False
        self._mark_saved()
        self._append_log("Настройки сохранены.\n")
        if show_success:
            self.status_var.set("Настройки сохранены")
        return True

    # ------------------------------------------------------------------ команды
    def start_littlefs(self) -> None:
        confirmed = self.messagebox.askyesno(
            "Загрузка LittleFS",
            "Файловая система и пользовательские данные на устройстве могут быть перезаписаны. Продолжить?",
        )
        if confirmed:
            self.start_action("uploadfs")

    def start_flash_erase(self) -> None:
        confirmed = self.messagebox.askyesno(
            "Полная очистка флеша",
            "Будут удалены прошивка, LittleFS и все сохранённые настройки. Продолжить?",
        )
        if confirmed:
            self.start_action("erase")

    def device_address(self) -> str:
        """Адрес для веб-функций: выбранное устройство в сети, иначе IP из монитора порта."""
        port = self.port_var.get()
        if is_network_port(port):
            return port_value(port)
        return self.device_ip or ""

    def _port_changed(self) -> None:
        has_address = bool(self.device_address())
        state = "normal" if has_address and not self.busy else "disabled"
        self.editor_button.configure(state=state)
        self.browser_button.configure(state="normal" if has_address else "disabled")

    def _network_device_selected(self, _event=None) -> None:
        self._request_network_device_config()

    def _network_address_entered(self, _event=None):
        self._request_network_device_config()
        return "break"

    def _request_network_device_config(self) -> None:
        if self.busy or not is_network_port(self.port_var.get()):
            return
        address = port_value(self.port_var.get())
        self.device_config_request_id += 1
        request_id = self.device_config_request_id
        self.status_var.set("Получение настроек устройства…")

        def fetch() -> None:
            try:
                payload = fetch_device_config(address)
            except (OSError, ConfigError) as error:
                self.output_queue.put(("device_config_error", (request_id, address, str(error))))
                return
            self.output_queue.put(("device_config", (request_id, address, payload)))

        threading.Thread(target=fetch, daemon=True).start()

    def _network_device_config_done(self, request_id: int, address: str, payload: Optional[str], error: str = "") -> None:
        if request_id != self.device_config_request_id or port_value(self.port_var.get()) != address:
            return
        if error:
            self._report_device_config_error("Wi-Fi", error)
            return
        assert payload is not None
        self._receive_device_config(payload, "Wi-Fi")

    def _report_device_config_error(self, source: str, error: str) -> None:
        self._append_log("Не удалось получить настройки через {}: {}\n".format(source, error), "error")
        self.status_var.set("Настройки устройства не получены")

    def _receive_device_config(self, payload: str, source: str) -> None:
        try:
            config = parse_device_config(payload)
        except ConfigError as error:
            self._report_device_config_error(source, str(error))
            return
        if not self.messagebox.askyesno(
            "Получить настройки",
            "Получены настройки прошивки {} через {}. Заменить поля формы?".format(
                config.firmware_version, source
            ),
        ):
            self.status_var.set("Получение настроек отменено")
            return
        self._apply_device_config(config.settings)
        self._append_log("Настройки устройства {} получены через {}.\n".format(config.firmware_version, source), "ok")
        self.status_var.set("Настройки устройства получены")

    def _apply_device_config(self, received: Dict[str, object]) -> None:
        state = self._state()
        state.update(received)
        self.board_var.set(str(state["board"]))
        self.servo_var.set(str(state["servoDelta"]))
        for macro, variable in self.value_vars.items():
            variable.set(str(state[macro]))
        for macro, variable in self.bool_vars.items():
            variable.set(bool(state[macro]))
        for macro, variable in self.optional_enabled_vars.items():
            variable.set(bool(state[macro + ".enabled"]))
        for key, variable in self.choice_vars.items():
            variable.set(str(state[key]))
        self.ssid_var.set(str(state["wifi_ssid"]))
        self.password_var.set(str(state["wifi_password"]))
        self._refresh_dirty()

    def _device_ip_found(self, address: str) -> None:
        if address != self.device_ip:
            self._append_log("Устройство сообщило адрес {}: можно выбрать его в списке портов.\n".format(address), "ok")
        self.device_ip = address
        self._apply_port_list(list(self.port_combo.cget("values")), [])
        self._port_changed()

    def reboot_esp(self) -> None:
        try:
            command = esptool_reboot_command(self.pio_executable, self.port_var.get())
        except ConfigError as error:
            self.messagebox.showerror("Не удалось перезагрузить ESP", str(error))
            return
        self._start_process(command, "reboot")

    def open_file_editor(self) -> None:
        try:
            address = _required_address(self.device_address())
        except ConfigError as error:
            self.messagebox.showerror("Редактор файлов", str(error))
            return
        FileEditorWindow(self.root, address)

    def open_in_browser(self) -> None:
        try:
            address = _required_address(self.device_address())
        except ConfigError as error:
            self.messagebox.showerror("Открыть в браузере", str(error))
            return
        import webbrowser

        webbrowser.open("http://{}/".format(address))

    def open_monitor(self) -> None:
        if self.busy:
            self.messagebox.showerror("Команда уже выполняется", "Дождитесь завершения текущей команды")
            return
        window = self.tk.Toplevel(self.root)
        window.title("Монитор порта Samovar")
        window.geometry("1000x600")
        window.minsize(700, 400)
        window.transient(self.root)
        window.protocol("WM_DELETE_WINDOW", self.close_monitor)

        frame = self.ttk.Frame(window, padding=10)
        frame.pack(fill="both", expand=True)
        scrollbar = self.ttk.Scrollbar(frame)
        scrollbar.pack(side="right", fill="y")
        self.monitor_log = self.tk.Text(
            frame, wrap="word", yscrollcommand=scrollbar.set, font="TkFixedFont", state="disabled"
        )
        self.monitor_log.pack(side="left", fill="both", expand=True)
        scrollbar.configure(command=self.monitor_log.yview)
        configure_log_tags(self.monitor_log)
        self.monitor_menu = EditMenu(self.monitor_log, "readonly", on_clear=self.clear_monitor)

        send_row = self.ttk.Frame(window, padding=(10, 0, 10, 6))
        send_row.pack(fill="x")
        self.ttk.Label(send_row, text="Команда устройству").pack(side="left")
        self.monitor_input = self.ttk.Entry(send_row)
        self.monitor_input.pack(side="left", fill="x", expand=True, padx=(8, 8))
        self.monitor_input.bind("<Return>", lambda _event: self.send_monitor_command())
        self.monitor_input_menu = EditMenu(self.monitor_input, "entry")
        self.ttk.Button(send_row, text="Отправить", command=self.send_monitor_command).pack(side="left")

        controls = self.ttk.Frame(window, padding=(10, 0, 10, 10))
        controls.pack(fill="x")
        self.monitor_ip_button = self.ttk.Button(
            controls, text="Получить IP", command=self.request_monitor_ip
        )
        self.monitor_ip_button.pack(side="left", padx=(0, 8))
        self.monitor_config_button = self.ttk.Button(
            controls, text="Получить настройки", command=self.request_monitor_config
        )
        self.monitor_config_button.pack(side="left", padx=(0, 8))
        self.ttk.Button(controls, text="Очистить", command=self.clear_monitor).pack(side="left", padx=(0, 8))
        self.monitor_autoscroll = self.tk.BooleanVar(value=True)
        self.ttk.Checkbutton(
            controls, text="Прокручивать к концу", variable=self.monitor_autoscroll
        ).pack(side="left", padx=(0, 8))
        self.monitor_stop_button = self.ttk.Button(
            controls, text="Остановить", command=self.toggle_monitor
        )
        self.monitor_stop_button.pack(side="right")
        self.monitor_window = window
        window.grab_set()
        window.focus_set()

        self.start_action("monitor")
        if self.active_action != "monitor":
            self._destroy_monitor_window()

    def toggle_monitor(self) -> None:
        if self.busy:
            if self.active_action != "monitor":
                return
            self.stop_requested = True
            if self.process is not None:
                terminate_process_tree(self.process)
            return
        self.close_monitor()

    def _write_monitor_command(self, command: str, error_title: str) -> bool:
        if not self.busy or self.active_action != "monitor" or self.process is None:
            self.messagebox.showerror(error_title, "Монитор порта не запущен")
            return False
        assert self.process.stdin is not None
        try:
            self.process.stdin.write(command)
            self.process.stdin.flush()
        except OSError as error:
            self.messagebox.showerror(error_title, str(error))
            return False
        return True

    def request_monitor_ip(self) -> None:
        self._write_monitor_command("SAMOVAR:IP?\n", "Не удалось получить IP")

    def request_monitor_config(self) -> None:
        self._write_monitor_command("SAMOVAR:CONFIG?\n", "Не удалось получить настройки")

    def send_monitor_command(self) -> None:
        if self.monitor_input is None:
            return
        command = self.monitor_input.get().strip()
        if not command:
            return
        if self._write_monitor_command(command + "\n", "Не удалось отправить команду"):
            self.monitor_input.delete(0, "end")

    def clear_monitor(self) -> None:
        if self.monitor_log is not None:
            clear_readonly(self.monitor_log)

    def close_monitor(self) -> None:
        if self.busy and self.active_action == "monitor":
            self.stop_requested = True
            if self.process is not None:
                terminate_process_tree(self.process)
        self._destroy_monitor_window()

    def _destroy_monitor_window(self) -> None:
        if self.monitor_window is not None:
            self.monitor_window.grab_release()
            self.monitor_window.destroy()
        self.monitor_window = None
        self.monitor_log = None
        self.monitor_stop_button = None
        self.monitor_ip_button = None
        self.monitor_config_button = None
        self.monitor_input = None

    def start_action(self, action: str) -> None:
        if self.busy:
            self.messagebox.showerror("Команда уже выполняется", "Дождитесь завершения текущей команды")
            return
        if action in ("upload", "uploadfs", "erase") and os.name == "nt" and is_unc_path(self.config.project_root):
            self.messagebox.showerror(
                "Проект находится в общей папке",
                "Windows не позволяет PlatformIO собирать проект по сетевому пути. "
                "Скопируйте всю папку проекта на локальный диск Windows, например "
                r"C:\Samovar-7.00, и запустите flash_windows.bat из этой папки.",
            )
            return
        try:
            if action == "monitor":
                command = serial_monitor_command(
                    pio_python_executable(self.pio_executable), Path(__file__).resolve(),
                    self.port_var.get(),
                )
            else:
                command = pio_command(
                    self.pio_executable, self.board_var.get(), action, self.port_var.get()
                )
        except (OSError, ConfigError) as error:
            self.messagebox.showerror("Ошибка запуска", str(error))
            return
        network = is_network_port(self.port_var.get())
        if action == "upload" and network and not self.bool_vars["USE_UPDATE_OTA"].get():
            confirmed = self.messagebox.askyesno(
                "Обновление по Wi-Fi выключено в настройках",
                "В разделе «Сеть» снят флажок «Разрешить обновление по Wi-Fi». Новая прошивка "
                "не будет принимать обновления по сети: следующий раз прошивать придётся по USB. "
                "Продолжить?",
            )
            if not confirmed:
                return
        if action == "upload" and not self.save(show_success=False):
            return
        self.active_port_network = network
        self._start_process(command, action)

    def stop_action(self) -> None:
        if not self.busy or self.process is None:
            return
        self.stop_requested = True
        terminate_process_tree(self.process)

    def _start_process(self, command: List[str], action: str) -> None:
        if self.busy:
            self.messagebox.showerror("Команда уже выполняется", "Дождитесь завершения текущей команды")
            return
        try:
            self.process = subprocess.Popen(
                command,
                cwd=str(self.config.project_root),
                stdin=subprocess.PIPE if action == "monitor" else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                **process_start_options(),
            )
        except OSError as error:
            self.messagebox.showerror("Не удалось запустить PlatformIO", str(error))
            return
        self.device_config_request_id += 1
        self.stop_requested = False
        self.busy = True
        self.active_action = action
        self.recent_lines = []
        self.action_lines = []
        self.partial_line = ""
        self.install_hint_shown = False
        self.action_started = time.monotonic()
        self._set_busy(True, action)
        self._append_log("\n> {}\n".format(subprocess.list2cmdline(command)), "command")
        threading.Thread(target=self._read_process_output, args=(self.process,), daemon=True).start()
        self._tick_status()

    def _read_process_output(self, process) -> None:
        """Читает вывод порциями, а не строками: PlatformIO печатает проценты загрузки
        («Downloading 0% 10% …») без перевода строки, и построчное чтение молчало бы до конца."""
        assert process.stdout is not None
        # IncrementalNewlineDecoder превращает \r\n и одиночный \r в \n даже на стыке порций:
        # иначе \r из вывода прошивки доходит до окна журнала и Tk рисует лишний перенос.
        decoder = io.IncrementalNewlineDecoder(codecs.getincrementaldecoder("utf-8")("replace"), translate=True)
        raw = process.stdout.buffer
        while True:
            chunk = raw.read1(4096)
            if not chunk:
                break
            text = decoder.decode(chunk)
            if text:
                self.output_queue.put(("chunk", text))
        text = decoder.decode(b"", final=True)
        if text:
            self.output_queue.put(("chunk", text))
        self.output_queue.put(("done", process.wait()))

    def _note_output(self, text: str) -> None:
        """Показывает порцию вывода сразу, а строки для журнала ошибок собирает по переводу строки."""
        for piece in text.splitlines(keepends=True):
            self._append_log(piece)
            self.partial_line += piece
            if piece.endswith("\n"):
                self._note_output_line(self.partial_line)
                self.partial_line = ""

    def _note_output_line(self, line: str) -> None:
        """Разбор только по целой строке: ответ SAMOVAR:IP= прошивка печатает двумя вызовами,
        и порции могут разрезать его посередине."""
        self.recent_lines = (self.recent_lines + [line])[-12:]
        self.action_lines.append(line)
        address = extract_samovar_ip(line)
        if address:
            self._device_ip_found(address)
        payload = extract_samovar_config(line)
        if payload is not None:
            self._receive_device_config(payload, "USB")
        if "Manager: Installing" in line and not self.install_hint_shown:
            self.install_hint_shown = True
            self._append_log(PACKAGE_INSTALL_HINT, "warning")

    def _tick_status(self) -> None:
        if self.tick_id is not None:
            self.root.after_cancel(self.tick_id)
            self.tick_id = None
        if not self.busy:
            return
        elapsed = int(time.monotonic() - self.action_started)
        self.status_var.set("{}… {}:{:02d}".format(
            ACTION_LABELS.get(self.active_action, self.active_action), elapsed // 60, elapsed % 60
        ))
        self.tick_id = self.root.after(1000, self._tick_status)

    def _drain_output(self) -> None:
        try:
            while True:
                kind, value = self.output_queue.get_nowait()
                if kind == "chunk":
                    self._note_output(value)
                elif kind == "network":
                    self._network_search_done(value)
                elif kind == "network_error":
                    self._network_search_done(None, value)
                elif kind == "device_config":
                    self._network_device_config_done(value[0], value[1], value[2])
                elif kind == "device_config_error":
                    self._network_device_config_done(value[0], value[1], None, value[2])
                else:
                    self._finish_action(value)
        except queue.Empty:
            pass
        self.root.after(100, self._drain_output)

    def _finish_action(self, code: int) -> None:
        if self.partial_line:
            self._note_output_line(self.partial_line)
            self.partial_line = ""
        stopped = self.stop_requested and code != 0
        completed_action = self.active_action
        label = ACTION_LABELS.get(completed_action, completed_action)
        elapsed = int(time.monotonic() - self.action_started)
        self.process = None
        self.busy = False
        self._set_busy(False, "")
        if stopped:
            message = "Монитор порта остановлен.\n" if completed_action == "monitor" else "{}: остановлено пользователем.\n".format(label)
            self._append_log(message)
            self.status_var.set("Остановлено")
        elif code == 0:
            if completed_action == "reboot":
                self._append_log("ESP перезагружен.\n", "ok")
            else:
                self._append_log("{}: успешно завершено за {}:{:02d}.\n".format(label, elapsed // 60, elapsed % 60), "ok")
            self.status_var.set("{}: готово".format(label))
        else:
            self._append_log("{}: завершилось с ошибкой {}.\n".format(label, code), "error")
            if self._repair_esptool_and_retry(completed_action, label):
                return
            if self.active_port_network and completed_action in ("upload", "uploadfs"):
                self._append_log(OTA_FAILURE_HINT, "warning")
            self.status_var.set("{}: ошибка".format(label))
            tail = "".join(self.recent_lines).strip()
            self.messagebox.showerror(
                "Ошибка операции",
                "{} завершилась с ошибкой (код {}).\n\nПоследние строки журнала:\n{}".format(
                    label, code, tail or "(пусто)"
                ),
            )
        self.active_action = ""
        self.active_port_network = False

    def _repair_esptool_and_retry(self, action: str, label: str) -> bool:
        """Повреждённый пакет esptool удаляется, и операция повторяется один раз."""
        package = broken_esptool_package(self.action_lines)
        if not package or action not in ("upload", "uploadfs", "erase") or package == self.esptool_repaired:
            return False
        try:
            remove_broken_esptool(package)
        except (OSError, ConfigError) as error:
            self._append_log(
                "В пакете esptool не хватает библиотек, но удалить его не удалось: {}. "
                "Удалите папку {} вручную и повторите операцию.\n".format(error, package), "error",
            )
            return False
        self.esptool_repaired = package
        self._append_log(
            "В пакете esptool не хватает библиотек (ошибка импорта). Папка {} удалена, "
            "PlatformIO установит пакет заново. Повторяю: {}.\n".format(package, label), "warning",
        )
        self.active_action = ""
        self.active_port_network = False
        self.start_action(action)
        return True

    def _set_busy(self, busy: bool, action: str) -> None:
        state = "disabled" if busy else "normal"
        self.save_button.configure(state=state)
        self.upload_button.configure(state=state)
        self.fs_button.configure(state=state)
        self.erase_button.configure(state=state)
        self.monitor_button.configure(state=state)
        self.reboot_button.configure(state=state)
        self.port_combo.configure(state=state)
        self.port_refresh_button.configure(state=state)
        self.stop_button.configure(state="normal" if busy and action != "monitor" else "disabled")
        self._port_changed()
        if self.monitor_stop_button is not None:
            self.monitor_stop_button.configure(
                text="Остановить" if busy and action == "monitor" else "Закрыть",
            )
        if self.monitor_ip_button is not None:
            self.monitor_ip_button.configure(
                state="normal" if busy and action == "monitor" else "disabled"
            )
        if getattr(self, "monitor_config_button", None) is not None:
            self.monitor_config_button.configure(
                state="normal" if busy and action == "monitor" else "disabled"
            )

    def _append_log(self, text: str, tag: Optional[str] = None) -> None:
        if self.active_action == "monitor" and self.monitor_log is not None:
            target, autoscroll = self.monitor_log, self.monitor_autoscroll
        else:
            target, autoscroll = self.log, self.log_autoscroll
        write_readonly(target, text, tag or log_line_tag(text), bool(autoscroll.get()))

    def clear_log(self) -> None:
        clear_readonly(self.log)

    def copy_log(self) -> None:
        text = self.log.get("1.0", "end-1c")
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status_var.set("Журнал скопирован в буфер обмена")

    def close(self) -> None:
        if self.is_dirty():
            answer = self.messagebox.askyesnocancel(
                "Несохранённые изменения", "Сохранить изменения настроек перед выходом?"
            )
            if answer is None:
                return
            if answer and not self.save(show_success=False):
                return
        if self.process is not None:
            terminate_process_tree(self.process)
        save_user_prefs({
            "port": self.port_var.get().strip(),
            "geometry": self.root.geometry(),
        })
        self.root.destroy()


def enable_windows_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def parse_arguments(argv: Optional[List[str]] = None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--pio", default=shutil.which("pio") or shutil.which("platformio"))
    parser.add_argument("--serial-monitor")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    arguments = parse_arguments(argv)
    if arguments.serial_monitor:
        try:
            return run_serial_monitor(arguments.serial_monitor)
        except ConfigError as error:
            print(str(error), file=sys.stderr)
            return 1
    if not arguments.pio:
        print("PlatformIO не найден", file=sys.stderr)
        return 1
    try:
        import tkinter as tk
    except ImportError:
        print("Tkinter не найден. Переустановите Python с компонентом Tcl/Tk.", file=sys.stderr)
        return 1
    enable_windows_dpi_awareness()
    root = tk.Tk()
    ConfiguratorWindow(root, SamovarConfig(arguments.project_root.resolve()), arguments.pio)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
