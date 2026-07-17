# A-07 / R4.2 — явные Lua I2C failures и checked numeric narrowing

## 1. Цель и критерий PASS

Закрыть только подтверждённый A-07 без нового функционала: Lua write API не должен
объявлять успех при известном I2C timeout/failure и не должен сужать Lua numeric
types до firmware-типов до проверки domain/range. Имена Lua-функций и
переменных, успешные return counts и существующие observable `0/1` результаты
сохраняются.

PASS требует одновременно:

- стабильного checkout после Gate W3 и отдельного `PASS: no errors, no warnings`
  A-05; A-07 не зависит от выдуманного A-05 mode API;
- integer arguments читаются как `lua_Integer`, fractional arguments — как
  `lua_Number`; checked conversion выполняется до каждого затронутого cast,
  mutation, lock и hardware call;
- Lua error для invalid numeric input, expander semaphore timeout и доступного через
  реальный vendor API `PCF8575::digitalWrite()==false`;
- сохранения трёх разных mode-семантик через один узкий owner под существующим
  `pending_command_lock`, без queue/operation/profile lifecycle;
- сохранения fractional pump volume в расчёте target steps, существующих distinct
  I2C/local calibration fallback semantics и `float` PID coefficients;
- production-derived host/Lua tests, полный smoke, два cppcheck, семь штатных
  PlatformIO environments, отдельная feature-build с expanders и чистый reviewer
  verdict `PASS: no errors, no warnings`.

## 2. Выбранная минимальная архитектура

Рассмотрены и отвергнуты два более широких пути:

1. `ProfileOperationSlot`/OperationStore для Lua mode setters меняет синхронный Lua
   контракт, добавляет lifecycle и связывает A-07 с web save — вне задачи.
2. Прямые assignments из `lua.h` сохраняют гонку с mode-change publication и
   оставляют mode state без владельца.

Выбран минимальный путь:

- Arduino-free checked converters остаются в `numeric_parse.h`;
- `lua.h` читает integer/fractional args через правильный Lua API, передаёт typed
  result setter-у и превращает validation/owner/I2C failure в существующий Lua
  error mechanism;
- один Lua-specific mode owner объявляется в `samovar_api.h` и реализуется в
  `Samovar.ino`; он использует только существующий `pending_command_lock`, не
  создаёт state, flag, queue, task или retry;
- `I2CStepper.h`, `control_numeric_input.h` и vendored APIs не меняются.

## 3. Неподвижная граница

- Не добавлять Lua functions/variables, routes, operation IDs, queue, task, mutex,
  retry, lifecycle, UI, security, shim/proxy, compatibility path или fallback.
- Не менять `data/**`, `Lua_script/**`, `libraries/**`, `I2CStepper.h`,
  `control_numeric_input.h`, `Samovar.h`, `platformio.ini` и persistent format.
- Не переводить Lua mode writes в A-12 profile operation и не сохранять NVS из Lua.
- Существующий local-stepper fallback в `I2CStepper.h::set_stepper_target()` и
  calibration fallback `SamSetup.StepperStepMlI2C -> I2C_STEPPER_STEP_ML_DEFAULT`
  сохраняются буквально; новый fallback не добавляется.
- `PCF8575::pinMode()` и `PCF8591::analogWrite()` имеют `void`, поэтому для них
  можно честно сообщить только semaphore timeout. Выдумывать ACK запрещено.
- `PCF8575::digitalWrite()` возвращает `bool`; этот доступный failure обязан стать
  Lua error после освобождения I2C semaphore.
- Browser/Playwright штатно не запускать: assets, routes, schema и observable UI не
  меняются. Любая необходимость изменить их — stop condition и перепланирование.

## 4. Checked numeric primitives

В `numeric_parse.h` добавить только два allocation-free inline C++11 helper-а,
не зависящих от Arduino или Lua:

1. checked narrowing из signed integral wide input в `int32_t` с explicit
   `min/max` и output-by-reference; caller передаёт уже полученный
   `luaL_checkinteger()` result без промежуточного `float`;
2. checked finite positive floating product в `uint32_t` с явно названной
   текущей truncation-семантикой для `volumeMl * stepsPerMl`, но только в
   диапазоне `[1, UINT32_MAX]`.

