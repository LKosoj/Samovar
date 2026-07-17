# A-10 — строгий числовой ввод во всех first-party внешних контурах

## Цель

Закрыть A-10 так, чтобы ни один текстовый/сетевой числовой ввод основной прошивки не мог:

- превратить пустую строку или мусор в `0`;
- пропустить `NaN`, `+Inf`, `-Inf` или overflow;
- wrap-нуться при приведении к `uint8_t`/`uint16_t`/`uint32_t`;
- быть молча обрезанным маской, clamp/fallback-значением или неявным cast;
- частично изменить runtime/staged state до обнаружения второй ошибки в том же запросе;
- занять pending-slot или поставить аппаратную команду при ошибке;
- скрыть конфликт, повтор или отсутствие обязательного аргумента.

План составлен по live tree на 2026-07-11. Использованы `dev-experts` в ролях `architect`, `cpp-dev`, `tester`, `reviewer` и принципы `97-dev`: один источник доменных контрактов, parse-before-side-effect, проверка каждой ошибки, минимальные Arduino-совместимые изменения.

## Completion record

- Статус: **complete**.
- Review: **PASS: no errors, no warnings**.
- Результат: все инвентаризированные first-party external numeric inputs проходят
  единую finite/bounded validation до narrowing, queue и изменения state;
  state-changing GET сохранены по решению пользователя.

Реализовано:

- `numeric_parse.h` владеет Arduino-независимой лексикой, overflow checks и
  стабильными `NumericParseError`;
- `control_numeric_input.h` владеет прикладными domains и checked conversions;
- `/save`, `/command`, `/program`, `/ajax_col_params`, `/i2cpump`,
  `/i2cstepper`, `/calibrate`, WebSerial, Blynk и SEM/KVIC paths валидируют
  значения до side effects;
- duplicate/conflicting/missing parameters отвергаются до pending publication;
- request-level staging сохраняет all-or-nothing semantics, а invalid input не
  занимает pending slot и не меняет globals.

Проверка на момент закрытия A-10:

- полный smoke: `48/48` PASS;
- Playwright: numeric `36/9`, I2C `10`, program-clear 12 pages / 48 requests PASS;
- PlatformIO: `7/7` environments PASS;
- buildfs, blocking/extended cppcheck и `git diff --check`: PASS;
- codebase map: 68 nodes / 530 edges.

Исторический baseline до реализации содержал duplicate `parseLongSafe` /
`parseFloatSafe`, unchecked `toInt()`/mask-after-cast, неатомарные `vless` /
`Descr`, раннюю запись `stpstep`, narrowing `WFpulseCount`, permissive Blynk и
SEM/KVIC conversions. Это описание исходных gaps, а не текущего состояния;
перечисленные пути закрыты реализацией и тестами A-10.

## Границы задачи

### В A-10

- HTTP-числа основной прошивки: `/save`, `/command`, `/program`, `/ajax_col_params`, `/i2cpump`, `/i2cstepper`, `/calibrate`;
- WebSerial `WFpulseCount`;
- Blynk numeric write pins;
- строковые числовые telemetry/response packets силового регулятора;
- чистые checked-conversion helpers до произведений и narrowing;
- UI pre-validation и явное отображение HTTP `400` для затронутых форм;
- сохранение frozen transport methods: `/command`, `/program`, `/save` остаются POST; `/ajax_col_params`, `/i2cpump`, `/i2cstepper`, `/calibrate` остаются GET по решению пользователя о state-changing GET;
- host/static/browser tests, семь firmware environments, LittleFS build, map/stack/RAM budget.

### Инвентаризировано, но реализуется владельцем другого audit ID

- `lua.h` содержит `luaL_checknumber()/luaL_checkinteger()` с прямыми casts. Это A-07: A-10 предоставляет общие finite/bounded value helpers, а A-07 применяет их ко всем Lua descriptors/wrappers и возвращает `luaL_error`. Одновременная правка `lua.h` в A-10 запрещена, чтобы не получить два независимых контракта одной API;
- значения из NVS/старого EEPROM не являются текстовым parse-контуром; durable validation и результат сохранения принадлежат A-12;
- бинарные показания датчиков/I2C registers не проходят строковый parser; A-02 отвечает за подтверждённый lifecycle I2C-операций;
- `pro_mini_ntc/`, `Stab-avr/`, `Lua_UART/`, `libraries/` не входят в main firmware `build_src_filter` и не меняются.

Окончательный repo-wide gate после A-07 обязан снять временное исключение `lua.h`; A-10 нельзя объявлять доказательством исправления Lua narrowing.

## Архитектурное решение

### Рассмотренные варианты

| Вариант | Плюсы | Минусы | Решение |
|---|---|---|---|
| Локально заменить каждый `toInt()/toFloat()` | минимальный первый diff | дублирует границы, вновь допускает разные semantics, трудно host-test, высокий риск забыть Blynk/UART | отклонён |
| Универсальная runtime schema/descriptor table | единообразная диагностика | лишние таблицы/indirection/flash, усложняет legacy Arduino code, провоцирует «framework внутри firmware» | отклонён |
| Малый синтаксический parser + отдельные pure domain helpers + тонкие transport adapters | один источник истины, host-test без Arduino, нет heap/RTTI, домены видны по имени | добавляется один focused header | выбран |

