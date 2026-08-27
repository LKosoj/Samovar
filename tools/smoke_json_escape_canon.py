#!/usr/bin/env python3
"""Единый канон экранирования JSON-строк: json_write_escaped() в string_utils.h.

До этого теста в прошивке было четыре независимые реализации экранирования для JSON
(toJsonString, jsonPrintEscaped, runtimeEventWriteEscaped, spiffsEditorJsonEscape), и две
из них давали НЕВАЛИДНЫЙ JSON на управляющих байтах <0x20 (кроме \\n \\r \\t) - сырой байт
шёл в вывод как есть. Теперь все четыре - тонкие делегаты поверх одной функции.

Тест из двух частей:
1. Архитектурная (без компиляции): в теле каждой из четырёх обёрток должен быть вызов
   json_write_escaped(...) - это не даёт будущей правке тихо вернуть инлайновую копию
   экранирования в одном месте и забыть про остальные три.
2. Поведенческая: один g++-харнесс с НАСТОЯЩИМИ телами всех пяти функций (канон + 4
   обёртки), прогнанный на ДВУХ разных значениях (правило AGENTS.md против теста на одном
   хардкод-значении: A - латиница/спецсимволы/управляющие байты, B - кириллица). Каждая
   выведенная строка разбирается настоящим json.loads() - невалидный JSON даёт
   содержательный JSONDecodeError, а не молчаливый провал, - и сверяется побайтово с
   исходной строкой: это ловит и потерю данных, и порчу UTF-8.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

# A: латиница, кавычка, обратный слэш, \n\r\t, DEL и управляющие байты вне \n\r\t.
# B: кириллица (многобайтовый UTF-8) вместе с теми же опасными символами - два разных
# значения нужны, чтобы тест не проходил на одном подогнанном под ответ примере.
VALUE_A = "tag<script>x</script>\"quo\\back\nline\ttab\x01\x1f\x7fend"
VALUE_B = "Привет, мир! <тест> \"кавычки\" \x02конец"

assert "<" in VALUE_A and "<" in VALUE_B, (
    "фикстуры обязаны содержать '<' - иначе тест не проверяет HTML-safety экранирование"
)
assert "</script" in VALUE_A, (
    "фикстура A обязана содержать закрывающий тег - именно он рвёт <script>-блок "
    "страницы, если '<' перестанет экранироваться"
)

JSON_WRITE_ESCAPED_SIGNATURE = (
    "inline bool json_write_escaped(Print& out, const char* text, size_t length)"
)

# (файл, сигнатура) - НАСТОЯЩИЕ обёртки, которые обязаны делегировать в json_write_escaped().
WRAPPERS = {
    "toJsonString": ("string_utils.h", "inline String toJsonString(const String& s)"),
    "jsonPrintEscaped": (
        "Samovar.ino", "static void jsonPrintEscaped(Print &out, const String &value)"
    ),
    "runtimeEventWriteEscaped": (
        "Samovar.ino", "static bool runtimeEventWriteEscaped(Print& out, const char* text, size_t length)"
    ),
    "spiffsEditorJsonEscape": (
        "SPIFFSEditor.h", "static String spiffsEditorJsonEscape(const String& value)"
    ),
}


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def check_delegates(errors: list[str]) -> None:
    """Архитектурная часть: каждая обёртка обязана звать json_write_escaped(), а не
    повторять экранирование инлайн."""
    for name, (filename, signature) in WRAPPERS.items():
        source = read(filename)
        try:
            body = extract_function_body(source, signature)
        except ValueError as exc:
            errors.append(f"{filename}: не найдено тело {name}(): {exc}")
            continue
        if "json_write_escaped(" not in body:
            errors.append(
                f"{filename}: {name}() больше не делегирует в json_write_escaped() - "
                "экранирование опять продублировали инлайн"
            )


def cpp_byte_string_literal(value: str) -> str:
    """Кодирует Python-строку в C++ строковый литерал побайтово через \\xHH: каждый
    небезопасный байт - в своём соседнем литерале. Иначе экранирование \\xHH жадно
    съедает все идущие подряд шестнадцатеричные цифры (например "\\x7fend" разобралось
    бы как один байт 0x7fe и текст "nd" - буква 'e' тоже шестнадцатеричная цифра),
    а соседние строковые литералы всегда останавливают этот захват на границе."""
    chunks: list[str] = []
    plain: list[str] = []

    def flush_plain() -> None:
        if plain:
            chunks.append('"' + "".join(plain) + '"')
            plain.clear()

    for byte in value.encode("utf-8"):
        if byte == 0x22:
            plain.append('\\"')
        elif byte == 0x5C:
            plain.append("\\\\")
        elif 0x20 <= byte < 0x7F:
            plain.append(chr(byte))
        else:
            flush_plain()
            chunks.append('"\\x%02x"' % byte)
    flush_plain()
    return " ".join(chunks) if chunks else '""'


HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <cstdio>
#include <string>

// Минимальный двойник Arduino String: только то, что реально используют пять функций ниже.
class String {
 public:
  String() = default;
  String(const char* s) : v(s ? s : "") {}
  size_t length() const { return v.size(); }
  const char* c_str() const { return v.c_str(); }
  void reserve(size_t) {}
  String& operator+=(char c) { v += c; return *this; }
  String& operator+=(const String& o) { v += o.v; return *this; }
  std::string v;
};

// Минимальный двойник Arduino Print: json_write_escaped() пишет только через
// двухаргументный write(buffer, size) - его же единственного требует фикстура
// smoke_runtime_event_ring.py, у которой однобайтового write() нет.
class Print {
 public:
  virtual ~Print() {}
  virtual size_t write(const uint8_t* buffer, size_t size) = 0;
};

// Тонкий Print-приёмник поверх String - копия JsonStringPrint из string_utils.h.
class JsonStringPrint : public Print {
 public:
  explicit JsonStringPrint(String& target) : target_(target) {}
  size_t write(const uint8_t* buffer, size_t size) override {
    for (size_t i = 0; i < size; i++) target_ += static_cast<char>(buffer[i]);
    return size;
  }
 private:
  String& target_;
};

// Минимальный двойник Arduino Serial.println(F(...)): concat() в этом тесте никогда не
// отказывает (std::string сам растёт), поэтому диагностика не печатается - заглушка
// нужна только для компиляции реальных тел toJsonString/spiffsEditorJsonEscape.
struct SerialStub {
  void println(const char* s) { (void)s; }
};
static SerialStub Serial;
static inline const char* F(const char* s) { return s; }

@DEFINITIONS@

static String wrapQuoted(const String& raw) {
  String out;
  out += '"';
  out += raw;
  out += '"';
  return out;
}

static int failures = 0;

static void emitFor(const char* label, const String& value) {
  printf("%s\n", toJsonString(value).c_str());

  String plainPrint;
  JsonStringPrint printSink(plainPrint);
  jsonPrintEscaped(printSink, value);
  printf("%s\n", wrapQuoted(plainPrint).c_str());

  String plainRuntime;
  JsonStringPrint runtimeSink(plainRuntime);
  if (!runtimeEventWriteEscaped(runtimeSink, value.c_str(), value.length())) {
    fprintf(stderr, "runtimeEventWriteEscaped вернул false для %s\n", label);
    failures++;
  }
  printf("%s\n", wrapQuoted(plainRuntime).c_str());

  printf("%s\n", wrapQuoted(spiffsEditorJsonEscape(value)).c_str());
}

int main() {
  String a(@VALUE_A@);
  String b(@VALUE_B@);
  emitFor("A", a);
  emitFor("B", b);
  return failures == 0 ? 0 : 1;
}
'''


def build_cpp_source() -> str:
    string_utils = read("string_utils.h")
    samovar = read("Samovar.ino")
    spiffs_editor = read("SPIFFSEditor.h")

    definitions = [
        "static bool json_write_escaped(Print& out, const char* text, size_t length) {\n"
        + extract_function_body(string_utils, JSON_WRITE_ESCAPED_SIGNATURE) + "\n}",
        "static String toJsonString(const String& s) {\n"
        + extract_function_body(string_utils, WRAPPERS["toJsonString"][1]) + "\n}",
        "static void jsonPrintEscaped(Print &out, const String &value) {\n"
        + extract_function_body(samovar, WRAPPERS["jsonPrintEscaped"][1]) + "\n}",
        "static bool runtimeEventWriteEscaped(Print& out, const char* text, size_t length) {\n"
        + extract_function_body(samovar, WRAPPERS["runtimeEventWriteEscaped"][1]) + "\n}",
        "static String spiffsEditorJsonEscape(const String& value) {\n"
        + extract_function_body(spiffs_editor, WRAPPERS["spiffsEditorJsonEscape"][1]) + "\n}",
    ]

    source = HARNESS_TEMPLATE.replace("@DEFINITIONS@", "\n\n".join(definitions))
    source = source.replace("@VALUE_A@", cpp_byte_string_literal(VALUE_A))
    source = source.replace("@VALUE_B@", cpp_byte_string_literal(VALUE_B))
    return source


def run_behavioral(errors: list[str]) -> None:
    source = build_cpp_source()
    with tempfile.TemporaryDirectory(prefix="samovar-json-escape-canon-") as tmp:
        src_path = Path(tmp) / "canon.cpp"
        bin_path = Path(tmp) / "canon"
        src_path.write_text(source, encoding="utf-8")
        compile_result = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(src_path), "-o", str(bin_path)],
            capture_output=True, text=True,
        )
        if compile_result.returncode != 0:
            errors.append("харнесс json_write_escaped не компилируется:\n" + compile_result.stderr)
            return
        run_result = subprocess.run(
            [str(bin_path)], capture_output=True, text=True, encoding="utf-8"
        )
        if run_result.returncode != 0:
            errors.append(
                "харнесс json_write_escaped упал:\n" + run_result.stdout + run_result.stderr
            )
            return

    lines = [line for line in run_result.stdout.split("\n") if line != ""]
    if len(lines) != 8:
        errors.append(f"ожидалось 8 строк вывода (2 значения x 4 обёртки), получено {len(lines)}: {lines}")
        return

    cases = [
        ("A", "toJsonString", VALUE_A, lines[0]),
        ("A", "jsonPrintEscaped", VALUE_A, lines[1]),
        ("A", "runtimeEventWriteEscaped", VALUE_A, lines[2]),
        ("A", "spiffsEditorJsonEscape", VALUE_A, lines[3]),
        ("B", "toJsonString", VALUE_B, lines[4]),
        ("B", "jsonPrintEscaped", VALUE_B, lines[5]),
        ("B", "runtimeEventWriteEscaped", VALUE_B, lines[6]),
        ("B", "spiffsEditorJsonEscape", VALUE_B, lines[7]),
    ]

    for value_label, wrapper_name, original, raw_line in cases:
        # Сырой (непарсенный) вывод: опасная "</script" не имеет права появиться живьём
        # (иначе HTML-страница со <script>-блоком порвётся), а экранированная форма '<'
        # обязана остаться видна - иначе ветка "character == '<'" тихо выпала из канона.
        if "</script" in raw_line:
            errors.append(
                f"{value_label}/{wrapper_name}: сырой вывод содержит небезопасную "
                f"подстроку </script: {raw_line}"
            )
        if "<" in original and "\\u003c" not in raw_line:
            errors.append(
                f"{value_label}/{wrapper_name}: '<' из исходной строки не превратился "
                f"в \\u003c - похоже, ветку экранирования '<' убрали из канона: {raw_line}"
            )
        try:
            parsed = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            errors.append(
                f"{value_label}/{wrapper_name}: вывод не разбирается как JSON ({exc}): {raw_line}"
            )
            continue
        if parsed != original:
            errors.append(
                f"{value_label}/{wrapper_name}: после json.loads строка не совпала побайтово "
                f"с исходной (потеря данных или порча UTF-8): ожидали {original!r}, "
                f"получили {parsed!r}"
            )


def main() -> int:
    errors: list[str] = []
    check_delegates(errors)
    if not errors:
        run_behavioral(errors)

    if errors:
        print("json escape canon smoke failed:")
        for error in errors:
            print(f" - {error}")
        return 1

    print("json escape canon smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
