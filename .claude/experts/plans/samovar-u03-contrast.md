# U-03 — контраст существующих light/dark состояний без редизайна

**Статус 2026-07-14:** complete — `PASS: no errors, no warnings`. Focused static
`8/8`, contrast/browser `60 + 6 + 160` и полный isolated Playwright `8/8`,
smoke `63/63`, buildfs `2/2` с exact `45/433187 < 786432` bytes, blocking
cppcheck exit `0`, extended cppcheck без error/warning, PlatformIO `7/7`, две
fixed-epoch clean-сборки с byte-identical firmware/ELF/map/bootloader/partitions,
targeted codebase-map и `git diff --check` прошли. Raw-update projection:
`23/413709` bytes; CDN Ace, GET contract и неиспользуемый P1.1 сохранены,
P1.2/A-B runtime и новый функционал не добавлены.

## 1. Цель и критерий готовности

Исправить только воспроизводимые contrast defects существующего UI. Не менять
layout, DOM order, тексты, controls, routes, telemetry/command behavior или
создавать новую тему.

Audit и post-U-06 preflight доказали следующие классы ошибок:

- `color:black` у `DeltaTemp` в `index.htm`, `bk.htm`, `chart.htm` становится
  практически невидимым на dark `--bg-form`;
- fixed light backgrounds `#fafafa/#fff/#eee` в `program.htm` не следуют теме.
- normal text/token pairs `--text-main/--bg-form`,
  `--text-on-accent/--accent`, `--text-history-link/--bg-page` и authored
  borders `--border-input/--bg-input`, `--border-soft/--bg-form` не достигают
  применимого порога хотя бы в одной теме;
- один `--msg-alarm` ошибочно используется и как foreground
  `.chart-status-error`, и как background `.message_0`, поэтому одним значением
  нельзя обеспечить оба контракта;
- configured `%*Color%` используется как foreground sensor-текста и делает
  часть штатных и пользовательских цветов нечитаемой хотя бы в одной теме;
- существующие `chart.js` series/grid colors не достигают `3:1` хотя бы в одной
  теме, поэтому canvas нельзя исключать из contrast gate.

Остальные пары сначала измеряются красным browser contract. В plan не
фиксируются выдуманные ratios или предполагаемые failures: production bytes
меняются только при наличии selector/state evidence.

Готовность:

- large text определяется только по computed values: `font-size >= 24 CSS px`
  либо `font-size >= 18.6667 CSS px` при numeric `font-weight >= 700`; для него
  threshold `>=3:1`, для всего остального текста `>=4.5:1`;
- authored focus/control boundaries `>=3:1`, где критерий применим;
- operational state не передаётся только цветом: уже существующий text/icon
  остаётся видимым и проверяется;
- вне цвета DOM, geometry, requests, text и behavior совпадают с post-U-06
  baseline;
- full gate и independent review дают `PASS: no errors, no warnings`.

## 2. Prerequisites и порядок

1. Начать только после U-06 clean PASS и заморозки его семи UI sources.
2. U-03 выполняется целиком до U-04; concurrent writers в `data/**`, manifest и
   UI tests запрещены.
3. Read-only planner-subagent `gpt-5.6-terra` перед patch повторно строит
   computed-color inventory live tree. Модель нельзя заменять молча.
4. Один developer исправляет только red pairs; отдельный reviewer проверяет
   каждую изменённую пару и отсутствие palette redesign.

## 3. Замороженная матрица и red oracle

Страницы:

```text
index beer distiller bk nbk program setup chart i2cstepper calibrate
```

Themes: forced light, forced dark. Viewports: `1440x900`, `390x844`, `320x800`.
Основная baseline matrix содержит ровно `10 pages x 2 themes x 3 viewports =
60` cells. `320x800` проверяет только contrast/visibility; responsive defect
исправляет U-04. `brewxml.htm` остаётся read-only consumer общего CSS и получает
отдельные `2 themes x 3 viewports = 6` regression cells вне основной matrix.

Закрытая state matrix выполняется на `1440x900` в обеих темах и содержит ровно
`160` cases:

- theme toggle + reload: восемь pages (`index`, `beer`, `distiller`, `bk`,
  `nbk`, `setup`, `chart`, `i2cstepper`) x 2 = `16`;
