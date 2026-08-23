#!/usr/bin/env python3
"""[П30 + фикс] Поведенческая проверка авто-остановки падающего периодического
lua-скрипта, РАЗДЕЛЬНО для script1 (общий script.lua, правится пользователем
через веб-редактор) и script2 (режимный скрипт - rectificat.lua/dist.lua/...).

Раньше был ОДИН общий счётчик подряд идущих неуспехов на оба скрипта - ошибка
в пустяковом пользовательском script.lua через 5 секунд глушила ВЕСЬ
периодический цикл (loop_lua_fl = false) ВМЕСТЕ с исправно работающим
режимным скриптом, который в этот момент может управлять нагревом и насосом.
В журнал при этом писалось "режимный скрипт остановлен...", хотя сломан был
не он - вводило в заблуждение при диагностике.

Берёт РЕАЛЬНОЕ тело do_lua_script()/load_lua_script()/lua_chunk_ref_valid() из
lua.h (через extract_function_body - без переписывания логики) и исполняет его
в g++-харнессе. do_lua_script() - это FreeRTOS-таск с while(1); чтобы выйти из
него без хаков внутри тела функции, харнесс считает завершённые периодические
прогоны в СТАБЕ finish_beer_lua_periodic_result() (реальный do_lua_script
зовёт её РОВНО один раз в конце каждого периодического прогона) и завершённые
one-shot job'ы в СТАБЕ finish_lua_job(), и кидает C++-исключение, когда нужное
число прогонов набрано - деструкторы String-локалей (sr/local_s1/local_s2) при
этом отрабатывают штатно.

Проверяемое поведение:
1. 5 подряд неуспешных прогонов ТОЛЬКО script1 -> loop_lua_fl остаётся true
   (режимный скрипт не глушится), script1 больше не запускается, а script2
   как ни в чём не бывало продолжает выполняться каждый цикл; итоговое
   сообщение об остановке ровно одно и называет script.lua, а не режимный.
2. 5 подряд неуспешных прогонов ТОЛЬКО script2 -> loop_lua_fl становится
   false, как и раньше, итоговое сообщение называет именно режимный скрипт.
3. Успешный прогон между сбоями сбрасывает СВОЙ счётчик - независимо для
   каждого скрипта (4 сбоя + 1 успех + 4 сбоя = 8 подряд, но НЕ 5 подряд
   после сброса, цикл не останавливается).
4. load_lua_script() безусловно сбрасывает ОБА счётчика И снимает отключение
   script1 - иначе пользователь не смог бы починить script1 через веб-редактор
   без перезагрузки устройства.
5. Неуспешный ONE-SHOT job (веб/кнопка, через lua_exec_locked) НЕ трогает ни
   один из периодических счётчиков и не может остановить периодический цикл.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

SIGNATURES = [
    "inline bool lua_chunk_ref_valid(int ref)",
    "void do_lua_script(void *parameter)",
    "void load_lua_script()",
]

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>
#include <string>
#include <vector>

using TickType_t = int;
constexpr TickType_t portMAX_DELAY = -1;
constexpr int portTICK_PERIOD_MS = 1;
constexpr int LUA_NOREF = -2;
constexpr int LUA_REFNIL = -1;
constexpr int LUA_GCCOLLECT = 2;

static TickType_t pdMS_TO_TICKS(int value) { return value; }

class String {
 public:
  String() = default;
  String(const char* value) : value_(value ? value : "") {}
  String(int value) : value_(std::to_string(value)) {}
  String(unsigned int value) : value_(std::to_string(value)) {}
  size_t length() const { return value_.length(); }
  const char* c_str() const { return value_.c_str(); }
  void reserve(size_t) {}
  void clear() { value_.clear(); }
  void trim() {
    size_t a = value_.find_first_not_of(" \t\r\n");
    size_t b = value_.find_last_not_of(" \t\r\n");
    value_ = (a == std::string::npos) ? std::string() : value_.substr(a, b - a + 1);
  }
  String operator+(const String& other) const { return String((value_ + other.value_).c_str()); }
  bool operator==(const char* other) const { return value_ == other; }
  bool operator==(const String& other) const { return value_ == other.value_; }
  bool operator!=(const String& other) const { return value_ != other.value_; }

  std::string value_;
};
static String operator+(const char* lhs, const String& rhs) { return String(lhs) + rhs; }

enum LuaJobType : uint8_t {
  LUA_JOB_NONE = 0,
  LUA_JOB_SCRIPT,
  LUA_JOB_INLINE
};

static const char* F(const char* text) { return text; }

// [Fix] счётчики/флаг/порог - объявлены в lua.h на уровне файла (не внутри
// какой-либо функции), поэтому extract_function_body их не захватывает вместе
// с телами функций; переобъявляем здесь так же, как это уже делается для
// loop_lua_fl/SetScriptOff в smoke_lua_beer_job_lifecycle.py.
#ifndef LUA_PERIODIC_FAILURE_STOP_THRESHOLD
#define LUA_PERIODIC_FAILURE_STOP_THRESHOLD 5
#endif
static uint8_t lua_periodic_failure_count_script1 = 0;
static uint8_t lua_periodic_failure_count_script2 = 0;
static bool lua_script1_disabled = false;

// --- зависимости load_lua_script() (компиляция/чтение скриптов с SPIFFS) ---
static bool lua_boot_init_ready = true;
static bool lua_coroutine_watchdog_ready = true;
static bool lua_runtime_ready = false;
static String lua_script_list_cache;
static std::string getScriptStub, getScriptListStub, compileErrorStub;
static String get_lua_script(String) { return String(getScriptStub.c_str()); }
static String get_lua_script_list() { return String(getScriptListStub.c_str()); }
static String lua_compile_chunk_locked(const String&, const char*, int&) {
  return String(compileErrorStub.c_str());
}
struct FakeLuaObj { void clear() {} };
static FakeLuaObj luaObjectFake;
static FakeLuaObj* luaObj = &luaObjectFake;

// --- журнал (для проверки количества и текста сообщений) -----------------
static std::vector<std::string> consoleLog;
static void WriteConsoleLog(const String& message) { consoleLog.push_back(message.value_); }

// --- прочие примитивы окружения -------------------------------------------
static bool ota_running = false;
static bool show_lua_script = false;
static bool luaLastExecutionTimedOut = false;
static bool lua_state_lock(TickType_t) { return true; }
static void lua_state_unlock(bool) {}
struct FakeRuntimeLock { bool operator()(TickType_t) const { return true; } };
static bool runtime_state_lock(TickType_t) { return true; }
static void runtime_state_unlock(bool) {}
static void reset_lua_message_cursor() {}
struct FakeLuaWrapper { void* GetState() { return nullptr; } };
static FakeLuaWrapper lua;
static void lua_gc(void*, int, int) {}

static unsigned long millisValue = 0;
static unsigned long millis() { millisValue += 2000; return millisValue; }

// --- планировщик периодического прогона (упрощённые стабы - НЕ предмет
// этого теста, реальные версии проверены в smoke_lua_beer_job_lifecycle.py) --
static bool loop_lua_fl = false;
static bool SetScriptOff = false;
static bool lua_start_requested = false;
static bool lua_finished = true;
static bool request_lua_periodic_start() {
  if (!lua_finished || lua_start_requested) return false;
  lua_start_requested = true;
  return true;
}
static bool consume_lua_periodic_start_request(bool& accepted) {
  accepted = false;
  if (lua_start_requested && lua_finished) {
    lua_start_requested = false;
    lua_finished = false;
    accepted = true;
  }
  return true;
}
static bool lua_periodic_active(bool& active) {
  active = !lua_finished;
  return true;
}
static void finish_lua_periodic_run() { lua_finished = true; }

// --- скрипты и их компилированные ссылки -----------------------------------
// script1_ref/script2_ref намеренно РАЗНЫЕ значения - lua_exec_chunk_locked
// ниже различает по ref, какой из двух скриптов сейчас исполняется.
static String script1, script2;
static int script1_ref = 7;
static int script2_ref = 8;
static String lua_type_script = "beer.lua";

// --- очереди результатов lua_exec_chunk_locked - РАЗДЕЛЬНЫЕ по script1 и
// script2 (различаем вызовы по ref) - иначе общий FIFO навязывал бы порядок
// "script1 затем script2" каждой итерации и не дал бы задать им независимые,
// не совпадающие по длине последовательности успехов/неудач. *CallCount
// считает реальное число вызовов - им проверяем "script1 больше не
// запускается" и "script2 продолжает исполняться" напрямую, а не через
// побочный эффект исчерпания очереди.
static std::vector<std::string> chunkResultsScript1;
static size_t chunkCallIndexScript1 = 0;
static int script1CallCount = 0;
static std::vector<std::string> chunkResultsScript2;
static size_t chunkCallIndexScript2 = 0;
static int script2CallCount = 0;
static String lua_exec_chunk_locked(int ref, bool = false) {
  if (ref == script1_ref) {
    script1CallCount++;
    if (chunkCallIndexScript1 < chunkResultsScript1.size()) return String(chunkResultsScript1[chunkCallIndexScript1++].c_str());
    return String("");
  }
  script2CallCount++;
  if (chunkCallIndexScript2 < chunkResultsScript2.size()) return String(chunkResultsScript2[chunkCallIndexScript2++].c_str());
  return String("");
}

// --- one-shot job (веб/кнопка) ---------------------------------------------
static bool takeLuaJobReturn = false;
static std::string takeLuaJobScript = "print(1)";
static LuaJobType takeLuaJobType = LUA_JOB_INLINE;
static bool take_lua_job(String& script, LuaJobType& type) {
  if (!takeLuaJobReturn) return false;
  takeLuaJobReturn = false;
  script = String(takeLuaJobScript.c_str());
  type = takeLuaJobType;
  return true;
}
static std::string oneShotJobResult;
static String lua_exec_locked(String&, bool = false) { return String(oneShotJobResult.c_str()); }

// --- выход из while(1): считаем завершённые прогоны в реальных концевых
// функциях do_lua_script() и кидаем исключение, когда набрали нужное число --
struct StopIteration {};
struct SafetyCapHit {};
static int periodicIterationsCompleted = 0;
static int periodicIterationsTarget = 1000000;
static void finish_beer_lua_periodic_result(bool, bool) {
  periodicIterationsCompleted++;
  // Останавливаем прогон досрочно и в случае, если цикл уже выключен - иначе
  // харнесс завис бы в ветке "lua_active=false" (vTaskDelay(50)) навсегда,
  // так и не добравшись до periodicIterationsTarget (упавший до срока цикл
  // больше НЕ планирует новые прогоны - именно это и есть П30-поведение).
  if (periodicIterationsCompleted >= periodicIterationsTarget || !loop_lua_fl) throw StopIteration{};
}
static int oneShotJobsCompleted = 0;
static int oneShotJobsTarget = 1000000;
static void finish_lua_job() {
  oneShotJobsCompleted++;
  if (oneShotJobsCompleted >= oneShotJobsTarget) throw StopIteration{};
}
static int vTaskDelayCalls = 0;
static void vTaskDelay(int) {
  if (++vTaskDelayCalls > 2000) throw SafetyCapHit{};
}

@FUNCTIONS@

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

static int count_occurrences(const std::string& needle) {
  int n = 0;
  for (const auto& line : consoleLog) {
    if (line.find(needle) != std::string::npos) n++;
  }
  return n;
}

static void reset_fixture() {
  consoleLog.clear();
  ota_running = false;
  show_lua_script = false;
  luaLastExecutionTimedOut = false;
  millisValue = 0;
  loop_lua_fl = false;
  SetScriptOff = false;
  lua_start_requested = false;
  lua_finished = true;
  script1 = String("");
  script2 = String("");
  script1_ref = 7;
  script2_ref = 8;
  lua_type_script = String("beer.lua");
  chunkResultsScript1.clear();
  chunkCallIndexScript1 = 0;
  script1CallCount = 0;
  chunkResultsScript2.clear();
  chunkCallIndexScript2 = 0;
  script2CallCount = 0;
  takeLuaJobReturn = false;
  oneShotJobResult.clear();
  lua_periodic_failure_count_script1 = 0;
  lua_periodic_failure_count_script2 = 0;
  lua_script1_disabled = false;
  periodicIterationsCompleted = 0;
  periodicIterationsTarget = 1000000;
  oneShotJobsCompleted = 0;
  oneShotJobsTarget = 1000000;
  vTaskDelayCalls = 0;
}

static void run_do_lua_script_once() {
  try {
    do_lua_script(nullptr);
  } catch (const StopIteration&) {
  }
}

static void test_five_script1_failures_disable_script1_without_stopping_loop() {
  reset_fixture();
  loop_lua_fl = true;
  script1 = String("bad-script1");
  script2 = String("mode-script");
  chunkResultsScript1 = {"boom1", "boom2", "boom3", "boom4", "boom5"};
  // script2 всегда успешен (очередь пуста - стаб отдаёт "" по умолчанию).
  // 7 прогонов: 5, на которых script1 копит ошибки и отключается, и ещё 2 -
  // чтобы убедиться, что после отключения script1 больше не вызывается,
  // а script2 как ни в чём не бывало продолжает выполняться каждый цикл.
  periodicIterationsTarget = 7;
  run_do_lua_script_once();
  check(loop_lua_fl, "5 consecutive script1 failures must NOT stop the periodic loop - only script2 failures do that");
  check(lua_script1_disabled, "script1 must be disabled after 5 consecutive failures");
  check(script1CallCount == 5, "script1 must stop being invoked once disabled, even though 7 periodic runs happened");
  check(script2CallCount == 7, "the mode script (script2) must keep running every periodic cycle regardless of script1's failures");
  check(count_occurrences("ERR in script.lua: boom") == 5, "each of the 5 failed script1 runs must log its own ERR");
  check(count_occurrences("script.lua остановлен после") == 1,
        "exactly one final stop message naming script.lua must be logged");
  check(count_occurrences("режимный скрипт") == 0,
        "a script1-only failure must never be reported as a mode-script (режимный скрипт) failure");
}

static void test_five_script2_failures_stop_the_loop() {
  reset_fixture();
  loop_lua_fl = true;
  script2 = String("bad-mode-script");
  lua_type_script = String("beer.lua");
  chunkResultsScript2 = {"boom1", "boom2", "boom3", "boom4", "boom5"};
  periodicIterationsTarget = 5;
  run_do_lua_script_once();
  check(!loop_lua_fl, "5 consecutive script2 (mode script) failures must stop the periodic loop");
  check(!lua_script1_disabled, "script1 was empty and never ran - it must not be disabled by script2's failures");
  check(script1CallCount == 0, "script1 is empty and must never be invoked");
  check(count_occurrences("ERR in beer.lua: boom") == 5, "each of the 5 failed script2 runs must log its own ERR");
  check(count_occurrences("режимный скрипт (beer.lua) остановлен после") == 1,
        "exactly one final stop message naming the mode script must be logged");
}

static void test_success_between_failures_resets_script1_counter() {
  reset_fixture();
  loop_lua_fl = true;
  script1 = String("script1-body");
  // script2 пуст - изолируем поведение script1 от script2.
  chunkResultsScript1 = {"e1", "e2", "e3", "e4", "", "e5", "e6", "e7", "e8"};
  periodicIterationsTarget = 9;
  run_do_lua_script_once();
  check(loop_lua_fl, "a success between failures must reset script1's streak - 8 failures split by 1 success must not stop the loop");
  check(!lua_script1_disabled, "script1's streak never reaches the threshold - it must stay enabled");
  check(lua_periodic_failure_count_script1 == 4, "script1's streak after its own reset must count only the 4 failures since the last success");
  check(count_occurrences("script.lua остановлен") == 0, "script1 must not be stopped when its streak never reaches the threshold");
}

static void test_success_between_failures_resets_script2_counter() {
  reset_fixture();
  loop_lua_fl = true;
  script2 = String("script2-body");
  // script1 пуст - изолируем поведение script2 от script1.
  lua_type_script = String("dist.lua");
  chunkResultsScript2 = {"e1", "e2", "e3", "e4", "", "e5", "e6", "e7", "e8"};
  periodicIterationsTarget = 9;
  run_do_lua_script_once();
  check(loop_lua_fl, "a success between failures must reset script2's streak - 8 failures split by 1 success must not stop the loop");
  check(lua_periodic_failure_count_script2 == 4, "script2's streak after its own reset must count only the 4 failures since the last success");
  check(count_occurrences("остановлен") == 0, "script2 must not be stopped when its streak never reaches the threshold");
}

static void test_load_lua_script_resets_both_counters_and_reenables_script1() {
  reset_fixture();
  lua_periodic_failure_count_script1 = 7;
  lua_periodic_failure_count_script2 = 9;
  lua_script1_disabled = true;
  load_lua_script();
  check(lua_periodic_failure_count_script1 == 0, "load_lua_script() must reset script1's consecutive-failure counter unconditionally");
  check(lua_periodic_failure_count_script2 == 0, "load_lua_script() must reset script2's consecutive-failure counter unconditionally");
  check(!lua_script1_disabled, "load_lua_script() must lift script1's disable flag, so a fixed script.lua can run again without a device reboot");
}

static void test_oneshot_job_failure_does_not_touch_either_counter() {
  reset_fixture();
  loop_lua_fl = false;
  lua_periodic_failure_count_script1 = 2;
  lua_periodic_failure_count_script2 = 3;
  takeLuaJobReturn = true;
  takeLuaJobType = LUA_JOB_INLINE;
  oneShotJobResult = "oneshot boom";
  oneShotJobsTarget = 1;
  run_do_lua_script_once();
  check(lua_periodic_failure_count_script1 == 2, "a failing one-shot job must not change script1's periodic failure counter");
  check(lua_periodic_failure_count_script2 == 3, "a failing one-shot job must not change script2's periodic failure counter");
  check(!lua_script1_disabled, "a failing one-shot job must never disable script1");
  check(count_occurrences("ERR in lua: oneshot boom") == 1, "one-shot job failure must still be logged under its own prefix");
  check(count_occurrences("остановлен") == 0, "a one-shot job must never emit either periodic-stop message");
  check(!loop_lua_fl, "a one-shot job must never turn the periodic loop on");
}

int main() {
  try {
    test_five_script1_failures_disable_script1_without_stopping_loop();
    test_five_script2_failures_stop_the_loop();
    test_success_between_failures_resets_script1_counter();
    test_success_between_failures_resets_script2_counter();
    test_load_lua_script_resets_both_counters_and_reenables_script1();
    test_oneshot_job_failure_does_not_touch_either_counter();
  } catch (const SafetyCapHit&) {
    std::cerr << "FAIL: safety cap hit - do_lua_script never reached the expected stopping point (infinite loop?)\n";
    return 1;
  }
  return failures == 0 ? 0 : 1;
}
'''


def production_failure_threshold(source: str) -> int:
    import re
    match = re.search(r"#define LUA_PERIODIC_FAILURE_STOP_THRESHOLD\s+(\d+)", source)
    if not match:
        raise ValueError("LUA_PERIODIC_FAILURE_STOP_THRESHOLD #define not found in lua.h")
    return int(match.group(1))


def build_harness(source: str) -> str:
    # Харнесс переобъявляет порог как #define со значением 5 (см. шаблон выше) -
    # сверяем его с реальным значением из lua.h, чтобы тест не тестировал
    # устаревшее число незаметно для читающего.
    threshold = production_failure_threshold(source)
    if threshold != 5:
        raise ValueError(
            f"LUA_PERIODIC_FAILURE_STOP_THRESHOLD changed to {threshold} in lua.h - "
            "update the hardcoded value in this harness's test scenarios"
        )
    definitions = []
    for signature in SIGNATURES:
        # strip_comments=False: мутации ниже находят место правки по тексту
        # комментария "// [П26]" в скомпилированном харнессе - на компиляцию
        # и поведение это не влияет, комментарии тут не мешают проверке.
        body = extract_function_body(source, signature, strip_comments=False)
        definitions.append(f"{signature} {{\n{body}\n}}")
    return HARNESS_TEMPLATE.replace("@FUNCTIONS@", "\n\n".join(definitions))


def compile_and_run(harness: str, label: str, show_output: bool = True) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-lua-periodic-failure-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "lua_periodic_failure_test.cpp"
        binary = temp / "lua_periodic_failure_test"
        source.write_text(harness, encoding="utf-8")
        compiled = subprocess.run(
            # -Wno-unused-parameter: do_lua_script(void *parameter) - реальная
            # сигнатура из lua.h, parameter там тоже не используется. Извлекаем
            # тело буквально (extract_function_body), поэтому подавляем warning
            # флагом компилятора, а не правкой извлечённого текста.
            ["g++", "-std=c++17", "-Wall", "-Wextra", "-Wno-unused-parameter", "-Werror",
             str(source), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compiled.returncode:
            output = compiled.stdout + compiled.stderr
            if show_output:
                sys.stderr.write(f"[{label}] compile failed:\n{output}")
            return compiled.returncode, output
        ran = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        output = ran.stdout + ran.stderr
        if show_output:
            sys.stdout.write(ran.stdout)
            sys.stderr.write(ran.stderr)
        return ran.returncode, output


def require_mutation(harness: str, old: str, new: str, expected: str) -> bool:
    mutant = harness.replace(old, new, 1)
    if mutant == harness:
        print(f"FAIL: cannot construct mutation for {expected}", file=sys.stderr)
        return False
    code, output = compile_and_run(mutant, expected, False)
    if code == 0 or expected not in output:
        print(f"FAIL: {expected} mutation survived", file=sys.stderr)
        sys.stderr.write(output)
        return False
    return True


def main() -> int:
    lua = (ROOT / "lua.h").read_text(encoding="utf-8")
    try:
        harness = build_harness(lua)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    code, _ = compile_and_run(harness, "Lua periodic failure stop")
    if code:
        return 1
    mutations = [
        (
            "lua_periodic_failure_count_script1 >= LUA_PERIODIC_FAILURE_STOP_THRESHOLD",
            "lua_periodic_failure_count_script1 > LUA_PERIODIC_FAILURE_STOP_THRESHOLD",
            "script1 must be disabled after 5 consecutive failures",
        ),
        (
            "lua_periodic_failure_count_script2 >= LUA_PERIODIC_FAILURE_STOP_THRESHOLD",
            "lua_periodic_failure_count_script2 > LUA_PERIODIC_FAILURE_STOP_THRESHOLD",
            "5 consecutive script2 (mode script) failures must stop the periodic loop",
        ),
        (
            "        } else {\n          lua_periodic_failure_count_script1 = 0;\n        }\n      }\n      vTaskDelay(5 / portTICK_PERIOD_MS);",
            "        }\n      }\n      vTaskDelay(5 / portTICK_PERIOD_MS);",
            "script1's streak after its own reset must count only the 4 failures since the last success",
        ),
        (
            "        } else {\n          lua_periodic_failure_count_script2 = 0;\n        }\n      } else {\n        lua_gc(lua.GetState(), LUA_GCCOLLECT, 0);",
            "        }\n      } else {\n        lua_gc(lua.GetState(), LUA_GCCOLLECT, 0);",
            "script2's streak after its own reset must count only the 4 failures since the last success",
        ),
        (
            "  lua_periodic_failure_count_script1 = 0;\n  lua_periodic_failure_count_script2 = 0;\n  lua_script1_disabled = false;\n  // [П26]",
            "  // [П26]",
            "load_lua_script() must reset script1's consecutive-failure counter unconditionally",
        ),
        (
            "  lua_script1_disabled = false;\n  // [П26]",
            "  // [П26]",
            "load_lua_script() must lift script1's disable flag, so a fixed script.lua can run again without a device reboot",
        ),
    ]
    for old, new, expected in mutations:
        if not require_mutation(harness, old, new, expected):
            return 1
    print("Lua periodic failure stop mutations were rejected as expected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
