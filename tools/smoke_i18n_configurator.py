#!/usr/bin/env python3
"""Проверяет мультиязычность конфигуратора: правила в исходнике, словари и механизм перевода.

Без Tk: исходник разбирается через ast/tokenize, окна подменяются заглушками.
`--dump-keys` печатает скелет словаря (все ключи tr()/N_() и макросы описаний) для переводчика.
"""

import ast
import contextlib
import importlib.util
import io
import json
import re
import shutil
import sys
import tempfile
import tokenize
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "samovar_configurator.py"
DICTIONARY_DIR = ROOT / "i18n" / "configurator"
CYRILLIC = re.compile("[А-Яа-яЁё]")
PLACEHOLDER_RE = re.compile(r"\{[^{}]*\}")
KEEP_RE = re.compile(r"i18n-keep:\s*\S")
TOP_KEYS = {"language_name", "strings", "macro_descriptions"}


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[name]
        raise
    return module


configurator = load_module(MODULE_PATH, "samovar_configurator_i18n")


# ---------------------------------------------------------------- правила исходника
def keep_lines(source: str):
    lines = set()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT and KEEP_RE.search(token.string):
            lines.add(token.start[0])
    return lines


def analyze_source(source: str):
    """(ключи tr()/N_() в порядке появления без повторов, список нарушений)."""
    tree = ast.parse(source)
    marked = keep_lines(source)
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                docstrings.add(first.value)
    keys = []
    problems = []

    def is_label_call(node):
        return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("tr", "N_")

    for node in ast.walk(tree):
        if is_label_call(node):
            name = node.func.id
            if len(node.args) != 1 or node.keywords:
                problems.append("строка {}: {}() принимает ровно один позиционный аргумент".format(node.lineno, name))
                continue
            argument = node.args[0]
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                if not CYRILLIC.search(argument.value):
                    problems.append("строка {}: ключ {}() без кириллицы: {!r}".format(node.lineno, name, argument.value))
                elif argument.value not in keys:
                    keys.append(argument.value)
            elif isinstance(argument, (ast.JoinedStr, ast.BinOp)) or (
                isinstance(argument, ast.Call)
                and isinstance(argument.func, ast.Attribute) and argument.func.attr == "format"
            ):
                problems.append(
                    "строка {}: аргумент {}() должен быть литералом, а не f-строкой, склейкой или format()".format(
                        node.lineno, name)
                )
            elif isinstance(argument, ast.Constant):
                problems.append("строка {}: аргумент {}() не строка".format(node.lineno, name))
            if name == "tr":
                scope = node
                while scope in parents and not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                    scope = parents[scope]
                if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                    problems.append(
                        "строка {}: tr() вне функции выполняется при импорте, до выбора языка (нужен N_)".format(node.lineno)
                    )
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str) and CYRILLIC.search(node.value)):
            continue
        if node in docstrings:
            continue
        parent = parents.get(node)
        if is_label_call(parent) and parent.args and parent.args[0] is node:
            continue
        if any(line in marked for line in range(node.lineno, node.end_lineno + 1)):
            continue
        problems.append("строка {}: русский литерал вне tr/N_ без i18n-keep: {!r}".format(node.lineno, node.value[:50]))
    return keys, problems


# ---------------------------------------------------------------- словари
class RecordingDescriptions(dict):
    """Словарь описаний, который запоминает, какие макросы у него спрашивали."""

    def __init__(self, data=None, answer_any=False):
        super().__init__(data or {})
        self.requested = []
        self.answer_any = answer_any

    def __getitem__(self, key):
        self.requested.append(key)
        if self.answer_any:
            return "x"
        return super().__getitem__(key)

    def __contains__(self, key):
        raise AssertionError("macro_description должен обращаться к словарю через [], а не через in")


def descriptions_with(module, i18n_dir: Path, code: str, answer_any: bool = False):
    """(описания, запрошенные макросы) для языка code; словарь описаний подменяется записывающим."""
    module.set_language(code, i18n_dir)
    try:
        recorder = RecordingDescriptions(module._macro_descriptions, answer_any)
        with mock.patch.object(module, "_macro_descriptions", recorder):
            return module.SamovarConfig(ROOT).descriptions(), recorder.requested
    finally:
        module.set_language("ru")


def required_macros(module):
    """Макросы, для которых описания нужны в macro_descriptions; список берётся из настоящего descriptions()."""
    with tempfile.TemporaryDirectory() as directory:
        write_dictionary(Path(directory), "xx", "Pseudo", pseudo_strings(SOURCE_KEYS), {})
        _, requested = descriptions_with(module, Path(directory), "xx", answer_any=True)
    return list(dict.fromkeys(requested))


def write_dictionary(directory: Path, code: str, name: str, strings: dict, macros: dict, **extra) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    data = {"language_name": name, "strings": strings, "macro_descriptions": macros}
    data.update(extra)
    path = directory / (code + ".json")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def dictionary_problems(path: Path, keys, macros):
    """Нарушения в словаре path относительно ключей исходника и макросов описаний."""

    def reject_duplicates(pairs):
        names = [name for name, _ in pairs]
        duplicated = sorted({name for name in names if names.count(name) > 1})
        if duplicated:
            problems.append("повторяются ключи JSON: {}".format(duplicated))
        return dict(pairs)

    problems = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates)
    except ValueError as error:
        return ["некорректный JSON: {}".format(error)]
    if not isinstance(data, dict) or set(data) != TOP_KEYS:
        return ["верхний уровень должен состоять ровно из {}".format(sorted(TOP_KEYS))]
    if not isinstance(data["language_name"], str) or not data["language_name"].strip():
        problems.append("language_name пуст")
    strings, macro_texts = data["strings"], data["macro_descriptions"]
    if not isinstance(strings, dict) or not isinstance(macro_texts, dict):
        return problems + ["strings и macro_descriptions должны быть объектами"]
    for key in keys:
        if key not in strings:
            problems.append("нет перевода ключа {!r}".format(key))
    for key in strings:
        if key not in keys:
            problems.append("лишний ключ {!r}".format(key))
    for key, value in strings.items():
        if not isinstance(value, str) or not value.strip():
            problems.append("пустой перевод {!r}".format(key))
        elif CYRILLIC.search(value):
            problems.append("кириллица в переводе {!r}: {!r}".format(key, value))
        elif PLACEHOLDER_RE.findall(key) != PLACEHOLDER_RE.findall(value):
            problems.append("не совпадают плейсхолдеры {!r}: {!r}".format(key, value))
    for macro in macros:
        if macro not in macro_texts:
            problems.append("нет описания настройки {}".format(macro))
    for macro, value in macro_texts.items():
        if macro not in macros:
            problems.append("лишнее описание настройки {}".format(macro))
        if not isinstance(value, str) or not value.strip():
            problems.append("пустое описание настройки {}".format(macro))
        elif CYRILLIC.search(value):
            problems.append("кириллица в описании {}: {!r}".format(macro, value))
    return problems


def real_dictionary_problems(module, path: Path, keys, macros):
    """Поведенческая часть: descriptions() на этом языке даёт те же настройки, что на русском, без кириллицы."""
    problems = dictionary_problems(path, keys, macros)
    if problems:
        return problems
    russian, _ = descriptions_with(module, path.parent, "ru")
    translated, requested = descriptions_with(module, path.parent, path.stem)
    data = json.loads(path.read_text(encoding="utf-8"))
    if set(translated) != set(russian):
        problems.append("набор описаний отличается от русского: {}".format(sorted(set(translated) ^ set(russian))))
    for macro, text in translated.items():
        if CYRILLIC.search(text):
            problems.append("кириллица в описании {} после перевода".format(macro))
    for macro in data["macro_descriptions"]:
        if macro not in requested:
            problems.append("описание {} не используется descriptions()".format(macro))
    return problems


LANG_FILE_RE = re.compile(r"^lang_([a-z][a-z0-9_]{0,15})\.h$")


def missing_dictionaries(project_root: Path, dictionary_dir: Path):
    """Коды неисходных языков прошивки (lang_<код>.h), для которых нет словаря конфигуратора <код>.json."""
    codes = []
    for path in sorted(project_root.glob("lang_*.h")):
        found = LANG_FILE_RE.match(path.name)
        if found and found.group(1) != "ru" and not (dictionary_dir / (found.group(1) + ".json")).is_file():
            codes.append(found.group(1))
    return codes


def pseudo_strings(keys):
    return {key: CYRILLIC.sub("x", key) for key in keys}


SOURCE_KEYS, SOURCE_PROBLEMS = analyze_source(MODULE_PATH.read_text(encoding="utf-8"))
REQUIRED_MACROS = required_macros(configurator)


class Variable:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value

    def trace_add(self, mode, callback):
        self.callback = callback


