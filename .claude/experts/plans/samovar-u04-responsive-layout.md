# U-04 — responsive fixes только для setup и chart

## 1. Цель и критерий готовности

Исправить доказанную fixed desktop geometry в `data/setup.htm` и
`data/chart.htm` без redesign и без изменения функций:

- `setupform` содержит invalid unitless `min-width:1024` intent;
- нижний action wrapper имеет fixed `width:668px`;
- четыре long inputs имеют `22em/30em` и выходят за mobile viewport;
- chart messages wrapper имеет absolute `left:200px;width:600px`;
- chart canvas/containing blocks дают horizontal overflow, включая пограничный
  desktop pixel;
- mobile tooltip на setup выходит вправо за viewport;
- четыре `.container_column` внутри chart status form сохраняют `width:100%`
  вместе с inline padding и расширяют content-box за viewport.

Готовность на `320x800`, `390x844`, `768x1024`, `1440x900`: оба выражения
`document.documentElement.scrollWidth <= window.innerWidth` и
`document.body.scrollWidth <= window.innerWidth` истинны.

Все visible first-party controls/messages/chart/legend помещаются, не
перекрываются и не обрезаются; DOM order, content, actions, requests, chart
behavior и post-U-03 colors неизменны. Reviewer: `PASS: no errors, no warnings`.

`data/edit.htm`/`data/edit.htm.gz` не входят в responsive scope и остаются
byte-for-byte frozen
(`26b7e41df2a0a0197a14b9cf129f808fd001e760df4ed7c16df7a35a10b03ce6`/
`bef3ce7e5c68a3cef89643ae1a22b5130c49b9983a9b69b71ffdd272dbe153f5`);
GET routes, CDN Ace и исключение security-hardening не меняются.

## 2. Prerequisites и порядок

1. U-06 и затем U-03 должны иметь последовательный clean PASS. Baseline
   снимается после U-03, а не по planning SHA старой версии.
2. U-04 завершается до U-05. Одновременные writers в `data/**`, manifest и
   browser tests запрещены.
3. Read-only planner-subagent `gpt-5.6-terra` повторяет geometry inventory по
   live bytes. Если audit selector уже не красный, production code для него не
   менять и зафиксировать evidence.
4. Один developer владеет patch; отдельный reviewer проверяет отсутствие
   hiding/reorder/new UI.

## 3. Red baseline

До patch новый browser test обязан доказать на current post-U-03 tree:

- setup document `scrollWidth > innerWidth` на 320/390;
- `#save` parent right edge выходит за viewport из-за `width:668px`;
- `videourl`, `blynkauth`, `tgtoken`, `tgchatid` выходят или сжимают content;
- `#Main select[name="mode"]` выходит за правую границу на `320px`;
- visible chart messages wrapper имеет right edge около `808px` независимо от
  mobile viewport; hidden host сам по себе не считается доказательством;
- setup `.tooltip .tooltiptext` в visible hover/focus state выходит за viewport
  на `320/390`;
- chart `.container_column` внутри status form расширяет content-box за
  viewport;
- `.chart-canvas` либо containing block увеличивает document шире viewport
  только после real data + `chart.draw()`; empty/error state не подменяет этот
  red case.

Unitless `min-width:1024` браузер игнорирует; его удаление остаётся
static-invalid cleanup, но не выдаётся за runtime root cause.

Для каждого failure сохранить в `/tmp`: page, viewport, theme, state, selector,
bounding rect, ancestor rect, scrollWidth/clientWidth. Screenshots/traces в
repository не добавлять.

## 4. Минимальное layout-решение

Использовать только существующие breakpoints `900px` и `600px`; новый mobile
navigation или component не вводить.

### Exact markup symbols

- `setup.htm`: удалить только inline `min-width: 1024;` у `#setupform`;
- четырём exact long inputs добавить class `setup-long-input`;
- existing parent `#save/#return/#edit` добавить class `setup-actions` и удалить
  inline fixed width;
- existing outer parent `#messagesBox` в chart добавить class
  `chart-messages-host` и удалить inline positioning/width.
- existing chart `<form>` добавить class `chart-status-form`; новый element не
  создаётся.

Новые nodes не добавлять, existing nodes не переносить и не скрывать.

### Exact CSS symbols

В `style.css` разрешены изменения только selectors: `#setupform`,
`.setup-long-input`, `#setupform > .message_0`, `.setup-actions`, `.tooltip .tooltiptext` внутри
существующего `<=600px` breakpoint, `.chart-messages-host`,
`.chart-status-form .container_column`, `#chartdiv`, `.chart-panel`,
`.chart-canvas`, `#Main select[name="mode"]`.

