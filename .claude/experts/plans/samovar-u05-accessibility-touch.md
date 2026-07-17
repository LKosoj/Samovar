# U-05 — accessibility, keyboard и touch без redesign

## Статус

**Завершено:** реализация, полный gate и независимый review закрыты точной
строкой `PASS: no errors, no warnings`. U-05 не добавил routes, product state,
редизайн, local Ace или новый runtime; editor/CDN, backend и существующие
request contracts остались неизменными.

Фактическая проверка: focused static/contracts `8/8`; accessibility browser
`88/88` page cells, `207/207` click/Enter/Space actions и `12/12` uploads;
отдельный mobile Lua/top-controls visual matrix `20/20`; полный изолированный
Playwright block `10/10`, включая U-03 `60+6+160` и U-04 `168/168`; smoke
`65/65`; buildfs `2/2`; blocking cppcheck exit `0` без errors/warnings; две
fixed-epoch `Samovar` clean-сборки дали `5/5` byte-identical artifacts; все
семь PlatformIO environments PASS без compiler errors/warnings. Текущие
размеры: LittleFS source `45/450742` из `786432`, raw update `23/431264`,
`style.css` `22293`, canonical `style.css.gz` `5143`. Exact U-05 allowlist и
`git diff --check` — PASS; mutation-проверка CSS expectations — PASS.

## 1. Цель и доказанные defects

Исправить first-party semantic/touch defects из audit, сохранив существующие
экраны и функции:

- 11 основных pages не имеют `lang`;
- в `setup.htm` два `id="selftest"` и 51
  text/password/range/select/textarea control без программной label;
- history/clear actions в пяти mode pages и clear-message actions в
  `program/chart` — click-only `div`;
- последний message из `app.js` рендерится click-only `div`;
- generated plus/minus в `index/program/beer/distiller` — interactive `img`;
- четыре upload actions (`beer`, `program`, `setup`, `brewxml`) используют
  `input[type=file]{display:none}` и click-only proxy label, поэтому native file
  control недоступен с клавиатуры;
- важные action controls имеют высоту около 34 px, а tablinks — около 34 px на
  mobile и 42 px на desktop вместо project target 44×44;
- focus/accessible-name/state contracts не проверяются автоматически.

U-05 не добавляет product functionality. Запрещены новая safety strip,
reorder текущего режима/нагрева/tabs, alarm acknowledge, новые panels/routes,
mobile navigation или redesign.

Готовность: unique IDs, named first-party controls, native keyboard behavior,
visible focus, critical targets `>=44x44`, post-U-03 contrast и post-U-04 no
overflow, all existing actions/request bodies unchanged, reviewer exact
`PASS: no errors, no warnings`.

## 2. Prerequisites и порядок

1. Начать только после последовательных clean PASS U-06 -> U-03 -> U-04.
2. U-05 — последний UI writer; concurrent `data/**`/manifest/browser edits
   запрещены.
3. Read-only planner-subagent `gpt-5.6-terra` повторно снимает live interactive
   element/label/ID/tab-order inventory. Молчаливая замена модели запрещена.
4. Один developer реализует task; отдельный reviewer проверяет весь diff и
   browser evidence. Любое замечание исправляется до clean rerun.

## 3. Замороженное поведение

Неизменны:

- page/section/tab order и visible product text, кроме точных label association;
- form `name`, type, value, template tokens и serialization;
- onclick target, handler arguments, confirmation text и request count/body;
- telemetry/program/I2C/chart behavior и all routes;
- U-03 colors и U-04 layout rules;
- U-06 theme storage/toggle/glyph/title policies, включая page-specific
  `dynamicThemeTitle`; U-05 добавляет semantics, но не унифицирует observable
  title behavior;
- весь editor shell `data/edit.htm` и `data/edit.htm.gz`: оба файла остаются
  byte-for-byte frozen по CDN decision, включая текущий outer `lang`; U-05 не
  проверяет и не меняет ни shell, ни Ace internals.

