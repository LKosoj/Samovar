#!/usr/bin/env python3
"""[P8] NVS-чекпоинт сессии (Samovar.ino): статические пины + поведенческий тест.

Статика:
- session_checkpoint_capture_pending() открывает "sam_sess" через NVS_READONLY
  (проба на существование - НЕ создаёт неймспейс), не через NVS_READWRITE.
- Ни одна из session_checkpoint_* функций не дёргает set_power(true) - чекпоинт
  только диагностика, автозапуска нагрева НЕТ.
- Вызов session_checkpoint_capture_pending() в setup() стоит СТРОГО ПОСЛЕ
  print_nvs_stats("after config load") - иначе харнессы smoke_profile_store.py/
  smoke_relay_polarity_boot_window.py (компилируют СРЕЗ setup() до этого якоря)
  подхватят чекпоинт-код в свой срез.

Поведение (реальные тела из Samovar.ino через extract_function_body, исполняются
против самодельного in-memory fake NVS с семантикой реального ESP-IDF: NVS_READONLY
на несуществующий неймспейс - ошибка и неймспейс НЕ создаётся; NVS_READWRITE -
всегда успех и неймспейс создаётся, если его не было):
- capture на пустом NVS не создаёт неймспейс и не трогает pendingCheckpoint.
- write() -> capture() эхом возвращает записанное (mode<<8)|prog.
- tick(): пишет чекпоинт ТОЛЬКО на растущем фронте PowerOn (false->true) и ТОЛЬКО
  для BEER/SUVID; повторный tick() при удержанном PowerOn НЕ пишет повторно.
- tick(): на спадающем фронте стирает чекпоинт, ТОЛЬКО если его в этой же сессии
  писали мы сами (checkpointOwned) - "чужой" чекпоинт (например, оставшийся от
  предыдущей загрузки) переживает цикл включения в режиме, который его не пишет
  (Ректификация).
- report_pending(): шлёт SendMsg (WARNING_MSG) с текстом, называющим режим и
  программу, ТОЛЬКО когда pendingCheckpoint != 0; не включает PowerOn (нет
  автозапуска).
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []


def require(condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def body(source: str, signature: str) -> str:
    try:
        return extract_function_body(source, signature)
    except ValueError as exc:
        errors.append(str(exc))
        return ""


def statement(source: str, prefix: str) -> str:
    start = source.find(prefix)
    if start < 0:
        errors.append(f"statement not found: {prefix}")
        return ""
    end = source.find(";", start)
    if end < 0:
        errors.append(f"statement not terminated: {prefix}")
        return ""
    return source[start : end + 1]


raw_samovar = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
samovar = strip_cpp_comments(raw_samovar)

FUNCTION_SIGNATURES = {
    "write": "static void session_checkpoint_write(uint8_t mode, uint8_t prog) {",
    "clear": "static void session_checkpoint_clear() {",
    "capture": "static void session_checkpoint_capture_pending() {",
    "report": "static void session_checkpoint_report_pending() {",
    "tick": "static void session_checkpoint_tick() {",
}
bodies = {name: body(samovar, sig) for name, sig in FUNCTION_SIGNATURES.items()}

# --- Static pins ------------------------------------------------------------------------
require("NVS_READONLY" in bodies["capture"], "session_checkpoint_capture_pending must probe via NVS_READONLY")
require("NVS_READWRITE" not in bodies["capture"], "session_checkpoint_capture_pending must NOT use NVS_READWRITE (would create the namespace)")
require("NVS_READWRITE" in bodies["write"], "session_checkpoint_write must open via NVS_READWRITE")
require("NVS_READWRITE" in bodies["clear"], "session_checkpoint_clear must open via NVS_READWRITE")
require("checkpointOwned" in bodies["tick"], "session_checkpoint_tick must gate clear() with checkpointOwned")
require("prevPowerOn" in bodies["tick"], "session_checkpoint_tick must track prevPowerOn for edge detection")
require(
    "SAMOVAR_BEER_MODE" in bodies["tick"] and "SAMOVAR_SUVID_MODE" in bodies["tick"],
    "session_checkpoint_tick must gate the write to BEER/SUVID modes",
)
for name, text in bodies.items():
    if "set_power(true)" in text:
        errors.append(f"session_checkpoint_{name} calls set_power(true) - no auto-start is allowed")

# --- Positional pin: capture call after the print_nvs_stats anchor ----------------------
setup_body = body(samovar, "void setup() {")
if setup_body:
    anchor = 'print_nvs_stats("after config load");'
    anchor_pos = setup_body.find(anchor)
    capture_call_pos = setup_body.find("session_checkpoint_capture_pending();")
    require(anchor_pos >= 0, "print_nvs_stats(\"after config load\") anchor not found in setup()")
    require(capture_call_pos >= 0, "session_checkpoint_capture_pending() call not found in setup()")
    require(
        anchor_pos >= 0 and capture_call_pos > anchor_pos,
        "session_checkpoint_capture_pending() must be called strictly AFTER "
        'print_nvs_stats("after config load") (harness-slice contract for '
        "smoke_profile_store.py / smoke_relay_polarity_boot_window.py)",
    )

if errors:
    print("Session checkpoint static checks failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

# --- Behavioral harness -----------------------------------------------------------------
namespace_stmt = statement(samovar, "static const char* const SESSION_CHECKPOINT_NAMESPACE")
key_stmt = statement(samovar, "static const char* const SESSION_CHECKPOINT_KEY")
pending_stmt = statement(samovar, "static uint16_t pendingCheckpoint")

samovar_header = (ROOT / "Samovar.h").read_text(encoding="utf-8")


def definition(source: str, token: str) -> str:
    start = source.find(token)
    if start < 0:
        raise ValueError(f"definition not found: {token}")
    end = source.find("};", start)
    return source[start : end + 2]


mode_enum = definition(samovar_header, "enum SAMOVAR_MODE")
msg_enum = definition(samovar_header, "enum MESSAGE_TYPE")

HARNESS = r'''
#include <cstdint>
#include <iostream>
#include <map>
#include <set>
#include <string>

typedef int esp_err_t;
typedef int nvs_handle_t;
typedef int nvs_open_mode_t;
static const esp_err_t ESP_OK = 0;
static const esp_err_t ESP_ERR_NVS_NOT_FOUND = 1;
static const nvs_open_mode_t NVS_READONLY = 0;
static const nvs_open_mode_t NVS_READWRITE = 1;

@MODE_ENUM@
@MSG_ENUM@

class String : public std::string {
 public:
  using std::string::operator=;
  String() {}
  String(const char* value) : std::string(value ? value : "") {}
  String(const std::string& value) : std::string(value) {}
  explicit String(int value) : std::string(std::to_string(value)) {}
};
static String operator+(const String& left, const char* right) {
  return String(static_cast<const std::string&>(left) + (right ? right : ""));
}
static String operator+(const String& left, const String& right) {
  return String(static_cast<const std::string&>(left) + static_cast<const std::string&>(right));
}
#define F(literal) (literal)

static void WriteConsoleLog(const String&) {}

static int sendMsgCalls = 0;
static MESSAGE_TYPE lastSendMsgType = NONE_MSG;
static std::string lastSendMsgText;
static void SendMsg(const String& m, MESSAGE_TYPE type) {
  sendMsgCalls++;
  lastSendMsgType = type;
  lastSendMsgText = m;
}

// [P8 fix#5] write()/clear() теперь логируют неудачные esp_err_t через Serial,
// той же конвенцией, что NVS_Manager.ino. Копим текст - тест обязан доказать,
// что отклонение действительно логируется, а не молча глотается.
struct FakeSerial {
  std::string log;
  void print(const char* value) { log += value ? value : ""; }
  void println(int value) { log += std::to_string(value); log += "\n"; }
};
static FakeSerial Serial;

static bool PowerOn = false;
static SAMOVAR_MODE Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
static uint8_t ProgramNum = 0;

// --- fake NVS: моделирует реальную семантику ESP-IDF -----------------------------------
// NVS_READONLY на несуществующий неймспейс - ошибка, неймспейс НЕ создаётся.
// NVS_READWRITE - всегда успех, неймспейс создаётся, если его не было.
struct FakeNvs {
  std::set<std::string> existingNamespaces;
  std::map<std::string, std::map<std::string, uint16_t>> values;
  int writeCalls = 0;
  int eraseCalls = 0;
};
static FakeNvs fakeNvs;
static std::map<int, std::string> handleNamespace;
static int nextHandle = 1;
// [P8 fix#5] Форсирует отказ nvs_open() независимо от режима - проверить, что
// write()/clear() логируют esp_err_t через Serial, а не глотают его молча.
static bool forceNvsOpenFailure = false;
static const esp_err_t ESP_ERR_NVS_FORCED_FAILURE = 7;

static esp_err_t nvs_open(const char* namespaceName, nvs_open_mode_t mode, nvs_handle_t* handle) {
  if (forceNvsOpenFailure) return ESP_ERR_NVS_FORCED_FAILURE;
  const std::string ns(namespaceName);
  if (mode == NVS_READONLY) {
    if (fakeNvs.existingNamespaces.find(ns) == fakeNvs.existingNamespaces.end()) {
      return ESP_ERR_NVS_NOT_FOUND;
    }
  } else {
    fakeNvs.existingNamespaces.insert(ns);
  }
  const int id = nextHandle++;
  handleNamespace[id] = ns;
  *handle = id;
  return ESP_OK;
}

static void nvs_close(nvs_handle_t handle) { handleNamespace.erase(handle); }

static esp_err_t nvs_get_u16(nvs_handle_t handle, const char* key, uint16_t* value) {
  const std::string& ns = handleNamespace.at(handle);
  auto nsIt = fakeNvs.values.find(ns);
  if (nsIt == fakeNvs.values.end()) return ESP_ERR_NVS_NOT_FOUND;
  auto keyIt = nsIt->second.find(key);
  if (keyIt == nsIt->second.end()) return ESP_ERR_NVS_NOT_FOUND;
  *value = keyIt->second;
  return ESP_OK;
}

static esp_err_t nvs_set_u16(nvs_handle_t handle, const char* key, uint16_t value) {
  fakeNvs.writeCalls++;
  const std::string& ns = handleNamespace.at(handle);
  fakeNvs.values[ns][key] = value;
  return ESP_OK;
}

static esp_err_t nvs_erase_key(nvs_handle_t handle, const char* key) {
  fakeNvs.eraseCalls++;
  const std::string& ns = handleNamespace.at(handle);
  auto nsIt = fakeNvs.values.find(ns);
  if (nsIt != fakeNvs.values.end()) nsIt->second.erase(key);
  return ESP_OK;
}

static esp_err_t nvs_commit(nvs_handle_t) { return ESP_OK; }

@NAMESPACE_STMT@
@KEY_STMT@
@PENDING_STMT@

static void session_checkpoint_write(uint8_t mode, uint8_t prog) {
@WRITE_BODY@
}

static void session_checkpoint_clear() {
@CLEAR_BODY@
}

static void session_checkpoint_capture_pending() {
@CAPTURE_BODY@
}

static void session_checkpoint_report_pending() {
@REPORT_BODY@
}

static void session_checkpoint_tick() {
@TICK_BODY@
}

static int failures = 0;
static void check(bool cond, const char* msg) {
  if (!cond) {
    std::cerr << "FAIL: " << msg << "\n";
    failures++;
  }
}

int main() {
  // 1) Пустой NVS: проба на чтение не должна создавать неймспейс и не должна
  //    менять pendingCheckpoint.
  pendingCheckpoint = 0;
  session_checkpoint_capture_pending();
  check(pendingCheckpoint == 0, "capture on empty NVS changed pendingCheckpoint");
  check(fakeNvs.existingNamespaces.count("sam_sess") == 0,
        "capture (NVS_READONLY probe) must not create the sam_sess namespace");

  // 2) write() -> capture() эхом возвращает записанное значение.
  session_checkpoint_write((uint8_t)SAMOVAR_BEER_MODE, 7);
  check(fakeNvs.existingNamespaces.count("sam_sess") == 1, "write() did not create sam_sess namespace");
  const uint16_t expected1 = (uint16_t(SAMOVAR_BEER_MODE) << 8) | 7;
  check(fakeNvs.values["sam_sess"]["chk"] == expected1, "write() stored an unexpected payload");
  pendingCheckpoint = 0;
  session_checkpoint_capture_pending();
  check(pendingCheckpoint == expected1, "capture() did not read back the written checkpoint");

  // 3) tick(): растущий фронт PowerOn в BEER пишет чекпоинт; повторный tick() при
  //    удержанном PowerOn НЕ пишет повторно (edge-triggered, не level-triggered).
  Samovar_Mode = SAMOVAR_BEER_MODE;
  ProgramNum = 3;
  PowerOn = false;
  session_checkpoint_tick();  // устанавливает prevPowerOn=false, ничего не пишет
  const int writesBeforeRise = fakeNvs.writeCalls;
  PowerOn = true;  // растущий фронт
  session_checkpoint_tick();
  check(fakeNvs.writeCalls == writesBeforeRise + 1, "tick() did not write on BEER rising edge");
  const uint16_t expected2 = (uint16_t(SAMOVAR_BEER_MODE) << 8) | 3;
  check(fakeNvs.values["sam_sess"]["chk"] == expected2, "tick() wrote an unexpected payload on rising edge");
  const int writesAfterRise = fakeNvs.writeCalls;
  session_checkpoint_tick();  // PowerOn всё ещё true - не растущий фронт
  check(fakeNvs.writeCalls == writesAfterRise, "tick() re-wrote checkpoint on a non-rising edge");

  // 3b) [P8 fix#1] Строка программы сменилась под удержанным PowerOn (одна
  //     многочасовая варка = одно включение, фронта нет) - чекпоинт обязан
  //     перезаписаться новым payload; если ProgramNum не менялся - повторной
  //     записи быть не должно.
  ProgramNum = 4;  // строка сменилась в рамках той же сессии (PowerOn всё ещё true)
  const int writesBeforeLineChange = fakeNvs.writeCalls;
  session_checkpoint_tick();
  check(fakeNvs.writeCalls == writesBeforeLineChange + 1,
        "tick() did not rewrite the checkpoint when ProgramNum changed under held PowerOn");
  const uint16_t expected2b = (uint16_t(SAMOVAR_BEER_MODE) << 8) | 4;
  check(fakeNvs.values["sam_sess"]["chk"] == expected2b, "tick() wrote a wrong payload after a ProgramNum change");
  const int writesAfterLineChange = fakeNvs.writeCalls;
  session_checkpoint_tick();  // ProgramNum не менялся - повторной записи быть не должно
  check(fakeNvs.writeCalls == writesAfterLineChange,
        "tick() rewrote the checkpoint without a ProgramNum change");

  // 4) tick(): спадающий фронт стирает чекпоинт, который писали мы сами (owned).
  PowerOn = false;  // спадающий фронт
  session_checkpoint_tick();
  check(fakeNvs.values["sam_sess"].count("chk") == 0, "tick() did not clear an owned checkpoint on falling edge");

  // 5) "Чужой" чекпоинт (записан не текущим циклом tick()) не должен стираться
  //    циклом включения в режиме, который его не пишет (Ректификация).
  session_checkpoint_write((uint8_t)SAMOVAR_SUVID_MODE, 9);
  const uint16_t foreign = (uint16_t(SAMOVAR_SUVID_MODE) << 8) | 9;
  check(fakeNvs.values["sam_sess"]["chk"] == foreign, "seeding a foreign checkpoint failed");
  Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
  const int writesBeforeRect = fakeNvs.writeCalls;
  PowerOn = true;  // растущий фронт, но режим не BEER/SUVID
  session_checkpoint_tick();
  check(fakeNvs.writeCalls == writesBeforeRect, "tick() wrote a checkpoint for a non-BEER/SUVID mode");
  check(fakeNvs.values["sam_sess"]["chk"] == foreign, "tick() touched a foreign checkpoint on a non-owning rising edge");
  const int erasesBeforeFall = fakeNvs.eraseCalls;
  PowerOn = false;  // спадающий фронт, checkpointOwned=false для этого режима
  session_checkpoint_tick();
  check(fakeNvs.eraseCalls == erasesBeforeFall, "tick() erased a foreign checkpoint it did not own");
  check(fakeNvs.values["sam_sess"]["chk"] == foreign, "foreign checkpoint was lost after a non-owning falling edge");

  // 6) SUVID тоже владеет чекпоинтом (не только BEER).
  Samovar_Mode = SAMOVAR_SUVID_MODE;
  ProgramNum = 2;
  PowerOn = true;
  session_checkpoint_tick();
  const uint16_t expected3 = (uint16_t(SAMOVAR_SUVID_MODE) << 8) | 2;
  check(fakeNvs.values["sam_sess"]["chk"] == expected3, "tick() did not write on SUVID rising edge");
  PowerOn = false;
  session_checkpoint_tick();
  check(fakeNvs.values["sam_sess"].count("chk") == 0, "tick() did not clear an owned SUVID checkpoint");

  // 7) report_pending(): сообщение только когда есть что сообщать; без автозапуска.
  pendingCheckpoint = 0;
  sendMsgCalls = 0;
  session_checkpoint_report_pending();
  check(sendMsgCalls == 0, "report_pending() sent a message despite pendingCheckpoint == 0");

  pendingCheckpoint = (uint16_t(SAMOVAR_BEER_MODE) << 8) | 5;
  sendMsgCalls = 0;
  PowerOn = false;
  session_checkpoint_report_pending();
  check(sendMsgCalls == 1, "report_pending() did not send a message for a pending checkpoint");
  check(lastSendMsgType == WARNING_MSG, "report_pending() must use WARNING_MSG severity");
  check(lastSendMsgText.find("незавершённая сессия") != std::string::npos,
        "report_pending() message does not mention the unfinished session");
  check(PowerOn == false, "report_pending() must never turn PowerOn on (no auto-start)");

  // 8) [P8 fix#2] После отчёта чекпоинт обязан быть стёрт из NVS - иначе одно и
  //    то же предупреждение повторялось бы на каждой перезагрузке. Пишем
  //    настоящий чекпоинт через write() (создаёт неймспейс по-настоящему,
  //    а не через прямое присваивание pendingCheckpoint), затем report'им.
  session_checkpoint_write((uint8_t)SAMOVAR_BEER_MODE, 6);
  pendingCheckpoint = 0;
  session_checkpoint_capture_pending();
  check(pendingCheckpoint != 0, "setup for fix#2 check failed: capture() did not see the seeded checkpoint");
  sendMsgCalls = 0;
  session_checkpoint_report_pending();
  check(sendMsgCalls == 1, "report_pending() did not send a message for the fix#2 scenario");
  check(fakeNvs.values["sam_sess"].count("chk") == 0,
        "report_pending() must erase the checkpoint from NVS after reporting it");

  // Второй boot: свежий процесс читает NVS заново (pendingCheckpoint = 0, как
  // при старте прошивки) - раз чекпоинт стёрт, ничего репортить не должен.
  pendingCheckpoint = 0;
  session_checkpoint_capture_pending();
  check(pendingCheckpoint == 0, "second boot must not see a checkpoint that report_pending() already cleared");
  sendMsgCalls = 0;
  session_checkpoint_report_pending();
  check(sendMsgCalls == 0, "second boot must not repeat the already-reported checkpoint warning");

  // 9) [P8 fix#5] write()/clear() обязаны логировать отказ nvs_open() через
  //    Serial (конвенция NVS_Manager.ino), а не молча его глотать.
  forceNvsOpenFailure = true;
  Serial.log.clear();
  session_checkpoint_write((uint8_t)SAMOVAR_BEER_MODE, 1);
  check(Serial.log.find("open failed") != std::string::npos,
        "session_checkpoint_write did not log an NVS open failure");
  Serial.log.clear();
  session_checkpoint_clear();
  check(Serial.log.find("open failed") != std::string::npos,
        "session_checkpoint_clear did not log an NVS open failure");
  forceNvsOpenFailure = false;

  if (failures != 0) return 1;
  std::cout << "Session checkpoint behavioral checks passed\n";
  return 0;
}
'''


def build_harness() -> str:
    harness = HARNESS
    harness = harness.replace("@MODE_ENUM@", mode_enum)
    harness = harness.replace("@MSG_ENUM@", msg_enum)
    harness = harness.replace("@NAMESPACE_STMT@", namespace_stmt)
    harness = harness.replace("@KEY_STMT@", key_stmt)
    harness = harness.replace("@PENDING_STMT@", pending_stmt)
    harness = harness.replace("@WRITE_BODY@", bodies["write"])
    harness = harness.replace("@CLEAR_BODY@", bodies["clear"])
    harness = harness.replace("@CAPTURE_BODY@", bodies["capture"])
    harness = harness.replace("@REPORT_BODY@", bodies["report"])
    harness = harness.replace("@TICK_BODY@", bodies["tick"])
    return harness


def run_harness(harness: str) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-session-checkpoint-") as temp_dir:
        temp = Path(temp_dir)
        source_file = temp / "session_checkpoint_test.cpp"
        binary = temp / "session_checkpoint_test"
        source_file.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source_file), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            sys.stderr.write(compile_result.stdout)
            sys.stderr.write(compile_result.stderr)
            return compile_result.returncode
        run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        sys.stdout.write(run_result.stdout)
        sys.stderr.write(run_result.stderr)
        return run_result.returncode


def main() -> int:
    try:
        harness = build_harness()
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    return run_harness(harness)


if __name__ == "__main__":
    raise SystemExit(main())