Оба helper-а сначала проверяют bounds/finite, возвращают `OUT_OF_RANGE` до unsafe
narrowing и не изменяют output при ошибке. Fractional integer input отклоняет
`luaL_checkinteger()` до helper-а. Integral comparison выполняется в wide integral
representation: значения `16777217` и `INT32_MAX` не проходят через 32-bit
`lua_Number=float`.

Не добавлять string parser, Lua type, domain defaults или duplicated
rate/product formula. Скорость насоса по-прежнему вычисляет существующий
`i2c_get_speed_from_rate()` с его I2C/local calibration choice; error text берётся
через `numeric_parse_error_code()`.

## 5. `setNumVariable`: domains и result propagation

`LuaNumVariableDescriptor::setter` становится result-returning, а descriptor
явно различает integral и fractional domain. После lookup integral entries
читаются `luaL_checkinteger()`, fractional entries — `luaL_checknumber()`; общего
промежуточного `float` для integer fields нет. Один descriptor validation path
проверяет raw value и только затем вызывает setter; ошибка даёт
`luaL_error("Invalid <name>: <code>")` без печати исходного значения. Unknown,
read-only, getter, access flag, имя и порядок каждой descriptor entry сохраняются.

`luaL_error()` в vendored Lua использует `longjmp`, поэтому ни один новый error
path не пересекает lifetime Arduino `String` или другого нетривиального C++
объекта. Mutation gate выполняется первым; variable name берётся как Lua-owned
`const char*`, descriptor ищется без heap-`String`, все Lua type checks происходят
до optional normal-return logging scope. Оставить живой `String Var` и вызвать
`luaL_error()` из descriptor setter-а запрещено.

| Setter(s) | Точный существующий target/domain |
|---|---|
| `WFpulseCount` | exact `0..UINT16_MAX`, затем `water_pulse_count_set()` |
| `pump_started`, `valve_status`, `loop_lua_fl`, `SetScriptOff`, `show_lua_script` | exact `{0,1}` |
| `SamSetup_Mode`, `Samovar_Mode`, `Samovar_CR_Mode` | exact enum `0..SAMOVAR_LUA_MODE`, затем mode owner из раздела 6 |
| `acceleration_temp` | exact `0..UINT16_MAX` |
| `wp_count` | exact `INT8_MIN..INT8_MAX`; ошибочный cast в `byte` удалить |
| `pmpKp`, `pmpKi`, `pmpKd` | любой finite `float`, дробная часть сохраняется; реальные vendor fields `GyverPID::{Kp,Ki,Kd}` имеют тип `float` |
| `SteamTemp`, `boil_temp`, `PipeTemp`, `WaterTemp`, `TankTemp`, `ACPTemp`, `test_num_val` | finite `lua_Number/float`; новых температурных limits не вводить |

Setter публикует mutation только после validation. Owner-busy для mode setter
преобразуется в отдельную понятную Lua busy error, а не маскируется numeric error.

## 6. Три разные mode-семантики и узкий owner

В `samovar_api.h` под `USE_LUA` объявить малый enum target-а и одну функцию owner;
в `Samovar.ino` реализовать её под тем же guard. Функция:

1. захватывает существующий `pending_command_lock(pdMS_TO_TICKS(50))`;
2. под lock требует одновременно
   `profile_operation_phase_load() == PROFILE_OPERATION_EMPTY` и
   `!mode_switch_in_progress()`; settings-only profile operation также блокирует
   Lua mode mutation;
3. выполняет ровно одну из трёх существующих семантик;
4. освобождает lock и возвращает `bool` caller-у.

Семантики не являются aliases:

- `SamSetup_Mode`: меняет только RAM-поле `SamSetup.Mode`; не меняет active/control
  mode, не вызывает `change_samovar_mode()` и не пишет NVS;
- `Samovar_Mode`: при отличающемся значении меняет только active
  `Samovar_Mode` и вызывает существующий `change_samovar_mode()`, который
  синхронизирует `Samovar_CR_Mode`; same-mode сохраняет прежний no-op, включая
  отсутствие принудительной нормализации отдельно изменённого CR mode;
- `Samovar_CR_Mode`: меняет только `Samovar_CR_Mode`; не меняет setup/active mode
  и не вызывает `change_samovar_mode()`.

