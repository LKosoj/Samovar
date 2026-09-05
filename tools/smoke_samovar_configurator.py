#!/usr/bin/env python3
"""Проверяет конфигуратор, выбор платы и начальные реквизиты Wi-Fi."""

import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from smoke_helpers import extract_function_body


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "samovar_configurator.py"
SPEC = importlib.util.spec_from_file_location("samovar_configurator", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
configurator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(configurator)


class ConfiguratorModelTests(unittest.TestCase):
    def make_project(self, include_override: bool = False) -> Path:
        root = Path(self.temporary.name)
        shutil.copyfile(ROOT / "Samovar_ini.h", root / "Samovar_ini.h")
        shutil.copyfile(
            ROOT / "user_config_override.example.h",
            root / "user_config_override.example.h",
        )
        if include_override:
            shutil.copyfile(ROOT / "user_config_override.h", root / "user_config_override.h")
        return root

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_round_trip_preserves_unknown_text_and_selects_exclusive_values(self) -> None:
        root = self.make_project()
        ini_path = root / "Samovar_ini.h"
        ini_path.write_text(
            ini_path.read_text(encoding="utf-8").replace(
                "#endif  // __SAMOVAR_I_H_",
                "// Пользовательская строка, которую конфигуратор не знает\n#endif  // __SAMOVAR_I_H_",
            ),
            encoding="utf-8",
        )
        model = configurator.SamovarConfig(root)
        state = model.load()
        self.assertTrue((root / "user_config_override.h").exists())
        self.assertEqual(state["board"], "ESP32 DevKit")
        self.assertEqual(state["regulator"], "KVIC")

        state.update({
            "board": "LILYGO",
            "regulator": "SEM_AVR",
            "atmospheric_sensor": "BMP280",
            "column_pressure_sensor": "XGZP6897D",
            "USE_PRESSURE_XGZ": "64",
            "MAX_WATER_TEMP": "73.5",
            "USE_WATERSENSOR": False,
            "USE_EXPANDER.enabled": True,
            "USE_EXPANDER": "0x21",
            "servoDelta": "0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10",
            "wifi_ssid": "Домашняя сеть",
            "wifi_password": "correct-pass",
        })
        model.save(state)

        ini = ini_path.read_text(encoding="utf-8")
        override = (root / "user_config_override.h").read_text(encoding="utf-8")
        self.assertIn("#define BOARD LILYGO", ini)
        self.assertIn("//#define BOARD DEVKIT", ini)
        self.assertIn("//#define BOARD ESP32S3", ini)
        self.assertIn("#define SAMOVAR_USE_SEM_AVR", ini)
        self.assertIn("//#define SAMOVAR_USE_RMVK", ini)
        self.assertIn("#define USE_BMP280", ini)
        self.assertIn("//#define USE_BME680", ini)
        self.assertIn("#define USE_PRESSURE_XGZ 64", ini)
        self.assertIn("// Пользовательская строка, которую конфигуратор не знает", ini)
        self.assertNotIn("correct-pass", ini)
        self.assertIn('#define SAMOVAR_WIFI_SSID "Домашняя сеть"', override)
        self.assertIn('#define SAMOVAR_WIFI_PASSWORD "correct-pass"', override)

        loaded = model.load()
        self.assertEqual(loaded["board"], "LILYGO")
        self.assertEqual(loaded["MAX_WATER_TEMP"], "73.5")
        self.assertEqual(loaded["USE_EXPANDER"], "0x21")
        self.assertEqual(loaded["wifi_ssid"], "Домашняя сеть")

    def test_second_board_and_regulator_are_not_hardcoded(self) -> None:
        root = self.make_project()
        model = configurator.SamovarConfig(root)
        state = model.load()
        state.update({
            "board": "ESP32-S3",
            "regulator": "РМВ-К",
            "atmospheric_sensor": "Не использовать",
            "column_pressure_sensor": "1-Wire",
            "wifi_ssid": "Workshop",
            "wifi_password": "another-pass",
        })
        model.save(state)
        loaded = model.load()
        self.assertEqual(loaded["board"], "ESP32-S3")
        self.assertEqual(loaded["regulator"], "РМВ-К")
        self.assertEqual(loaded["column_pressure_sensor"], "1-Wire")
        self.assertEqual(loaded["wifi_ssid"], "Workshop")

    def test_invalid_values_fail_without_changing_files(self) -> None:
        root = self.make_project()
        model = configurator.SamovarConfig(root)
        state = model.load()
        before_ini = model.ini_path.read_bytes()
        before_override = model.override_path.read_bytes()
        state["MAX_WATER_TEMP"] = "не число"
        with self.assertRaisesRegex(configurator.ConfigError, "требуется число"):
            model.save(state)
        self.assertEqual(model.ini_path.read_bytes(), before_ini)
        self.assertEqual(model.override_path.read_bytes(), before_override)

        state = model.load()
        state["wifi_ssid"] = "Workshop"
        state["wifi_password"] = "short"
        with self.assertRaisesRegex(configurator.ConfigError, "от 8 до 64"):
            model.save(state)
        self.assertEqual(model.ini_path.read_bytes(), before_ini)
        self.assertEqual(model.override_path.read_bytes(), before_override)

    def test_numeric_suffixes_are_hidden_and_preserved(self) -> None:
        root = self.make_project()
        model = configurator.SamovarConfig(root)
        state = model.load()
        self.assertEqual(state["PAUSE_RESUME_HYSTERESIS_DELTA"], "0.07")
        self.assertEqual(state["NBK_WORK_PRESSURE_RATIO"], "0.5")
        self.assertEqual(state["LCD_RESET_PERIOD_MS"], "240000")

        state["PAUSE_RESUME_HYSTERESIS_DELTA"] = "0.08"
        state["NBK_WORK_PRESSURE_RATIO"] = "0.6"
        state["LCD_RESET_PERIOD_MS"] = "250000"
        model.save(state)

        source = model.ini_path.read_text(encoding="utf-8")
        self.assertRegex(source, r"#define PAUSE_RESUME_HYSTERESIS_DELTA 0\.08f\b")
        self.assertRegex(source, r"#define NBK_WORK_PRESSURE_RATIO 0\.6f\b")
        self.assertRegex(source, r"#define LCD_RESET_PERIOD_MS 250000UL\b")
        loaded = model.load()
        self.assertEqual(loaded["PAUSE_RESUME_HYSTERESIS_DELTA"], "0.08")
        self.assertEqual(loaded["NBK_WORK_PRESSURE_RATIO"], "0.6")
        self.assertEqual(loaded["LCD_RESET_PERIOD_MS"], "250000")

    def test_tooltip_descriptions_come_from_header_comments(self) -> None:
        descriptions = configurator.SamovarConfig(self.make_project()).descriptions()

        self.assertEqual(
            descriptions["ALARM_WATER_TEMP"],
            "Температура воды, при достижении которой будет оповещен оператор",
        )
        self.assertIn("использовать датчик потока воды охлаждения", descriptions["USE_WATERSENSOR"])
        self.assertEqual(descriptions["servoDelta"], "Корректировка для угла поворота сервопривода.")
        self.assertIn("РМВ-К: использовать в проекте регулятор напряжения РМВК", descriptions["regulator"])

    def test_configurator_attaches_descriptions_to_registered_widgets(self) -> None:
        first_widget = object()
        second_widget = object()
        window = configurator.ConfiguratorWindow.__new__(configurator.ConfiguratorWindow)
        window.config = type(
            "Config",
            (),
            {"descriptions": lambda self: {"MAX_WATER_TEMP": "Аварийный предел"}},
        )()
        window.tooltip_widgets = {
            "MAX_WATER_TEMP": [first_widget, second_widget],
            "NO_COMMENT": [object()],
        }
        window.tooltips = []

        created = []
        with mock.patch.object(
            configurator,
            "Tooltip",
            side_effect=lambda widget, text: created.append((widget, text)) or (widget, text),
        ):
            window._apply_tooltips()

        self.assertEqual(
            created,
            [(first_widget, "Аварийный предел"), (second_widget, "Аварийный предел")],
        )
        self.assertEqual(window.tooltips, created)

    def test_tooltip_opens_below_widget_and_closes(self) -> None:
        class FakeWidget:
            def __init__(self):
                self.bindings = {}

            def bind(self, event, callback, add=None):
                self.bindings[event] = (callback, add)

            def winfo_rootx(self):
                return 100

            def winfo_rooty(self):
                return 200

            def winfo_height(self):
                return 24

        class FakeWindow:
            def wm_overrideredirect(self, value):
                self.borderless = value

            def wm_geometry(self, value):
                self.geometry = value

            def destroy(self):
                self.destroyed = True

        class FakeLabel:
            def __init__(self, parent, **options):
                self.parent = parent
                self.options = options
                labels.append(self)

            def pack(self):
                self.packed = True

        widget = FakeWidget()
        popup = FakeWindow()
        labels = []
        fake_tk = types.ModuleType("tkinter")
        fake_ttk = types.ModuleType("tkinter.ttk")
        fake_tk.Toplevel = lambda parent: popup
        fake_tk.ttk = fake_ttk
        fake_ttk.Label = FakeLabel
        tooltip = configurator.Tooltip(widget, "Описание параметра")

        with mock.patch.dict(sys.modules, {"tkinter": fake_tk, "tkinter.ttk": fake_ttk}):
            widget.bindings["<Enter>"][0]()
            self.assertIs(tooltip.window, popup)
            self.assertEqual(popup.geometry, "+116+228")
            self.assertEqual(labels[0].options["text"], "Описание параметра")
            widget.bindings["<Leave>"][0]()

        self.assertTrue(popup.destroyed)
        self.assertIsNone(tooltip.window)

    def test_monitor_uses_modal_window_and_separate_log(self) -> None:
        class FakeWidget:
            def __init__(self, *args, **kwargs):
                self.options = dict(kwargs)
                self.entries = []
                self.destroyed = False

            def pack(self, **kwargs):
                self.pack_options = kwargs

            def configure(self, **kwargs):
                self.options.update(kwargs)

            def insert(self, position, text):
                self.entries.append((position, text))

            def see(self, position):
                self.last_seen = position

            def set(self, *args):
                self.scroll = args

            def yview(self, *args):
                self.yview_args = args

        class FakeWindow(FakeWidget):
            def __init__(self):
                super().__init__()
                self.grabbed = False

            def title(self, value):
                self.window_title = value

            def geometry(self, value):
                self.window_geometry = value

            def minsize(self, width, height):
                self.minimum_size = (width, height)

            def transient(self, parent):
                self.transient_parent = parent

            def protocol(self, name, callback):
                self.protocols = {name: callback}

            def grab_set(self):
                self.grabbed = True

            def grab_release(self):
                self.grabbed = False

            def focus_set(self):
                self.focused = True

            def destroy(self):
                self.destroyed = True

        class FakeTk:
            def __init__(self):
                self.window = FakeWindow()

            def Toplevel(self, parent):
                self.window.parent = parent
                return self.window

            Text = FakeWidget

        class FakeTtk:
            Frame = FakeWidget
            Scrollbar = FakeWidget
            Button = FakeWidget

        window = configurator.ConfiguratorWindow.__new__(configurator.ConfiguratorWindow)
        window.root = object()
        window.tk = FakeTk()
        window.ttk = FakeTtk()
        window.messagebox = type("Messages", (), {"showerror": lambda *args: None})()
        window.log = FakeWidget()
        window.busy = False
        window.active_action = ""
        window.monitor_window = None
        window.monitor_log = None
        window.monitor_stop_button = None
        window.start_action = lambda action: setattr(window, "active_action", action)

        window.open_monitor()
        modal = window.monitor_window
        self.assertIs(modal.transient_parent, window.root)
        self.assertTrue(modal.grabbed)
        self.assertEqual(modal.protocols["WM_DELETE_WINDOW"], window.close_monitor)
        window._append_log("serial\n")
        self.assertEqual(window.monitor_log.entries, [("end", "serial\n")])
        self.assertEqual(window.log.entries, [])

        window.active_action = "upload"
        window._append_log("build\n")
        self.assertEqual(window.log.entries, [("end", "build\n")])

        process = type("Process", (), {"terminate": lambda self: setattr(self, "terminated", True)})()
        process.terminated = False
        window.busy = True
        window.active_action = "monitor"
        window.process = process
        window.toggle_monitor()
        self.assertTrue(window.stop_requested)
        self.assertTrue(process.terminated)
        self.assertFalse(modal.destroyed)

        window.busy = False
        window.active_action = ""
        window.close_monitor()
        self.assertTrue(modal.destroyed)
        self.assertIsNone(window.monitor_window)

    def test_main_log_expands_with_window(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn('log_frame.pack(fill="both", expand=True)', source)
        self.assertNotIn('log_frame.pack(fill="both", expand=False)', source)

    def test_cheese_shared_connections_warning_is_visible(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        for token in ('Режим «Сыр»', 'LUA_PIN', 'PH-4502C', 'MPX5010DP', 'реле №4',
                      'клапан слива', 'разгонный ТЭН'):
            self.assertIn(token, source)

    def test_commands_use_existing_environments_and_never_build_twice(self) -> None:
        self.assertEqual(
            configurator.pio_command("pio.exe", "ESP32 DevKit", "upload", "COM7"),
            ["pio.exe", "run", "-e", "Samovar", "-t", "upload", "--upload-port", "COM7"],
        )
        self.assertEqual(
            configurator.pio_command("pio.exe", "LILYGO", "uploadfs", "/dev/ttyUSB0"),
            [
                "pio.exe", "run", "-e", "Samovar", "-t", "uploadfs",
                "--upload-port", "/dev/ttyUSB0",
            ],
        )
        self.assertEqual(
            configurator.pio_command("pio.exe", "ESP32-S3", "monitor", "/dev/cu.usbserial-1"),
            [
                "pio.exe", "run", "-e", "Samovar_s3", "-t", "monitor",
                "--monitor-port", "/dev/cu.usbserial-1",
            ],
        )
        with self.assertRaisesRegex(configurator.ConfigError, "Выберите последовательный порт"):
            configurator.pio_command("pio.exe", "ESP32 DevKit", "upload", "  ")

    def test_serial_ports_are_read_from_platformio_json(self) -> None:
        result = type(
            "Result",
            (),
            {
                "returncode": 0,
                "stdout": '[{"port":"COM7"},{"port":"/dev/ttyUSB0"},{"port":"COM7"}]',
                "stderr": "",
            },
        )()
        with mock.patch.object(configurator.subprocess, "run", return_value=result) as run:
            ports = configurator.list_serial_ports("pio.exe")

        self.assertEqual(ports, ["COM7", "/dev/ttyUSB0"])
        run.assert_called_once_with(
            ["pio.exe", "device", "list", "--serial", "--json-output"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    def test_port_control_is_editable_and_refreshable(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        for token in (
            'text="Последовательный порт"',
            'self.port_combo = ttk.Combobox(',
            'state="normal"',
            'text="Обновить"',
            'command=self.refresh_ports',
        ):
            self.assertIn(token, source)

    def test_empty_port_stops_upload_before_saving_or_starting(self) -> None:
        errors = []
        window = configurator.ConfiguratorWindow.__new__(configurator.ConfiguratorWindow)
        window.busy = False
        window.config = type("Config", (), {"project_root": Path("/tmp/Samovar")})()
        window.pio_executable = "pio.exe"
        window.board_var = type("Variable", (), {"get": lambda self: "ESP32 DevKit"})()
        window.port_var = type("Variable", (), {"get": lambda self: ""})()
        window.messagebox = type(
            "Messages",
            (),
            {"showerror": lambda _, title, message: errors.append((title, message))},
        )()
        window.save = lambda **kwargs: self.fail("Upload without a port must stop before saving")

        with mock.patch.object(configurator.subprocess, "Popen") as popen:
            window.start_action("upload")

        self.assertEqual(errors, [("Ошибка запуска", "Выберите последовательный порт")])
        popen.assert_not_called()

    def test_unc_project_path_detection(self) -> None:
        self.assertTrue(configurator.is_unc_path(Path(r"\\Mac\Home\Documents\Samovar-7.00")))
        self.assertTrue(configurator.is_unc_path(Path("//server/share/Samovar-7.00")))
        self.assertFalse(configurator.is_unc_path(Path(r"C:\Users\gala\Documents\Samovar-7.00")))
        self.assertFalse(configurator.is_unc_path(Path("/Users/kosoj/Documents/Samovar-7.00")))

    def test_windows_unc_path_stops_builds_before_save(self) -> None:
        for action in ("upload", "uploadfs"):
            with self.subTest(action=action):
                errors = []
                window = configurator.ConfiguratorWindow.__new__(configurator.ConfiguratorWindow)
                window.busy = False
                window.config = type(
                    "Config",
                    (),
                    {"project_root": Path(r"\\Mac\Home\Documents\Arduino\Samovar-7.00")},
                )()
                window.messagebox = type(
                    "Messages",
                    (),
                    {"showerror": lambda _, title, message: errors.append((title, message))},
                )()
                window.save = lambda **kwargs: self.fail("UNC build must stop before saving")

                with mock.patch.object(configurator.os, "name", "nt"):
                    window.start_action(action)

                self.assertEqual(errors[0][0], "Проект находится в общей папке")
                self.assertIn(r"C:\Samovar-7.00", errors[0][1])

    def test_every_user_macro_has_an_interface_control(self) -> None:
        source = (ROOT / "Samovar_ini.h").read_text(encoding="utf-8")
        defined = set(
            re.findall(r"^\s*(?://\s*)?#define\s+([A-Za-z_]\w*)", source, re.MULTILINE)
        )
        expected = defined - {"__SAMOVAR_I_H_", "NBK_DEFAULT_PROGRAM"}
        controlled = {"BOARD"}
        controlled.update(spec.macro for spec in configurator.VALUE_SPECS)
        controlled.update(spec.macro for spec in configurator.BOOL_SPECS)
        controlled.update(spec.macro for spec in configurator.OPTIONAL_SPECS)
        controlled.update(spec.macro for spec in configurator.CHOICE_VALUE_SPECS)
        controlled.update(
            macro
            for options in configurator.CHOICE_OPTIONS.values()
            for macros in options.values()
            for macro in macros
        )
        self.assertEqual(controlled, expected)

    def test_every_control_section_has_a_tab(self) -> None:
        control_sections = {
            spec.section
            for specs in (
                configurator.VALUE_SPECS,
                configurator.BOOL_SPECS,
                configurator.OPTIONAL_SPECS,
                configurator.CHOICE_VALUE_SPECS,
            )
            for spec in specs
        }
        self.assertEqual(control_sections, set(configurator.SECTIONS))


class FirmwareIntegrationTests(unittest.TestCase):
    def test_wifi_override_is_local_and_optional(self) -> None:
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "user_config_override.h"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(tracked.returncode, 0)
        self.assertIn("user_config_override.h", (ROOT / ".gitignore").read_text(encoding="utf-8"))
        template = (ROOT / "user_config_override.example.h").read_text(encoding="utf-8")
        self.assertIn('#define SAMOVAR_WIFI_SSID ""', template)
        self.assertIn('#define SAMOVAR_WIFI_PASSWORD ""', template)
        header = (ROOT / "Samovar.h").read_text(encoding="utf-8")
        self.assertIn('#if __has_include("user_config_override.h")', header)

    def test_explicit_board_precedes_automatic_detection(self) -> None:
        for explicit, automatic, expected in (
            ("LILYGO", "ARDUINO_ESP32_DEV", "2"),
            ("ESP32S3", "ARDUINO_ESP32_DEV", "3"),
            (None, "ARDUINO_ESP32_DEV", "1"),
        ):
            definitions = "#define DEVKIT 1\n#define LILYGO 2\n#define ESP32S3 3\n"
            if explicit is not None:
                definitions += "#define BOARD {}\n".format(explicit)
            definitions += "#define {}\n#include \"Samovar_pin.h\"\nBOARD\n".format(automatic)
            result = subprocess.run(
                ["cpp", "-x", "c++", "-P", "-I", str(ROOT), "-"],
                input=definitions,
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertEqual(result.stdout.strip().splitlines()[-1], expected)

    def test_initial_wifi_credentials_use_real_firmware_function(self) -> None:
        source = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
        body = extract_function_body(source, "static void apply_initial_wifi_credentials()")
        for ssid, expected_mode, expected_begin in (("Workshop", 1, 1), ("", 0, 0)):
            harness = """
#include <cassert>
#include <cstring>
#include <string>
#include <cstdint>
#define SAMOVAR_WIFI_SSID "@SSID@"
#define SAMOVAR_WIFI_PASSWORD "correct-pass"
#define WIFI_STA 1
#define WIFI_IF_STA 0
#define ESP_OK 0
#define F(value) value
typedef int esp_err_t;
struct wifi_sta_config_t { unsigned char ssid[33]; };
struct wifi_config_t { wifi_sta_config_t sta; };
static int configResult = ESP_OK;
static bool hasStoredSsid = false;
static int modeCalls = 0;
static int beginCalls = 0;
struct FakeWiFi {
  void mode(int) { modeCalls++; }
  void begin(const char *, const char *) { beginCalls++; }
} WiFi;
struct FakeSerial {
  void print(const char *) {}
  void println(const char *) {}
} Serial;
const char *esp_err_to_name(int) { return "error"; }
int esp_wifi_get_config(int, wifi_config_t *config) {
  std::memset(config, 0, sizeof(*config));
  if (hasStoredSsid) config->sta.ssid[0] = 'x';
  return configResult;
}
static void apply_initial_wifi_credentials() {
@BODY@
}
int main() {
  apply_initial_wifi_credentials();
  assert(modeCalls == @MODE@);
  assert(beginCalls == @BEGIN@);
  modeCalls = beginCalls = 0;
  hasStoredSsid = true;
  apply_initial_wifi_credentials();
  assert(beginCalls == 0);
}
""".replace("@SSID@", ssid).replace("@BODY@", body).replace("@MODE@", str(expected_mode)).replace("@BEGIN@", str(expected_begin))
            with tempfile.TemporaryDirectory() as temporary:
                source_path = Path(temporary) / "wifi.cpp"
                binary_path = Path(temporary) / "wifi"
                source_path.write_text(harness, encoding="utf-8")
                subprocess.run(
                    ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source_path), "-o", str(binary_path)],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                subprocess.run([str(binary_path)], check=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
