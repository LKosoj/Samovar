#!/usr/bin/env python3
"""[T35 п.4в] /save показывает СРАЗУ ВСЕ поля вне диапазона, а не только первое.

Раньше handleSave() (WebServer.ino) выходил из циклов по kSaveU16Fields/kSaveFloatFields/
kSaveU8Fields по первой же ошибке (`return;` внутри цикла) - пользователь чинил одно поле,
отправлял форму заново и узнавал про следующее только тогда. Починка копит имена ВСЕХ
неверных полей (тот же приём, что sanitize_setup_profile_ranges() - String, растущая через
запятую) и отвечает одним 400 с конвертом {error, field, message, fields}: field/message -
первое плохое поле (обратная совместимость), fields - все, до SAVE_RANGE_ERROR_FIELD_LIMIT.

Здесь два независимых свойства.

1. Статическое: сами три цикла в handleSave() не обрываются на первом отказе (нет голого
   `return;` внутри них), копят через collect_save_bad_field(), а единственная точка отказа -
   ПОСЛЕ всех трёх циклов и ДО применения kSaveCheckboxFields/остального staged - значит,
   staged не публикуется частично ни при каком отказе диапазона.

2. Поведенческое: компилирует настоящие тела apply_save_u8_arg/apply_save_u16_arg/
   apply_save_float_arg/collect_save_bad_field/build_save_range_errors_envelope (+
   build_error_envelope/toJsonString, которые они переиспользуют) и реальный numeric_parse.h,
   гоняет несколько полей сразу (разных типов, разных причин отказа - формат и диапазon) и
   разбирает результат настоящим JSON-парсером.
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_helpers import extract_function_body, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]
WEBSERVER = ROOT / "WebServer.ino"
STRING_UTILS = ROOT / "string_utils.h"
NUMERIC_PARSE = ROOT / "numeric_parse.h"

errors: list[str] = []


def check_static(web_text: str) -> None:
    try:
        handle_save = extract_function_body(web_text, "void handleSave(AsyncWebServerRequest *request)")
    except ValueError as exc:
        errors.append(str(exc))
        return

    require_ordered_tokens(
        "handleSave collects every out-of-range field before one combined 400",
        handle_save,
        [
            "String saveBadFieldsJson;",
            "String saveFirstBadField;",
            "uint8_t saveBadFieldsCount = 0;",
            "for (const SaveU16Field &f : kSaveU16Fields)",
            "collect_save_bad_field(f.name, saveBadFieldsJson, saveFirstBadField, saveBadFieldsCount);",
            "for (const SaveFloatField &f : kSaveFloatFields)",
            "collect_save_bad_field(f.name, saveBadFieldsJson, saveFirstBadField, saveBadFieldsCount);",
            "for (const SaveU8Field &f : kSaveU8Fields)",
            "collect_save_bad_field(f.name, saveBadFieldsJson, saveFirstBadField, saveBadFieldsCount);",
            "if (saveBadFieldsCount > 0)",
            "build_save_range_errors_envelope(saveFirstBadField, saveBadFieldsJson)",
            "for (const SaveCheckboxField &f : kSaveCheckboxFields)",
        ],
        errors,
    )

    # Мутационный кейс (проверено вручную - см. отчёт): вернуть голый `return;` в один из
    # трёх циклов вместо collect_save_bad_field(...) - эта проверка обязана упасть, так как
    # ищет ИМЕННО последовательность "for (...) { collect_save_bad_field(...) }" для каждого
    # из трёх циклов, а не просто факт наличия collect_save_bad_field где-то в функции.
    for loop_header, loop_field_kind in (
        ("for (const SaveU16Field &f : kSaveU16Fields) {", "kSaveU16Fields"),
        ("for (const SaveFloatField &f : kSaveFloatFields) {", "kSaveFloatFields"),
        ("for (const SaveU8Field &f : kSaveU8Fields) {", "kSaveU8Fields"),
    ):
        loop_start = handle_save.find(loop_header)
        if loop_start < 0:
            errors.append(f"handleSave: loop over {loop_field_kind} not found in expected form")
            continue
        loop_end = handle_save.find("\n  }", loop_start)
        loop_body = handle_save[loop_start:loop_end]
        if "collect_save_bad_field(" not in loop_body:
            errors.append(f"handleSave: loop over {loop_field_kind} must call collect_save_bad_field on failure")
        if re.search(r"\breturn;\s*$", loop_body.strip()) or "      return;\n" in loop_body:
            errors.append(
                f"handleSave: loop over {loop_field_kind} still returns early on the first bad "
                "field instead of collecting all of them"
            )

    # staged публикуется одним queue_profile_operation() в конце - здесь фиксируем, что
    # отказ по накопленным полям происходит СТРОГО до него (staged.* уже не пишется после
    # combined-ответа ни для чекбоксов/цветов/DS-адресов, ни тем более для commit).
    combined_check_pos = handle_save.find("if (saveBadFieldsCount > 0)")
    queue_pos = handle_save.find("queue_profile_operation(")
    if combined_check_pos < 0 or queue_pos < 0 or combined_check_pos > queue_pos:
        errors.append("handleSave: combined range-error response must be sent before queue_profile_operation()")


CPP_HARNESS_TEMPLATE = r"""
#include <cstdint>
#include <string>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <cerrno>
#include <cfloat>
#include <climits>
#include <cmath>
#include <map>
using namespace std;