class FakeToolkit:
    """Подмена tkinter для настоящего ConfiguratorWindow.__init__ и main().

    Переменные хранят значение и зовут подписчиков, как настоящие; виджеты - MagicMock,
    запоминающие вид и аргументы создания (kind, kwargs); messagebox.showerror складывает вызовы в errors.
    """

    def __init__(self):
        self.widgets = []
        self.errors = []
        self.root = mock.MagicMock(name="root")
        toolkit = self

        class FakeVariable:
            def __init__(self, master=None, value=""):
                self.value = value
                self.callbacks = []

            def get(self):
                return self.value

            def set(self, value):
                self.value = value
                for callback in self.callbacks:
                    callback()

            def trace_add(self, mode, callback):
                self.callbacks.append(callback)

        def factory(kind):
            def create(*args, **kwargs):
                widget = mock.MagicMock(name=kind)
                widget.kind, widget.kwargs = kind, kwargs
                toolkit.widgets.append(widget)
                return widget

            return create

        self.tkinter = types.ModuleType("tkinter")
        self.tkinter.__getattr__ = factory
        self.tkinter.StringVar = self.tkinter.BooleanVar = FakeVariable
        self.tkinter.Tk = lambda: toolkit.root
        self.ttk = types.ModuleType("tkinter.ttk")
        for kind in ("Frame", "Labelframe", "Label", "Combobox", "Entry", "Button", "Checkbutton",
                     "Scrollbar", "Panedwindow"):
            setattr(self.ttk, kind, factory(kind))
        self.messagebox = types.ModuleType("tkinter.messagebox")
        self.messagebox.showerror = lambda title, message: toolkit.errors.append((title, message))
        self.font = types.ModuleType("tkinter.font")
        self.font.nametofont = lambda name: mock.MagicMock()
        self.tkinter.ttk, self.tkinter.messagebox, self.tkinter.font = self.ttk, self.messagebox, self.font

    def modules(self):
        return {
            "tkinter": self.tkinter, "tkinter.ttk": self.ttk,
            "tkinter.messagebox": self.messagebox, "tkinter.font": self.font,
        }


class SourceRuleTests(unittest.TestCase):
    def test_every_russian_literal_is_translated_or_marked(self) -> None:
        self.assertEqual(SOURCE_PROBLEMS, [])
        self.assertGreater(len(SOURCE_KEYS), 200)

    def test_rules_detect_each_kind_of_violation(self) -> None:
        cases = (
            ('X = "Русский текст"\n', "русский литерал вне tr/N_ без i18n-keep"),
            ('X = "Другой текст"  # i18n-keep\n', "русский литерал вне tr/N_ без i18n-keep"),
            ('X = "Текст"  # i18n-keep: внутренний ключ\n', None),
            ('X = (\n    "Первая "\n    "вторая"  # i18n-keep: многострочный\n)\n', None),
            ('def f():\n    """Докстринг не переводится."""\n', None),
            ('def f(a):\n    return tr("Текст {}" + a)\n', "должен быть литералом"),
            ('def f(a):\n    return tr("Текст {}".format(a))\n', "должен быть литералом"),
            ('def f(a):\n    return tr(f"Текст {a}")\n', "должен быть литералом"),
            ('def f(a):\n    return tr("No cyrillic")\n', "без кириллицы"),
            ('X = N_("Only latin")\n', "без кириллицы"),
            ('X = tr("Текст при импорте")\n', "вне функции выполняется при импорте"),
            ('X = N_("Метка")\ndef f():\n    return tr(X)\n', None),
            ('def f():\n    return f"Текст {1}"\n', "русский литерал вне tr/N_"),
        )
        for source, expected in cases:
            with self.subTest(source=source):
                _, problems = analyze_source(source)
                if expected is None:
                    self.assertEqual(problems, [])
                else:
                    self.assertTrue(
                        any(expected in problem for problem in problems),
                        "ожидалось «{}», получено {}".format(expected, problems),
                    )

    def test_keys_are_collected_from_both_labels_and_deduplicated(self) -> None:
        keys, problems = analyze_source('A = N_("Один")\ndef f():\n    return tr("Один") + tr("Два")\n')
        self.assertEqual(problems, [])
        self.assertEqual(keys, ["Один", "Два"])


class DictionaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)

    def tearDown(self) -> None:
        configurator.set_language("ru")
        self.temporary.cleanup()

    def good_dictionary(self, code="en"):
        return write_dictionary(
            self.directory, code, "English",
            pseudo_strings(SOURCE_KEYS), {macro: "Text of " + macro for macro in REQUIRED_MACROS},
        )

    def test_real_dictionaries_are_complete(self) -> None:
        paths = sorted(DICTIONARY_DIR.glob("*.json")) if DICTIONARY_DIR.is_dir() else []
        self.assertTrue(paths, "нет словарей в {}".format(DICTIONARY_DIR))
        for path in paths:
            with self.subTest(dictionary=path.name):
                self.assertEqual(real_dictionary_problems(configurator, path, SOURCE_KEYS, REQUIRED_MACROS), [])

    def test_every_firmware_language_has_a_configurator_dictionary(self) -> None:
        self.assertEqual(missing_dictionaries(ROOT, DICTIONARY_DIR), [])
        self.assertTrue(any(ROOT.glob("lang_*.h")), "в проекте нет lang_*.h")

    def test_missing_dictionary_for_a_firmware_language_is_detected(self) -> None:
        project = self.directory / "project"
        project.mkdir()
        for name in ("lang_ru.h", "lang_en.h", "lang_de.h", "lang_EN.h", "lang_fr.h.bak"):
            (project / name).write_text("", encoding="utf-8")
        write_dictionary(self.directory / "dict", "en", "English", {}, {})
        found = missing_dictionaries(project, self.directory / "dict")
        self.assertEqual(found, ["de"])
        (self.directory / "dict" / "en.json").unlink()
        self.assertEqual(missing_dictionaries(project, self.directory / "dict"), ["de", "en"])
        print("  мутация -> отсутствие словаря у lang_de.h: {}".format(found))

    def test_dictionary_without_one_real_key_is_reported(self) -> None:
        data = json.loads((DICTIONARY_DIR / "en.json").read_text(encoding="utf-8"))
        del data["strings"]["Закрыть"]
        del data["macro_descriptions"]["MAX_WATER_TEMP"]
        path = self.directory / "en.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        found = dictionary_problems(path, SOURCE_KEYS, REQUIRED_MACROS)
        self.assertEqual(found, ["нет перевода ключа 'Закрыть'", "нет описания настройки MAX_WATER_TEMP"])
        print("  мутация -> {}".format(found))

    def test_required_macros_cover_options_servo_pump_and_language(self) -> None:
        for macro in (
            "SAMOVAR_USE_POWER", "SAMOVAR_USE_RMVK", "SAMOVAR_USE_SEM_AVR", "USE_BMP180", "USE_BMP280",
            "USE_BMP280_ALT", "USE_BME280", "USE_BME680", "USE_PRESSURE_XGZ", "USE_PRESSURE_1WIRE",
            "USE_PRESSURE_MPX", "servoDelta", "PUMP_PWM_FREQ", "SAMOVAR_LANG", "MAX_WATER_TEMP",
        ):
            self.assertIn(macro, REQUIRED_MACROS)

    def test_pseudo_dictionary_passes_every_check(self) -> None:
        path = self.good_dictionary()
        self.assertEqual(real_dictionary_problems(configurator, path, SOURCE_KEYS, REQUIRED_MACROS), [])

    def test_checker_reports_each_defect_with_its_own_message(self) -> None:
        keys = ["Файл {} из {}", "Закрыть", "Имя: {name}"]
        macros = ["MAX_WATER_TEMP", "USE_LUA"]

        def build(strings=None, macro_texts=None, name="English", **extra):
            return write_dictionary(
                self.directory, "en", name,
                {"Файл {} из {}": "File {} of {}", "Закрыть": "Close", "Имя: {name}": "Name: {name}"}
                if strings is None else strings,
                {"MAX_WATER_TEMP": "Max", "USE_LUA": "Lua"} if macro_texts is None else macro_texts,
                **extra,
            )

        self.assertEqual(dictionary_problems(build(), keys, macros), [])
        cases = (
            (dict(strings={"Файл {} из {}": "File {} of {}", "Закрыть": "Close"}), "нет перевода ключа 'Имя: {name}'"),
            (dict(strings={"Файл {} из {}": "File {} of {}", "Закрыть": "Close", "Имя: {name}": "N: {name}", "Лишний": "Extra"}),
             "лишний ключ 'Лишний'"),
            (dict(strings={"Файл {} из {}": "File {} of {}", "Закрыть": "Закрыть", "Имя: {name}": "N: {name}"}),
             "кириллица в переводе 'Закрыть'"),
            (dict(strings={"Файл {} из {}": "File {} of {}", "Закрыть": " ", "Имя: {name}": "N: {name}"}),
             "пустой перевод 'Закрыть'"),
            (dict(strings={"Файл {} из {}": "File {}", "Закрыть": "Close", "Имя: {name}": "N: {name}"}),
             "не совпадают плейсхолдеры 'Файл {} из {}'"),
            (dict(strings={"Файл {} из {}": "File {} of {}", "Закрыть": "Close", "Имя: {name}": "N: {0}"}),
             "не совпадают плейсхолдеры 'Имя: {name}'"),
            (dict(strings={"Файл {} из {}": "File {} of {}", "Закрыть": "Close", "Имя: {name}": "N: {:d}"}),
             "не совпадают плейсхолдеры 'Имя: {name}'"),
            (dict(macro_texts={"MAX_WATER_TEMP": "Max"}), "нет описания настройки USE_LUA"),
            (dict(macro_texts={"MAX_WATER_TEMP": "Max", "USE_LUA": "Lua", "OTHER": "x"}), "лишнее описание настройки OTHER"),
            (dict(macro_texts={"MAX_WATER_TEMP": "Максимум", "USE_LUA": "Lua"}), "кириллица в описании MAX_WATER_TEMP"),
            (dict(name=""), "language_name пуст"),
            (dict(extra_key=1), "верхний уровень"),
        )
        for arguments, expected in cases:
            with self.subTest(expected=expected):
                problems = dictionary_problems(build(**arguments), keys, macros)
                self.assertTrue(
                    any(expected in problem for problem in problems),
                    "ожидалось «{}», получено {}".format(expected, problems),
                )
        broken = self.directory / "en.json"
        broken.write_text('{"language_name": "English", "strings": {}, "macro_descriptions": {}', encoding="utf-8")
        self.assertIn("некорректный JSON", dictionary_problems(broken, [], [])[0])
        broken.write_text(
            '{"language_name": "English", "strings": {"Да": "Yes", "Да": "Yes"}, "macro_descriptions": {}}',
            encoding="utf-8",
        )
        self.assertTrue(any("повторяются ключи JSON" in problem for problem in dictionary_problems(broken, ["Да"], [])))

    def test_dictionary_must_translate_every_source_key_even_after_a_new_tr_call(self) -> None:
        path = self.good_dictionary()
        source = MODULE_PATH.read_text(encoding="utf-8") + '\n\ndef added():\n    return tr("Новая строка интерфейса")\n'
        keys, problems = analyze_source(source)
        self.assertEqual(problems, [])
        found = dictionary_problems(path, keys, REQUIRED_MACROS)
        self.assertEqual(found, ["нет перевода ключа 'Новая строка интерфейса'"])

    def test_untranslated_macro_description_is_caught_behaviourally(self) -> None:
        macros = {macro: "Text of " + macro for macro in REQUIRED_MACROS}
        del macros["MAX_WATER_TEMP"]
        path = write_dictionary(self.directory, "en", "English", pseudo_strings(SOURCE_KEYS), macros)
        self.assertEqual(
            dictionary_problems(path, SOURCE_KEYS, REQUIRED_MACROS), ["нет описания настройки MAX_WATER_TEMP"]
        )
        configurator.set_language("en", self.directory)
        try:
            with self.assertRaises(configurator.TranslationError) as raised:
                configurator.SamovarConfig(ROOT).descriptions()
        finally:
            configurator.set_language("ru")
        self.assertIn("MAX_WATER_TEMP", str(raised.exception))

    def test_unused_macro_description_is_caught_by_recorded_requests(self) -> None:
        macros = {macro: "Text of " + macro for macro in REQUIRED_MACROS}
        macros["NOT_A_SETTING"] = "Text"
        path = write_dictionary(self.directory, "en", "English", pseudo_strings(SOURCE_KEYS), macros)
        required_with_extra = REQUIRED_MACROS + ["NOT_A_SETTING"]
        # словарь согласован со списком, но descriptions() этот макрос не запрашивает
        problems = real_dictionary_problems(configurator, path, SOURCE_KEYS, required_with_extra)
        self.assertEqual(problems, ["описание NOT_A_SETTING не используется descriptions()"])


class MechanismTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name) / "i18n"
        self.module = configurator
        write_dictionary(
            self.directory, "en", "English",
            {
                **pseudo_strings(SOURCE_KEYS),
                "Сохранить": "Save", "Закрыть": "Close", "Файл {}": "File {}",
                "Настройки сохранены.\n": "Settings saved.\n", "PlatformIO не найден": "PlatformIO not found",
                "Поле «{}» не должно быть пустым": "Field \"{}\" must not be empty",
            },
            {"MAX_WATER_TEMP": "Maximum water temperature", "SAMOVAR_LANG": "Firmware language"},
        )
        write_dictionary(
            self.directory, "de", "Deutsch",
            {**pseudo_strings(SOURCE_KEYS), "Сохранить": "Speichern", "Закрыть": "Schliessen", "Файл {}": "Datei {}"},
            {"MAX_WATER_TEMP": "Maximale Wassertemperatur"},
        )

    def tearDown(self) -> None:
        configurator.set_language("ru")
        self.temporary.cleanup()

    # --- проверки, которые прогоняются и на мутантах модуля
    def check_translation(self, module) -> None:
        module.set_language("en", self.directory)
        self.assertEqual(module.current_language(), "en")
        self.assertEqual(module.tr("Сохранить"), "Save")
        self.assertEqual(module.tr("Закрыть"), "Close")
        self.assertEqual(module.tr("Файл {}").format("a.txt"), "File a.txt")
        for text in ("OK", "192.168.1.37", "COM3", "—", "{}: {}"):
            self.assertEqual(module.tr(text), text)
        with self.assertRaises(module.TranslationError) as raised:
            module.tr("Нет такой строки")
        self.assertIn("Нет такой строки", str(raised.exception))
        module.set_language("de", self.directory)
        self.assertEqual(module.tr("Сохранить"), "Speichern")
        self.assertEqual(module.tr("Закрыть"), "Schliessen")
        with self.assertRaises(module.TranslationError):
            module.tr("Нет такой строки")
        module.set_language("ru")
        self.assertEqual(module.tr("Нет такой строки"), "Нет такой строки")
        self.assertEqual(module.tr("Сохранить"), "Сохранить")

    def check_descriptions(self, module) -> None:
        macros = {macro: "Description of " + macro for macro in REQUIRED_MACROS}
        write_dictionary(self.directory, "en", "English", pseudo_strings(SOURCE_KEYS), macros)
        russian, _ = descriptions_with(module, self.directory, "ru")
        translated, requested = descriptions_with(module, self.directory, "en")
        self.assertEqual(set(translated), set(russian))
        self.assertEqual(
            set(requested), set(REQUIRED_MACROS),
            "descriptions() не запросил описания через macro_description для этих настроек",
        )
        for macro, text in translated.items():
            self.assertFalse(CYRILLIC.search(text), "описание {} осталось русским: {!r}".format(macro, text))
        self.assertTrue(translated["MAX_WATER_TEMP"].startswith("Description of"))

    def check_language_save(self, module, expect_disabled_for_russian=True) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copyfile(ROOT / "Samovar_ini.h", root / "Samovar_ini.h")
            shutil.copyfile(ROOT / "user_config_override.example.h", root / "user_config_override.example.h")
            for code, name in (("ru", "Русский"), ("en", "English"), ("de", "Deutsch")):
                (root / "lang_{}.h".format(code)).write_text('#define SAMOVAR_LANG_NAME "{}"\n'.format(name), encoding="utf-8")
            model = module.SamovarConfig(root)
            state = model.load()
            self.assertEqual(state["SAMOVAR_LANG"], "ru")
            original = (root / "user_config_override.h").read_text(encoding="utf-8")
            for code in ("en", "de", "ru"):
                state["SAMOVAR_LANG"] = code
                model.save(state)
                override = module.HeaderDocument((root / "user_config_override.h").read_text(encoding="utf-8"))
                line = override.find("SAMOVAR_LANG")
                self.assertEqual(line.enabled, code != "ru", "язык {}: {}".format(code, override.lines))
                self.assertEqual(line.value, code)
                self.assertEqual(model.load()["SAMOVAR_LANG"], code)
            # остальной override не меняется: после возврата на ru разница только в значении строки
            final = (root / "user_config_override.h").read_text(encoding="utf-8")
            def stable(text):
                return [line for line in text.splitlines() if "PUMP_PWM_FREQ" not in line and "SAMOVAR_LANG" not in line]

            self.assertEqual(stable(final), stable(original))

    # --- тесты
    def test_translation_lookup_is_strict_and_two_languages_differ(self) -> None:
        self.check_translation(configurator)

    def test_broken_dictionaries_are_rejected_without_changing_current_language(self) -> None:
        configurator.set_language("en", self.directory)
        cases = {
            "bad_json": ("{", "некорректный JSON"),
            "dup": ('{"language_name": "X", "strings": {"Да": "a", "Да": "b"}}', "повторяются ключи"),
            "noname": ('{"strings": {}}', "language_name"),
            "extra": ('{"language_name": "X", "strings": {}, "other": 1}', "допустимы только ключи"),
            "badstrings": ('{"language_name": "X", "strings": {"Да": 1}}', "словарём строк"),
        }
        for code, (text, expected) in cases.items():
            with self.subTest(code=code):
                (self.directory / (code + ".json")).write_text(text, encoding="utf-8")
                with self.assertRaises(configurator.TranslationError) as raised:
                    configurator.set_language(code, self.directory)
                self.assertIn(expected, str(raised.exception))
                self.assertEqual(configurator.current_language(), "en")
                self.assertEqual(configurator.tr("Сохранить"), "Save")
        for code in ("fr", "../en", "EN", "", "ru "):
            with self.subTest(code=code):
                with self.assertRaises(configurator.TranslationError):
                    configurator.set_language(code, self.directory)
                self.assertEqual(configurator.current_language(), "en")

    def test_available_languages_lists_russian_first_then_dictionaries(self) -> None:
        (self.directory / "README.json").write_text("{}", encoding="utf-8")
        (self.directory / "de.json.bak").write_text("{", encoding="utf-8")
        self.assertEqual(
            configurator.available_languages(self.directory),
            [("ru", "Русский"), ("de", "Deutsch"), ("en", "English")],
        )
        self.assertEqual(configurator.available_languages(self.directory / "missing"), [("ru", "Русский")])
        (self.directory / "xx.json").write_text("{", encoding="utf-8")
        with self.assertRaises(configurator.TranslationError):
            configurator.available_languages(self.directory)

    def test_macro_description_is_source_text_for_russian_and_dictionary_otherwise(self) -> None:
        self.assertEqual(configurator.macro_description("MAX_WATER_TEMP", "Исходный"), "Исходный")
        configurator.set_language("en", self.directory)
        self.assertEqual(configurator.macro_description("MAX_WATER_TEMP", "Исходный"), "Maximum water temperature")
        configurator.set_language("de", self.directory)
        self.assertEqual(configurator.macro_description("MAX_WATER_TEMP", "Исходный"), "Maximale Wassertemperatur")
        with self.assertRaises(configurator.TranslationError) as raised:
            configurator.macro_description("SAMOVAR_LANG", "Исходный")
        self.assertIn("SAMOVAR_LANG", str(raised.exception))

    def test_descriptions_are_translated_per_macro_with_the_same_keys_as_russian(self) -> None:
        self.check_descriptions(configurator)

    def test_validation_errors_use_translated_text_and_translated_label(self) -> None:
        configurator.set_language("en", self.directory)
        with self.assertRaises(configurator.ConfigError) as raised:
            configurator.validate_value("", "text", "Сохранить")
        self.assertEqual(str(raised.exception), 'Field "Save" must not be empty')
        # метку, уже переведённую вызывающим, повторный tr() не ломает
        with self.assertRaises(configurator.ConfigError) as raised:
            configurator.validate_value("", "text", "Save")
        self.assertEqual(str(raised.exception), 'Field "Save" must not be empty')

    def test_choice_variable_shows_labels_and_returns_identifiers(self) -> None:
        for labels, identifier in (
            ({"ru": "Русский", "en": "English"}, "en"),
            ({"KVIC": "KVIC", "Не использовать": "Do not use"}, "Не использовать"),
        ):
            variable = Variable()
            choice = configurator.ChoiceVariable(variable, labels)
            choice.set(identifier)
            self.assertEqual(variable.value, labels[identifier])
            self.assertEqual(choice.get(), identifier)
            with self.assertRaises(configurator.ConfigError):
                choice.set("нет такого")
            choice.trace_add("write", print)
            self.assertIs(variable.callback, print)
        with self.assertRaises(configurator.ConfigError):
            configurator.ChoiceVariable(Variable(), {"a": "Same", "b": "Same"})

    def test_option_variable_translates_labels_but_keeps_russian_identifiers(self) -> None:
        write_dictionary(
            self.directory, "en", "English",
            {"Не использовать": "Do not use", "РМВ-К": "RMV-K"}, {},
        )
        configurator.set_language("en", self.directory)
        variable = Variable()
        choice = configurator.option_variable(variable, configurator.GROUP_REGULATOR)
        self.assertEqual(list(choice.labels.values()), ["Do not use", "KVIC", "RMV-K", "SEM_AVR"])
        choice.set("РМВ-К")
        self.assertEqual(variable.value, "RMV-K")
        self.assertEqual(choice.get(), "РМВ-К")

    def test_user_preferences_keep_only_known_language(self) -> None:
        path = Path(self.temporary.name) / "prefs.json"
        for language in ("en", "de"):
            configurator.save_user_prefs({"port": "COM3", "language": language}, path)
            self.assertEqual(
                configurator.load_user_prefs(path, i18n_dir=self.directory), {"port": "COM3", "language": language}
            )
        configurator.save_user_prefs({"port": "COM3", "language": "ru"}, path)
        self.assertEqual(configurator.load_user_prefs(path, i18n_dir=self.directory)["language"], "ru")
        for garbage in ("fr", "../en", "EN", "", "en.json"):
            with self.subTest(language=garbage):
                configurator.save_user_prefs({"port": "COM3", "language": garbage}, path)
                self.assertEqual(configurator.load_user_prefs(path, i18n_dir=self.directory), {"port": "COM3"})
        path.write_text(json.dumps({"language": 5, "geometry": "bad"}), encoding="utf-8")
        self.assertEqual(configurator.load_user_prefs(path, i18n_dir=self.directory), {})
        # словарь удалён - язык из настроек устаревает и отбрасывается
        configurator.save_user_prefs({"language": "de"}, path)
        (self.directory / "de.json").unlink()
        self.assertEqual(configurator.load_user_prefs(path, i18n_dir=self.directory), {})

    def test_firmware_languages_come_from_lang_files(self) -> None:
        root = Path(self.temporary.name) / "project"
        root.mkdir()
        for name, text in (
            ("lang_ru.h", '#define SAMOVAR_LANG_NAME "Русский"\n'),
            ("lang_en.h", '#define SAMOVAR_LANG_NAME "English"  // комментарий\n'),
            ("lang_de.h", '#define SAMOVAR_LANG_NAME "Deutsch"\n'),
            ("lang_.h", "garbage\n"),
            ("lang_EN.h", "garbage\n"),
            ("lang_en.h.bak", "garbage\n"),
            ("language.h", "garbage\n"),
        ):
            (root / name).write_text(text, encoding="utf-8")
        model = configurator.SamovarConfig(root)
        self.assertEqual(model.firmware_languages(), [("ru", "Русский"), ("de", "Deutsch"), ("en", "English")])
        (root / "lang_en.h").write_text('//#define SAMOVAR_LANG_NAME "English"\n', encoding="utf-8")
        with self.assertRaises(configurator.ConfigError) as raised:
            model.firmware_languages()
        self.assertIn("lang_en.h", str(raised.exception))
        (root / "lang_en.h").write_text('#define SAMOVAR_LANG_NAME "English"\n', encoding="utf-8")
        (root / "lang_ru.h").unlink()
        with self.assertRaises(configurator.ConfigError) as raised:
            model.firmware_languages()
        self.assertIn("lang_ru.h", str(raised.exception))

    def test_firmware_language_round_trip_through_user_override(self) -> None:
        self.check_language_save(configurator)

    def test_firmware_language_rejects_bad_codes_and_keeps_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copyfile(ROOT / "Samovar_ini.h", root / "Samovar_ini.h")
            shutil.copyfile(ROOT / "user_config_override.example.h", root / "user_config_override.example.h")
            (root / "lang_en.h").write_text('#define SAMOVAR_LANG_NAME "English"\n', encoding="utf-8")
            model = configurator.SamovarConfig(root)
            state = model.load()
            model.save(state)
            before = {name: (root / name).read_bytes() for name in ("Samovar_ini.h", "user_config_override.h")}
            for code in ("../x", "fr", "EN", "en/../en", "", "x" * 17):
                with self.subTest(code=code):
                    bad = dict(state, SAMOVAR_LANG=code, MAX_WATER_TEMP="75")
                    with self.assertRaises(configurator.ConfigError):
                        model.save(bad)
                    for name, content in before.items():
                        self.assertEqual((root / name).read_bytes(), content)
            # у старого override нет строки SAMOVAR_LANG: она добавляется перед завершающим #endif
            override = root / "user_config_override.h"
            text = override.read_text(encoding="utf-8")
            override.write_text(re.sub(r"(?m)^(//)?#define SAMOVAR_LANG .*\n", "", text), encoding="utf-8")
            self.assertIsNone(configurator.HeaderDocument(override.read_text(encoding="utf-8")).find("SAMOVAR_LANG"))
            model.save(dict(state, SAMOVAR_LANG="en"))
            lines = override.read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[-2:], ["#define SAMOVAR_LANG en", "#endif  // _USER_CONFIG_OVERRIDE_H_"])
            self.assertEqual(lines.count("#define SAMOVAR_LANG en"), 1)
            override.write_text(re.sub(r"(?m)^(//)?#define SAMOVAR_LANG .*\n", "", override.read_text(encoding="utf-8")), encoding="utf-8")
            model.save(dict(state, SAMOVAR_LANG="ru"))
            lines = override.read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[-2:], ["//#define SAMOVAR_LANG ru", "#endif  // _USER_CONFIG_OVERRIDE_H_"])

    def test_settings_saved_message_is_tagged_ok_in_every_language(self) -> None:
        for language, expected in (("ru", "Настройки сохранены.\n"), ("en", "Settings saved.\n")):
            configurator.set_language(language, self.directory)
            logged = []
            window = configurator.ConfiguratorWindow.__new__(configurator.ConfiguratorWindow)
            window.config = type("Config", (), {"save": lambda _, state: None})()
            window._state = lambda: {}
            window._mark_saved = lambda: None
            window.status_var = Variable()
            window._append_log = lambda text, tag=None: logged.append((text, tag))
            self.assertTrue(window.save())
            self.assertEqual(logged, [(expected, "ok")])
        self.assertIsNone(configurator.log_line_tag("Settings saved.\n"))

    def test_monitor_child_gets_the_current_language_and_dictionary_folder(self) -> None:
        for language in ("ru", "en", "de"):
            configurator.set_language(language, self.directory)
            started = []
            window = configurator.ConfiguratorWindow.__new__(configurator.ConfiguratorWindow)
            window.busy = False
            window.config = type("Config", (), {"project_root": Path("/tmp/Samovar")})()
            window.pio_executable = "pio"
            window.port_var = Variable("/dev/ttyUSB0")
            window.board_var = Variable("ESP32 DevKit")
            window._start_process = lambda command, action, env=None: started.append((command, action))
            with mock.patch.object(configurator, "pio_python_executable", lambda _: "python-pio"):
                window.start_action("monitor")
            command, action = started[0]
            self.assertEqual(action, "monitor")
            self.assertEqual(command[-4:], ["--language", language, "--i18n-dir", str(self.directory)])
            self.assertEqual(command[1:3], [str(MODULE_PATH), "--serial-monitor"])

    def test_main_applies_language_option_and_rejects_unknown_language(self) -> None:
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            code = configurator.main(["--language", "fr", "--i18n-dir", str(self.directory), "--pio", "pio"])
        self.assertEqual(code, 1)
        self.assertIn("fr", errors.getvalue())
        self.assertEqual(configurator.current_language(), "ru")
        for language, expected in (("en", "PlatformIO not found"),):
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors):
                code = configurator.main(["--language", language, "--i18n-dir", str(self.directory), "--pio", ""])
            self.assertEqual((code, errors.getvalue().strip()), (1, expected))
            self.assertEqual(configurator.current_language(), language)
        configurator.set_language("ru")
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            code = configurator.main(["--language", "ru", "--i18n-dir", str(self.directory), "--pio", ""])
        self.assertEqual((code, errors.getvalue().strip()), (1, "PlatformIO не найден"))


