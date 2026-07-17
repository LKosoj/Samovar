#!/usr/bin/env python3
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, strip_cpp_comments


ROOT = Path(__file__).resolve().parents[1]
WEB_SERVER = ROOT / "WebServer.ino"
errors: list[str] = []


def require(condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def extract_lua_handler(source: str) -> str:
    marker = 'server.on("/lua"'
    if source.count(marker) != 1:
        raise ValueError(
            f"expected one /lua registration, found {source.count(marker)}"
        )
    return extract_function_body(source, marker)


def build_harness(handler: str) -> str:
    template = r'''
#include <stddef.h>
#include <stdint.h>

#include <iostream>
#include <string>
#include <vector>

// Настоящие toJsonString()/build_error_envelope() зовут charAt(), которого у std::string
// нет. Тонкая надстройка позволяет вкомпилировать их как есть: харнесс проверяет реальное
// тело ответа /lua, а не его копию, которая молча разъедется с прошивкой.
struct String : std::string {
  String() = default;
  String(const char* s) : std::string(s ? s : "") {}
  String(const std::string& s) : std::string(s) {}
  String(char c) : std::string(1, c) {}
  char charAt(size_t i) const { return (*this)[i]; }
};

struct RecordedResponse {
  bool sent = false;
  uint16_t status = 0;
  String contentType;
  String body;
  String cacheControl;
};

class AsyncWebParameter {
 public:
  AsyncWebParameter(const String& name, const String& value,
                    bool post = false, bool file = false)
      : name_(name), value_(value), post_(post), file_(file) {}

  const String& name() const { return name_; }
  const String& value() const { return value_; }
  bool isPost() const { return post_; }
  bool isFile() const { return file_; }

 private:
  String name_;
  String value_;
  bool post_;
  bool file_;
};

class AsyncWebServerRequest {
 public:
  explicit AsyncWebServerRequest(
      const std::vector<AsyncWebParameter*>& parameters)
      : parameters_(parameters) {}

  size_t params() const { return parameters_.size(); }

  AsyncWebParameter* getParam(size_t index) const {
    return index < parameters_.size() ? parameters_[index] : nullptr;
  }

  RecordedResponse response;

 private:
  std::vector<AsyncWebParameter*> parameters_;
};

static volatile bool pending_lua_start_flag = false;
static volatile bool pending_lua_file_flag = false;
static String pending_lua_file = "unchanged";
static bool start_queue_allowed = true;
static bool file_queue_allowed = true;
static unsigned start_queue_calls = 0;
static unsigned file_queue_calls = 0;

static bool queue_pending_flag(volatile bool& flag) {
  ++start_queue_calls;
  if (!start_queue_allowed) return false;
  flag = true;
  return true;
}

static bool queue_pending_string(volatile bool& flag, String& valueSlot,
                                 const String& value) {
  ++file_queue_calls;
  if (!file_queue_allowed) return false;
  valueSlot = value;
  flag = true;
  return true;
}

static void send_no_store_response(AsyncWebServerRequest* request,
                                   uint16_t status,
                                   const char* contentType,
                                   const String& body) {
  request->response.sent = true;
  request->response.status = status;
  request->response.contentType = contentType;
  request->response.body = body;
  request->response.cacheControl = "no-store";
}

@JSON_UTILS@

@ERROR_ENVELOPE@

static void handle_lua(AsyncWebServerRequest* request) {
@HANDLER_BODY@
}

struct RunResult {
  RecordedResponse response;
  unsigned startCalls;
  unsigned fileCalls;
  bool startPending;
  bool filePending;
  String fileValue;
};

static RunResult run_handler(
    const std::vector<AsyncWebParameter*>& parameters,
    bool allowStart = true,
    bool allowFile = true) {
  pending_lua_start_flag = false;
  pending_lua_file_flag = false;
  pending_lua_file = "unchanged";
  start_queue_allowed = allowStart;
  file_queue_allowed = allowFile;
  start_queue_calls = 0;
  file_queue_calls = 0;

  AsyncWebServerRequest request(parameters);
  handle_lua(&request);

  RunResult result;
  result.response = request.response;
  result.startCalls = start_queue_calls;
  result.fileCalls = file_queue_calls;
  result.startPending = pending_lua_start_flag;
  result.filePending = pending_lua_file_flag;
  result.fileValue = pending_lua_file;
  return result;
}

static int failures = 0;

static void check(bool condition, const String& scenario,
                  const String& detail) {
  if (condition) return;
  ++failures;
  std::cerr << scenario << ": " << detail << "\n";
}

static void check_response(const RunResult& result, const String& scenario,
                           uint16_t status, const String& contentType,
                           const String& body) {
  check(result.response.sent, scenario, "response was not sent");
  check(result.response.status == status, scenario, "unexpected status");
  check(result.response.contentType == contentType, scenario,
        "unexpected content type");
  check(result.response.body == body, scenario, "unexpected body");
  check(result.response.cacheControl == "no-store", scenario,
        "Cache-Control is not no-store");
}

static void check_invalid(const RunResult& result, const String& scenario) {
  check_response(result, scenario, 400, "application/json",
                 "{\"error\":\"BAD_REQUEST\",\"field\":null,\"message\":\"BAD_REQUEST\"}");
  check(result.startCalls == 0, scenario, "start queue was called");
  check(result.fileCalls == 0, scenario, "file queue was called");
  check(!result.startPending, scenario, "start pending value changed");
  check(!result.filePending, scenario, "file pending value changed");
  check(result.fileValue == "unchanged", scenario,
        "pending file value changed");
}

static void test_zero_params() {
  const RunResult result = run_handler({});
  check_response(result, "zero params", 200, "text/html", "OK");
  check(result.startCalls == 1, "zero params", "wrong start queue count");
  check(result.fileCalls == 0, "zero params", "file queue was called");
  check(result.startPending, "zero params", "start flag was not queued");
  check(!result.filePending, "zero params", "file flag changed");
  check(result.fileValue == "unchanged", "zero params", "file value changed");
}

static void test_script_values() {
  AsyncWebParameter script("script", "main.lua");
  RunResult result = run_handler({&script});
  check_response(result, "script", 200, "text/html", "OK");
  check(result.startCalls == 0, "script", "start queue was called");
  check(result.fileCalls == 1, "script", "wrong file queue count");
  check(!result.startPending, "script", "start flag changed");
  check(result.filePending, "script", "file flag was not queued");
  check(result.fileValue == "main.lua", "script", "file value changed");

  AsyncWebParameter emptyScript("script", "");
  result = run_handler({&emptyScript});
  check_response(result, "empty script", 200, "text/html", "OK");
  check(result.startCalls == 0, "empty script", "start queue was called");
  check(result.fileCalls == 1, "empty script", "wrong file queue count");
  check(result.filePending, "empty script", "file flag was not queued");
  check(result.fileValue.empty(), "empty script", "empty value was not preserved");
}

static void test_busy() {
  RunResult result = run_handler({}, false, true);
  check_response(result, "busy start", 503, "application/json",
                 "{\"error\":\"BUSY\",\"field\":null,\"message\":\"BUSY\"}");
  check(result.startCalls == 1, "busy start", "wrong start queue count");
  check(result.fileCalls == 0, "busy start", "file queue was called");
  check(!result.startPending && !result.filePending, "busy start",
        "pending flag changed");
  check(result.fileValue == "unchanged", "busy start", "file value changed");

  AsyncWebParameter script("script", "busy.lua");
  result = run_handler({&script}, true, false);
  check_response(result, "busy file", 503, "application/json",
                 "{\"error\":\"BUSY\",\"field\":null,\"message\":\"BUSY\"}");
  check(result.startCalls == 0, "busy file", "start queue was called");
  check(result.fileCalls == 1, "busy file", "wrong file queue count");
  check(!result.startPending && !result.filePending, "busy file",
        "pending flag changed");
  check(result.fileValue == "unchanged", "busy file", "file value changed");
}

static void test_invalid_forms() {
  AsyncWebParameter unknown("other", "value");
  check_invalid(run_handler({&unknown}), "unknown");

  AsyncWebParameter firstScript("script", "first.lua");
  AsyncWebParameter secondScript("script", "second.lua");
  check_invalid(run_handler({&firstScript, &secondScript}), "duplicate");

  check_invalid(run_handler({&firstScript, &unknown}), "mixed");

  AsyncWebParameter postScript("script", "post.lua", true, false);
  check_invalid(run_handler({&postScript}), "POST parameter");

  AsyncWebParameter fileScript("script", "upload.lua", false, true);
  check_invalid(run_handler({&fileScript}), "file parameter");

  check_invalid(run_handler({nullptr}), "null parameter");
}

int main() {
  test_zero_params();
  test_script_values();
  test_busy();
  test_invalid_forms();
  if (failures != 0) return 1;
  std::cout << "Lua GET contract harness passed\n";
  return 0;
}
'''
    string_utils = (ROOT / "string_utils.h").read_text(encoding="utf-8", errors="ignore")
    web_server = WEB_SERVER.read_text(encoding="utf-8", errors="ignore")
    json_utils = "static String toJsonString(const String& s) {\n" + extract_function_body(
        string_utils, "inline String toJsonString(const String& s)"
    ) + "\n}"
    envelope = (
        "static String build_error_envelope(const char *code, const char *field, "
        "const String& message) {\n"
        + extract_function_body(
            web_server,
            "static String build_error_envelope(const char *code, const char *field, "
            "const String& message)",
        )
        + "\n}"
    )
    return (
        template.replace("@JSON_UTILS@", json_utils)
        .replace("@ERROR_ENVELOPE@", envelope)
        .replace("@HANDLER_BODY@", handler)
    )


def compile_and_run(harness: str) -> None:
    compiler = shutil.which("g++")
    if compiler is None:
        errors.append("g++ is required for the /lua behavioral harness")
        return

    with tempfile.TemporaryDirectory(prefix="samovar-lua-get-") as temporary:
        directory = Path(temporary)
        source = directory / "lua_get_contract.cpp"
        binary = directory / "lua_get_contract"
        source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            [
                compiler,
                "-std=c++11",
                "-Wall",
                "-Wextra",
                "-Werror",
                str(source),
                "-o",
                str(binary),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if compile_result.returncode != 0:
            errors.append(
                "/lua behavioral harness compile failed:\n"
                + compile_result.stderr.strip()
            )
            return

        run_result = subprocess.run(
            [str(binary)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if run_result.returncode != 0:
            output = "\n".join(
                value
                for value in (run_result.stdout.strip(), run_result.stderr.strip())
                if value
            )
            errors.append(f"/lua behavioral harness failed:\n{output}")


def main() -> int:
    if not WEB_SERVER.exists():
        print("Lua GET contract smoke failed:\n - WebServer.ino not found")
        return 1

    source = WEB_SERVER.read_text(encoding="utf-8", errors="ignore")
    try:
        handler = extract_lua_handler(source)
    except ValueError as exc:
        print(f"Lua GET contract smoke failed:\n - {exc}")
        return 1

    handler_without_comments = strip_cpp_comments(handler)
    forbidden_tokens = {
        "OperationId": "OperationStore lifecycle",
        "OperationStore": "OperationStore lifecycle",
        "operationId": "OperationStore lifecycle",
        "operation_store": "OperationStore lifecycle",
        '"/ajax"': "/ajax lookup",
        "waitForOperation": "operation polling",
        "run_lua_script(": "direct Lua execution",
        "start_lua_script(": "direct Lua execution",
        "load_lua_script(": "direct Lua execution",
        "get_lua_script_list(": "direct filesystem access",
        "SPIFFS": "direct filesystem access",
        "LittleFS": "direct filesystem access",
        "xTaskCreate": "new task",
        "TaskHandle_t": "new task lifecycle",
        "xQueueCreate": "new RTOS queue",
        "QueueHandle_t": "new RTOS queue",
        "vTaskDelay": "retry/delay path",
    }
    for token, label in forbidden_tokens.items():
        require(token not in handler_without_comments, f"handler contains {label}: {token}")

    lowered_handler = handler_without_comments.lower()
    for token in ("retry", "fallback"):
        require(token not in lowered_handler, f"handler contains forbidden {token} path")

    queue_calls = set(
        re.findall(r"\b(queue_[A-Za-z0-9_]+)\s*\(", handler_without_comments)
    )
    require(
        queue_calls <= {"queue_pending_flag", "queue_pending_string"},
        f"handler contains unexpected queue helper: {sorted(queue_calls)}",
    )
    require(
        "request->send(" not in handler_without_comments,
        "handler bypasses send_no_store_response",
    )

    compile_and_run(build_harness(handler))

    if errors:
        print("Lua GET contract smoke failed:")
        for error in errors:
            print(f" - {error}")
        return 1

    print("Lua GET contract smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
