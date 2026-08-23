#ifndef __SAMOVAR_LUA_H_
#define __SAMOVAR_LUA_H_

#include "Samovar.h"
#include "samovar_api.h"
#include "numeric_parse.h"
#include "runtime_helpers.h"
#include "safety_transition.h"

#ifdef USE_WATER_PUMP
#include "pumppwm.h"
#endif

#include <LuaWrapper.h>
LuaWrapper lua;

inline bool lua_state_lock(TickType_t timeout = pdMS_TO_TICKS(50)) {
  return xLuaSemaphore && xSemaphoreTake(xLuaSemaphore, timeout) == pdTRUE;
}

inline void lua_state_unlock(bool locked) {
  if (locked) xSemaphoreGive(xLuaSemaphore);
}

// [P8] Watchdog зависших Lua-чанков: hook по счётчику VM-инструкций обрывает
// исполнение luaL_error'ом (longjmp), если чанк не уложился в дедлайн.
// Компромисс: lua_wrapper_delay (см. ниже) НЕ ограничен этим таймаутом — там нет
// байткода между инструкциями, а vTaskDelay внутри hook не дёрнуть; hook сработает
// только когда задача проснётся и вернётся к выполнению чанка.
#ifndef LUA_CHUNK_TIMEOUT_MS
#define LUA_CHUNK_TIMEOUT_MS 20000
#endif
#ifndef LUA_CHUNK_TIMEOUT_INSTRUCTIONS
#define LUA_CHUNK_TIMEOUT_INSTRUCTIONS 1000
#endif

static volatile uint32_t luaHookDeadlineMs;
static volatile bool luaTimeoutFired;
static volatile bool luaLastExecutionTimedOut;
String lua_coroutine_watchdog_error;

static void lua_timeout_hook(lua_State* L, lua_Debug*) {
  if (safety_deadline_expired(millis(), luaHookDeadlineMs)) {
    luaTimeoutFired = true;
    luaL_error(L, "chunk timeout");  // longjmp! никаких SendMsg/тяжёлых вызовов здесь
  }
}

inline void lua_install_timeout_hook_locked() {
  luaHookDeadlineMs = safety_deadline_after(millis(), LUA_CHUNK_TIMEOUT_MS);
  luaTimeoutFired = false;
  lua_sethook(lua.GetState(), lua_timeout_hook, LUA_MASKCOUNT, LUA_CHUNK_TIMEOUT_INSTRUCTIONS);
}

inline void lua_remove_timeout_hook_locked() {
  lua_sethook(lua.GetState(), NULL, 0, 0);
}

inline void lua_report_timeout_if_fired() {
  if (!luaTimeoutFired) return;
  luaTimeoutFired = false;
  SendMsg("Lua: выполнение чанка прервано по таймауту", ALARM_MSG);
}

inline String lua_exec_locked(String& script, bool collect_garbage = false) {
  // [П27] lua.Lua_dostring делает lua_pcall(..., LUA_MULTRET, ...) - возвращаемые
  // чанком значения остаются на стеке навсегда. Запоминаем высоту стека до вызова
  // и восстанавливаем после - как это уже сделано в lua_exec_chunk_locked.
  lua_State* L = lua.GetState();
  int base = lua_gettop(L);
  lua_install_timeout_hook_locked();
  String result = lua.Lua_dostring(&script);
  lua_remove_timeout_hook_locked();
  luaLastExecutionTimedOut = luaTimeoutFired;
  lua_report_timeout_if_fired();
  // [P8] __gc-финализаторы НЕ покрываются hook-watchdog'ом: вендорный lgc.c::GCTM()
  // выставляет L->allowhook=0 перед вызовом __gc (ldo.c::luaD_hook вызывает хук
  // только когда allowhook==1) - count-хук во время __gc не сработает вне
  // зависимости от того, снят он к этому моменту или ещё установлен. Зависший
  // __gc-финализатор повесит задачу Lua - принятое ограничение, а не защищённый
  // watchdog'ом случай.
  if (collect_garbage) {
    lua_gc(L, LUA_GCCOLLECT, 0);
  }
  lua_settop(L, base);
  return result;
}

inline String lua_exec(String& script, bool collect_garbage = false, TickType_t timeout = pdMS_TO_TICKS(50)) {
  bool locked = lua_state_lock(timeout);
  if (!locked) return "Lua busy";
  String result = lua_exec_locked(script, collect_garbage);
  lua_state_unlock(true);
  return result;
}

inline bool lua_chunk_ref_valid(int ref) {
  return ref != LUA_NOREF && ref != LUA_REFNIL;
}

inline void lua_unref_chunk_locked(int& ref) {
  if (lua_chunk_ref_valid(ref)) {
    luaL_unref(lua.GetState(), LUA_REGISTRYINDEX, ref);
  }
  ref = LUA_NOREF;
}

inline String lua_error_string(lua_State* L) {
  const char* error = lua_tostring(L, -1);
  return error ? String(error) : String("unknown Lua error");
}

inline String lua_compile_chunk_locked(const String& script, const char* chunk_name, int& ref) {
  lua_unref_chunk_locked(ref);
  if (script.length() == 0) return "";
  lua_State* L = lua.GetState();
  int base = lua_gettop(L);
  if (luaL_loadbuffer(L, script.c_str(), script.length(), chunk_name) != LUA_OK) {
    String error = lua_error_string(L);
    lua_settop(L, base);
    return "# lua compile error:\n" + error;
  }
  ref = luaL_ref(L, LUA_REGISTRYINDEX);
  lua_settop(L, base);
  return "";
}

inline String lua_exec_chunk_locked(int ref, bool collect_garbage = false) {
  if (!lua_chunk_ref_valid(ref)) return "";
  lua_State* L = lua.GetState();
  int base = lua_gettop(L);
  String result;
  lua_rawgeti(L, LUA_REGISTRYINDEX, ref);
  lua_install_timeout_hook_locked();
  if (lua_pcall(L, 0, LUA_MULTRET, 0) != LUA_OK) {
    result = "# lua error:\n" + lua_error_string(L);
  }
  lua_remove_timeout_hook_locked();
  luaLastExecutionTimedOut = luaTimeoutFired;
  lua_report_timeout_if_fired();
  // [P8] __gc-финализаторы НЕ покрываются hook-watchdog'ом - см. комментарий в
  // lua_exec_locked(). Зависший __gc-финализатор повесит задачу Lua - принятое
  // ограничение.
  if (collect_garbage) {
    lua_gc(L, LUA_GCCOLLECT, 0);
  }
  lua_settop(L, base);
  return result;
}

inline void lua_set_number_global_locked(const char* name, lua_Number value) {
  lua_pushnumber(lua.GetState(), value);
  lua_setglobal(lua.GetState(), name);
}

inline void lua_install_constants_locked() {
  lua_set_number_global_locked("INPUT", INPUT);
  lua_set_number_global_locked("OUTPUT", OUTPUT);
  lua_set_number_global_locked("LOW", LOW);
  lua_set_number_global_locked("HIGH", HIGH);
  lua_set_number_global_locked("ACTUATOR_COMMAND_ACCEPTED", ACTUATOR_COMMAND_ACCEPTED);
  lua_set_number_global_locked("ACTUATOR_COMMAND_PENDING", ACTUATOR_COMMAND_PENDING);
  lua_set_number_global_locked("ACTUATOR_COMMAND_APPLIED", ACTUATOR_COMMAND_APPLIED);
  lua_set_number_global_locked("ACTUATOR_COMMAND_FAILED", ACTUATOR_COMMAND_FAILED);
}

// [П3] Lua может поднять канал нагрева сырым digitalWrite, минуя PowerOn.
// Запоминаем этот факт здесь, чтобы аварийный надзор (перегрев, отказ датчиков)
// работал и в этом случае - иначе скрипт греет без единого шанса на отсечку.
// Раздельно по каналу (RELE_CHANNEL1 - основной ТЭН, RELE_CHANNEL4 - разгонный):
// "поднят" значит записан РАВНО тот уровень, что C++-тракт считает включённым
// (SamSetup.rele1/rele4 - см. power_regulator.h heater_outputs_enable_locked).
static bool luaHeaterChannel1Raised = false;
static bool luaHeaterChannel4Raised = false;
inline bool lua_heater_channel_raised() { return luaHeaterChannel1Raised || luaHeaterChannel4Raised; }

inline void lua_set_heater_channel_raised(int pin, bool raised) {
  if (pin == RELE_CHANNEL1) luaHeaterChannel1Raised = raised;
  else if (pin == RELE_CHANNEL4) luaHeaterChannel4Raised = raised;
}

// level - сырое значение, ушедшее в digitalWrite(pin, level) (без инверсии по
// releN - см. комментарий в lua_wrapper_digitalWrite). "Включено" - совпадение
// с SamSetup.releN этого канала, как и в C++-тракте.
inline void lua_track_heater_channel_write(int pin, int level) {
  const bool onLevel = (pin == RELE_CHANNEL1) ? SamSetup.rele1 : SamSetup.rele4;
  lua_set_heater_channel_raised(pin, (level != 0) == onLevel);
}

// [P8] lua_sethook выше вооружает только ГЛАВНЫЙ lua_State. Код внутри
// coroutine.resume исполняется в СВОЁМ lua_State и хуком главного состояния не
// покрыт - зависший `while true do end` внутри корутины watchdog не прервёт
// (подтверждено экспериментом: MASKCOUNT=50 не сработал ни разу за 10000
// итераций в корутине). Лечим Lua-прелюдией: подменяем coroutine.create/wrap/
// resume так, чтобы дочерний lua_State тоже вооружался тем же хуком. Дедлайн
// (luaHookDeadlineMs) - общий static, его выставляет lua_install_timeout_hook_locked()
// перед исполнением; корутина, резюмируемая внутри exec-окна, увидит актуальный
// дедлайн, а вне exec-окна Lua не исполняется вовсе - ложных срабатываний нет.
static int lua_wrapper_arm_coroutine_watchdog(lua_State* lua_state) {
  lua_State* co = lua_tothread(lua_state, 1);
  if (co) lua_sethook(co, lua_timeout_hook, LUA_MASKCOUNT, LUA_CHUNK_TIMEOUT_INSTRUCTIONS);
  return 0;
}

// coroutine.resume перевооружает co перед КАЖДЫМ резюме - это ловит и корутины,
// созданные до подмены, и созданные через сохранённые оригиналы (originalCreate).
// coroutine.wrap оборачивает оригинальный resume, а не подменённый глобальный,
// и пробрасывает ошибку (в т.ч. "chunk timeout") через error(msg, 0) - как это
// делает штатный coroutine.wrap.
// [П2] Пользовательский скрипт живёт в том же _G, что и armCoroutineWatchdog -
// без укрытия он мог бы написать `armCoroutineWatchdog = function() end` и
// обойти сторож. Захватываем C-функцию в локальную переменную прелюдии (тот же
// приём, что уже применён к originalCreate/originalResume) и в конце убираем
// глобальное имя - дальнейшие переопределения глобали замыканий уже не касаются.
static const char* const LUA_COROUTINE_WATCHDOG_PRELUDE = R"lua(
local armCoroutineWatchdog = armCoroutineWatchdog
local originalCreate = coroutine.create
local originalResume = coroutine.resume
coroutine.create = function(f)
  local co = originalCreate(f)
  armCoroutineWatchdog(co)
  return co
end
coroutine.wrap = function(f)
  local co = coroutine.create(f)
  armCoroutineWatchdog(co)
  return function(...)
    local results = table.pack(originalResume(co, ...))
    if not results[1] then error(results[2], 0) end
    return table.unpack(results, 2, results.n)
  end
end
coroutine.resume = function(co, ...)
  armCoroutineWatchdog(co)
  return originalResume(co, ...)
end
-- ВАЖНО: именно _G.armCoroutineWatchdog, а не голое имя - после `local
-- armCoroutineWatchdog = armCoroutineWatchdog` выше голое имя уже указывает на
-- локальную переменную (ту, что замкнули функции выше), и `armCoroutineWatchdog
-- = nil` обнулил бы ИМЕННО её, а не глобаль.
_G.armCoroutineWatchdog = nil
)lua";

