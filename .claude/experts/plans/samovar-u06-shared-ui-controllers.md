# U-06 — единый lifecycle telemetry для пяти mode pages и chart

## Статус реализации

Завершено 2026-07-13. Независимый reviewer после исправления всех замечаний
вернул `PASS: no errors, no warnings`.

Фактические gates: focused/static/derived PASS; полный smoke `62/62`;
изолированный стабильный `playwright-cli 0.1.17` из `/tmp` — `7/7`, включая
U-06 matrix `72` page/theme/viewport cells, `8` toggle/reload, `8`
storage-fault cases и `24` screenshots; `buildfs` ESP32/ESP32-S3 PASS, payload
`430349 < 0xC0000`; blocking cppcheck — exit `0`, zero warnings/errors;
extended cppcheck — zero warnings/errors, только ожидаемые informational
missing-include/ValueFlow сообщения; семь PlatformIO environments — PASS без
compiler warnings. Две clean-сборки `Samovar` с одинаковым
`SOURCE_DATE_EPOCH` дали byte-identical firmware/ELF/map/bootloader/partitions.
Без фиксированного epoch различаются только две существующие строки
`__DATE__/__TIME__`; их долговременное закрепление остаётся в A-08.

Изменены только существующие UI ownership boundaries и синхронизированные
raw-update metadata/tests/map nodes. Routes, GET methods, DOM/layout/CSS,
`chart.js`, editor/Ace, security, A/B runtime и продуктовая функциональность не
изменялись. Внешний A-04 remote CDN parity остаётся отдельным publication/final
blocker и не меняет локальный PASS U-06.

## 1. Цель и граница

Исправить подтверждённое архитектурное дублирование в
`data/index.htm`, `data/beer.htm`, `data/distiller.htm`, `data/bk.htm`,
`data/nbk.htm` и `data/chart.htm`: шесть локальных polling-shell, а в chart ещё
локальные контроллеры connection/messages/audio/theme и заведомо неиспользуемый
`setPowerUnit()`.

Это рефакторинг существующего поведения, а не новая UI-функция. Единственным
owner остаётся существующий `window.SamovarApp` из `data/app.js`.

В U-06 запрещено переносить в shared code:

- `setPowerUnit()` пяти mode pages, power/program/PWM/heat actions;
- форматирование и mapping telemetry-полей конкретного режима;
- validators и редакторы программ;
- detector/pause/status/process decisions;
- chart drawing, CSV, series, legend, refresh и 15-секундный throttle;
- DOM/layout/CSS, новые controls/routes/assets или новый JS-файл.

`data/edit.htm` и `data/edit.htm.gz` остаются byte-for-byte frozen
(`26b7e41df2a0a0197a14b9cf129f808fd001e760df4ed7c16df7a35a10b03ce6`,
`bef3ce7e5c68a3cef89643ae1a22b5130c49b9983a9b69b71ffdd272dbe153f5`);
CDN Ace decision, существующие GET routes и исключение security-hardening
не меняются.

U-06 готов, когда шесть страниц используют один shared polling lifecycle,
observable behavior совпадает с исходным, все gates зелёные, а независимый
reviewer возвращает `PASS: no errors, no warnings`.

## 2. Обязательные prerequisites и последовательность

1. Локальные code/review/gates A-04 имеют фактический clean PASS; внешний remote
   CDN parity остаётся отдельным publication/final blocker и не блокирует этот
   локальный refactor. A-04 нельзя объявлять release-complete, пока все 23 URL не
   совпадут с typed projection. A-05 и A-07 завершены с точным reviewer verdict
   `PASS: no errors, no warnings`; используемые U-06 контракты A-12/A-13 также
   закрыты. В U-06 переиспользуются существующие `SamovarApp.pollAjax()`, message
   cursor, immutable `/ajax` snapshot и A-04 manifest/typed `raw_update`
   projection; альтернативный путь не создаётся.
2. U-06 выполняется первым в UI-очереди. После него строго последовательно идут
   U-03, U-04, U-05. Одновременные writers в `data/**`, manifest/projection или
   browser tests запрещены.
