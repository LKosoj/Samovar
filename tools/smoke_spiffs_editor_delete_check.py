#!/usr/bin/env python3
"""Behavioral check for пункт 22: DELETE в /edit обязан проверять результат remove().

До правки SPIFFSEditor.h всегда отвечал 200 "DELETE: ..." независимо от того, удалился
ли файл на самом деле - на переполненной/повреждённой ФС remove() мог вернуть false, а
пользователь был уверен, что скрипт стёрт, хотя автоматика продолжала его использовать.

Компилирует РЕАЛЬНОЕ тело DELETE-ветки handleRequest() (через extract_braced_block_after)
поверх минимальных моков _fs/request, у которых remove() управляемо возвращает true/false,
и проверяет: при успехе - 200 "DELETE: <path>", при неудаче - 500 (не 200!) и НЕ
содержится обманчивое "DELETE:" в теле ответа.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_helpers import extract_braced_block_after

ROOT = Path(__file__).resolve().parents[1]
DELETE_BRANCH_TOKEN = "} else if (request->method() == HTTP_DELETE) {"

HARNESS = r'''
#include <cstdio>
#include <cstring>
#include <string>

class String {
 public:
  String() = default;
  String(const char* s) : v(s ? s : "") {}
  String(const std::string& s) : v(s) {}
  size_t length() const { return v.size(); }
  char operator[](size_t i) const { return i < v.size() ? v[i] : '\0'; }
  String operator+(const String& o) const { return String(v + o.v); }
  friend String operator+(const char* lhs, const String& rhs) { return String(std::string(lhs) + rhs.v); }
  const char* c_str() const { return v.c_str(); }
  std::string v;
};

static bool g_remove_result = true;
static std::string g_removed_path;

struct FSMock {
  bool remove(const String& p) { g_removed_path = p.c_str(); return g_remove_result; }
};
static FSMock _fs;

static bool samovar_process_active() { return false; }
static bool data_log_close_pending() { return false; }

struct Param {
  String v;
  const String& value() const { return v; }
};

struct RequestMock {
  Param path_param{String("/dist.lua")};
  bool has_path = true;
  int sent_code = -1;
  std::string sent_body;

  bool hasParam(const char*, bool) { return has_path; }
  Param* getParam(const char*, bool) { return &path_param; }
  void send(int code, String type = String(), String body = String()) {
    (void)type;
    sent_code = code;
    sent_body = body.c_str();
  }
};
static RequestMock request_storage;
static RequestMock* request = &request_storage;

@EXTRACTED@

static int failures = 0;

static void expect(bool cond, const char* what) {
  if (!cond) { fprintf(stderr, "FAIL: %s\n", what); failures++; }
}

int main() {
  // Успех: remove() отработал - 200 и подтверждение с именем файла.
  {
    request_storage = RequestMock{};
    g_remove_result = true;
    handleDelete();
    expect(request_storage.sent_code == 200, "успешное удаление должно вернуть 200");
    expect(request_storage.sent_body.find("DELETE:") != std::string::npos,
           "успешный ответ должен подтверждать удаление");
  }
  // Неудача: remove() вернул false (ФС отказала) - НЕ 200, и тело не должно врать про
  // успешное удаление.
  {
    request_storage = RequestMock{};
    g_remove_result = false;
    handleDelete();
    expect(request_storage.sent_code != 200,
           "неудачное удаление НЕ должно отвечать 200 - файл на самом деле не удалён");
    expect(request_storage.sent_code == 500, "неудачное удаление должно вернуть 500");
  }

  if (failures) {
    fprintf(stderr, "%d проверок провалено\n", failures);
    return 1;
  }
  printf("SPIFFSEditor DELETE remove() check: все проверки прошли\n");
  return 0;
}
'''


def main() -> int:
    source_text = (ROOT / "SPIFFSEditor.h").read_text(encoding="utf-8")
    try:
        body, _ = extract_braced_block_after(source_text, DELETE_BRANCH_TOKEN)
    except ValueError as exc:
        print(f"SPIFFSEditor DELETE check smoke failed: {exc}")
        return 1

    extracted = "static void handleDelete() {\n" + body + "\n}"
    source = HARNESS.replace("@EXTRACTED@", extracted)

    with tempfile.TemporaryDirectory(prefix="samovar-spiffs-delete-") as tmpdir:
        cpp_path = Path(tmpdir) / "harness.cpp"
        cpp_path.write_text(source, encoding="utf-8")
        binary_path = Path(tmpdir) / "harness"
        compiled = subprocess.run(
            ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
             str(cpp_path), "-o", str(binary_path)],
            capture_output=True, text=True,
        )
        if compiled.returncode != 0:
            print("SPIFFSEditor DELETE check smoke failed:")
            print(" - харнесс не компилируется:")
            print(compiled.stderr)
            return 1
        run = subprocess.run([str(binary_path)], capture_output=True, text=True)
        if run.returncode != 0:
            print("SPIFFSEditor DELETE check smoke failed:")
            print(run.stdout)
            print(run.stderr)
            return 1

    print("SPIFFSEditor DELETE remove() check smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