### Компоненты

1. `numeric_parse.h` остаётся единственным низкоуровневым parser-ом лексики и checked arithmetic. Он ничего не знает о HTTP, Blynk, SamSetup и hardware globals.
2. Новый корневой inline-only `control_numeric_input.h` становится единственным источником прикладных доменов и чистых преобразований. Он принимает raw `const char*` и явные snapshots (`stepsPerMl`, `maxPower`), возвращает typed value/result и не меняет globals.
3. Transport adapters (`WebServer.ino`, `Samovar.ino`, `Blynk.ino`, `power_regulator.h`) только:
   - проверяют cardinality/source аргументов;
   - собирают raw values;
   - вызывают pure domain helper;
   - при полном успехе одним commit/queue действием публикуют typed draft.
4. Никаких реализаций в `Samovar.h`, `.cpp` в подкаталогах, `src/`, shim/proxy или fallback.

### Frozen boundary с A-09

A-10 не изменяет `ProgramDraft`, `PendingProgramUpdate`, `ProgramParseSpec`, `prepare_program_for_mode()`, `program_commit()`, `program_clear()`, serializers и mode wrappers. `program_io.h`/`program_types.h` в write-scope A-10 не входят. Для атомарности `/program` добавить отдельный A-10 metadata draft/slot в `Samovar.ino`, связанный с существующим pending program slot тем же `pending_command_lock`; он содержит только presence flags, bounded `vless` и bounded копию `Descr` (live UI contract `maxlength=250`). Frozen `PendingProgramUpdate` вкладывается/копируется без изменения. Metadata-only request также проходит через этот slot. В `loop()` metadata применяется только вместе с успешным A-09 action либо самостоятельно после тех же mode/session checks; при reject/busy не применяется ничего.

Регрессионные тесты A-09 запускаются неизменными. Допустимы только новые A-10 tests вокруг transport envelope; ослаблять A-09 assertions или возвращать raw pending program `String` запрещено.

### Новые generic primitives

Дополнить `numeric_parse.h` только реально используемыми операциями:

- `parse_bounded_uint8(text, min, max, out)`;
- `parse_bounded_uint32(text, min, max, out)` через ручное `uint64_t` decimal accumulation либо `strtoull` с одинаковой проверкой `UINT32_MAX` на host/ESP32; ширина host `unsigned long` не влияет на результат;
- `parse_fixed_hex_uint16(text, exactDigits, min, max, out)`; допускаются только `[0-9A-Fa-f]`, точная длина, overflow до умножения на 16;
- `validate_bounded_finite_float(value, min, max)` для уже типизированных Lua/Blynk-adapter значений;
- `checked_mul_u32(a, b, out)` через `uint64_t` и проверку до cast;
- `checked_rate_to_step_speed(rateLph, stepsPerMl, outSteps)` с явно документированным round-to-nearest, `stepsPerMl > 0`, результатом `1..UINT16_MAX`, без clamp к `1/65535`;
- `checked_step_speed_to_mlh(stepSpeed, stepsPerMl, outMlh)` через `uint64_t`, без saturating return;
- `numeric_parse_error_code(error)` — стабильный короткий ASCII code для transport diagnostics, без `String` и heap.

`out` у всех helpers меняется только при `ok()`. Ошибка bounds/configuration отличается от malformed input.

## Общие правила cardinality и atomicity

### Повторы и конфликтующие параметры

- Для каждого скалярного поля допустимо не более одного параметра с таким именем в разрешённом source (query/body).
- Одинаковое имя дважды — `400 BAD_REQUEST`, даже если значения равны.
- Один параметр одновременно в query и body у `/save` — конфликт, `400`; нельзя молча предпочесть body.
- `/command` принимает ровно одно action-name. Два разных action-name или повтор одного — `400` до throttle и до queue.
- `/calibrate` принимает ровно одно из `start`/`finish`; вместе или ни одного — `400`.
- `/i2cpump`: `stop` несовместим со `speed`/`volume`; start требует ровно по одному `speed` и `volume`.
- `/i2cstepper`: `relay` и `state` идут парой только для `cmd=relay`; stop/status отвергают config payload; apply/save/start принимают documented patch-fields.
- Неизвестные action/config поля отвергаются; последующие задачи не расширяют этот allowlist служебными исключениями.

### Missing semantics

- Необязательное поле отсутствует — staged значение сохраняется без изменения.
- Обязательное поле отсутствует — `400`; значение по умолчанию не подставляется.
- Единственное сохранённое legacy-default поведение чтения: `/ajax_col_params` без `mat` использует сахар (`2`), `/i2cstepper` status без `device` использует pump. Для mutating `cmd` device/cmd обязательны.
- `/program` без `vless` не меняет `BoilerVolume`; invalid/zero `vless` не заменяется на `30`.

### All-or-nothing

- Все поля одного transport request сначала разбираются в локальный draft.
- Semantic cross-field validation выполняется после parse, но до queue/global write.
- Pending-slot проверяется и заполняется только после полного success.
- При `BUSY` локально проверенный draft не публикуется и globals не меняются.
- `/program` не должен успевать изменить `Descr`/`BoilerVolume` до ошибки WProgram/vless или неуспешной постановки операции; отдельный A-10 metadata slot коммитится в `loop()` вместе с неизменённым A-09 `PendingProgramUpdate`.
- UART packet обновляет `current`, `target`, `mode`, `reg_online/last_reg_online` только после полной проверки всех полей.

