#!/usr/bin/env python3
"""Проверяет реальный сборщик crash.txt на двух снимках и отказах чтения."""

import subprocess
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "crash_handler.ino"
HEADER = ROOT / "crash_handler.h"

PREFIX = r'''
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <map>
#include <string>
#include <type_traits>
#include <vector>

class String : public std::string {
public:
  using std::string::string;
  String(const std::string &s) : std::string(s) {}
  template<class T, typename std::enable_if<std::is_integral<T>::value, int>::type = 0>
  String(T n) : std::string(std::to_string(n)) {}
};
using esp_err_t = int;
enum esp_reset_reason_t {
  ESP_RST_UNKNOWN, ESP_RST_POWERON, ESP_RST_EXT, ESP_RST_SW, ESP_RST_PANIC,
  ESP_RST_INT_WDT, ESP_RST_TASK_WDT, ESP_RST_WDT, ESP_RST_DEEPSLEEP, ESP_RST_BROWNOUT, ESP_RST_SDIO
};
static esp_reset_reason_t reset_reason=ESP_RST_PANIC;
static esp_reset_reason_t esp_reset_reason() { return reset_reason; }
enum MESSAGE_TYPE { ALARM_MSG, WARNING_MSG, NOTIFY_MSG };
static std::vector<std::pair<String, MESSAGE_TYPE>> notices;
static void SendMsg(const String &text, MESSAGE_TYPE type) { notices.emplace_back(text,type); }
static void check_and_load_crash_log() {}
constexpr int ESP_OK=0, ESP_ERR_NOT_FOUND=1, ESP_ERR_INVALID_CRC=2, ESP_FAIL=3;
struct esp_core_dump_summary_t {
  char exc_task[16]; uint32_t exc_pc;
  struct { uint32_t bt[16]; uint32_t depth; bool corrupted; } exc_bt_info;
  uint8_t app_elf_sha256[65];
  struct { uint32_t exc_cause; uint32_t exc_vaddr; } ex_info;
};
static esp_core_dump_summary_t stored;
static bool present=true, checksum_ok=true, readable=true;
static int checks=0, reads=0;
static esp_err_t esp_core_dump_image_check() {
  ++checks;
  return !present ? ESP_ERR_NOT_FOUND : checksum_ok ? ESP_OK : ESP_ERR_INVALID_CRC;
}
static esp_err_t esp_core_dump_get_summary(esp_core_dump_summary_t *out) {
  ++reads;
  if (!present || !readable) return ESP_FAIL;
  *out=stored;
  return ESP_OK;
}
static const char *esp_err_to_name(esp_err_t e) {
  switch(e) { case ESP_ERR_NOT_FOUND:return "ESP_ERR_NOT_FOUND";
    case ESP_ERR_INVALID_CRC:return "ESP_ERR_INVALID_CRC"; default:return "ESP_FAIL"; }
}
static bool fs_available=true;
enum { FILE_READ, FILE_WRITE };
static std::map<std::string,std::string> files;
struct File {
  std::string path; size_t pos=0; bool valid=false;
  explicit operator bool() const { return valid; }
  bool available() const { return pos < files[path].size(); }
  char read() { return files[path][pos++]; }
  void write(char c) { files[path] += c; }
  void print(const String &s) { files[path] += s; }
  void close() {}
};
struct FakeFS {
  bool mounted=true;
  bool begin(bool) { return mounted; }
  bool exists(const char *p) { return files.count(p); }
  void remove(const char *p) { files.erase(p); }
  File open(const char *p,int mode) {
    if(mode==FILE_WRITE) files[p].clear();
    return File{p,0,files.count(p)!=0};
  }
} SPIFFS;
struct FakeSerial {
  template<class T> void println(const T &) {}
  template<class T> void print(const T &) {}
} Serial;
struct FakeESP {
  unsigned getFreeHeap() { return 111; }
  unsigned getMaxAllocHeap() { return 222; }
  unsigned getMinFreeHeap() { return 100; }
  const char *getChipModel() { return "ESP32"; }
  unsigned getChipRevision() { return 1; }
  unsigned getCpuFreqMHz() { return 240; }
} ESP;
using UBaseType_t = unsigned;
using TaskHandle_t = void *;
static unsigned millis() { return 17; }
static String get_reset_reason_string() { return "panic (4)"; }
static unsigned uxTaskGetNumberOfTasks() { return 2; }
static TaskHandle_t xTaskGetCurrentTaskHandle() { return (void*)1; }
static unsigned uxTaskGetStackHighWaterMark(TaskHandle_t) { return 400; }
static const char *pcTaskGetName(TaskHandle_t) { return "loopTask-after-boot"; }
'''