В `lua.h` после этого нет assignments этих трёх globals и прямого вызова
`change_samovar_mode()`. Lock busy, любая non-empty profile phase или active
mode-switch завершают Lua chunk с ошибкой и оставляют все три значения
неизменными. Никакой pending request не создаётся.

## 7. I2C/stepper/pump wrappers в scope

Integer arguments ниже читаются `luaL_checkinteger()`, fractional rate/volume —
`luaL_checknumber()`; validation всегда предшествует narrowing и side effects.

| Wrapper | Validation | Сохранённый success/failure contract |
|---|---|---|
| `exp_pinMode` | pin `0..15`, mode exactly `INPUT/OUTPUT/INPUT_PULLUP`, как поддерживает текущий `PCF8575` | success returns 0 values; timeout — Lua error |
| `exp_digitalWrite` | pin `0..15`, value exactly `LOW/HIGH` | success 0 values; timeout или vendor `false` — unlock, затем Lua error |
| `exp_digitalRead` | pin `0..15` | success 1 value; существующий timeout error |
| `exp_analogWrite` | exact `0..UINT8_MAX` | success 0 values; timeout error; `void` vendor call без fake ACK |
| `exp_analogRead` | channel `0..3` | success 1 value; существующий timeout error |
| `set_stepper_by_time` | integer speed/time `0..UINT16_MAX`, direction `{0,1}` | ровно один фактический bool `0/1` |
| `set_stepper_target` | integer speed `0..UINT16_MAX`, direction `{0,1}`, target `0..INT32_MAX` из-за vendored 32-bit `lua_Integer` contract | ровно один фактический bool `0/1`; existing local fallback неизменен |
| `i2cpump_start` | finite positive rate сохраняет `i2c_get_speed_from_rate()` и его I2C/local calibration choice; результат проверяется finite и `1..UINT16_MAX` до cast. Volume остаётся finite positive fractional; checked product `volumeMl * stepsPerMl` должен попасть в `[1, UINT32_MAX]` | `use_I2C_dev != 2` остаётся `0`; physical refresh может перейти в существующий local fallback; underlying `false` остаётся `0`; invalid numeric — Lua error |
| `i2cpump_stop` | numeric input отсутствует | один реальный bool от `set_stepper_target(0,0,0)`, не unconditional `1` |
| `set_mixer_pump_target` | exact `{0,1}` | один фактический bool `0/1` |
| `set_i2c_rele_state` | relay `1..4`, state `{0,1}` | один фактический bool `0/1` |
| `get_i2c_rele_state` | relay `1..4` | один существующий read result; invalid numeric — Lua error до cast |

`i2cpump_start` сохраняет текущие две calibration semantics: target product берёт
существующий I2C steps-per-ml/default, а speed вычисляет ровно текущий
`i2c_get_speed_from_rate()`, который при physical I2C refresh failure использует
local `SamSetup.StepperStepMl`. Значение `0 < product < 1` отклоняется, потому что
truncation в ноль превратит target в stop. Fractional `volumeMl` участвует в
расчёте `targetSteps` без предварительного округления, но A-07 не обещает точного
fractional tracking: `set_stepper_target()` сейчас округляет I2C ml до `uint16_t`,
а local fallback не обновляет те же tracking fields. Существующие wrapper tracking
assignments/order и owner/rollback semantics не рефакторируются в read-only
`I2CStepper.h`.

Generic GPIO/delay/timer/power/PWM/valve/message/HTTP и unrelated Lua execution,
registration/caching не рефакторить: они не являются доказательством A-07.

## 8. Последовательность разработки

1. **Freeze baseline.** После A-05 PASS сохранить SHA/scoped diff пяти production
   файлов, exact Lua registration/descriptor/return inventory и vendor contracts:
   `LUA_32BITS=1`, `sizeof(lua_Number)==4`, `sizeof(lua_Integer)==4`, PCF return
   signatures. Убедиться, что нет параллельной записи в allowlist.
2. **Red tests.** Сначала расширить `smoke_numeric_parse.py` и добавить
   `smoke_lua_a07.py`; подтвердить красный результат на current unsafe narrowing,
   mode direct writes, expander silent failure и unconditional pump-stop success.
3. **Numeric helpers.** Реализовать два helper-а раздела 4 и довести только numeric
   host matrix до зелёного.