// Исполняется один раз при инициализации Lua-состояния (см. lua_init(), сразу
// после lua_install_constants_locked()). Ошибка прелюдии делает Lua runtime
// неготовым: запуск без watchdog'а корутин запрещён.
inline bool lua_install_coroutine_watchdog_locked() {
  lua_State* L = lua.GetState();
  lua_register(L, "armCoroutineWatchdog", lua_wrapper_arm_coroutine_watchdog);
  luaL_requiref(L, LUA_COLIBNAME, luaopen_coroutine, 1);
  lua_pop(L, 1);
  if (luaL_dostring(L, LUA_COROUTINE_WATCHDOG_PRELUDE) != LUA_OK) {
    const char* error = lua_tostring(L, -1);
    lua_coroutine_watchdog_error = error ? error : "unknown watchdog prelude error";
    lua_pop(L, 1);
    return false;
  }
  lua_coroutine_watchdog_error = "";
  return true;
}


/**
 * @brief Надзор за режимом Lua (mode_registry.h::mode_dispatch_alarm, SysTicker,
 * core 0, 1 Гц). В отличие от check_alarm_suvid (suvid.h) все три датчика тут
 * опциональны — какие датчики нужны, решает сам Lua-скрипт, а не прошивка.
 */
inline void check_alarm_lua() {
  mode_clear_alarm_pause_if_expired();

  // [П3] Lua мог поднять канал нагрева сырым digitalWrite мимо PowerOn -
  // в этом случае надзор датчиков обязан работать так же, как при PowerOn.
  if (PowerOn || lua_heater_channel_raised()) {
    if (optional_sensor_failed(WaterSensor) && process_sensor_failed("Lua", "воды")) return;
    if (optional_sensor_failed(ACPSensor) && process_sensor_failed("Lua", "ТСА")) return;
    if (optional_sensor_failed(TankSensor) && process_sensor_failed("Lua", "куба")) return;
  }

#ifdef SAMOVAR_USE_POWER
  check_power_error();
#endif

  mode_request_overheat_emergency_if_needed();
  mode_request_water_flow_emergency_if_needed();
}

#include <SimpleMap.h>

#include <asyncHTTPrequest.h>
#include "I2CStepper.h"

#include <TimeLib.h>

#define EXPANDER_UPDATE_TIMEOUT 500


unsigned long lua_timer[10];  //10 таймеров для lua
String lua_type_script;
String script1, script2;
int script1_ref = LUA_NOREF;
int script2_ref = LUA_NOREF;
extern String lua_script_list_cache;

// [П30] Падающий режимный скрипт раньше перезапускался планировщиком раз в
// секунду безусловно и забивал журнал повторяющимся "ERR in <режим>.lua: ..."
// вечно. Порог подряд идущих неуспешных прогонов, после которого периодический
// цикл останавливается и печатается ОДНО итоговое сообщение вместо потока ERR.
#ifndef LUA_PERIODIC_FAILURE_STOP_THRESHOLD
#define LUA_PERIODIC_FAILURE_STOP_THRESHOLD 5
#endif
// [Fix] script1 (общий script.lua) и script2 (режимный скрипт) падают независимо -
// счётчик один на оба заставлял ошибку в пользовательском script.lua тушить
// исправно работающий режимный скрипт. Счётчики раздельные; script1 при
// достижении порога не глушит планировщик (loop_lua_fl), а просто перестаёт
// запускаться сам, пока его не перезагрузят через load_lua_script().
static volatile uint8_t lua_periodic_failure_count_script1 = 0;
static volatile uint8_t lua_periodic_failure_count_script2 = 0;
static volatile bool lua_script1_disabled = false;

// [П26] Ключи setObject/getObject раньше копились в luaObj без предела -
// хранилище растёт бесконечно, пока не сменится режимный скрипт. Предел числа
// РАЗНЫХ ключей (обновление существующего ключа лимит не расходует).
#ifndef LUA_OBJECT_STORE_MAX_KEYS
#define LUA_OBJECT_STORE_MAX_KEYS 32
#endif

SimpleMap<String, String> *luaObj = new SimpleMap<String, String>([](String &a, String &b) -> int {
  if (a == b) return 0;      // a and b are equal
  else if (a > b) return 1;  // a is bigger than b
  else return -1;            // a is smaller than b
});

TaskHandle_t DoLuaScriptTask = NULL;
volatile bool lua_finished;
volatile bool lua_start_requested = false;

enum LuaJobType : uint8_t {
  LUA_JOB_NONE = 0,
  LUA_JOB_SCRIPT,
  LUA_JOB_INLINE
};

String lua_job_script;
volatile LuaJobType lua_job_type = LUA_JOB_NONE;
volatile bool lua_job_active = false;

enum LuaBeerJobResult : uint8_t {
  LUA_BEER_JOB_IDLE = 0,
  LUA_BEER_JOB_QUEUED,
  LUA_BEER_JOB_RUNNING,
  LUA_BEER_JOB_SUCCEEDED,
  LUA_BEER_JOB_STOPPED,
  LUA_BEER_JOB_FAILED_INIT,
  LUA_BEER_JOB_FAILED_RUNTIME,
  LUA_BEER_JOB_FAILED_TIMEOUT,
};

volatile bool lua_runtime_ready = false;
volatile bool lua_coroutine_watchdog_ready = false;
volatile bool lua_boot_init_ready = false;
volatile uint32_t lua_beer_job_next_ticket = 0;
volatile uint32_t lua_beer_job_ticket = 0;
volatile LuaBeerJobResult lua_beer_job_result = LUA_BEER_JOB_IDLE;
#ifdef SAMOVAR_LUA_SIMULATION
static uint32_t luaSimulationMillis = 0;
#endif

inline bool lua_state_mutation_allowed() {
  return !mode_switch_in_progress();
}

inline int lua_reject_state_mutation(lua_State* lua_state) {
  return luaL_error(lua_state, "mode switch blocks state changes");
}

inline bool lua_simulation_enabled() {
#ifdef SAMOVAR_LUA_SIMULATION
  return true;
#else
  return false;
#endif
}

inline int lua_reject_actuator_mutation(lua_State* lua_state) {
  return luaL_error(lua_state, "Lua simulation blocks actuator control");
}

inline bool queue_lua_job(LuaJobType type, const String& script) {
  if (script.length() == 0) return true;
  if (!lua_runtime_ready) return false;
  if (mode_switch_in_progress()) return false;
  bool locked = runtime_state_lock(pdMS_TO_TICKS(500));
  if (!locked) return false;
  bool queued = false;
  if (!mode_switch_in_progress() && lua_job_type == LUA_JOB_NONE) {
    lua_job_script = script;
    lua_job_type = type;
    queued = true;
  }
  runtime_state_unlock(true);
  return queued;
}

inline bool queue_lua_script_job(const String& script) {
  return queue_lua_job(LUA_JOB_SCRIPT, script);
}

inline bool queue_lua_inline_job(const String& script) {
  return queue_lua_job(LUA_JOB_INLINE, script);
}

inline bool take_lua_job(String& script, LuaJobType& type) {
  bool locked = runtime_state_lock(pdMS_TO_TICKS(50));
  if (!locked) return false;
  bool hasJob = false;
  if (!mode_switch_in_progress() && lua_job_type != LUA_JOB_NONE) {
    script = lua_job_script;
    type = lua_job_type;
    lua_job_script = "";
    lua_job_type = LUA_JOB_NONE;
    lua_job_active = true;
    hasJob = true;
  }
  runtime_state_unlock(true);
  return hasJob;
}

inline void finish_lua_job() {
  bool locked = runtime_state_lock(portMAX_DELAY);
  if (locked) {
    lua_job_active = false;
    runtime_state_unlock(true);
  }
}

inline bool request_lua_periodic_start() {
  if (!lua_runtime_ready) return false;
  if (mode_switch_in_progress()) return false;
  bool locked = runtime_state_lock(pdMS_TO_TICKS(50));
  if (!locked) return false;
  bool accepted = false;
  if (!mode_switch_in_progress() && lua_finished && !lua_start_requested) {
    lua_start_requested = true;
    accepted = true;
  }
  runtime_state_unlock(true);
  return accepted;
}

inline bool request_lua_mode_stop() {
  bool locked = runtime_state_lock(pdMS_TO_TICKS(50));
  if (!locked) return false;
  SetScriptOff = true;
  loop_lua_fl = false;
  lua_start_requested = false;
  lua_job_script = "";
  lua_job_type = LUA_JOB_NONE;
  runtime_state_unlock(true);
  return true;
}

inline bool lua_mode_owner_idle() {
  bool locked = runtime_state_lock(pdMS_TO_TICKS(50));
  if (!locked) return false;
  const bool idle = lua_finished && !lua_start_requested &&
                    lua_job_type == LUA_JOB_NONE && !lua_job_active &&
                    !loop_lua_fl;
  runtime_state_unlock(true);
  if (!idle) return false;
  const bool vmIdle = lua_state_lock(0);
  lua_state_unlock(vmIdle);
  return vmIdle;
}

inline bool consume_lua_periodic_start_request(bool& accepted) {
  bool locked = runtime_state_lock(pdMS_TO_TICKS(50));
  if (!locked) return false;
  accepted = false;
  if (mode_switch_in_progress()) {
    lua_start_requested = false;
    if (lua_beer_job_result == LUA_BEER_JOB_QUEUED) {
      lua_beer_job_result = LUA_BEER_JOB_FAILED_RUNTIME;
    }
  } else if (lua_start_requested && lua_finished) {
    lua_start_requested = false;
    lua_finished = false;
    accepted = true;
    if (lua_beer_job_result == LUA_BEER_JOB_QUEUED) {
      lua_beer_job_result = LUA_BEER_JOB_RUNNING;
    }
  }
  runtime_state_unlock(true);
  return true;
}

inline bool lua_periodic_active(bool& active) {
  bool locked = runtime_state_lock(pdMS_TO_TICKS(50));
  if (!locked) return false;
  active = !lua_finished;
  runtime_state_unlock(true);
  return true;
}

inline void finish_lua_periodic_run() {
  bool locked = runtime_state_lock(portMAX_DELAY);
  if (locked) {
    lua_finished = true;
    runtime_state_unlock(true);
  }
}

inline void finish_beer_lua_periodic_result(bool periodicFailed, bool periodicTimedOut) {
  bool locked = runtime_state_lock(pdMS_TO_TICKS(50));
  if (locked && (lua_beer_job_result == LUA_BEER_JOB_RUNNING ||
      (lua_beer_job_result == LUA_BEER_JOB_SUCCEEDED && periodicFailed))) {
    lua_beer_job_result = periodicTimedOut ? LUA_BEER_JOB_FAILED_TIMEOUT
        : periodicFailed ? LUA_BEER_JOB_FAILED_RUNTIME : LUA_BEER_JOB_SUCCEEDED;
  }
  runtime_state_unlock(locked);
}

inline bool request_beer_lua_job(uint32_t& ticket) {
  bool locked = runtime_state_lock(pdMS_TO_TICKS(50));
  if (!locked) return false;
  const bool modeScriptReady = lua_runtime_ready && script2.length() > 0 &&
                               lua_chunk_ref_valid(script2_ref);
  if (!modeScriptReady || mode_switch_in_progress() || !lua_finished ||
      lua_start_requested || loop_lua_fl) {
    lua_beer_job_result = modeScriptReady ? LUA_BEER_JOB_FAILED_RUNTIME
                                          : LUA_BEER_JOB_FAILED_INIT;
    runtime_state_unlock(true);
    return false;
  }
  ticket = ++lua_beer_job_next_ticket;
  lua_beer_job_ticket = ticket;
  lua_beer_job_result = LUA_BEER_JOB_QUEUED;
  SetScriptOff = false;
  loop_lua_fl = true;
  lua_start_requested = true;
  runtime_state_unlock(true);
  return true;
}

inline LuaBeerJobResult beer_lua_job_result(uint32_t ticket) {
  bool locked = runtime_state_lock(pdMS_TO_TICKS(50));
  if (!locked) return LUA_BEER_JOB_FAILED_RUNTIME;
  const LuaBeerJobResult result = ticket == lua_beer_job_ticket
      ? lua_beer_job_result : LUA_BEER_JOB_FAILED_RUNTIME;
  runtime_state_unlock(true);
  return result;
}

inline bool request_beer_lua_stop(uint32_t ticket) {
  bool locked = runtime_state_lock(portMAX_DELAY);
  if (!locked || ticket != lua_beer_job_ticket) {
    runtime_state_unlock(locked);
    return false;
  }
  SetScriptOff = true;
  loop_lua_fl = false;
  lua_start_requested = false;
  lua_beer_job_result = LUA_BEER_JOB_STOPPED;
  runtime_state_unlock(true);
  return true;
}

inline bool beer_lua_job_idle(uint32_t ticket) {
  if (ticket != lua_beer_job_ticket) return false;
  return lua_mode_owner_idle();
}