class String {
 public:
  String() {}
  String(const char* s) : v(s ? s : "") {}
  String(char c) : v(1, c) {}
  void reserve(unsigned int) {}
  unsigned int length() const { return (unsigned int)v.size(); }
  char charAt(unsigned int i) const { return v[i]; }
  String& operator+=(const String& o) { v += o.v; return *this; }
  String& operator+=(const char* s) { v += s; return *this; }
  String& operator+=(char c) { v += c; return *this; }
  const char* c_str() const { return v.c_str(); }
  String substring(unsigned int from, unsigned int to) const {
    return String(v.substr(from, to - from).c_str());
  }
  std::string v;
};

class Print {
 public:
  virtual ~Print() {}
  virtual size_t write(const uint8_t* buffer, size_t size) = 0;
};

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

#define F(text) (text)
struct FakeSerial { void println(const char*) {} };
static FakeSerial Serial;

static bool json_write_escaped(Print& out, const char* text, size_t length) {
__JSON_WRITE_ESCAPED__
}

static String toJsonString(const String& s) {
__TO_JSON_STRING__
}

__NUMERIC_PARSE__

class AsyncWebParameter {
 public:
  AsyncWebParameter(String value, bool file) : value_(value), file_(file) {}
  const String& value() const { return value_; }
  bool isFile() const { return file_; }
 private:
  String value_;
  bool file_;
};

class AsyncWebServerRequest {
 public:
  void set(const char* name, const char* value, bool file = false) {
    params_[name] = new AsyncWebParameter(String(value), file);
  }
  bool hasArg(const char* name) const { return params_.count(name) != 0; }
  AsyncWebParameter* param(const char* name) const {
    auto it = params_.find(name);
    return it == params_.end() ? nullptr : it->second;
  }
 private:
  std::map<std::string, AsyncWebParameter*> params_;
};

static const AsyncWebParameter *get_request_param(AsyncWebServerRequest *request, const char *name) {
  return request->param(name);
}

static String build_error_envelope(const char *code, const char *field, const String& message) {
__BUILD_ERROR_ENVELOPE__
}

static bool apply_save_u8_arg(AsyncWebServerRequest *request, const char *name, uint8_t& target, long minValue, long maxValue) {
__APPLY_U8__
}

static bool apply_save_u16_arg(AsyncWebServerRequest *request, const char *name, uint16_t& target, long minValue, long maxValue) {
__APPLY_U16__
}

static bool apply_save_float_arg(AsyncWebServerRequest *request, const char *name, float& target, float minValue, float maxValue) {
__APPLY_FLOAT__
}

static const uint8_t SAVE_RANGE_ERROR_FIELD_LIMIT = __FIELD_LIMIT__;

static void collect_save_bad_field(
    const char *name, String& badFieldsJson, String& firstBadField, uint8_t& badFieldsCount) {
__COLLECT__
}

static String build_save_range_errors_envelope(const String& firstBadField, const String& badFieldsJson) {
__ENVELOPE__
}