## Полный inventory и точные домены

### 1. `/save` (`WebServer.ino::handleSave`)

Все существующие диапазоны сохраняются, но переводятся на `numeric_parse.h`. Ошибка любого поля оставляет `PendingSetupSave::staged`, pending slots и `SamSetup` неопубликованными.

| Поле | Тип/единица | Допустимый домен | Missing |
|---|---|---|---|
| `mode` | `SAMOVAR_MODE` | exact enum `{0,1,2,3,4,5,6}` | текущий mode |
| `SteamDelay`, `PipeDelay`, `WaterDelay`, `TankDelay`, `ACPDelay` | `uint16_t`, сек | `0..65535` | сохранить |
| `DeltaSteamTemp`, `DeltaPipeTemp`, `DeltaWaterTemp`, `DeltaTankTemp`, `DeltaACPTemp` | finite float, °C | `-1000..1000` | сохранить |
| `SetSteamTemp`, `SetPipeTemp`, `SetWaterTemp`, `SetTankTemp`, `SetACPTemp` | finite float, °C | `0..150` | сохранить |
| `Kp`, `Ki`, `Kd` | finite float | `0..100000` | сохранить |
| `StbVoltage`, `BVolt` | finite float, V/W по build | `0..10000` как существующий persisted contract | сохранить |
| `DistTimeF` | `uint8_t`, мин | `0..255` | сохранить |
| `MaxPressureValue` | finite float | `0..10000` | сохранить |
| `StepperStepMl`, `StepperStepMlI2C` | `uint16_t`, шаг/мл | `0..65535`; `0` допустим в профиле как «не откалибровано», но запрещает команды преобразования скорости | сохранить |
| `stepperstepml` | integer, шаг/100 мл | `0..6553500` и обязательно кратно `100` до деления; результат `0..65535` | сохранить |
| `autospeed` | `uint8_t` | `0..99` | сохранить |
| `DistTemp`, `NbkSteamT` | finite float, °C | `0..150` | сохранить |
| `TimeZone` | `uint8_t` | `0..23` | сохранить |
| `LogPeriod` | `uint8_t` | `1..255` | сохранить |
| `HeaterR` | finite float, Ом | `0.001..10000` | сохранить |
| `NbkIn`, `NbkDelta`, `NbkDM`, `NbkDP`, `NbkOwPress` | finite float | `0..100000` | сохранить |
| `rele1..rele4` | bool | exact lexical `0`/`1` | сохранить |
| `SteamAddr`, `PipeAddr`, `WaterAddr`, `TankAddr`, `ACPAddr` | integer index | `-1` либо `0..snapshot.count-1`; также hard bound `< SAMOVAR_DS_ADDRESS_MAX` | сохранить |
| `ColDiam` | finite float, дюйм | `0.1..10` | сохранить |
| `ColHeight` | finite float, м | `0.01..10` | сохранить |
| `PackDens` | `uint8_t`, % | `0..100` | сохранить |

Presence checkboxes (`useflevel`, `usepressure`, `useautospeed`, `useDetectorOnHeads`, `ChangeProgramBuzzer`, `UseBuzzer`, `UseBBuzzer`, `UseWS`, `UseST`, `CheckPower`) не являются числовым вводом; их существующая form-presence semantics сохраняется.

### 2. `/command` (`WebServer.ino::web_command`)

| Action/value | Тип/единица | Домен | Typed result |
|---|---|---|---|
| `mixer` | bool | exact `0`/`1` | `PendingMixerCmd{off/on}` |
| `distiller`, `startbk`, `startnbk` | bool | exact `0`/`1` | `1` → соответствующий start command, `0` → `SAMOVAR_POWER`; malformed никогда не становится power toggle |
| `watert` | integer PWM duty | `0..1023` | `uint16_t`; дробь запрещена |
| `voltage` | finite float V/W | `0..power_input_max(snapshot)` | typed power setpoint |
| `pumpspeed` | finite rate, л/ч | `>0` и checked conversion при `StepperStepMl>0` даёт `1..65535` шаг/с | queue уже готового `uint16_t stepSpeed`, а не raw float |
| `pnbk` | tagged numeric command | exact `0` = stop; `0<x<8000` = absolute rate; exact `8000` = decrement; exact `9000` = increment; всё остальное reject | `PendingNbkSpeedCmd{kind, rate/steps}` без cast float→int |

`power_input_max(snapshot)`:

- обычный voltage/RMVK/KVIC build: `230.0f`;
- SEM build: `52900.0f / HeaterResistant`, если finite `HeaterResistant > 1`, иначе существующий explicit hardware ceiling `4000.0f`;
- no-power build: action `voltage` не зарегистрирован/не компилируется.

Значения выше ceiling отвергаются; `set_current_power()` больше не является местом silent clamp для внешнего запроса. Значение ниже hardware threshold (`40 V` либо `100 W`) остаётся явной командой regulator sleep по существующему контракту, поэтому `0` допустим.

Для `pumpspeed` и absolute `pnbk` round-to-nearest step является документированным protocol quantization, не fallback. До queue проверяются calibration snapshot, finite intermediate, `uint16_t` result и все произведения.