static bool lua_copy_current_program(WProgram& currentProgram) {
  if (ProgramNum >= PROGRAM_MAX) return false;
  currentProgram = program[ProgramNum];
  return !program_type_empty(currentProgram.WType);
}

static String lua_to_string_arg(lua_State *lua_state, int index) {
  String value;
  lua_getglobal(lua_state, "tostring");
  lua_pushvalue(lua_state, index);
  lua_call(lua_state, 1, 1);
  size_t len;
  const char *text = lua_tolstring(lua_state, -1, &len);
  if (text) value = text;
  lua_pop(lua_state, 1);
  return value;
}

enum LuaVariableAccess : uint8_t {
  LUA_VAR_READ = 0x01,
  LUA_VAR_WRITE = 0x02
};

static const uint8_t LUA_VAR_RO = LUA_VAR_READ;
static const uint8_t LUA_VAR_WO = LUA_VAR_WRITE;
static const uint8_t LUA_VAR_RW = LUA_VAR_READ | LUA_VAR_WRITE;

enum LuaNumVariableDomain : uint8_t {
  LUA_NUM_INTEGRAL = 0,
  LUA_NUM_FRACTIONAL,
};

struct LuaNumVariableDescriptor {
  const char* name;
  float (*getter)();
  bool (*setter)(int32_t integerValue, float fractionalValue);
  uint8_t access;
  LuaNumVariableDomain domain;
  int32_t minValue;
  int32_t maxValue;
};

static float lua_num_get_WFpulseCount() { return water_pulse_count_get(); }
static float lua_num_get_pump_started() { return pump_started; }
static float lua_num_get_valve_status() { return valve_status; }
static float lua_num_get_SamSetup_Mode() { return SamSetup.Mode; }
static float lua_num_get_Samovar_Mode() { return Samovar_Mode; }
static float lua_num_get_Samovar_CR_Mode() { return Samovar_CR_Mode; }
static float lua_num_get_acceleration_temp() { return acceleration_temp; }
static bool lua_num_set_acceleration_temp(int32_t value, float) {
  acceleration_temp = static_cast<uint16_t>(value);
  return true;
}
#ifdef USE_WATER_PUMP
static float lua_num_get_wp_count() { return wp_count; }
static bool lua_num_set_wp_count(int32_t value, float) {
  wp_count = static_cast<int8_t>(value);
  return true;
}
static bool lua_num_set_pmpKp(int32_t, float value) {
  pump_regulator.Kp = value;
  return true;
}
static bool lua_num_set_pmpKi(int32_t, float value) {
  pump_regulator.Ki = value;
  return true;
}
static bool lua_num_set_pmpKd(int32_t, float value) {
  pump_regulator.Kd = value;
  return true;
}
#endif
static float lua_num_get_SteamTemp() { return SteamSensor.avgTemp; }
static float lua_num_get_boil_temp() { return boil_temp; }
static bool lua_num_set_boil_temp(int32_t, float value) {
  boil_temp = value;
  return true;
}
static float lua_num_get_PipeTemp() { return PipeSensor.avgTemp; }
static float lua_num_get_WaterTemp() { return WaterSensor.avgTemp; }
static float lua_num_get_TankTemp() { return TankSensor.avgTemp; }
static float lua_num_get_ACPTemp() { return ACPSensor.avgTemp; }
#ifdef SAMOVAR_LUA_SIMULATION
static float virtualSteamTemp = 0;
static float virtualPipeTemp = 0;
static float virtualWaterTemp = 0;
static float virtualTankTemp = 0;
static float virtualACPTemp = 0;
static float lua_num_get_VirtualSteamTemp() { return virtualSteamTemp; }
static bool lua_num_set_VirtualSteamTemp(int32_t, float value) { virtualSteamTemp = value; return true; }
static float lua_num_get_VirtualPipeTemp() { return virtualPipeTemp; }
static bool lua_num_set_VirtualPipeTemp(int32_t, float value) { virtualPipeTemp = value; return true; }
static float lua_num_get_VirtualWaterTemp() { return virtualWaterTemp; }
static bool lua_num_set_VirtualWaterTemp(int32_t, float value) { virtualWaterTemp = value; return true; }
static float lua_num_get_VirtualTankTemp() { return virtualTankTemp; }
static bool lua_num_set_VirtualTankTemp(int32_t, float value) { virtualTankTemp = value; return true; }
static float lua_num_get_VirtualACPTemp() { return virtualACPTemp; }
static bool lua_num_set_VirtualACPTemp(int32_t, float value) { virtualACPTemp = value; return true; }
#endif
static float lua_num_get_loop_lua_fl() { return loop_lua_fl; }
static bool lua_num_set_loop_lua_fl(int32_t value, float) {
  loop_lua_fl = value;
  return true;
}
static float lua_num_get_SetScriptOff() { return SetScriptOff; }
static bool lua_num_set_SetScriptOff(int32_t value, float) {
  SetScriptOff = value != 0;
  return true;
}
static float lua_num_get_show_lua_script() { return show_lua_script; }
static bool lua_num_set_show_lua_script(int32_t value, float) {
  show_lua_script = value;
  return true;
}
static float lua_num_get_test_num_val() { return test_num_val; }
static bool lua_num_set_test_num_val(int32_t, float value) {
  test_num_val = value;
  return true;
}
static float lua_num_get_WFtotalMilliLitres() { return WFtotalMilliLitres; }
static float lua_num_get_WFflowRate() { return WFflowRate; }
static float lua_num_get_program_volume() {
  WProgram currentProgram;
  return lua_copy_current_program(currentProgram) ? currentProgram.Volume : 0;
}
static float lua_num_get_program_speed() {
  WProgram currentProgram;
  return lua_copy_current_program(currentProgram) ? currentProgram.Speed : 0;
}
static float lua_num_get_program_temp() {
  WProgram currentProgram;
  return lua_copy_current_program(currentProgram) ? currentProgram.Temp : 0;
}
static float lua_num_get_program_power() {
  WProgram currentProgram;
  return lua_copy_current_program(currentProgram) ? currentProgram.Power : 0;
}
static float lua_num_get_program_time() {
  WProgram currentProgram;
  return lua_copy_current_program(currentProgram) ? currentProgram.Time : 0;
}
static float lua_num_get_program_capacity_num() {
  WProgram currentProgram;
  return lua_copy_current_program(currentProgram) ? currentProgram.capacity_num : 0;
}
static float lua_num_get_capacity_num() { return capacity_num; }
static float lua_num_get_target_power_volt() { return target_power_volt; }
static float lua_num_get_PowerOn() { return PowerOn; }
static float lua_num_get_alcohol() { return get_alcohol(TankSensor.avgTemp); }
static float lua_num_get_alcohol_s() { return alcohol_s; }
static float lua_num_get_water_pump_speed() { return water_pump_speed; }
static float lua_num_get_pressure_value() { return pressure_value; }
static float lua_num_get_PauseOn() { return PauseOn; }
static float lua_num_get_program_Wait() { return program_Wait; }
static float lua_num_get_YY() { return year(time(NULL)); }
static float lua_num_get_MM() { return month(time(NULL)); }
static float lua_num_get_DD() { return day(time(NULL)); }
static float lua_num_get_HH() { return hour(time(NULL)) + SamSetup.TimeZone; }
static float lua_num_get_MI() { return minute(time(NULL)); }
static float lua_num_get_SS() { return second(time(NULL)); }

