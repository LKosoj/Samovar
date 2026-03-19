# Детальное ТЗ: Шаг 4. Консолидация UI и transport-слоя

Дата: `2026-03-19`

Статус документа:
- draft for review

Связь с master roadmap:
- этот документ является детальным ТЗ для шага 4 из [00_full_refactoring_roadmap_ru.md](/srv/git_projects/Samovar/docs/refactoring/00_full_refactoring_roadmap_ru.md)

Связь с завершённым шагом 3:
- Step 3 closure и подтверждённые program layer invariants зафиксированы в [step3_closure_report.md](/srv/git_projects/Samovar/docs/result/delivery/step3_closure_report.md)

## 1. Назначение

После завершения Шага 3 backend-слой (state, program codecs, runtime) нормализован. Но frontend и transport-слой содержат значительное дублирование:

- 5 mode-страниц (`index.htm`, `beer.htm`, `distiller.htm`, `nbk.htm`, `bk.htm`) содержат ~80% одинакового HTML-каркаса (header, tabs, temperature display, status, power controls, I2C pump, Lua controls)
- Embedded `<script>` блоки в каждой .htm файле дублируют логику инициализации, polling, sound
- Общий объём HTML assets: 263KB, из которых ~100KB — чистый copy-paste
- Web route modules (`template_keys.h`) содержат длинные if-else цепочки для template vars, часть которых можно устранить

Цель Шага 4:
- устранить крупный copy-paste в HTML-каркасе mode-страниц
- вынести общий JS в `common.js`, убрав embedded `<script>` дублирование
- упростить web route modules где возможно без изменения контрактов
- не менять UI/UX, не менять endpoints, не менять JSON-формат `/ajax`

## 2. Обязательные инварианты шага

- Нельзя менять HTTP endpoints (`/ajax`, `/command`, `/program`, `/save`).
- Нельзя менять JSON-формат ответа `/ajax`.
- Нельзя менять template variable names (`%WProgram%`, `%SteamColor%` и т.д.).
- Нельзя менять визуальное поведение UI (layout, цвета, кнопки, порядок элементов).
- Нельзя менять Lua/menu/Blynk contracts — они не входят в этот шаг.
- Нельзя вводить build-time tooling (Webpack, templating engines) — проект остаётся plain HTML/JS/CSS.
- Нельзя вводить новые frontend-frameworks (React, Vue, etc.).
- Каждый подшаг должен заканчиваться рабочим UI, проверяемым в браузере.

## 3. Что входит в шаг 4

- дедупликация common HTML-каркаса mode-страниц через JS-рендеринг
- вынос embedded `<script>` блоков из .htm файлов в `common.js`
- сокращение mode .htm файлов до mode-specific контента
- упрощение `template_keys.h` где возможно
- cleanup `server_init.h` route registration где есть избыточность

## 4. Что не входит в шаг 4

- redesign UI/UX
- изменение polling-модели (замена на WebSockets/SSE)
- изменение JSON-формата `/ajax`
- рефакторинг menu actions или Lua bindings (эти areas не содержат крупного дублирования с web)
- добавление build tooling или frontend frameworks

## 5. Текущее состояние (baseline)

### HTML assets (263KB total)

| Файл | Размер | Роль |
| --- | --- | --- |
| `index.htm` | 37KB | Ректификация |
| `beer.htm` | 28KB | Пивоварение |
| `program.htm` | 28KB | Калькулятор программ |
| `setup.htm` | 26KB | Настройки |
| `nbk.htm` | 22KB | НБК |
| `distiller.htm` | 22KB | Дистилляция |
| `brewxml.htm` | 19KB | Импорт BeerXML |
| `edit.htm` | 18KB | Редактор файлов |
| `bk.htm` | 14KB | БК |
| `chart.htm` | 10KB | Графики |
| `calibrate.htm` | 3KB | Калибровка |
| `wifi.htm` | 2KB | Wi-Fi (standalone) |
| `common.js` | 21KB | Общий JS |
| `style.css` | 13KB | Общий CSS |