Native conversion должна вызывать старый handler ровно один раз на click,
Enter или Space. Keydown-to-click shim, duplicate listener и positive tabindex
запрещены.

## 4. Exact semantic changes

### 4.1 Language и IDs

Добавить `lang="ru"` ровно в:

```text
index beer distiller bk nbk program setup chart calibrate i2cstepper brewxml
```

`wifi.htm` уже `ru` и остаётся read-only regression. `edit.htm(.gz)`
остаётся вне U-05 и контролируется только frozen SHA/size:
`26b7e41df2a0a0197a14b9cf129f808fd001e760df4ed7c16df7a35a10b03ce6`
для raw и
`bef3ce7e5c68a3cef89643ae1a22b5130c49b9983a9b69b71ffdd272dbe153f5`
для gzip.

В `setup.htm` сохранить `#selftest` за кнопкой самотеста; второму sensor-rescan
control задать `id="scanSensorsButton"`, сохранив его `name` и вызов
`rescanSensors()`. ID не должен совпадать с именем глобальной функции.

Static и live DOM после dynamic rows обязаны иметь zero duplicate IDs.

### 4.2 Native actions

На `index/beer/distiller/bk/nbk` заменить existing click-only nodes на native:

- `button[type=button].history-trigger` с `aria-controls="historyBox"` и
  `aria-expanded`;
- `button[type=button].history-clear`;
- `button[type=button].messages-clear` с `aria-controls="messages"`.

`program.htm` и `chart.htm` получают native `.messages-clear`. Existing
`SamovarApp.showHistory/clearHistory/clearMessages` handlers не переименовывать.

В `index.htm`, `program.htm`, `beer.htm`, `distiller.htm` каждое generated
plus/minus action становится `button[type=button].program-row-action`. Existing
image остаётся decorative `img[alt=""]`; button получает row-specific
accessible name и ровно один прежний `addLine(...)`/`removeLine(...)` с теми
же arguments.

В `beer.htm`, `program.htm`, `setup.htm`, `brewxml.htm` exact native file input
остаётся в DOM/tab order и получает visually-hidden CSS вместо `display:none`.
Существующие label, `for`, `accept`, `onchange` и handler сохраняются; visible
focus input-а отображается на proxy label через `:focus-within`: ровно четыре
существующих pair-wrapper получают один exact class `.file-upload-control`, а
порядок `label + input` не меняется. `tabindex`, keydown/click shim и второй
upload handler запрещены.

В `app.js` изменить только existing symbols:

- `renderMessage`: последний dismissible message — native
  `button[type=button].message-dismiss`, остальные остаются text;
- `showHistory`: `aria-expanded` отражает фактическую visibility;
- `applyTheme`: existing icon-only `.theme-toggle` получает universal exact
  `aria-label` `Включить тёмную тему` в light state или
  `Включить светлую тему` в dark state и согласованный `aria-pressed`; glyph и
  существующая page-specific title policy сохраняются. `title` не
  унифицируется и U-06 `dynamicThemeTitle` не обесценивается;
- `openTab`: семантическое состояние добавляется только controls, чей handler
  реально вызывает `SamovarApp.openTab(event, target)`, а target является
  existing `.tabcontent`. Только такие native `.tablinks` получают
  согласованные `aria-pressed`, а их panels — `aria-hidden`; существующий
  `display` contract сохраняется, полный ARIA tab widget/`role=tablist`/
  arrow navigation не вводить.

В `setup.htm` его существующий local `openTab` получает только ту же
синхронизацию `aria-pressed/aria-hidden`; transport, order и tab switching не
меняются. Navigation `.tablinks` с
`location.href='/i2cstepper.htm'`, а также Back/current controls на
`i2cstepper.htm`, не являются tabs и не получают tab roles/state/
`aria-controls`. Неиспользуемый `program.htm::openTab` не чистить попутно.