static const LuaNumVariableDescriptor lua_num_variables[] = {
  {"WFpulseCount", lua_num_get_WFpulseCount, nullptr,
   LUA_VAR_RO, LUA_NUM_INTEGRAL, 0, UINT16_MAX},
  {"pump_started", lua_num_get_pump_started, nullptr,
   LUA_VAR_RO, LUA_NUM_INTEGRAL, 0, 1},
  {"valve_status", lua_num_get_valve_status, nullptr,
   LUA_VAR_RO, LUA_NUM_INTEGRAL, 0, 1},
  {"SamSetup_Mode", lua_num_get_SamSetup_Mode, nullptr,
   LUA_VAR_RO, LUA_NUM_INTEGRAL, 0, SAMOVAR_LUA_MODE},
  {"Samovar_Mode", lua_num_get_Samovar_Mode, nullptr,
   LUA_VAR_RO, LUA_NUM_INTEGRAL, 0, SAMOVAR_LUA_MODE},
  {"Samovar_CR_Mode", lua_num_get_Samovar_CR_Mode, nullptr,
   LUA_VAR_RO, LUA_NUM_INTEGRAL, 0, SAMOVAR_LUA_MODE},
  {"acceleration_temp", lua_num_get_acceleration_temp, lua_num_set_acceleration_temp,
   LUA_VAR_RW, LUA_NUM_INTEGRAL, 0, UINT16_MAX},
#ifdef USE_WATER_PUMP
  {"wp_count", lua_num_get_wp_count, lua_num_set_wp_count,
   LUA_VAR_RW, LUA_NUM_INTEGRAL, INT8_MIN, INT8_MAX},
  {"pmpKp", nullptr, lua_num_set_pmpKp,
   LUA_VAR_WO, LUA_NUM_FRACTIONAL, 0, 0},
  {"pmpKi", nullptr, lua_num_set_pmpKi,
   LUA_VAR_WO, LUA_NUM_FRACTIONAL, 0, 0},
  {"pmpKd", nullptr, lua_num_set_pmpKd,
   LUA_VAR_WO, LUA_NUM_FRACTIONAL, 0, 0},
#endif
  {"SteamTemp", lua_num_get_SteamTemp, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"boil_temp", lua_num_get_boil_temp, lua_num_set_boil_temp,
   LUA_VAR_RW, LUA_NUM_FRACTIONAL, 0, 0},
  {"PipeTemp", lua_num_get_PipeTemp, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"WaterTemp", lua_num_get_WaterTemp, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"TankTemp", lua_num_get_TankTemp, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"ACPTemp", lua_num_get_ACPTemp, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
#ifdef SAMOVAR_LUA_SIMULATION
  {"VirtualSteamTemp", lua_num_get_VirtualSteamTemp, lua_num_set_VirtualSteamTemp,
   LUA_VAR_RW, LUA_NUM_FRACTIONAL, 0, 0},
  {"VirtualPipeTemp", lua_num_get_VirtualPipeTemp, lua_num_set_VirtualPipeTemp,
   LUA_VAR_RW, LUA_NUM_FRACTIONAL, 0, 0},
  {"VirtualWaterTemp", lua_num_get_VirtualWaterTemp, lua_num_set_VirtualWaterTemp,
   LUA_VAR_RW, LUA_NUM_FRACTIONAL, 0, 0},
  {"VirtualTankTemp", lua_num_get_VirtualTankTemp, lua_num_set_VirtualTankTemp,
   LUA_VAR_RW, LUA_NUM_FRACTIONAL, 0, 0},
  {"VirtualACPTemp", lua_num_get_VirtualACPTemp, lua_num_set_VirtualACPTemp,
   LUA_VAR_RW, LUA_NUM_FRACTIONAL, 0, 0},
#endif
  {"loop_lua_fl", lua_num_get_loop_lua_fl, lua_num_set_loop_lua_fl,
   LUA_VAR_RW, LUA_NUM_INTEGRAL, 0, 1},
  {"SetScriptOff", lua_num_get_SetScriptOff, lua_num_set_SetScriptOff,
   LUA_VAR_RW, LUA_NUM_INTEGRAL, 0, 1},
  {"show_lua_script", lua_num_get_show_lua_script, lua_num_set_show_lua_script,
   LUA_VAR_RW, LUA_NUM_INTEGRAL, 0, 1},
  {"test_num_val", lua_num_get_test_num_val, lua_num_set_test_num_val,
   LUA_VAR_RW, LUA_NUM_FRACTIONAL, 0, 0},
  {"WFtotalMilliLitres", lua_num_get_WFtotalMilliLitres, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"WFflowRate", lua_num_get_WFflowRate, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"program_volume", lua_num_get_program_volume, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"program_speed", lua_num_get_program_speed, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"program_temp", lua_num_get_program_temp, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"program_power", lua_num_get_program_power, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"program_time", lua_num_get_program_time, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"program_capacity_num", lua_num_get_program_capacity_num, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"capacity_num", lua_num_get_capacity_num, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"target_power_volt", lua_num_get_target_power_volt, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"PowerOn", lua_num_get_PowerOn, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"alcohol", lua_num_get_alcohol, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"alcohol_s", lua_num_get_alcohol_s, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"water_pump_speed", lua_num_get_water_pump_speed, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"pressure_value", lua_num_get_pressure_value, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"PauseOn", lua_num_get_PauseOn, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"program_Wait", lua_num_get_program_Wait, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"YY", lua_num_get_YY, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"MM", lua_num_get_MM, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"DD", lua_num_get_DD, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"HH", lua_num_get_HH, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"MI", lua_num_get_MI, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
  {"SS", lua_num_get_SS, nullptr,
   LUA_VAR_RO, LUA_NUM_FRACTIONAL, 0, 0},
};

static const LuaNumVariableDescriptor* find_lua_num_variable(const char* name) {
  if (!name) return nullptr;
  for (size_t i = 0; i < sizeof(lua_num_variables) / sizeof(lua_num_variables[0]); i++) {
    if (strcmp(name, lua_num_variables[i].name) == 0) return &lua_num_variables[i];
  }
  return nullptr;
}

static int lua_numeric_error(
    lua_State* lua_state,
    const char* name,
    NumericParseError error) {
  return luaL_error(
      lua_state, "Invalid %s: %s", name, numeric_parse_error_code(error));
}

// [PKG-F] Две политики для числовых аргументов. Для ВЕЛИЧИН (магнитуд: ШИМ,
// скорость, время, напряжение/мощность) обновлённый luaL_checkinteger кидает
// "number has no integer representation" на нецелых float (напр.
// set_stepper_by_time(0,0,1.5) валил бы скрипт), тогда как старый код молча
// усекал. lua_check_truncated_arg принимает любое число и усекает к нулю
// (как (int)double), с клемпом против UB при |x|>LONG_MAX / NaN. Для
// ИНДЕКСОВ/СЕЛЕКТОРОВ (номер пина, канал, реле, направление и т.п.)
// действует обратная политика — см. lua_check_index_arg ниже: дробное
// значение это ошибка скрипта и должно быть показано, а не спрятано
// усечением.
static long lua_check_truncated_arg(lua_State* lua_state, int index) {
  // Точные целые (Lua-integer или float с целым значением) берём напрямую через
  // lua_tointegerx — без прогона через lua_Number. Иначе при LUA_32BITS (lua_Number =
  // float) целые >2^24 округляются (напр. 2147483647 -> 2147483648) и ломают диапазон.
  int isInteger = 0;
  const lua_Integer asInteger = lua_tointegerx(lua_state, index, &isInteger);
  if (isInteger) return static_cast<long>(asInteger);
  // Дробное число: принимаем и усекаем к нулю (поведение HEAD), с клемпом против UB
  // при |x|>LONG_MAX / NaN.
  const lua_Number rawValue = luaL_checknumber(lua_state, index);
  const double truncated = trunc(static_cast<double>(rawValue));
  if (!isfinite(truncated)) return 0;
  if (truncated <= static_cast<double>(LONG_MIN)) return LONG_MIN;
  if (truncated >= static_cast<double>(LONG_MAX)) return LONG_MAX;
  return static_cast<long>(truncated);
}

// [PKG-F] Проверяем диапазон float В DOUBLE до сужения: сужение double, чья
// величина превышает FLT_MAX, — формально UB (parse_finite_float проверяет
// величину в double по той же причине).
static NumericParseResult lua_narrow_to_float(lua_Number rawValue, float& out) {
  const double value = static_cast<double>(rawValue);
  if (!isfinite(value)) return numeric_parse_result(NUMERIC_PARSE_NOT_FINITE);
  const double magnitude = value < 0.0 ? -value : value;
  if (magnitude > static_cast<double>(FLT_MAX)) {
    return numeric_parse_result(NUMERIC_PARSE_OUT_OF_RANGE);
  }
  out = static_cast<float>(value);
  return numeric_parse_result(NUMERIC_PARSE_OK);
}

static int32_t lua_check_int32_arg(
    lua_State* lua_state,
    int index,
    int32_t minValue,
    int32_t maxValue,
    const char* name) {
  const long rawValue = lua_check_truncated_arg(lua_state, index);
  int32_t value = 0;
  const NumericParseResult result = checked_narrow_int32(
      static_cast<int64_t>(rawValue), minValue, maxValue, value);
  if (!result.ok()) lua_numeric_error(lua_state, name, result.error);
  return value;
}

// [PKG-F] Строгая проверка для индексов/селекторов: аргумент обязан быть
// точным целым (lua_tointegerx уже успешен и для Lua-float с целым
// значением). Дробный вход — ошибка скрипта (NUMERIC_PARSE_INVALID_FORMAT),
// а не молчаливое усечение, как в lua_check_int32_arg.
static int32_t lua_check_index_arg(
    lua_State* lua_state,
    int index,
    int32_t minValue,
    int32_t maxValue,
    const char* name) {
  int isInteger = 0;
  const lua_Integer asInteger = lua_tointegerx(lua_state, index, &isInteger);
  if (!isInteger) {
    luaL_checknumber(lua_state, index);  // not a number at all: standard Lua error
    lua_numeric_error(lua_state, name, NUMERIC_PARSE_INVALID_FORMAT);
  }
  int32_t value = 0;
  const NumericParseResult result = checked_narrow_int32(
      static_cast<int64_t>(asInteger), minValue, maxValue, value);
  if (!result.ok()) lua_numeric_error(lua_state, name, result.error);
  return value;
}

static float lua_check_finite_arg(
    lua_State* lua_state,
    int index,
    const char* name) {
  float value = 0.0f;
  const NumericParseResult result =
      lua_narrow_to_float(luaL_checknumber(lua_state, index), value);
  if (!result.ok()) lua_numeric_error(lua_state, name, result.error);
  return value;
}

struct LuaStrVariableDescriptor {
  const char* name;
  bool (*getter)(String& value);
  bool (*setter)(const String& value);
  uint8_t access;
  const char* busy_error;
};

static bool lua_str_get_Msg(String& value) { return copy_web_message_raw(value); }
static bool lua_str_get_SamovarStatus(String& value) {
  bool locked = runtime_state_lock(pdMS_TO_TICKS(50));
  if (!locked) return false;
  value = SamovarStatus;
  runtime_state_unlock(true);
  return true;
}
static bool lua_str_set_SamovarStatus(const String& value) {
  bool locked = runtime_state_lock(pdMS_TO_TICKS(50));
  if (!locked) return false;
  SamovarStatus = value;
  runtime_state_unlock(true);
  return true;
}
static bool lua_str_get_test_str_val(String& value) {
  value = test_str_val;
  return true;
}
static bool lua_str_set_test_str_val(const String& value) {
  test_str_val = value;
  return true;
}
static bool lua_str_get_program_type(String& value) {
  WProgram currentProgram;
  value = lua_copy_current_program(currentProgram) ? program_type_to_string(currentProgram.WType) : String();
  return true;
}

static const LuaStrVariableDescriptor lua_str_variables[] = {
  // [PKG-F] Msg: чтение (getter) продвигает приватный Lua-курсор по кольцу событий
  // (copy_web_message_raw отдаёт следующее непрочитанное сообщение или ""); запись
  // идёт спец-веткой `if (Var == "Msg")` в set_str_variable через append_web_message,
  // поэтому setter намеренно nullptr при доступе RW.
  {"Msg", lua_str_get_Msg, nullptr, LUA_VAR_RW, "Msg busy"},
  {"SamovarStatus", lua_str_get_SamovarStatus, lua_str_set_SamovarStatus, LUA_VAR_RW, "SamovarStatus busy"},
  {"test_str_val", lua_str_get_test_str_val, lua_str_set_test_str_val, LUA_VAR_RW, nullptr},
  {"program_type", lua_str_get_program_type, nullptr, LUA_VAR_RO, nullptr},
};

static const LuaStrVariableDescriptor* find_lua_str_variable(const String& name) {
  for (size_t i = 0; i < sizeof(lua_str_variables) / sizeof(lua_str_variables[0]); i++) {
    if (name == lua_str_variables[i].name) return &lua_str_variables[i];
  }
  return nullptr;
}

inline bool lua_pin_is_heater_channel(int pin) {
  return pin == RELE_CHANNEL1 || pin == RELE_CHANNEL4;
}


static int lua_wrapper_pinMode(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  int a = lua_check_truncated_arg(lua_state, 1);
  int b = lua_check_truncated_arg(lua_state, 2);
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  if (lua_simulation_enabled()) return lua_reject_actuator_mutation(lua_state);
  if (a == RELE_CHANNEL1 || a == RELE_CHANNEL4 || a == RELE_CHANNEL3 || a == RELE_CHANNEL2 || a == LUA_PIN) {
    if (lua_pin_is_heater_channel(a) && heater_safety_latched()) {
      // Защёлка взведена: pinMode(INPUT) отдал бы пин подтяжке платы в обход
      // защёлки, поэтому молча игнорируем; luaL_error оборвал бы весь чанк.
    } else {
      pinMode(a, b);
    }
  }
  return 0;
}

static int lua_wrapper_digitalWrite(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  int a = lua_check_truncated_arg(lua_state, 1);
  int b = lua_check_truncated_arg(lua_state, 2);
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  if (lua_simulation_enabled()) return lua_reject_actuator_mutation(lua_state);
  if (a == RELE_CHANNEL1 || a == WATER_PUMP_PIN || a == RELE_CHANNEL4 || a == RELE_CHANNEL3 || a == RELE_CHANNEL2 || a == LUA_PIN
#ifdef ALARM_BTN_PIN
      || a == ALARM_BTN_PIN
#endif
#ifdef BTN_PIN
      || a == BTN_PIN
#endif
     ) {
    // ВНИМАНИЕ: для RELE_CHANNEL2/3 здесь НАМЕРЕННО сырая запись на пин, без инверсии
    // по SamSetup.releN, в отличие от остального C++-тракта (ВКЛ = releN, ВЫКЛ = !releN).
    // Это не упущение: функция повторяет семантику одноимённого примитива Arduino, и все
    // существующие пользовательские скрипты написаны под сырой проход — они уже учитывают
    // полярность своей платы сами. Добавление инверсии молча перевернуло бы миксер и
    // клапан у всех на конфигурации по умолчанию (releN=false), поэтому поведение
    // зафиксировано тестом. Полярность-зависимое управление реле — это отдельная новая
    // функция, а не смена смысла digitalWrite.
    if (lua_pin_is_heater_channel(a) && heater_safety_latched()) {
      // Защёлка аварийного отключения нагрева взведена. C++-тракт уже погасил эти
      // каналы и сам их не подаст, пока защёлка не снята. Lua пишет сырым значением
      // мимо releN-инверсии, поэтому по b нельзя отличить "включить" от "выключить";
      // запись игнорируется молча — luaL_error убил бы весь чанк (общий lua_pcall).
      // [П3] C++-тракт уже физически погасил канал - снимаем и наш учёт "поднят".
      lua_set_heater_channel_raised(a, false);
    } else if (a != WATER_PUMP_PIN) {
      digitalWrite(a, b);
      if (lua_pin_is_heater_channel(a)) lua_track_heater_channel_write(a, b);
    } else {
#ifdef USE_WATER_PUMP
      if (b == LOW) {
        water_pump_speed = 0;
        pump_pwm.write(0);
      } else {
        water_pump_speed = 1023;
        pump_pwm.write(1023);
      }
#else
      digitalWrite(a, b);
#endif
    }
  }
  return 0;
}

static int lua_wrapper_digitalRead(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  int a = lua_check_truncated_arg(lua_state, 1);
  lua_pushnumber(lua_state, (lua_Number)digitalRead(a));
  return 1;
}

static int lua_wrapper_analogRead(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  lua_pushnumber(lua_state, (lua_Number)analogRead(LUA_PIN));
  return 1;
}

#ifdef USE_EXPANDER
static int lua_wrapper_exp_pinMode(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  const int32_t pin = lua_check_index_arg(lua_state, 1, 0, 15, "pin");
  const int32_t mode = lua_check_index_arg(
      lua_state, 2, INT32_MIN, INT32_MAX, "mode");
  if (mode != INPUT && mode != OUTPUT && mode != INPUT_PULLUP) {
    return lua_numeric_error(lua_state, "mode", NUMERIC_PARSE_NOT_ALLOWED);
  }
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  if (lua_simulation_enabled()) return lua_reject_actuator_mutation(lua_state);
  if (xSemaphoreTake(
          xI2CSemaphore,
          static_cast<TickType_t>(EXPANDER_UPDATE_TIMEOUT / portTICK_RATE_MS)) !=
      pdTRUE) {
    return luaL_error(lua_state, "I2C expander write timeout");
  }
  expander.pinMode(static_cast<uint8_t>(pin), static_cast<uint8_t>(mode));
  xSemaphoreGive(xI2CSemaphore);
  return 0;
}

static int lua_wrapper_exp_digitalWrite(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  const int32_t pin = lua_check_index_arg(lua_state, 1, 0, 15, "pin");
  const int32_t value = lua_check_index_arg(
      lua_state, 2, INT32_MIN, INT32_MAX, "value");
  if (value != LOW && value != HIGH) {
    return lua_numeric_error(lua_state, "value", NUMERIC_PARSE_NOT_ALLOWED);
  }
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  if (lua_simulation_enabled()) return lua_reject_actuator_mutation(lua_state);
  if (xSemaphoreTake(
          xI2CSemaphore,
          static_cast<TickType_t>(EXPANDER_UPDATE_TIMEOUT / portTICK_RATE_MS)) !=
      pdTRUE) {
    return luaL_error(lua_state, "I2C expander write timeout");
  }
  const bool writeOk = expander.digitalWrite(
      static_cast<uint8_t>(pin), static_cast<uint8_t>(value));
  xSemaphoreGive(xI2CSemaphore);
  if (!writeOk) return luaL_error(lua_state, "I2C expander write failed");
  return 0;
}

static int lua_wrapper_exp_digitalRead(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  const int32_t pin = lua_check_index_arg(lua_state, 1, 0, 15, "pin");
  if (xSemaphoreTake(
          xI2CSemaphore,
          static_cast<TickType_t>(EXPANDER_UPDATE_TIMEOUT / portTICK_RATE_MS)) !=
      pdTRUE) {
    return luaL_error(lua_state, "I2C expander read timeout");
  }
  const uint8_t value = expander.digitalRead(static_cast<uint8_t>(pin));
  xSemaphoreGive(xI2CSemaphore);
  lua_pushnumber(lua_state, static_cast<lua_Number>(value));
  return 1;
}
#endif

#ifdef USE_ANALOG_EXPANDER
static int lua_wrapper_exp_analogWrite(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  const int32_t value = lua_check_int32_arg(
      lua_state, 1, 0, UINT8_MAX, "value");
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  if (lua_simulation_enabled()) return lua_reject_actuator_mutation(lua_state);
  if (xSemaphoreTake(
          xI2CSemaphore,
          static_cast<TickType_t>(EXPANDER_UPDATE_TIMEOUT / portTICK_RATE_MS)) !=
      pdTRUE) {
    return luaL_error(lua_state, "I2C analog expander write timeout");
  }
  analog_expander.analogWrite(static_cast<uint8_t>(value));
  xSemaphoreGive(xI2CSemaphore);
  return 0;
}

static int lua_wrapper_exp_analogRead(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  const int32_t channel = lua_check_index_arg(
      lua_state, 1, 0, 3, "channel");
  if (xSemaphoreTake(
          xI2CSemaphore,
          static_cast<TickType_t>(EXPANDER_UPDATE_TIMEOUT / portTICK_RATE_MS)) !=
      pdTRUE) {
    return luaL_error(lua_state, "I2C analog expander read timeout");
  }
  const uint8_t value = analog_expander.analogRead(
      static_cast<uint8_t>(channel));
  xSemaphoreGive(xI2CSemaphore);
  lua_pushnumber(lua_state, static_cast<lua_Number>(value));
  return 1;
}
#endif

static int lua_wrapper_delay(lua_State *lua_state) {
  const int32_t a = lua_check_index_arg(lua_state, 1, 0, 1000, "delay");
#ifdef SAMOVAR_LUA_SIMULATION
  luaSimulationMillis += static_cast<uint32_t>(a);
#else
  vTaskDelay(a / portTICK_PERIOD_MS);
#endif
  return 0;
}

static int lua_wrapper_millis(lua_State *lua_state) {
#ifdef SAMOVAR_LUA_SIMULATION
  lua_pushnumber(lua_state, static_cast<lua_Number>(luaSimulationMillis));
#else
  lua_pushnumber(lua_state, (lua_Number)millis());
#endif
  return 1;
}

static int lua_wrapper_set_pause_withdrawal(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  int a = lua_check_truncated_arg(lua_state, 1);
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  if (lua_simulation_enabled()) return lua_reject_actuator_mutation(lua_state);
  pause_withdrawal(a);
  return 0;
}

static int lua_wrapper_set_power(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  int a = lua_check_truncated_arg(lua_state, 1);
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  if (lua_simulation_enabled()) return lua_reject_actuator_mutation(lua_state);
  SamovarCommands command = SAMOVAR_NONE;

  if (a && !PowerOn) {
    command = mode_power_on_command(Samovar_Mode);
  } else if (!a && PowerOn)
    command = SAMOVAR_POWER;

  if (command != SAMOVAR_NONE) {
    if (!queue_samovar_command(command, pdMS_TO_TICKS(100))) {
      return luaL_error(lua_state, "Samovar command queue busy");
    }
  }

  return 0;
}

static int lua_wrapper_set_mixer(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  int a = lua_check_truncated_arg(lua_state, 1);
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  if (lua_simulation_enabled()) return lua_reject_actuator_mutation(lua_state);
  const ActuatorCommandResult result = set_mixer(a);
  lua_pushnumber(lua_state, static_cast<lua_Number>(result));
  return 1;
}

static int lua_wrapper_open_valve(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  bool a = lua_check_truncated_arg(lua_state, 1);
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  if (lua_simulation_enabled()) return lua_reject_actuator_mutation(lua_state);
  const ActuatorCommandResult result = open_valve(a, false);
  lua_pushnumber(lua_state, static_cast<lua_Number>(result));
  return 1;
}

#ifdef SAMOVAR_USE_POWER
static int lua_wrapper_set_current_power(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  float a = lua_check_finite_arg(lua_state, 1, "power");
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  if (lua_simulation_enabled()) return lua_reject_actuator_mutation(lua_state);
#ifdef SAMOVAR_USE_SEM_AVR
  a = roundf(a);  // регулятор SEM/AVR: уставка в ваттах
#else
  a = roundf(a * 10.0f) / 10.0f;  // регулятор по напряжению: один знак после запятой
#endif
  const ActuatorCommandResult result = set_current_power(a);
  lua_pushnumber(lua_state, static_cast<lua_Number>(result));
  return 1;
}
#endif

static int lua_wrapper_set_alarm(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  if (lua_simulation_enabled()) return lua_reject_actuator_mutation(lua_state);
  set_alarm();
  return 0;
}

static int lua_wrapper_set_body_temp(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  if (lua_simulation_enabled()) return lua_reject_actuator_mutation(lua_state);
  set_body_temp();
  return 0;
}

static int lua_wrapper_set_next_program(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  if (lua_simulation_enabled()) return lua_reject_actuator_mutation(lua_state);
  if (!PowerOn) return 0;
  SamovarCommands command = mode_start_command(Samovar_Mode);
  if (command != SAMOVAR_NONE) {
    if (!queue_samovar_command(command, pdMS_TO_TICKS(100))) {
      return luaL_error(lua_state, "Samovar command queue busy");
    }
  }
  return 0;
}

static int lua_wrapper_get_state(lua_State *lua_state) {
  lua_pushnumber(lua_state, (lua_Number)SamovarStatusInt);
  return 1;
}

static int lua_wrapper_send_msg(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  int a = lua_check_truncated_arg(lua_state, 2);
  String st = lua_to_string_arg(lua_state, 1);
  if (a == -1) {
    WriteConsoleLog(st);
  } else {
    SendMsg(st, (MESSAGE_TYPE)a);
  }
  return 0;
}

static int lua_wrapper_set_num_variable(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  const char* variableName = luaL_checkstring(lua_state, 1);
  const LuaNumVariableDescriptor* descriptor =
      find_lua_num_variable(variableName);
  if (descriptor && (descriptor->access & LUA_VAR_WRITE) && descriptor->setter) {
    int32_t integerValue = 0;
    float fractionalValue = 0.0f;
    NumericParseResult result = numeric_parse_result(NUMERIC_PARSE_OK);
    if (descriptor->domain == LUA_NUM_INTEGRAL) {
      const lua_Integer rawValue = luaL_checkinteger(lua_state, 2);
      result = checked_narrow_int32(
          static_cast<int64_t>(rawValue), descriptor->minValue,
          descriptor->maxValue, integerValue);
    } else {
      // [PKG-F] Проверяем диапазон float в double ДО сужения (иначе UB при |x|>FLT_MAX).
      result = lua_narrow_to_float(luaL_checknumber(lua_state, 2), fractionalValue);
    }
    if (!result.ok()) {
      return lua_numeric_error(lua_state, variableName, result.error);
    }
    if (!descriptor->setter(integerValue, fractionalValue)) {
      return luaL_error(lua_state, "%s busy", variableName);
    }
  } else if (descriptor) {
    return luaL_error(lua_state, "%s is read-only", variableName);
  } else {
    const lua_Number value = luaL_checknumber(lua_state, 2);
    if (variableName[0] != '\0') {
      WriteConsoleLog(
          "UNDEF NUMERIC LUA VAR " + String(variableName) + " = " +
          String(static_cast<float>(value)));
    }
  }
  return 0;
}

static int lua_wrapper_get_num_variable(lua_State *lua_state) {
  float a = 0;
  String Var = lua_to_string_arg(lua_state, 1);
  const LuaNumVariableDescriptor* descriptor = find_lua_num_variable(Var.c_str());
  if (descriptor && (descriptor->access & LUA_VAR_READ) && descriptor->getter) {
    a = descriptor->getter();
  } else if (Var.length() > 0) {
    WriteConsoleLog("GET UNDEF NUMERIC LUA VAR " + Var);
  }
  lua_pushnumber(lua_state, (lua_Number)a);
  return 1;
}

static int lua_wrapper_set_str_variable(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  const char* errorMessage = nullptr;
  {
    String Var = lua_to_string_arg(lua_state, 1);
    String Val = lua_to_string_arg(lua_state, 2);
    if (Var == "Msg") {
      const RuntimeEventPublishResult result = append_web_message(Val, NOTIFY_MSG);
      if (result == RUNTIME_EVENT_PUBLISH_OK || result == RUNTIME_EVENT_PUBLISH_EMPTY) return 0;
      if (result == RUNTIME_EVENT_PUBLISH_LOCK_BUSY) errorMessage = "Msg busy";
      else if (result == RUNTIME_EVENT_PUBLISH_TEXT_TOO_LONG) errorMessage = "Msg too long";
      else errorMessage = "Msg event store corrupt";
    } else {
      const LuaStrVariableDescriptor* descriptor = find_lua_str_variable(Var);
      if (descriptor && (descriptor->access & LUA_VAR_WRITE) && descriptor->setter) {
        if (!descriptor->setter(Val)) errorMessage = descriptor->busy_error ? descriptor->busy_error : "Lua string variable busy";
      } else if (descriptor) {
        WriteConsoleLog("WARNING! " + Var + " is read only property");
      } else if (Var.length() > 0) {
        WriteConsoleLog("UNDEF STRING LUA VAR " + Var + " = " + Val);
      }
    }
  }
  if (errorMessage) return luaL_error(lua_state, "%s", errorMessage);
  return 0;
}

static int lua_wrapper_set_object(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  // [П26] luaL_error - longjmp мимо деструкторов живых String (см. П25 у
  // lua_wrapper_get/set_str_variable) - прячем Var/Val во вложенный блок и
  // зовём luaL_error только после его закрытия.
  bool limitExceeded = false;
  {
    String Var = lua_to_string_arg(lua_state, 1);
    String Val = lua_to_string_arg(lua_state, 2);
    // Обновление уже существующего ключа лимит не расходует - has() отличает
    // "ключа нет" от "значение пустая строка", чего get() не умеет.
    if (luaObj->has(Var) || luaObj->size() < LUA_OBJECT_STORE_MAX_KEYS) {
      luaObj->put(Var, Val);
    } else {
      limitExceeded = true;
    }
  }
  if (limitExceeded) {
    return luaL_error(lua_state, "setObject: key limit reached (%d)", (int)LUA_OBJECT_STORE_MAX_KEYS);
  }
  return 0;
}

static int lua_wrapper_get_object(lua_State *lua_state) {
  String Var, Type;
  int n = lua_gettop(lua_state); /* number of arguments */
  Var = lua_to_string_arg(lua_state, 1);

  String v = luaObj->get(Var);
  if (n == 2) {
    Type = lua_to_string_arg(lua_state, 2);
    if (Type == "NUMERIC" && v.length() == 0) {
      v = "0";
    }
  }

  lua_pushstring(lua_state, v.c_str());
  return 1;
}

static int lua_wrapper_set_lua_status(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  bool statusSet = false;
  {
    String Var = lua_to_string_arg(lua_state, 1);
    statusSet = set_lua_status_value(Var);
  }
  if (!statusSet) return luaL_error(lua_state, "Lua_status busy");
  return 0;
}

static int lua_wrapper_set_capacity(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  int a = luaL_checkinteger(lua_state, 1);
  if (a < 0 || a > CAPACITY_NUM) return luaL_error(lua_state, "capacity out of range");
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  if (lua_simulation_enabled()) return lua_reject_actuator_mutation(lua_state);
  set_capacity((uint8_t)a);
  return 0;
}

#ifdef USE_WATER_PUMP
static int lua_wrapper_set_pump_pwm(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  // [PKG-F] Ограничиваем ШИМ насоса 0..1023 (10-битный pump_pwm, constrain(0,1023)
  // в pumppwm.h; water_pump_speed тоже 0..1023). Float-вход усекается до целого.
  const int32_t duty = lua_check_int32_arg(lua_state, 1, 0, 1023, "pwm");
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  if (lua_simulation_enabled()) return lua_reject_actuator_mutation(lua_state);
  const ActuatorCommandResult result = set_pump_pwm(duty);
  lua_pushnumber(lua_state, static_cast<lua_Number>(result));
  return 1;
}
#endif

static int lua_wrapper_set_timer(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  // [П28] luaL_checknumber(...) в uint8_t усекал номер таймера ПО МОДУЛЮ 256 ДО
  // проверки диапазона (setTimer(266,...) тихо писал в lua_timer[9]).
  // lua_check_index_arg проверяет диапазон ДО усечения, как и в остальных
  // 15 обёртках-селекторах этого файла.
  int32_t a = lua_check_index_arg(lua_state, 1, 1, 10, "timer");
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  a--;
  uint16_t b = luaL_checknumber(lua_state, 2);
  lua_timer[a] = millis() + b * 1000;
  return 0;
}

static int lua_wrapper_get_timer(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  // [П28] см. lua_wrapper_set_timer - тот же сдвиг проверки диапазона раньше усечения.
  int32_t a = lua_check_index_arg(lua_state, 1, 1, 10, "timer") - 1;
  uint16_t b;
  if (lua_timer[a] == 0) b = 0;
  else {
    long l;
    l = lua_timer[a] - millis();
    if (l <= 0) {
      b = 0;
      lua_timer[a] = 0;
    } else b = l / 1000;
  }
  lua_pushnumber(lua_state, (lua_Number)b);
  return 1;
}

static int lua_wrapper_get_str_variable(lua_State *lua_state) {
  // [П25] luaL_error - это longjmp: если он вызван, пока String c/Var ещё живы
  // в этом кадре стека, их деструкторы не выполнятся (утечка). Как и в
  // lua_wrapper_set_str_variable/lua_wrapper_set_lua_status, прячем String во
  // вложенный блок и зовём luaL_error только после его закрытия.
  const char* errorMessage = nullptr;
  int pushCount = 0;
  {
    String c;
    String Var = lua_to_string_arg(lua_state, 1);
    const LuaStrVariableDescriptor* descriptor = find_lua_str_variable(Var);
    if (descriptor && (descriptor->access & LUA_VAR_READ) && descriptor->getter) {
      if (!descriptor->getter(c)) {
        errorMessage = descriptor->busy_error ? descriptor->busy_error : "Lua string variable busy";
      } else {
        lua_pushstring(lua_state, c.c_str());
        pushCount = 1;
      }
    } else if (Var.length() > 0) {
      WriteConsoleLog("UNDEF GET STRING LUA VAR " + Var);
    } else {
      lua_pushstring(lua_state, c.c_str());
      pushCount = 1;
    }
  }
  if (errorMessage) return luaL_error(lua_state, "%s", errorMessage);
  return pushCount;
}

static int lua_wrapper_http_request(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  int n = lua_gettop(lua_state); /* number of arguments */
  if (n != 1 && n != 4) {
    lua_pushstring(lua_state, "error");
    return 1;
  }

  String Var = lua_to_string_arg(lua_state, 1);
  String payload;

  // Запрос выполняется на общем долгоживущем объекте (http_sync_request_custom).
  // Прежний локальный asyncHTTPrequest уничтожался сразу после abort(), а колбэк lwIP
  // приходил уже в освобождённую память — это и была паника при пропаже интернета.
  if (n == 1) {  // GET(url)
    payload = http_sync_request_custom("GET", Var, "", "");
  } else {
    String RequestType = lua_to_string_arg(lua_state, 2);
    String ContentType = lua_to_string_arg(lua_state, 3);
    String Body = lua_to_string_arg(lua_state, 4);
    payload = http_sync_request_custom(RequestType, Var, Body, ContentType);
  }
  if (payload == "<ERR>") payload = "error";

  lua_pushstring(lua_state, payload.c_str());

  return 1;
}

static int lua_wrapper_set_stepper_by_time(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  const int32_t speed = lua_check_int32_arg(
      lua_state, 1, 0, UINT16_MAX, "speed");
  const int32_t direction = lua_check_index_arg(
      lua_state, 2, 0, 1, "direction");
  const int32_t seconds = lua_check_int32_arg(
      lua_state, 3, 0, UINT16_MAX, "time");
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  if (lua_simulation_enabled()) return lua_reject_actuator_mutation(lua_state);
  const bool started = set_stepper_by_time(
      static_cast<uint16_t>(speed), static_cast<uint8_t>(direction),
      static_cast<uint16_t>(seconds));
  lua_pushnumber(lua_state, static_cast<lua_Number>(started));
  return 1;
}

static int lua_wrapper_set_stepper_target(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  const int32_t speed = lua_check_int32_arg(
      lua_state, 1, 0, UINT16_MAX, "speed");
  const int32_t direction = lua_check_index_arg(
      lua_state, 2, 0, 1, "direction");
  const int32_t target = lua_check_int32_arg(
      lua_state, 3, 0, INT32_MAX, "target");
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  if (lua_simulation_enabled()) return lua_reject_actuator_mutation(lua_state);
  const bool started = set_stepper_target(
      static_cast<uint16_t>(speed), static_cast<uint8_t>(direction),
      static_cast<uint32_t>(target));
  lua_pushnumber(lua_state, static_cast<lua_Number>(started));
  return 1;
}

static int lua_wrapper_get_stepper_status(lua_State *lua_state) {
  lua_pushnumber(lua_state, (lua_Number)get_stepper_status());
  return 1;
}

static int lua_wrapper_i2cpump_start(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  // Плохие ЧИСЛА (NaN/Inf/<=0) - молчаливый возврат 0, без luaL_error: lua_pcall в
  // проекте один (lua.h:77) и оборачивает весь чанк пользователя целиком, поэтому
  // ошибка тут убивала бы весь скрипт из-за одного вызова насоса. Раньше
  // luaL_checknumber пропускал NaN/Inf дальше, NaN<=0 давало false, и мусор уходил
  // в расчёт. На аргументе, который вообще не число, luaL_checknumber по-прежнему
  // валит чанк - так во всех обёртках этого файла, это общая конвенция, а не
  // недосмотр. Проверка железа стоит первой в условии, как раньше.
  const lua_Number rawRate = luaL_checknumber(lua_state, 1);
  const lua_Number rawVolume = luaL_checknumber(lua_state, 2);
  float speedRate = 0.0f;
  float volumeMl = 0.0f;
  const bool rateFinite = lua_narrow_to_float(rawRate, speedRate).ok();
  const bool volumeFinite = lua_narrow_to_float(rawVolume, volumeMl).ok();
  if (use_I2C_dev != 2 || !rateFinite || !volumeFinite || speedRate <= 0.0f || volumeMl <= 0.0f) {
    lua_pushnumber(lua_state, 0);
    return 1;
  }
  const uint16_t stepsPerMl = SamSetup.StepperStepMlI2C > 0
      ? SamSetup.StepperStepMlI2C
      : I2C_STEPPER_STEP_ML_DEFAULT;
  uint32_t targetSteps = 0;
  const NumericParseResult targetResult = checked_truncating_product_u32(
      static_cast<double>(volumeMl), static_cast<double>(stepsPerMl),
      targetSteps);
  if (!targetResult.ok()) {
    lua_pushnumber(lua_state, 0);
    return 1;
  }
  const float speedValue = i2c_get_speed_from_rate(speedRate);
  const NumericParseResult speedResult = validate_bounded_finite_float(
      speedValue, 1.0f, static_cast<float>(UINT16_MAX));
  if (!speedResult.ok()) {
    lua_pushnumber(lua_state, 0);
    return 1;
  }
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  if (lua_simulation_enabled()) return lua_reject_actuator_mutation(lua_state);
  const uint16_t speedSteps = static_cast<uint16_t>(speedValue);
  I2CPumpCmdSpeed = speedSteps;
  I2CPumpTargetSteps = targetSteps;
  I2CPumpTargetMl = volumeMl;
  const bool started = set_stepper_target(speedSteps, 0, targetSteps);
  lua_pushnumber(lua_state, static_cast<lua_Number>(started));
  return 1;
}

static int lua_wrapper_i2cpump_stop(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  if (use_I2C_dev != 2) {
    lua_pushnumber(lua_state, 0);
    return 1;
  }
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  if (lua_simulation_enabled()) return lua_reject_actuator_mutation(lua_state);
  const bool stopped = set_stepper_target(0, 0, 0);
  I2CPumpTargetSteps = 0;
  I2CPumpTargetMl = 0;
  I2CPumpCmdSpeed = 0;
  lua_pushnumber(lua_state, static_cast<lua_Number>(stopped));
  return 1;
}

static int lua_wrapper_i2cpump_get_speed(lua_State *lua_state) {
  if (use_I2C_dev != 2) {
    lua_pushnumber(lua_state, 0);
    return 1;
  }
  lua_pushnumber(lua_state, (lua_Number)get_stepper_speed());
  return 1;
}

static int lua_wrapper_i2cpump_get_target_ml(lua_State *lua_state) {
  if (use_I2C_dev != 2) {
    lua_pushnumber(lua_state, 0);
    return 1;
  }
  lua_pushnumber(lua_state, (lua_Number)I2CPumpTargetMl);
  return 1;
}

static int lua_wrapper_i2cpump_get_remaining_ml(lua_State *lua_state) {
  if (use_I2C_dev != 2) {
    lua_pushnumber(lua_state, 0);
    return 1;
  }
  uint32_t remaining = get_stepper_status();
  float remainingMl = i2c_get_liquid_volume_by_step(remaining);
  lua_pushnumber(lua_state, (lua_Number)remainingMl);
  return 1;
}

static int lua_wrapper_i2cpump_get_running(lua_State *lua_state) {
  if (use_I2C_dev != 2) {
    lua_pushnumber(lua_state, 0);
    return 1;
  }
  uint32_t remaining = get_stepper_status();
  lua_pushnumber(lua_state, (lua_Number)((get_stepper_speed() > 0 && remaining > 0) ? 1 : 0));
  return 1;
}

static int lua_wrapper_set_mixer_pump_target(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  const int32_t target = lua_check_index_arg(
      lua_state, 1, 0, 1, "target");
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  if (lua_simulation_enabled()) return lua_reject_actuator_mutation(lua_state);
  const bool started = set_mixer_pump_target(static_cast<uint8_t>(target));
  lua_pushnumber(lua_state, static_cast<lua_Number>(started));
  return 1;
}

static int lua_wrapper_get_mixer_pump_status(lua_State *lua_state) {
  lua_pushnumber(lua_state, (lua_Number)get_mixer_pump_status());
  return 1;
}

static int lua_wrapper_check_I2C_device(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  uint8_t a = lua_check_truncated_arg(lua_state, 1);
  lua_pushnumber(lua_state, (lua_Number)check_I2C_device(a));
  return 1;
}

static int lua_wrapper_set_i2c_rele_state(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  const int32_t relay = lua_check_index_arg(
      lua_state, 1, 1, 4, "relay");
  const int32_t state = lua_check_index_arg(
      lua_state, 2, 0, 1, "state");
  if (!lua_state_mutation_allowed()) return lua_reject_state_mutation(lua_state);
  if (lua_simulation_enabled()) return lua_reject_actuator_mutation(lua_state);
  const bool changed = set_i2c_rele_state(
      static_cast<uint8_t>(relay), state != 0);
  lua_pushnumber(lua_state, static_cast<lua_Number>(changed));
  return 1;
}

static int lua_wrapper_get_i2c_rele_state(lua_State *lua_state) {
  vTaskDelay(5 / portTICK_PERIOD_MS);
  const int32_t relay = lua_check_index_arg(
      lua_state, 1, 1, 4, "relay");
  lua_pushnumber(
      lua_state,
      static_cast<lua_Number>(get_i2c_rele_state(static_cast<uint8_t>(relay))));
  return 1;
}

void lua_init() {
  lua_runtime_ready = false;
  lua_coroutine_watchdog_ready = false;
  lua_boot_init_ready = false;
  lua.Lua_register("pinMode", &lua_wrapper_pinMode);
  lua.Lua_register("digitalWrite", &lua_wrapper_digitalWrite);
  lua.Lua_register("digitalRead", &lua_wrapper_digitalRead);
  lua.Lua_register("analogRead", &lua_wrapper_analogRead);
#ifdef USE_EXPANDER
  lua.Lua_register("exp_pinMode", &lua_wrapper_exp_pinMode);
  lua.Lua_register("exp_digitalWrite", &lua_wrapper_exp_digitalWrite);
  lua.Lua_register("exp_digitalRead", &lua_wrapper_exp_digitalRead);
#endif
#ifdef USE_ANALOG_EXPANDER
  lua.Lua_register("exp_analogWrite", &lua_wrapper_exp_analogWrite);
  lua.Lua_register("exp_analogRead", &lua_wrapper_exp_analogRead);
#endif
  lua.Lua_register("delay", &lua_wrapper_delay);
  lua.Lua_register("millis", &lua_wrapper_millis);
  lua.Lua_register("sendMsg", &lua_wrapper_send_msg);

  lua.Lua_register("setPower", &lua_wrapper_set_power);
  lua.Lua_register("setBodyTemp", &lua_wrapper_set_body_temp);
  lua.Lua_register("setAlarm", &lua_wrapper_set_alarm);
  lua.Lua_register("setNumVariable", &lua_wrapper_set_num_variable);
  lua.Lua_register("setStrVariable", &lua_wrapper_set_str_variable);
  lua.Lua_register("setObject", &lua_wrapper_set_object);
  lua.Lua_register("setLuaStatus", &lua_wrapper_set_lua_status);
#ifdef USE_WATER_PUMP
  lua.Lua_register("setPumpPwm", &lua_wrapper_set_pump_pwm);
#endif
#ifdef SAMOVAR_USE_POWER
  lua.Lua_register("setCurrentPower", &lua_wrapper_set_current_power);
#endif
  lua.Lua_register("setMixer", &lua_wrapper_set_mixer);
  lua.Lua_register("setNextProgram", &lua_wrapper_set_next_program);
  lua.Lua_register("setPauseWithdrawal", &lua_wrapper_set_pause_withdrawal);
  lua.Lua_register("setTimer", &lua_wrapper_set_timer);
  lua.Lua_register("setCapacity", &lua_wrapper_set_capacity);

  lua.Lua_register("openValve", &lua_wrapper_open_valve);

  lua.Lua_register("getNumVariable", &lua_wrapper_get_num_variable);
  lua.Lua_register("getStrVariable", &lua_wrapper_get_str_variable);
  lua.Lua_register("getState", &lua_wrapper_get_state);
  lua.Lua_register("getObject", &lua_wrapper_get_object);
  lua.Lua_register("getTimer", &lua_wrapper_get_timer);
  lua.Lua_register("http_request", &lua_wrapper_http_request);

  lua.Lua_register("check_I2C_device", &lua_wrapper_check_I2C_device);
  lua.Lua_register("set_stepper_by_time", &lua_wrapper_set_stepper_by_time);
  lua.Lua_register("set_stepper_target", &lua_wrapper_set_stepper_target);
  lua.Lua_register("get_stepper_status", &lua_wrapper_get_stepper_status);
  lua.Lua_register("i2cpump_start", &lua_wrapper_i2cpump_start);
  lua.Lua_register("i2cpump_stop", &lua_wrapper_i2cpump_stop);
  lua.Lua_register("i2cpump_get_speed", &lua_wrapper_i2cpump_get_speed);
  lua.Lua_register("i2cpump_get_target_ml", &lua_wrapper_i2cpump_get_target_ml);
  lua.Lua_register("i2cpump_get_remaining_ml", &lua_wrapper_i2cpump_get_remaining_ml);
  lua.Lua_register("i2cpump_get_running", &lua_wrapper_i2cpump_get_running);
  lua.Lua_register("set_mixer_pump_target", &lua_wrapper_set_mixer_pump_target);
  lua.Lua_register("get_mixer_pump_status", &lua_wrapper_get_mixer_pump_status);

  lua.Lua_register("get_i2c_rele_state", &lua_wrapper_get_i2c_rele_state);
  lua.Lua_register("set_i2c_rele_state", &lua_wrapper_set_i2c_rele_state);

  loop_lua_fl = 0;
  SetScriptOff = false;

  // 1. Уменьшим размер стека для lua скриптов
  lua_State* L = lua.GetState();
  lua_gc(L, LUA_GCSETPAUSE, 120); // Увеличим паузу между сборками мусора
  lua_gc(L, LUA_GCSETSTEPMUL, 200); // Увеличим агрессивность сборки
  lua_install_constants_locked();
  const bool watchdogReady = lua_install_coroutine_watchdog_locked();
  lua_coroutine_watchdog_ready = watchdogReady;
  if (!watchdogReady) {
    WriteConsoleLog("Lua coroutine watchdog init failed: " + lua_coroutine_watchdog_error);
    lua_runtime_ready = false;
  }

  //Запускаем инициализирующий lua-скрипт
  File f = SPIFFS.open("/init.lua");
  bool initOk = true;
  if (f) {
    //нашли файл со скриптом, выполняем
    String script;
    script = get_global_variables();
    script += f.readString();
    f.close();
    if (show_lua_script) {
      WriteConsoleLog(F("--BEGIN LUA SCRIPT--"));
      WriteConsoleLog(script);
      WriteConsoleLog(F("--END LUA SCRIPT--"));
    }
    String sr = lua_exec(script);
    if (sr.length() > 0) {
      initOk = false;
      WriteConsoleLog("INI ERR " + sr);
    }
  }
  lua_type_script = get_lua_mode_name();
  lua_finished = true;
  lua_boot_init_ready = initOk && watchdogReady;

  load_lua_script();

  //Запускаем таск для запуска скрипта
  xTaskCreatePinnedToCore(
    do_lua_script,    /* Function to implement the task */
    "do_lua_script",  /* Name of the task */
    8192,             /* Stack size in bytes (в ESP-IDF это байты, а не слова) */
    NULL,             /* Task input parameter */
    1,                /* Priority of the task */
    &DoLuaScriptTask, /* Task handle. */
    1);               /* Core where the task should run */
}

String get_lua_script_list() {
  String s, fn;
  uint8_t i = 1;
  File root = SPIFFS.open("/");
  File file = root.openNextFile();
  while (file) {
    if (!file.isDirectory()) {
      fn = file.name();
      if (fn.substring(0, 4) == "btn_" && getValue(fn, '_', 1) == get_lua_mode_name(false)) {
        String str;
        s = s + fn;
        if (fn[0] != '/') fn = "/" + fn;
        File f = SPIFFS.open(fn);
        str = f.readStringUntil('^');
        str = getValue(str, '|', 1);
        if (str.length() == 0) str = "LUA" + (String)i;
        i++;
        s = s + "|" + str + ",";
      }
    }
    file = root.openNextFile();
  }
  s = s.substring(0, s.length() - 1);
  return s;
}

String get_lua_script(String fn) {
  String s = "";
  File f;
  if (fn[0] != '/') fn = "/" + fn;
  f = SPIFFS.open(fn);
  if (f) {
    //нашли файл со скриптом, загружаем
    s = f.readString();
    s.trim();
    f.close();
  }
  return s;
}

bool run_lua_script(String fn) {
  String s = get_lua_script(fn);
  if (s.length() > 0) s = get_global_variables() + s;
  if (!queue_lua_script_job(s)) {
    WriteConsoleLog(F("Lua busy"));
    return false;
  }
  return true;
}

String run_lua_string(String lstr) {
  String sr = "";
  if (lstr.length() > 0) {
#ifdef USE_MQTT
    String MsgPl = lstr;
    MsgPl.replace(",", ";");
    MqttSendMsg(MsgPl + "," + NOTIFY_MSG, "msg");
#endif
    if (!queue_lua_inline_job(lstr)) {
      sr = "Lua busy";
      WriteConsoleLog(sr);
    } else {
      WriteConsoleLog(F("Lua queued"));
    }
  }
  return sr;
}

void load_lua_script() {
  // [П30] Отредактированный/перезагруженный скрипт заслуживает новую попытку -
  // оба счётчика подряд идущих неудачных периодических прогонов сбрасываются
  // всегда, и script1 (если был отключён из-за своих ошибок) снова разрешён.
  lua_periodic_failure_count_script1 = 0;
  lua_periodic_failure_count_script2 = 0;
  lua_script1_disabled = false;
  // [П26] Хранилище setObject чистим только когда сменился РЕЖИМНЫЙ скрипт -
  // простая перезагрузка того же script2 (правка через веб) обязана сохранить
  // накопленное состояние прогона (например tank_filled/total_volume).
  static String lua_last_loaded_type_script;
  if (lua_last_loaded_type_script != lua_type_script) {
    luaObj->clear();
    lua_last_loaded_type_script = lua_type_script;
  }
  String s1 = get_lua_script("script.lua");
  String s2 = get_lua_script(lua_type_script);
  String btnList = get_lua_script_list();
  String modeChunkName = "@" + lua_type_script;

  bool lua_locked = lua_state_lock(portMAX_DELAY);
  if (!lua_locked) {
    WriteConsoleLog(F("Lua reload busy"));
    lua_runtime_ready = false;
    return;
  }
  String script1Error = lua_compile_chunk_locked(s1, "@script.lua", script1_ref);
  String script2Error = lua_compile_chunk_locked(s2, modeChunkName.c_str(), script2_ref);
  bool locked = runtime_state_lock(portMAX_DELAY);
  if (locked) {
    script1 = s1;
    script2 = s2;
    lua_script_list_cache = btnList;
    runtime_state_unlock(true);
  }
  lua_state_unlock(lua_locked);
  if (script1Error.length() > 0) WriteConsoleLog("ERR in script.lua: " + script1Error);
  if (script2Error.length() > 0) WriteConsoleLog("ERR in " + lua_type_script + ": " + script2Error);
  const bool ready = lua_boot_init_ready &&
                     lua_coroutine_watchdog_ready &&
                     script1Error.length() == 0 && script2Error.length() == 0;
  lua_runtime_ready = ready;
}

//Запускаем таск для запуска скрипта
void do_lua_script(void *parameter) {
  String sr;
  sr.reserve(128);
  unsigned long last_periodic_lua_start = 0;
  //String glv;
  while (1) {
    // Приостанавливаем выполнение Lua скриптов во время OTA обновления
    if (ota_running) {
      vTaskDelay(500 / portTICK_PERIOD_MS);  // Увеличиваем задержку во время OTA
      continue;
    }

    // One-shot Lua jobs from web/Blynk/buttons are executed only by this task.
    {
      String local_job_script;
      LuaJobType local_job_type = LUA_JOB_NONE;
      if (take_lua_job(local_job_script, local_job_type)) {
        // [PKG-F] Свежий one-shot job начинает читать Msg «с текущего момента»:
        // сбрасываем приватный Lua-курсор на новейшее событие (вне runtime_state_lock,
        // одиночный писатель — задача do_lua_script).
        reset_lua_message_cursor();
        bool lua_locked = false;
        lua_locked = lua_state_lock(portMAX_DELAY);
        if (!lua_locked) {
          finish_lua_job();
          WriteConsoleLog(F("Lua mutex unavailable"));
          vTaskDelay(50 / portTICK_PERIOD_MS);
          continue;
        }
        if (show_lua_script && local_job_script.length() > 0) {
          WriteConsoleLog(F("--BEGIN LUA SCRIPT--"));
          WriteConsoleLog(local_job_script);
          WriteConsoleLog(F("--END LUA SCRIPT--"));
        }
        sr = lua_exec_locked(local_job_script);
        sr.trim();
        if (sr.length() > 0) {
          WriteConsoleLog((local_job_type == LUA_JOB_INLINE) ? "ERR in lua: " + sr : "ERR in BTN_SCRIPT " + sr);
        } else {
          WriteConsoleLog((local_job_type == LUA_JOB_INLINE) ? F("Lua run complete") : F("BTN_SCRIPT complete"));
        }
        lua_state_unlock(lua_locked);
        finish_lua_job();
      }
    }

    if (SetScriptOff && loop_lua_fl) {
      loop_lua_fl = false;
    }
    if (loop_lua_fl && !SetScriptOff) {
      unsigned long now = millis();
      if (last_periodic_lua_start == 0 || now - last_periodic_lua_start >= 1000) {
        if (request_lua_periodic_start()) last_periodic_lua_start = now;
      }
    }
    bool has_lua_start_request = false;
    if (!consume_lua_periodic_start_request(has_lua_start_request)) {
      vTaskDelay(5 / portTICK_PERIOD_MS);
      continue;
    }
    bool lua_active = false;
    if (!lua_periodic_active(lua_active)) {
      vTaskDelay(5 / portTICK_PERIOD_MS);
      continue;
    }
    if (lua_active) {
      // [W-4/W3] Копируем script1/script2 под runtime lock, но после захвата Lua VM:
      // если runtime lock занят, оставляем lua_finished=false и повторяем позже.
      bool lua_locked = lua_state_lock(portMAX_DELAY);
      if (!lua_locked) {
        WriteConsoleLog(F("Lua mutex unavailable"));
        vTaskDelay(50 / portTICK_PERIOD_MS);
        continue;
      }
      if (ota_running) {
        lua_state_unlock(lua_locked);
        vTaskDelay(500 / portTICK_PERIOD_MS);
        continue;
      }
      String local_s1, local_s2;
      int local_script1_ref = script1_ref;
      int local_script2_ref = script2_ref;
      {
        bool locked = runtime_state_lock(pdMS_TO_TICKS(50));
        if (locked) {
          local_s1 = script1;
          local_s2 = script2;
          runtime_state_unlock(true);
        } else {
          lua_state_unlock(lua_locked);
          vTaskDelay(5 / portTICK_PERIOD_MS);
          continue;
        }
      }

      bool periodicFailed = false;
      bool periodicTimedOut = false;
      if (local_s1.length() > 0 && lua_chunk_ref_valid(local_script1_ref) && !lua_script1_disabled) {
        if (show_lua_script) {
          WriteConsoleLog(F("--BEGIN LUA SCRIPT--"));
          WriteConsoleLog(local_s1);
          WriteConsoleLog(F("--END LUA SCRIPT--"));
        }
        sr = lua_exec_chunk_locked(local_script1_ref);
        periodicTimedOut = periodicTimedOut || luaLastExecutionTimedOut;
        sr.trim();
        if (sr.length() > 0) {
          periodicFailed = true;
          WriteConsoleLog("ERR in script.lua: " + sr);
          lua_periodic_failure_count_script1++;
          if (lua_periodic_failure_count_script1 >= LUA_PERIODIC_FAILURE_STOP_THRESHOLD) {
            WriteConsoleLog("script.lua остановлен после " + String(lua_periodic_failure_count_script1) +
                             " ошибок подряд, см. предыдущие ERR");
            lua_script1_disabled = true;
            lua_periodic_failure_count_script1 = 0;
          }
        } else {
          lua_periodic_failure_count_script1 = 0;
        }
      }
      vTaskDelay(5 / portTICK_PERIOD_MS);

      if (local_s2.length() > 0 && lua_chunk_ref_valid(local_script2_ref)) {
        if (show_lua_script) {
          WriteConsoleLog(F("--BEGIN LUA SCRIPT--"));
          WriteConsoleLog(local_s2);
          WriteConsoleLog(F("--END LUA SCRIPT--"));
        }
        sr = lua_exec_chunk_locked(local_script2_ref, true);
        periodicTimedOut = periodicTimedOut || luaLastExecutionTimedOut;
        sr.trim();
        if (sr.length() > 0) {
          periodicFailed = true;
          WriteConsoleLog("ERR in " + lua_type_script + ": " + sr);
          lua_periodic_failure_count_script2++;
          if (lua_periodic_failure_count_script2 >= LUA_PERIODIC_FAILURE_STOP_THRESHOLD) {
            WriteConsoleLog("режимный скрипт (" + lua_type_script + ") остановлен после " + String(lua_periodic_failure_count_script2) +
                             " ошибок подряд, см. предыдущие ERR");
            loop_lua_fl = false;
            lua_periodic_failure_count_script2 = 0;
          }
        } else {
          lua_periodic_failure_count_script2 = 0;
        }
      } else {
        lua_gc(lua.GetState(), LUA_GCCOLLECT, 0);
      }
      finish_lua_periodic_run();
      finish_beer_lua_periodic_result(periodicFailed, periodicTimedOut);
      lua_state_unlock(lua_locked);
    } else {
      vTaskDelay(50 / portTICK_PERIOD_MS);
    }
    if (!loop_lua_fl && SetScriptOff) {
      SetScriptOff = 0;
    }
    vTaskDelay(5 / portTICK_PERIOD_MS);
  }
}

bool start_lua_script() {
  if (!request_lua_periodic_start()) {
    WriteConsoleLog(F("Lua busy"));
    return false;
  }
  return true;
}

// [П29] test_str_val приходит из Lua (setStrVariable) без санитизации: кавычка
// или перевод строки в значении ломают компиляцию ВСЕХ кнопочных скриптов до
// перезагрузки (склеивается в текст прелюдии, а не передаётся как Lua-строка).
inline String lua_escape_prelude_string(const String& value) {
  String escaped;
  escaped.reserve(value.length());
  for (unsigned int i = 0; i < value.length(); i++) {
    char c = value[i];
    switch (c) {
      case '"': escaped += "\\\""; break;
      case '\\': escaped += "\\\\"; break;
      case '\n': escaped += "\\n"; break;
      case '\r': escaped += "\\r"; break;
      default: escaped += c; break;
    }
  }
  return escaped;
}

// [П29] String(float) на NaN/Inf даёт текст "nan"/"inf" - в прелюдии это имя
// НЕОПРЕДЕЛЁННОЙ Lua-глобали (компиляция пройдёт, значение станет nil), и
// скрипт упадёт позже и в другом, менее очевидном месте. Датчик температуры
// на отказе может отдать NaN - здесь превращаем его в валидное Lua-выражение,
// которое даёт настоящие NaN/Inf (Lua собран с плавающим lua_Number - см.
// libraries/ESP-Arduino-Lua/src/lua/luaconf.h: LUA_FLOAT_TYPE == LUA_FLOAT_FLOAT,
// оператор "/" в Lua - всегда вещественное деление, даже для целого lua_Number).
inline String lua_prelude_number(float value) {
  if (isnan(value)) return "(0/0)";
  if (isinf(value)) return value > 0 ? "(1/0)" : "(-1/0)";
  return String(value);
}

String get_global_variables() {
  String Variables;
  Variables += "bme_pressure = " + String(bme_pressure) + "\r\n";
  Variables += "capacity_num = " + String(capacity_num) + "\r\n";
  Variables += "SamovarStatusInt = " + String(SamovarStatusInt) + "\r\n";
  Variables += "ProgramNum = " + String(ProgramNum) + "\r\n";
  Variables += "ProgramLen = " + String(ProgramLen) + "\r\n";
  Variables += "ActualVolumePerHour = " + String(ActualVolumePerHour) + "\r\n";
  Variables += "WthdrwlProgress = " + String(WthdrwlProgress) + "\r\n";
  Variables += "PowerOn = " + String(PowerOn) + "\r\n";
  Variables += "PauseOn = " + String(PauseOn) + "\r\n";
  Variables += "StepperMoving = " + String(StepperMoving) + "\r\n";
  Variables += "program_Pause = " + String(program_Pause) + "\r\n";
  Variables += "program_Wait = " + String(program_Wait) + "\r\n";
  String programWaitTypeText;
  if (!copy_program_wait_type_text(programWaitTypeText)) {
    WriteConsoleLog(F("WARNING! program_Wait_Type busy"));
    Variables += "error('program_Wait_Type busy')\r\n";
  } else {
    Variables += "program_Wait_Type = \"" + programWaitTypeText + "\"\r\n";
  }
#ifdef USE_WATERSENSOR
  Variables += "WFflowMilliLitres = " + String(WFflowMilliLitres) + "\r\n";
  Variables += "WFtotalMilliLitres = " + String(WFtotalMilliLitres) + "\r\n";
  Variables += "WFflowRate = " + String(WFflowRate) + "\r\n";
#endif
  Variables += "WthdrwTimeAll = " + String(WthdrwTimeAll) + "\r\n";
  Variables += "WthdrwTime = " + String(WthdrwTime) + "\r\n";
  Variables += "WthdrwTimeAllS = \"" + WthdrwTimeAllS + "\"\r\n";
  Variables += "WthdrwTimeS = \"" + WthdrwTimeS + "\"\r\n";
  Variables += "pump_started = " + String(pump_started) + "\r\n";
  Variables += "heater_state = " + String(heater_state) + "\r\n";
  Variables += "mixer_status = " + String(mixer_status) + "\r\n";
  Variables += "alarm_event = " + String(alarm_event) + "\r\n";
  Variables += "acceleration_heater = " + String(acceleration_heater) + "\r\n";
  Variables += "valve_status = " + String(valve_status) + "\r\n";
  WProgram currentProgram;
  bool hasCurrentProgram = lua_copy_current_program(currentProgram);
  Variables += "program_type = \"" + String(hasCurrentProgram ? program_type_to_string(currentProgram.WType) : String()) + "\"\r\n";
  Variables += "program_volume = " + String(hasCurrentProgram ? currentProgram.Volume : 0) + "\r\n";
  Variables += "program_speed = " + String(hasCurrentProgram ? currentProgram.Speed : 0) + "\r\n";
  Variables += "program_temp = " + String(hasCurrentProgram ? currentProgram.Temp : 0) + "\r\n";
  Variables += "program_power = " + String(hasCurrentProgram ? currentProgram.Power : 0) + "\r\n";
  Variables += "program_time = " + String(hasCurrentProgram ? currentProgram.Time : 0) + "\r\n";
  Variables += "program_capacity_num = " + String(hasCurrentProgram ? currentProgram.capacity_num : 0) + "\r\n";

  Variables += "SamSetup_Mode = " + String(SamSetup.Mode) + "\r\n";
  Variables += "test_num_val = " + String(test_num_val) + "\r\n";
  Variables += "test_str_val = \"" + lua_escape_prelude_string(test_str_val) + "\"\r\n";

  Variables += "SteamTemp = " + lua_prelude_number(SteamSensor.avgTemp) + "\r\n";
  Variables += "PipeTemp = " + lua_prelude_number(PipeSensor.avgTemp) + "\r\n";
  Variables += "WaterTemp = " + lua_prelude_number(WaterSensor.avgTemp) + "\r\n";
  Variables += "TankTemp = " + lua_prelude_number(TankSensor.avgTemp) + "\r\n";
  Variables += "ACPTemp = " + lua_prelude_number(ACPSensor.avgTemp) + "\r\n";

  String currentPowerMode;
  if (!copy_current_power_mode_value(currentPowerMode)) {
    WriteConsoleLog(F("WARNING! current_power_mode busy"));
    Variables += "error('current_power_mode busy')\r\n";
  } else {
    Variables += "current_power_mode = \"" + currentPowerMode + "\"\r\n";
  }
  Variables += "target_power_volt = " + String(target_power_volt) + "\r\n";

#ifdef USE_WATER_PUMP
  Variables += "wp_count = " + String(wp_count) + "\r\n";
#endif

  return Variables;
}

String get_lua_mode_name(bool filename) {
  String fl;
  if (Samovar_CR_Mode == SAMOVAR_BEER_MODE) {
    if (filename) {
      fl = "/beer" + String(LUA_BEER) + ".lua";
    } else {
      fl = "beer";
    }
  } else if (Samovar_CR_Mode == SAMOVAR_DISTILLATION_MODE) {
    if (filename) {
      fl = "/dist" + String(LUA_DIST) + ".lua";
    } else {
      fl = "dist";
    }
  } else if (Samovar_CR_Mode == SAMOVAR_BK_MODE) {
    if (filename) {
      fl = "/bk" + String(LUA_BK) + ".lua";
    } else {
      fl = "bk";
    }
  } else if (Samovar_CR_Mode == SAMOVAR_NBK_MODE) {
    if (filename) {
      fl = "/nbk" + String(LUA_NBK) + ".lua";
    } else {
      fl = "nbk";
    }
  } else if (Samovar_CR_Mode == SAMOVAR_SUVID_MODE) {
    if (filename) {
      fl = "/suvid" + String(LUA_SUVID) + ".lua";
    } else {
      fl = "suvid";
    }
  } else {
    if (filename) {
      fl = "/rectificat" + String(LUA_RECT) + ".lua";
    } else {
      fl = "rect";
    }
  }
  return fl;
}
#endif
