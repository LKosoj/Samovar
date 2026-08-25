#!/usr/bin/env python3
"""[T27.1] Цвет длиннее буфера должен давать 400, а не молча обрезаться.

Раньше handleSave() (WebServer.ino) применял SaveColorField напрямую через
copyStringSafe(staged.*f.member, request->arg(f.name)) - шаблонная
copyStringSafe МОЛЧА усекает значение длиннее буфера (char[20]) вместо того,
чтобы сообщить об ошибке. Пользователь видел "сохранено", а сохранённый цвет
на деле был обрезан.

Решение: цикл по kSaveColorFields теперь зовёт apply_save_string_arg() -
тот же хелпер, которым уже применяются videourl/blynkauth/tgtoken/tgchatid -
он сам отвечает 400 через send_save_parse_error() при переполнении и
возвращает false (handleSave делает return, черновик staged не публикуется).

(а) Текстовая проверка: цикл по kSaveColorFields в handleSave() действительно
    вызывает apply_save_string_arg(...) и делает return при отказе - не
    copyStringSafe напрямую.

(б) Поведенческий харнесс на РЕАЛЬНОМ теле apply_save_string_arg()
    (extract_function_body) с подставными AsyncWebServerRequest/
    AsyncWebParameter и настоящим copyStringSafe (string_utils.h,
    extract_function_body) при N=20 (размер char[20] SteamColor и т.п.):
      - 19 байт значения -> принято (true), значение скопировано в target,
        send_save_parse_error НЕ вызван;
      - 20 байт значения -> отклонено (false), send_save_parse_error вызван
        РОВНО один раз с именем поля, target НЕ изменён (остался прежним).

(в) Мутационная проверка: замена `>= N` на `> N` в apply_save_string_arg
    (ошибка на единицу - граничное значение 20 байт снова проходит и
    молча обрезается до 19) обязана завалить харнесс.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []

web_text = (ROOT / "WebServer.ino").read_text(encoding="utf-8", errors="ignore")
string_utils_text = (ROOT / "string_utils.h").read_text(encoding="utf-8", errors="ignore")


# ---- (а) Текстовая проверка: handleSave использует apply_save_string_arg для цвета ----

try:
    handle_save = extract_function_body(web_text, "void handleSave(AsyncWebServerRequest *request)")
except ValueError as exc:
    errors.append(str(exc))
    handle_save = ""

if handle_save:
    color_loop_start = handle_save.find("for (const SaveColorField &f : kSaveColorFields)")
    if color_loop_start < 0:
        errors.append("handleSave: не найден цикл по kSaveColorFields")
    else:
        color_loop_end = handle_save.find("}", color_loop_start)
        color_loop = handle_save[color_loop_start:color_loop_end]
        if "apply_save_string_arg(request, f.name, staged.*f.member)" not in color_loop:
            errors.append(
                "handleSave: цикл по kSaveColorFields должен звать "
                "apply_save_string_arg(request, f.name, staged.*f.member)"
            )
        if "return;" not in color_loop:
            errors.append("handleSave: цикл по kSaveColorFields должен делать return при отказе apply_save_string_arg")
        if "copyStringSafe(staged.*f.member, request->arg(f.name))" in color_loop:
            errors.append(
                "handleSave: цикл по kSaveColorFields всё ещё зовёт copyStringSafe напрямую - "
                "переполнение снова будет молча обрезано вместо 400"
            )

if errors:
    print("Save color overflow smoke failed (text checks):")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)


# ---- (б)/(в) Поведенческий + мутационный харнесс ----

try:
    apply_body = extract_function_body(
        web_text,
        "static bool apply_save_string_arg(AsyncWebServerRequest *request, const char *name, char (&target)[N])",
    )
except ValueError as exc:
    print(f"FAIL: {exc}", file=sys.stderr)
    sys.exit(1)

try:
    copy_body = extract_function_body(
        string_utils_text, "inline void copyStringSafe(char (&dst)[N], const String& src)"
    )
except ValueError as exc:
    print(f"FAIL: {exc}", file=sys.stderr)
    sys.exit(1)

HARNESS_TEMPLATE = r'''
#include <cstddef>
#include <cstring>
#include <string>
#include <iostream>

// Мини-String вместо Arduino String: настоящему apply_save_string_arg и
// copyStringSafe хватает length()/c_str().
struct String {
  std::string data;
  String() = default;
  String(const char* s) : data(s ? s : "") {}
  size_t length() const { return data.size(); }
  const char* c_str() const { return data.c_str(); }
};

// ---- настоящий copyStringSafe (string_utils.h, extract_function_body) ----
template <size_t N>
inline void copyStringSafe(char (&dst)[N], const String& src) {
@COPY_BODY@
}

enum NumericParseError { NUMERIC_PARSE_OUT_OF_RANGE };

struct AsyncWebParameter {
  String val;
  bool fileFlag = false;
  bool isFile() const { return fileFlag; }
  String value() const { return val; }
};

struct AsyncWebServerRequest {
  bool hasArgFlag = true;
  AsyncWebParameter* paramPtr = nullptr;
  bool hasArg(const char*) const { return hasArgFlag; }
};

static AsyncWebServerRequest* lastRequestSeen = nullptr;
const AsyncWebParameter* get_request_param(AsyncWebServerRequest *request, const char *) {
  lastRequestSeen = request;
  return request->paramPtr;
}

// ---- мок send_save_parse_error (не static: единственный вызов лежит во
// вклеенном реальном теле ниже - static без вызова роняет сборку на
// -Wunused-function ещё до runtime, что не ловит мутацию содержательно) ----
int sendParseErrorCalls = 0;
std::string lastErrorName;
NumericParseError lastErrorCode;
void send_save_parse_error(AsyncWebServerRequest *, const char *name, NumericParseError error) {
  sendParseErrorCalls++;
  lastErrorName = name;
  lastErrorCode = error;
}

// ---- реальное тело apply_save_string_arg (WebServer.ino, extract_function_body) ----
template <size_t N>
static bool apply_save_string_arg(AsyncWebServerRequest *request, const char *name, char (&target)[N]) {
@APPLY_BODY@
}

// ---- тесты ----
static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

int main() {
  // 19 байт в char[20] - помещается с местом под '\0', должно быть принято.
  {
    sendParseErrorCalls = 0;
    AsyncWebServerRequest request;
    AsyncWebParameter param;
    param.val = String("1234567890123456789");  // 19 символов
    check(param.val.length() == 19, "test setup: expected a 19-byte value");
    request.paramPtr = &param;
    char target[20];
    std::memset(target, 'X', sizeof(target));
    target[19] = '\0';
    bool result = apply_save_string_arg<20>(&request, "SteamColor", target);
    check(result, "19-byte value must be accepted (buffer is char[20])");
    check(sendParseErrorCalls == 0, "19-byte value must not call send_save_parse_error");
    check(std::strcmp(target, "1234567890123456789") == 0,
          "19-byte value must be copied into the draft unchanged");
  }

  // 20 байт в char[20] - не помещается (нужен байт под '\0'), должно быть отклонено.
  {
    sendParseErrorCalls = 0;
    lastErrorName.clear();
    AsyncWebServerRequest request;
    AsyncWebParameter param;
    param.val = String("12345678901234567890");  // 20 символов
    check(param.val.length() == 20, "test setup: expected a 20-byte value");
    request.paramPtr = &param;
    char target[20];
    std::strcpy(target, "SENTINEL");
    bool result = apply_save_string_arg<20>(&request, "SteamColor", target);
    check(!result, "20-byte value must be rejected (400), not silently truncated to 19 bytes");
    check(sendParseErrorCalls == 1, "20-byte value must call send_save_parse_error exactly once");
    check(lastErrorName == "SteamColor", "send_save_parse_error must name the offending field");
    check(std::strcmp(target, "SENTINEL") == 0,
          "rejected value must not modify the draft field at all");
  }

  // hasArg() == false - поле не тронуто вовсе (принято, значение не читается).
  {
    sendParseErrorCalls = 0;
    AsyncWebServerRequest request;
    request.hasArgFlag = false;
    request.paramPtr = nullptr;
    char target[20];
    std::strcpy(target, "SENTINEL");
    bool result = apply_save_string_arg<20>(&request, "SteamColor", target);
    check(result, "absent argument must be treated as no-op success");
    check(sendParseErrorCalls == 0, "absent argument must not call send_save_parse_error");
    check(std::strcmp(target, "SENTINEL") == 0, "absent argument must not touch the draft field");
  }

  if (failures != 0) return 1;
  std::cout << "apply_save_string_arg overflow behaviour checks passed\n";
  return 0;
}
'''


def build_harness() -> str:
    harness = HARNESS_TEMPLATE
    harness = harness.replace("@COPY_BODY@", copy_body)
    harness = harness.replace("@APPLY_BODY@", apply_body)
    return harness


def compile_and_run(harness: str, show_output: bool = True) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-save-color-overflow-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "save_color_overflow_test.cpp"
        binary = temp / "save_color_overflow_test"
        source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            sys.stderr.write("compile failed:\n")
            sys.stderr.write(compile_result.stdout)
            sys.stderr.write(compile_result.stderr)
            return compile_result.returncode
        run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        if show_output:
            sys.stdout.write(run_result.stdout)
            sys.stderr.write(run_result.stderr)
        return run_result.returncode


def main() -> int:
    harness = build_harness()
    if compile_and_run(harness) != 0:
        return 1

    # ---- (в) Мутация: >= N -> > N (ошибка на единицу) ----
    mutant = harness.replace(
        "param->value().length() >= N",
        "param->value().length() > N",
        1,
    )
    if mutant == harness:
        print("FAIL: не удалось построить мутацию off-by-one (>= N -> > N)", file=sys.stderr)
        return 1
    if compile_and_run(mutant, show_output=False) == 0:
        print(
            "FAIL: мутация off-by-one (>= N -> > N) пережила тест - "
            "20-байтовое значение на границе буфера снова молча обрезалось бы до 19 байт",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