Presence-only actions (`start`, `power`, `setbodytemp`, `reset`, `reboot`, `resetwifi`, `startst`, `rescands`, `stopst`, `nbkopt`, `pause`, `lua`, `luastr`) числового payload не имеют. Их cardinality всё равно входит в ровно-один-action gate.

### 3. `/i2cstepper`

#### Общие поля

| Поле | Домен |
|---|---|
| `device` | exact string `mixer`/`pump`; для mutation обязателен |
| `cmd` | exact string `status/apply/save/start/stop/calstart/calfinish/relay` |
| `mode` | mixer exact `{1}`; pump exact `{2,3}`; дополнительно mode должен поддерживаться `caps` |
| `relayMask` | `uint8_t 0..15`; mask-after-cast запрещён |
| `sensorFlags` | `uint8_t 0..7`, `(value & ~0x07)==0`; при отсутствии sensor capability только `0` |
| `optionFlags` | `uint8_t 0..7`, `(value & ~0x07)==0` |
| `relay` | exact `1..4` |
| `state` | exact bool `0/1` |

#### `uint16_t` configuration

| Поле | Домен | Start semantic |
|---|---|---|
| `mixerRpm` | `0..65535` | mode mixer: `>=1` |
| `mixerRunSec`, `mixerPauseSec` | `0..65535` | `0` допустим |
| `pumpMlHour` | `0..65535` | mode pump: `>=1` |
| `pumpPauseSec` | `0..65535` | `0` допустим |
| `fillingMl`, `fillingMlHour` | `0..65535` | mode filling: оба `>=1` |
| `stepsPerMl` | `1..65535` | обязателен для pump/filling apply/save/start |

`apply_i2c_stepper_args()` заменяется на `parse_i2c_stepper_patch(...) -> NumericInputResult`. Helper начинает с `candidate = current`, парсит все предоставленные поля во временные scalar locals, выполняет device/caps/cmd cross-validation и только затем присваивает готовый `candidate` вызывающему draft. На ошибке исходный `I2CStepperDevice` и candidate caller-а byte-for-byte неизменны.

Command schemas:

- `status`: только `device`/`cmd`, config payload запрещён;
- `stop`: только `device`/`cmd`, config payload запрещён;
- `relay`: обязательно ровно по одному `relay` + `state`, другие config fields запрещены;
- `apply`/`save`: optional patch; missing сохраняет current staged field; итоговая mode/caps/config комбинация обязана быть валидна;
- `start`: optional patch, затем positive start-semantic для активного mode;
- `calstart`/`calfinish`: только pump с filling capability; `calstart` требует валидного `stepsPerMl` и rate fields, `calfinish` не принимает config payload.

### 4. `/i2cpump`

| Поле | Тип | Домен |
|---|---|---|
| `stop` | presence action | несовместим с `speed`/`volume` |
| `speed` | finite float, л/ч | `>0`; checked rate→steps и steps→ml/h оба дают `1..65535` без clamp |
| `volume` | целое число мл | `1..min(65535, floor(UINT32_MAX / stepsPerMl))`; fractional value запрещено, потому что protocol `fillingMl` — `uint16_t` |

До произведения проверяется persisted `SamSetup.StepperStepMlI2C > 0`; legacy substitution `I2C_STEPPER_STEP_ML_DEFAULT` в этом request path удаляется. `targetSteps` вычисляется как `uint64_t(volumeMl) * stepsPerMl`, проверяется против `UINT32_MAX`, только затем cast. `speedSteps`, `fillingMlHour`, `targetSteps`, `targetMl`, `fillingMl`, `stepsPerMl` публикуются одним `PendingI2CPumpCmd` commit.

### 5. `/program`, `/ajax_col_params`, `/calibrate`

| Endpoint/поле | Домен | Atomicity |
|---|---|---|
| `/program?vless` | finite `0.001..10000.0` л | duplicate/invalid не меняет `BoilerVolume`, `heatLossCalculated`, `heatStartMillis`, description или pending program; отсутствие сохраняет значение; отсутствие fallback `30` остаётся regression contract |
| `/ajax_col_params?mat` | exact enum `{0,1,2}`; missing = `2` | duplicate/invalid → JSON `400`, calculation не вызывается |
| `/calibrate?stpstep` start | integer `1..STEPPER_MAX_SPEED` (`8000` в live tree) | parse в local; `CurrrentStepperSpeed` меняется только при successful queue/loop commit |

`/calibrate` дополнительно:

- `pump` exact string `local`/`i2c`, missing = `local`;
- ровно одно из `start`/`finish`;
- start требует `stpstep`; finish отвергает `stpstep`, чтобы stale input не менял speed;
- I2C start требует present + filling capability + valid nonzero calibration snapshot;
- queue busy не меняет `CurrrentStepperSpeed`/calibration globals.

Значение `vless` получает широкий, но конечный engineering ceiling 10 000 л: он заведомо выше поддерживаемого DIY-сценария и не позволяет бесконечно раздувать downstream heat-energy products. Это новый явный API contract, а не auto-correction.

### 6. A-09 program text

Существующий A-09 contract сохраняется и фиксируется regression tests:

- rect: volume `0..65535` (pause требует `>0`), non-pause speed finite `>0`, capacity `0..CAPACITY_NUM`, temp/power finite;
- dist: speed/power finite, capacity `0..CAPACITY_NUM`;
- beer: temp finite, time finite `>=0`, device type `0..255`, on/off `0..65535`, sensor `0..4`, speed в текущем signed-long contract;
- NBK: speed/power finite, exact rows `H/S/O/W`.

A-10 не переписывает активный A-09 draft/commit. После A-09 reviewer PASS выполняется повторный scan: `program_io.h` использует только `numeric_parse.h`, invalid output не меняется, ни один field не принимает NaN/Inf.

### 7. WebSerial (`Samovar.ino::recvMsg`)

- Maximum message length задаётся фиксированной константой; overlength reject без накопления неограниченного `String`.
- Grammar: exact `WFpulseCount=<uint16>` либо exact `print`, один `=`, без лишнего suffix/second value.
- `WFpulseCount`: `0..65535`, parse до `water_pulse_count_set()`.
- Invalid/unknown command отвечает `ERR BAD_REQUEST`/`ERR UNKNOWN_COMMAND`, не echo-success и не меняет counter.

### 8. Blynk (`Blynk.ino`)

Использовать raw `param.asStr()` и те же pure domain helpers; `asFloat()/asInt()` запрещаются.

| Pin | Домен | Ошибка |
|---|---|---|
| `V16` power setpoint | тот же dynamic `0..power_input_max(snapshot)` | не вызывать `set_current_power`; `SendMsg` с pin/error code |
| `V17` withdrawal rate | finite `>0`, checked rate→`uint16_t` steps при `StepperStepMl>0` | не вызывать `set_pump_speed` |
| `V12` next/start | exact bool `0/1`; только `1` ставит action | invalid не ставит queue |
| `V3` start/reset | exact bool `0/1` | invalid не запускает и не reset-ит |

`V4`, `V13`, `V18` не читают numeric payload и остаются presence-trigger handlers; A-06/A-12 позже унифицирует их operation lifecycle.

### 9. UART responses (`power_regulator.h`/`mod_rmv.ino`)

KVIC fixed packet `TxxxYYYm\r`:

- ровно 8 data chars перед `\r`;
- `xxx` и `YYY` — ровно по 3 hex digits;
- current raw `31..2549` (сохранение live validity window), target raw `0..2550`, затем `/10.0f`;
- mode exact one digit `{0,1,2,3}`;
- все поля валидируются в locals, затем одним commit обновляются current/target/mode/online timestamp;
- permissive `hexToDec()` удаляется из `power_regulator.h` и декларация из `samovar_api.h`.

SEM decimal responses:

- `+SS?` — exact один ASCII digit из `{0,1,2}` (`WORK/SPEED/SLEEP`), без whitespace/suffix; invalid mode не меняет `current_power_mode` и online timestamp;
- `+VO?`/`+VS?` — strict integer ASCII, `0..floor(power_input_max(snapshot))`;
- trailing garbage/empty/negative/overflow reject;
- invalid response не обнуляет показание и не обновляет `reg_online/last_reg_online`;
- diagnostic rate-limited, чтобы битый UART не забивал log.

`mod_rmv.ino::rmvk_parse_uint8_response()` уже проверяет digits, overflow `< RMVK_ERROR`, trailing whitespace и не меняет output на ошибке; его не заменять без необходимости, только добавить regression cases в A-10 scan/tests.

## Контракты ошибок

| Surface | Parse/semantic error | Busy после valid parse |
|---|---|---|
| `/command` | HTTP `400`, `text/plain`, exact `BAD_REQUEST` | существующий `503 BUSY` |
| `/save` | HTTP `400`, `Invalid <field>: <numeric_error_code>` | существующий `503 BUSY...` |
| `/program` | HTTP `400`, JSON `{ok:false,err:"Invalid <field>: <code>",program:""}` | JSON `503` |
| `/ajax_col_params` | HTTP `400`, JSON `{error:"Invalid mat",code:"..."}` | не применимо |
| `/i2cpump` | HTTP `400`, `Invalid <field>: <code>` | `503 BUSY` |
| `/i2cstepper` | HTTP `400`, JSON `{error:"Invalid <field>",code:"..."}` | JSON `503` |
| `/calibrate` | HTTP `400`, `BAD_REQUEST: <field>: <code>` | `503 BUSY` |
| WebSerial | `ERR <field> <code>` | не применимо |
| Blynk | warning с pin + code; никакого side effect | существующая queue warning |
| UART | rate-limited warning + старое snapshot state | не применимо |

Ошибки содержат только имя поля и стабильный numeric error code, без исходного значения. В HTTP error response ставится `Cache-Control: no-store`; будущий operation result W2 может переносить тот же code без изменения numeric semantics.

## File/symbol-level план реализации

### Шаг 0 — freeze зависимостей и baseline

Зависимости:

1. Дождаться A-11 `PASS: no errors, no warnings`, потому что A-11 меняет `Samovar.ino`, `WebServer.ino`, `power_regulator.h`, `samovar_api.h` и pending/safety contracts.
2. Дождаться A-09 integration PASS, потому что `/program`, `/save`, pending program DTO и `program_io.h` ещё меняются.
3. После freeze заново перечитать live symbols и зафиксировать baseline hashes/diff только A-10 scope.
4. Зафиксировать method matrix и не менять transport: POST `/command|program|save`; GET `/ajax_col_params|i2cpump|i2cstepper|calibrate`.