int main() {
  AsyncWebServerRequest req;
  // Три причины отказа сразу, в трёх разных таблицах - ровно то, что раньше обрывалось на
  // первой же (SteamDelay из kSaveU16Fields).
  req.set("SteamDelay", "not-a-number");      // формат, kSaveU16Fields
  req.set("Kp", "999999999");                 // диапазон, kSaveFloatFields
  req.set("PackDens", "200");                 // диапазон (max 100), kSaveU8Fields
  req.set("autospeed", "5");                  // валидное значение - должно примениться

  uint16_t steamDelay = 0;
  float kp = 0;
  uint8_t packDens = 0;
  uint8_t autospeed = 0;

  String badFieldsJson, firstBadField;
  uint8_t badFieldsCount = 0;

  if (!apply_save_u16_arg(&req, "SteamDelay", steamDelay, 0, 65535))
    collect_save_bad_field("SteamDelay", badFieldsJson, firstBadField, badFieldsCount);
  if (!apply_save_float_arg(&req, "Kp", kp, 0.0f, 100000.0f))
    collect_save_bad_field("Kp", badFieldsJson, firstBadField, badFieldsCount);
  if (!apply_save_u8_arg(&req, "PackDens", packDens, 0, 100))
    collect_save_bad_field("PackDens", badFieldsJson, firstBadField, badFieldsCount);
  if (!apply_save_u8_arg(&req, "autospeed", autospeed, 0, 99))
    collect_save_bad_field("autospeed", badFieldsJson, firstBadField, badFieldsCount);

  printf("COUNT %d\n", (int)badFieldsCount);
  printf("AUTOSPEED_APPLIED %d\n", (int)autospeed);
  printf("ENVELOPE %s\n", build_save_range_errors_envelope(firstBadField, badFieldsJson).c_str());

  // Предел на рост String: 9 отказов подряд, лимит __FIELD_LIMIT__.
  {
    String j2, f2;
    uint8_t c2 = 0;
    const char* names[] = {"a", "b", "c", "d", "e", "f", "g", "h", "i"};
    for (auto n : names) collect_save_bad_field(n, j2, f2, c2);
    printf("LIMIT_COUNT %d\n", (int)c2);
    printf("LIMIT_ENVELOPE %s\n", build_save_range_errors_envelope(f2, j2).c_str());
  }

  return 0;
}
"""


def check_behavior(web_text: str) -> None:
    try:
        apply_u8 = extract_function_body(
            web_text,
            "static bool apply_save_u8_arg(AsyncWebServerRequest *request, const char *name, "
            "uint8_t& target, long minValue, long maxValue)",
        )
        apply_u16 = extract_function_body(
            web_text,
            "static bool apply_save_u16_arg(AsyncWebServerRequest *request, const char *name, "
            "uint16_t& target, long minValue, long maxValue)",
        )
        apply_float = extract_function_body(
            web_text,
            "static bool apply_save_float_arg(AsyncWebServerRequest *request, const char *name, "
            "float& target, float minValue, float maxValue)",
        )
        collect = extract_function_body(
            web_text,
            "static void collect_save_bad_field(\n"
            "    const char *name, String& badFieldsJson, String& firstBadField, uint8_t& badFieldsCount)",
        )
        envelope = extract_function_body(
            web_text,
            "static String build_save_range_errors_envelope(const String& firstBadField, "
            "const String& badFieldsJson)",
        )
        build_error_envelope_body = extract_function_body(
            web_text,
            "static String build_error_envelope(const char *code, const char *field, const String& message)",
        )
        limit_match = re.search(r"SAVE_RANGE_ERROR_FIELD_LIMIT = (\d+);", web_text)
        if not limit_match:
            errors.append("WebServer.ino: SAVE_RANGE_ERROR_FIELD_LIMIT constant not found")
            return
        field_limit = int(limit_match.group(1))
    except ValueError as exc:
        errors.append(f"WebServer.ino: {exc}")
        return

    utils_text = STRING_UTILS.read_text(encoding="utf-8", errors="ignore")
    try:
        json_body = extract_function_body(utils_text, "inline String toJsonString(const String& s)")
        jwe_body = extract_function_body(
            utils_text, "inline bool json_write_escaped(Print& out, const char* text, size_t length)"
        )
    except ValueError as exc:
        errors.append(f"string_utils.h: {exc}")
        return

    numeric_parse_text = NUMERIC_PARSE.read_text(encoding="utf-8", errors="ignore")
    numeric_parse_body = numeric_parse_text.split("#include <string.h>", 1)[-1]

    program = (
        CPP_HARNESS_TEMPLATE
        .replace("__JSON_WRITE_ESCAPED__", jwe_body)
        .replace("__TO_JSON_STRING__", json_body)
        .replace("__NUMERIC_PARSE__", numeric_parse_body)
        .replace("__BUILD_ERROR_ENVELOPE__", build_error_envelope_body)
        .replace("__APPLY_U8__", apply_u8)
        .replace("__APPLY_U16__", apply_u16)
        .replace("__APPLY_FLOAT__", apply_float)
        .replace("__COLLECT__", collect)
        .replace("__ENVELOPE__", envelope)
        .replace("__FIELD_LIMIT__", str(field_limit))
    )

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "range_errors.cpp"
        exe = Path(tmp) / "range_errors"
        src.write_text(program, encoding="utf-8")
        compile_proc = subprocess.run(
            ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-o", str(exe), str(src)],
            capture_output=True, text=True,
        )
        if compile_proc.returncode != 0:
            errors.append("save range-error harness did not compile:\n" + compile_proc.stderr)
            return
        run_proc = subprocess.run([str(exe)], capture_output=True, text=True)
        if run_proc.returncode != 0:
            errors.append("save range-error harness crashed:\n" + run_proc.stderr)
            return

    lines = dict(line.split(" ", 1) for line in run_proc.stdout.strip("\n").split("\n"))

    if lines.get("COUNT") != "3":
        errors.append(f"expected 3 bad fields (SteamDelay/Kp/PackDens), got COUNT={lines.get('COUNT')}")
    if lines.get("AUTOSPEED_APPLIED") != "5":
        errors.append(
            "a valid field (autospeed) must still be applied even though other fields in the "
            f"same request are bad, got AUTOSPEED_APPLIED={lines.get('AUTOSPEED_APPLIED')}"
        )

    try:
        envelope_obj = json.loads(lines["ENVELOPE"])
    except (KeyError, json.JSONDecodeError) as exc:
        errors.append(f"envelope is not valid JSON: {exc}: {lines.get('ENVELOPE')}")
        envelope_obj = None
    if envelope_obj is not None:
        if envelope_obj.get("field") != "SteamDelay":
            errors.append(f"'field' must stay the FIRST bad field for backward compatibility: {envelope_obj}")
        if "SteamDelay" not in envelope_obj.get("message", ""):
            errors.append(f"'message' must reference the first bad field for backward compatibility: {envelope_obj}")
        if envelope_obj.get("fields") != ["SteamDelay", "Kp", "PackDens"]:
            errors.append(f"'fields' must list ALL bad fields, in encounter order: {envelope_obj}")

    if lines.get("LIMIT_COUNT") != "9":
        errors.append(
            f"badFieldsCount must keep counting past the String cap (expected 9), got {lines.get('LIMIT_COUNT')}"
        )
    try:
        limit_obj = json.loads(lines["LIMIT_ENVELOPE"])
    except (KeyError, json.JSONDecodeError) as exc:
        errors.append(f"limit envelope is not valid JSON: {exc}: {lines.get('LIMIT_ENVELOPE')}")
        limit_obj = None
    if limit_obj is not None:
        if len(limit_obj.get("fields", [])) != field_limit:
            errors.append(
                f"'fields' must be capped at SAVE_RANGE_ERROR_FIELD_LIMIT={field_limit} to bound heap growth, "
                f"got {len(limit_obj.get('fields', []))}: {limit_obj}"
            )


MALFORMED_ENVELOPE_HARNESS_TEMPLATE = r"""
#include <cstdint>
#include <string>
#include <cstdio>