`setup.htm::applyTheme` и `i2cstepper.htm::applyTheme` остаются локальными
owners и получают только те же `aria-label/aria-pressed` updates; storage,
toggle, glyph и current title behavior не менять. Переводить их на новый
shared wrapper/shim или второй theme API запрещено.

### 4.3 Labels и groups

Правило: static visible control получает unique stable `id` и visible
`label[for]` из уже существующего соседнего русского текста. `title` и
placeholder не заменяют label. `aria-label` разрешён только для generated
repeated row actions и existing icon-only `.theme-toggle`; у theme toggle это
только две exact action-label из 4.2. Остальные controls не получают generic
`aria-label`.

Узкое исключение live inventory: на `beer` и `bk` controls `PWM` (range) и
`PWMt` (text) — два синхронизированных представления одной скорости насоса, а
в page существует один visible text `Скорость насоса:`. Сохранить этот текст
ровно один раз как `<span id="pump-speed-label">...` и связать оба controls
через exact `aria-labelledby="pump-speed-label"`. Hidden duplicate label, два
повтора visible phrase, новый visible text, `aria-label` или новый group/role
запрещены.

Exact 51-control setup inventory:

```text
mode DistTemp DistTimeF ColDiam ColHeight PackDens MaxPressureValue
SteamAddr DeltaSteamTemp SetSteamTemp SteamDelay
PipeAddr DeltaPipeTemp SetPipeTemp PipeDelay
WaterAddr DeltaWaterTemp SetWaterTemp WaterDelay
TankAddr DeltaTankTemp SetTankTemp TankDelay
ACPAddr DeltaACPTemp SetACPTemp ACPDelay
StepperStepMl StepperStepMlI2C Kp Ki Kd StbVoltage BVolt
NbkIn NbkDelta NbkDM NbkDP NbkSteamT NbkOwPress
blynkauth tgtoken tgchatid videourl TimeZone HeaterR LogPeriod
rele1 rele2 rele3 rele4
```

Для named control exact `id=name`; `name` не менять. Отдельно от этих 51
form controls `#PackDensDisplay` становится exact
`<output id="PackDensDisplay" name="PackDensDisplay" for="PackDens">` только
после red/green test существующего `.value` update и visible percentage.

Generated program rows получают accessible name только из уже видимого row/
column context:

- существующим visible column headers и видимому номеру каждой строки задать
  stable IDs; существующие `_lnIdx` row/control IDs остаются стабильными
  handler targets и не перенумеровываются. Existing `set_num` обновляет только
  visible row number, row accessible text и add/remove `aria-label`;
- каждый generated input/select получает unique ID из его существующего prefix
  плюс row index и
  `aria-labelledby="<row-id> <column-header-id>"`;
- closed column ownership: index — `ptype/pvolume/pspeed/pnum/pvolt` =
  type/volume/speed/container/power; beer —
  `ptype/ptemp/ptime/pmixer/dt` =
  type/temperature/time/mixer/sensor; distiller —
  `ptype/ptemp/pnum/ppower` = type/value/container/power; program —
  `pnum/speed/percent/ptype/pvolt/pvl/tm` =
  container/speed/percent/type/power/output/time;
- disabled calculated `pvl<N>`/`tm<N>` остаются named; hidden transport
  fields/spans остаются hidden и non-focusable;
- plus/minus button может иметь exact row-specific `aria-label`, которое
  синхронно с текущим visible row number. Generated form controls generic
  `aria-label` не получают.

Те же row+column IDs и
`aria-labelledby="<row-id> <column-header-id>"` применяются к восьми статическим
NBK controls `pspeed1..4`/`ppower1..4`: отдельного существующего visible
`label[for]` для каждой комбинации строки и колонки в live markup нет.

`fieldset/legend` conversion исключён из U-05: live plan не доказывает exact
wrapper/legend ownership, а speculative grouping изменит post-U-04 geometry и
может дублировать visible headings. Existing sections `Main`, `Temp`, `Pump`,
`Beer`, `NBK`, `Other` сохраняются; task ограничен exact `label[for]` и native
control semantics из closed inventory.