4. **Descriptors/modes.** Перевести descriptor setters на validated result,
   реализовать owner и убрать прямые mode writes из `lua.h`.
5. **I2C wrappers.** Последовательно исправить expander, stepper/pump/mixer/relay
   conversions и result propagation; semaphore всегда освобождается до
   `luaL_error()`.
6. **Stabilize.** Запустить targeted/full gates, allowlist audit, map update и
   reviewer loop.

Шаги 3 и подготовка fake boundaries шага 5 могут делаться параллельно разными
сабагентами только до общей записи в `lua.h`; production edits `lua.h` и
`Samovar.ino/samovar_api.h` выполняются последовательно.

## 9. Exact production-derived tests

### `tools/smoke_numeric_parse.py`

Host C++11 `-Wall -Wextra -Werror` matrix для новых production helper-ов:

- integral min/max, min-1/max+1 и invalid bounds без floating intermediate;
- truncating uint32: `0`, smallest accepted product `1`, fractional product below
  one, ordinary fractional product, `UINT32_MAX`, next representable overflow,
  `NaN`, `+Inf`, `-Inf`;
- output sentinel неизменен при каждой ошибке.

### Новый `tools/smoke_lua_a07.py`

Тест не моделирует Lua вызовом C++ callback напрямую. Он:

1. компилирует vendored Lua `.c` sources из `libraries/ESP-Arduino-Lua/src/lua`
   именно C-компилятором (исключая CLI `lua.c/luac.c`), а C++ harness — отдельно
   C++-компилятором; проверяет фактический 32-bit numeric contract;
2. извлекает из production `lua.h` затронутые callback/setter/descriptor bodies и
   из `Samovar.ino` mode-owner body; production formulas не копирует;
3. предоставляет fake только на Arduino/FreeRTOS/PCF/I2CStepper boundaries;
4. регистрирует actual extracted callbacks в `lua_State` и запускает chunks через
   `luaL_loadstring` + `lua_pcall`.

Обязательная matrix:

- каждый descriptor domain: обе границы, outside, fractional integer,
  NaN/±Inf; integer path отдельно проверяет `16777217` и `INT32_MAX` без
  float-rounding; invalid chunk прерывается до следующей mutation;
- PID `6.5/0.3/30.25` сохраняются как float без byte truncation;
- три mode names: отдельно valid/same/invalid, lock busy, active mode-switch и
  каждая non-empty `ProfileOperationPhase`; assertions подтверждают exact distinct
  semantics раздела 6 и неизменность всех трёх mode fields при busy;
- expander success, semaphore timeout и digitalWrite false; give count равен 1
  только после успешного take, side-effect после failed call не исполняется;
- analog write не проверяет несуществующий ACK;
- stepper/mixer/relay min/max/direction/state failures и реальный bool result;
- pump: fractional volume без pre-round, persisted I2C/default и отдельная local
  calibration, rate result `65535/65536`, product below one/edge/overflow,
  `use_I2C_dev != 2`, physical refresh local fallback, underlying false/true;
  `i2cpump_stop` возвращает underlying bool, existing tracking не объявляется
  transactional;
- longjmp safety: все новые `luaL_error()` paths выполняются без живого Arduino
  `String`; повторные invalid chunks не дают рост tracked test allocation count;
- success return cardinality: void wrappers 0, reads/bool wrappers 1;
- registration names/order/cardinality byte-for-byte равны baseline;
- static: нет affected raw narrowing, mode direct write/call, duplicate numeric
  formulas, новых registrations/routes/tasks/queues/operation symbols; существующая
  wrapper tracking semantics не расширяется и не удаляется.

Дополнительно оставить зелёными:

```text
PYTHONDONTWRITEBYTECODE=1 python3 tools/smoke_numeric_parse.py
PYTHONDONTWRITEBYTECODE=1 python3 tools/smoke_lua_a07.py
PYTHONDONTWRITEBYTECODE=1 python3 tools/smoke_lua_serialization.py
PYTHONDONTWRITEBYTECODE=1 python3 tools/smoke_lua_api_optimizations.py
PYTHONDONTWRITEBYTECODE=1 python3 tools/smoke_lua_scripts.py
PYTHONDONTWRITEBYTECODE=1 python3 tools/smoke_numeric_i2c_contract.py
PYTHONDONTWRITEBYTECODE=1 python3 tools/smoke_i2cstepper_atomic.py
PYTHONDONTWRITEBYTECODE=1 python3 tools/smoke_profile_operation.py
```