Rules:

1. `#setupform` и relevant flex children получают только необходимое
   `min-width:0`, `width/max-width:100%`, `box-sizing:border-box`.
2. `.setup-long-input` имеет `max-width:100%`; desktop computed width остаётся
   исходной 22em/30em, пока available width это позволяет.
3. `#Main select[name="mode"]` ограничен available width без изменения
   options/value/name.
4. `.setup-actions` сохраняет desktop `max-width:668px`, центрирование и order
   Save -> Return -> Editor; на narrow width становится fluid flex/wrap.
5. `.chart-messages-host` сохраняет desktop composition, а на `<=900px` идёт в
   normal flow с `width:100%;max-width:600px`; message content не скрывается и
   page shell не получает horizontal scroll.
6. Chart blocks ограничиваются containing block через `min-width:0`,
   `max-width:100%`, `box-sizing:border-box`. Canvas drawing buffer, data,
   height, JS и scale logic не менять.
7. Mobile `.tooltip .tooltiptext` остаётся полностью видимым и получает только
   viewport-contained width/left/right positioning; text не скрывать и не
   обрезать.
8. `.chart-status-form .container_column` получает только
   `min-width:0; box-sizing:border-box`; inline content/order/padding и form
   behavior не менять.

Запрещены `overflow-x:hidden/clip`, `display:none`, text truncation, horizontal
page shell, sticky/fixed mobile actions, panel/collapsible, DOM reorder,
animation, framework и new feature.

## 5. Red-before-green tests

### `tools/smoke_u04_responsive_layout.py` (new)

Сначала RED на exact inline literals. После patch:

- запрещает `min-width:1024`, `width:668px`, chart `left:200px;width:600px` и
  unbounded `22em/30em` без class constraint;
- требует exact classes/selectors из раздела 4, включая bounded mobile tooltip
  и `.chart-status-form .container_column`, не разрешает hiding/clipping;
- сравнивает DOM ids/names/types/order/text, form names/actions, script/routes;
- фиксирует отсутствие изменений `app.js`, `chart.js` и post-U-03 color tokens;
- проверяет deterministic gzip и manifest/projection SHA/size.

### `tools/test_u04_responsive_layout_browser.py` (new)

Exact matrix содержит `168` cells:

- setup base: шесть existing tabs x 4 viewports x 2 themes = `48`;
- setup additional states: Main longest mode, Other long values, Other empty
  values, validation error, request error и visible tooltip — 6 x 4 x 2 =
  `48`; setup total = `96`;
- chart: messages hidden/short/long/multiline, empty/data/error chart, legend и
  refresh — 9 x 4 x 2 = `72`. Data state обязан загрузить реальные points и
  вызвать `chart.draw()`.

Viewports exact: `320x800`, `390x844`, `768x1024`, `1440x900`; themes exact:
forced light/dark. Проверки:

- обе document width inequalities;
- every target rect inside viewport/containing block;
- pairwise no overlap для actions и chart message/content;
- visible text/control/focus ring not clipped;
- desktop geometry отличается от baseline только minimal overflow correction;
- exact request trace и chart data/refresh behavior;
- zero console warning/error, pageerror, missing/skipped selector.

New test минимально импортирует существующие `render_site`, `QuietHandler` и
`run_cli` patterns, мокает `/ajax` и `/data.csv`; их код не копируется и current
browser tests не меняются. Post-U-03 normalized DOM/control/request/color
digests и normalized desktop geometry baseline хранятся как exact constants
самого нового test, чтобы gate был replayable в CI. Geometry constants включают
`x/y/width/height` и expected containing selector для каждого проверяемого
setup/chart target во всех relevant states/themes при `1440x900`; координаты
нормализуются до `0.01 CSS px`, а единое допустимое отклонение каждой координаты
равно `0.5 CSS px` без накопления и viewport-dependent исключений. Containment и
no-overlap остаются строгими inequalities. `/tmp` используется только для
diagnostic geometry/PNG, не как baseline/golden source.

U-04 не проверяет 44×44 как acceptance — это U-05, но не должен ухудшать
существующие target sizes.

## 6. Последовательность разработки

1. Freeze exact post-U-03 sources, включая final `chart.js` palette/CSS tokens,
   DOM/text/control/request/geometry baseline; planning-time U-06 hashes не
   использовать.
2. Добавить red static + browser tests и сохранить exact failures.
3. Исправить setup only, включая visible mobile tooltip; прогнать все setup
   cells и existing numeric tests.
4. Исправить chart message host; прогнать hidden/visible/long-message cells.
5. Исправить chart status-column/canvas containment; прогнать real-data draw,
   error/refresh/legend cells.