Closed label inventory других pages:

- index: `Voltage`, `pumpspeed`, `lua_str_i`, visible `Descr/WProgram`;
- beer: `Voltage`, `m_type`, `m_direction`, `m_time`, `m_pause`, shared visible
  owner `pump-speed-label` для `PWM/PWMt`, `lua_str_i`, visible
  `Descr/WProgram`;
- distiller: `Voltage`, `lua_str_i`, visible `Descr/WProgram`;
- bk: shared visible owner `pump-speed-label` для `PWM/PWMt`, `Voltage`,
  `lua_str_i`;
- nbk: `Voltage`, `lua_str_i`, visible `Descr/WProgram`, `pspeed1..4`,
  `ppower1..4`;
- program: `loadprogram`, `heaterMaxPower`, `vless`, `vlssp`, `vlp`, `vlhp`,
  `vltp`, `trest`, `sum`; hidden `WProgram/WProgram1` не focusable/exposed;
- calibrate: `pump_type`, `kstepperspd`, `stepperstepml`;
- i2cstepper: `mixerRpm`, `mixerRunSec`, `mixerPauseSec`, `pumpMode`,
  `pumpMlHour`, `pumpPauseSec`, `fillingMl`, `fillingMlHour`, `stepsPerMl`;
- chart/brewxml: сохранить существующие `refresh/fileToLoad` labels; исправить
  только clear/native/hidden semantics, перечисленные выше.

Live inventory 2026-07-14: у пяти `lua_str_i` нет отдельного существующего
visible label text — рядом находится только action «Выполнить Lua». Пользователь
выбрал короткую видимую метку exact `Lua:` с обычным `label[for="lua_str_i"]`
на `index`, `beer`, `distiller`, `bk`, `nbk`; generic `aria-label` и scoped
ARIA association не добавлять. Это единственное разрешённое новое visible label
text и оно не меняет `runLuaString()`/`luastr=` behavior.

Если live inventory расходится с closed list, до patch обновить plan/evidence;
не добавлять generic aria-label всем controls.

### 4.4 Focus и touch

В `style.css` объединить, а не дублировать существующие
`.button:focus-visible` и `input:focus-visible` в один closed selector contract:
`a[href]`, `button`, `input:not([type=hidden])`, `select`, `textarea`, `summary`.
Он использует post-U-03 tokens, не вызывает layout shift и не содержит
`outline:none/0`. Для native file input тот же merged rule включает exact
`.file-upload-control:focus-within .custom-file-upload` visible-focus owner;
input остаётся реальным tab target. Третий независимый focus-rule запрещён.

Actual element, а не pseudo hit-area, должен иметь `min-width/min-height:44px`
для `.theme-toggle`, `.tablinks`, `.button`, `.history-trigger`,
`.history-clear`, `.messages-clear`, `.message-dismiss`,
`.program-row-action` и visible I2C/state action buttons.

На 320/390 controls могут wrap по U-04 rules, но не перекрываться, не выходить
за viewport и не менять section order.

Focused live browser inventory после 44 px conversion доказал existing overflow
`89 px` на `390x844` в `program.htm` и `brewxml.htm`: оба action wrappers имели
inline `width:450px`. Для этих двух существующих wrappers разрешена одна shared
`.program-actions` rule, которая сохраняет desktop `width:450px`/centering и
добавляет только `max-width:100%`/`box-sizing:border-box`. Порядок, controls,
handlers и остальные wrappers не менять; это responsive invariant, не redesign.

## 5. Red-before-green tests

### `tools/smoke_accessibility_ui.py` (new)

Сначала test обязан быть RED на missing lang, duplicate selftest, click-only
nodes, missing labels и touch CSS. После patch проверяет:

1. exact 11 target pages `lang=ru`, wifi regression unchanged; editor raw/gzip
   exact frozen SHA/size and excluded from semantic assertions;
2. zero duplicate static IDs;
3. zero interactive `div`/`img`; every replacement native button has exact
   `type=button`, handler and accessible name;
4. exact 51 setup labels, named/associated `PackDensDisplay` output, generated
   row/header ownership и closed page inventories;
5. no positive tabindex, `outline:none/0`, click-emulating keyboard shim or
   duplicate handler; существующий `app.js` `keydown -> unlockAudio` является
   audio-unlock lifecycle, не shim, и остаётся в allowlist;
6. hidden transport elements excluded from focus/accessibility tree;
7. app.js changes limited to four symbols from 4.2; page-local semantic
   controller changes ограничены `setup::openTab`, `setup::applyTheme` и
   `i2cstepper::applyTheme`;
8. один merged focus contract, keyboard-focusable native file inputs и 44 px
   rules on actual targets;
9. form names, template tokens, routes, commands and handler arguments exact;
10. source/gzip/manifest/projection parity.

### `tools/test_accessibility_ui_browser.py` (new)

Interactive matrix полностью исключает frozen editor shell и Ace internals:

```text
index beer distiller bk nbk program setup chart calibrate i2cstepper brewxml
```

11 pages × 4 viewports (`320x800`, `390x844`, `768x1024`, `1440x900`) ×
light/dark = 88
mandatory scenarios. Ни static accessibility/lang assertion, ни browser/AX
scenario не открывает `edit.htm(.gz)`; отдельный byte-hash contract только
подтверждает frozen pair.

Отдельная exact keyboard/action matrix на `1440x900` light содержит `69`
native action families и `69 x click/Enter/Space = 207` one-call cases:

- history trigger + clear на пяти mode pages = `10`;
- messages clear на семи message pages = `7`;
- last-message dismiss на тех же семи pages = `7`;
- add + remove на четырёх generated-program pages = `8`;
- existing details summaries для Descr/WProgram = `8`;
- реальные tab switches: 14 shared + 6 setup = `20`;
- theme toggles = `8`;
- sensor rescan в setup = `1`.

Отдельная native file-upload matrix содержит четыре controls и
`4 x click/Enter/Space = 12` file-chooser cases.

Через `playwright-cli run-code` test получает live DOM и Chromium CDP
`Accessibility.getFullAXTree`:

- every visible enabled interactive element exposed and named;
- label/control relationship, role/state/hidden semantics exact;
- zero duplicate live IDs after representative generated rows;
- ordered Tab traversal bounded; every focus visible and unobscured;
- click/Enter/Space on each of the exact 64 action families invokes existing
  handler exactly once. Для каждой из `4 x 3` upload cases stable CLI выполняет
  свой exact modal lifecycle: `run-code` с native activation обязан открыть
  ровно один `[File chooser]` без Result/Error, штатная команда
  `playwright-cli upload <isolated-/tmp-fixture>` закрывает его, затем отдельный
  `run-code` проверяет ровно один file, один `change`, один вызов существующего
  load handler и отсутствие неожиданного request/hardware action. Direct
  `setInputFiles`, cancel, synthetic change и keyboard shim запрещены;
- destructive/network controls intercepted or `confirm=false`, без hardware
  action;
- each critical target rect width/height `>=44`, center hit belongs to element,
  no clipping/overlap;
- post-U-03 contrast and post-U-04 scrollWidth invariants remain green;
- zero console warning/error, pageerror, missing/skipped scenario.

No CDN/npm asset or alternate accessibility runner is added to repository.
Browser absence/AX failure is hard FAIL, not skip/fallback.

## 6. Последовательность разработки

1. Freeze post-U-04 DOM/control/request/tab/geometry baseline and green tests.
2. Add static/browser red tests and prove every audit defect before patch.
3. Language на exact 11 pages + duplicate ID; focused tests.
4. Native history/message/program-row actions; exact one-call browser tests.
5. Setup labels без speculative fieldset conversion, затем other page labels
   one page at a time.