3. Перед разработкой read-only planner-subagent на запрошенной модели
   `gpt-5.6-terra` сверяет этот план с live tree и выдаёт точный symbol/file
   inventory. Если такая модель недоступна, это сообщается явно; молчаливая
   замена модели запрещена.
4. Один developer владеет всем U-06 diff. После реализации отдельный reviewer
   читает полный diff; каждое замечание исправляется и проверяется повторно до
   чистого результата.

## 3. Проверенный live inventory

На planning snapshot `data/app.js` уже владеет:

- `init`, `pollAjax`, `startPollLoop` и защитой от concurrent telemetry request;
- message cursor/sequence, request error, connection, history/messages/audio;
- theme, I2C renderer, command/program/operation helpers.

Все пять mode pages уже вызывают `SamovarApp.pollAjax()` и
`SamovarApp.startPollLoop(loadDoc, 2000)`, но повторяют локальные `loadDoc()` и
startup shell. Их page-specific render logic внутри `loadDoc()` не является
дубликатом и должно остаться локальным. Startup всех пяти страниц сейчас
принадлежит существующему `window.onload`; этот event boundary и порядок
`init -> page-specific startup -> immediate first poll` заморожены.

`chart.htm` уже подключает `<script src="app.js"></script>`; добавлять include
не требуется. На странице всё ещё существуют local `ConnectError`,
`playSound/addMessage/removeLastMessage/showMessages/clearMessages`,
`escapeHtml`, `applyTheme/toggleTheme/initTheme`, polling wrapper `loadDoc()` и
orphan `setPowerUnit()`. При этом chart использует отличающиеся, но уже
существующие contracts:

- connection indicators `#GreenT/#RedT`, красный после второго подряд failure;
- сообщения не сохраняются в mode-page history;
- theme button меняет существующий `title`;
- chart-specific status warning вызывает message owner;
- `GET /data.csv`, `SamovarChart` и 15 s append throttle остаются локальными.

Chart уже применяет theme дважды: local theme IIFE выполняется во время parse в
существующем inline script, после загрузки `chart.js` и предшествующих inline
declarations; существующий `DOMContentLoaded` повторно вызывает `applyTheme()`
перед `initChart()` и immediate first telemetry poll.
При сохранённых `light`/`dark` chart выставляет explicit `data-theme`; без
сохранённого значения удаляет attribute и вычисляет glyph/title через
`matchMedia`. Его toggle при unset attribute выбирает тему, противоположную
системной. Пять mode pages не имеют раннего parse-init и применяют explicit
light/dark только из текущего `window.onload`.

Chart `removeLastMessage()` сбрасывает page-local `IsCalmingPause` только когда
после фактического удаления очередь стала пустой; `clearMessages()` этот flag не
сбрасывает. Оба различия являются observable contract, а не поводом переносить
status decision в shared code.

Существующие regression tests с прямой ссылкой на удаляемый `loadDoc`:

- `tools/test_i2c_pump_ui_browser.py`;
- `tools/test_runtime_event_ui_browser.py`;
- `tools/smoke_chart_ui.py`;
- `tools/smoke_runtime_event_ring.py`.

## 4. Минимальное архитектурное решение

### Единственный новый public symbol

Добавить в существующий IIFE `data/app.js` ровно один public entrypoint:

```text
SamovarApp.startTelemetryPage(renderFn, options)
```

Он:

1. проверяет `renderFn` и закрытый набор `options`;
2. синхронно при вызове вызывает существующий `init()` и сам не регистрирует
   `DOMContentLoaded`, `load` или другой startup listener;
3. вызывает optional page-local `options.onReady`;
4. запускает ровно один non-overlapping loop через существующие
   `pollAjax(renderFn, sinks)` и `startPollLoop(..., 2000)`;
5. fail-loud сообщает duplicate start, неизвестный option или отсутствующий
   обязательный connection element; second timer/fallback не создаёт.

