#!/usr/bin/env python3
"""Behavioral check for пункт 37: приёмник строк (JsonStringPrint) обязан честно
сообщать об отказе, а не всегда врать "успех".

До фикса write() комментарий утверждал, что String "растёт сама" и частичной записи
не бывает, поэтому write() безусловно возвращал полный size, а toJsonString() и
spiffsEditorJsonEscape() не проверяли возврат json_write_escaped(). На самом деле
Arduino String::concat() может отказать при нехватке памяти под reserve()/realloc(),
и старый код (per-char цикл через operator+=, который отбрасывает bool от concat())
эту неудачу проглатывал молча - часть символов терялась, а вызывающий код был уверен,
что всё записано.

Компилирует РЕАЛЬНЫЕ тела JsonStringPrint, json_write_escaped, toJsonString и
spiffsEditorJsonEscape (через smoke_helpers) поверх мока String, у которого concat()
может имитировать нехватку памяти (атомарно - как у настоящего Arduino String: либо
весь фрагмент влезает, либо строка не трогается). Проверяет:
  1. JsonStringPrint::write() возвращает 0 (не полный size) при отказе concat().
  2. json_write_escaped() из-за этого возвращает false.
  3. toJsonString()/spiffsEditorJsonEscape() замечают false и логируют это в Serial -
     если бы проверки не было, лог остался бы пуст даже при потере данных.
  4. В штатном режиме (памяти достаточно) ничего не логируется и строка экранируется
     корректно - тест не должен требовать лога всегда, только при реальном отказе.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_helpers import extract_function_body, extract_braced_block_after

ROOT = Path(__file__).resolve().parents[1]

JSON_WRITE_ESCAPED_SIGNATURE = (
    "inline bool json_write_escaped(Print& out, const char* text, size_t length)"
)
JSON_STRING_PRINT_TOKEN = "class JsonStringPrint : public Print {"
TO_JSON_STRING_SIGNATURE = "inline String toJsonString(const String& s)"
SPIFFS_EDITOR_JSON_ESCAPE_SIGNATURE = "static String spiffsEditorJsonEscape(const String& value)"

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <cstdio>
#include <cstddef>
#include <cstring>
#include <string>
#include <vector>

// Глобальный лимит "памяти" на текущий String - имитирует отказ Arduino
// String::concat() при нехватке кучи. SIZE_MAX по умолчанию - обычная работа.
static size_t g_capacity_limit = static_cast<size_t>(-1);

// Минимальный двойник Arduino String с АТОМАРНЫМ concat(): как и у настоящего
// Arduino String, при нехватке места под весь фрагмент строка не трогается вовсе -
// частичной записи внутри одного concat() быть не может.
class String {
 public:
  String() = default;
  String(const char* s) : v(s ? s : "") {}
  size_t length() const { return v.size(); }
  const char* c_str() const { return v.c_str(); }
  void reserve(size_t) {}
  bool concat(char c) {
    if (v.size() + 1 > g_capacity_limit) return false;
    v += c;
    return true;
  }
  bool concat(const char* s, size_t len) {
    if (!s) return false;
    if (len == 0) return true;
    if (v.size() + len > g_capacity_limit) return false;
    // Настоящая String::concat(const char*, unsigned int) в ядре Arduino-ESP32
    // (WString.cpp) всегда делает memcpy_P(dst, s, len + 1) - читает байт s[len],
    // рассчитывая на нулевой терминатор сразу за данными. Повторяем именно это
    // чтение здесь (а не std::string::append(s, len), которое трогает только
    // len байт), чтобы под ASan (-fsanitize=address, см. compile_cmd ниже) харнесс
    // ловил переполнение буфера у вызывающего - как для unicodeEscape[6] без
    // терминатора в json_write_escaped().
    volatile char guard = s[len];
    (void)guard;
    v.append(s, len);
    return true;
  }
  String& operator+=(char c) { concat(c); return *this; }
  String& operator+=(const String& o) { v += o.v; return *this; }
  std::string v;
};

// Минимальный двойник Arduino Print.
class Print {
 public:
  virtual ~Print() {}
  virtual size_t write(uint8_t value) = 0;
  virtual size_t write(const uint8_t* buffer, size_t size) = 0;
};

// Двойник Serial.println(F(...)): копит вызовы, чтобы тест видел, заметила ли
// вызывающая функция отказ приёмника.
static std::vector<std::string> g_serial_log;
struct SerialStub {
  void println(const char* s) { g_serial_log.push_back(s); }
};
static SerialStub Serial;
static inline const char* F(const char* s) { return s; }

@JSON_STRING_PRINT@

@JSON_WRITE_ESCAPED@

@TO_JSON_STRING@

@SPIFFS_EDITOR_JSON_ESCAPE@

static int failures = 0;

static void expect(bool cond, const char* what) {
  if (!cond) {
    fprintf(stderr, "FAIL: %s\n", what);
    failures++;
  }
}

int main() {
  // 1) JsonStringPrint::write() честно возвращает 0, а не size, когда concat()
  //    отказал - и строка не тронута (атомарность), а не обрезана посередине.
  {
    g_capacity_limit = 3;
    String target;
    JsonStringPrint sink(target);
    size_t written = sink.write(reinterpret_cast<const uint8_t*>("abcdef"), 6);
    expect(written == 0, "write(buffer,6) при лимите 3 должен вернуть 0, а не 6");
    expect(target.length() == 0, "при отказе concat() строка не должна меняться");
  }
  {
    g_capacity_limit = 0;
    String target;
    JsonStringPrint sink(target);
    size_t written = sink.write(static_cast<uint8_t>('x'));
    expect(written == 0, "write(byte) при лимите 0 должен вернуть 0, а не 1");
  }
  // Однобайтовый write() тоже должен успевать в штатном случае.
  {
    g_capacity_limit = static_cast<size_t>(-1);
    String target;
    JsonStringPrint sink(target);
    size_t written = sink.write(static_cast<uint8_t>('x'));
    expect(written == 1, "write(byte) в штатном случае должен вернуть 1");
    expect(target.c_str() == std::string("x"), "write(byte) должен дописать байт в String");
  }

  // 2) json_write_escaped() замечает отказ приёмника и возвращает false.
  {
    g_capacity_limit = 2;
    String target;
    JsonStringPrint sink(target);
    bool ok = json_write_escaped(sink, "ab\"cd", 5);
    expect(!ok, "json_write_escaped() должен вернуть false при отказе приёмника");
  }
  {
    g_capacity_limit = static_cast<size_t>(-1);
    String target;
    JsonStringPrint sink(target);
    bool ok = json_write_escaped(sink, "ab\"cd", 5);
    expect(ok, "json_write_escaped() должен вернуть true, когда памяти достаточно");
  }
  // Управляющий байт вне именованных escape (\b \f \n \r \t) идёт через
  // unicodeEscape[6] в json_write_escaped() - локальный стековый массив БЕЗ
  // нулевого терминатора. Раньше write(buffer,size) звал String::concat(cstr,size)
  // прямо на нём, а concat() читает size+1 байт - чтение unicodeEscape[6] за
  // границей массива. Под ASan (см. compile_cmd) это должно упасть, если регрессия
  // вернётся; сейчас (после фикса write() через терминированную копию) должно пройти.
  {
    g_capacity_limit = static_cast<size_t>(-1);
    String target;
    JsonStringPrint sink(target);
    bool ok = json_write_escaped(sink, "a\x01z", 3);
    expect(ok, "json_write_escaped() с control-байтом 0x01 не должен падать/URB под ASan");
    expect(target.c_str() == std::string("a\\u0001z"),
           "control-байт 0x01 должен экранироваться в \\u0001");
  }

  // 3) toJsonString()/spiffsEditorJsonEscape() замечают неуспех и логируют его -
  //    вызывающий код перестаёт молча доверять "всегда успех".
  {
    g_serial_log.clear();
    g_capacity_limit = static_cast<size_t>(-1);
    String ok1 = toJsonString(String("hello"));
    expect(ok1.c_str() == std::string("\"hello\""), "toJsonString() в штатном случае");
    expect(g_serial_log.empty(), "toJsonString() не должен логировать, когда всё влезло");

    g_serial_log.clear();
    g_capacity_limit = 3;
    String truncated = toJsonString(String("hello world"));
    expect(!g_serial_log.empty(),
           "toJsonString() обязан заметить отказ json_write_escaped() и залогировать его");
  }
  {
    g_serial_log.clear();
    g_capacity_limit = static_cast<size_t>(-1);
    String ok2 = spiffsEditorJsonEscape(String("hello"));
    expect(ok2.c_str() == std::string("hello"), "spiffsEditorJsonEscape() в штатном случае");
    expect(g_serial_log.empty(), "spiffsEditorJsonEscape() не должен логировать без отказа");

    g_serial_log.clear();
    g_capacity_limit = 3;
    String truncated2 = spiffsEditorJsonEscape(String("hello world"));
    expect(!g_serial_log.empty(),
           "spiffsEditorJsonEscape() обязан заметить отказ json_write_escaped() и залогировать");
  }

  if (failures) {
    fprintf(stderr, "%d проверок провалено\n", failures);
    return 1;
  }
  printf("json sink OOM honesty: все проверки прошли\n");
  return 0;
}
'''


def build_cpp_source() -> str:
    string_utils = (ROOT / "string_utils.h").read_text(encoding="utf-8")
    spiffs_editor = (ROOT / "SPIFFSEditor.h").read_text(encoding="utf-8")

    json_string_print_body, _ = extract_braced_block_after(string_utils, JSON_STRING_PRINT_TOKEN)
    json_string_print = "class JsonStringPrint : public Print {" + json_string_print_body + "};"

    json_write_escaped = (
        "static bool json_write_escaped(Print& out, const char* text, size_t length) {\n"
        + extract_function_body(string_utils, JSON_WRITE_ESCAPED_SIGNATURE) + "\n}"
    )
    to_json_string = (
        "static String toJsonString(const String& s) {\n"
        + extract_function_body(string_utils, TO_JSON_STRING_SIGNATURE) + "\n}"
    )
    spiffs_editor_json_escape = (
        "static String spiffsEditorJsonEscape(const String& value) {\n"
        + extract_function_body(spiffs_editor, SPIFFS_EDITOR_JSON_ESCAPE_SIGNATURE) + "\n}"
    )

    source = HARNESS_TEMPLATE
    source = source.replace("@JSON_STRING_PRINT@", json_string_print)
    source = source.replace("@JSON_WRITE_ESCAPED@", json_write_escaped)
    source = source.replace("@TO_JSON_STRING@", to_json_string)
    source = source.replace("@SPIFFS_EDITOR_JSON_ESCAPE@", spiffs_editor_json_escape)
    return source


def main() -> int:
    try:
        source = build_cpp_source()
    except ValueError as exc:
        print(f"json sink OOM honesty smoke failed: {exc}")
        return 1

    with tempfile.TemporaryDirectory(prefix="samovar-json-sink-oom-") as tmpdir:
        cpp_path = Path(tmpdir) / "harness.cpp"
        cpp_path.write_text(source, encoding="utf-8")
        binary_path = Path(tmpdir) / "harness"
        compile_cmd = [
            # -fsanitize=address - без него однобайтовое чтение за границей маленького
            # стекового массива (см. concat() выше и unicodeEscape[6] в
            # json_write_escaped()) почти всегда молча "срабатывает": лишний байт
            # читается из чужой памяти стека, не падает и ничего не портит. ASan
            # превращает это неопределённое поведение в детерминированный отказ теста.
            "g++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
            "-fsanitize=address", "-g", "-O0",
            str(cpp_path), "-o", str(binary_path),
        ]
        compiled = subprocess.run(compile_cmd, capture_output=True, text=True)
        if compiled.returncode != 0:
            print("json sink OOM honesty smoke failed:")
            print(" - харнесс не компилируется:")
            print(compiled.stderr)
            return 1
        run = subprocess.run([str(binary_path)], capture_output=True, text=True)
        if run.returncode != 0:
            print("json sink OOM honesty smoke failed:")
            print(run.stdout)
            print(run.stderr)
            return 1

    print("json sink OOM honesty smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
