#!/usr/bin/env python3
"""Source-derived contract for the read-only /ui-bootstrap response."""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens


ROOT = Path(__file__).resolve().parents[1]
WEB_SERVER = ROOT / "WebServer.ino"
STRING_UTILS = ROOT / "string_utils.h"
errors: list[str] = []


def require(condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def extract_route_handler(source: str) -> str:
    marker = 'server.on("/ui-bootstrap"'
    count = source.count(marker)
    require(count == 1,
            f"/ui-bootstrap должен быть зарегистрирован ровно один раз, найдено {count}")
    if count != 1:
        return ""
    return extract_function_body(source, marker)


def extract_or_error(source: str, signature: str) -> str:
    try:
        return extract_function_body(source, signature)
    except ValueError as exc:
        errors.append(str(exc))
        return ""


def check_static(source: str) -> tuple[str, str, str]:
    route_matches = re.findall(
        r'server\.on\("/ui-bootstrap"\s*,\s*(HTTP_[A-Z_]+)\s*,', source)
    require(route_matches == ["HTTP_GET"],
            f"/ui-bootstrap должен быть ровно одним HTTP_GET, найдено {route_matches}")

    handler = extract_route_handler(source)
    capture_signature = "static bool capture_ui_bootstrap_snapshot(UiBootstrapSnapshot& snapshot) {"
    writer_signature = "static bool write_ui_bootstrap_json(Print& out, const UiBootstrapSnapshot& snapshot) {"
    capture = extract_or_error(source, capture_signature)
    writer = extract_or_error(source, writer_signature)
    helper_start = source.find("static bool ui_bootstrap_write_key")
    writer_start = source.find(writer_signature)
    writer_scope = (
        source[helper_start:writer_start]
        + writer_signature + "\n"
        + writer + "\n}"
        if helper_start >= 0 and writer_start >= 0 else writer
    )

    if handler:
        web_init = source.find("void WebServerInit(void)")
        require(source.find("struct UiBootstrapSnapshot") < web_init and
                source.find("static bool capture_ui_bootstrap_snapshot(UiBootstrapSnapshot& snapshot);") < web_init and
                source.find("static bool write_ui_bootstrap_json(Print& out, const UiBootstrapSnapshot& snapshot);") < web_init,
                "/ui-bootstrap использует тип или функции до их объявления")
        require_ordered_tokens(
            "/ui-bootstrap rejects request parameters before snapshot",
            handler,
            ["request->params() != 0", "400", "capture_ui_bootstrap_snapshot(snapshot)", "503",
             "beginResponseStream(\"application/json\")"],
            errors,
        )
        require("mode_switch_in_progress()" in handler,
                "/ui-bootstrap не отклоняет смену режима")
        require(handler.count("mode_switch_in_progress()") >= 2,
                "/ui-bootstrap должен повторно проверить барьер перед stream")
        require(handler.count("send_no_store_response(") == 4,
                "/ui-bootstrap должен отправлять ошибки через no-store helper")
        require(handler.count('send_no_store_response(request, 503') == 3,
                "/ui-bootstrap должен вернуть 503 для барьеров и сбоя snapshot/JSON")
        require('response->addHeader("Cache-Control", "no-store")' in handler,
                "/ui-bootstrap не ставит no-store на успешный ответ")
        for forbidden in ("send_ajax_json(", "SPIFFS.", "i2c_stepper_", "Wire.",
                          "nvs_", "delay(", "vTaskDelay("):
            require(forbidden not in handler,
                    f"/ui-bootstrap содержит запрещённую async-операцию: {forbidden}")

    if capture:
        require_ordered_tokens(
            "/ui-bootstrap copies SetupEEPROM only inside configMux",
            capture,
            ["portENTER_CRITICAL(&configMux)", "snapshot.setup = SamSetup",
             "portEXIT_CRITICAL(&configMux)", "serialize_program_for_mode(snapshot.mode)"],
            errors,
        )
        require("copy_session_description(snapshot.description, 0)" in capture,
                "/ui-bootstrap должен копировать description без ожидания")
        require("copy_lua_button_list_cache(snapshot.luaButtonList, 0)" in capture,
                "/ui-bootstrap должен копировать Lua cache без ожидания")
        require("runtime_state_lock(" not in capture,
                "/ui-bootstrap не должен брать runtime lock напрямую")
        require("snapshot.version = SAMOVAR_VERSION" in capture,
                "/ui-bootstrap должен копировать flash-версию в String до stream")
        require("control_power_input_max(" in capture and "!powerResult.ok()" in capture,
                "/ui-bootstrap должен явно отклонять невычислимую heaterMaxPower")

    if writer_scope:
        require("json_write_escaped(" in writer_scope,
                "/ui-bootstrap должен экранировать JSON общим helper")
        require("toJsonString(" not in writer_scope,
                "/ui-bootstrap не должен собирать JSON-строки через временный String")
        for field in (
            '"mode"', '"version"', '"powerUnit"', '"program"', '"description"',
            '"luaButtonList"', '"steamColor"', '"steamVisible"',
            '"i2cStepperVisible"', '"beerBrewOrder"', '"nbkDp"',
            '"stepperStepsPerMl"', '"calibrationRunning"', '"cheesePhSlope"',
            '"cheesePhAvailable"', '"cheesePhAds1115Address"',
            '"cheeseCoolingScheme"', '"heaterMaxPower"', '"timeZone"',
        ):
            require(field in writer, f"/ui-bootstrap не отдаёт обязательное поле {field}")
        cooling = extract_or_error(
            source, "static const char* ui_bootstrap_cheese_cooling_scheme() {"
        )
        require(
            '#if defined(USE_WATER_PUMP)' in cooling and
            '#elif defined(USE_WATER_VALVE)' in cooling and
            '#else' in cooling and
            'return "pump";' in cooling and
            'return "two-valves";' in cooling and
            'return "unavailable";' in cooling,
            "/ui-bootstrap должен выбирать схему охлаждения только по compile-time флагам",
        )
        require("strlen(SAMOVAR_VERSION)" not in writer_scope,
                "/ui-bootstrap обращается к flash-версии как к RAM-строке")
        require("if (!isfinite(value)) return false;" in writer_scope,
                "/ui-bootstrap должен отклонять NaN/Inf до записи JSON-числа")
        require("value > 99999.0f || value < -99999.0f) return false;" in writer_scope,
                "/ui-bootstrap должен отклонять float вне диапазона форматирования")
    return handler, capture, writer_scope


def build_writer_harness(writer_scope: str, json_escape: str) -> str:
    return r'''
#include <cstdint>
#include <cstdio>
#include <string>
#include <cstring>
#include <cmath>
#include <limits>

class __FlashStringHelper {};

class String {
 public:
  String() = default;
  String(const char* value) : value_(value ? value : "") {}
  String(const __FlashStringHelper* value)
      : value_(reinterpret_cast<const char*>(value)) {}
  String(char value) : value_(1, value) {}
  String(const std::string& value) : value_(value) {}
  size_t length() const { return value_.size(); }
  const char* c_str() const { return value_.c_str(); }
  char charAt(size_t index) const { return value_[index]; }
 private:
  std::string value_;
};

class Print {
 public:
  virtual ~Print() = default;
  virtual size_t write(uint8_t value) = 0;
  virtual size_t write(const uint8_t* value, size_t length) = 0;
  size_t print(const char* value) { return write(reinterpret_cast<const uint8_t*>(value), std::strlen(value)); }
  size_t print(char value) { return write(static_cast<uint8_t>(value)); }
  size_t print(bool value) { return print(value ? "1" : "0"); }
  size_t print(unsigned long value) { return print(std::to_string(value).c_str()); }
  size_t print(long value) { return print(std::to_string(value).c_str()); }
  size_t print(int value) { return print(std::to_string(value).c_str()); }
  size_t print(float value, int digits) {
    char out[64]; std::snprintf(out, sizeof(out), "%.*f", digits, static_cast<double>(value)); return print(out);
  }
};

class Output : public Print {
 public:
  size_t write(uint8_t value) override { data += static_cast<char>(value); return 1; }
  size_t write(const uint8_t* value, size_t length) override {
    data.append(reinterpret_cast<const char*>(value), length); return length;
  }
  std::string data;
};

enum SAMOVAR_MODE { SAMOVAR_RECTIFICATION_MODE, SAMOVAR_NBK_MODE };
#define F(value) (reinterpret_cast<const __FlashStringHelper*>(value))
using std::isfinite;
struct SetupEEPROM {
  char SteamColor[20]; char PipeColor[20]; char WaterColor[20]; char TankColor[20]; char ACPColor[20];
  uint8_t BeerBrewOrder; float NbkDP; float ColDiam; float ColHeight; uint8_t PackDens;
  float HeaterResistant; float MainsVoltage; uint16_t StepperStepMl; uint16_t StepperStepMlI2C;
  float CheesePhSlope; float CheesePhOffset; uint8_t TimeZone;
};
struct UiBootstrapSnapshot {
  SAMOVAR_MODE mode; SetupEEPROM setup; String program; String description; String luaButtonList; String version; String powerUnit;
  bool steamVisible; bool pipeVisible; bool waterVisible; bool tankVisible; bool pressureVisible; bool programNumberVisible;
  bool i2cStepperVisible; bool i2cPumpVisible; bool calibrationRunning; bool i2cCalibration;
  bool cheesePhAvailable; int cheesePhAds1115Address;
  int pwmValue; float pwmLow; float heaterMaxPower;
};
static const unsigned long STEPPER_MAX_SPEED = 1200;

static bool json_write_escaped(Print& out, const char* text, size_t length) {
@JSON_ESCAPE@
}

@WRITER_SCOPE@

static UiBootstrapSnapshot make_snapshot(SAMOVAR_MODE mode, const char* program, bool i2c) {
  UiBootstrapSnapshot snapshot{};
  snapshot.mode = mode; snapshot.program = String(program); snapshot.description = String("desc\\n\"<x>");
  snapshot.luaButtonList = String("[\"Lua\"]"); snapshot.version = String(F("7.00")); snapshot.powerUnit = String("V");
  std::snprintf(snapshot.setup.SteamColor, sizeof(snapshot.setup.SteamColor), "%s", "#123456");
  std::snprintf(snapshot.setup.PipeColor, sizeof(snapshot.setup.PipeColor), "%s", "#234567");
  std::snprintf(snapshot.setup.WaterColor, sizeof(snapshot.setup.WaterColor), "%s", "#345678");
  std::snprintf(snapshot.setup.TankColor, sizeof(snapshot.setup.TankColor), "%s", "#456789");
  std::snprintf(snapshot.setup.ACPColor, sizeof(snapshot.setup.ACPColor), "%s", "#56789A");
  snapshot.setup.BeerBrewOrder = mode == SAMOVAR_NBK_MODE ? 2 : 1;
  snapshot.setup.NbkDP = mode == SAMOVAR_NBK_MODE ? 1.25f : 0.5f;
  snapshot.setup.ColDiam = mode == SAMOVAR_NBK_MODE ? 3.0f : 1.5f;
  snapshot.setup.ColHeight = 1.7f; snapshot.setup.PackDens = 80; snapshot.setup.HeaterResistant = 12.3f;
  snapshot.setup.MainsVoltage = 220.0f; snapshot.setup.StepperStepMl = 123; snapshot.setup.StepperStepMlI2C = 456;
  snapshot.setup.CheesePhSlope = 2.5f; snapshot.setup.CheesePhOffset = -1.0f;
  snapshot.setup.TimeZone = mode == SAMOVAR_NBK_MODE ? 3 : 5;
  snapshot.cheesePhAvailable = !i2c; snapshot.cheesePhAds1115Address = i2c ? 0x48 : 0;
  snapshot.steamVisible = true; snapshot.pipeVisible = false; snapshot.waterVisible = true; snapshot.tankVisible = false;
  snapshot.pressureVisible = true; snapshot.programNumberVisible = true; snapshot.i2cStepperVisible = i2c; snapshot.i2cPumpVisible = i2c;
  snapshot.calibrationRunning = i2c; snapshot.i2cCalibration = i2c; snapshot.pwmValue = i2c ? 77 : 11; snapshot.pwmLow = i2c ? 20.0f : 10.0f; snapshot.heaterMaxPower = 1234.0f;
  return snapshot;
}

int main() {
  for (const UiBootstrapSnapshot& snapshot : {make_snapshot(SAMOVAR_RECTIFICATION_MODE, "H;10;20;0;0;100\\n", false), make_snapshot(SAMOVAR_NBK_MODE, "N;30;40;1\\n", true)}) {
    Output out;
    if (!write_ui_bootstrap_json(out, snapshot)) return 2;
    std::puts(out.data.c_str());
  }
  UiBootstrapSnapshot overflow = make_snapshot(SAMOVAR_RECTIFICATION_MODE, "H;10;20;0;0;100\\n", false);
  overflow.setup.NbkDP = 1.0e20f;
  Output overflowOut;
  if (write_ui_bootstrap_json(overflowOut, overflow)) {
    std::puts("float вне диапазона был сериализован как JSON-число");
    return 3;
  }
  UiBootstrapSnapshot nan = make_snapshot(SAMOVAR_RECTIFICATION_MODE, "H;10;20;0;0;100\\n", false);
  nan.setup.NbkDP = std::numeric_limits<float>::quiet_NaN();
  Output nanOut;
  if (write_ui_bootstrap_json(nanOut, nan)) {
    std::puts("NaN был сериализован как JSON-число");
    return 4;
  }
  return 0;
}
'''.replace("@JSON_ESCAPE@", json_escape).replace("@WRITER_SCOPE@", writer_scope)


def check_writer_behavior(writer_scope: str) -> None:
    if not writer_scope:
        return
    string_utils = STRING_UTILS.read_text(encoding="utf-8")
    json_escape = extract_or_error(
        string_utils,
        "inline bool json_write_escaped(Print& out, const char* text, size_t length)",
    )
    if not json_escape:
        return
    with tempfile.TemporaryDirectory(prefix="samovar-ui-bootstrap-") as tmp:
        source_path = Path(tmp) / "ui_bootstrap.cpp"
        binary_path = Path(tmp) / "ui_bootstrap"
        source_path.write_text(build_writer_harness(writer_scope, json_escape), encoding="utf-8")
        result = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source_path), "-o", str(binary_path)],
            capture_output=True, text=True,
        )
        if result.returncode:
            errors.append("ui-bootstrap writer harness не компилируется:\n" + result.stderr)
            return
        result = subprocess.run([str(binary_path)], capture_output=True, text=True)
        if result.returncode:
            errors.append("ui-bootstrap writer harness завершился с ошибкой:\n" + result.stdout + result.stderr)
            return
    lines = [line for line in result.stdout.splitlines() if line]
    require(len(lines) == 2, f"writer должен вывести два JSON-снимка, получено {len(lines)}")
    if len(lines) != 2:
        return
    try:
        rect, nbk = (json.loads(line) for line in lines)
    except json.JSONDecodeError as exc:
        errors.append(f"writer выдал невалидный JSON: {exc}")
        return
    require(rect["mode"] != nbk["mode"], "два режима вернули один mode")
    require(rect["program"] != nbk["program"], "два режима вернули одну программу")
    require(rect["i2cPumpVisible"] is False and nbk["i2cPumpVisible"] is True,
            "признак I2C насоса не сохранил два разных состояния")
    require(isinstance(rect["nbkDp"], (int, float)), "nbkDp должен быть числом")
    require(isinstance(nbk["calibrationRunning"], bool), "calibrationRunning должен быть bool")
    require(rect["cheesePhAvailable"] is True and nbk["cheesePhAvailable"] is False,
            "доступность pH не сохранила два разных состояния")
    require(rect["cheesePhAds1115Address"] == 0 and nbk["cheesePhAds1115Address"] == 0x48,
            "адрес ADS1115 потерян в bootstrap")
    require(rect["timeZone"] == 5 and nbk["timeZone"] == 3,
            "timeZone не сохранил два разных значения SetupEEPROM")
    require(rect["cheeseCoolingScheme"] == "unavailable" and
            nbk["cheeseCoolingScheme"] == "unavailable",
            "сборка без охлаждения должна отдавать unavailable")
    for define, expected in (("USE_WATER_PUMP", "pump"), ("USE_WATER_VALVE=1", "two-valves")):
        with tempfile.TemporaryDirectory(prefix="samovar-ui-bootstrap-cooling-") as tmp:
            source_path = Path(tmp) / "ui_bootstrap.cpp"
            binary_path = Path(tmp) / "ui_bootstrap"
            source_path.write_text(build_writer_harness(writer_scope, json_escape), encoding="utf-8")
            result = subprocess.run(
                ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", f"-D{define}",
                 str(source_path), "-o", str(binary_path)],
                capture_output=True, text=True,
            )
            if result.returncode:
                errors.append(f"ui-bootstrap writer harness ({expected}) не компилируется:\n" + result.stderr)
                continue
            result = subprocess.run([str(binary_path)], capture_output=True, text=True)
            if result.returncode:
                errors.append(f"ui-bootstrap writer harness ({expected}) завершился с ошибкой:\n" + result.stdout + result.stderr)
                continue
            try:
                payloads = [json.loads(line) for line in result.stdout.splitlines() if line]
            except json.JSONDecodeError as exc:
                errors.append(f"writer ({expected}) выдал невалидный JSON: {exc}")
                continue
            require(len(payloads) == 2 and all(payload["cheeseCoolingScheme"] == expected for payload in payloads),
                    f"сборка {expected} не отдала схему охлаждения {expected}")
    require(rect["description"] == 'desc\\n"<x>', "description не прошёл JSON escaping round-trip")
    require(rect["luaButtonList"] == '["Lua"]', "luaButtonList не прошёл JSON escaping round-trip")
    require(rect["version"] == "7.00", "flash-версия не сериализуется как строка")
    require(rect["heaterMaxPower"] == 1234.0, "heaterMaxPower потерян или не число")


