#!/usr/bin/env python3
"""Окно настройки, сборки и прошивки Samovar для Windows."""

import argparse
import ast
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
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
    ValueSpec("PAUSE_RESUME_HYSTERESIS_DELTA", "Гистерезис паузы, °C", "Автоматика"),
    ValueSpec("PROGRAM_ROW_STOP_PAUSE_LIMIT", "Число стоп-пауз строки", "Автоматика"),
    ValueSpec("PROGRAM_ROW_STOP_PAUSE_SPEED_CUT_PCT", "Снижение скорости после стоп-пауз, %", "Автоматика"),
    ValueSpec("PROGRAM_DONE_AUTO_POWEROFF_MIN", "Автовыключение после программы, мин", "Автоматика"),
    ValueSpec("BODY_TEMP_AUTOSET_MAX_RISE", "Предел автоподъёма температуры тела, °C", "Автоматика"),
    ValueSpec("BK_STEAM_SETPOINT_MIN", "Минимальная уставка пара БК, °C", "БК"),
    ValueSpec("BK_STEAM_SETPOINT_MAX", "Максимальная уставка пара БК, °C", "БК"),
    ValueSpec("BK_WATER_ADJUST_PERIOD_MS", "Период регулировки воды БК, мс", "БК"),
    ValueSpec("BK_WATER_DEADBAND", "Мёртвая зона воды БК, °C", "БК"),
    ValueSpec("BK_WATER_PWM_STEP", "Шаг ШИМ воды БК", "БК"),
    ValueSpec("BLYNK_SAMOVAR_TOOL", "Сервер Blynk", "Сеть", "text"),
)

BOOL_SPECS = (
    BoolSpec("SAMOVAR_USE_BLYNK", "Использовать Blynk", "Сеть"),
    BoolSpec("USE_MQTT", "Сохранять логи через MQTT", "Сеть"),
    BoolSpec("USE_TELEGRAM", "Отправлять уведомления в Telegram", "Сеть"),
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
    BoolSpec("USE_BODY_TEMP_AUTOSET", "Автокоррекция температуры тела", "Автоматика"),
    BoolSpec("USE_LUA", "Использовать Lua", "Оборудование"),
    BoolSpec("USE_STEPPER_ACCELERATION", "Плавный разгон шагового двигателя", "Шаговый двигатель"),
    BoolSpec("STEPPER_REVERSE", "Обратное направление шагового двигателя", "Шаговый двигатель"),
    BoolSpec("COLUMN_WETTING", "Смачивание насадки перед ректификацией", "Автоматика"),
)

OPTIONAL_SPECS = (
    OptionalSpec("USE_WATER_VALVE", "Управление клапаном воды", "Насосы", "token"),
    OptionalSpec("USE_EXPANDER", "Адрес расширителя PCF8575", "Оборудование", "number"),
    OptionalSpec("USE_ANALOG_EXPANDER", "Адрес расширителя PCF8591", "Оборудование", "number"),
    OptionalSpec("I2CStepperStepMl", "Шагов на мл для I2CStepper", "Шаговый двигатель", "number"),
    OptionalSpec("WETTING_POWER", "Мощность смачивания насадки", "Автоматика", "number"),
)

CHOICE_VALUE_SPECS = (
    ValueSpec("USE_PRESSURE_XGZ", "Коэффициент датчика XGZP6897D", "Датчики", "number"),
    ValueSpec("USE_PRESSURE_1WIRE", "Адрес датчика давления 1-Wire", "Датчики", "onewire"),
)

SECTIONS = (
    "Основные", "Температуры", "Регулятор", "БК", "НБК", "Датчики",
    "Насосы", "Оборудование", "Шаговый двигатель", "Автоматика", "Сеть",
)