### Дублируемые блоки в 5 mode-страницах

| Блок | Файлов | Примерный размер блока |
| --- | --- | --- |
| HTML head + meta + includes | 9 | ~200 байт × 9 |
| Header (version, connection, messages) | 5 | ~1.5KB × 5 |
| Temperature display | 5 | ~2KB × 5 |
| Status line | 5 | ~300 байт × 5 |
| Power/voltage controls | 5 | ~3KB × 5 |
| System parameters | 5 | ~200 байт × 5 |
| I2C Pump tab | 5 | ~1KB × 5 |
| Lua controls | 4 | ~1KB × 4 |
| Tab navigation boilerplate | 5 | ~500 байт × 5 |
| Embedded `<script>` init/polling | 5 | ~3KB × 5 |
| **Итого дублирования** | | **~60KB** |

### Transport architecture

```
Browser → HTTP GET .htm → Template processor (%vars%) → HTML response
Browser → HTTP GET /ajax (poll 2s) → JSON snapshot → JS updates DOM
Browser → HTTP POST /command → Action → OK/error text
Browser → HTTP POST /program → set_program_for_mode → program text
```

## 6. Архитектурное решение шага

### Подход: JS-based common shell

Платформа (ESP32 + SPIFFS + AsyncWebServer) не поддерживает SSI (server-side includes). Единственный доступный серверный механизм — `%var%` template substitution.

Рекомендуемый подход:
1. **Общий HTML-каркас** рендерится из `common.js` при загрузке страницы
2. **Mode-specific контент** остаётся в .htm файлах, но содержит только уникальные секции (mode-specific inputs, controls, displays)
3. **Template %vars%** для начальных значений (colors, settings) переносятся в скрытый `<div>` в .htm или в первый ответ `/ajax`

### Результат

- 5 mode .htm файлов уменьшаются с ~125KB суммарно до ~40-50KB
- `common.js` увеличивается с 21KB до ~35-40KB
- Общий объём assets уменьшается на ~40-50KB
- gzip-сжатие более эффективно на крупном JS (один файл vs 5 повторов)

## 7. Декомпозиция на подзадачи

### Подзадача 4.1. Инвентаризация и baseline smoke

Цель:
- зафиксировать текущий baseline UI в виде скриншотов/checklist для каждого режима
- подготовить автоматизированный smoke-тест через playwright-cli

Что сделать:
- скриншот каждой mode-страницы (index, beer, distiller, nbk, bk)
- скриншот setup, program, chart страниц
- checklist видимых элементов на каждой странице
- playwright-cli baseline smoke script

Критерии приёмки:
- есть baseline для визуального сравнения после рефакторинга

### Подзадача 4.2. Вынос embedded `<script>` блоков в common.js

Цель:
- убрать дублирование инициализации, polling, sound setup из .htm файлов

Что сделать:
- идентифицировать все embedded `<script>` блоки в 5 mode pages
- вынести общую инициализацию (connection check, polling setup, sound, messages) в `common.js`
- оставить в .htm только mode-specific JS (если есть)
- в .htm файлах — единый `<script>initPage('mode_name');</script>` вызов

Нельзя:
- менять polling interval (2000ms)
- менять формат /ajax response
- менять логику обновления DOM-элементов

Проверки:
- playwright-cli smoke на все 5 mode pages
- ручная проверка temperature updates, status, messages

### Подзадача 4.3. Вынос общего header/status/system params в JS

Цель:
- убрать copy-paste header block, status line, system parameters из 5 mode pages

Что сделать:
- создать JS-функции `renderHeader()`, `renderStatusLine()`, `renderSystemParams()`
- .htm файлы содержат `<div id="common-header"></div>` placeholder
- `common.js` заполняет placeholder при инициализации

Нельзя:
- менять визуальный layout
- менять id/class names существующих элементов (JS polling обновляет по id)