CASES = r'''
static void check(bool ok,const char *why) {
  if(!ok) { std::cerr << "FAIL: " << why << '\n'; std::exit(1); }
}
static bool has(const std::string &s,const std::string &part) { return s.find(part)!=s.npos; }
static String report() {
  checks=reads=0;
  save_stacktrace_to_file("startup");
  check(files.count("/crash.txt"),"report not written");
  check(checks==1,"core dump must be checked once per report");
  return files["/crash.txt"];
}
int main() {
  (void)&SendMsg;
  for(int i=0;i<2;++i) {
    stored={};
    std::strcpy(stored.exc_task,i ? "do_lua_script" : "async_tcp");
    stored.exc_pc=i ? 0x400d2222 : 0x400d1111;
    stored.ex_info.exc_cause=i ? 28 : 6;
    stored.ex_info.exc_vaddr=i ? 0x3ffb1234 : 0;
    std::memset(stored.app_elf_sha256,i ? 'b' : 'a',64);
    stored.exc_bt_info.depth=i ? 3 : 2;
    stored.exc_bt_info.bt[0]=stored.exc_pc;
    stored.exc_bt_info.bt[1]=i ? 0x400d3333 : 0x400d4444;
    stored.exc_bt_info.bt[2]=0x400d5555;
    auto s=report();
    check(reads==1,"summary was not read");
    check(has(s,i ? "Crashed Task: do_lua_script" : "Crashed Task: async_tcp"),"crashed task not taken from snapshot");
    check(has(s,i ? "Exception PC: 0x400d2222" : "Exception PC: 0x400d1111"),"exception PC lost");
    check(has(s,i ? "Exception Cause: 28" : "Exception Cause: 6"),"exception cause lost");
    check(has(s,i ? "Exception Address: 0x3ffb1234" : "Exception Address: 0x00000000"),"exception address lost");
    check(has(s,"Crashed Firmware ELF SHA256: "+std::string(64,i ? 'b' : 'a')+"\n"),"snapshot firmware identifier lost");
    check(has(s,i ? "Backtrace: 0x400d2222 0x400d3333 0x400d5555\n" : "Backtrace: 0x400d1111 0x400d4444\n"),"backtrace frames or order lost");
    check(has(s,"Saved snapshot may predate this reset."),"saved dump attributed to latest reset");
    auto current=s.find("=== CURRENT BOOT DIAGNOSTICS (NOT CRASH-TIME STATE) ===");
    check(current!=s.npos && current>s.find("Backtrace:") && current<s.find("Free Heap:"),"boot measurements mislabeled as crash state");
    check(has(s,"Boot Uptime: 17 ms"),"boot time mislabeled");
  }
  check(has(files["/crash_old.txt"],"Crashed Task: async_tcp"),"previous crash report not preserved");
  present=false;
  auto s=report();
  check(reads==0 && has(s,"Core dump unavailable: ESP_ERR_NOT_FOUND") && !has(s,"Backtrace:"),"missing snapshot must be explicit, without fabricated frames");
  present=true; checksum_ok=false;
  s=report();
  check(reads==0 && has(s,"Core dump unavailable: ESP_ERR_INVALID_CRC") && !has(s,"Backtrace:"),"corrupted snapshot must not be parsed");
  checksum_ok=true; readable=false;
  s=report();
  check(reads==1 && has(s,"Core dump read failed: ESP_FAIL") && !has(s,"Backtrace:"),"summary failure must be explicit");
  readable=true; stored.exc_bt_info.corrupted=true;
  s=report();
  check(has(s," [CORRUPTED]"),"corrupted backtrace marker lost");
  stored.exc_bt_info={};
  s=report();
  check(has(s,"Backtrace: unavailable (no frames)"),"empty backtrace must be explicit");
  stored.exc_bt_info.depth=16;
  for(unsigned i=0;i<16;++i) stored.exc_bt_info.bt[i]=0x400d1000+i;
  s=report();
  check(has(s,"0x400d100f [frame limit reached]"),"last frame or truncation notice lost");
  stored.exc_bt_info.depth=17;
  check(report()==s,"backtrace read beyond SDK array");
  // Старый снимок остаётся: обычный запуск не должен объявляться аварией из-за него.
  for (auto reason : {ESP_RST_POWERON, ESP_RST_EXT, ESP_RST_SW, ESP_RST_DEEPSLEEP, ESP_RST_BROWNOUT, ESP_RST_UNKNOWN}) {
    reset_reason=reason; notices.clear(); checks=0;
    init_crash_handler();
    check(notices.empty() && checks==0,"normal boot emitted crash notification");
  }
  for (auto reason : {ESP_RST_PANIC, ESP_RST_INT_WDT, ESP_RST_TASK_WDT, ESP_RST_WDT, ESP_RST_SDIO}) {
    reset_reason=reason;
    for (bool available : {true,false}) {
      SPIFFS.mounted=available; present=available; notices.clear();
      init_crash_handler();
      check(notices.size()==1,"crash boot must emit exactly one notification, even without crash file");
      check(notices[0].first=="Аварийная перезагрузка","crash notification text changed");
      check(notices[0].second==ALARM_MSG,"crash notification must have alarm severity");
    }
  }
}
'''


