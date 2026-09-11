#!/usr/bin/env python3
"""T06: реальные upload/POST отличают запись файла от принятия Lua reload."""
import subprocess
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body
from smoke_spiffs_editor_upload_safety import (
    HANDLE_UPLOAD_SIGNATURE, NAME_ALLOWED_SIGNATURE, NAME_HARNESS,
)

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <map>
#include <cstdint>
#include <cstdlib>
String operator+(const char* a, const String& b) { return String((a + b.v).c_str()); }
bool operator!=(const String& a, const char* b) { return !(a == b); }
bool fileLockAvailable = true, fileLocked = false, pendingAvailable = true;
bool switchingMode = false, shortWrite = false;
volatile bool pending_lua_reload_flag = false;
String pending_lua_reload_file;
void check(bool value, const char* message) {
  if (!value) { fprintf(stderr, "FAIL: %s\n", message); std::exit(1); }
}
bool log_file_lock(int) {
  if (!fileLockAvailable || fileLocked) return false;
  fileLocked = true;
  return true;
}
void log_file_unlock(bool) { check(fileLocked, "unlock must own file lock"); fileLocked = false; }
bool mode_switch_in_progress() { return switchingMode; }
struct PendingCommandLockGuard {
  explicit operator bool() const { return pendingAvailable; }
};
String getValue(const String& input, char delimiter, int index) {
  size_t start = 0;
  for (int i = 0; i < index; ++i) {
    size_t next = input.v.find(delimiter, start);
    if (next == std::string::npos) return String("");
    start = next + 1;
  }
  return String(input.v.substr(start, input.v.find(delimiter, start) - start).c_str());
}
std::map<std::string, std::string> files;
struct File {
  std::string name;
  explicit operator bool() const { return !name.empty(); }
  size_t write(uint8_t* bytes, size_t count) {
    check(fileLocked, "write must own file lock");
    size_t written = shortWrite && count ? count - 1 : count;
    files[name].append(reinterpret_cast<char*>(bytes), written);
    return written;
  }
  void close() {}
};
struct FakeFS {
  File open(const String& name, const char* mode) {
    check(fileLocked, "open must own file lock");
    if (*mode == 'w') files[name.v] = "";
    return File{name.v};
  }
  void remove(const String& name) {
    check(fileLocked, "remove must own file lock");
    files.erase(name.v);
  }
} _fs;
struct Param {
  String path;
  String value() { return path; }
};
struct AsyncWebServerRequest {
  Param param;
  std::map<std::string, String> attrs;
  int status = 0;
  String body;
  explicit AsyncWebServerRequest(const char* path) : param{String(path)} {}
  bool hasParam(const char*, bool, bool) { return true; }
  Param* getParam(const char*, bool, bool) { return &param; }
  String getAttribute(const char* name) { return attrs[name]; }
  void setAttribute(const char* name, const char* value) { attrs[name] = String(value); }
  void send(int code, const char*, const String& text) { status = code; body = text; }
};
@CONSTANTS@
static bool spiffsEditorNameAllowed(const String &path) { @NAME@ }
void upload(AsyncWebServerRequest *request, const String& filename, size_t index,
            uint8_t *data, size_t len, bool final) { @UPLOAD@ }
void post(AsyncWebServerRequest *request) { @POST@ }