Проверки:
- playwright-cli smoke
- проверка, что polling-обновления (version, connection, status, heap, rssi) работают

### Подзадача 4.4. Вынос temperature display и power controls в JS

Цель:
- убрать copy-paste temperature block и power/voltage controls из 5 mode pages

Что сделать:
- создать JS-функции для temperature display (с учётом mode-specific датчиков)
- создать JS-функцию для power/voltage control block
- параметризовать по режиму (какие датчики показывать, какие скрывать)

Нельзя:
- менять порядок отображения датчиков в конкретном режиме
- менять template-var имена для colors

Проверки:
- playwright-cli smoke для каждого режима
- проверка, что temperature hide/show (%SteamHide%, %PipeHide% etc.) работает
- проверка, что color settings применяются

### Подзадача 4.5. Вынос I2C pump и Lua controls в JS

Цель:
- убрать copy-paste I2C pump tab и Lua controls из mode pages

Что сделать:
- создать JS-функции для I2C pump block и Lua controls
- .htm файлы содержат только placeholders

Проверки:
- playwright-cli проверка I2C pump tab visibility и controls
- проверка Lua buttons и script execution

### Подзадача 4.6. Финальная зачистка web route modules

Цель:
- упростить `template_keys.h` и `server_init.h` где возможно

Что сделать:
- если template vars для common blocks переехали в JS, убрать их из `indexKeyProcessor`
- проверить, нет ли dead routes или unused template vars
- cleanup server_init.h если есть redundancy

Нельзя:
- менять endpoint URLs
- менять JSON format
- убирать template vars, которые ещё используются

### Подзадача 4.7. Финальная интеграционная верификация Шага 4

Цель:
- закрыть step gate перед переходом к Шагу 5

Что сделать:
- playwright-cli full smoke на все страницы
- build matrix (`pio run -e Samovar`, `pio run -e lua_expander`)
- ручной smoke на hardware
- closure report

Критерии приёмки:
- frontend не содержит крупного copy-paste каркаса
- UI визуально идентичен baseline
- все функции (polling, commands, program upload, settings) работают
- общий объём assets уменьшился

## 8. Порядок исполнения

Строго последовательно:
1. **4.1** — baseline (нельзя начинать рефакторинг без baseline для сравнения)
2. **4.2** — embedded scripts (наименее рискованный первый шаг)
3. **4.3** — header/status (простые read-only блоки)
4. **4.4** — temperatures/power (сложнее — mode-specific параметризация)
5. **4.5** — I2C/Lua (отдельные tab-блоки)
6. **4.6** — route cleanup (после стабилизации frontend)
7. **4.7** — closure

## 9. Риски шага

- Ломается DOM-структура, polling JS не находит элементы по id → не обновляются данные
- Template %vars% для colors перестают работать после переноса в JS
- gzip cache в браузере показывает старую версию common.js
- Увеличение common.js может замедлить первую загрузку
- Mode-specific CSS breaks после изменения HTML structure

Способ снижения рисков:
- playwright-cli smoke после каждого подшага
- не менять id/class имена элементов
- cache-control headers уже настроены (`no-cache` для mode pages, `max-age=5000` для static)
- инкрементальный подход — по одному блоку за подшаг

## 10. Gate завершения шага 4

Шаг 4 считается завершённым только если одновременно выполнено всё ниже:
- frontend не содержит крупного copy-paste HTML-каркаса между mode pages
- все mode pages визуально идентичны baseline
- polling, commands, program upload, settings работают без изменений
- web route modules упрощены где это было уместно
- в UI layer нет shim, adapter и compat wrappers
- build и regression checks подтверждают отсутствие регрессии
- playwright-cli smoke подтверждает функциональность

## 11. Рекомендуемый следующий исполнимый task

Следующим открывать:
- **Подзадача 4.1**: baseline smoke и скриншоты

Почему:
- нельзя безопасно рефакторить frontend без baseline для визуального сравнения
- playwright-cli даёт автоматизированную проверку, которая нужна на каждом подшаге