Разрешённые options закрыты фактическими различиями шести страниц:

- `threshold`: mode pages `3`, NBK `4`, chart `1`;
- `onReady`: существующая page-local инициализация;
- `connectionIds`: отсутствует для mode-page `#connection_indicator`; только
  chart передаёт exact `{ online: 'GreenT', offline: 'RedT' }`;
- `storeMessageHistory`: `true` для mode pages, `false` для chart;
- `dynamicThemeTitle`: `false` для mode pages, `true` для chart;
- `implicitSystemTheme`: `false` для mode pages, `true` для chart;
- `onLastMessageRemoved(remainingCount)`: единственный закрытый callback-option;
  отсутствует у mode pages, а chart передаёт функцию, которая сбрасывает
  `IsCalmingPause` только при `remainingCount === 0`.

Shared `removeLastMessage()` вызывает callback только после фактического `pop()`
и передаёт точный оставшийся count. Пустая очередь не считается удалением и не
вызывает callback; `clearMessages()` callback не вызывает. Chart-specific
решение, когда добавить status-warning и установить `IsCalmingPause`, остаётся
локальным в `renderTelemetry`.

### Существующий theme API

Новый public theme symbol не добавлять. Расширить существующий
`SamovarApp.initTheme(options)` закрытыми boolean-полями
`implicitSystemTheme` и `dynamicThemeTitle`; `init(options)` передаёт ему только
эти theme-поля. Активная policy остаётся document-local private state, поэтому
существующий `SamovarApp.toggleTheme()` сохраняет сигнатуру без аргументов.

Theme owner обязан сохранять две существующие политики:

- при saved `light`/`dark` обе политики выставляют exact explicit
  `data-theme`, glyph `☾`/`☼` и, только при `dynamicThemeTitle: true`, title
  `Тёмная тема`/`Светлая тема`;
- при no saved theme и `implicitSystemTheme: true` owner удаляет `data-theme`,
  определяет effective light/dark через `matchMedia` и по нему вычисляет
  glyph/title, не сохраняя значение в `localStorage`;
- при no saved theme и `implicitSystemTheme: false` owner сохраняет текущее
  mode-page поведение: выставляет explicit `light` либо `dark` по `matchMedia`;
- shared toggle под implicit policy при unset `data-theme` выбирает explicit
  тему, противоположную system theme, сохраняет её и применяет. При explicit
  attribute, а также на mode pages, toggle меняет текущие `light <-> dark` как
  прежде.

Storage-denied parity является закрытой частью только существующей chart
`implicitSystemTheme` policy, а не новым fallback или общей storage abstraction:

- только при `implicitSystemTheme: true` exception из `localStorage.getItem()`
  трактуется как no-saved: chart всё равно применяет implicit system theme без
  записи;
- только при `implicitSystemTheme: true` exception из `setItem()` не отменяет
  уже вычисленный toggle: explicit opposite theme применяется в текущем DOM.
  После reload недоступное чтение снова даёт implicit system theme;
- при `implicitSystemTheme: false` никакие storage exceptions не подавляются:
  mode pages сохраняют текущий shared fail-loud get/set contract. Общий helper,
  wrapper, retry, substitute storage или silent catch вне chart policy запрещены.

В `chart.htm` заменить local theme IIFE прямым вызовом
`SamovarApp.initTheme({ implicitSystemTheme: true, dynamicThemeTitle: true })`.
Вызов остаётся в exact current IIFE position внутри того же существующего inline
script: после `chart.js` и предшествующих declarations, до `initChart()` и
регистрации `DOMContentLoaded`. Новый script element и reorder не добавляются.
Local chart `applyTheme/toggleTheme/initTheme` после этого удаляются. Parse-time
вызов не требует существования `#themeToggle`: shared owner обновляет control,
только если он уже смонтирован.

Не добавлять descriptors полей/actions, generic renderer, class, registry,
component, DSL, compatibility alias или второй controller API. Эти options
нужны только для сохранения уже измеренных различий; расширяемый configuration
framework из них не строится.