Baseline commands:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 tools/run_smoke_tests.py
PYTHONDONTWRITEBYTECODE=1 python3 tools/smoke_numeric_parse.py
PYTHONDONTWRITEBYTECODE=1 python3 tools/smoke_program_atomic.py
PYTHONDONTWRITEBYTECODE=1 python3 tools/smoke_program_io_contract.py
PYTHONDONTWRITEBYTECODE=1 python3 tools/smoke_handle_save_staging.py
PYTHONDONTWRITEBYTECODE=1 python3 tools/smoke_i2cstepper_atomic.py
pio run -e Samovar
pio run -e Samovar_s3
pio run -e Samovar_no_power
pio run -e Samovar_rmvk
pio run -e Samovar_sem
pio run -e Samovar_lua_mqtt
pio run -e Samovar_alarm_button
```

### Шаг 1 — generic parser и pure domain layer

Изменить:

- `numeric_parse.h`: generic primitives, checked arithmetic, stable error codes; оставить Arduino-free;
- создать `control_numeric_input.h`: domain constants, typed DTO/result, pure functions без globals/Arduino;
- добавить `control_numeric_input.h` в `tools/static_analysis_sources.json` в том же change-set; manifest completeness из `smoke_ci_contract.py` является acceptance gate;
- `tools/smoke_numeric_parse.py`: расширить lexical/overflow/hex/arithmetic matrix;
- создать `tools/smoke_control_numeric_input.py`: host-compile production header и проверить все домены.

Acceptance:

- output sentinel byte-for-byte не меняется на каждой ошибке;
- `nan/inf/-inf/1e999`, empty, internal whitespace, trailing garbage, overflow отвергаются;
- min/max, min-1/max+1, dynamic calibration/power bounds покрыты;
- no heap, `String`, Arduino include, exception, RTTI;
- отдельный reviewer PASS до transport migration.

### Шаг 2 — `/save` и A-09 handoff

Изменить `WebServer.ino`:

- заменить `parse_save_long_arg`, `parse_save_float_arg`, `apply_save_*` на `numeric_parse.h` results;
- добавить unique-param adapter с явным source/cardinality;
- проверить `stepperstepml % 100 == 0` до деления;
- pre-validate A-09 `ProgramDraft` до общего queue commit;
- stage setup/mode и неизменённый A-09 program update одним существующим locked queue commit; `PendingProgramUpdate`/`program_io.h` не менять;
- сохранить текущие field ranges из inventory.

После миграции обновить `tools/smoke_handle_save_staging.py`: запрет legacy parsers, duplicate body/query, first/last field failure, zero pending/global changes.

### Шаг 3 — `/command` и typed pending values

Изменить:

- `WebServer.ino::{get_web_command_key, web_command_parse_float, web_command}`: сначала exact-one action/cardinality, затем typed parse, затем canonical throttle key и queue;
- `Samovar.ino` pending DTOs: заменить raw float там, где downstream narrowing зависит от calibration, на готовые typed steps/kind;
- `control_numeric_input.h`: command-specific pure parsers;
- `tools/smoke_api_routes.py` и новый `tools/smoke_numeric_command_contract.py`.

Проверить malformed `distiller/startbk/startnbk` особенно: ни `SAMOVAR_POWER`, ни другой command не попадает в queue.

### Шаг 4 — I2C request drafts

Изменить:

- `WebServer.ino::apply_i2c_stepper_args` → result-returning full parse/validate function;
- `/i2cstepper` handler — exact schema/cardinality, staged commit only after success;
- `/i2cpump` handler — nonzero calibration, checked products/conversions, no default calibration/clamp;
- `Samovar.ino::{PendingI2CStepperCmd, PendingI2CPumpCmd}` только при необходимости typed invariants; execution path не reparses raw data;
- `I2CStepper.h` — saturating conversion functions не использовать на external request path; если нужен общий checked helper, он должен делегировать pure primitive, а не дублировать формулу;
- `tools/smoke_i2cstepper_atomic.py`, `tools/smoke_numeric_i2c_contract.py`.

Fault cases: invalid последний field, unsupported caps/mode, partial relay pair, stop+payload, `UINT32_MAX` product edge, calibration zero, result `65535/65536`.

### Шаг 5 — program metadata, column и calibration

Изменить:

- `WebServer.ino::web_program` — unique-param gate для `vless`/`Descr`, bounded parse `vless` до side effects, regression отсутствия fallback 30; queue отдельный A-10 metadata draft вместе с неизменённым A-09 update;
- `Samovar.ino` — отдельный metadata slot (presence flags, `float boilerVolume`, bounded description `<=250`) и единый loop-side success/reject path; `PendingProgramUpdate` не расширять;
- `/ajax_col_params` — exact enum, duplicate handling, JSON 400;
- `calibrate_command` — local typed draft, exact start/finish schema, commit speed only after queue success;
- `Samovar.ino` loop-side apply — single commit для boiler/calibration values;
- `tools/smoke_program_atomic.py`, `tools/smoke_calibration_ux.py`, новый `tools/smoke_numeric_misc_routes.py`.

### Шаг 6 — WebSerial, Blynk и regulator protocol

Можно выполнять параллельно двумя независимыми developer-сабагентами после frozen A-11:

- branch 6A: `Samovar.ino::recvMsg`, `Blynk.ino`, host/static tests;
- branch 6B: `power_regulator.h::triggerPowerStatus`, `hexToDec` removal, `samovar_api.h`, protocol tests.

Объединять только после отдельных reviewer PASS и проверки пересечения с A-11. `mod_rmv.ino` production logic не менять, если regression подтверждает текущий strict parser.

### Шаг 7 — удалить второй источник parsing truth

После `rg` всех callers:

- удалить `parseLongSafe` и `parseFloatSafe` из `string_utils.h`;
- оставить только unrelated `copyStringSafe`/`toJsonString`;
- repo gate запрещает `.toInt()/.toFloat()/asInt()/asFloat()` в first-party external-input paths;
- допускаются только явно перечисленные internal conversions, если они не разбирают внешнюю строку; каждый exception фиксируется в тесте с причиной.

### Шаг 8 — UI contract и Playwright

Изменить:

- `data/app.js`: один shared finite/bounded/integer validator и единое отображение server `400`; server остаётся source of truth;
- `data/setup.htm`: submit pre-validation всех numeric `/save` fields по inventory, нормализация запятой только перед отправкой, сохранение dirty state и видимый server `400/503`;
- `data/index.htm`: `pumpspeed`, `voltage`;
- `data/beer.htm`, `data/bk.htm`: `watert`, `voltage`;
- `data/distiller.htm`: `voltage`;
- `data/nbk.htm`: `pnbk`, `voltage`;
- `data/program.htm`: `vless`, `mat` request error;
- `data/calibrate.htm`: `stpstep`;
- `data/i2cstepper.htm`: integer/range validation всех config fields и parse server error body вместо generic status text.

UI разрешает локализованную запятую только как явное client-side преобразование в точку перед отправкой; direct HTTP с запятой отвергается. UI не показывает success и не снимает dirty state при HTTP 400.

Обязательная проверка через `playwright-cli`:

- desktop `1440x900` и mobile `390x844`;
- light/dark;
- все девять страниц (`setup` плюс восемь остальных страниц из write-scope);
- min/max valid отправляются ровно один раз;
- empty, garbage, NaN/Inf text, boundary±1 не отправляются или показывают server error;
- mocked `400/503` не отображается как success;
- console errors/warnings = 0.

Создать/расширить browser harness под `tools/test_numeric_input_ui_browser.py`; запускать его только через project-mandated Playwright CLI workflow.

### Шаг 9 — codebase map

После production/test/UI changes обновить `Last reviewed` и contracts в nodes:

- `webserver-ino.md`;
- `samovar-ino.md`;
- `i2cstepper-h.md`;
- `power-regulator-h.md`;
- `blynk-ino.md`;
- `program-io-h.md`;
- `string-utils-h.md`;
- `samovar-api-h.md`;
- `data.md`;
- `tools.md`.

Если для `control_numeric_input.h` mapper создаёт новый node — добавить его обычным mapper workflow, не вручную дублировать graph topology.

## Test strategy

### Host behavioral table

Для каждого scalar/domain helper:

- exact min/max;
- min−1/max+1;
- `""`, whitespace-only, leading/trailing ASCII whitespace;
- `1x`, `1 2`, `--1`, `+`, decimal перед integer;
- integer/float overflow;
- `nan`, `NaN`, `inf`, `+inf`, `-inf`, `infinity`, `1e999`, underflow `1e-9999`;
- duplicate/missing/conflict cases;
- output/state sentinels неизменны при failure.

Отдельные adversarial cases:

- invalid последнего из 12 I2C fields после 11 valid;
- relay=1 без state, duplicate state, mode/caps mismatch;
- target product `UINT32_MAX-1`, `UINT32_MAX`, `UINT32_MAX+1`;
- rate conversion до/после `1` и `65535` steps, ml/h `65535/65536`;
- `pnbk=7999.999`, `8000`, `8000.1`, `8999`, `9000`, `9000.1`;
- power max меняется при SEM resistance snapshot;
- KVIC packet с одним non-hex char и valid suffix;
- Blynk malformed value никогда не вызывает mocked side effect;
- WebSerial `WFpulseCount=1=2`, `65536`, `-1`, NUL/overlength.

### Production wiring/static tests

Static checks не заменяют behavior tests, но обязаны доказать wiring:

- parser/semantic gate расположен до queue/global write;
- pending flag не выставляется в failure branch;
- no `toInt/toFloat/parseLongSafe/parseFloatSafe` в `WebServer.ino`/`Samovar.ino` external handlers;
- no `asInt/asFloat` в Blynk write handlers;
- no `toInt/hexToDec` в regulator response parsing;
- `/program` не содержит `BoilerVolume = 30.0f` fallback;
- `apply_i2c_stepper_args` возвращает result и commit следует после full validation.
- frozen A-09 signatures/types/functions (`ProgramDraft`, `PendingProgramUpdate`, parse/serialize/commit/clear helpers) byte-for-byte не изменены;
- exact transport method matrix не изменена: POST `/command|program|save`, GET `/ajax_col_params|i2cpump|i2cstepper|calibrate`;
- invalid SEM `+SS?` mode оставляет `current_power_mode` и online timestamp byte-stable.

### Firmware/build matrix

Обязательны все feature branches, иначе SEM/RMVK/no-power paths не проверены:

```sh
pio run -e Samovar
pio run -e Samovar_s3
pio run -e Samovar_no_power
pio run -e Samovar_rmvk
pio run -e Samovar_sem
pio run -e Samovar_lua_mqtt
pio run -e Samovar_alarm_button
pio run -e Samovar -t buildfs
PYTHONDONTWRITEBYTECODE=1 python3 tools/run_smoke_tests.py
PYTHONDONTWRITEBYTECODE=1 python3 tools/run_cppcheck.py --timeout 600 --report /tmp/samovar-a10-cppcheck.txt
git diff --check
```

`cppcheck` blocking report: 0 errors/warnings; informational `toomanyconfigs` допустим только как tool information в уже согласованном W0 runner contract.

## Stack/RAM/flash budget

- `numeric_parse.h`/`control_numeric_input.h`: 0 mutable static/global bytes, 0 heap allocations, 0 tasks/mutexes.
- Самый большой request draft (`I2CStepperDevice` + scalar temporaries/result) — compile-time `static_assert <= 96` bytes.
- `PendingProgramMetadata` имеет `static_assert(sizeof(PendingProgramMetadata) <= 264)`; fixed `Descr[251]`, flags и finite volume не выносятся в heap.
- Typed pending structs должны заменить raw slots; суммарный net `.bss` рост A-10 `<= 384` bytes.
- Ни один handler не создаёт runtime descriptor table, `std::function`, `std::vector`, exception или JSON DOM.
- High-water regression web/loop task на hardware smoke `<= 128` bytes против frozen baseline; при отсутствии стенда compile-time sizes и map обязательны, hardware gate честно отмечается как требующий устройства, но не заменяется догадкой.
- Release flash delta A-10 `<= 16 KiB` на каждом environment; превышение требует устранить duplicated error strings/inline instantiations, а не увеличивать лимит молча.
- `firmware.map`/PlatformIO memory output сохраняются до/после; app partition limit не должен приближаться менее чем на 128 KiB free headroom.

## Параллелизация без конфликтов

После Step 1 и frozen A-09/A-11:

| Ветка | Write scope | Можно параллельно с |
|---|---|---|
| API/HTTP | `WebServer.ino`, numeric route tests | Blynk, UI после API contract freeze |
| Loop/WebSerial | `Samovar.ino`, WebSerial/pending tests | Blynk; не с HTTP, если меняется общий Pending DTO |
| Blynk | `Blynk.ino`, Blynk tests | HTTP, UART, UI |
| Regulator protocol | `power_regulator.h`, `samovar_api.h`, protocol tests | Blynk/UI; только после A-11 PASS |
| UI/Playwright | `data/app.js`, перечисленные pages, browser tests | Blynk/UART; старт после фиксации API error/domain contract |

`WebServer.ino` и `Samovar.ino` интегрирует один владелец либо последовательные ветки: shared pending DTO делает их логически связанными. Параллельное редактирование одних строк запрещено.

## Reviewer checkpoints

После каждого шага reviewer-сабагент проверяет полный task diff и возвращает только один из outcomes:

- `PASS: no errors, no warnings`;
- список `ERROR/WARNING` с file:line и точным failure scenario.

Любой `ERROR/WARNING` исправляется тем же developer scope; targeted tests и review повторяются. A-10 закрывается только после:

1. отдельного PASS generic/domain layer;
2. PASS HTTP/pending integration;
3. PASS Blynk/WebSerial/UART;
4. PASS UI/Playwright;
5. финального combined PASS.

## Критерии полного завершения A-10

- Все перечисленные external numeric inputs имеют единственный documented domain.
- Все malformed/duplicate/missing/conflicting values дают явную ошибку до side effect.
- `NaN/Inf/overflow` не проходят ни в program, HTTP, Blynk, WebSerial, ни в regulator string protocol.
- Ни один external product/cast выполняется до проверки диапазона результата.
- Invalid request не меняет global/staged/pending state byte-for-byte и не занимает command slot.
- `distiller/startbk/startnbk=garbage` никогда не ставят `SAMOVAR_POWER`.
- `vless` не имеет fallback 30.
- Legacy `parseLongSafe/parseFloatSafe`, permissive `hexToDec`, external `toInt/toFloat/asInt/asFloat` удалены из main first-party paths.
- Host, static, семь builds, LittleFS build, blocking cppcheck, Playwright desktop/mobile light/dark и `git diff --check` проходят.
- Codebase map синхронизирован.
- Финальный reviewer сообщает exact `PASS: no errors, no warnings`.

## Rollback

Rollback только целыми слоями в обратном порядке:

1. UI validation/error rendering;
2. transport adapters/pending DTO;
3. domain helpers;
4. generic parser additions.

Нельзя откатывать parser, оставляя handlers с новым typed contract, либо возвращать `toInt()/toFloat()` как временный fallback. При regression возвращается предыдущий целый A-10 checkpoint и повторно согласуется домен, а не добавляется молчаливая совместимость.