6. Full two-page matrix и regression pages; только затем gzip/manifests/gates.

## 7. Точный write allowlist

Production — ровно:

```text
data/style.css
data/style.css.gz
data/setup.htm
data/chart.htm
```

Tests/contracts — ровно:

```text
tools/smoke_u04_responsive_layout.py                 # new
tools/test_u04_responsive_layout_browser.py          # new
web_src/ui-manifest-v1.json
web_update.h
tools/ui_pack_assets_contract.py
tools/smoke_ui_pack_assets.py
tools/smoke_web_update_transaction.py
```

Existing `smoke_ui_foundations.py`, `smoke_style_cleanup.py`,
`smoke_chart_ui.py` и `smoke_web_file_writes.py` не содержат stale U-04
selector/constant и запускаются read-only; новый smoke единолично владеет
новыми layout assertions. Exact downstream contract:

- `test_profile_operation_ui_browser.py` и
  `test_numeric_input_ui_browser.py` запускать read-only: `#setupform`,
  control names/IDs и save/numeric behavior обязаны сохраниться; failure здесь
  является U-04 scope error, а не основанием patch теста;
- U-06 shared-controller tests и
  `test_runtime_event_ui_browser.py` запускать read-only; IDs, lifecycle,
  message/chart behavior и scenario counts сохраняются.

Ни одно existing assertion/scenario нельзя удалить или ослабить. Любая
необходимость менять browser selectors вне перечисленного chart wrapper требует
stop и явного уточнения allowlist.

Map после полного PASS:

```text
.cli-proxy/.codebase_map/nodes/data.md
.cli-proxy/.codebase_map/nodes/tools.md
.cli-proxy/.codebase_map/nodes/web-src.md
.cli-proxy/.codebase_map/nodes/web-update-h.md
```

Status/evidence allowlist только после clean review:

```text
.claude/experts/plans/samovar-u04-responsive-layout.md
.claude/experts/plans/samovar-audit-remediation.md
.claude/experts/plans/samovar-remaining-remediation-2026-07-12.md
```

`data/app.js`, `chart.js`, `data/edit.htm`, `data/edit.htm.gz`, other
pages, C++/INO, routes/schemas, raw/legacy inventories, build
configs/workflows запрещены.

## 8. Gzip/manifest/hash discipline

- Создать `style.css.gz` только через существующий
  `tools.ui_pack_format.canonical_gzip`; exact header
  `1f8b08000000000002ff`, один member, `MTIME=0/FLG=0/XFL=2/OS=255`, two-run
  byte identity и decompression parity обязательны.
- Setup/chart не получают новые checked `.gz`.
- Обновить только SHA/size/maxima изменённых `style.css`, `setup.htm`,
  `chart.htm` entries в manifest и existing A-04 typed projection.
- Derived writes ограничены changed entry SHA/size/maxima и raw_update SHA/size
  в `ui-manifest-v1.json`, corresponding `WEB_UPDATE_ENTRIES` в
  `web_update.h`, а в `ui_pack_assets_contract.py` — только
  `EXPECTED_CONTRACT_INPUT_SHA256`, `A10_FREEZE_AGGREGATE_SHA256`,
  `EXPECTED_RAW_SOURCE_TREE_SHA256`, `_RAW_UPDATE_BYTES`,
  `_EXPECTED_UI_TOTALS`; в `smoke_ui_pack_assets.py` — только raw total literals
  в `verify_raw_update_contract()` и `main()` и соответствующие сообщения.
  Existing max-pack boundary literals в `main()` меняются только если exact
  recomputation действительно пересекает текущий cap. В
  `smoke_web_update_transaction.py` разрешены только projection total и сообщение
  `verify_static_contract()`, а также exact 45-file active-data total и сообщение
  `run_littlefs_capacity_proof()`. Все значения вычисляются механически из
  зафиксированных U-04 bytes; test/transaction logic менять запрещено.
- Raw-update transaction logic, generator/importer, version/routes/schema,
  неиспользуемые P1.1 A/B manifest fields и local Ace/pack runtime/security не
  менять; A/B runtime не добавлять.
- Frozen editor pair не regenerates и проверяется только по exact SHA/size.

## 9. Expected inventory

База после U-03: `63 smoke / 8 browser / 174 durable tools`. U-04 добавляет
ровно два scripts:

```text
после U-04: 64 smoke / 9 browser / 176 durable tools
```

## 10. Gate и reviewer-loop

Browser gate выполняется только в isolated environment:

```bash
PW=/tmp/samovar-playwright-cli-0.1.17/node_modules/.bin/playwright-cli
export PATH=/tmp/samovar-playwright-cli-0.1.17/node_modules/.bin:$PATH
export PLAYWRIGHT_BROWSERS_PATH=/tmp/samovar-playwright-browsers
export PYTHONPYCACHEPREFIX=/tmp/samovar-u04-pycache
test "$(command -v playwright-cli)" = "$PW"
test "$("$PW" --version)" = "0.1.17"
```

Последовательно выполнить exact `9/9`: `test_u04_responsive_layout_browser.py`,
`test_u03_contrast_browser.py`, `test_shared_ui_controllers_browser.py`,
`test_i2c_operation_results_browser.py`, `test_i2c_pump_ui_browser.py`,
`test_numeric_input_ui_browser.py`, `test_profile_operation_ui_browser.py`,
`test_program_clear_ui_browser.py`, `test_runtime_event_ui_browser.py`.
Global alpha/fallback runner запрещены.

1. focused static + `py_compile`;
2. full U-04 `168`-cell matrix, затем exact browser `9/9` выше;
3. post-U-03 contrast matrix regression входит в тот же несокращённый block;
4. deterministic gzip, manifest и typed `raw_update` projection/transaction
   smokes;
5. full smoke suite;
6. Samovar/S3 buildfs и LittleFS `<0xC0000`;
7. blocking/extended cppcheck последовательно;
8. frozen post-U-04 source дважды clean-собрать с одинаковым
   `SOURCE_DATE_EPOCH=$(git show -s --format=%ct HEAD)` и получить
   byte-identical firmware/ELF/map/bootloader/partitions; затем собрать семь
   environments. Равенство SHA с
   pre-U-04 не требуется: pre/post binary/map/section delta допускается только
   как механическое следствие changed `WEB_UPDATE_ENTRIES` constants в
   `web_update.h`; новые symbols/code paths и необъяснимый flash/RAM/map drift
   = FAIL;
9. `git diff --check`, exact allowlist, no repo temp/browser artifacts;
10. targeted map update/check;
11. independent `gpt-5.6-terra` review; fix/rerun until exact
    `PASS: no errors, no warnings`.
12. После clean review записать actual evidence/PASS в этот task-plan и обновить
    только U-04/status master ledger; затем повторить `git diff --check`.

## 11. Stop/rollback

Остановиться, если green result требует hiding/clipping, DOM reorder/new node,
изменения chart JS/requests, U-03 colors, U-05 semantics/touch sizes или выхода
из allowlist. Не исправлять overflow на других pages попутно.

После двух повторов одной ошибки выполнить web-исследование 3–5 решений.
Rollback — reverse только собственного U-04 group (CSS/gzip/two pages/derived
hashes/tests); destructive git и очистка чужих files запрещены.

## 12. Фактический результат — 2026-07-14

Статус: **complete**. Независимый reviewer после исправления двух замечаний:
`PASS: no errors, no warnings`.

- Production diff ограничен `setup.htm`, `chart.htm`, `style.css(.gz)`:
  удалены только фиксированные ограничения ширины, существующим узлам добавлены
  точные classes, а CSS обеспечивает containment. Проверенный на 320/390/768
  selector `#setupform > .message_0` включён в закрытый allowlist после того,
  как его удаление воспроизвело overflow существующих validation/request
  сообщений; нового элемента или поведения не добавлено.
- Focused static/assets/foundation/style/chart/web-file и default/capacity
  transaction gates PASS. U-04 Playwright matrix — `168/168`; полный browser
  block — `9/9`; полный smoke — `64/64`.
- `style.css`/gzip — `20452/4746` bytes; active LittleFS source —
  `45 files / 434245 bytes` из `786432`; raw update —
  `23 files / 414767 bytes`. Capacity proof: `baseline_free=66`,
  `payload_pass=65`, `payload_fail=66`, `singleton=23`.
- Buildfs `Samovar`/`Samovar_s3` — `2/2`. Blocking cppcheck завершён с кодом
  `0`; extended cppcheck содержит только informational `missingInclude`/
  `checkLevel`, `Timed out: no`, без errors/warnings.
- Две clean-сборки с `SOURCE_DATE_EPOCH=1783141834` побайтово совпали для
  firmware/ELF/map/bootloader/partitions. Все семь environments PASS без
  compiler errors/warnings; базовый `Samovar`: Flash
  `1241897/1638400` (75.8%), RAM `72856/327680` (22.2%),
  `firmware.bin=1248480` bytes.
- CDN Ace/editor raw+gzip, `app.js`, `chart.js`, routes/backend, GET/security и
  P1.2/local-pack runtime не изменены. Codebase-map metadata, exact allowlist и
  `git diff --check` PASS.