6. App semantic state in only four allowed symbols plus exact two local
   `applyTheme` and setup `openTab` scopes.
7. Focus and 44×44; run 320/390 U-04 regression after each CSS group.
8. Full 88 scenarios, gzip/manifests/build/full gates.

## 7. Точный write allowlist

Production:

```text
data/app.js
data/style.css
data/style.css.gz
data/index.htm
data/beer.htm
data/distiller.htm
data/bk.htm
data/nbk.htm
data/program.htm
data/setup.htm
data/chart.htm
data/calibrate.htm
data/i2cstepper.htm
data/brewxml.htm
```

Tests/contracts:

```text
tools/smoke_accessibility_ui.py                      # new
tools/test_accessibility_ui_browser.py               # new
tools/smoke_ui_foundations.py                        # only semantic invariant
tools/smoke_style_cleanup.py                         # only focus/touch invariant
tools/test_numeric_input_ui_browser.py               # only stale selector
tools/test_i2c_pump_ui_browser.py                    # only stale selector
tools/test_program_clear_ui_browser.py               # only stale selector
tools/test_runtime_event_ui_browser.py               # only stale direct-child selector
tools/smoke_shared_ui_controllers.py                 # only stale DOM/selector/baseline
tools/test_shared_ui_controllers_browser.py          # only stale DOM/selector/baseline
tools/smoke_u03_contrast.py                           # only stale DOM/selector/baseline
tools/test_u03_contrast_browser.py                    # only stale DOM/selector/baseline
tools/smoke_u04_responsive_layout.py                  # only stale DOM/selector/baseline
tools/test_u04_responsive_layout_browser.py           # only stale DOM/selector/baseline
web_src/ui-manifest-v1.json
web_update.h
tools/ui_pack_assets_contract.py
tools/smoke_ui_pack_assets.py
tools/fixtures/ui_pack_assets_v1/manifests/ui-limit-cases-v1.json # only derived cap boundary
tools/smoke_web_update_transaction.py
```

`tools/smoke_web_file_writes.py` запускается read-only. Добавлять его в write
allowlist можно только после post-U-04 live re-inventory с именованием exact stale
symbol; текущий tree byte-derived U-05 literal в нём не содержит.

Exact downstream updates:

- `smoke_ui_foundations.py` меняет только semantic inventory/ownership
  assertions; routes, DOM control inventory, theme/I2C/message contracts
  сохраняются;
- `smoke_style_cleanup.py` добавляет только focus/touch selectors и сохраняет
  все прочие CSS hygiene/count assertions;
- `test_numeric_input_ui_browser.py` допускает только native-element selector
  substitution; 36 checks/9 page contracts, request bodies, dirty/error
  assertions сохраняются;
- `test_i2c_pump_ui_browser.py` не считает navigation controls tabs; допускает
  только selector substitution, сохраняя exact GET/method/count и 10 page cells;
- `test_program_clear_ui_browser.py` допускает только selector substitution,
  сохраняя cancel/202/400/409/503, exact POST body и request counts;
- `test_runtime_event_ui_browser.py` допускает только замену устаревшего
  `#messages > div` на точный existing message-class selector; event cursor,
  queue count, transport/schema/commit cases и все failure assertions
  сохраняются;
- U-06 pair `smoke_shared_ui_controllers.py`/
  `test_shared_ui_controllers_browser.py` допускает только адаптацию
  устаревших DOM/selector/baseline expectations к native semantic markup;
  все scenarios и one-owner/one-start/lifecycle/controller invariants
  сохраняются;
- U-03 pair `smoke_u03_contrast.py`/`test_u03_contrast_browser.py`
  допускает только такую же адаптацию DOM/selector/baseline expectations;
  полная page/theme/state matrix, thresholds и no-color-only-state invariants
  сохраняются;