def check_mutation_contracts(source: str) -> None:
    if "--skip-mutations" in sys.argv:
        return
    mutations = (
        (
            "configMux",
            lambda text: text.replace("  portENTER_CRITICAL(&configMux);\n  snapshot.setup = SamSetup;",
                                      "  snapshot.setup = SamSetup;", 1),
            "/ui-bootstrap copies SetupEEPROM only inside configMux",
        ),
        (
            "JSON escaping",
            lambda text: text.replace("json_write_escaped(", "raw_json_write("),
            "/ui-bootstrap должен экранировать JSON общим helper",
        ),
        (
            "request parameters",
            lambda text: text.replace("request->params() != 0", "request->params() > 1", 1),
            "/ui-bootstrap rejects request parameters before snapshot",
        ),
        (
            "503 status",
            lambda text: text.replace(
                "if (mode_switch_in_progress()) {\n"
                "      send_no_store_response(request, 503, \"text/plain\", \"BUSY\");",
                "if (mode_switch_in_progress()) {\n"
                "      send_no_store_response(request, 200, \"text/plain\", \"BUSY\");", 1),
            "/ui-bootstrap должен вернуть 503 для барьеров и сбоя snapshot/JSON",
        ),
        (
            "cheese cooling scheme",
            lambda text: text.replace('return "two-valves";', 'return "pump";', 1),
            "/ui-bootstrap должен выбирать схему охлаждения только по compile-time флагам",
        ),
    )
    script = Path(__file__).read_text(encoding="utf-8")
    helpers = (ROOT / "tools" / "smoke_helpers.py").read_text(encoding="utf-8")
    string_utils = STRING_UTILS.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="samovar-ui-bootstrap-mutations-") as tmp:
        root = Path(tmp)
        tools = root / "tools"
        tools.mkdir()
        (tools / "smoke_ui_bootstrap.py").write_text(script, encoding="utf-8")
        (tools / "smoke_helpers.py").write_text(helpers, encoding="utf-8")
        (root / "string_utils.h").write_text(string_utils, encoding="utf-8")
        for name, mutate, expected_error in mutations:
            mutated = mutate(source)
            if mutated == source:
                errors.append(f"mutation {name} не изменила временный исходник")
                continue
            (root / "WebServer.ino").write_text(mutated, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(tools / "smoke_ui_bootstrap.py"), "--skip-mutations"],
                cwd=root, capture_output=True, text=True,
            )
            output = result.stdout + result.stderr
            require(result.returncode != 0,
                    f"mutation {name} должна завершать smoke неуспехом")
            require(expected_error in output,
                    f"mutation {name} не дала содержательную ошибку:\n{output}")


def main() -> int:
    source = WEB_SERVER.read_text(encoding="utf-8")
    _, _, writer = check_static(source)
    check_writer_behavior(writer)
    check_mutation_contracts(source)
    if errors:
        for error in errors:
            print("ERROR:", error)
        return 1
    print("PASS: /ui-bootstrap route, snapshot and streaming JSON contract")
    return 0


if __name__ == "__main__":
    sys.exit(main())