void reset() {
  files.clear(); fileLockAvailable = true; fileLocked = false;
  pendingAvailable = true; switchingMode = false; shortWrite = false;
  pending_lua_reload_flag = false; pending_lua_reload_file = "";
}
void twoChunks(AsyncWebServerRequest& request, const char* path) {
  uint8_t first[] = {'a', 'b', 'c'}, last[] = {'1', '2', '3', '4'};
  upload(&request, String(path), 0, first, sizeof(first), false);
  check(!fileLocked, "first chunk must release lock");
  upload(&request, String(path), sizeof(first), last, sizeof(last), true);
  check(!fileLocked, "final chunk must release lock");
}
int main() {
  for (const char* path : {"/btn_a.lua", "/btn_b.lua"}) {
    for (int busy = 0; busy < 3; ++busy) {
      reset();
      pendingAvailable = busy != 1;
      switchingMode = busy == 2;
      AsyncWebServerRequest request(path);
      twoChunks(request, path);
      post(&request);
      check(request.status == 200, "committed Lua must return saved status even when reload is rejected");
      check(files.count(path) == 1 && files[path] == "abc1234", "committed file bytes must survive reload result");
      check(!fileLocked, "POST must release file lock");
#ifdef USE_LUA
      if (busy) {
        check(request.body.v == std::string("UPLOADED, LUA RELOAD NOT QUEUED: ") + path,
              "rejected reload must have explicit saved-but-not-applied response");
        check(!pending_lua_reload_flag, "rejected reload must not claim queued work");
      } else {
        check(request.body.v == std::string("UPLOADED: ") + path, "accepted reload retains success response");
        check(pending_lua_reload_flag && pending_lua_reload_file.v == path, "accepted reload must carry actual filename");
      }
#else
      check(request.body.v == std::string("UPLOADED: ") + path && !pending_lua_reload_flag,
            "build without Lua must save files without reporting or enqueueing Lua reload");
#endif
    }
    reset();
    shortWrite = true;
    AsyncWebServerRequest failed(path);
    uint8_t bytes[] = {'x', 'y'};
    upload(&failed, String(path), 0, bytes, sizeof(bytes), true);
    post(&failed);
    check(failed.status == 500 && files.count(path) == 0, "short write must fail and remove incomplete file");
    check(!pending_lua_reload_flag && !fileLocked, "short write must not enqueue reload or retain lock");

    reset();
    AsyncWebServerRequest partial(path);
    upload(&partial, String(path), 0, bytes, sizeof(bytes), false);
    post(&partial);
    check(partial.status == 500 && files.count(path) == 0, "missing final chunk must fail and remove incomplete file");

    reset();
    fileLockAvailable = false;
    AsyncWebServerRequest locked(path);
    upload(&locked, String(path), 0, bytes, sizeof(bytes), true);
    post(&locked);
    check(locked.status == 503 && files.count(path) == 0, "busy file lock must not report saved or create file");
  }
  reset();
  pendingAvailable = false;
  AsyncWebServerRequest textFile("/notes.txt");
  twoChunks(textFile, "/notes.txt");
  post(&textFile);
  check(textFile.status == 200 && !pending_lua_reload_flag,
        "non-Lua file must not depend on reload queue");
  puts("T06 upload and POST outcomes passed");
}
'''


def harness(source: str, lua_enabled: bool) -> str:
    post, _ = extract_braced_block_after(source, "else if (request->method() == HTTP_POST) {")
    prefix = NAME_HARNESS.split("@EXTRACTED@", 1)[0]
    constants = source[source.index("static const char *SPIFFS_EDITOR_UPLOAD_ERROR_ATTR"):
                       source.index("class SPIFFSEditor:")]
    return ("#define USE_LUA\n" if lua_enabled else "") + prefix + (HARNESS
        .replace("@CONSTANTS@", constants)
        .replace("@NAME@", extract_function_body(source, NAME_ALLOWED_SIGNATURE))
        .replace("@UPLOAD@", extract_function_body(source, HANDLE_UPLOAD_SIGNATURE))
        .replace("@POST@", post))


def run(source: str, lua_enabled: bool = True) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory(prefix="samovar-t06-") as directory:
        path = Path(directory)
        (path / "test.cpp").write_text(harness(source, lua_enabled), encoding="utf-8")
        compiled = subprocess.run(
            ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
             str(path / "test.cpp"), "-o", str(path / "test")],
            capture_output=True, text=True,
        )
        if compiled.returncode:
            raise RuntimeError("harness compile failed: " + compiled.stderr)
        return subprocess.run([str(path / "test")], capture_output=True, text=True)


def main() -> int:
    source = (ROOT / "SPIFFSEditor.h").read_text(encoding="utf-8")
    try:
        for lua_enabled in (True, False):
            original = run(source, lua_enabled)
            if original.returncode:
                raise RuntimeError(original.stdout + original.stderr)
        marker = 'request->send(200, "text/plain", "UPLOADED, LUA RELOAD NOT QUEUED: " + p);'
        for replacement, expected in (
            (marker.replace("send(200", "send(503"), "committed Lua must return saved status"),
            (marker.replace("UPLOADED, LUA RELOAD NOT QUEUED: ", "UPLOADED: "),
             "rejected reload must have explicit saved-but-not-applied response"),
        ):
            if source.count(marker) != 1:
                raise RuntimeError("mutation anchor must be unique")
            mutant = run(source.replace(marker, replacement, 1))
            if mutant.returncode == 0 or expected not in mutant.stderr:
                raise RuntimeError("mutation must fail on intended assertion: " + mutant.stdout + mutant.stderr)
        print("T06 upload/POST with/without Lua and two substantive mutations passed")
        return 0
    except (RuntimeError, ValueError) as error:
        print("FAIL: " + str(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