- opened history: пять mode pages x 2 = `10`;
- visible tooltip: `index`, `beer`, `distiller`, `nbk`, `program`, `setup` x 2
  = `12`;
- `.message_0/.message_1/.message_2`: 3 x 2 = `6`;
- `.chart-status-error`: 1 x 2 = `2`;
- power on/off: пять mode pages x 2 fixtures x 2 = `20`;
- detector ok/warn/alarm: 3 x 2 = `6`;
- I2C `.state-button.state-on/.state-off`: 2 x 2 = `4`;
- существующие program-row types: `index 5 + beer 8 + distiller 5 + nbk 4 +
  program 5 = 27`, x 2 = `54`;
- custom `PipeColor` fixture на семи sensor pages x 2 = `14`;
- beer popup open: 1 x 2 = `2`;
- common controls: `.button` hover/focus/active = `6`, actual disabled
  `#heaterMaxPower` = `2`, chart `#refresh` checked/unchecked = `4`, focused
  `select` = `2`.

Для каждого visible first-party text node и authored control/state browser
получает через `getComputedStyle()`:

- foreground и реальный alpha-composed ancestor background;
- font size/weight и применимый threshold;
- selector/page/theme/state;
- visible redundant text/icon для color-coded state.

До production patch новый test обязан быть RED как минимум на трёх delta и
program fixed surfaces. Дополнительная пара становится разрешённой к исправлению
только после сохранения exact red JSON в `/tmp`; screenshots/baselines в repo не
добавляются.

Disabled/inactive и decorative элементы отчётно измеряются, но не выдаются за
PASS/FAIL, если критерий делает исключение. Missing selector/background/state,
неполная cardinality или skip — FAIL. Весь `data/edit.htm(.gz)` shell вместе
с Ace исключён из U-03 и остаётся byte-for-byte frozen:
`26b7e41df2a0a0197a14b9cf129f808fd001e760df4ed7c16df7a35a10b03ce6`/
`bef3ce7e5c68a3cef89643ae1a22b5130c49b9983a9b69b71ffdd272dbe153f5`.

## 4. Минимальное решение

### Обязательные audit fixes

1. В `index.htm`, `bk.htm`, `chart.htm` заменить только hard-coded black у
   delta container на существующий `var(--text-strong)` или другой уже
   проверенный theme token. Binding, font-size и markup не менять.
2. В `program.htm` заменить только доказанные fixed surface/text literals
   `#fafafa`, `#fff`, `#eee` и конфликтующий inherited foreground на
   существующие `--bg-program-panel`, `--bg-program-example`, `--text-main` или
   `--text-strong`. Structure, calculations и type/state behavior не менять;
   program-row colors корректируются только при отдельном exact RED evidence.

### Условные fixes только по red evidence

3. Если shared normal/control/message pair красная, минимально скорректировать
   только этот закрытый token allowlist в `:root` и двух current dark-theme
   blocks: `--accent`, `--accent-hover`, `--bg-page`, `--text-main`,
   `--text-strong`, `--text-on-accent`, `--text-history-link`,
   `--border-input`, `--border-soft`, `--msg-alarm`, `--state-danger-bg`,
   `--detector-ok-text/bg`, `--detector-warn-text/bg`,
   `--detector-alarm-text/bg`. Не менять spacing/typography/radius/shadow/motion.
   `--msg-alarm` остаётся только foreground `.chart-status-error`;
   `.message_0` использует `background: var(--state-danger-bg)` и
   `color: var(--text-on-accent)`. Значения меняются только при exact RED ratio.
4. Page-local hard-coded program/status foreground/background исправляется
   только на closed candidate pages из раздела 7 и только в exact red selector.
   Существующий hue/type/state machine сохраняется.
5. На семи существующих sensor pages (`index`, `beer`, `distiller`, `bk`,
   `nbk`, `setup`, `chart`) configured `%*Color%` перестаёт быть foreground:
   text того же элемента использует `var(--text-strong)`, а exact configured hue
   сохраняется на том же элементе через `text-decoration-line: underline` и
   `text-decoration-color: %*Color%`. Browser contract обязан проверять
   `textDecorationLine === "underline"` и exact computed
   `textDecorationColor` для всех defaults и custom `PipeColor`.
   Новые element/class/component/setting и geometry не добавляются. Defaults
   берутся из `NVS_Manager.ino` (`Steam #ff0000`, `Pipe #0000ff`,
   `Water #00bfff`, `Tank #008000`, `ACP #800080`); custom gate использует
   `PipeColor=#21303d` и требует readable foreground при неизменном hue accent.