class String {
 public:
  String() {}
  String(const char* s) : v(s ? s : "") {}
  String(char c) : v(1, c) {}
  void reserve(unsigned int) {}
  unsigned int length() const { return (unsigned int)v.size(); }
  char charAt(unsigned int i) const { return v[i]; }
  String& operator+=(const String& o) { v += o.v; return *this; }
  String& operator+=(const char* s) { v += s; return *this; }
  String& operator+=(char c) { v += c; return *this; }
  const char* c_str() const { return v.c_str(); }
  String substring(unsigned int from, unsigned int to) const {
    return String(v.substr(from, to - from).c_str());
  }
  std::string v;
};

// МУТАЦИЯ: стенд, имитирующий гипотетическую будущую правку build_error_envelope() -
// дописывает "\n" после закрывающей скобки. Это НЕ настоящая build_error_envelope() (её
// трогать нельзя - она запинена smoke_api_error_envelope.py), а инструмент проверки:
// build_save_range_errors_envelope() обязана заметить, что последний символ не '}', и
// не резать JSON вслепую.
static String build_error_envelope(const char *code, const char *field, const String& message) {
  String json = "{\"error\":\"";
  json += (code ? code : "internal_error");
  json += "\",\"field\":";
  if (field && *field) { json += "\""; json += field; json += "\""; }
  else json += "null";
  json += ",\"message\":\"";
  json += message;
  json += "\"}";
  json += "\n";
  return json;
}

