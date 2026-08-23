#!/usr/bin/env python3
"""Behavioral check for пункт 39: дамп заголовков/параметров на 404 не должен идти
в горячий путь.

До правки onNotFound() в FS.ino печатал в Serial ПОЛНЫЙ дамп заголовков и параметров
запроса на КАЖДЫЙ промах по адресу (~45 мс блокировки веб-задачи), а промахи обычны в
штатной работе (например, favicon от старой вкладки браузера). Правка убирает дамп из
обычной сборки и оставляет его только под уже принятым в проекте флагом __SAMOVAR_DEBUG
(тем же, что чуть ниже управляет дампом тела запроса в onFileUpload()/onRequestBody()).

Компилирует РЕАЛЬНОЕ тело лямбды server.onNotFound(...) из FS.ino (через
extract_braced_block_after) поверх мока AsyncWebServerRequest, который считает вызовы
getHeader()/getParam(), ДВАЖДЫ: без __SAMOVAR_DEBUG (дамп обязан не выполняться) и с ним
(дамп обязан выполняться) - и в обоих случаях request->send(404) обязан быть вызван
ровно один раз, иначе гейт по ошибке проглотил бы саму отправку ответа.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_helpers import extract_braced_block_after

ROOT = Path(__file__).resolve().parents[1]
ONNOTFOUND_TOKEN = "server.onNotFound([](AsyncWebServerRequest * request) {"

HARNESS = r'''
#include <cstdio>
#include <cstdarg>
#include <string>

class String {
 public:
  String() = default;
  String(const char* s) : v(s ? s : "") {}
  const char* c_str() const { return v.c_str(); }
  bool equals(const String& o) const { return v == o.v; }
  std::string v;
};

enum { HTTP_GET = 1, HTTP_POST = 2, HTTP_DELETE = 4, HTTP_PUT = 8,
       HTTP_PATCH = 16, HTTP_HEAD = 32, HTTP_OPTIONS = 64 };

struct SerialStub {
  int printf(const char* fmt, ...) { (void)fmt; return 0; }
};
static SerialStub Serial;

struct AsyncWebHeader {
  String nm{"X"}, val{"Y"};
  const String& name() const { return nm; }
  const String& value() const { return val; }
};
struct AsyncWebParameter {
  String nm{"a"}, val{"b"};
  bool isFile() const { return false; }
  bool isPost() const { return false; }
  const String& name() const { return nm; }
  const String& value() const { return val; }
  size_t size() const { return 0; }
};

static int g_getHeader_calls = 0;
static int g_getParam_calls = 0;
static int g_send_calls = 0;
static int g_send_code = -1;

struct AsyncWebServerRequest {
  int method() const { return HTTP_GET; }
  String host() const { return String("device"); }
  String url() const { return String("/missing"); }
  size_t contentLength() const { return 0; }
  String contentType() const { return String(""); }
  int headers() const { return 2; }
  AsyncWebHeader hdr;
  const AsyncWebHeader* getHeader(int) { g_getHeader_calls++; return &hdr; }
  int params() const { return 1; }
  AsyncWebParameter prm;
  const AsyncWebParameter* getParam(int) { g_getParam_calls++; return &prm; }
  void send(int code) { g_send_calls++; g_send_code = code; }
};

static void onNotFound(AsyncWebServerRequest* request) {
@EXTRACTED@
}

static int failures = 0;
static void expect(bool cond, const char* what) {
  if (!cond) { fprintf(stderr, "FAIL: %s\n", what); failures++; }
}

int main() {
  AsyncWebServerRequest request;
  onNotFound(&request);
  expect(g_send_calls == 1, "send(404) должен быть вызван ровно один раз");
  expect(g_send_code == 404, "ответ на промах должен быть 404");
#ifdef HARNESS_DEBUG_BUILD
  expect(g_getHeader_calls > 0, "в отладочной сборке дамп заголовков обязан выполняться");
  expect(g_getParam_calls > 0, "в отладочной сборке дамп параметров обязан выполняться");
#else
  expect(g_getHeader_calls == 0,
         "в обычной сборке дамп заголовков НЕ должен выполняться на горячем пути 404");
  expect(g_getParam_calls == 0,
         "в обычной сборке дамп параметров НЕ должен выполняться на горячем пути 404");
#endif

  if (failures) {
    fprintf(stderr, "%d проверок провалено\n", failures);
    return 1;
  }
  printf("onNotFound debug gate (DEBUG=%d): все проверки прошли\n",
#ifdef HARNESS_DEBUG_BUILD
         1
#else
         0
#endif
        );
  return 0;
}
'''


def main() -> int:
    source_text = (ROOT / "FS.ino").read_text(encoding="utf-8")
    try:
        body, _ = extract_braced_block_after(source_text, ONNOTFOUND_TOKEN)
    except ValueError as exc:
        print(f"FS.ino onNotFound debug gate smoke failed: {exc}")
        return 1

    source = HARNESS.replace("@EXTRACTED@", body)

    with tempfile.TemporaryDirectory(prefix="samovar-fs-notfound-") as tmpdir:
        src_path = Path(tmpdir) / "harness.cpp"
        src_path.write_text(source, encoding="utf-8")
        for debug_build in (False, True):
            binary_path = Path(tmpdir) / ("harness_debug" if debug_build else "harness_release")
            cmd = ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror"]
            if debug_build:
                cmd += ["-D__SAMOVAR_DEBUG", "-DHARNESS_DEBUG_BUILD"]
            cmd += [str(src_path), "-o", str(binary_path)]
            compiled = subprocess.run(cmd, capture_output=True, text=True)
            if compiled.returncode != 0:
                print("FS.ino onNotFound debug gate smoke failed:")
                print(f" - харнесс (debug={debug_build}) не компилируется:")
                print(compiled.stderr)
                return 1
            run = subprocess.run([str(binary_path)], capture_output=True, text=True)
            if run.returncode != 0:
                print("FS.ino onNotFound debug gate smoke failed:")
                print(f" - debug={debug_build}:")
                print(run.stdout)
                print(run.stderr)
                return 1

    print("FS.ino onNotFound debug gate smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