## 10. Write allowlist

Planning-pass меняет только этот файл.

Implementation allowlist:

- `numeric_parse.h`;
- `lua.h`;
- `Samovar.ino`;
- `samovar_api.h`;
- `tools/smoke_numeric_parse.py`;
- новый `tools/smoke_lua_a07.py`.

После полного PASS разрешены только status/metadata changes:

- `.claude/experts/plans/samovar-a07-lua-errors.md`;
- два master ledger: `samovar-audit-remediation.md` и
  `samovar-remaining-remediation-2026-07-12.md`;
- affected map nodes `lua-h`, `numeric-parse-h`, `samovar-ino`, `samovar-api-h`,
  `tools`, а также `.cli-proxy/.codebase_map/TESTING.md` и count в `INDEX.md`.

Ожидаемый backend inventory до слияния параллельных UI-additions:
`61 smoke / 6 browser` (58 после A-01, 59 после A-04, 60 после A-05 и 61 после
нового A-07 smoke).

Любой другой production/test файл требует остановки и пересмотра плана. В
частности, `I2CStepper.h`, `control_numeric_input.h`, `Samovar.h`, vendor
libraries, UI/data и build config строго read-only.

## 11. Финальные gates и reviewer loop

Cppcheck и PlatformIO никогда не запускать одновременно.

1. Выполнить targeted matrix раздела 9, затем
   `PYTHONDONTWRITEBYTECODE=1 python3 tools/run_smoke_tests.py --timeout 60`.
2. Последовательно выполнить:

   ```text
   python3 tools/run_cppcheck.py --timeout 300
   python3 tools/run_cppcheck.py --force --timeout 600 --report /tmp/samovar-a07-cppcheck-extended.txt
   ```

   Любые `error`/`warning` блокируют PASS; information фиксируется отдельно.
3. Сначала собрать Lua environment, затем все семь штатных environments строго
   последовательно: `Samovar_lua_mqtt`, `Samovar`, `Samovar_s3`,
   `Samovar_no_power`, `Samovar_rmvk`, `Samovar_sem`, `Samovar_alarm_button`.
4. Отдельно, не меняя repo/global config, проверить реальные conditional wrappers:

   ```text
   PLATFORMIO_BUILD_FLAGS="-DUSE_EXPANDER=0x20 -DUSE_ANALOG_EXPANDER=0x48" \
   PLATFORMIO_BUILD_DIR=/tmp/samovar-a07-pio-expanders \
   pio run -e Samovar_lua_mqtt
   ```

   Verbose/preprocess evidence обязано содержать оба define и inherited
   `SAMOVAR_BUILD_LUA`; иначе build не считается gate.
5. Выполнить `git diff --check`, exact registration/return/direct-write inventory
   и audit фактического diff по allowlist. Browser gate не нужен при нулевом UI
   diff.
6. Обновить только affected map/status files после test PASS; при mapper failure —
   targeted `update-node`/`repair`, не full regeneration.
7. Независимый reviewer читает весь A-07 diff и возвращает ERROR/WARNING либо
   точный `PASS: no errors, no warnings`. Каждую находку исправить в том же
   allowlist, повторить affected tests/builds и review до exact PASS. Только после
   этого отмечать A-07 complete в обоих ledgers.

## 12. Stop conditions и rollback

Немедленно остановиться, если:

- Gate W3/A-05 не закрыт или другой агент пишет в implementation allowlist;
- mode semantics требуют persistence, queue, operation lifecycle или изменения
  `switch_samovar_mode()`;
- correctness требует менять `I2CStepper.h`, calibration/local-stepper fallback,
  vendor Lua/PCF libraries или `control_numeric_input.h`;
- требуется изменить Lua name/success return count, route, UI/data или build config;
- production-derived `lua_pcall` test возможен только через копию production
  algorithm, shim или test hook.

После двух повторов одной ошибки прекратить локальные попытки и по правилу
репозитория изучить 3–5 решений в web. Rollback — только обратный patch собственных
A-07 строк и metadata; `git reset`, checkout и очистка чужого dirty tree запрещены.
Hardware side effect не повторять и не пытаться автоматически откатывать.