static String build_save_range_errors_envelope(const String& firstBadField, const String& badFieldsJson) {
__ENVELOPE__
}

int main() {
  String result = build_save_range_errors_envelope(String("SteamDelay"), String("\"SteamDelay\",\"Kp\""));
  printf("%s", result.c_str());
  return 0;
}
"""


def check_malformed_envelope_guard(web_text: str) -> None:
    """Мутационная проверка находки [код-ревью 24.08 #3]: если build_error_envelope()
    когда-нибудь перестанет заканчиваться на '}' (допишет хвост), build_save_range_errors_
    envelope() не должна тихо собрать битый JSON слепым substring().

    build_error_envelope() в харнессе ниже - НЕ настоящая (трогать нельзя), а стенд с
    хвостовым '\n' после скобки - имитация будущей правки. Тело
    build_save_range_errors_envelope() (с проверкой последнего символа) берётся из
    WebServer.ino как есть - значит проверяется реальный код, а не его копия.

    Откат подтверждён вручную (см. отчёт): без проверки (голый
    json.substring(0, json.length() - 1)) отрезался бы хвостовой '\n', а не '}', и
    результат превращался бы в два слепленных JSON-объекта подряд - тест падает на
    json.loads(). С проверкой guard возвращает исходный конверт без "fields", но
    валидным JSON.
    """
    try:
        envelope = extract_function_body(
            web_text,
            "static String build_save_range_errors_envelope(const String& firstBadField, "
            "const String& badFieldsJson)",
        )
    except ValueError as exc:
        errors.append(f"WebServer.ino: {exc}")
        return

    program = MALFORMED_ENVELOPE_HARNESS_TEMPLATE.replace("__ENVELOPE__", envelope)

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "malformed_envelope.cpp"
        exe = Path(tmp) / "malformed_envelope"
        src.write_text(program, encoding="utf-8")
        compile_proc = subprocess.run(
            ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-o", str(exe), str(src)],
            capture_output=True, text=True,
        )
        if compile_proc.returncode != 0:
            errors.append("malformed-envelope guard harness did not compile:\n" + compile_proc.stderr)
            return
        run_proc = subprocess.run([str(exe)], capture_output=True, text=True)
        if run_proc.returncode != 0:
            errors.append("malformed-envelope guard harness crashed:\n" + run_proc.stderr)
            return

    output = run_proc.stdout
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError as exc:
        errors.append(
            "build_save_range_errors_envelope produced broken JSON when build_error_envelope "
            f"did not end on '}}': {exc}: {output!r}"
        )
        return
    if "fields" in parsed:
        errors.append(
            "guard did not trigger: 'fields' must be absent when the last char isn't '}' "
            f"(soft degradation expected): {parsed}"
        )


def main() -> int:
    if not WEBSERVER.exists():
        print("smoke_save_range_errors failed: WebServer.ino not found")
        return 1
    web_text = WEBSERVER.read_text(encoding="utf-8", errors="ignore")
    check_static(web_text)
    check_behavior(web_text)
    check_malformed_envelope_guard(web_text)
    if errors:
        print("save range errors accumulation smoke failed:")
        for error in errors:
            print(f" - {error}")
        return 1
    print("save range errors accumulation smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