### Изменения страниц

- На каждой mode page переименовать только polling callback `loadDoc()` в
  локальный `renderTelemetry(myObj)` и удалить из него обёртку
  `SamovarApp.pollAjax(...)`. Page-specific branches и formatters оставить на
  месте.
- В существующем `window.onload` каждой mode page вызвать ровно один
  `SamovarApp.startTelemetryPage(renderTelemetry, options)`. В `onReady` оставить
  текущий page-specific wiring (`setPowerUnit`, program textarea, recipe/mixer и
  т. п.) в исходном порядке; theme options передать exact
  `implicitSystemTheme: false, dynamicThemeTitle: false`; локальные
  `init/startPollLoop` удалить. Shared entrypoint не создаёт второй listener и
  запускает first poll синхронно в той же startup-фазе.
- В chart оставить local `renderTelemetry`, `initChart`, `appendChartPoint`,
  `refresh_chart`, `templateBool`, log formatting и status-warning decision.
  Status warning вызывает `SamovarApp.addMessage`, buzzer state —
  `SamovarApp.setSoundEnabled`.
- В существующем chart `DOMContentLoaded` заменить локальные theme/chart/poll
  вызовы одним `startTelemetryPage`. Его options повторяют exact
  `implicitSystemTheme: true, dynamicThemeTitle: true`; shared `init()` тем самым
  второй раз применяет theme после построения DOM, `onReady: initChart` сохраняет
  следующий шаг, затем немедленно стартует первый poll. Новый
  `DOMContentLoaded` listener не добавлять и current double-apply timing не
  сокращать до одного вызова.
- В chart удалить только перечисленные local shared owners и orphan
  `setPowerUnit`; existing markup handlers перевести прямо на
  `SamovarApp.toggleTheme/clearMessages`, без global aliases.
- `AddLuaButtons` и другие unrelated chart symbols не чистить попутно: если они
  мертвы, это отдельное finding, а не разрешение расширить U-06.

## 5. Замороженный observable contract

До первого production patch сохранить в `/tmp` normalized DOM, request trace,
computed theme/connection/message state и screenshots. После migration каждой
страницы должны совпасть:

- route, method, body, query names, `2000 ms` cadence и один in-flight request;
- первый poll и следующий poll только после завершения предыдущего;
- mode startup остаётся: `window.onload` -> shared `init()` -> прежний
  page-specific `onReady` order -> immediate first poll; chart startup остаётся:
  shared `initTheme()` в former-IIFE position после `chart.js`/declarations ->
  `DOMContentLoaded` -> повторный shared theme init внутри `startTelemetryPage`
  -> `initChart()`/CSV start -> immediate first poll; дополнительной
  event-loop/DOMContentLoaded задержки нет;
- chart saved `light`/`dark` даёт explicit attribute и не зависит от system
  theme; no saved + system light/dark оставляет attribute unset, но выставляет
  соответственно glyph/title `☾`/`Тёмная тема` либо `☼`/`Светлая тема`; mode
  pages при no saved сохраняют explicit system-derived `light`/`dark`;
- chart toggle из implicit light выбирает/saves `dark`, из implicit dark —
  `light`; reload применяет сохранённую explicit theme. Mode toggle/reload
  сохраняет прежнюю explicit light/dark семантику;
- telemetry formatting/precision, DOM targets, text, button values/colors;
- message order/levels, cursor advance, gap warning, audio state и clear action;
- offline thresholds: index/beer/distiller/BK `3`, NBK `4`, chart `1`;
- page-specific optional-field behavior и все program/control requests;
- chart `GET /data.csv` count, series/legend/status, refresh state и 15 s
  throttle; `data/chart.js` bytes неизменны;
- body DOM/tree/layout и light/dark pixels, кроме отсутствия controller source
  text, которое не рендерится.