- U-04 pair `smoke_u04_responsive_layout.py`/
  `test_u04_responsive_layout_browser.py` допускает только такую же адаптацию
  DOM/selector/baseline expectations; full viewport/state matrix,
  scrollWidth/containment/no-overlap invariants сохраняются.

Ни одно existing assertion или scenario нельзя удалять, ослаблять либо заменять
shape-only проверкой.

Map after PASS:

```text
.cli-proxy/.codebase_map/nodes/data.md
.cli-proxy/.codebase_map/nodes/tools.md
.cli-proxy/.codebase_map/nodes/web-src.md
.cli-proxy/.codebase_map/nodes/web-update-h.md
```

Status/evidence allowlist только после clean review:

```text
.claude/experts/plans/samovar-u05-accessibility-touch.md
.claude/experts/plans/samovar-audit-remediation.md
.claude/experts/plans/samovar-remaining-remediation-2026-07-12.md
```

`wifi.htm`, `data/edit.htm`, `data/edit.htm.gz`, `chart.js`, Ace
assets/code, C++/INO, routes/schemas, raw/legacy inventories, build
configs/workflows запрещены.

## 8. Gzip/manifest/hash discipline

- Создать только `style.css.gz` через существующий
  `tools.ui_pack_format.canonical_gzip`: exact header
  `1f8b08000000000002ff`, one member, `MTIME=0/FLG=0/XFL=2/OS=255`, two-run
  byte identity и decompression parity.
- `edit.htm`/`edit.htm.gz` не regenerates и сохраняет exact frozen
  SHA/size из 4.1.
- Other changed raw pages/app.js не получают checked `.gz`.
- Update only changed source SHA/size/maxima in UI manifest and existing A-04
  typed projection.
- Derived updates ограничены changed entry/raw_update SHA/size/maxima в
  `ui-manifest-v1.json`, corresponding `WEB_UPDATE_ENTRIES`, а в
  `ui_pack_assets_contract.py` — только
  `EXPECTED_CONTRACT_INPUT_SHA256`, `A10_FREEZE_AGGREGATE_SHA256`,
  `EXPECTED_RAW_SOURCE_TREE_SHA256`, `_RAW_UPDATE_BYTES`,
  `_EXPECTED_UI_TOTALS`; в `smoke_ui_pack_assets.py` — только raw total literals
  в `verify_raw_update_contract()`/`main()`, corresponding messages и exact
  stale cap negative literal. Если exact recomputation пересекает 4 KiB
  boundary, `ui-limit-cases-v1.json` меняет только derived exact/stale cap pair.
  Existing max-pack boundary literals в `main()` меняются только если exact
  recomputation действительно пересекает текущий cap. В
  `smoke_web_update_transaction.py` разрешены только projection total и сообщение
  `verify_static_contract()`, exact 45-file active-data total/message, а также
  механически derived capacity-evidence literals/messages/subset targets
  `baseline_free`, `payload_pass`, `payload_fail` в
  `run_littlefs_capacity_proof()`, только если pinned LittleFS proof подтверждает
  CTZ block-boundary transition. Все значения вычисляются из зафиксированных
  U-05 bytes и подтверждаются реальным capacity run; harness algorithm и
  test/transaction/updater logic менять запрещено.
- Raw-update transaction/importer/generator, version/routes/schema,
  неиспользуемые P1.1 A/B manifest fields и local Ace/pack runtime/security
  unchanged; A/B runtime не добавлять.

## 9. Expected inventory

База после U-04: `64 smoke / 9 browser / 176 durable tools`. U-05 добавляет
ровно два scripts:

```text
после U-05: 65 smoke / 10 browser / 178 durable tools
```

## 10. Gate и reviewer-loop

Browser gate only in isolated environment:

```bash
PW=/tmp/samovar-playwright-cli-0.1.17/node_modules/.bin/playwright-cli
export PATH=/tmp/samovar-playwright-cli-0.1.17/node_modules/.bin:$PATH
export PLAYWRIGHT_BROWSERS_PATH=/tmp/samovar-playwright-browsers
export PYTHONPYCACHEPREFIX=/tmp/samovar-u05-pycache
test "$(command -v playwright-cli)" = "$PW"
test "$("$PW" --version)" = "0.1.17"
```

Последовательно выполнить exact `10/10`: новый
`test_accessibility_ui_browser.py`, U-04, U-03 и семь post-U06 browser suites
(`shared`, `i2c_operation`, `i2c_pump`, `numeric`, `profile_operation`,
`program_clear`, `runtime_event`). Global alpha/fallback runner запрещены.

```text
tools/test_accessibility_ui_browser.py
tools/test_u04_responsive_layout_browser.py
tools/test_u03_contrast_browser.py
tools/test_shared_ui_controllers_browser.py
tools/test_i2c_operation_results_browser.py
tools/test_i2c_pump_ui_browser.py
tools/test_numeric_input_ui_browser.py
tools/test_profile_operation_ui_browser.py
tools/test_program_clear_ui_browser.py
tools/test_runtime_event_ui_browser.py
```

1. focused static + `py_compile`;
2. 88/88 U-05 page scenarios + 207 keyboard/action cases и exact browser
   `10/10` выше;
3. full U-03 contrast and U-04 responsive regressions; после automation —
   read-only visual checklist `320x800`/`390x844` в light/dark для focus,
   44×44 targets, upload proxy и отсутствия clipping/overlap. Screenshots и
   checklist evidence хранятся только в `/tmp`, repo golden/UI не добавляются;
4. deterministic `style.css` gzip pair, frozen editor pair, manifest и typed `raw_update`
   projection/transaction smokes;
5. full smoke suite;
6. Samovar/S3 buildfs, exact files and LittleFS `<0xC0000`;
7. blocking + extended cppcheck sequentially;
8. frozen post-U-05 source дважды clean-собрать с одним заранее зафиксированным
   `SOURCE_DATE_EPOCH=$(git show -s --format=%ct HEAD)`:
   firmware/ELF/map/bootloader/partitions обязаны быть byte-identical. Равенство
   firmware SHA с pre-U-05 не требуется,
   потому что derived `WEB_UPDATE_ENTRIES` constants в `web_update.h` меняют
   manifest table. Любой pre/post binary/map/section delta должен механически
   объясняться только этими changed constants; новые symbols/code paths и
   необъяснимый flash/RAM/map drift = FAIL. После этой pair в verified root A
   последовательно собрать с тем же captured epoch все семь existing env:
   `Samovar`, `Samovar_s3`, `Samovar_no_power`, `Samovar_rmvk`, `Samovar_sem`,
   `Samovar_lua_mqtt`, `Samovar_alarm_button`; каждый log без compiler
   error/warning;
9. `git diff --check`, exact allowlist, no repo browser/cache artifacts;
10. targeted mapper update/check;
11. independent `gpt-5.6-terra` review; fix and rerun until exact
    `PASS: no errors, no warnings`.
12. После clean review записать actual evidence/PASS в этот task-plan и обновить
    только U-05/status master ledger; затем повторить `git diff --check`.
13. После закрытия всей очереди U-06 -> U-03 -> U-04 -> U-05 основной агент
    запускает финальный `/goal`: независимый review aggregate diff, исправление
    каждого ERROR/WARNING и повтор affected gates/review, пока reviewer не
    вернёт `PASS: no errors, no warnings`.

## 11. Stop/rollback

Остановиться, если semantic fix требует backend/name/body/route change,
redesign/reorder/new product state, local Ace, generic keyboard/ARIA shim или
если 44×44 нельзя сохранить без U-04 regression. Scope не расширять молча.

После двух повторов одной ошибки исследовать web и сравнить 3–5 решений.
Rollback — reverse только собственного U-05 group (sources/gzip/derived
contracts/tests), без destructive git или удаления чужих artifacts.