6. Перед добавлением icon/text для state проверить уже существующие visible
   labels (`Включить/Выключить`, state text, row type). Если redundancy уже есть,
   ничего не добавлять. Не создавать новую safety strip, alarm acknowledge или
   product state.
7. В `data/chart.js` разрешены только значения `SERIES[*].color` и существующий
   grid/palette color flow. Keys, labels, order, draw/CSV/timing/behavior
   заморожены. Каждая видимая series и grid line должна иметь `>=3:1` к canvas
   background обеих тем.

Closed shared selector allowlist для доказанных RED pairs:

```text
.chart-status-error
.message_0
textarea
input
input[type=text/password]
#file-input
.custom-file-upload
.tab / .tab input / :hover / .active
.btn
.button / :hover / :active / :focus-visible
checkbox/radio + label :before/:after
input:focus-visible
.tooltip .tooltiptext
select, включая SVG arrow fill
.popup__button
.theme-toggle / :hover
.chart-panel
.chart-legend-swatch
```

Page-local owners разрешены только при one-to-one RED evidence: три delta;
sensor styles на семи перечисленных pages; `program.htm` fixed
panel/result/note/button; существующие program-row builders/fixed rows в
`index`, `beer`, `distiller`, `nbk`, `program`; `nbk #ISspd`, setup equipment
heading и I2C state buttons. Всё остальное остаётся read-only.

Новые theme modes, design system, CSS/JS framework, assets, gradients,
animations, fallback и browser-dependent palette запрещены.

## 5. Red-before-green tests

### `tools/smoke_u03_contrast.py` (new)

Static test сначала RED на exact audit literals, затем проверяет:

- zero `color:black` на трёх delta и zero fixed audit backgrounds в program;
- closed token/selector allowlist; no new theme JS/control;
- route/template-token/control inventory unchanged; element count/order/tree
  unchanged, кроме exact allowlisted color/style attributes того же элемента;
- state label/icon inventory не уменьшен;
- `chart.js` после нормализации ровно шести `SERIES[*].color` byte-identical
  post-U-06 baseline: keys/order/labels/parsing/draw logic не меняются; grid flow
  остаётся byte-identical и получает новый цвет только через `--border-soft`;
- `style.css.gz` single-layer, deterministic (`mtime=0`) и распаковывается
  byte-for-byte в `style.css`;
- manifest/projection SHA/size соответствуют live bytes.

### `tools/test_u03_contrast_browser.py` (new)

Browser test через isolated `playwright-cli` выполняет матрицу раздела 3:

- normal/large text thresholds;
- default, hover, focus, active, disabled, error/message, power/detector/I2C и
  все существующие program-row states;
- exact configured sensor defaults и custom `PipeColor=#21303d`; text остаётся
  theme-readable, underline сохраняет exact configured hue;
- no color-only state по visible text/icon inventory;
- theme toggle/persistence, no console warning/error/pageerror;
- canvas series/grid измеряются отдельно от DOM text и обязаны пройти `3:1`;
- normalized DOM/text/request/geometry parity; допускаются только computed
  foreground/background/border/focus colors и exact sensor style-only changes,
  перечисленные в плане.

Failure должен печатать page/theme/viewport/selector/state/RGB/ratio/threshold.
Missing selector, skipped scenario или невозможность вычислить background —
FAIL, не skip.

`tools/test_numeric_input_ui_browser.py` разрешено изменить только для
параметризации существующего `render_site(..., color_tokens=...)`: прежний
default и все current callers остаются неизменными. Копировать renderer в U-03
test запрещено.

## 6. Последовательность разработки

1. Freeze post-U-06 hashes, DOM/request/geometry и current green regressions.
2. Добавить оба red tests; подтвердить обязательные failures до production patch.
3. Исправить три delta, после каждой страницы прогнать exact browser cells.
4. Исправить program surfaces, проверить все current panel/result/row states.
5. Исправить shared/page-local пары только из сохранённого red report, по одной
   группе; после каждой группы прогнать полную десятистраничную matrix.