class LittleFsImageTests(unittest.TestCase):
    STUB = (
        "import json, os, sys\n"
        "args = sys.argv[1:]\n"
        "out = args[args.index('--out') + 1]\n"
        "os.makedirs(out, exist_ok=True)\n"
        "open(os.path.join(out, 'index.htm'), 'w').write(args[args.index('--image') + 1])\n"
        "json.dump(args, open(os.path.join(os.path.dirname(out), 'args.json'), 'w'))\n"
        "if os.environ.get('STUB_FAIL'):\n"
        "    sys.stderr.write('line1\\nbuild failed: no translation\\n')\n"
        "    sys.exit(3)\n"
    )

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "project"
        (self.root / "tools").mkdir(parents=True)
        (self.root / "tools" / "build_web_assets.py").write_text(self.STUB, encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def make_window(self, language: str, errors: list, module=configurator):
        window = module.ConfiguratorWindow.__new__(module.ConfiguratorWindow)
        window.config = type("Config", (), {"project_root": self.root})()
        window.choice_vars = {"SAMOVAR_LANG": Variable(language)}
        window.logged = []
        window._append_log = lambda text, tag=None: window.logged.append(text)
        window.messagebox = type("Messages", (), {"showerror": lambda _, title, message: errors.append((title, message))})()
        window.root = type("Root", (), {"update_idletasks": lambda _: None})()
        window.save = lambda show_success=True: True
        return window

    def test_log_line_is_painted_before_the_blocking_build(self) -> None:
        self.check_log_line_is_painted_before_the_blocking_build(configurator)

    def check_log_line_is_painted_before_the_blocking_build(self, module) -> None:
        events = []
        window = self.make_window("en", [], module)
        window.save = lambda show_success=True: events.append("save") or True
        window._append_log = lambda text, tag=None: events.append("log")
        window.root = type("Root", (), {"update_idletasks": lambda _: events.append("update")})()
        real_run = module.subprocess.run

        def recording_run(*args, **kwargs):
            events.append("run")
            return real_run(*args, **kwargs)

        with mock.patch.object(module.subprocess, "run", recording_run):
            self.assertIsNotNone(window._prepare_littlefs_environment())
        window._cleanup_fs_image()
        self.assertEqual(events, ["save", "log", "update", "run"])

    def test_settings_are_saved_before_the_image_is_built(self) -> None:
        self.check_settings_are_saved_before_the_image_is_built(configurator)

    def check_settings_are_saved_before_the_image_is_built(self, module) -> None:
        for language in ("ru", "en"):
            events = []
            window = self.make_window(language, [], module)
            window.save = lambda show_success=True: events.append(
                ("save", show_success, window.choice_vars["SAMOVAR_LANG"].get())
            ) or True
            real_run = module.subprocess.run

            def recording_run(command, **kwargs):
                events.append(("run", command[command.index("--image") + 1]))
                return real_run(command, **kwargs)

            with mock.patch.object(module.subprocess, "run", recording_run):
                environment = window._prepare_littlefs_environment()
            self.assertIsNotNone(environment, language)
            window._cleanup_fs_image()
            self.assertEqual(
                events, [("save", False, language), ("run", language)],
                "язык {}: образ собирается не после сохранения настроек".format(language),
            )

    def test_failed_save_stops_the_image_build(self) -> None:
        self.check_failed_save_stops_the_image_build(configurator)

    def check_failed_save_stops_the_image_build(self, module) -> None:
        for language in ("ru", "en"):
            errors, runs = [], []
            before = set(Path(tempfile.gettempdir()).glob("samovar_littlefs_*"))
            window = self.make_window(language, errors, module)
            window.save = lambda show_success=True: False
            def failing_run(*args, **kwargs):
                runs.append(args)
                return types.SimpleNamespace(returncode=0, stdout="", stderr="")

            with mock.patch.object(module.subprocess, "run", failing_run):
                result = window._prepare_littlefs_environment()
            self.assertIsNone(result, "язык {}: сборка продолжилась после отказа сохранения".format(language))
            self.assertEqual(runs, [], "язык {}: образ собран без сохранённых настроек".format(language))
            self.assertIsNone(window.fs_image_dir)
            self.assertEqual(set(Path(tempfile.gettempdir()).glob("samovar_littlefs_*")) - before, set())
            self.assertEqual(errors, [], "об ошибке сохранения сообщает сам save()")

    def test_image_build_gets_the_process_start_options(self) -> None:
        self.check_image_build_gets_the_process_start_options(configurator)

    def check_image_build_gets_the_process_start_options(self, module) -> None:
        for options in ({"creationflags": 512}, {"start_new_session": True}):
            calls = []
            window = self.make_window("en", [], module)
            real_run = module.subprocess.run

            def recording_run(command, **kwargs):
                calls.append(kwargs)
                return real_run(command, **{k: v for k, v in kwargs.items() if k not in options})

            with mock.patch.object(module, "process_start_options", lambda: dict(options)), \
                    mock.patch.object(module.subprocess, "run", recording_run):
                self.assertIsNotNone(window._prepare_littlefs_environment())
            window._cleanup_fs_image()
            self.assertEqual(len(calls), 1)
            for name, value in options.items():
                self.assertEqual(calls[0].get(name), value, "сборка образа без параметра {}".format(name))

    def test_command_and_environment_carry_language_and_data_folder(self) -> None:
        for language, out in (("ru", Path("/tmp/a/data")), ("en", Path("/tmp/b/data"))):
            command = configurator.littlefs_image_command("python", self.root, language, out)
            self.assertEqual(
                command,
                ["python", str(self.root / "tools" / "build_web_assets.py"), "--image", language, "--out", str(out)],
            )
        base = {"PATH": "/bin", "PLATFORMIO_DATA_DIR": "/old"}
        environment = configurator.littlefs_environment(base, Path("/tmp/x/data"))
        self.assertEqual(environment, {"PATH": "/bin", "PLATFORMIO_DATA_DIR": "/tmp/x/data"})
        self.assertEqual(base["PLATFORMIO_DATA_DIR"], "/old")

    def test_image_is_built_for_selected_language_into_temporary_folder_and_removed(self) -> None:
        for language in ("ru", "en"):
            errors = []
            window = self.make_window(language, errors)
            environment = window._prepare_littlefs_environment()
            self.assertEqual(errors, [])
            data_dir = Path(environment["PLATFORMIO_DATA_DIR"])
            self.assertEqual(data_dir.name, "data")
            self.assertEqual((data_dir / "index.htm").read_text(), language)
            arguments = json.loads((data_dir.parent / "args.json").read_text())
            self.assertEqual(arguments, ["--image", language, "--out", str(data_dir)])
            self.assertEqual(window.fs_image_dir, data_dir.parent)
            self.assertTrue(data_dir.parent.name.startswith("samovar_littlefs_"))
            self.assertTrue(any(language in line and "LittleFS" in line for line in window.logged))
            window._cleanup_fs_image()
            self.assertFalse(data_dir.parent.exists())
            self.assertIsNone(window.fs_image_dir)

    def test_failed_image_build_stops_the_upload_without_fallback_to_data(self) -> None:
        errors = []
        started = []
        before = set(Path(tempfile.gettempdir()).glob("samovar_littlefs_*"))
        window = self.make_window("en", errors)
        window.busy = False
        window.pio_executable = "pio"
        window.board_var = Variable("ESP32 DevKit")
        window.port_var = Variable("COM7")
        window._start_process = lambda *args, **kwargs: started.append(args)
        with mock.patch.dict(configurator.os.environ, {"STUB_FAIL": "1"}):
            window.start_action("uploadfs")
        self.assertEqual(started, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("build failed: no translation", errors[0][1])
        self.assertIsNone(window.fs_image_dir)
        leftovers = set(Path(tempfile.gettempdir()).glob("samovar_littlefs_*")) - before
        self.assertEqual(leftovers, set())

    def test_slow_build_is_reported_as_error(self) -> None:
        errors = []
        window = self.make_window("en", errors)
        timeout = configurator.subprocess.TimeoutExpired("build", 120)
        with mock.patch.object(configurator.subprocess, "run", side_effect=timeout):
            self.assertIsNone(window._prepare_littlefs_environment())
        self.assertEqual(len(errors), 1)
        self.assertIsNone(window.fs_image_dir)


class WindowBehaviorTests(unittest.TestCase):
    """Поведение окна на заглушках (без Tk). Каждая проверка принимает модуль: её же гоняют на мутантах."""

    STRINGS = {
        "Язык интерфейса": "Interface language",
        "Язык будет применён после перезапуска конфигуратора.": "Restart the configurator to apply the language.",
        "Неизвестная подпись варианта: {}": "Unknown option label: {}",
        "Ошибка чтения настроек": "Settings read error",
        "Настройка {}: {}": "Setting {}: {}",
        "Неизвестное значение {}": "Unknown value {}",
    }

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        write_dictionary(self.directory / "i18n", "en", "English", self.STRINGS, {})
        write_dictionary(self.directory / "i18n", "de", "Deutsch", self.STRINGS, {})

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @contextlib.contextmanager
    def prefs_file(self, module, content: dict):
        """Настройки окна читаются и пишутся через значения по умолчанию аргумента path."""
        path = self.directory / "prefs.json"
        path.write_text(json.dumps(content), encoding="utf-8")
        with mock.patch.object(module.load_user_prefs, "__defaults__", (path, None)), \
                mock.patch.object(module.save_user_prefs, "__defaults__", (path,)):
            yield path

    def window(self, module):
        window = module.ConfiguratorWindow.__new__(module.ConfiguratorWindow)
        window.errors = []
        window.infos = []
        window.messagebox = type("Messages", (), {
            "showerror": lambda _, title, message: window.errors.append((title, message)),
            "showinfo": lambda _, title, message: window.infos.append((title, message)),
        })()
        window.logged = []
        window._append_log = lambda text, tag=None: window.logged.append(text)
        return window

    # --- close() и выбор языка
    def check_close_keeps_the_language(self, module) -> None:
        for language in ("en", "de"):
            module.set_language(language, self.directory / "i18n")
            with self.prefs_file(module, {"language": language, "port": "old"}) as path:
                window = self.window(module)
                window.is_dirty = lambda: False
                window.process = None
                window.fs_image_dir = None
                window.port_var = Variable(" COM9 ")
                destroyed = []
                window.root = type("Root", (), {"geometry": lambda _: "900x700+10+20", "destroy": lambda _: destroyed.append(1)})()
                window.close()
                saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                saved, {"language": language, "port": "COM9", "geometry": "900x700+10+20"}, "язык {}".format(language)
            )
            self.assertEqual(destroyed, [1])

    def check_language_selection_is_saved_and_announced(self, module) -> None:
        module.set_language("en", self.directory / "i18n")
        for label, code in (("Deutsch", "de"), ("English", "en")):
            with self.prefs_file(module, {"port": "COM3"}) as path:
                window = self.window(module)
                window.language_var = module.ChoiceVariable(Variable(label), {"en": "English", "de": "Deutsch"})
                window._language_selected()
                saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved, {"port": "COM3", "language": code}, "выбран {}".format(label))
            self.assertEqual(
                window.infos,
                [("Interface language", "Restart the configurator to apply the language.")],
                "выбран {}".format(label),
            )

    # --- каталог образа и запуск процесса
    def check_close_and_finish_remove_the_image_folder(self, module) -> None:
        for name in ("close", "finish"):
            image = Path(tempfile.mkdtemp(prefix="samovar_littlefs_"))
            (image / "data").mkdir()
            window = self.window(module)
            window.fs_image_dir = image
            window.process = None
            window.is_dirty = lambda: False
            window.port_var = Variable("COM1")
            window.root = type("Root", (), {"geometry": lambda _: "1x1+0+0", "destroy": lambda _: None})()
            window.partial_line = ""
            window.stop_requested = False
            window.active_action = "upload"
            window.action_started = 0
            window.active_port_network = False
            window.status_var = Variable()
            window._set_busy = lambda busy, action: None
            try:
                with self.prefs_file(module, {}):
                    if name == "close":
                        window.close()
                    else:
                        window._finish_action(0)
                self.assertFalse(image.exists(), "{}: каталог образа остался".format(name))
                self.assertIsNone(window.fs_image_dir, name)
            finally:
                shutil.rmtree(str(image), ignore_errors=True)

    def start_window(self, module, image: Path):
        window = self.window(module)
        window.busy = False
        window.fs_image_dir = image
        window.config = type("Config", (), {"project_root": self.directory})()
        window.device_config_request_id = 0
        window.stop_requested = False
        window._set_busy = lambda busy, action: None
        window._tick_status = lambda: None
        return window

    def check_process_gets_the_environment_and_failed_start_removes_the_image(self, module) -> None:
        module.set_language("ru")
        for environment in ({"PLATFORMIO_DATA_DIR": "/a/data"}, {"PLATFORMIO_DATA_DIR": "/b/data"}):
            calls = []
            window = self.start_window(module, None)
            popen = lambda command, **kwargs: calls.append(kwargs) or object()
            with mock.patch.object(module.subprocess, "Popen", popen), mock.patch.object(module.threading, "Thread"):
                window._start_process(["pio"], "uploadfs", environment)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]["env"], environment)
        image = Path(tempfile.mkdtemp(prefix="samovar_littlefs_"))
        try:
            window = self.start_window(module, image)

            def failing_popen(command, **kwargs):
                raise OSError("no such file")

            with mock.patch.object(module.subprocess, "Popen", failing_popen):
                window._start_process(["pio"], "uploadfs", {"PLATFORMIO_DATA_DIR": str(image / "data")})
            self.assertFalse(image.exists(), "после отказа Popen каталог образа остался")
            self.assertEqual(len(window.errors), 1)
            self.assertIn("no such file", window.errors[0][1])
        finally:
            shutil.rmtree(str(image), ignore_errors=True)

    # --- ChoiceVariable и чтение настроек
    def check_unknown_label_is_a_translated_config_error(self, module) -> None:
        for language, label, expected in (("en", "Foo", "Unknown option label: Foo"), ("de", "Bar", "Unknown option label: Bar")):
            module.set_language(language, self.directory / "i18n")
            variable = module.ChoiceVariable(Variable(label), {"en": "English"})
            try:
                variable.get()
            except module.ConfigError as error:
                self.assertEqual(str(error), expected)
            except KeyError as error:
                self.fail("get() бросил голый KeyError {!r}".format(error))
            else:
                self.fail("get() не бросил исключение для подписи {!r}".format(label))
        self.assertEqual(module.ChoiceVariable(Variable("English"), {"en": "English"}).get(), "en")

    def check_unknown_firmware_language_names_the_setting(self, module) -> None:
        for language, code, expected in (
            ("en", "fr", "Setting SAMOVAR_LANG: Unknown value fr"),
            ("de", "xx", "Setting SAMOVAR_LANG: Unknown value xx"),
        ):
            module.set_language(language, self.directory / "i18n")
            window = self.window(module)
            window.config = type("Config", (), {"load": lambda _: {"board": "b", "servoDelta": "1", "SAMOVAR_LANG": code}})()
            window.board_var = Variable()
            window.servo_var = Variable()
            window.value_vars, window.bool_vars, window.optional_enabled_vars = {}, {}, {}
            window.choice_vars = {"SAMOVAR_LANG": module.ChoiceVariable(Variable(), {"ru": "Русский"})}
            destroyed = []
            window.root = type("Root", (), {"destroy": lambda _: destroyed.append(1)})()
            window._load()
            self.assertEqual(window.errors, [("Settings read error", expected)])
            self.assertEqual(destroyed, [1])

    def load_window(self, module, board: str, known_boards: dict):
        window = self.window(module)
        window.config = type("Config", (), {"load": lambda _: {
            "board": board, "servoDelta": "1", "wifi_ssid": "net", "wifi_password": "pw",
        }})()
        window.board_var = module.ChoiceVariable(Variable(), known_boards)
        window.servo_var, window.ssid_var, window.password_var = Variable(), Variable(), Variable()
        window.value_vars, window.bool_vars, window.optional_enabled_vars, window.choice_vars = {}, {}, {}, {}
        window.destroyed = []
        window.root = type("Root", (), {"destroy": lambda _: window.destroyed.append(1)})()
        for name in ("_update_mqtt_visibility", "_apply_tooltips", "_mark_saved", "_port_changed", "refresh_ports"):
            setattr(window, name, lambda: None)
        window._tracked_variables = lambda: []
        return window

    def check_unknown_board_names_the_setting(self, module) -> None:
        for language, board, expected in (
            ("en", "Foo", "Setting board: Unknown value Foo"),
            ("de", "Bar", "Setting board: Unknown value Bar"),
        ):
            module.set_language(language, self.directory / "i18n")
            window = self.load_window(module, board, {"ESP32 DevKit": "ESP32 DevKit"})
            try:
                window._load()
            except module.ConfigError as error:
                self.fail("_load() пропустил ошибку неизвестной платы {!r}: {}".format(board, error))
            self.assertEqual(window.errors, [("Settings read error", expected)])
            self.assertEqual(window.destroyed, [1])

    def check_known_board_is_shown_by_its_label(self, module) -> None:
        for board, label in (("ESP32 DevKit", "Dev"), ("LILYGO", "Lily")):
            window = self.load_window(module, board, {"ESP32 DevKit": "Dev", "LILYGO": "Lily"})
            window._load()
            self.assertEqual(window.errors, [])
            self.assertEqual(window.board_var.variable.get(), label, board)
            self.assertEqual(window.destroyed, [])

    def test_unknown_board_names_the_setting(self) -> None:
        self.check_unknown_board_names_the_setting(configurator)

    def test_known_board_is_shown_by_its_label(self) -> None:
        self.check_known_board_is_shown_by_its_label(configurator)

    def test_close_keeps_the_saved_language(self) -> None:
        self.check_close_keeps_the_language(configurator)

    def test_language_selection_is_saved_and_announced(self) -> None:
        self.check_language_selection_is_saved_and_announced(configurator)

    def test_close_and_finish_remove_the_image_folder(self) -> None:
        self.check_close_and_finish_remove_the_image_folder(configurator)

    def test_process_gets_the_environment_and_failed_start_removes_the_image(self) -> None:
        self.check_process_gets_the_environment_and_failed_start_removes_the_image(configurator)

    def test_unknown_label_is_a_translated_config_error(self) -> None:
        self.check_unknown_label_is_a_translated_config_error(configurator)

    def test_unknown_firmware_language_names_the_setting(self) -> None:
        self.check_unknown_firmware_language_names_the_setting(configurator)


