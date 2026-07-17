#!/usr/bin/env python3
"""A-01 filesystem mount / web-startup boot contract (auto-format, always start web server).

Owner decision (2026-07-16): a device with a broken filesystem must be recoverable
remotely (format + remount + get_web_interface() re-downloads the UI), not only via
USB. The prior "fail-closed" contract (mount failure => no format, no web server)
traded away that remote recovery path and is intentionally reverted here.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import tempfile
import textwrap

from smoke_helpers import extract_braced_block_after, extract_function_body, strip_cpp_comments


ROOT = pathlib.Path(__file__).resolve().parents[1]
FS_SOURCE = ROOT / "FS.ino"
WEB_SOURCE = ROOT / "WebServer.ino"
SAMOVAR_SOURCE = ROOT / "Samovar.ino"
API_SOURCE = ROOT / "samovar_api.h"
ROOT_FIRMWARE_SOURCES = tuple(
    sorted((*ROOT.glob("*.ino"), *ROOT.glob("*.h")), key=lambda path: path.name)
)

errors: list[str] = []


def require(condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def body(source: str, signature: str) -> str:
    try:
        return extract_function_body(source, signature)
    except ValueError as error:
        errors.append(str(error))
        return ""


def ordered(source: str, tokens: list[str], label: str) -> None:
    position = -1
    for token in tokens:
        next_position = source.find(token, position + 1)
        if next_position < 0:
            errors.append(f"{label}: missing or out-of-order token {token!r}")
            return
        position = next_position


def require_no_halt_block(
    source: str,
    condition_token: str,
    must_contain: str,
    label: str,
) -> None:
    """Owner decision: FS mount degradation must degrade and continue, not halt."""
    try:
        block, _ = extract_braced_block_after(source, condition_token)
    except ValueError as error:
        errors.append(f"{label}: {error}")
        return
    require(
        must_contain in block,
        f"{label}: missing expected degraded-boot action {must_contain!r}",
    )
    require(
        re.search(r"while\s*\(\s*true\s*\)", block) is None,
        f"{label}: must not contain a perpetual halt",
    )


def compile_and_run_fs_init(fs_init_body: str) -> None:
    compiler = shutil.which("g++")
    if compiler is None:
        errors.append("g++ is required for the A-01 FS_init behavioral harness")
        return

    harness = textwrap.dedent(
        r'''
        #include <assert.h>
        #include <stddef.h>
        #include <stdint.h>
        #include <string.h>

        #include <string>

        #define F(value) value

        enum FsInitResult : uint8_t {
          FS_INIT_OK = 0,
          FS_INIT_MOUNT_FAILED,
          FS_INIT_FORMATTED,
        };

        struct FakeSerial {
          std::string output;

          void println(const char* value) {
            output += value;
            output += '\n';
          }
        } Serial;

        // beginResults[0] is returned by the first SPIFFS.begin(false) call, beginResults[1]
        // by the (optional) second call after a format. format() flips userFilesPresent to
        // false, standing in for SPIFFS.format() wiping Lua scripts/logs/UI off real flash.
        struct FakeSPIFFS {
          bool beginResults[2] = {false, false};
          size_t beginResultCount = 0;
          bool formatResult = true;
          size_t beginCalls = 0;
          size_t formatCalls = 0;
          size_t totalBytesCalls = 0;
          size_t totalValue = 0;
          bool userFilesPresent = true;

          bool begin(bool formatOnFail) {
            (void)formatOnFail;
            size_t index = beginCalls < beginResultCount ? beginCalls : beginResultCount - 1;
            ++beginCalls;
            return beginResults[index];
          }

          bool format() {
            ++formatCalls;
            userFilesPresent = false;
            return formatResult;
          }

          size_t totalBytes() {
            ++totalBytesCalls;
            return totalValue;
          }
        } SPIFFS;

        size_t total_byte = 0;

        FsInitResult FS_init(void) {
        @FS_INIT_BODY@
        }

        static void reset_fixture(bool first, bool second, bool formatResult, size_t totalValue) {
          SPIFFS.beginResults[0] = first;
          SPIFFS.beginResults[1] = second;
          SPIFFS.beginResultCount = 2;
          SPIFFS.formatResult = formatResult;
          SPIFFS.beginCalls = 0;
          SPIFFS.formatCalls = 0;
          SPIFFS.totalBytesCalls = 0;
          SPIFFS.totalValue = totalValue;
          SPIFFS.userFilesPresent = true;
          Serial.output.clear();
        }

        int main() {
          // Mount succeeds on the first try: no format, no data loss.
          reset_fixture(true, true, true, 4096);
          total_byte = 0xA5A5U;
          assert(FS_init() == FS_INIT_OK);
          assert(SPIFFS.beginCalls == 1);
          assert(SPIFFS.formatCalls == 0);
          assert(SPIFFS.totalBytesCalls == 1);
          assert(total_byte == 4096U);
          assert(SPIFFS.userFilesPresent == true);

          // Mount fails, format succeeds, remount succeeds: recovered, user files wiped.
          reset_fixture(false, true, true, 0x2222U);
          total_byte = 0x5A5AU;
          assert(FS_init() == FS_INIT_FORMATTED);
          assert(SPIFFS.beginCalls == 2);
          assert(SPIFFS.formatCalls == 1);
          assert(SPIFFS.totalBytesCalls == 1);
          assert(total_byte == 0x2222U);
          assert(SPIFFS.userFilesPresent == false);

          // Mount fails, format fails outright: unrecoverable, no total_byte update.
          reset_fixture(false, false, false, 0x9999U);
          total_byte = 0x1111U;
          assert(FS_init() == FS_INIT_MOUNT_FAILED);
          assert(SPIFFS.beginCalls == 1);
          assert(SPIFFS.formatCalls == 1);
          assert(SPIFFS.totalBytesCalls == 0);
          assert(total_byte == 0x1111U);

          // Mount fails, format succeeds, remount still fails: unrecoverable.
          reset_fixture(false, false, true, 0x8888U);
          total_byte = 0x3333U;
          assert(FS_init() == FS_INIT_MOUNT_FAILED);
          assert(SPIFFS.beginCalls == 2);
          assert(SPIFFS.formatCalls == 1);
          assert(SPIFFS.totalBytesCalls == 0);
          assert(total_byte == 0x3333U);
          return 0;
        }
        '''
    ).replace("@FS_INIT_BODY@", fs_init_body)

    with tempfile.TemporaryDirectory(prefix="samovar-a01-fs-") as temp_dir:
        source_path = pathlib.Path(temp_dir) / "fs_init.cpp"
        binary_path = pathlib.Path(temp_dir) / "fs_init"
        source_path.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            [
                compiler,
                "-std=c++11",
                "-Wall",
                "-Wextra",
                "-Werror",
                str(source_path),
                "-o",
                str(binary_path),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        if compile_result.returncode != 0:
            errors.append("FS_init host compile failed:\n" + compile_result.stderr)
            return
        run_result = subprocess.run(
            [str(binary_path)], text=True, capture_output=True, check=False
        )
        if run_result.returncode != 0:
            errors.append("FS_init host behavior failed:\n" + run_result.stderr)


fs_text = strip_cpp_comments(FS_SOURCE.read_text(encoding="utf-8"))
web_text = strip_cpp_comments(WEB_SOURCE.read_text(encoding="utf-8"))
samovar_text = strip_cpp_comments(SAMOVAR_SOURCE.read_text(encoding="utf-8"))
api_text = strip_cpp_comments(API_SOURCE.read_text(encoding="utf-8"))
root_firmware = {
    path.name: strip_cpp_comments(path.read_text(encoding="utf-8"))
    for path in ROOT_FIRMWARE_SOURCES
}
root_firmware_text = "\n".join(root_firmware.values())

require(
    len(ROOT_FIRMWARE_SOURCES) > 0,
    "root firmware source inventory is empty",
)

require(
    re.search(
        r"enum\s+FsInitResult\s*:\s*uint8_t\s*\{\s*"
        r"FS_INIT_OK\s*=\s*0\s*,\s*FS_INIT_MOUNT_FAILED\s*,\s*FS_INIT_FORMATTED\s*,?\s*\}\s*;",
        api_text,
        re.DOTALL,
    )
    is not None,
    "samovar_api.h has no exact FsInitResult contract",
)
require(
    "WebServerInitResult" not in api_text,
    "samovar_api.h must not declare WebServerInitResult: web server always starts now",
)
require(
    "WebServerInitResult" not in root_firmware_text,
    "root firmware must not reference WebServerInitResult: web server always starts now",
)

for declaration in (
    "FsInitResult FS_init(void);",
    "void FS_register_web_handlers(void);",
    "void WebServerInit(void);",
):
    require(
        api_text.count(declaration) == 1,
        f"samovar_api.h must declare exactly one {declaration}",
    )
require("void FS_init(void);" not in api_text, "legacy void FS_init declaration remains")

symbol_contracts = (
    (
        "FS_init",
        r"\bFsInitResult\s+FS_init\s*\(\s*void\s*\)\s*\{",
        r"\bFS_init\s*\(\s*\)\s*;",
    ),
    (
        "FS_register_web_handlers",
        r"\bvoid\s+FS_register_web_handlers\s*\(\s*void\s*\)\s*\{",
        r"\bFS_register_web_handlers\s*\(\s*\)\s*;",
    ),
    (
        "WebServerInit",
        r"\bvoid\s+WebServerInit\s*\(\s*void\s*\)\s*\{",
        r"\bWebServerInit\s*\(\s*\)\s*;",
    ),
)
for symbol, definition_pattern, call_pattern in symbol_contracts:
    require(
        len(re.findall(rf"\b{symbol}\s*\(", root_firmware_text)) == 3,
        f"root firmware must contain one declaration, definition, and call for {symbol}",
    )
    require(
        len(re.findall(definition_pattern, root_firmware_text)) == 1,
        f"root firmware must contain one definition for {symbol}",
    )
    require(
        len(re.findall(call_pattern, root_firmware_text)) == 1,
        f"root firmware must contain one call site for {symbol}",
    )

require(
    len(re.findall(r"\bserver\s*\.\s*begin\s*\(\s*\)", root_firmware_text)) == 1,
    "root firmware must contain one server.begin() call",
)
# Обновление интерфейса живёт в get_web_interface() и пинится отдельно, в
# tools/smoke_web_interface_update.py. Здесь важно лишь, что FS_init им не занимается,
# и что WebServerInit его безусловно вызывает после server.begin().

fs_init_body = body(fs_text, "FsInitResult FS_init(void)")
if fs_init_body:
    require(
        fs_init_body.count("SPIFFS.begin(false)") == 2,
        "FS_init must call SPIFFS.begin(false) once up front and once after formatting",
    )
    require(
        fs_init_body.count("SPIFFS.format()") == 1,
        "FS_init must auto-format on mount failure (owner: remote recovery beats a soldering iron)",
    )
    for forbidden in (
        "SPIFFS.open",
        "SPIFFS.remove",
        "SPIFFS.rename",
        "server.",
        "events.",
        "SPIFFSEditor",
        "FS_register_web_handlers",
        "get_web_interface",
        "SendMsg",
    ):
        require(forbidden not in fs_init_body, f"FS_init contains forbidden {forbidden}")
    ordered(
        fs_init_body,
        [
            "if (!SPIFFS.begin(false))",
            'Serial.println(F("Не удалось подключиться к файловой системе, форматируем..."));',
            "if (!SPIFFS.format())",
            'Serial.println(F("Не удалось отформатировать файловую систему, загрузите интерфейс через Arduino"));',
            "return FS_INIT_MOUNT_FAILED;",
            "if (!SPIFFS.begin(false))",
            'Serial.println(F("Ошибка файловой системы! Загрузите через Arduino"));',
            "return FS_INIT_MOUNT_FAILED;",
            "formatted = true;",
            "total_byte = SPIFFS.totalBytes();",
            "return formatted ? FS_INIT_FORMATTED : FS_INIT_OK;",
        ],
        "FS_init",
    )
    compile_and_run_fs_init(fs_init_body)

handler_body = body(fs_text, "void FS_register_web_handlers(void)")
handler_groups = (
    "events.onConnect(",
    "server.addHandler(&events)",
    "server.addHandler(new SPIFFSEditor(SPIFFS))",
    "server.onNotFound(",
    "server.onFileUpload(",
    "server.onRequestBody(",
)
for token in handler_groups:
    require(handler_body.count(token) == 1, f"FS handler owner must contain one {token}")
    require(
        root_firmware_text.count(token) == 1,
        f"FS handler registration must have one production owner: {token}",
    )

web_init_body = body(web_text, "void WebServerInit(void)")
if web_init_body:
    require(
        "fsInitResult" not in web_init_body,
        "WebServerInit must not gate on fsInitResult anymore: web server always starts",
    )
    compact_web = re.sub(r"\s+", " ", web_init_body).strip()
    require(
        compact_web.startswith("FS_register_web_handlers();"),
        "WebServerInit must register FS handlers unconditionally as its first action",
    )
    ordered(
        web_init_body,
        [
            "FS_register_web_handlers();",
            'server.on("/", HTTP_GET | HTTP_POST',
            # Обновление интерфейса идёт ПОСЛЕ старта сервера и не решает, жить ему
            # или нет: недоступный web.samovar-tool.ru не должен лишать пользователя
            # локального веб-интерфейса, который уже лежит на ФС.
            "server.begin();",
            "get_web_interface();",
        ],
        "WebServerInit",
    )
require(
    web_init_body.count("server.begin()") == 1,
    "WebServerInit must start the server once",
)
require(
    web_init_body.count("get_web_interface();") == 1,
    "WebServerInit must call get_web_interface once",
)

setup_body = body(samovar_text, "void setup()")
if setup_body:
    ordered(
        setup_body,
        [
            "SamSetup = startupProfile;",
            'print_nvs_stats("after config load");',
            "const FsInitResult fsInitResult = FS_init();",
            "if (fsInitResult == FS_INIT_FORMATTED)",
            'report_degraded_boot("filesystem", "formatted, user files lost");',
            "else if (fsInitResult != FS_INIT_OK)",
            'report_degraded_boot("filesystem", "mount failed");',
            "esp_log_level_set",
            "AsyncWiFiManager",
            "startService();",
            "WebServerInit();",
            'Serial.println(F("Samovar started"));',
            "xTaskCreatePinnedToCore",
        ],
        "setup auto-format boot order",
    )
    require(
        "WebServerInit(fsInitResult)" not in setup_body,
        "setup() must call WebServerInit() unconditionally, no fsInitResult argument",
    )
    require(
        "webServerInitResult" not in setup_body,
        "setup() must not branch on a WebServerInit result anymore",
    )
    # Owner decision: FS mount failure (formatted-recovery or fully unrecoverable) degrades
    # and continues (report_degraded_boot), it must not halt the boot forever.
    require_no_halt_block(
        setup_body,
        "if (fsInitResult == FS_INIT_FORMATTED)",
        'report_degraded_boot("filesystem", "formatted, user files lost");',
        "filesystem auto-format gate",
    )
    require_no_halt_block(
        setup_body,
        "else if (fsInitResult != FS_INIT_OK)",
        'report_degraded_boot("filesystem", "mount failed");',
        "filesystem unrecoverable-mount gate",
    )
    fs_call = setup_body.find("const FsInitResult fsInitResult = FS_init();")
    require(fs_call >= 0, "setup filesystem mount call is missing")
    startup_side_effect_patterns = (
        (
            "WiFi API",
            r"(?:\bWiFi\s*\.\s*[A-Za-z_]\w*\s*\(|"
            r"\bAsyncWiFiManager(?:Parameter)?\s+[A-Za-z_]\w*\s*\()",
        ),
        (
            "touch API",
            r"\btouch_[A-Za-z_]\w*\s*\(",
        ),
        (
            "I2C/Wire API",
            r"(?:\bWire\s*\.\s*[A-Za-z_]\w*\s*\(|"
            r"\b(?:check_I2C_device|detect_i2c_steppers|sensor_init|"
            r"refresh_i2c_stepper_cache)\s*\()",
        ),
        (
            "semaphore API",
            r"\bxSemaphore[A-Za-z0-9_]*\s*\(",
        ),
        (
            "task startup",
            r"\b(?:xTaskCreate(?:PinnedToCore)?|startService|"
            r"initEmergencyButtonTask)\s*\(",
        ),
    )
    if fs_call >= 0:
        pre_mount_setup = setup_body[:fs_call]
        for label, pattern in startup_side_effect_patterns:
            matches = list(re.finditer(pattern, setup_body))
            require(matches, f"setup side-effect inventory has no {label} tokens")
            for match in matches:
                position = match.start()
                token = match.group(0).strip()
                require(
                    position > fs_call,
                    f"filesystem gate must precede {label} token {token}",
                )
            require(
                re.search(pattern, pre_mount_setup) is None,
                f"pre-mount setup prefix contains forbidden {label} side effect",
            )
    for direct_startup_token in ("esp_log_level_set", "pinMode(0, INPUT)"):
        position = setup_body.find(direct_startup_token)
        require(
            position < 0 or fs_call < position,
            f"filesystem gate must precede {direct_startup_token}",
        )
    require(
        setup_body.count('Serial.println(F("Samovar started"));') == 1,
        "Samovar started diagnostic must occur exactly once",
    )

if errors:
    for error in errors:
        print(f"ERROR: {error}")
    raise SystemExit(1)

print("PASS: A-01 filesystem mount auto-format and unconditional web startup")