6. Стабилизировать bytes, regenerate deterministic gzip, обновить derived
   manifests/projection и выполнить full gate.

## 7. Точный write allowlist

Production mandatory candidates:

```text
data/style.css
data/style.css.gz
data/index.htm
data/bk.htm
data/chart.htm
data/program.htm
data/chart.js                         # only SERIES/grid palette
```

Closed conditional candidates — только если их exact selector красный:

```text
data/beer.htm
data/distiller.htm
data/nbk.htm
data/setup.htm
data/i2cstepper.htm
```

Sensor fix с подтверждённым общим дефектом разрешает exact style-only changes в
`beer`, `distiller`, `nbk`, `setup` из conditional списка. `data/i2cstepper.htm`
меняется только при exact RED state selector. `data/calibrate.htm` и
`data/brewxml.htm` — browser regression only. Итоговый changed-page set должен
быть подмножеством списка и иметь one-to-one red evidence; «заодно» менять все
candidate pages запрещено. `data/app.js` read-only.

Tests/contracts:

```text
tools/smoke_u03_contrast.py                         # new
tools/test_u03_contrast_browser.py                  # new
tools/test_numeric_input_ui_browser.py              # render_site parameters only
tools/smoke_ui_foundations.py                       # only new invariant if needed
tools/smoke_style_cleanup.py                        # only stale exact literal
web_src/ui-manifest-v1.json
web_update.h
tools/ui_pack_assets_contract.py
tools/smoke_ui_pack_assets.py
tools/smoke_web_update_transaction.py
tools/smoke_web_file_writes.py
```

Exact downstream updates:

- `smoke_ui_foundations.py`: обновить только exact allowed
  token/selector inventory для changed color owners; сохранить route, DOM,
  control, theme-owner, I2C и message assertions;
- `smoke_style_cleanup.py`: заменить только stale forbidden/required color
  literal/token expectation; сохранить все остальные CSS hygiene/count
  assertions;
- U-06 `smoke_shared_ui_controllers.py` и
  `test_shared_ui_controllers_browser.py` запускать без изменений. Если
  color-only patch делает их selector stale, остановиться: это scope leak, а не
  основание ослаблять controller contract.

Existing assertions/scenarios не удалять и не ослаблять.

Map после полного PASS:

```text
.cli-proxy/.codebase_map/nodes/data.md
.cli-proxy/.codebase_map/nodes/tools.md
.cli-proxy/.codebase_map/nodes/web-src.md
.cli-proxy/.codebase_map/nodes/web-update-h.md       # only if projection changed
```

Status/evidence allowlist только после clean review:

```text
.claude/experts/plans/samovar-u03-contrast.md
.claude/experts/plans/samovar-audit-remediation.md
.claude/experts/plans/samovar-remaining-remediation-2026-07-12.md
```

Firmware, routes/schemas, raw/legacy inventories, `data/edit.htm`,
`data/edit.htm.gz`, Ace, other pages, build configs и workflows запрещены.

## 8. Gzip/manifest/hash discipline

- `style.css.gz` создавать только существующим
  `tools.ui_pack_format.canonical_gzip(style_bytes)`, дважды; обе генерации
  byte-identical. Exact header `1f8b08000000000002ff` (`MTIME=0`, `FLG=0`,
  `XFL=2`, `OS=255`), один member (`decompressobj(wbits=31).eof == true`,
  `unused_data == b""`), decompressed bytes byte-identical `style.css`.
- HTML candidates не получают новые checked `.gz`.
- Обновить только changed source SHA/size/maxima в `ui-manifest-v1.json` и
  existing A-04 typed entries в `web_update.h`.