NUMERIC_RE = re.compile(
    r"^[+-]?(?:0[xX][0-9A-Fa-f]+|(?:(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?))(?:[fFuUlL]{0,3})$"
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
            state[spec.macro] = cpp_string_decode(line.value) if spec.kind == "text" else line.value
        for spec in BOOL_SPECS:
            state[spec.macro] = self._required_line(ini, spec.macro).enabled
        for spec in OPTIONAL_SPECS:
            line = self._required_line(ini, spec.macro)
            state[spec.macro + ".enabled"] = line.enabled
            state[spec.macro] = line.value
        for spec in CHOICE_VALUE_SPECS:
            state[spec.macro] = self._required_line(ini, spec.macro).value

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
            value = str(state[spec.macro]).strip()
            validate_value(value, spec.kind, spec.label)
            ini.set_macro(
                spec.macro,
                True,
                cpp_string_encode(value) if spec.kind == "text" else value,
            )
        for spec in BOOL_SPECS:
            current = self._required_line(ini, spec.macro)
            ini.set_macro(spec.macro, bool(state[spec.macro]), current.value)
        for spec in OPTIONAL_SPECS:
            value = str(state[spec.macro]).strip()
            validate_value(value, spec.kind, spec.label)
            ini.set_macro(spec.macro, bool(state[spec.macro + ".enabled"]), value)
        for spec in CHOICE_VALUE_SPECS:
            value = str(state[spec.macro]).strip()
            validate_value(value, spec.kind, spec.label)
            current = self._required_line(ini, spec.macro)
            ini.set_macro(spec.macro, current.enabled, value)

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

        servo_values = [part.strip() for part in str(state["servoDelta"]).split(",")]
        if len(servo_values) != 11 or any(not re.fullmatch(r"[+-]?\d+", item) for item in servo_values):
            raise ConfigError("Для servoDelta требуется ровно 11 целых чисел через запятую")
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


def pio_command(pio_executable: str, board: str, action: str) -> List[str]:
    if board not in BOARD_OPTIONS:
        raise ConfigError("Неизвестная плата: {}".format(board))
    targets = {"upload": "upload", "uploadfs": "uploadfs", "monitor": "monitor"}
    if action not in targets:
        raise ConfigError("Неизвестная команда: {}".format(action))
    environment = BOARD_OPTIONS[board][1]
    return [pio_executable, "run", "-e", environment, "-t", targets[action]]


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
        self.value_vars = {}
        self.bool_vars = {}
        self.optional_enabled_vars = {}
        self.choice_vars = {}

        root.title("Настройка и прошивка Samovar")
        root.geometry("1040x780")
        root.minsize(820, 620)
        root.protocol("WM_DELETE_WINDOW", self.close)

        self._build()
        self._load()
        self.root.after(100, self._drain_output)

    def _build(self) -> None:
        ttk = self.ttk
        tk = self.tk
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill="both", expand=True)

        notebook = ttk.Notebook(outer)
        notebook.pack(fill="both", expand=True)
        section_frames = {}
        section_rows = {}
        for section in SECTIONS:
            frame = ttk.Frame(notebook, padding=12)
            notebook.add(frame, text=section)
            frame.columnconfigure(1, weight=1)
            section_frames[section] = frame
            section_rows[section] = 0

        self.board_var = tk.StringVar()
        self._add_combo(section_frames, section_rows, "Основные", "Плата", self.board_var, tuple(BOARD_OPTIONS))
        self.servo_var = tk.StringVar()
        self._add_entry(section_frames, section_rows, "Основные", "Поправки сервопривода (11 чисел)", self.servo_var)

        self.choice_vars["regulator"] = tk.StringVar()
        self._add_combo(
            section_frames, section_rows, "Регулятор", "Тип регулятора",
            self.choice_vars["regulator"], tuple(CHOICE_OPTIONS["Регулятор мощности"]),
        )
        self.choice_vars["atmospheric_sensor"] = tk.StringVar()
        self._add_combo(
            section_frames, section_rows, "Датчики", "Атмосферное давление",
            self.choice_vars["atmospheric_sensor"],
            tuple(CHOICE_OPTIONS["Датчик атмосферного давления"]),
        )
        self.choice_vars["column_pressure_sensor"] = tk.StringVar()
        self._add_combo(
            section_frames, section_rows, "Датчики", "Давление в колонне",
            self.choice_vars["column_pressure_sensor"],
            tuple(CHOICE_OPTIONS["Датчик давления в колонне"]),
        )

        for spec in VALUE_SPECS:
            variable = tk.StringVar()
            self.value_vars[spec.macro] = variable
            self._add_entry(section_frames, section_rows, spec.section, spec.label, variable)
        for spec in BOOL_SPECS:
            variable = tk.BooleanVar()
            self.bool_vars[spec.macro] = variable
            row = section_rows[spec.section]
            ttk.Checkbutton(section_frames[spec.section], text=spec.label, variable=variable).grid(
                row=row, column=0, columnspan=2, sticky="w", pady=3
            )
            section_rows[spec.section] += 1
        for spec in OPTIONAL_SPECS:
            enabled = tk.BooleanVar()
            value = tk.StringVar()
            self.optional_enabled_vars[spec.macro] = enabled
            self.value_vars[spec.macro] = value
            row = section_rows[spec.section]
            ttk.Checkbutton(section_frames[spec.section], text=spec.label, variable=enabled).grid(
                row=row, column=0, sticky="w", pady=3
            )
            ttk.Entry(section_frames[spec.section], textvariable=value, width=34).grid(
                row=row, column=1, sticky="ew", padx=(10, 0), pady=3
            )
            section_rows[spec.section] += 1
        for spec in CHOICE_VALUE_SPECS:
            variable = tk.StringVar()
            self.value_vars[spec.macro] = variable
            self._add_entry(section_frames, section_rows, spec.section, spec.label, variable)

        self.ssid_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self._add_entry(section_frames, section_rows, "Сеть", "SSID Wi-Fi", self.ssid_var)
        row = section_rows["Сеть"]
        ttk.Label(section_frames["Сеть"], text="Пароль Wi-Fi").grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(
            section_frames["Сеть"], textvariable=self.password_var, show="•", width=34
        ).grid(row=row, column=1, sticky="ew", padx=(10, 0), pady=3)

        buttons = ttk.Frame(outer, padding=(0, 10, 0, 8))
        buttons.pack(fill="x")
        self.save_button = ttk.Button(buttons, text="Сохранить настройки", command=self.save)
        self.upload_button = ttk.Button(buttons, text="Прошить", command=lambda: self.start_action("upload"))
        self.fs_button = ttk.Button(buttons, text="Загрузить LittleFS", command=self.start_littlefs)
        self.monitor_button = ttk.Button(buttons, text="Монитор порта", command=self.toggle_monitor)
        for button in (self.save_button, self.upload_button, self.fs_button, self.monitor_button):
            button.pack(side="left", padx=(0, 8))

        ttk.Label(outer, text="Журнал").pack(anchor="w")
        log_frame = ttk.Frame(outer)
        log_frame.pack(fill="both", expand=False)
        scrollbar = ttk.Scrollbar(log_frame)
        scrollbar.pack(side="right", fill="y")
        self.log = tk.Text(log_frame, height=13, wrap="word", yscrollcommand=scrollbar.set)
        self.log.pack(side="left", fill="both", expand=True)
        scrollbar.configure(command=self.log.yview)

    def _add_entry(self, frames, rows, section, label, variable) -> None:
        row = rows[section]
        self.ttk.Label(frames[section], text=label).grid(row=row, column=0, sticky="w", pady=3)
        self.ttk.Entry(frames[section], textvariable=variable, width=34).grid(
            row=row, column=1, sticky="ew", padx=(10, 0), pady=3
        )
        rows[section] += 1

    def _add_combo(self, frames, rows, section, label, variable, values) -> None:
        row = rows[section]
        self.ttk.Label(frames[section], text=label).grid(row=row, column=0, sticky="w", pady=3)
        self.ttk.Combobox(frames[section], textvariable=variable, values=values, state="readonly").grid(
            row=row, column=1, sticky="ew", padx=(10, 0), pady=3
        )
        rows[section] += 1

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

    def save(self, show_success: bool = True) -> bool:
        try:
            self.config.save(self._state())
        except (OSError, ConfigError) as error:
            self.messagebox.showerror("Настройки не сохранены", str(error))
            return False
        self._append_log("Настройки сохранены.\n")
        if show_success:
            self.messagebox.showinfo("Samovar", "Настройки сохранены")
        return True

    def start_littlefs(self) -> None:
        confirmed = self.messagebox.askyesno(
            "Загрузка LittleFS",
            "Файловая система и пользовательские данные на устройстве могут быть перезаписаны. Продолжить?",
        )
        if confirmed:
            self.start_action("uploadfs")

    def toggle_monitor(self) -> None:
        if self.busy:
            if self.active_action != "monitor":
                return
            self.stop_requested = True
            if self.process is not None:
                self.process.terminate()
            return
        self.start_action("monitor")

    def start_action(self, action: str) -> None:
        if self.busy:
            self.messagebox.showerror("Команда уже выполняется", "Дождитесь завершения текущей команды")
            return
        if action == "upload" and not self.save(show_success=False):
            return
        try:
            command = pio_command(self.pio_executable, self.board_var.get(), action)
        except ConfigError as error:
            self.messagebox.showerror("Ошибка запуска", str(error))
            return
        try:
            self.process = subprocess.Popen(
                command,
                cwd=str(self.config.project_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as error:
            self.messagebox.showerror("Не удалось запустить PlatformIO", str(error))
            return
        self.stop_requested = False
        self.busy = True
        self.active_action = action
        self._set_busy(True, action)
        self._append_log("\n> {}\n".format(subprocess.list2cmdline(command)))
        threading.Thread(target=self._read_process_output, args=(self.process,), daemon=True).start()

    def _read_process_output(self, process) -> None:
        assert process.stdout is not None
        for line in process.stdout:
            self.output_queue.put(("line", line))
        self.output_queue.put(("done", process.wait()))

    def _drain_output(self) -> None:
        try:
            while True:
                kind, value = self.output_queue.get_nowait()
                if kind == "line":
                    self._append_log(value)
                else:
                    stopped = self.stop_requested
                    self.process = None
                    self.busy = False
                    self.active_action = ""
                    self._set_busy(False, "")
                    if stopped:
                        self._append_log("Монитор порта остановлен.\n")
                    elif value == 0:
                        self._append_log("Операция успешно завершена.\n")
                    else:
                        self._append_log("Операция завершилась с ошибкой {}.\n".format(value))
                        self.messagebox.showerror("Ошибка PlatformIO", "Код завершения: {}".format(value))
        except queue.Empty:
            pass
        self.root.after(100, self._drain_output)

    def _set_busy(self, busy: bool, action: str) -> None:
        state = "disabled" if busy else "normal"
        self.save_button.configure(state=state)
        self.upload_button.configure(state=state)
        self.fs_button.configure(state=state)
        self.monitor_button.configure(
            state="normal" if busy and action == "monitor" else state,
            text="Остановить монитор" if busy and action == "monitor" else "Монитор порта",
        )

    def _append_log(self, text: str) -> None:
        self.log.insert("end", text)
        self.log.see("end")

    def close(self) -> None:
        if self.process is not None:
            self.process.terminate()
        self.root.destroy()


def parse_arguments(argv: Optional[List[str]] = None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--pio", default=shutil.which("pio") or shutil.which("platformio"))
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    arguments = parse_arguments(argv)
    if not arguments.pio:
        print("PlatformIO не найден", file=sys.stderr)
        return 1
    try:
        import tkinter as tk
    except ImportError:
        print("Tkinter не найден. Переустановите Python с компонентом Tcl/Tk.", file=sys.stderr)
        return 1
    root = tk.Tk()
    ConfiguratorWindow(root, SamovarConfig(arguments.project_root.resolve()), arguments.pio)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