def run(source: str) -> tuple[int, str]:
    header = HEADER.read_text(encoding="utf-8")
    classifier_signature = "inline bool is_crash_reset_reason(esp_reset_reason_t reason)"
    classifier = classifier_signature + " {" + extract_function_body(header, classifier_signature) + "}"
    methods = (
        "void append_core_dump_to_report(String& crash_log)",
        "void save_stacktrace_to_file(const char* info)",
        "void init_crash_handler()",
    )
    code = PREFIX + classifier + "\n" + "\n".join(
        sig + " {" + extract_function_body(source, sig) + "}" for sig in methods
    ) + CASES
    with tempfile.TemporaryDirectory(prefix="samovar-core-dump-") as tmp:
        cpp, exe = Path(tmp) / "test.cpp", Path(tmp) / "test"
        cpp.write_text(code, encoding="utf-8")
        build = subprocess.run(["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(exe)], capture_output=True, text=True)
        if build.returncode:
            raise RuntimeError(build.stderr)
        result = subprocess.run([str(exe)], capture_output=True, text=True)
        return result.returncode, result.stdout + result.stderr


def main() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    code, output = run(source)
    assert code == 0, output
    mutations = (
        ("checksum check ignored", "if (err != ESP_OK)", "if (false)"),
        ("summary failure ignored", "err = esp_core_dump_get_summary(&summary);", "err = esp_core_dump_get_summary(&summary); err = ESP_OK;"),
        ("wrong PC", "(unsigned long)summary.exc_pc", "(unsigned long)0"),
        ("wrong crashed task", "summary.exc_task);", '"boot-task");'),
        ("wrong exception cause", "(unsigned long)summary.ex_info.exc_cause", "(unsigned long)0"),
        ("wrong exception address", "(unsigned long)summary.ex_info.exc_vaddr", "(unsigned long)0"),
        ("frames reordered", "summary.exc_bt_info.bt[i]", "summary.exc_bt_info.bt[0]"),
        ("missing firmware identifier", 'crash_log += line;\n  crash_log += "Backtrace:";', 'crash_log += "Backtrace:";'),
        ("missing corrupted marker", "if (summary.exc_bt_info.corrupted)", "if (false)"),
        ("missing empty marker", "if (summary.exc_bt_info.depth == 0)", "if (false)"),
        ("missing frame-limit marker", "summary.exc_bt_info.depth >= max_frames", "false"),
        ("wrong snapshot attribution", "Saved snapshot may predate this reset.", "Snapshot of this reset."),
        ("wrong boot-state label", "CURRENT BOOT DIAGNOSTICS (NOT CRASH-TIME STATE)", "CRASH-TIME STATE"),
        ("missing report integration", "append_core_dump_to_report(crash_log);", "(void)&append_core_dump_to_report;"),
        ("missing crash notification", 'SendMsg("Аварийная перезагрузка", ALARM_MSG);', '(void)&SendMsg;'),
        ("wrong crash notification text", 'SendMsg("Аварийная перезагрузка", ALARM_MSG);', 'SendMsg("Перезагрузка", ALARM_MSG);'),
        ("wrong crash notification severity", 'SendMsg("Аварийная перезагрузка", ALARM_MSG);', 'SendMsg("Аварийная перезагрузка", NOTIFY_MSG);'),
        ("normal boot misclassified", "if (was_crash)", "if (was_crash || true)"),
    )
    for name, old, new in mutations:
        assert old in source, f"mutation not applied: {name}"
        code, output = run(source.replace(old, new, 1))
        assert code != 0 and "FAIL:" in output, f"mutation survived without semantic assertion: {name}: {output}"
        print(f"  {name}: {output.strip()}")
    print("crash core dump checks passed")


if __name__ == "__main__":
    main()