- Derived-only updates: в `ui-manifest-v1.json` меняются только changed
  `entries[*]` SHA/maxima и `raw_update.entries[*]` size/SHA; в `web_update.h`
  только corresponding `WEB_UPDATE_ENTRIES`; в `ui_pack_assets_contract.py`
  только `EXPECTED_CONTRACT_INPUT_SHA256`, `A10_FREEZE_AGGREGATE_SHA256`,
  `EXPECTED_RAW_SOURCE_TREE_SHA256`, `_RAW_UPDATE_BYTES`,
  `_EXPECTED_UI_TOTALS`; в `smoke_ui_pack_assets.py` — только raw total в
  `verify_raw_update_contract()` и `main()` и соответствующие сообщения; в
  `smoke_web_update_transaction.py` — только projection total и сообщение в
  `verify_static_contract()`, а также exact 45-file active-data total и сообщение
  в `run_littlefs_capacity_proof()`. Все числа вычисляются механически из
  зафиксированных U-03 bytes; test/transaction logic не меняется.
- Raw-update transaction semantics, importer/generator, routes/schema/version,
  неиспользуемые P1.1 A/B manifest fields и local Ace/pack runtime/security не
  менять; A/B runtime не добавлять.
- Frozen editor pair не regenerates; exact SHA/size проверяется отдельным
  contract без contrast/browser assertions.

## 9. Expected inventory

База после U-06: `62 smoke / 7 browser / 172 durable tools`. U-03 добавляет
ровно один smoke и один browser script:

```text
после U-03: 63 smoke / 8 browser / 174 durable tools
```

## 10. Gate и reviewer-loop

Browser gate выполняется только в isolated environment:

```bash
PW=/tmp/samovar-playwright-cli-0.1.17/node_modules/.bin/playwright-cli
export PATH=/tmp/samovar-playwright-cli-0.1.17/node_modules/.bin:$PATH
export PLAYWRIGHT_BROWSERS_PATH=/tmp/samovar-playwright-browsers
export PYTHONPYCACHEPREFIX=/tmp/samovar-u03-pycache
test "$(command -v playwright-cli)" = "$PW"
test "$("$PW" --version)" = "0.1.17"
```

Последовательно выполнить ровно восемь scripts и получить `8/8`:

```text
tools/test_u03_contrast_browser.py
tools/test_shared_ui_controllers_browser.py
tools/test_i2c_operation_results_browser.py
tools/test_i2c_pump_ui_browser.py
tools/test_numeric_input_ui_browser.py
tools/test_profile_operation_ui_browser.py
tools/test_program_clear_ui_browser.py
tools/test_runtime_event_ui_browser.py
```

Global alpha и fallback runner запрещены. Существующую repo
`.playwright-cli/` не удалять: снять pre/post inventory и доказать отсутствие её
изменения.

1. focused static + `py_compile` с указанным `PYTHONPYCACHEPREFIX`;
2. full `60 + 6 + 160` contrast/state matrix и exact browser `8/8` выше;
3. deterministic gzip, manifest и typed `raw_update` projection/transaction
   smokes;
4. full `run_smoke_tests.py --timeout 60`;
5. Samovar/S3 buildfs, exact hashes, LittleFS `<0xC0000`;
6. blocking и extended cppcheck последовательно;
7. frozen post-U-03 source дважды clean-собрать с одинаковым
   `SOURCE_DATE_EPOCH=$(git show -s --format=%ct HEAD)` и получить
   byte-identical firmware/ELF/map/bootloader/partitions; затем собрать семь
   environments. Равенство SHA с
   pre-U-03 не требуется: pre/post binary/map/section delta допускается только
   как механическое следствие changed `WEB_UPDATE_ENTRIES` constants в
   `web_update.h`; новые symbols/code paths и необъяснимый flash/RAM/map drift
   = FAIL;
8. `git diff --check`, exact allowlist, no repo browser artifacts;
9. targeted mapper update/check;
10. independent `gpt-5.6-terra` review. Исправлять и повторять affected gates
    до exact `PASS: no errors, no warnings`.
11. После clean review записать actual evidence/PASS в этот task-plan и обновить
    только U-03/status master ledger; повторить `git diff --check`. Не отмечать
    completion до фактических gates.

## 11. Stop/rollback

Остановиться, если fix требует layout/DOM/control/functionality change, нового
theme/component/framework/asset, выхода из allowlist или ослабления threshold.
Новая неожиданная red pair сначала документируется и добавляется в closed
evidence, а не исправляется попутно.

При повторе одной ошибки дважды выполнить web-исследование 3–5 решений.
Rollback — только reverse собственного U-03 diff как согласованной группы CSS,
gzip, pages, manifest/projection и tests; destructive git commands запрещены.