Дополнительно проверить chart-specific parity: no history write, exact
`#GreenT/#RedT` visibility, theme glyph/title, connection message suppression
и recovery; удаление непустой очереди вызывает callback с положительным count и
не сбрасывает `IsCalmingPause`, удаление последнего message вызывает callback с
`0` и сбрасывает flag, remove на пустой очереди и `clearMessages()` callback не
вызывают. Если shared owner не может сохранить это минимальными закрытыми
options, остановиться; не менять поведение молча.

## 6. Red-before-green tests

### Новый static smoke

`tools/smoke_shared_ui_controllers.py` сначала обязан быть RED и доказать:

- на шести pages есть local polling/startup ownership;
- chart содержит перечисленные duplicate controllers и orphan power helper.

После реализации он проверяет:

- один definition `startTelemetryPage`, `pollAjax`, theme/message/connection
  owners — только в `app.js`;
- ровно один `startTelemetryPage` на каждой из шести pages;
- zero local `loadDoc`, `startPollLoop`, `ConnectError`, chart message/audio/theme
  helpers; zero chart `setPowerUnit`;
- mode-page `setPowerUnit`, program/PWM/heat functions и local render inventories
  сохранены, не появились в `app.js`;
- exact thresholds/options и запрет неизвестных keys;
- closed option allowlist содержит ровно `threshold`, `onReady`, `connectionIds`,
  `storeMessageHistory`, `dynamicThemeTitle`, `implicitSystemTheme`,
  `onLastMessageRemoved`; оба theme flags имеют boolean validation, callback
  передаёт только chart, пять mode pages его не передают;
- public export inventory добавляет только `startTelemetryPage`: существующий
  `initTheme(options)` расширен, но нового theme symbol/alias нет;
- в exact former-IIFE position существующего chart inline script, после
  `chart.js`/предшествующих declarations и до `initChart`, существует один direct
  parse-time `initTheme({ implicitSystemTheme: true, dynamicThemeTitle: true })`;
  пять mode pages не имеют parse-time theme call;
- `startTelemetryPage` не содержит и не регистрирует `DOMContentLoaded`/`load`;
  пять вызовов находятся внутри существующих `window.onload`, chart-вызов —
  внутри единственного существующего `DOMContentLoaded`; mode options содержат
  exact `implicitSystemTheme: false, dynamicThemeTitle: false`, chart options —
  те же exact `true/true`, что ранний call; порядок двух chart theme applies,
  page-local `onReady` и immediate first poll фиксирован;
- shared theme owner при implicit/no-saved удаляет `data-theme`, использует
  `matchMedia` только для effective glyph/title, не пишет storage и при toggle
  выбирает opposite system theme; explicit policy всегда выставляет attribute;
- storage catch branches существуют только внутри
  `implicitSystemTheme === true`: get failure следует exact no-saved path, set
  failure всё равно вызывает current-DOM `applyTheme(next)`; explicit mode path
  остаётся fail-loud, а generic storage helper/wrapper/retry отсутствует;
- shared remove проверяет непустую очередь, делает actual pop и только затем
  вызывает callback с `messages.length`; `clearMessages` и empty remove callback
  не вызывают; chart callback содержит только exact
  `if (remainingCount === 0) IsCalmingPause = false`, а status decision остаётся
  в local `renderTelemetry`;
- one I2C owner и прежние mounts на пяти mode pages; chart не получил I2C;
- chart.js/CSV/chart symbols отсутствуют в `app.js`;
- routes, template tokens, DOM ids/names и script inventory/count/order неизменны;
  external `src` order остаётся `app.js` -> `chart.js`, новый script element не
  появляется, меняется только тело существующего inline block в former-IIFE
  position.

### Новый browser contract

`tools/test_shared_ui_controllers_browser.py` сначала RED на duplicate lifecycle,
затем GREEN на matrix:

| Ось | Проверки |
|---|---|
| Pages | index, beer, distiller, bk, nbk, chart |
| Viewports/themes | `390x844`, `1440x900`; saved light/dark/no saved × system light/dark, parse-before-DCL, second apply, toggle+reload |
| Polling | initial/second/delayed, one in-flight, timeout/non-2xx/malformed JSON, recovery |
| Events | no event, message/log, sequential cursor, gap, reconnect, no duplicate |
| Startup | five `window.onload` paths; chart theme call at exact former-IIFE position in existing inline script after `chart.js`/declarations, then existing `DOMContentLoaded`; second init/onReady/first-poll order, no new listener or delayed first poll |
| Removal | remaining `2→1` callback without reset; `1→0` callback with chart reset; empty remove and clear produce no callback/reset |
| Page render | required/optional telemetry fields, exact precision/text/visibility |
| Controls | existing action request counts/bodies unchanged; no new request |
| Chart | CSV success/error, refresh, point throttle, indicators, no history write |

Exact theme cases:

| Storage | System | Chart parse-before-DCL | Chart after DCL | Toggle -> reload | Mode pages at `window.onload` |
|---|---|---|---|---|---|
| `light` | light + dark | explicit `light`; effective glyph/title computed, control ещё не смонтирован | explicit `light`, `☾`, `Тёмная тема` | `dark` -> explicit saved `dark` | explicit `light`; dynamic title не добавлен |
| `dark` | light + dark | explicit `dark`; effective glyph/title computed, control ещё не смонтирован | explicit `dark`, `☼`, `Светлая тема` | `light` -> explicit saved `light` | explicit `dark`; dynamic title не добавлен |
| absent | light | no `data-theme`; effective `☾`/`Тёмная тема`, storage absent | no `data-theme`, `☾`, `Тёмная тема` | `dark` -> reload explicit `dark` | explicit `light` |
| absent | dark | no `data-theme`; effective `☼`/`Светлая тема`, storage absent | no `data-theme`, `☼`, `Светлая тема` | `light` -> reload explicit `light` | explicit `dark` |

Parse-before-DCL fixture инструментирует shared owner до разбора chart inline
block и фиксирует возврат direct call в former-IIFE position: theme trace имеет
ровно один apply при `document.readyState === 'loading'`, до
`DOMContentLoaded`, а storage/attribute соответствуют matrix. DCL trace затем
получает ровно второй apply перед `initChart` и first poll; console и pageerror
чистые.

Storage-denied cases проверяются отдельно:

| Page/policy | Fault | Expected current behavior |
|---|---|---|
| chart implicit, system light + dark | `getItem` throws на parse и DCL | no `data-theme`; после DCL system-derived glyph/title; storage не пишется; warning/pageerror отсутствуют |
| chart implicit, system light + dark | absent theme, `setItem` throws на toggle | текущий DOM всё равно получает explicit opposite theme и glyph/title; reload возвращает no-attribute implicit system state |
| chart implicit, system light + dark | `getItem` и `setItem` throw | сочетание двух предыдущих contracts: usable implicit load, explicit current-DOM toggle, implicit state после reload |
| mode explicit | `getItem` throws в `window.onload` | existing pageerror/fail-loud; implicit theme substitution и storage catch отсутствуют |
| mode explicit | `setItem` throws при toggle | existing pageerror/fail-loud; DOM theme не переключается после failed persistence |

Ожидаемые injected mode-storage pageerrors учитываются только в этих двух
negative cases; любое иное console warning/error/pageerror остаётся FAIL.

Unexpected console warning/error, pageerror, duplicate timer/request, missing
selector или visual drift = FAIL. Browser artifacts хранятся только в `/tmp`.

Старые browser tests больше не вызывают удалённый global `loadDoc`; они ждут
реальный lifecycle или вызывают public `startTelemetryPage` fixture. Coverage
I2C/runtime events не ослабляется.

## 7. Точный write allowlist

Production data — ровно:

```text
data/app.js
data/index.htm
data/beer.htm
data/distiller.htm
data/bk.htm
data/nbk.htm
data/chart.htm
```

Tests — ровно:

```text
tools/smoke_shared_ui_controllers.py                 # new
tools/test_shared_ui_controllers_browser.py          # new
tools/smoke_ui_foundations.py
tools/smoke_chart_ui.py
tools/smoke_runtime_event_ring.py
tools/test_i2c_pump_ui_browser.py
tools/test_runtime_event_ui_browser.py
```