class RealWindowTests(unittest.TestCase):
    """Настоящие ConfiguratorWindow.__init__ и main() на подменённом tkinter (FakeToolkit)."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.counter = 0

    def tearDown(self) -> None:
        configurator.set_language("ru")
        self.temporary.cleanup()

    def scenario(self, drop_russian_firmware_language=False, broken_dictionary=False):
        """Свежий проект (копии файлов настроек и языков) и каталог словарей: (проект, словари)."""
        self.counter += 1
        project = self.base / "project{}".format(self.counter)
        project.mkdir()
        for name in ("Samovar_ini.h", "user_config_override.example.h", "lang_ru.h", "lang_en.h"):
            shutil.copy(str(ROOT / name), str(project / name))
        if drop_russian_firmware_language:
            (project / "lang_ru.h").unlink()
        dictionaries = self.base / "i18n{}".format(self.counter)
        dictionaries.mkdir()
        shutil.copy(str(DICTIONARY_DIR / "en.json"), str(dictionaries / "en.json"))
        if broken_dictionary:
            (dictionaries / "de.json").write_text("{not json", encoding="utf-8")
        return project, dictionaries

    @contextlib.contextmanager
    def toolkit(self, module):
        toolkit = FakeToolkit()
        prefs = self.base / "prefs.json"
        prefs.write_text("{}", encoding="utf-8")
        with mock.patch.dict(sys.modules, toolkit.modules()), \
                mock.patch.object(module.load_user_prefs, "__defaults__", (prefs, None)), \
                mock.patch.object(module.save_user_prefs, "__defaults__", (prefs,)), \
                mock.patch.object(module, "list_serial_ports", lambda *args: []), \
                mock.patch.object(module.threading, "Thread"):
            yield toolkit

    def check_choice_variables_are_bound_to_comboboxes(self, module) -> None:
        project, dictionaries = self.scenario()
        module.set_language("en", dictionaries)
        with self.toolkit(module) as toolkit:
            window = module.ConfiguratorWindow(toolkit.root, module.SamovarConfig(project), "pio")
        self.assertEqual(toolkit.errors, [])
        combos = [widget for widget in toolkit.widgets if widget.kind == "Combobox"]

        def combo_of(name, choice):
            found = [combo for combo in combos if combo.kwargs.get("textvariable") is choice.variable]
            self.assertEqual(len(found), 1, "{}: комбобоксов с переменной выбора: {}".format(name, len(found)))
            return found[0]

        variables = {"board": window.board_var, **window.choice_vars}
        self.assertEqual(
            sorted(variables), ["SAMOVAR_LANG", "atmospheric_sensor", "board", "column_pressure_sensor", "regulator"]
        )
        for name, choice in variables.items():
            combo = combo_of(name, choice)
            self.assertEqual(combo.kwargs["values"], tuple(choice.labels.values()), name)
            for identifier, label in choice.labels.items():
                combo.kwargs["textvariable"].set(label)
                self.assertEqual(choice.get(), identifier, "{}: выбрана подпись {!r}".format(name, label))
                self.assertEqual(window._state()[name], identifier, "{}: выбрана подпись {!r}".format(name, label))
        self.assertEqual(window.choice_vars["SAMOVAR_LANG"].labels, {"ru": "Русский", "en": "English"})

        section_combo = combo_of("раздел", window.section_var)
        handlers = [call.args[1] for call in section_combo.bind.call_args_list if call.args[0] == "<<ComboboxSelected>>"]
        self.assertEqual(len(handlers), 1, "у списка разделов нет обработчика выбора")
        for section in module.SECTIONS:
            self.assertEqual(window.section_var.labels[section], module.tr(section), section)
            for frame in window.section_frames.values():
                frame.reset_mock()
            section_combo.kwargs["textvariable"].set(window.section_var.labels[section])
            try:
                handlers[0]()
            except Exception as error:
                self.fail("выбор раздела {!r} закончился исключением {!r}".format(section, error))
            raised = [name for name, frame in window.section_frames.items() if frame.tkraise.called]
            self.assertEqual(raised, [section], "выбран раздел {!r}".format(window.section_var.labels[section]))

    def check_main_reports_window_build_errors(self, module) -> None:
        title = "Cannot open the configurator window"
        for name, options, expected in (
            ("нет lang_ru.h", {"drop_russian_firmware_language": True}, "lang_ru.h"),
            ("битый словарь de.json", {"broken_dictionary": True}, "de.json"),
        ):
            project, dictionaries = self.scenario(**options)
            with self.toolkit(module) as toolkit:
                try:
                    code = module.main([
                        "--project-root", str(project), "--pio", "pio",
                        "--language", "en", "--i18n-dir", str(dictionaries),
                    ])
                except Exception as error:
                    self.fail("{}: main() пропустил {}: {}".format(name, type(error).__name__, error))
            self.assertEqual(code, 1, "{}: код выхода".format(name))
            self.assertEqual(len(toolkit.errors), 1, "{}: сообщение об ошибке не показано".format(name))
            self.assertEqual(toolkit.errors[0][0], title, name)
            self.assertIn(expected, toolkit.errors[0][1], name)
            self.assertEqual(toolkit.root.destroy.call_count, 1, "{}: окно не закрыто".format(name))
            self.assertFalse(toolkit.root.mainloop.called, "{}: работа продолжилась".format(name))
        project, dictionaries = self.scenario()
        with self.toolkit(module) as toolkit:
            code = module.main([
                "--project-root", str(project), "--pio", "pio",
                "--language", "en", "--i18n-dir", str(dictionaries),
            ])
        self.assertEqual((code, toolkit.errors), (0, []))
        self.assertTrue(toolkit.root.mainloop.called)

    def test_choice_variables_are_bound_to_comboboxes(self) -> None:
        self.check_choice_variables_are_bound_to_comboboxes(configurator)

    def test_main_reports_window_build_errors(self) -> None:
        self.check_main_reports_window_build_errors(configurator)


class MutationTests(unittest.TestCase):
    """Правки логики на временных копиях модуля: проверка обязана упасть своим содержательным сообщением."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.counter = 0
        self.helper = MechanismTests("test_translation_lookup_is_strict_and_two_languages_differ")
        self.helper.setUp()
        self.window = WindowBehaviorTests("test_close_keeps_the_saved_language")
        self.window.setUp()

    def tearDown(self) -> None:
        self.helper.tearDown()
        self.window.tearDown()
        self.temporary.cleanup()

    def mutant(self, old: str, new: str):
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertEqual(source.count(old), 1, old)
        self.counter += 1
        name = "mutant_configurator_{}".format(self.counter)
        path = Path(self.temporary.name) / (name + ".py")
        path.write_text(source.replace(old, new, 1), encoding="utf-8")
        return load_module(path, name)

    def assert_check_fails(self, check, module, expected: str) -> None:
        with self.assertRaises(AssertionError) as raised:
            check(module)
        message = str(raised.exception)
        self.assertIn(expected, message)
        print("  мутация -> {}".format(message.replace("\n", " ")[:160]))

    def test_missing_key_falling_back_to_source_text_is_detected(self) -> None:
        module = self.mutant("return _strings[text]", "return _strings.get(text, text)")
        try:
            self.assert_check_fails(self.helper.check_translation, module, "TranslationError not raised")
        finally:
            del sys.modules[module.__name__]

    def test_descriptions_that_skip_macro_description_are_detected(self) -> None:
        module = self.mutant(
            "descriptions[spec.macro] = macro_description(spec.macro, description)",
            "descriptions[spec.macro] = description",
        )
        try:
            self.assert_check_fails(self.helper.check_descriptions, module, "не запросил описания")
        finally:
            del sys.modules[module.__name__]

    def test_option_descriptions_that_skip_macro_description_are_detected(self) -> None:
        module = self.mutant(
            'options.append("{}: {}".format(tr(label), macro_description(macro, description)))',
            'options.append("{}: {}".format(tr(label), description))',
        )
        try:
            self.assert_check_fails(self.helper.check_descriptions, module, "не запросил описания")
        finally:
            del sys.modules[module.__name__]

    def test_firmware_language_that_is_always_enabled_is_detected(self) -> None:
        module = self.mutant(
            'override.set_macro("SAMOVAR_LANG", language != SOURCE_LANGUAGE, language)',
            'override.set_macro("SAMOVAR_LANG", True, language)',
        )
        try:
            self.assert_check_fails(self.helper.check_language_save, module, "язык ru")
        finally:
            del sys.modules[module.__name__]

    def run_window_mutation(self, old: str, new: str, check_name: str, expected: str) -> None:
        module = self.mutant(old, new)
        try:
            self.assert_check_fails(getattr(self.window, check_name), module, expected)
        finally:
            del sys.modules[module.__name__]

    def test_close_that_rewrites_prefs_without_language_is_detected(self) -> None:
        self.run_window_mutation(
            """        prefs = load_user_prefs(i18n_dir=current_i18n_dir())
        prefs.update({
            "port": self.port_var.get().strip(),
            "geometry": self.root.geometry(),
        })
        save_user_prefs(prefs)
""",
            """        save_user_prefs({"port": self.port_var.get().strip(), "geometry": self.root.geometry()})
""",
            "check_close_keeps_the_language", "'language': 'en'",
        )

    def test_language_selection_that_is_not_saved_is_detected(self) -> None:
        self.run_window_mutation(
            """        save_user_prefs(prefs)
        self.messagebox.showinfo(""",
            """        self.messagebox.showinfo(""",
            "check_language_selection_is_saved_and_announced", "выбран Deutsch",
        )

    def test_language_selection_without_message_is_detected(self) -> None:
        self.run_window_mutation(
            """        self.messagebox.showinfo(
            tr("Язык интерфейса"), tr("Язык будет применён после перезапуска конфигуратора.")
        )
""",
            "        pass\n",
            "check_language_selection_is_saved_and_announced", "Restart the configurator",
        )

    def test_finish_without_image_cleanup_is_detected(self) -> None:
        self.run_window_mutation(
            "    def _finish_action(self, code: int) -> None:\n        self._cleanup_fs_image()\n",
            "    def _finish_action(self, code: int) -> None:\n",
            "check_close_and_finish_remove_the_image_folder", "finish: каталог образа остался",
        )

    def test_close_without_image_cleanup_is_detected(self) -> None:
        self.run_window_mutation(
            "            terminate_process_tree(self.process)\n        self._cleanup_fs_image()\n        prefs = ",
            "            terminate_process_tree(self.process)\n        prefs = ",
            "check_close_and_finish_remove_the_image_folder", "close: каталог образа остался",
        )

    def test_process_started_without_environment_is_detected(self) -> None:
        self.run_window_mutation(
            "                env=env,\n", "                env=None,\n",
            "check_process_gets_the_environment_and_failed_start_removes_the_image", "PLATFORMIO_DATA_DIR",
        )

    def test_failed_process_start_that_keeps_the_image_is_detected(self) -> None:
        self.run_window_mutation(
            "        except OSError as error:\n            self._cleanup_fs_image()\n            self.messagebox.showerror(tr(\"Не удалось запустить PlatformIO\")",
            "        except OSError as error:\n            self.messagebox.showerror(tr(\"Не удалось запустить PlatformIO\")",
            "check_process_gets_the_environment_and_failed_start_removes_the_image", "каталог образа остался",
        )

    def test_bare_key_error_on_unknown_label_is_detected(self) -> None:
        self.run_window_mutation(
            """        label = self.variable.get()
        if label not in self.identifiers:
            raise ConfigError(tr("Неизвестная подпись варианта: {}").format(label))
        return self.identifiers[label]
""",
            "        return self.identifiers[self.variable.get()]\n",
            "check_unknown_label_is_a_translated_config_error", "голый KeyError",
        )

    def test_load_error_that_does_not_name_the_setting_is_detected(self) -> None:
        self.run_window_mutation(
            """tr("Настройка {}: {}").format(key, error)""", "str(error)",
            "check_unknown_firmware_language_names_the_setting", "Setting SAMOVAR_LANG",
        )

    def test_build_that_does_not_paint_the_log_line_first_is_detected(self) -> None:
        module = self.mutant(
            "        self.root.update_idletasks()\n        try:\n            result = subprocess.run(",
            "        try:\n            result = subprocess.run(",
        )
        helper = LittleFsImageTests("test_log_line_is_painted_before_the_blocking_build")
        helper.setUp()
        try:
            self.assert_check_fails(
                helper.check_log_line_is_painted_before_the_blocking_build, module,
                "['save', 'log', 'run'] != ['save', 'log', 'update', 'run']",
            )
        finally:
            helper.tearDown()
            del sys.modules[module.__name__]

    def run_littlefs_mutation(self, old: str, new: str, check_name: str, expected: str) -> None:
        module = self.mutant(old, new)
        helper = LittleFsImageTests(check_name)
        helper.setUp()
        try:
            self.assert_check_fails(getattr(helper, check_name), module, expected)
        finally:
            helper.tearDown()
            del sys.modules[module.__name__]

    def test_image_built_without_saving_settings_is_detected(self) -> None:
        self.run_littlefs_mutation(
            "        if not self.save(show_success=False):\n            return None\n        language = ",
            "        language = ",
            "check_settings_are_saved_before_the_image_is_built",
            "образ собирается не после сохранения настроек",
        )

    def test_image_built_after_failed_save_is_detected(self) -> None:
        self.run_littlefs_mutation(
            "        if not self.save(show_success=False):\n            return None\n        language = ",
            "        self.save(show_success=False)\n        language = ",
            "check_failed_save_stops_the_image_build", "сборка продолжилась после отказа сохранения",
        )

    def test_image_build_without_process_start_options_is_detected(self) -> None:
        self.run_littlefs_mutation(
            "timeout=120,\n                **process_start_options(),\n",
            "timeout=120,\n",
            "check_image_build_gets_the_process_start_options", "сборка образа без параметра creationflags",
        )

    def test_board_set_outside_the_error_handler_is_detected(self) -> None:
        self.run_window_mutation(
            """        for key, variable in {"board": self.board_var, **self.choice_vars}.items():""",
            """        self.board_var.set(str(state["board"]))
        for key, variable in self.choice_vars.items():""",
            "check_unknown_board_names_the_setting", "_load() пропустил ошибку неизвестной платы 'Foo'",
        )

    def test_board_that_is_never_loaded_is_detected(self) -> None:
        self.run_window_mutation(
            """{"board": self.board_var, **self.choice_vars}.items()""", "self.choice_vars.items()",
            "check_unknown_board_names_the_setting", "[] != [('Settings read error'",
        )

    def run_real_window_mutation(self, old: str, new: str, check_name: str, expected: str) -> None:
        module = self.mutant(old, new)
        helper = RealWindowTests(check_name)
        helper.setUp()
        try:
            self.assert_check_fails(getattr(helper, check_name), module, expected)
        finally:
            helper.tearDown()
            del sys.modules[module.__name__]

    def test_main_that_misses_translation_errors_is_detected(self) -> None:
        self.run_real_window_mutation(
            "    except (ConfigError, TranslationError) as error:\n        from tkinter import messagebox",
            "    except ConfigError as error:\n        from tkinter import messagebox",
            "check_main_reports_window_build_errors", "битый словарь de.json: main() пропустил TranslationError",
        )

    def test_main_that_exits_with_zero_after_window_error_is_detected(self) -> None:
        self.run_real_window_mutation(
            "        root.destroy()\n        return 1\n", "        root.destroy()\n        return 0\n",
            "check_main_reports_window_build_errors", "0 != 1 : нет lang_ru.h: код выхода",
        )

    def test_main_that_hides_the_window_error_is_detected(self) -> None:
        self.run_real_window_mutation(
            '        messagebox.showerror(tr("Не удалось открыть окно конфигуратора"), str(error))\n', "",
            "check_main_reports_window_build_errors", "0 != 1 : нет lang_ru.h: сообщение об ошибке не показано",
        )

    def test_combobox_bound_to_the_wrapper_instead_of_the_tk_variable_is_detected(self) -> None:
        self.run_real_window_mutation(
            """            frames[section], textvariable=variable.variable,
            values=tuple(variable.labels.values()), state="readonly",""",
            """            frames[section], textvariable=variable,
            values=tuple(variable.labels.values()), state="readonly",""",
            "check_choice_variables_are_bound_to_comboboxes", "board: комбобоксов с переменной выбора: 0",
        )

    def test_section_list_bound_to_the_wrapper_is_detected(self) -> None:
        self.run_real_window_mutation(
            "section_row, textvariable=self.section_var.variable,", "section_row, textvariable=self.section_var,",
            "check_choice_variables_are_bound_to_comboboxes", "раздел: комбобоксов с переменной выбора: 0",
        )

    def test_section_selected_by_label_instead_of_identifier_is_detected(self) -> None:
        self.run_real_window_mutation(
            "self.section_frames[self.section_var.get()].tkraise()",
            "self.section_frames[self.section_var.variable.get()].tkraise()",
            "check_choice_variables_are_bound_to_comboboxes", "выбор раздела 'Основные' закончился исключением KeyError('Main')",
        )

    def test_section_selection_without_handler_is_detected(self) -> None:
        self.run_real_window_mutation(
            'self.section_combo.bind("<<ComboboxSelected>>", self._section_selected)', "pass",
            "check_choice_variables_are_bound_to_comboboxes", "у списка разделов нет обработчика выбора",
        )

    def test_firmware_language_that_is_never_enabled_is_detected(self) -> None:
        module = self.mutant(
            'override.set_macro("SAMOVAR_LANG", language != SOURCE_LANGUAGE, language)',
            'override.set_macro("SAMOVAR_LANG", False, language)',
        )
        try:
            self.assert_check_fails(self.helper.check_language_save, module, "False != True : язык en")
        finally:
            del sys.modules[module.__name__]

    def test_source_rules_catch_new_literal_and_new_tr_call_in_the_real_file(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        _, problems = analyze_source(source + '\n\ndef added():\n    return "Русская строка без метки"\n')
        self.assertEqual(len(problems), 1)
        self.assertIn("русский литерал вне tr/N_ без i18n-keep", problems[0])
        print("  мутация -> {}".format(problems[0]))
        keys, problems = analyze_source(source + '\n\ndef added():\n    return tr("Новая строка")\n')
        self.assertEqual(problems, [])
        missing = dictionary_problems(
            write_dictionary(Path(self.temporary.name), "en", "English", pseudo_strings(SOURCE_KEYS),
                             {macro: "t" for macro in REQUIRED_MACROS}),
            keys, REQUIRED_MACROS,
        )
        self.assertEqual(missing, ["нет перевода ключа 'Новая строка'"])
        print("  мутация -> {}".format(missing[0]))

    def test_disabled_placeholder_check_is_detected(self) -> None:
        path = write_dictionary(
            Path(self.temporary.name), "en", "English", {"Файл {} из {}": "File {}"}, {},
        )
        self.assertEqual(
            dictionary_problems(path, ["Файл {} из {}"], []), ["не совпадают плейсхолдеры 'Файл {} из {}': 'File {}'"]
        )
        with mock.patch.object(sys.modules[__name__], "PLACEHOLDER_RE", re.compile(r"(?!x)x")):
            self.assertEqual(dictionary_problems(path, ["Файл {} из {}"], []), [])
        print("  мутация -> без проверки плейсхолдеров дефектный перевод проходит (список нарушений пуст), тест выше падает на assertEqual")


def dump_keys() -> None:
    skeleton = {
        "language_name": "",
        "strings": {key: "" for key in SOURCE_KEYS},
        "macro_descriptions": {macro: "" for macro in REQUIRED_MACROS},
    }
    print(json.dumps(skeleton, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    if "--dump-keys" in sys.argv:
        dump_keys()
        raise SystemExit(0)
    print("ключей tr()/N_(): {}, макросов описаний: {}".format(len(SOURCE_KEYS), len(REQUIRED_MACROS)))
    unittest.main(verbosity=2)
