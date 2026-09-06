#!/usr/bin/env python3
"""Проверяет конфигуратор, выбор платы и начальные реквизиты Wi-Fi."""

import gzip
import importlib.util
import inspect
import json
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

            def after(self, _delay, callback):
                callback()
                return "after#1"

            def after_cancel(self, _identifier):
                pass

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

            def insert(self, position, text, *tags):
                self.entries.append((position, text))

            def see(self, position):
                self.last_seen = position

            def tag_configure(self, *args, **kwargs):
                pass

            def bind(self, *args, **kwargs):
                pass

            def get(self):
                return self.options.get("value", "")

            def delete(self, *args):
                pass

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

        class FakeVar:
            def __init__(self, value=True):
                self.value = value

            def get(self):
                return self.value

        class FakeTk:
            def __init__(self):
                self.window = FakeWindow()

            def Toplevel(self, parent):
                self.window.parent = parent
                return self.window

            Text = FakeWidget
            BooleanVar = FakeVar

        class FakeTtk:
            Frame = FakeWidget
            Scrollbar = FakeWidget
            Button = FakeWidget
            Entry = FakeWidget
            Label = FakeWidget
            Checkbutton = FakeWidget

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
        window.monitor_ip_button = None
        window.monitor_input = None
        window.log_autoscroll = FakeVar(True)
        window.start_action = lambda action: setattr(window, "active_action", action)

        with mock.patch.object(configurator, "EditMenu", lambda *args, **kwargs: None), \
                mock.patch.object(configurator, "configure_log_tags", lambda widget: None):
            window.open_monitor()
        modal = window.monitor_window
        self.assertIs(modal.transient_parent, window.root)
        self.assertTrue(modal.grabbed)
        self.assertEqual(modal.protocols["WM_DELETE_WINDOW"], window.close_monitor)
        self.assertEqual(window.monitor_ip_button.options["text"], "Получить IP")
        window._append_log("serial\n")
        self.assertEqual(window.monitor_log.entries, [("end", "serial\n")])
        self.assertEqual(window.log.entries, [])

        window.active_action = "upload"
        window._append_log("build\n")
        self.assertEqual(window.log.entries, [("end", "build\n")])

        class Input:
            def __init__(self):
                self.text = ""

            def write(self, text):
                self.text += text

            def flush(self):
                self.flushed = True

        process = type("Process", (), {"terminate": lambda self: setattr(self, "terminated", True)})()
        process.terminated = False
        process.stdin = Input()
        window.busy = True
        window.active_action = "monitor"
        window.process = process
        window.request_monitor_ip()
        self.assertEqual(process.stdin.text, "SAMOVAR:IP?\n")
        self.assertTrue(process.stdin.flushed)
        window.monitor_input.options["value"] = "  SAMOVAR:STATUS?  "
        window.send_monitor_command()
        self.assertEqual(process.stdin.text, "SAMOVAR:IP?\nSAMOVAR:STATUS?\n")
        with mock.patch.object(
            configurator, "terminate_process_tree", lambda process: process.terminate()
        ):
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
        source = inspect.getsource(configurator.ConfiguratorWindow._build)
        self.assertIn('log_frame.pack(fill="both", expand=True)', source)
        self.assertNotIn('log_frame.pack(fill="both", expand=False)', source)
        # Журнал занимает правую колонку на всю высоту, настройки слева не растягиваются.
        self.assertIn('ttk.Panedwindow(outer, orient="horizontal")', source)
        self.assertIn("paned.add(left, weight=0)", source)
        self.assertIn("paned.add(right, weight=1)", source)
        self.assertIn('log_box.pack(fill="both", expand=True', source)

    def test_network_port_in_the_same_list_switches_platformio_to_espota(self) -> None:
        # PlatformIO включает espota только по виду --upload-port (IPv4 или *.local);
        # переменная PLATFORMIO_UPLOAD_PROTOCOL при проверке 06.09.2026 была проигнорирована.
        for port in ("COM7", r"\\.\COM12", "/dev/ttyUSB0", "com3", ""):
            self.assertFalse(configurator.is_network_port(port), port)
        for port in ("192.168.1.37", "samovar.local", "192.168.1.37 — samovar (Wi-Fi)"):
            self.assertTrue(configurator.is_network_port(port), port)
        self.assertEqual(configurator.port_value("192.168.1.37 — samovar (Wi-Fi)"), "192.168.1.37")
        self.assertEqual(configurator.port_value(" COM7 "), "COM7")
        self.assertEqual(configurator.network_port_label("192.168.1.37", "samovar"), "192.168.1.37 — samovar (Wi-Fi)")
        self.assertEqual(
            configurator.pio_command("pio.exe", "ESP32 DevKit", "upload", "192.168.1.37 — samovar (Wi-Fi)"),
            ["pio.exe", "run", "-e", "Samovar", "-t", "upload", "--upload-port", "192.168.1.37"],
        )
        with mock.patch.object(
            configurator.socket, "getaddrinfo",
            return_value=[(None, None, None, "", ("192.168.1.40", 0))],
        ) as resolver:
            self.assertEqual(
                configurator.pio_command("pio.exe", "ESP32-S3", "uploadfs", "samovar.local"),
                ["pio.exe", "run", "-e", "Samovar_s3", "-t", "uploadfs", "--upload-port", "192.168.1.40"],
            )
        resolver.assert_called_once_with(
            "samovar.local", None, configurator.socket.AF_INET, configurator.socket.SOCK_STREAM
        )
        with mock.patch.object(configurator.socket, "getaddrinfo", side_effect=OSError("no such host")):
            with self.assertRaisesRegex(configurator.ConfigError, "Не удалось определить IP-адрес"):
                configurator.pio_command("pio.exe", "ESP32 DevKit", "upload", "samovar")
        with self.assertRaisesRegex(configurator.ConfigError, "Некорректный адрес"):
            configurator.pio_command("pio.exe", "ESP32 DevKit", "upload", "192.168.1.37; rm")
        # По сети нельзя стирать флеш, смотреть монитор и перезагружать через esptool
        with self.assertRaisesRegex(configurator.ConfigError, "только по USB"):
            configurator.pio_command("pio.exe", "ESP32 DevKit", "erase", "192.168.1.37")
        with self.assertRaisesRegex(configurator.ConfigError, "только по USB"):
            configurator.esptool_reboot_command("pio.exe", "samovar.local")
        with self.assertRaisesRegex(configurator.ConfigError, "только по USB"):
            configurator.serial_monitor_command("python", Path("x.py"), "192.168.1.37 — samovar (Wi-Fi)")
        self.assertEqual(
            configurator.esptool_reboot_command("pio.exe", "COM7")[-3:], ["--port", "COM7", "run"]
        )
        process_source = inspect.getsource(configurator.ConfiguratorWindow._start_process)
        self.assertIn("**process_start_options()", process_source)
        for method in ("stop_action", "close", "close_monitor", "toggle_monitor"):
            self.assertIn(
                "terminate_process_tree(self.process)",
                inspect.getsource(getattr(configurator.ConfiguratorWindow, method)),
                method,
            )

    def test_network_devices_are_read_from_mdns_arduino_services(self) -> None:
        result = type("Result", (), {
            "returncode": 0,
            "stdout": json.dumps([
                {"type": "_arduino._tcp.local.", "name": "samovar._arduino._tcp.local.", "ip": "192.168.1.37", "port": 3232},
                {"type": "_http._tcp.local.", "name": "printer._http._tcp.local.", "ip": "192.168.1.5", "port": 80},
                {"type": "_arduino._tcp.local.", "name": "esp-kitchen._arduino._tcp.local.", "ip": "fe80::1, 192.168.1.38", "port": 3232},
                {"type": "_arduino._tcp.local.", "name": "samovar._arduino._tcp.local.", "ip": "192.168.1.37", "port": 3232},
            ]),
            "stderr": "",
        })()
        with mock.patch.object(configurator.subprocess, "run", return_value=result) as run:
            devices = configurator.list_network_devices("pio.exe")
        self.assertEqual(devices, ["192.168.1.37 — samovar (Wi-Fi)", "192.168.1.38 — esp-kitchen (Wi-Fi)"])
        run.assert_called_once_with(
            ["pio.exe", "device", "list", "--mdns", "--json-output"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        failed = type("Result", (), {"returncode": 1, "stdout": "", "stderr": "zeroconf missing"})()
        with mock.patch.object(configurator.subprocess, "run", return_value=failed):
            with self.assertRaisesRegex(configurator.ConfigError, "zeroconf missing"):
                configurator.list_network_devices("pio.exe")

    def test_refresh_merges_serial_ports_network_devices_and_reported_ip(self) -> None:
        class Variable:
            def __init__(self, value=""):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

        class Widget:
            def __init__(self):
                self.options = {"values": ()}

            def configure(self, **kwargs):
                self.options.update(kwargs)

            def cget(self, key):
                return self.options[key]

        logged = []
        window = configurator.ConfiguratorWindow.__new__(configurator.ConfiguratorWindow)
        window.busy = False
        window.pio_executable = "pio.exe"
        window.device_ip = None
        window.port_var = Variable("")
        window.port_combo = Widget()
        window.port_refresh_button = Widget()
        window.editor_button = Widget()
        window.browser_button = Widget()
        window.status_var = Variable()
        window.output_queue = configurator.queue.Queue()
        window._append_log = lambda text, tag=None: logged.append((text, tag))
        window.messagebox = type(
            "Messages", (), {"showerror": lambda _, title, message: self.fail(message)}
        )()

        class Thread:
            def __init__(self, target, daemon):
                self.target = target

            def start(self):
                self.target()

        with mock.patch.object(configurator, "list_serial_ports", return_value=["COM7"]), \
                mock.patch.object(configurator, "list_network_devices", return_value=["192.168.1.37 — samovar (Wi-Fi)"]), \
                mock.patch.object(configurator.threading, "Thread", Thread):
            window.refresh_ports()
        # COM-порты появляются сразу, а сетевые - когда закончится поиск в фоне
        self.assertEqual(window.port_combo.cget("values"), ["COM7"])
        self.assertEqual(window.port_var.get(), "COM7")
        self.assertEqual(window.port_refresh_button.options["state"], "disabled")
        window._drain_output = None
        kind, value = window.output_queue.get_nowait()
        self.assertEqual((kind, value), ("network", ["192.168.1.37 — samovar (Wi-Fi)"]))
        window._network_search_done(value)
        self.assertEqual(window.port_combo.cget("values"), ["COM7", "192.168.1.37 — samovar (Wi-Fi)"])
        self.assertEqual(window.port_var.get(), "COM7")
        self.assertEqual(window.port_refresh_button.options["state"], "normal")
        self.assertEqual(window.status_var.get(), "Найдено устройств в сети: 1")

        # адрес, который устройство сообщило в мониторе порта, тоже попадает в список
        window._device_ip_found("192.168.1.40")
        self.assertEqual(
            window.port_combo.cget("values"),
            ["COM7", "192.168.1.37 — samovar (Wi-Fi)", "192.168.1.40 — samovar (Wi-Fi)"],
        )
        self.assertEqual(logged[-1][1], "ok")
        self.assertEqual(window.device_address(), "192.168.1.40")
        self.assertEqual(window.editor_button.options["state"], "normal")
        window.port_var.set("192.168.1.37 — samovar (Wi-Fi)")
        self.assertEqual(window.device_address(), "192.168.1.37")
        window.device_ip = None
        window.port_var.set("COM7")
        window._port_changed()
        self.assertEqual(window.editor_button.options["state"], "disabled")
        self.assertEqual(window.browser_button.options["state"], "disabled")

        window._network_search_done(None, "zeroconf missing")
        self.assertEqual(logged[-1][1], "warning")
        self.assertEqual(window.status_var.get(), "Устройства в сети не найдены")

    def test_broken_esptool_package_is_removed_and_action_retried_once(self) -> None:
        # Лог форумчанина (Windows): зависимости esptool не доставлены в _contrib -> ошибка импорта
        log = [
            'Building .pio\\build\\Samovar\\bootloader.bin\n',
            'Traceback (most recent call last):\n',
            '  File "C:\\Users\\Admin\\.platformio\\packages\\tool-esptoolpy\\esptool.py", line 41, in <module>\n',
            '    import esptool\n',
            '  File "C:\\Users\\Admin\\.platformio\\packages\\tool-esptoolpy\\esptool\\bin_image.py", line 16, in <module>\n',
            '    from intelhex import HexRecordError, IntelHex\n',
            "ImportError: cannot import name 'HexRecordError' from 'intelhex' (unknown location)\n",
            '*** [.pio\\build\\Samovar\\bootloader.bin] Error 1\n',
        ]
        self.assertEqual(configurator.broken_esptool_package(log), "C:\\Users\\Admin\\.platformio\\packages\\tool-esptoolpy")
        self.assertEqual(
            configurator.broken_esptool_package([
                '  File "/home/u/.platformio/packages/tool-esptoolpy@2.40900.250804/esptool/bin_image.py", line 16\n',
                "ModuleNotFoundError: No module named 'intelhex'\n",
            ]),
            "/home/u/.platformio/packages/tool-esptoolpy@2.40900.250804",
        )
        # ошибка импорта без трассировки esptool и трассировка esptool без ошибки импорта - не наш случай
        self.assertIsNone(configurator.broken_esptool_package(["ImportError: x\n"]))
        self.assertIsNone(configurator.broken_esptool_package([log[2], "OSError: boom\n"]))

        with tempfile.TemporaryDirectory() as root:
            package = Path(root) / "tool-esptoolpy"
            package.mkdir()
            (package / "esptool.py").write_text("", encoding="utf-8")
            (package / "_contrib" / "intelhex").mkdir(parents=True)
            configurator.remove_broken_esptool(str(package))
            self.assertFalse(package.exists())
            # чужую папку удалять нельзя
            other = Path(root) / "framework-arduinoespressif32"
            other.mkdir()
            (other / "esptool.py").write_text("", encoding="utf-8")
            with self.assertRaisesRegex(configurator.ConfigError, "не похожа на пакет esptool"):
                configurator.remove_broken_esptool(str(other))
            self.assertTrue(other.exists())
            empty = Path(root) / "tool-esptoolpy@1"
            empty.mkdir()
            with self.assertRaises(configurator.ConfigError):
                configurator.remove_broken_esptool(str(empty))

        class Variable:
            def __init__(self):
                self.value = ""

            def set(self, value):
                self.value = value

            def get(self):
                return self.value

        with tempfile.TemporaryDirectory() as root:
            package = Path(root) / "tool-esptoolpy"
            package.mkdir()
            (package / "esptool.py").write_text("", encoding="utf-8")
            traceback_line = '  File "{}", line 41, in <module>\n'.format(package / "esptool.py")
            logged, errors, started = [], [], []
            window = configurator.ConfiguratorWindow.__new__(configurator.ConfiguratorWindow)
            window.stop_requested = False
            window.active_action = "upload"
            window.active_port_network = False
            window.action_started = 0.0
            window.process = object()
            window.busy = True
            window.esptool_repaired = None
            window.partial_line = ""
            window.recent_lines = [log[6]]
            window.action_lines = [traceback_line, log[6]]
            window.status_var = Variable()
            window._set_busy = lambda busy, action: None
            window._append_log = lambda text, tag=None: logged.append((text, tag))
            window.start_action = lambda action: started.append(action)
            window.messagebox = type("Messages", (), {"showerror": lambda _, title, message: errors.append(message)})()

            window._finish_action(1)
            self.assertFalse(package.exists())
            self.assertEqual(started, ["upload"])
            self.assertEqual(errors, [])  # окно с ошибкой не показываем: операция повторяется сама
            self.assertEqual(logged[-1][1], "warning")
            self.assertIn("установит пакет заново", logged[-1][0])
            self.assertEqual(window.esptool_repaired, str(package))

            # та же папка сломана снова после переустановки: второй раз не удаляем и не зацикливаемся
            package.mkdir()
            (package / "esptool.py").write_text("", encoding="utf-8")
            window.busy, window.process, window.active_action = True, object(), "upload"
            window._finish_action(1)
            self.assertTrue(package.exists())
            self.assertEqual(started, ["upload"])
            self.assertEqual(len(errors), 1)

            # монитор порта не повторяем никогда
            window.busy, window.process, window.active_action = True, object(), "monitor"
            window.esptool_repaired = None
            window._finish_action(1)
            self.assertTrue(package.exists())
            self.assertEqual(started, ["upload"])

        note = inspect.getsource(configurator.ConfiguratorWindow._note_output_line)
        self.assertIn("self.action_lines.append(line)", note)

    def test_process_output_is_shown_in_chunks_before_newline(self) -> None:
        # PlatformIO через канал печатает «Downloading 0% 10% …» без перевода строки: построчное
        # чтение молчало до конца загрузки тулчейна, и батник выглядел зависшим.
        import io
        import queue as queue_module

        class Process:
            def __init__(self, payload: bytes):
                self.stdout = io.TextIOWrapper(io.BufferedReader(io.BytesIO(payload)), encoding="utf-8")

            def wait(self):
                return 0

        window = configurator.ConfiguratorWindow.__new__(configurator.ConfiguratorWindow)
        window.output_queue = queue_module.Queue()
        window._read_process_output(Process(
            "Tool Manager: Installing espressif/toolchain-xtensa-esp32 @ 8.4.0\nDownloading 0% 10%".encode("utf-8")
        ))
        items = []
        while True:
            item = window.output_queue.get_nowait()
            items.append(item)
            if item[0] == "done":
                break
        self.assertEqual(items[-1], ("done", 0))
        self.assertEqual("".join(value for kind, value in items[:-1]), "Tool Manager: Installing espressif/toolchain-xtensa-esp32 @ 8.4.0\nDownloading 0% 10%")
        self.assertTrue(all(kind == "chunk" for kind, _ in items[:-1]))

        logged = []
        window.recent_lines, window.action_lines, window.partial_line = [], [], ""
        window.install_hint_shown = False
        window._append_log = lambda text, tag=None: logged.append((text, tag))
        window._note_output("Tool Manager: Installing espressif/toolchain-xtensa-esp32 @ 8.4.0\nDownloading 0% 10%")
        self.assertEqual(logged[0][0], "Tool Manager: Installing espressif/toolchain-xtensa-esp32 @ 8.4.0\n")
        self.assertEqual(logged[1], (configurator.PACKAGE_INSTALL_HINT, "warning"))
        self.assertEqual(logged[2][0], "Downloading 0% 10%")  # видно сразу, без ожидания перевода строки
        self.assertEqual(window.recent_lines, ["Tool Manager: Installing espressif/toolchain-xtensa-esp32 @ 8.4.0\n"])
        self.assertEqual(window.partial_line, "Downloading 0% 10%")
        window._note_output(" 20%\nTool Manager: Installing platformio/tool-scons @ 4.4\n")
        self.assertEqual(window.recent_lines[-2:], ["Downloading 0% 10% 20%\n", "Tool Manager: Installing platformio/tool-scons @ 4.4\n"])
        self.assertEqual(window.partial_line, "")
        self.assertEqual(sum(1 for text, _ in logged if text == configurator.PACKAGE_INSTALL_HINT), 1)  # подсказка один раз
        # незавершённая строка при завершении процесса тоже попадает в журнал ошибок
        finish = inspect.getsource(configurator.ConfiguratorWindow._finish_action)
        self.assertIn("if self.partial_line:\n            self._note_output_line(self.partial_line)", finish)
        drain = inspect.getsource(configurator.ConfiguratorWindow._drain_output)
        self.assertIn('if kind == "chunk":\n                    self._note_output(value)', drain)

    def test_upload_to_network_port_warns_when_firmware_option_disabled(self) -> None:
        class Variable:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

        answers = iter((False, True))
        prompts = []
        started = []
        saved = []
        window = configurator.ConfiguratorWindow.__new__(configurator.ConfiguratorWindow)
        window.busy = False
        window.config = type("Config", (), {"project_root": Path("/tmp/Samovar")})()
        window.pio_executable = "pio.exe"
        window.board_var = Variable("LILYGO")
        window.port_var = Variable("192.168.1.37 — samovar (Wi-Fi)")
        window.bool_vars = {"USE_UPDATE_OTA": Variable(False)}
        window.messagebox = type(
            "Messages",
            (),
            {
                "askyesno": lambda _, title, message: (prompts.append(title), next(answers))[1],
                "showerror": lambda _, title, message: self.fail(message),
            },
        )()
        window.save = lambda **kwargs: saved.append(kwargs) or True
        window._start_process = lambda command, action: started.append((command, action))

        window.start_action("upload")
        self.assertEqual(started, [])
        self.assertEqual(saved, [])
        window.start_action("upload")
        self.assertEqual(len(prompts), 2)
        self.assertIn("Wi-Fi", prompts[0])
        self.assertEqual(saved, [{"show_success": False}])
        self.assertEqual(
            started,
            [(
                ["pio.exe", "run", "-e", "Samovar", "-t", "upload", "--upload-port", "192.168.1.37"],
                "upload",
            )],
        )
        self.assertTrue(window.active_port_network)

        # LittleFS по сети без вопроса про USE_UPDATE_OTA; по COM-порту - тоже без вопроса
        window.start_action("uploadfs")
        self.assertEqual(len(prompts), 2)
        self.assertEqual(started[-1][0][5], "uploadfs")
        window.port_var = Variable("COM7")
        window.start_action("upload")
        self.assertEqual(len(prompts), 2)
        self.assertEqual(started[-1][0][-1], "COM7")
        self.assertFalse(window.active_port_network)

    def test_shortcut_action_is_layout_independent(self) -> None:
        self.assertEqual(configurator.shortcut_action("Cyrillic_es", 54, "linux"), "copy")
        self.assertEqual(configurator.shortcut_action("Cyrillic_EM", 55, "linux"), "paste")
        self.assertEqual(configurator.shortcut_action("Cyrillic_ef", 38, "darwin"), "select_all")
        self.assertEqual(configurator.shortcut_action("Cyrillic_yeru", 39, "linux"), "save")
        self.assertEqual(configurator.shortcut_action("c", 54, "linux"), "copy")
        self.assertEqual(configurator.shortcut_action("Cyrillic_es", 67, "win32"), "copy")
        self.assertEqual(configurator.shortcut_action("Cyrillic_em", 86, "win32"), "paste")
        self.assertEqual(configurator.shortcut_action("Cyrillic_ef", 65, "win32"), "select_all")
        self.assertIsNone(configurator.shortcut_action("q", 24, "linux"))
        self.assertIsNone(configurator.shortcut_action("Cyrillic_shorti", 81, "win32"))
        # AltGr (Control+Alt) в Windows - ввод символа, а не сочетание
        self.assertIsNone(configurator.shortcut_action("aogonek", 65, "win32", state=0x20004))
        self.assertIsNone(configurator.shortcut_action("c", 54, "linux", state=0xC))
        self.assertEqual(configurator.shortcut_action("c", 67, "win32", state=0x4), "copy")

    def test_edit_menu_is_installed_on_every_text_control(self) -> None:
        build = inspect.getsource(configurator.ConfiguratorWindow._build)
        self.assertIn('self._install_edit_menu(self.log, "readonly", on_clear=self.clear_log)', build)
        self.assertIn('self._install_edit_menu(self.port_combo, "entry")', build)
        self.assertIn('self._install_edit_menu(self.password_entry, "entry")', build)
        self.assertIn('self._install_edit_menu(entry, "entry")', build)
        add_entry = inspect.getsource(configurator.ConfiguratorWindow._add_entry)
        self.assertIn('self._install_edit_menu(entry, "entry")', add_entry)
        monitor = inspect.getsource(configurator.ConfiguratorWindow.open_monitor)
        self.assertIn('EditMenu(self.monitor_log, "readonly", on_clear=self.clear_monitor)', monitor)
        self.assertIn('EditMenu(self.monitor_input, "entry")', monitor)
        editor = inspect.getsource(configurator.FileEditorWindow.__init__)
        self.assertIn('EditMenu(self.editor, "text", on_save=self.save)', editor)
        menu = inspect.getsource(configurator.EditMenu.__init__)
        for label in ("Вырезать", "Копировать", "Вставить", "Выделить всё", "Отменить", "Повторить"):
            self.assertIn('label="{}"'.format(label), menu)
        self.assertIn('widget.bind("<Button-3>", self.popup', menu)
        self.assertIn('widget.bind("<Control-KeyPress>", self.key', menu)

    def test_log_lines_are_classified_for_colouring(self) -> None:
        cases = {
            "> pio run -e Samovar -t upload": "command",
            "src/lua.h:1442:5: error: expected ';'": "error",
            "==== [FAILED] Took 12.34 seconds ====": "error",
            "Samovar.ino:12:3: warning: unused variable": "warning",
            "==== [SUCCESS] Took 61.2 seconds ====": "ok",
            "Compiling .pio/build/Samovar/src/Samovar.ino.cpp.o": None,
            "build_flags = -Werror=return-type": None,
        }
        for line, expected in cases.items():
            self.assertEqual(configurator.log_line_tag(line), expected, line)

    def test_user_preferences_round_trip_and_ignore_garbage(self) -> None:
        path = Path(self.temporary.name) / "prefs.json"
        configurator.save_user_prefs({"port": "192.168.1.37 — samovar (Wi-Fi)", "geometry": "1280x780+10+10"}, path)
        self.assertEqual(
            configurator.load_user_prefs(path),
            {"port": "192.168.1.37 — samovar (Wi-Fi)", "geometry": "1280x780+10+10"},
        )
        path.write_text("{not json", encoding="utf-8")
        self.assertEqual(configurator.load_user_prefs(path), {})
        path.write_text('{"address": 5, "port": "COM3", "geometry": "abc"}', encoding="utf-8")
        self.assertEqual(configurator.load_user_prefs(path), {"port": "COM3"})
        self.assertEqual(configurator.load_user_prefs(path.with_name("missing.json")), {})

    def test_failed_action_reports_recent_log_lines_and_ota_hint(self) -> None:
        class Variable:
            def __init__(self):
                self.value = ""

            def set(self, value):
                self.value = value

            def get(self):
                return self.value

        logged = []
        errors = []
        window = configurator.ConfiguratorWindow.__new__(configurator.ConfiguratorWindow)
        window.stop_requested = False
        window.active_action = "upload"
        window.active_port_network = True
        window.action_started = 0.0
        window.process = object()
        window.busy = True
        window.recent_lines = ["[ERROR]: No response from the ESP\n", "*** [upload] Error 1\n"]
        window.action_lines = list(window.recent_lines)
        window.partial_line = ""
        window.esptool_repaired = None
        window.status_var = Variable()
        window._set_busy = lambda busy, action: None
        window._append_log = lambda text, tag=None: logged.append((text, tag))
        window.messagebox = type(
            "Messages", (), {"showerror": lambda _, title, message: errors.append(message)}
        )()

        window._finish_action(1)
        self.assertFalse(window.busy)
        self.assertIsNone(window.process)
        self.assertEqual(window.active_action, "")
        self.assertEqual(logged[0][1], "error")
        self.assertEqual(logged[1], (configurator.OTA_FAILURE_HINT, "warning"))
        self.assertIn("No response from the ESP", errors[0])
        self.assertIn("Прошивка", errors[0])
        self.assertEqual(window.status_var.get(), "Прошивка: ошибка")
        self.assertFalse(window.active_port_network)

        logged.clear()
        window.busy = True
        window.process = object()
        window.active_action = "upload"
        window.stop_requested = True
        window._finish_action(-15)
        self.assertEqual(errors, errors[:1])
        self.assertIn("остановлено пользователем", logged[0][0])

    def test_full_flash_erase_requires_confirmation(self) -> None:
        answers = iter((False, True))
        prompts = []
        actions = []
        window = configurator.ConfiguratorWindow.__new__(configurator.ConfiguratorWindow)
        window.messagebox = type(
            "Messages",
            (),
            {
                "askyesno": lambda _, title, message: (
                    prompts.append((title, message)), next(answers)
                )[1]
            },
        )()
        window.start_action = actions.append

        window.start_flash_erase()
        self.assertEqual(actions, [])
        window.start_flash_erase()
        self.assertEqual(actions, ["erase"])
        self.assertIn("прошивка", prompts[0][1])
        self.assertIn("LittleFS", prompts[0][1])
        self.assertIn("настройки", prompts[0][1])

        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn('text="Полностью очистить флеш"', source)
        self.assertIn("self.erase_button.configure(state=state)", source)

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
            configurator.pio_command("pio.exe", "ESP32 DevKit", "erase", "COM7"),
            ["pio.exe", "run", "-e", "Samovar", "-t", "erase", "--upload-port", "COM7"],
        )
        with self.assertRaisesRegex(configurator.ConfigError, "Выберите порт или устройство в сети"):
            configurator.pio_command("pio.exe", "ESP32 DevKit", "upload", "  ")

    def test_serial_monitor_does_not_reset_esp(self) -> None:
        monitor_source = inspect.getsource(configurator.run_serial_monitor)
        action_source = inspect.getsource(configurator.ConfiguratorWindow.start_action)
        self.assertIn("open_serial_without_reset(serial, port)", monitor_source)
        self.assertIn("forward_serial_commands", monitor_source)
        self.assertIn("serial_monitor_command(", action_source)
        self.assertIn("pio_python_executable", action_source)
        process_source = inspect.getsource(configurator.ConfiguratorWindow._start_process)
        self.assertIn('stdin=subprocess.PIPE if action == "monitor" else None', process_source)

    def test_main_window_device_controls_and_ip_gate(self) -> None:
        source = inspect.getsource(configurator.ConfiguratorWindow._build)
        for token in (
            'text="Перезагрузить ESP"',
            'text="Редактор файлов"',
            'self.port_var.trace_add("write", lambda *_: self._port_changed())',
        ):
            self.assertIn(token, source)
        # Редактор файлов недоступен, пока нет адреса устройства (см. _port_changed)
        self.assertIn("self._port_changed()", inspect.getsource(configurator.ConfiguratorWindow._load))
        self.assertNotIn('text="Получить IP"', source)
        monitor_source = inspect.getsource(configurator.ConfiguratorWindow.open_monitor)
        self.assertIn('text="Получить IP"', monitor_source)
        for label in ("Перезагрузить ESP", "Редактор файлов"):
            self.assertNotIn(label, monitor_source)

        self.assertEqual(
            configurator.extract_samovar_ip("noise\nSAMOVAR:IP=192.168.1.37\n"),
            "192.168.1.37",
        )
        self.assertEqual(
            configurator.extract_samovar_ip("SAMOVAR:IP=10.0.0.8\n"),
            "10.0.0.8",
        )
        self.assertIsNone(configurator.extract_samovar_ip("SAMOVAR:IP=999.1.2.3\n"))
        self.assertIsNone(configurator.extract_samovar_ip("SAMOVAR:IP=0.0.0.0\n"))

    def test_reboot_and_monitor_commands_use_selected_port(self) -> None:
        self.assertEqual(
            configurator.esptool_reboot_command("pio.exe", "COM7"),
            ["pio.exe", "pkg", "exec", "-p", "tool-esptoolpy", "--", "esptool.py", "--port", "COM7", "run"],
        )
        self.assertEqual(
            configurator.serial_monitor_command(
                "C:/Python/python.exe", MODULE_PATH, "/dev/cu.usbserial-1"
            ),
            [
                "C:/Python/python.exe", str(MODULE_PATH),
                "--serial-monitor", "/dev/cu.usbserial-1",
            ],
        )
        with self.assertRaisesRegex(configurator.ConfigError, "Выберите порт или устройство в сети"):
            configurator.esptool_reboot_command("pio.exe", " ")

        result = type(
            "Result", (), {
                "returncode": 0,
                "stdout": '{"python_exe":{"title":"Python Executable","value":"C:/pio/python.exe"}}',
                "stderr": "",
            },
        )()
        with mock.patch.object(configurator.subprocess, "run", return_value=result) as run:
            self.assertEqual(configurator.pio_python_executable("pio.exe"), "C:/pio/python.exe")
        run.assert_called_once_with(
            ["pio.exe", "system", "info", "--json-output"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )

        # Сброс ESP32 = «DTR снят, RTS выставлен». Порт открывается без прохода через это состояние.
        class FakeSerial:
            def __init__(self):
                self.events = []
                self.is_open = False
                self.fd = 7
                self.exclusive = False

            @property
            def dtr(self):
                return self._dtr

            @dtr.setter
            def dtr(self, value):
                self.events.append(("dtr", value, self.is_open))

            @property
            def rts(self):
                return self._rts

            @rts.setter
            def rts(self, value):
                self.events.append(("rts", value, self.is_open))

            def open(self):
                self.is_open = True
                self.events.append(("open",))

        class SerialModule:
            Serial = FakeSerial

            def __init__(self):
                self.calls = []

            def serial_for_url(self, port, baud, do_not_open=False):
                self.calls.append((port, baud, do_not_open))
                self.instance = FakeSerial()
                return self.instance

        module = SerialModule()
        with mock.patch.object(configurator.os, "name", "nt"):
            connection = configurator.open_serial_without_reset(module, "COM7")
        self.assertEqual(module.calls, [("COM7", 115200, True)])
        self.assertTrue(connection.exclusive)
        # Windows: драйвер опускает линии при закрытии (DTR первым = сброс), поэтому до открытия
        # просим «DTR выставлен, RTS снят» - из любого стартового состояния меняется ровно одна
        # линия через безопасную сторону; после открытия снимаем DTR, закрытие ничего не трогает.
        self.assertEqual(
            connection.events,
            [("dtr", True, False), ("rts", False, False), ("open",), ("dtr", False, True)],
        )

        module = SerialModule()
        termios_calls = []
        fake_termios = types.SimpleNamespace(
            HUPCL=0x4000, TCSANOW="TCSANOW", error=OSError,
            tcgetattr=lambda fd: [0, 0, 0x4000 | 0x0B00, 0],
            tcsetattr=lambda fd, when, attrs: termios_calls.append((fd, when, list(attrs))),
        )
        with mock.patch.object(configurator.os, "name", "posix"), \
                mock.patch.dict(sys.modules, {"termios": fake_termios}):
            connection = configurator.open_serial_without_reset(module, "/dev/cu.usbserial-1")
        # macOS/Linux: линии не опускаем вовсе и снимаем HUPCL - ядро не опустит их при закрытии;
        # следующее открытие ничего не переключает, а сбрасывает плату только переключение.
        self.assertEqual(connection.events, [("dtr", True, False), ("rts", True, False), ("open",)])
        self.assertEqual(termios_calls, [(7, "TCSANOW", [0, 0, 0x0B00, 0])])
        monitor_source = inspect.getsource(configurator.run_serial_monitor)
        self.assertIn("BOOT_BANNER in data", monitor_source)
        self.assertIn("перезагрузилась при открытии порта", monitor_source)
        with self.assertRaisesRegex(configurator.ConfigError, "только по USB"):
            configurator.open_serial_without_reset(module, "192.168.1.37")

        class Connection:
            def __init__(self):
                self.writes = []

            def write(self, payload):
                self.writes.append(payload)

        connection = Connection()
        configurator.forward_serial_commands(
            connection, ["SAMOVAR:IP?\n", "second command\n"]
        )
        self.assertEqual(
            connection.writes,
            [b"SAMOVAR:IP?\n", b"second command\n"],
        )

    def test_compressed_editor_files_round_trip_and_upload_to_existing_gzip(self) -> None:
        text = "<html>Привет</html>\n"
        packed = gzip.compress(text.encode("utf-8"), mtime=0)
        self.assertEqual(configurator.decode_remote_text("/index.htm.gz", packed), text)
        self.assertEqual(
            gzip.decompress(configurator.encode_remote_text("/index.htm.gz", text)).decode("utf-8"),
            text,
        )

        target, payload = configurator.prepare_remote_upload(
            "index.htm", text.encode("utf-8"), ["/index.htm.gz", "/style.css.gz"]
        )
        self.assertEqual(target, "/index.htm.gz")
        self.assertEqual(gzip.decompress(payload).decode("utf-8"), text)

        target, payload = configurator.prepare_remote_upload(
            "program.txt", b"first\nsecond\n", ["/index.htm.gz"]
        )
        self.assertEqual(target, "/program.txt")
        self.assertEqual(payload, b"first\nsecond\n")

    def test_syntax_highlighting_covers_supported_text_formats(self) -> None:
        def spans(name, content):
            return [(tag, content[start:end]) for tag, start, end in configurator.syntax_spans(name, content)]

        # ключевые слова внутри строк и комментариев не подсвечиваются, // в адресе - не комментарий
        self.assertEqual(
            spans("script.lua", 'local s = "if end" -- if\nreturn 0x1F'),
            [("keyword", "local"), ("string", '"if end"'), ("comment", "-- if"), ("keyword", "return"), ("number", "0x1F")],
        )
        self.assertEqual(
            spans("app.js", 'const u = "http://x"; // c'),
            [("keyword", "const"), ("string", '"http://x"'), ("comment", "// c")],
        )
        self.assertIn(("comment", "--[[ long\ncomment ]]"), spans("script.lua", "x = 1 --[[ long\ncomment ]] y"))
        self.assertIn(("string", "[[ ( ]]"), spans("script.lua", "s = [[ ( ]]"))
        self.assertEqual(
            spans("style.css", ".x:hover { color: #fff; margin:-2px }"),
            [("property", "color"), ("number", "#fff"), ("property", "margin"), ("number", "-2px")],
        )
        self.assertEqual(
            spans("data.json", '{"a": [1, true, "s"]}'),
            [("property", '"a"'), ("number", "1"), ("keyword", "true"), ("string", '"s"')],
        )
        # HTML: имена тегов, атрибуты, значения, вложенные script/style на их языках
        html = spans("page.htm", '<!-- c --><div class="x">t</div><script>var a = "</div>";</script><style>.a{color:red}</style>')
        self.assertEqual(html[:6], [
            ("comment", "<!-- c -->"), ("tag", "<div"), ("property", "class"), ("string", '"x"'), ("tag", ">"), ("tag", "</div"),
        ])
        self.assertIn(("keyword", "var"), html)
        self.assertIn(("string", '"</div>"'), html)
        self.assertIn(("property", "color"), html)
        self.assertEqual(configurator.syntax_spans("notes.txt", "plain text 42"), [])
        self.assertEqual(configurator.syntax_spans("app.js.gz", "let x"), [("keyword", 0, 3)])
        self.assertTrue(configurator.is_text_remote_file("/data.json"))
        self.assertTrue(configurator.is_text_remote_file("/program.csv"))

    def test_editor_syntax_check_reports_first_problem_with_line(self) -> None:
        cases = [
            ("a.lua", "if x then\n  print(1)\n", (1, "нет «end» для «if» (строка 1)")),
            ("a.lua", "function f() end end", (1, "лишний «end»")),
            ("a.lua", "repeat x() until y", None),
            ("a.lua", 'for i=1,3 do print("end") end', None),
            ("a.lua", 'local s = "(("', None),
            ("a.lua", "--[==[ x ]] ]==] ok = 1", None),
            ("a.js", "f(1, [2)", (1, "лишняя закрывающая скобка «)»")),
            ("a.js", "let a = 1;\nfunction f() {\n", (2, "не закрыта скобка «{»")),
            ("a.js", "/* open", (1, "не закрыт комментарий /*")),
            ("a.js", "'unterminated", (1, "не закрыта строка")),
            ("a.json", '{"a": }', (1, "Expecting value")),
            ("a.json", '{"a": [1]}', None),
            ("a.htm", "<script>\nif (x {\n</script>", (2, "не закрыта скобка «{»")),
            ("a.htm", "<!-- x", (1, "не закрыт комментарий <!--")),
            ("a.txt", "anything ((", None),
        ]
        for name, text, expected in cases:
            self.assertEqual(configurator.check_syntax(name, text), expected, (name, text))
        self.assertEqual(configurator.matching_bracket("a(b[c])d", 1), 6)
        self.assertEqual(configurator.matching_bracket("a(b[c])d", 6), 1)
        self.assertIsNone(configurator.matching_bracket("a(b", 1))
        self.assertIsNone(configurator.matching_bracket("abc", 1))
        self.assertEqual(configurator.web_editor_url("192.168.1.37"), "http://192.168.1.37/edit")
        self.assertEqual(
            configurator.web_editor_url("samovar.local", "/файл.lua"),
            "http://samovar.local/edit?file=/%D1%84%D0%B0%D0%B9%D0%BB.lua",
        )
        # /edit прошивки не распаковывает gzip: для сжатых файлов кнопка гаснет
        self.assertTrue(configurator.web_editor_supports("/script.lua"))
        self.assertFalse(configurator.web_editor_supports("/index.htm.gz"))
        self.assertFalse(configurator.web_editor_supports("/INDEX.HTM.GZ"))
        self.assertFalse(configurator.web_editor_supports(None))
        editor = inspect.getsource(configurator.FileEditorWindow.__init__)
        self.assertIn('text="Веб-редактор (/edit)"', editor)
        self.assertIn('self.web_button = ttk.Button(', editor)
        load_text = inspect.getsource(configurator.FileEditorWindow._load_text)
        self.assertIn('self.web_button.configure(state="normal" if web_editor_supports(path) else "disabled")', load_text)
        self.assertIn("self.gutter = tk.Text(", editor)
        self.assertIn('self.editor.bind("<KeyRelease>", self._edited)', editor)

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
            'text="Порт или адрес"',
            'text="Устройство"',
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

        self.assertEqual(errors, [("Ошибка запуска", "Выберите порт или устройство в сети")])
        popen.assert_not_called()

    def test_unc_project_path_detection(self) -> None:
        self.assertTrue(configurator.is_unc_path(Path(r"\\Mac\Home\Documents\Samovar-7.00")))
        self.assertTrue(configurator.is_unc_path(Path("//server/share/Samovar-7.00")))
        self.assertFalse(configurator.is_unc_path(Path(r"C:\Users\gala\Documents\Samovar-7.00")))
        self.assertFalse(configurator.is_unc_path(Path("/Users/kosoj/Documents/Samovar-7.00")))

    def test_windows_unc_path_stops_builds_before_save(self) -> None:
        for action in ("upload", "uploadfs", "erase"):
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