Exact downstream updates:

- `smoke_ui_foundations.py`: заменить только legacy local-controller/
  `ConnectError` ownership expectation на one shared owner и exact one start
  per page; сохранить route/script/theme/I2C/DOM assertions;
- `smoke_chart_ui.py`: заменить exact
  `SamovarApp.startPollLoop(loadDoc, 2000)`/chart-local owner assertions на
  former-IIFE-position
  `initTheme({ implicitSystemTheme: true, dynamicThemeTitle: true })` плюс
  `startTelemetryPage(renderTelemetry, ...)` с теми же exact theme flags;
  сохранить script order/count, CSV, series, refresh, 15 s throttle,
  status/connection и request-count assertions;
- `smoke_runtime_event_ring.py`: заменить только chart-local
  `loadDoc`/`ConnectError` sink wiring на shared lifecycle/options; сохранить
  strict `/ajax` cursor/query/message/log/gap assertions;
- `test_i2c_pump_ui_browser.py`: перестать вызывать `loadDoc()` напрямую,
  дождаться/запустить один реальный shared lifecycle tick с controlled fake
  timer/network; сохранить exact I2C GET URL/method/count, present/absent,
  rendering/action и 10 page-cell assertions;
- `test_runtime_event_ui_browser.py`: перестать вызывать `loadDoc()`
  напрямую и управлять real lifecycle; сохранить two-client
  cursor/reconnect/failure/gap, sink/chart и scenario-count assertions.

Ни одно existing assertion/scenario не удалять и не ослаблять; разрешены только
точные owner/reference/selector substitutions. Новый U-06 browser contract
отдельно покрывает shared controller.

Derived contracts — ровно:

```text
web_src/ui-manifest-v1.json
web_update.h
tools/ui_pack_assets_contract.py
tools/smoke_ui_pack_assets.py
tools/smoke_web_update_transaction.py
tools/smoke_web_file_writes.py
```

Последние три smoke меняются только при stale exact SHA/size/projection.
После полного PASS разрешены только affected metadata:

```text
.cli-proxy/.codebase_map/nodes/data.md
.cli-proxy/.codebase_map/nodes/tools.md
.cli-proxy/.codebase_map/nodes/web-src.md
.cli-proxy/.codebase_map/nodes/web-update-h.md
```

`style.css(.gz)`, `chart.js`, `data/edit.htm`, `data/edit.htm.gz`, other
pages, C++/INO, manifests schemas/routes, fixtures, `platformio.ini`,
workflows, libraries, master/ledger запрещены.
Исключение — только status/evidence update после clean review из раздела 10.

## 8. Source/gzip/manifest discipline

- У семи изменяемых sources нет checked-in `.gz` pairs; новые `.gz` не
  создавать. Canonical gzip нужен только для manifest size evidence.
- В `ui-manifest-v1.json` обновить source SHA/size и вычисляемые stored/expanded
  maxima только для фактически изменённых entries.
- В уже существующей A-04 typed projection `web_update.h` обновить только bytes,
  size и SHA тех же entries; transaction/importer/generator не переписывать.
- В `ui_pack_assets_contract.py` обновить только derived input SHA/A10 aggregate/
  totals. Raw/legacy routes, неиспользуемые P1.1 A/B manifest fields и schema
  неизменны; A/B runtime не добавляется.
- `data/version.txt`, local Ace, pack runtime и security additions запрещены.
- Frozen editor pair не regenerates и проверяется по exact SHA/size; U-06 не
  добавляет editor assertions или local Ace.

## 9. Инвентарь после задачи

Проверенная текущая база после локального A-04 и завершённых A-05/A-07 —
`61 smoke / 6 browser / 170 durable tools`. U-06 добавляет ровно два durable
scripts:

```text
после U-06: 62 smoke / 7 browser / 172 durable tools
```

Fixtures/screenshots/traces в repository не добавляются и в inventory не входят.

## 10. Gate и reviewer-loop

Использовать только изолированный стабильный executable:

```text
/tmp/samovar-playwright-cli-0.1.17/node_modules/.bin/playwright-cli
```

Он обязан сообщать `0.1.17`; глобальный alpha binary не использовать и не
менять repository/global environment.

Browser gate выполняется в изолированном subshell и обязан дать `7/7`: новый
U-06 contract плюс все шесть существующих suites без выборочного сокращения.

```bash
(
  export PATH="/tmp/samovar-playwright-cli-0.1.17/node_modules/.bin:$PATH"
  export PLAYWRIGHT_BROWSERS_PATH="/tmp/samovar-playwright-browsers"
  test "$(playwright-cli --version)" = "0.1.17"
  python3 tools/test_shared_ui_controllers_browser.py
  python3 tools/test_i2c_operation_results_browser.py
  python3 tools/test_i2c_pump_ui_browser.py
  python3 tools/test_numeric_input_ui_browser.py
  python3 tools/test_profile_operation_ui_browser.py
  python3 tools/test_program_clear_ui_browser.py
  python3 tools/test_runtime_event_ui_browser.py
)
```

`test_numeric_input_ui_browser.py` остаётся полным regression gate, включая
`program.htm` и `calibrate.htm` в light/dark; их theme scenarios нельзя исключать
как якобы не относящиеся к U-06.

Порядок gate:

1. new static smoke и изменённые focused smokes, включая exact closed-option,
   parse/DCL double theme apply, implicit/explicit toggle policy и
   `onLastMessageRemoved`/`clearMessages` assertions;
2. `python3 -m py_compile` всех changed Python tests;
3. полный browser block выше: новый U-06 + existing `6`, итого exact `7/7`
   через указанный CLI;
4. UI manifest и typed `raw_update` projection/transaction smokes;
5. `PYTHONDONTWRITEBYTECODE=1 python3 tools/run_smoke_tests.py --timeout 60`;
6. `pio run -e Samovar -t buildfs` и `pio run -e Samovar_s3 -t buildfs`, exact
   hashes и LittleFS `< 0xC0000`;
7. blocking cppcheck, затем extended cppcheck; zero unexplained warning/error;
8. frozen post-U-06 source дважды собрать в одинаковой environment и получить
   byte-identical outputs; затем собрать семь environments: `Samovar`,
   `Samovar_s3`, `Samovar_no_power`,
   `Samovar_rmvk`, `Samovar_sem`, `Samovar_lua_mqtt`,
   `Samovar_alarm_button`. Равенство SHA с pre-U-06 не требуется: pre/post
   binary/map/section delta допускается только как механическое следствие
   changed `WEB_UPDATE_ENTRIES` constants в `web_update.h`; новые symbols/
   code paths и необъяснимый flash/RAM/map drift = FAIL;
9. `git diff --check`, exact diff-name allowlist, no repo browser/cache artifacts;
10. targeted mapper update-node/repair только affected nodes и graph check;
11. independent `gpt-5.6-terra` reviewer. Любой ERROR/WARNING исправить,
    повторить affected gates и review до exact
    `PASS: no errors, no warnings`.
12. Только после clean review основной агент добавляет фактический evidence/PASS
    в этот task-plan и обновляет только строку U-06/status в
    `samovar-remaining-remediation-2026-07-12.md`; затем повторяет
    `git diff --check`. До PASS status/ledger не опережают код.

## 11. Stop/rollback

Остановиться при concurrent edit, неготовом prerequisite, необходимости менять
page-specific decisions/layout/routes, добавлять shim/fallback/retry/framework,
переписывать A-04 updater или при невозможности сохранить chart parity.

Если одна ошибка повторилась дважды, прекратить попытки, исследовать web и
сравнить 3–5 решений по правилу repository, затем выбрать одно минимальное.

Rollback — только reverse собственного U-06 patch единой группой sources +
manifest/projection/tests; `git reset/checkout` и очистка чужого dirty tree
запрещены.
