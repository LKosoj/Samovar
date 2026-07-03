# Аудит архитектуры, кода и UI проекта Samovar

Дата: 2026-07-02. Метод: параллельный аудит по направлениям (персоны architect / cpp-dev / reviewer из skill `dev-experts`), затем сводка и приоритизация.

Статус: **завершён** — все 7 проверок выполнены (6 зон + углублённый аудит конкурентности), результаты сведены в разделе 7.

## Содержание

1. [Архитектура](#1-архитектура) — модель сборки, модульность, конкурентность, слои
2. [Код прошивки: ядро](#2-код-прошивки-ядро) — Samovar.ino, logic.h, sensorinit.h, runtime_helpers.h
3. [Код прошивки: I/O и веб-слой](#3-код-прошивки-io-и-веб-слой) — WebServer.ino, NVS_Manager.ino, FS.ino, Menu.ino, Blynk.ino, lua.h
4. [Код прошивки: режимы](#4-код-прошивки-режимы) — distiller.h, beer.h, nbk.h, BK.h, mod_rmv, impurity_detector.h
5. [UI: основные страницы](#5-ui-основные-страницы) — index, setup, program, chart
6. [UI: страницы режимов](#6-ui-страницы-режимов) — beer, distiller, nbk, bk, i2cstepper, прочее
7. [Сводка и приоритеты](#7-сводка-и-приоритеты)

Обозначения серьёзности: 🔴 Критично (баг/UB/гонка) · 🟠 Важно (риск отказа, потеря данных) · 🟡 Средне (качество, сопровождение) · ⚪ Мелочь (стиль).

---

## 1. Архитектура

### 1.1. Архитектурная карта

**Модель сборки.** PlatformIO с `src_dir = .` (platformio.ini:12), совместимо с Arduino IDE: корневые `.ino` (Samovar, WebServer, NVS_Manager, Menu, FS, Blynk, crash_handler, mod_rmv) конкатенируются в одну единицу трансляции, остальная логика — в корневых `.h`. Порядок include задаёт Samovar.ino: `Samovar.h`(:77) → `runtime_helpers.h`(:80) → `lua.h`(:93) → `mod_rmvk.h`(:125) → `logic.h`(:128) → `I2CStepper.h`(:156) → `distiller.h` → `beer.h` → `BK.h` → `nbk.h`(:157–160) → `SPIFFSEditor.h`(:161) → `sensorinit.h`(:168). Циклы между «слоями» разорваны не архитектурой, а стенами форвард-деклараций в каждом файле (WebServer.ino:11–91, distiller.h:8–187 и т.д.). Библиотеки полностью вендорены в `./libraries` (~35 шт., в т.ч. **патченный** Async_TCP). Разделы: `partitions/samovar.csv` (app0/app1 по 0x190000, spiffs 0xC0000, coredump 0x10000) — подключён через platformio.ini:26; в корне лежит второй, устаревший `partitions.csv` с другой разметкой.

**Задачи/ядра (фактические, по коду):**

```
core 0                                 core 1
──────────────────────────────         ──────────────────────────────
SysTicker (prio 1)                     loopTask (Arduino)
  triggerSysTicker: DS18B20,             loop(): pending_*-команды,
  давление, аварии по режимам,           sam_command_sync-диспетчер,
  прогресс, get_Samovar_Status()         withdrawal()/…_proc(), меню,
  (Samovar.ino:452,1232)                 Blynk, OTA (Samovar.ino:1310)
PowerStatusTask (prio 1)               GetClockTicker (prio 1)
  UART-регулятор (logic.h:1592/1660,     NTP, WiFi/Blynk/MQTT reconnect
  Samovar.ino:1187)                      (Samovar.ino:354,1242)
async_tcp (prio 5!)                    DoLuaScriptTask (prio 1)
  веб-хендлеры ESPAsyncWebServer         (lua.h:1011–1018)
  (libraries/Async_TCP/…/AsyncTCP.h:52)
                       ISR: StepperTicker (hw-timer, Samovar.ino:339)
```

Синхронизация: `xRuntimeStateSemaphore` через `runtime_state_lock/unlock` (runtime_helpers.h:8–14) для общих String (Msg/LogMsg/SamovarStatus/WthdrwTimeS/current_power_mode); `xI2CSemaphore` (1000 мс, I2CStepper.h:125,135) на каждую I2C-транзакцию; `xSemaphoreAVR` для UART-регулятора (logic.h:1850); `timerMux` portMUX для GyverStepper (runtime_helpers.h:111–179). Команды из веба — одноместный mailbox `sam_command_sync` (Samovar.h:375, разбор в Samovar.ino:1404–1489) и семейство `volatile pending_*`-флагов с буферами и `__sync_synchronize()` (Samovar.ino:184–254, обработка в loop() 1497–1646).

**Слои (номинальные):** web (WebServer.ino, FS.ino, SPIFFSEditor.h, data/) → логика (logic.h) → режимы (distiller.h, beer.h, BK.h, nbk.h) → железо (sensorinit.h, I2CStepper.h, pumppwm.h, mod_rmvk.h). Настройки — `SetupEEPROM SamSetup` (~70 полей, Samovar.h:386–456), персистентность — NVS_Manager.ino (самый дисциплинированный модуль: static-функции, namespace-ы, миграция legacy, backup/restore). Фактически слоистости нет: `logic.h` (2080 строк) — одновременно общая библиотека (клапаны/буззер/питание/шаговик), режим ректификации и статус-агрегатор всех режимов; всё связано через ~120 глобалов в Samovar.h (работает только благодаря одной TU); `SamSetup` читается/пишется в 16 файлах (~640 упоминаний).

### 1.2. Проблемы

**[🔴] Модель конкурентности не соответствует реальности: async_tcp работает на core 0 с приоритетом 5, дефайны в скетче мертвы** — Samovar.ino:18–19, Samovar.h:4–5, libraries/Async_TCP/src/AsyncTCP.h:35–52. В скетче `#define CONFIG_ASYNC_TCP_RUNNING_CORE 1`, но библиотека компилируется отдельной единицей трансляции и этих дефайнов не видит. Вендоренный заголовок жёстко задаёт `CONFIG_ASYNC_TCP_RUNNING_CORE 0` и `CONFIG_ASYNC_TCP_PRIORITY 5` (AsyncTCP.cpp:382 использует именно их). Итог: веб-задача сидит на одном ядре с SysTicker (prio 1) и **вытесняет** его — тяжёлый хендлер тормозит опрос датчиков и аварийные проверки. Документация и комментарии проекта исходят из ложной посылки «async_tcp на core 1».

**[🔴] Блокирующий I2C из async-контекста на каждый опрос /ajax** — Samovar.ino:1778 внутри `send_ajax_json` (роут /ajax, WebServer.ino:345): `i2c_get_liquid_rate_by_step(get_stepper_speed())`. `get_stepper_speed()` (I2CStepper.h:362–365) вызывает `i2c_stepper_refresh()` — ~30 последовательных чтений регистров, каждое под `xSemaphoreTake(xI2CSemaphore, 1000 мс)` (I2CStepper.h:135, 183–225). Комментарий [W-3] строкой ниже и кэш `i2c_stepper_cache` существуют именно для этого случая, но эта строка кэш обходит. При подключённом I2C-насосе каждый ajax-опрос гоняет шину из веб-задачи; при залипании шины — до секунд блокировки async_tcp (на core 0 — и голодание SysTicker).

**[🔴] `vTaskDelay` и UART из async-хендлера** — WebServer.ino:1366–1369 (`/command?voltage=`) → logic.h:1820–1868 `set_current_power`: `vTaskDelay(100)` (:1845), в варианте SEM_AVR — `xSemaphoreTake(xSemaphoreAVR, ≈3.3 с)` (:1850) плюс задержки 300 мс (:1857–1859) и запись в Serial2. Каждый клик по регулятору мощности замораживает TCP-стек.

**[🔴] Пачка блокирующих I2C из `/command?mixer=`** — WebServer.ino:1318–1323 → `set_mixer` (beer.h:1001) → `set_mixer_state` (beer.h:639–680): четыре вызова `i2c_stepper_mixer_present()/i2c_stepper_pump_present()` (:648, :660, :672, :676), каждый — полный `i2c_stepper_refresh`, плюс I2C-записи. Для соседних команд (`/i2cstepper`, `/i2cpump`, `pnbk`) идиома `pending_*` применена (WebServer.ino:1324–1330, Samovar.ino:1551–1616), для `mixer`, `watert` (:1355–1356), `pumpspeed` (:1357–1358, останавливает/перезапускает шаговик отбора прямо из async) и `nbkopt` (:1331–1336, нелоченая запись `nbk_Mo`/`nbk_Po`) — нет. Идиома выполнена на ~80%, оставшиеся 20% — самые тяжёлые операции.

**[🟠] `handleSave`: ~70 полей SamSetup пишутся напрямую из async без лока и почти без валидации** — WebServer.ino:971–1060 и далее: `SamSetup.SteamDelay = request->arg("SteamDelay").toInt();`. Поля конкурентно читаются в SysTicker (например `SamSetup.MaxPressureValue` в аварийной проверке Samovar.ino:466, `SamSetup.LogPeriod` :558) и в loop. `toInt()/toFloat()` без проверки диапазонов (валидация есть только у `mode`, :990–1000). Для float/многобайтовых полей возможны рваные чтения; для порогов аварий это неприятно. Сохранение в NVS корректно отложено через `pending_save_profile_flag`.

**[🟠] GET-запросы страниц мутируют `Samovar_Mode`** — WebServer.ino:185–199 (`send_index_page`: `Samovar_Mode = (SAMOVAR_MODE)cfgMode;` :193) и :202–216 (`send_mode_specific_htm`, :211). Открытие страницы браузером меняет глобальный режим, по которому диспетчеризуются loop() и SysTicker, из веб-задачи без синхронизации. Две вкладки с разными страницами — гонка на режиме.

**[🟠] `sam_command_sync` — одноместный почтовый ящик с потерей команд** — Samovar.h:375, писатели: web_command, Menu.ino:444–476, Blynk.ino, lua.h; читатель — loop() (Samovar.ino:1404–1489). Две команды за одну итерацию loop → первая молча теряется (last-writer-wins). Дополнительно web_command глушит команды 1500-мс rate-limit'ом, отвечая «OK» (WebServer.ino:1255–1260).

**[🟠] Кросс-задачные String без защиты** — `SessionDescription`: пишется из async (WebServer.ino:1416), читается/модифицируется из loop-контекста в четырёх режимах (`SessionDescription.replace(",", ";")` + MqttSendMsg — BK.h:111–112, distiller.h:223–224, beer.h:279–280, nbk.h:670–671, Menu.ino:534–535). Присваивание Arduino String = free+malloc; параллельный replace из другой задачи — порча кучи. Аналогично `pending_program_str` (Samovar.ino:186): loop копирует её (:1508) без лока, повторный POST /program в этот момент пишет туда же (WebServer.ino:1393).

**[🟠] `get_Samovar_Status()` — «геттер», который двигает FSM всех режимов** — logic.h:387–535: формирование строки статуса перемешано с переходами `SamovarStatusInt = 10/15/20/30/40/50` (:395–:419) и режимными ветками вплоть до пивных деталей (`getBeerCurrentTemp`, :451). Управляющий автомат спрятан в функцию форматирования UI-текста, вызываемую раз в секунду из SysTicker (Samovar.ino:825); магические статусы (1000/2000/3000/4000) продублированы во входных проверках режимов (distiller.h:219, beer.h:273, nbk.h:742).

**[🟠] Копипаста между режимами уже разошлась по поведению** — не стилистика, а источник багов:
- Авария «прекращена подача воды» — 4 дословные копии (BK.h:182–187, distiller.h:378–383, nbk.h:820–825, logic.h:1055–1061).
- «Критическая температура воды» — 4 копии с расползшимися константами: пауза 30000 мс (BK.h:204, distiller.h:399) против 60000 мс (nbk.h:830); понижение мощности `-5` (distiller.h:396) против `-5*PWR_FACTOR` (logic.h:1071–1077) — правку внесли в одну копию.
- ПИД насоса — 3 копии; в logic.h:1026 порог захардкожен `> 39` вместо `SamSetup.SetACPTemp`, как в distiller.h:357/nbk.h:812.
- Парсеры/сериализаторы программ — по 4 копии одного скелета (`set_program` logic.h:563 / distiller.h:454 / beer.h:855 / nbk.h:881; `get_*_program` logic.h:654 / distiller.h:523 / beer.h:834 / nbk.h:954) с дословным триммингом строк.
- Финиш асимметричен: `distiller_finish`/`bk_finish` — обёртки над `stop_process` (logic.h:377–382), а `nbk_finish` (nbk.h:838–860) повторяет тело вручную **без** `SamovarStatusInt = 0`.
- Дубль математики отбора: logic.h:89–98 и I2CStepper.h:296–300, 412–414 — одинаковые формулы `round(... * 3.6 * 1000) / 1000`.

**[🟡] Диспетчеризация режима размазана по ~32 местам в 8+ файлах** — добавление режима требует правок: enum-ы (Samovar.h:374, :377), диспетчер аварий (Samovar.ino:626–637), главный диспетчер loop (:1648–1657), case-ы команд (:1448–1474), кнопка (:1356–1399), выбор страницы (WebServer.ino:178–183), web_command `start`/`power` (:1272–1299), `stop_active_process_for_mode` (:920–933), шаблонизаторы (:561–564, :661–663), Menu.ino:441–479, Blynk.ino:206–299, lua.h:199–258 и :1262+, FS.ino:156–218, sensorinit.h:12–22, get_Samovar_Status. Магические `SamovarStatusInt`/`startval` (1000/2000/3000/4000) зашиты в каждый модуль.

**[🟡] God-функции и god-модуль** — setup() 475 строк (Samovar.ino:833), triggerSysTicker 379 (:452), loop() 360 (:1310), WebServerInit 294 (WebServer.ino:234), setupKeyProcessor 285 (:609), handleSave 280 (:971), check_alarm 274 (logic.h:885), send_ajax_json 221 (Samovar.ino:1698). `logic.h` смешивает отбор, аварии, клапаны, буззер, самотест, смачивание и **две** реализации UART-задачи регулятора (logic.h:1592 и :1660 под #ifdef).

**[🟡] Слоистость нарушена в обе стороны, зависимости циклические** — sensorinit.h:12–22 `load_default_program_for_mode()` задаёт дефолтные рецепты режимов (`set_beer_program(...)`); режимы напрямую дергают транспорт (`MqttSendMsg` в BK.h/distiller.h/beer.h/nbk.h; `SendMsg` из Samovar.ino:2039 — ~45 вызовов из logic.h) и LCD-меню (logic.h:1243 `set_menu_screen(2)`, :140 `menu_samovar_start()`). Явные циклы: logic.h↔Samovar.ino, logic.h↔sensorinit.h, logic.h↔Menu.ino. Симптом — стены форвард-деклараций с дублями: в WebServer.ino восемь функций объявлены по два раза (:39–46 и :60–69); distiller.h объявляет `set_capacity` дважды (:152, :168); прототип `SendMsg` продублирован в 10 файлах.

**[🟡] Нет include guards у ключевых заголовков; глобалы определяются в .h** — logic.h, distiller.h, beer.h, nbk.h, BK.h не имеют ни `#pragma once`, ни guard, при этом содержат не-inline определения и глобалы (nbk.h:207–237 — два десятка `float nbk_*`; quality.h:23–24 — `float steamTempHistory[60]` в заголовке). Второй include ломает сборку; порядок include — неявный контракт, зафиксированный только в Samovar.ino.

**[🟡] Две таблицы разделов** — корневой partitions.csv (app 0x160000, spiffs 0x130000, без coredump) не совпадает с реально используемым partitions/samovar.csv (platformio.ini:26). Инструкция в шапке Samovar.ino:6–10 — по устаревшему файлу можно прошить несовместимую разметку.

**[⚪] Мёртвый и декоративный код** — quality.h подключён только из distiller.h:3, его `QualityParams/overallScore` используются лишь в закомментированном блоке distiller.h:294–303; закомментированные task-создания в setup() (Samovar.ino:1251–1269). SPIFFSEditor с зашитыми `admin/admin` (FS.ino:7–8) даёт полный RW-доступ к FS — по AGENTS.md для DIY приемлемо, но упомянуть стоит.

### 1.3. Что сделано хорошо

Чистые обёртки runtime_helpers.h; потоковая генерация JSON через `AsyncResponseStream` вместо конкатенации String (Samovar.ino:1672–1704) — снижает фрагментацию кучи; идиома `pending_*` с барьерами применена системно (Samovar.ino:184–254); кэш I2C-статуса `i2c_stepper_cache`, обновляемый из SysTicker (Samovar.ino:206–213, 527–537); coredump-раздел + crash_handler; вендоринг библиотек; NVS_Manager — дисциплинированный модуль с миграцией legacy и backup/restore.

### 1.4. Предложения по улучшению архитектуры

Все совместимы с ограничением «одна единица трансляции, только .h/.ino в корне, новый код — inline в .h».

1. **Синхронизировать заявленную и фактическую модель async_tcp.** Либо перенести `CONFIG_ASYNC_TCP_RUNNING_CORE/PRIORITY` в `build_flags` platformio.ini (тогда они реально дойдут до библиотеки) и удалить мёртвые дефайны из Samovar.ino:18–19/Samovar.h:4–5, либо осознанно оставить core 0, но опустить приоритет до ≤1 в вендоренном AsyncTCP.h и задокументировать. *Усилия: часы. Риск: средний — меняется реальное планирование под нагрузкой, нужен прогон с параллельными /ajax + активным процессом. Выгода: высокая — исчезает класс «веб тормозит датчики».*
2. **Дочистить идиому `pending_*` до 100%.** Перевести `mixer`, `voltage`, `watert`, `pumpspeed`, `nbkopt`, `Descr` на существующий механизм (по образцу `pending_pnbk_*`), а в send_ajax_json заменить `get_stepper_speed()` на чтение `i2c_stepper_cache.pump_current_speed` (кэш уже есть). *Усилия: 1–2 дня. Риск: низкий. Выгода: высокая — закрывает все 🔴, кроме первого.*
3. **Заменить `sam_command_sync` и разрозненные pending-флаги на одну FreeRTOS-очередь команд** (`xQueueCreate(8, sizeof(SamovarCmdMsg))` — enum + числовые аргументы + char[] для строк; String в очередь не класть). Убирает потерю команд, барьеры и десяток флагов. *Усилия: 2–4 дня. Риск: средний — `SAMOVAR_RESET` сейчас обрабатывается особо (Samovar.ino:1486–1488), мигрировать по одной команде. Выгода: высокая, архитектурно самый чистый шаг.*
4. **Реестр режимов на указателях функций.** Новый `mode_registry.h` (после всех режимных .h): `struct ModeOps { void (*proc)(); void (*check_alarm)(); void (*finish)(); void (*set_prog)(String); String (*get_prog)(); const char* index_htm; SamovarCommands start_cmd; int16_t status_base; }` + `static const ModeOps MODES[]`. Сначала перевести диспетчеры loop() (Samovar.ino:1648–1657) и аварий (:626–637), выбор страницы и `stop_active_process_for_mode`; остальные ~25 мест — постепенно. NBK-особенность оборачивается адаптером. *Усилия: неделя. Риск: средний — мигрировать по одному диспетчеру со сверкой. Выгода: «добавить режим» = один .h + строка таблицы вместо правки 8 файлов.*
5. **Вынести продублированную аварийную логику и парсер программ в общие inline-хелперы** (`mode_common.h`: `check_water_supply_alarm()`, `check_water_overheat(pause_ms, delta)`, `close_valve_after_cooldown(threshold)`, `pump_pid_tick()`; `program_io.h`: общий скелет parse/serialize с таблицей полей на режим). Устраняет 4×4 копий с разошедшимися константами (30000/60000 мс, `-5` vs `-5*PWR_FACTOR`, захардкоженный `39`). Расхождения придётся явно решить — это и есть скрытые баги. *Усилия: 3–5 дней, половина — выяснение «какая копия права». Риск: средний — унификация изменит поведение минимум двух режимов; делать по одному блоку. Выгода: высокая — правки аварий перестанут «не доезжать» до трёх из четырёх режимов.*
6. **Валидация и атомарное применение настроек.** В `handleSave` парсить аргументы в локальную `SetupEEPROM staged` с проверкой диапазонов, затем отдавать в loop через флаг (расширить `pending_save_profile_flag` буфером) и применять целиком. *Усилия: 2–3 дня. Риск: низкий. Выгода: средняя-высокая — исчезают рваные записи порогов аварий; 280-строчная функция станет табличной.*
7. **Include guards везде + распил logic.h по темам.** Сначала `#pragma once` в logic.h/distiller.h/beer.h/nbk.h/BK.h (нулевой риск). Затем механически вынести из logic.h `alarm.h`, `power_regulator.h` (triggerPowerStatus ×2, set_current_power), `valve_buzzer.h`, `selftest.h`, сохранив порядок include. *Усилия: 1–2 дня. Риск: низкий. Выгода: средняя — навигация и ревью; предпосылка для шагов 4–5.*
8. **Единый `samovar_api.h` с форвард-декларациями** вместо стен дублирующихся прототипов (включается сразу после Samovar.h). Убирает дубли (`SendMsg` ×10, повторные блоки WebServer.ino:39–69). *Усилия: день. Риск: почти нулевой. Выгода: средняя — единая точка правды об API.*
9. **Гигиена артефактов сборки.** Удалить корневой partitions.csv (или заменить копией partitions/samovar.csv), поправить инструкцию в Samovar.ino:6–10; удалить мёртвый quality.h либо довести до использования; выпилить закомментированные task-блоки из setup(). *Усилия: час. Риск: нулевой. Выгода: убирает сценарий прошивки неверной разметки через Arduino IDE.*

Приоритет: 2 → 1 → 6 (закрывают 🔴/🟠 при минимальном риске), затем 5 и 4 (главный источник будущих багов), 3/7/8/9 — по мере плановых работ.

### 1.5. Глубокий аудит конкурентности

Контексты: `triggerSysTicker` — core 0 (Samovar.ino:1232–1239), `loopTask`+`triggerGetClock`+`do_lua_script` — core 1 (Samovar.ino:1242–1249, lua.h:1011–1018), `triggerPowerStatus` — core 0 (Samovar.ino:1187–1194), async_tcp — отдельная задача AsyncWebServer.

**Идиома `pending_*` (объявления Samovar.ino:180–254, обработка только в loop() Samovar.ino:1491–1646) — корректно реализована для:** программы (`pending_program_*`), смены режима, `rescands`, `save_profile`, `luastr`, `/i2cstepper` (staged-копия WebServer.ino:445–456), `/i2cpump`, `/calibrate?pump=i2c`, `pnbk`. Барьеры `__sync_synchronize()` на местах.

**Обработчики, нарушающие идиому (прямые FS/NVS/I2C/delay/restart из async):**

1. **[🔴] `/command?resetwifi` → `menu_reset_wifi()`** — WebServer.ino:1309–1310 → Menu.ino:434–436: `wifiManager.resetSettings(); ESP.restart();` — стирание WiFi-настроек (flash) и **прямой рестарт из async_tcp**; ответ `request->send(200)` (WebServer.ino:1384) никогда не уйдёт. Из меню (loopTask) тот же вызов легален.
2. **[🔴] Общий `lua_State` без мьютекса из параллельных контекстов** — `LuaWrapper lua` (lua.h:11) исполняется в SysTicker core 0 (`lua.Lua_dostring(&local_btn_script)` Samovar.ino:504), в задаче do_lua_script core 1 (lua.h:1141, 1153, `lua_gc` :1158), в loop core 1 (Samovar.ino:1545) и из Blynk в loopTask (Blynk.ino:25). Core 0 и core 1 могут исполнять Lua одновременно — порча интерпретатора.
3. **[🔴] Блокирующий I2C в async** — `/ajax` → `get_stepper_speed()` + **второй** refresh в `i2c_get_liquid_volume_by_step` (Samovar.ino:1778, I2CStepper.h:362–364, 407); `/command?mixer` → `set_mixer_state` с `i2c_stepper_send_command` (цикл `for(i<20) vTaskDelay(10ms)` — до ~200 мс, beer.h:648–661, I2CStepper.h:257–258).
4. **[🟠] String-гонки между задачами без лока** — `SessionDescription` (async WebServer.ino:1416 vs loop BK.h:111 и др.); `program[].WType` (loop logic.h:563–651 vs SysTicker logic.h:497 vs async WebServer.ino:560–565); `Lua_status` (lua.h:583 vs async Samovar.ino:1914); **`Msg` мимо замка в Lua** — lua.h:490 `Msg = Val;` и lua.h:649 — без `runtime_state_lock`, тогда как все остальные обращения к Msg идут под замком (runtime_helpers.h:35–64).
5. **[🟠] OneWire без взаимного исключения** — `DS_getvalue()` в SysTicker core 0 (sensorinit.h:195–226) vs `scan_ds_adress()` в loop core 1 по `pending_rescan_ds_flag` (sensorinit.h:274–318): идиома убрала скан из async, но loop и SysTicker могут работать с 1-Wire одновременно — DallasTemperature не потокобезопасна: битые тайминги, мусорные адреса в `DSAddr`.
6. **[🟠] `handleSave`: массовая запись SamSetup и сенсорных структур из async без лока** (WebServer.ino:1003–1231), вкл. неатомарные `copyStringSafe` в char[] (:1135) и `SteamSensor.Sensor[0] = 255; SteamSensor.avgTemp = 0;` (:1181–1183); NVS-снимок из loop может зафиксировать полуобновлённое состояние; `DSAddr/DScnt` читаются в async (:836–845, :1173–1220).
7. **[🟠] `/command?pumpspeed` из async** — logic.h:334–355: запись `program[].Time`, `CurrrentStepperSpeed` и старт/стоп hw-таймера `stopService()/startService()` (Samovar.ino:321–337) без `timerMux`.
8. **[🟠] FS из async вопреки идиоме** — SPIFFSEditor: удаление/создание/запись файлов прямо в хендлерах (SPIFFSEditor.h:298, 318–321, 340, плюс `load_lua_script()` после аплоада .lua :344–347); `run_lua_script` читает SPIFFS (lua.h:1051–1053); шаблонизатор `%btn_list%` перебирает каталог SPIFFS (WebServer.ino:580 → lua.h:1024–1034).
9. **[🟡] Torn-read POD-структур** — `I2CStepperDevice staged = *dev;` в async (WebServer.ino:445) во время посекундного refresh в SysTicker (Samovar.ino:530–536); аналогично `send_i2c_stepper_json` (WebServer.ino:140–165).
10. **[🟡] Флаги без volatile** — `is_reboot` (Samovar.h:534), `shouldSaveWiFiConfig` (Samovar.ino:178); `nbk_M/Mo/P/Po` без volatile/лока (nbk.h:209–214 vs WebServer.ino:1332–1333).
11. **[🟡] Окно гонки на pending-строках** — loop сбрасывает `pending_lua_flag` до копирования строки (Samovar.ino:1542–1544) — повторный запрос может писать `pending_lua_str` во время копии; то же для `pending_program_str`; запись `Samovar_Mode` из async GET-обработчиков (WebServer.ino:193, 211).
12. **[⚪] Тихая деградация при таймауте замка** — `append_web_message`/`append_console_log`: `if (!locked) return;` (runtime_helpers.h:50–51, 79–80) — тихая потеря сообщения; SysTicker при отказе не обновляет `Crt/StrCrt/WthdrwTimeS` — устаревшие данные без порчи.

**Что проверено и оказалось в порядке:** двойного захвата нерекурсивного `xRuntimeStateSemaphore` по одному пути не найдено — все критические секции листовые; порядок «`xSemaphoreAVR` → runtime lock» (logic.h:1666–1684) односторонний, дедлок-цикла нет; весь сырой I2C — под `xI2CSemaphore` (BME/BMP sensorinit.h:83–123, XGZ :138–141, LCD Menu.ino:184–239, Lua-экспандер lua.h:115–162); позиции шаговика закрыты `stepper_safe_*` под `portENTER_CRITICAL(&timerMux)` (runtime_helpers.h:111–179), включая вызов из async в `/calibrate` (WebServer.ino:1466); `http_sync_request_get` с vTaskDelay (WebServer.ino:1633–1691) вызывается только из setup-контекста; игнорирования результата `runtime_state_lock` с продолжением записи не найдено.

## 2. Код прошивки: ядро

Зона: Samovar.ino, logic.h, sensorinit.h, Samovar.h, runtime_helpers.h, Samovar_ini.h, time_utils.h, string_utils.h, column_math.h, quality.h, crash_handler.h/.ino; перекрёстно — WebServer.ino, Menu.ino, FS.ino, I2CStepper.h, lua.h, impurity_detector.h. Дедлок-скан по `runtime_state_lock` отрицательный: вложенных захватов не обнаружено.

### 2.1. Существенные находки

**[🟠] Samovar.ino:1055 — Blynk-токен: валидный токен не сохраняется, а «валидируемый» переполняет буфер.** `if (strlen(custom_blynk_token.getValue()) == 33) { strcpy(SamSetup.blynkauth, ...); }` — реальный Blynk-токен 32 символа, условие ложно → токен из WiFi-портала **никогда не сохраняется**. А при вводе 33 символов `strcpy` запишет 34 байта в `char blynkauth[33]` (Samovar.h:420) — off-by-one, затирается `videourl[0]`. Фикс: `== 32` + `copyStringSafe` (уже есть в string_utils.h).

**[🟠] Samovar.ino:1778 — блокирующий I2C-опрос шаговика в async_tcp вопреки собственному кэшу [W-3].** При `USE_STEPPER_I2C` `get_stepper_speed()` → `i2c_stepper_refresh()` — ~30 I2C-транзакций под `xI2CSemaphore(1000мс)` из async_tcp на каждый `/ajax` (раз в 2–3 с); плюс запись общей структуры `i2cStepperPump` из третьего контекста. Кэш `i2c_stepper_cache` построен именно для этого и здесь не используется. Фикс: `i2c_stepper_cache.pump_current_speed` (обновляется в SysTicker, Samovar.ino:531–534).

**[🟠] Samovar.ino:1505–1517 — применение программы из loop без проверки активного отбора: гонка на `program[]` с core0.** Комментарий [C-3] обещает guard «когда withdrawal не активна», но проверки `startval == 0` **нет** — ни здесь, ни в `set_program()`. Сохранение программы во время отбора: `set_program` (core1) переписывает `program[]` и `ProgramLen`, пока SysTicker (core0) читает `program[ProgramNum].WType/.Speed/.Time` (Samovar.ino:610, 699, 704) и async читает WType. Отбор продолжится по смеси старой и новой программы, `ProgramNum >= ProgramLen` посреди строки. Фикс: `if (startval == 0 && SamovarStatusInt == 0) set_program(...); else SendMsg("Программа не изменена: идёт отбор", WARNING_MSG);`.

**[🟠] Samovar.ino:1520–1523 — `scan_ds_adress()` из loop конкурентно с опросом DS18B20 на core0.** [W-9] верно вынес OneWire из async в loop (core1), но SysTicker (core0) в это же время гоняет `DS_getvalue()` → `requestTemperatures()/getTempC()` по той же шине. OneWire/DallasTemperature не потокобезопасны: битые тайминги → мусорные адреса при сканировании и/или ложные -127 у рабочих датчиков. Фикс: выполнять скан только при `startval == 0` c гейтом `ds_scan_in_progress`, либо вызывать скан из SysTicker вместо очередного опроса.

**[🟠] crash_handler.ino:123–141 — shutdown_handler логически неверен: ложные crash-отчёты ротируют настоящие, реальные паники не ловятся.** (1) `esp_register_shutdown_handler` срабатывает только при штатном `esp_restart()` — при панике/WDT хендлеры не вызываются, «crash detected» в момент краха не запишется никогда. (2) `esp_reset_reason()` внутри хендлера возвращает причину **предыдущей** загрузки: если устройство когда-то упало, каждый штатный ребут пишет ложный «System crash detected» и ротирует настоящий crash.txt. Фикс: убрать shutdown_handler целиком; анализ уже корректно делается в `init_crash_handler()` при старте. Для реального стектрейса — core dump в flash.

**[🟠] Samovar.ino:531 vs 1554–1570 — SysTicker-refresh может перетереть staged-конфиг I2C-шаговика между копированием и отправкой.** loop (core1) копирует staged-поля в живую `i2cStepperPump` и шлёт конфиг; если между копированием и `i2c_stepper_apply` SysTicker (core0) выполнит `i2c_stepper_refresh` (чтение регистров в ту же структуру), свежие поля перезапишутся старыми с устройства — «Применить» молча не применится. Фикс: атомарный флаг `i2c_config_in_flight`: SysTicker пропускает refresh, пока loop не завершил apply/save.

### 2.2. Умеренные находки

**[🟡] logic.h:405 / Samovar.ino:1441 — общий `String program_Wait_Type` кросс-ядерно без лока.** Писатель на core1 — только `= ""` (не освобождает буфер, UAF сейчас нет), но torn read реален: core0 может собрать статус с мусорным хвостом, а сравнения `program_Wait_Type == "(царга)"` (logic.h:253, impurity_detector.h:343) на тик видят рассинхрон. Любой будущий непустой писатель превращает это в кросс-ядерный UAF. Фикс: `enum WaitType : uint8_t` + таблица строк; либо все обращения под лок.

**[🟡] WebServer.ino:1081/1393 + Samovar.ino:1508 — мейлбокс `pending_program_str` без проверки занятости: перезапись String во время копирования.** Барьеры правильные, но слот один: два быстрых POST подряд — пока loop копирует `pstr`, второй async-запрос делает `pending_program_str = ...` с реаллокацией → free буфера под ногами. Окно узкое, но это UAF. Фикс: в писателе `if (pending_program_mode != PPM_NONE) → 503`; либо пара буфер+флаг под runtime_state_lock.

**[🟡] Samovar.ino:645–650 — прогресс пива без клампа: отрицательное время и UB при float→uint8_t.** `WthdrwlProgress` — `volatile uint8_t` (Samovar.h:556). В пиве этап может идти дольше планового `Time` (ожидание подтверждения): при `wp > 2.55` конверсия float→uint8_t вне диапазона — UB, мусорный прогресс; `WthdrwTime` уходит в минус → «0-1:0-5» на экране. Фикс: `if (wp > 1) wp = 1;`.

**[🟡] logic.h:297 — калибровка помпы без клампа: тихий wrap uint16_t.** `SamSetup.StepperStepMl = round((float)stepper_safe_get_current() / 100);` — `StepperStepMl` uint16_t (Samovar.h:392). Счётчик шагов > 6 553 500 → результат по модулю 65536 → калибровка бессмысленна без признака ошибки. Фикс: кламп + `SendMsg("Ошибка калибровки")`.

**[🟡] logic.h:542 — `set_capacity()` без проверки границ: OOB-чтение `servoDelta[cap]`.** `servoDelta[11]` (Samovar_ini.h:46), CAPACITY_NUM=10; Lua-обёртка (lua.h:590) не валидирует: `set_capacity(200)` → OOB-чтение + `servo.write()` с мусорным углом. Фикс: `if (cap > CAPACITY_NUM) return;`.

**[🟡] Samovar.ino:487–507 — Lua-скрипт кнопки исполняется в SysTicker (core0), основной Lua — на core1.** Один `lua_State` из двух задач без синхронизации + произвольно долгий скрипт блокирует опрос датчиков на core0. Смягчение: USE_LUA по умолчанию выключен; чтение `btn_script` — корректно под локом [W-4]. Фикс: исполнение btn_script перенести в DoLuaScriptTask (мейлбокс).

**[🟡] logic.h:748–750 — `fileToAppend.close()` с core1 при активном гейте записи на core0.** `run_program(CAPACITY_NUM*2)` может выполняться из loop/menu (core1), при этом до `stop_process()` SysTicker (core0) может находиться внутри `append_data()` → `println`. File/FileImpl не рассчитан на close из другой задачи во время println — от потерянной строки до падения VFS. Фикс: закрывать файл в SysTicker по признаку `startval == 0` (следующим тиком core0).

**[🟡] Samovar.ino:466–469 — при удержании давления `set_alarm()` вызывается каждую секунду.** Guard'а «авария уже поднята» нет: пока давление выше порога, каждый тик шлёт ALARM_MSG (спам в web/Telegram/Blynk) и повторяет `set_alarm()` с vTaskDelay и I2C-остановками — SysTicker систематически пропускает тики опроса именно в аварии. Фикс: флаг `pressure_alarm_sent` с гистерезисом сброса.

**[🟡] Samovar.h:505 + logic.h:209/261/686/720 — три несогласованных предела массива программ.** `WProgram program[30]` vs рабочий предел `CAPACITY_NUM*2` (=20) vs хардкод `< 30`. Работает за счёт запаса, но изменение CAPACITY_NUM (>15) или уменьшение массива рассинхронизирует проверки → OOB. Фикс: `constexpr uint8_t PROGRAM_MAX = CAPACITY_NUM * 2; WProgram program[PROGRAM_MAX];` и все «30» → PROGRAM_MAX.

**[🟡] logic.h:1143 — автостарт после смачивания вызывает `menu_samovar_start()` из SysTicker.** «Толстая» операция уровня loop (создание файла на LittleFS, `create_data()`, меню) исполняется на core0 и конкурирует с menu-объектом из loop (core1). Смягчение: COLUMN_WETTING по умолчанию выключен. Фикс: `sam_command_sync = SAMOVAR_START` (механизм уже есть).

**[🟡] Samovar.ino:1961, 2020–2026 — `char == 255` всегда ложно на Xtensa: очистка NVS-мусора не работает.** char знаковый, максимум 127 — сравнение с 255 всегда false; санация «свежая NVS = 0xFF» не срабатывает → после стирания флеша в UI/Blynk уходит строка из 0xFF. Фикс: `(uint8_t)SamSetup.videourl[0] == 0xFF`.

**[🟡] Samovar.ino:2081–2109 — `verbose_print_reset_reason()`: мёртвый код с неверным маппингом причин.** Числовые case'ы из легаси `rtc_get_reset_reason()` применяются к `esp_reset_reason_t` — подписи не соответствуют причинам; единственный вызов закомментирован (:1304); роль выполняет корректный `get_reset_reason_string()` из crash_handler. Фикс: удалить.

**[🟡] crash_handler.ino:6 — статический буфер 2 КБ RAM не используется.** `stacktrace_buffer[2048]` только memset'ится. Фикс: удалить.

**[🟡] quality.h — модуль мёртв целиком, но резервирует RAM.** `float steamTempHistory[60]` (240 байт) + ~100 строк; единственная ссылка закомментирована (distiller.h:294). Фикс: удалить (или доделать осознанно).

### 2.3. Ниты

**[⚪] Samovar.ino:1319/1325 — `portENTER_CRITICAL_ISR` из task-контекста.** Работает, но семантическая ошибка; остальной код использует `portENTER_CRITICAL`. Фикс: заменить.

**[⚪] Samovar.h:137 и 143 — дублирующееся объявление `temprature_sens_read()`** — внутри `extern "C" {}` и после него с C++-linkage. Фикс: удалить внешний дубль.

**[⚪] `sam_command_sync` — одноместный слот с асимметричной очисткой.** Вторая команда за цикл затирает первую; SAMOVAR_RESET очищается не в диспетчере, а глубоко в `reset_sensor_counter()` (sensorinit.h:582) — инвариант «кто ставит, тот и снимает» нарушен. Фикс: очищать в диспетчере; при потребности — FreeRTOS-очередь.

**[⚪] Пиво: `WFpulseCount = 100;` мимо `pulseCountMux`.** Запись переменной, разделяемой с GPIO-ISR, без critical section — конкурирующий инкремент из ISR может исказить `WFflowRate` на один интервал; остальной код с ней работает под mux. Фикс: обернуть.

**[⚪] logic.h:1670, 1691, 1711, 1858, 1887, 1902 — кириллические «А» и «Т» в командах регулятора.** `Serial2.print("АТ+SS?\r")` — байты `D0 90 D0 A2 2B` вместо ASCII `41 54 2B` во всех шести командах SEM_AVR (подтверждено hexdump; докуменация в mod_rmvk.h набрана так же). Раз работает — контрагент матчит те же байты, но это мина: ASCII-«AT» по докам молча не заработает, в diff неразличимо. Фикс: привести к ASCII на обеих сторонах или оставить громкий комментарий.

### 2.4. Предложения по улучшению

1. **Telegram-прокси: токен уходит открытым HTTP на захардкоженный IP.** Samovar.ino:417/1108 — бот-токен и chat_id передаются на `212.237.16.93` без TLS: утечка секрета наблюдателю в сети + единая точка отказа/доверия. Минимум — сделать адрес настраиваемым и предупредить в UI; лучше — HTTPS напрямую к api.telegram.org.
2. **`get_speed_from_rate()` — геттер с побочным эффектом** (logic.h:94–98 пишет `ActualVolumePerHour`). Разнести на чистый расчёт и явное обновление состояния.
3. **Типы вместо строк для `WType` и `program_Wait_Type`.** Односимвольные String-теги «H/B/T/C/P» сравниваются десятки раз за тик; enum убирает и накладные расходы, и весь класс String-гонок.
4. **Двойной `set_power(false)`** в цепочке `stop_process() → reset_sensor_counter()` — второй холостой, но каждый тянет UART-обмен с регулятором; схлопнуть.
5. **Передача String по значению** (`writeString`, `WriteConsoleLog`) и `char input[1025]` на стеке `set_program` — на фоне 8К-стеков задач лучше `const String&` и статический буфер парсера.
6. **`triggerSysTicker` — монолит на сотни строк.** Разбиение на `poll_sensors() / update_progress() / check_alarms()` удешевит ревью и точечные правки.
7. **Ввести `PROGRAM_MAX` и включить `-Wall -Wextra` в CI:** «tautological compare» с 255 и off-by-one компилятор находит сам.

### 2.5. Что сделано хорошо

- **Дисциплина `runtime_state_lock`**: ни одного вложенного захвата; разумная асимметрия таймаутов (чтение 50 мс, запись 500 мс).
- **Идиома [C-13] `(int32_t)(millis() - t) >= 0`** применяется последовательно — переполнение millis отработано системно.
- **`format_float()`** (sensorinit.h) — NaN/Inf → «0», кламп диапазона, без sprintf-сюрпризов.
- **string_utils.h** — редкая аккуратность для Arduino-кода (errno, endptr).
- **Валидация `set_program()`**: strtok_r, whitelist типов «HBCTP», проверка границ, атомарная очистка при ошибке.
- **Обёртки `stepper_safe_*`** — весь доступ к GyverStepper2 корректно закрыт `portENTER_CRITICAL(&timerMux)`.
- **Pending-паттерн async→loop** с симметричными барьерами — правильная архитектура; найденные дыры — доводка, а не пересмотр подхода.
- **Комментарии-маркеры [C-x]/[W-x]/[L-x]** документируют инварианты конкурентности прямо в коде — благодаря им видно, где инвариант заявлен, но не реализован.

## 3. Код прошивки: I/O и веб-слой

Зона: WebServer.ino, NVS_Manager.ino, lua.h, Menu.ino, I2CStepper.h, SPIFFSEditor.h, Blynk.ino, FS.ino, SamovarMqtt.h, wifi_htm_gz.h, user_config_override.h; перекрёстно проверены Samovar.ino, logic.h, beer.h, sensorinit.h, runtime_helpers.h, string_utils.h.

### 3.1. Находки

**[🔴] WebServer.ino:1310 → Menu.ino:432–437 — `menu_reset_wifi()` прямо в async-хендлере: стирание NVS + ESP.restart() до отправки ответа.** Тройное нарушение правил async_tcp: (1) конструирование AsyncWiFiManager и `resetSettings()` — запись в NVS из задачи async_tcp; (2) `ESP.restart()` ДО `request->send(...)` — клиент получает обрыв вместо ответа; (3) рестарт изнутри колбэка, пока lwIP держит соединение. Соседняя ветка `reboot` (:1304–1308) сделана правильно — через `is_reboot`. Фикс: `request->send(200); pending_reset_wifi_flag = true;` — выполнение в loop().

**[🔴] WebServer.ino:1318–1323 — `set_mixer()` в хендлере: блокирующая I2C-цепочка на секунды.** `set_mixer` → `set_mixer_state` (beer.h:639) вызывает `i2c_stepper_mixer_present()` (полный refresh — десятки I2C-транзакций, каждая с ожиданием `xI2CSemaphore` до 1000 мс), затем `set_stepper_by_time`/`set_mixer_pump_target` — `i2c_stepper_send_command` опрашивает ack до 20×10 мс. При занятой шине async_tcp блокируется на секунды → отвал всех веб-клиентов, риск WDT. Фикс: `pending_mixer_*` по образцу `pending_i2cpump_*`.

**[🔴] WebServer.ino:1367–1368 — `set_current_power()` в хендлере: vTaskDelay(100) + UART-семафор в async_tcp.** `set_current_power` (logic.h:1820) содержит безусловный `vTaskDelay(100)` (logic.h:1845), в конфигурации SEM_AVR — ещё и `xSemaphoreTake(xSemaphoreAVR, ≈3.3 с)` с обменом по Serial2. Усыпляет задачу, обслуживающую ВСЕ TCP-соединения. Фикс: `pending_voltage_*` + применение в loop().

**[🔴] Samovar.ino:504, Samovar.ino:1540–1546, Blynk.ino:25, lua.h — один `lua_State` из трёх задач на двух ядрах без взаимного исключения.** btn_script исполняется в SysTicker (core 0, Samovar.ino:504, без проверки `lua_finished`), pending_lua — в loop (core 1), Blynk V22 — в loopTask, do_lua_script — задача на core 1 (lua.h:1011). lua_State не потокобезопасен (общий стек VM, GC): при наложении — порча кучи Lua, крэш. Флаг `lua_finished` не мьютекс (check-then-act без атомарности) и в двух ветках вообще не проверяется. Фикс: минимально — общий `xLuaSemaphore` вокруг каждого `lua.Lua_dostring(...)` во всех четырёх точках; правильнее — весь Lua в одной задаче do_lua_script (очередь строк/скриптов).

**[🟠] WebServer.ino:1372–1373 — `run_lua_script()` в хендлере: SPIFFS-чтение + lock 500 мс в async.** `run_lua_script` (lua.h:1061) читает файл из SPIFFS и берёт `runtime_state_lock(500 мс)`. Соседняя ветка `luastr` (:1375–1381) сделана правильно. Фикс: `pending_lua_file_*` — чтение файла в loop().

**[🟠] SPIFFSEditor.h:346 — `load_lua_script()` из upload-колбэка async_tcp.** После загрузки .lua через /edit в async-контексте — два чтения SPIFFS + `runtime_state_lock(500 мс)` (lua.h:1096–1106). Фикс: `pending_reload_lua_flag`.

**[🟠] NVS_Manager.ino:630–637 — `saveStringIfChanged` считает успешную запись пустой строки ошибкой → ложная полная перестройка NVS.** `Preferences::putString` возвращает `strlen(value)` — для пустой строки это 0 при успехе. Пользователь очищает поле (videourl, blynkauth, tg_token) → помечается сбой → `save_profile` запускает `compact_samovar_nvs_namespaces()` — стирание и перезапись ВСЕХ Samovar-неймспейсов: износ флеша и окно потери настроек на ровном месте. Фикс: `if (prefs.putString(key, String(value)) == 0 && value[0] != '\0') markNvsProfileWriteFailed(key);`.

**[🟠] NVS_Manager.ino:510–561 — компактизация NVS неатомарна: erase всех неймспейсов до restore.** Бэкап живёт только в RAM (`calloc`). Обрыв питания между «стёрли всё» и «восстановили» = потеря всех профилей и настроек всех режимов. В сочетании с предыдущей находкой окно открывается при обычной очистке текстового поля. Фикс: бэкап во временный неймспейс/файл SPIFFS до erase, либо компактизация по одному неймспейсу.

**[🟠] WebServer.ino:332–334, 1476–1477 — `fileToAppend.flush()` из async-хендлеров на общем File.** `fileToAppend` — глобальный File, в который SysTicker пишет `append_data`. `flush()` из async_tcp — блокирующая запись во флеш в запрещённом контексте + гонка на внутреннее состояние File с параллельным `print` из другой задачи → порча лога или крэш VFS. Фикс: `pending_flush_log_flag` либо семафор на все операции с fileToAppend.

**[🟠] WebServer.ino:1316–1317 — `stop_self_test()` в хендлере: SendMsg под 500-мс лок + сброс `sam_command_sync` из async.** `stop_self_test` (logic.h:1560) → `open_valve` → `SendMsg` → `append_web_message` (лок 500 мс) + MQTT; далее `reset_sensor_counter()` (sensorinit.h:500) делает `sam_command_sync = SAMOVAR_NONE;` — из async молча затирается команда, поставленная loop'у другим источником. Запуск self-test (`startst`) корректно отложен — остановка должна идти тем же путём. Фикс: команда `SAMOVAR_SELF_TEST_STOP` через `sam_command_sync`.

**[🟠] WebServer.ino:478–495 — catch-all onFileUpload/onRequestBody льют всё тело запроса в Serial.** Отладочный код без `#ifdef`: `Serial.write(data, len)`. Serial 115200 ≈ 11.5 КБ/с; POST со 100 КБ тела на URL без выделенного body-хендлера заблокирует async_tcp на ~9 секунд → отвал клиентов, риск WDT. Фикс: `#ifdef __SAMOVAR_DEBUG` или `min(len, 64)`.

**[🟡] WebServer.ino:304 — /pong.htm отдаёт mp3.** `serveStatic("/pong.htm", SPIFFS, "/alarm.mp3")` — copy-paste; страница недоступна, браузер рисует мусор. Фикс: `"/pong.htm"`.

**[🟡] SPIFFSEditor.h:198 — `arg("edit")` вместо `arg("download")` в ветке download.** Слэш добавляется по содержимому чужого параметра; работает случайно. Фикс: проверять собственное значение, как в соседней ветке edit.

**[🟡] lua.h:587–592 → logic.h:542 — `set_capacity()` из Lua без валидации: чтение за границей `servoDelta[11]`.** `servoDelta` — `int8_t[11]` (Samovar_ini.h:46), CAPACITY_NUM=10. Lua-скрипт `set_capacity(255)` → OOB-чтение `servoDelta[255]` и бессмысленный угол в сервопривод; скрипты редактируются через веб (/edit) — путь от HTTP до OOB существует. Фикс: `if (a > CAPACITY_NUM) return luaL_error(...)` и/или клэмп в `set_capacity`.

**[🟡] WebServer.ino:399–416 — /i2cpump: непроверенный float из HTTP → UB при касте в целые.** (1) `volume=nan/inf` проходит проверку `volumeMl <= 0` → `(uint32_t)NaN` — UB; (2) `volume=1e9` → out-of-range конверсия float→uint — UB; (3) `(uint16_t)volumeMl` молча переполняется при volume > 65535. Фикс: `if (!(volumeMl > 0.0f && volumeMl < 65000.0f) || !(speedRate > 0.0f && speedRate < 10000.0f)) { request->send(400); return; }`.

**[🟡] I2CStepper.h:148–173 — read_u16/u32 собираются из отдельных транзакций: рваные значения.** Семафор берётся/отпускается на каждый байт; между чтением hi и lo устройство обновляет регистр: 0x0100→0x00FF читается как 0x01FF или 0x0000. `remaining`/`currentSpeed` используются в логике отбора — ложные «долив завершён»/скачки скорости. Фикс: держать `xI2CSemaphore` на всю групповую операцию, а лучше — блок регистров одной транзакцией `requestFrom(addr, n)`.

**[🟡] WebServer.ino:1611–1613 — `get_web_file`: запись в SPIFFS без единой проверки.** При заполненной FS `open` вернёт невалидный File, `print` вернёт 0 — всё игнорируется, печатается «Done». Обновление веб-интерфейса молча оставляет усечённые/пустые .htm. Фикс: `if (!wf || wf.print(s) != s.length()) { SPIFFS.remove("/" + fn); return "<ERR>"; }`.

**[🟡] SamovarMqtt.h:64–76 — `MqttSendMsg`: общие буферы без синхронизации.** `SendMsg` → `MqttSendMsg` вызывается из SysTicker (core 0), loop (core 1) и async-путей. Параллельные вызовы перемешивают `mqttstr1`/`payload`: сообщение уходит в чужой топик или с обрезанным телом. Фикс: мьютекс вокруг тела либо локальные буферы на стеке (static убрать).

**[🟡] WebServer.ino:1003–1243 — `handleSave` мутирует SamSetup по частям прямо в async; нет барьера перед `pending_save_profile_flag`.** (1) Поля (включая char-массивы) переписываются из async, пока SysTicker/loop считают по ним регулирование — чтение полуобновлённых Kp/Ki/Kd; (2) в отличие от соседнего `pending_switch_mode_flag` (:1238, с барьером), перед `pending_save_profile_flag = true` (:1243) барьера нет; (3) `toInt()/toFloat()` без валидации: `HeaterR=abc` → 0 → `current_power_volt²/SamSetup.HeaterResistant` = inf. Фикс: staging-копия `pending_samsetup_buf` + барьер + флаг; числовые поля — через существующие parseLongSafe/parseFloatSafe с диапазонами.

**[🟡] WebServer.ino:1255–1259 — троттлинг web_command молча съедает разные команды.** Защита от дублей не различает команды: «выключить нагрев» через секунду после «пауза» отбрасывается с ответом "OK". Для аварийных команд — 1.5 с глухоты с ложным подтверждением. Фикс: троттлить по совпадению команды; `reset`/`reboot` пропускать всегда; при отбросе — `429`.

**[🟡] Samovar.ino:1817 — чтение `program[ProgramNum].WType` (String) в /ajax без лока.** WType переприсваивается в loop() при применении pending_program. Копирование String в async параллельно с реассайном — гонка кучи → редкий крэш при сохранении программы под открытым веб-интерфейсом. Остальные строки в send_ajax_json читаются под локом — это место выбивается. Фикс: копировать под `runtime_state_lock(50)` либо хранить WType как char[4].

**[🟡] WebServer.ino:578–581 → lua.h:1021–1046 — обход SPIFFS с открытием файлов в template-процессоре.** `%btn_list%` → полный листинг SPIFFS + открытие/чтение каждого btn_*-файла при каждой отдаче index/mode-страниц в async_tcp. Фикс: кэшировать список в глобальной String, инвалидировать по флагу из load_lua_script/upload.

**[⚪] FS.ino:7–8 — мёртвые креды + SPIFFSEditor без авторизации.** `http_username/http_password = "admin"` не используются; /edit даёт любому в LAN полный RW к FS, включая загрузку .lua — т.е. исполнение произвольной логики управления нагревом. Для DIY допустимо, но написанные креды создают ложное ощущение защиты. Фикс: удалить переменные либо передать в конструктор SPIFFSEditor.

**[⚪] lua.h:1179–1180 — `get_global_variables`: мёртвый код после return.** `return ""; String Variables; ...` — ~30 строк мертвы. Фикс: удалить или вернуть осознанно.

**[⚪] NVS_Manager.ino:207 — `set_current_profile_mode()` не вызывается ниоткуда.** Мёртвая функция; актуальная запись меты идёт напрямую (:623); прототип в WebServer.ino:35 вводит в заблуждение. Фикс: удалить.

**[⚪] FS.ino:122–139 — дублирующиеся onFileUpload/onRequestBody перекрываются WebServer.ino:478–495.** Вторая регистрация перезаписывает первую; мёртвый код. Фикс: оставить одну.

**[⚪] Одиночные pending_*-буферы: вторая команда до цикла loop затирает первую.** Все pending-каналы — один слот без очереди. Для DIY приемлемо (loop крутится в мс), но стоит знать. Фикс (по желанию): `if (pending_X_flag) → 429` в хендлере.

### 3.2. Предложения по улучшению

1. **Единая точка диспетчеризации команд.** В web_command сосуществуют три механизма: `sam_command_sync`, `pending_*`-флаги и прямые вызовы. Все прямые вызовы (resetwifi, mixer, voltage, lua, stopst) — регрессии относительно собственной идиомы проекта. Таблица «аргумент → enum команды + payload» и один обработчик очереди в loop() — новые команды перестанут появляться в опасном варианте.
2. **Обёртка для Lua.** Все четыре точки входа в `lua.Lua_dostring` свести к одной `lua_exec(const String&)` с мьютексом (или очередью в do_lua_script) — закрывает 🔴-гонку и даёт единое место логирования ошибок скриптов.
3. **Блочное чтение I2CStepper.** Чтение статуса одним `requestFrom` на 8–12 байт: меньше времени на шине, меньше точек отказа, снимает рваные значения.
4. **Компактизация NVS с бэкапом на флеш.** RAM-бэкап писать во временный файл SPIFFS перед erase — восстановление при старте по наличию файла.
5. **Централизованная валидация HTTP-входа.** parseFloatSafe/parseLongSafe из string_utils.h уже есть — прогнать через них все `toInt()/toFloat()` в web_command/handleSave с явными диапазонами.

### 3.3. Что сделано хорошо

- Идиома отложенных команд образцова там, где применена: `pending_i2cpump_*`/`pending_i2cstepper_*`/`pending_lua_str`/`pending_program_str` — симметричные барьеры, сброс флага до чтения буфера, комментарии с номерами issue.
- Хендлер /i2cpump — пример правильного мышления: `present` из глобала вместо I2C, скорость по SamSetup без шины, работа с железом в loop().
- string_utils.h (copyStringSafe/parseLongSafe/parseFloatSafe/toJsonString) — аккуратные утилиты с проверкой границ и errno.
- Ретрай сохранения профиля NVS (retryingProfileSave, компактизация по факту сбоя) — продуманный, с защитой от рекурсии; подводит только детектор сбоя (putString==0).
- Чтения разделяемого состояния в Blynk.ino и send_ajax_json почти везде через копии под `runtime_state_lock(50)` с защитой от рекурсии (static inReadHandler).
- Валидация set_program (коммит d231d45f) — разбор с проверкой типов и границ; подозрения на OOB по program[] не подтвердились.

## 4. Код прошивки: режимы

Зона: beer.h, nbk.h, distiller.h, impurity_detector.h, BK.h, mod_rmv.ino, mod_rmvk.h, pumppwm.h; call-sites проверены в logic.h / Samovar.ino / WebServer.ino / sensorinit.h.

### 4.1. Критические находки

**[🔴] distiller.h:221–244, BK.h:109–125 — кросс-ядерная гонка: авто-рестарт нагрева сразу после аварийного отключения.** `check_alarm_distiller`/`check_alarm_bk` выполняются в SysTicker на core 0 (Samovar.ino:626–637): при перегреве воды/ТСА `set_power(false)` сбрасывает `PowerOn` немедленно (distiller.h:364–367), но `sam_command_sync = SAMOVAR_RESET` выставляется только в конце после ~900 мс vTaskDelay и обрабатывается loop'ом на следующей итерации. Всё это время loop на core 1 видит `SamovarStatusInt == 1000 && !PowerOn` — ровно условие штатной инициализации старта в `distiller_proc`/`bk_proc` (distiller.h:219–237): `set_power(true)`, `create_data()`, `run_dist_program(0)`. **Аварийное отключение по перегреву превращается в перезапуск сессии с включённым нагревом**; при пограничном условии (датчик колеблется у 75.0°C) нагрев останется включённым. Плюс два ядра одновременно выполняют `set_power(false)`/`set_power(true)` — функция не реентерабельна. Фикс: в аварийных ветках вместо прямого `set_power(false)` ставить `sam_command_sync = SAMOVAR_POWER` — так уже сделано в соседней ветке отказа подачи воды (distiller.h:381, BK.h:185); либо гейтить ре-инициализацию по `startval`, как в `beer_proc` (beer.h:275).

**[🔴] beer.h:687–712, nbk.h:358–369, distiller.h:249, BK.h:127 — отказ/отсутствие датчика температуры не останавливает нагрев.** `DS_getvalue` (sensorinit.h:228–262) отбрасывает ошибочные чтения: при умершем датчике `avgTemp` «замерзает», при отсутствующем — 0. `ErrCount > 10` даёт только SendMsg (Samovar.ino:799–817). Следствия:
- **Пиво**: `setpoint - 0 > HEAT_DELTA` → ТЭН (включая разгонный, beer.h:690) включён непрерывно; переход «достигнута температура» и таймер паузы (beer.h:584) не сработают — затор выкипает без единой аварии.
- **НБК**: разгон ждёт `nbk_Tp >= 75` (nbk.h:366) на полной мощности бессрочно; защита «Кончилась брага» (`> 98.0`, nbk.h:751) мертва по той же причине.
- **Дистиллятор/БК**: финиш по `TankSensor.avgTemp >= SamSetup.DistTemp` не сработает; куб выкипает досуха, единственная страховка — перегрев воды охлаждения (которая при выкипании куба может и не перегреться).
Идиома «датчик есть = avgTemp >= 2» в проекте существует (logic.h, check_boiling), но в контурах управления нагревом не применяется. Фикс: перед решением о нагреве проверять валидность ключевого датчика (`avgTemp >= 2` + ErrCount); при отказе управляющего датчика — стоп процесса через `sam_command_sync = SAMOVAR_POWER`, а не только сообщение.

### 4.2. Серьёзные находки

**[🟠] nbk.h:738–782 — критические аварии НБК исполняются внутри SysTicker (core 0) с delay'ями и кросс-ядерными вызовами.** Ветка «Кончилась брага» (nbk.h:751–758, вызов Samovar.ino:633): `SetSpeed(0)` (I2C, конкурентно с SetSpeed из nbk-этапов на core 1), `delay(1000)`, затем `run_nbk_program(20)` → `nbk_finish()` → ещё `SetSpeed(0)` + `delay(1000)` + `set_power(false)` (~900 мс). Итого SysTicker заморожен ~3 секунды: не опрашиваются датчики и аварийные проверки — в момент аварии. «Недостаточное охлаждение» (nbk.h:767–775) — то же + прямой `set_power(false)`. Фикс: из `check_nbk_critical_alarms` только диагностировать и выставлять команду; фактическую остановку выполнять в loop.

**[🟠] nbk.h:383–391 — при захлёбе в «Ручной настройке» подача пересчитывается от устаревшего nbk_P и может УВЕЛИЧИТЬСЯ.** Мощность актуализируется из реального состояния (`target_power_volt`), подача — нет: `nbk_P` хранит значение при входе в этап, а пользователь в этом этапе крутит подачу через веб мимо `nbk_P`. Сценарий: П=10 в программе, пользователь снизил до 3 л/ч, захлёб → `SetSpeed(10/3 ≈ 3.3)` — подача повышается в момент захлёба. Эталон — этап «Работа», где обе величины актуализируются (nbk.h:562–563). То же в `handle_overflow` (nbk.h:864). Фикс: перед делением `nbk_P = i2c_get_liquid_rate_by_step(get_stepper_speed())`.

**[🟠] beer.h:584, nbk.h:750 — чтение Arduino String из program[] на core 0 гоняется с перезаписью программы из loop.** Применение программы вынесено в loop (Samovar.ino:1505–1514) БЕЗ проверки активности сессии: `set_beer_program` чистит все 20 строк (`program[j].WType = ""`, beer.h:906/926) и заполняет заново, пока `check_alarm_beer` и `check_nbk_critical_alarms` (core 0) читают те же String без лока. UB (torn read); смягчает SSO, но в худшем случае «P» распознаётся как не-«P» → таймер паузы затирания сбрасывается/не срабатывает. Фикс: отклонять загрузку программы при активной сессии режима, либо сравнение WType под `runtime_state_lock`.

### 4.3. Средние находки

**[🟡] distiller.h:249–251 — нет return после `distiller_finish()`.** После финиша (сброс `ProgramNum=0`) исполнение продолжается: код ниже читает `program[0]`, условие «T»/«A» на горячем кубе почти наверняка истинно → `run_dist_program(1)` уже после завершения: движение сервопривода, применение мощности, «переход к строке» после «Дистилляция завершена». Фикс: `{ distiller_finish(); return; }`; в BK.h:127–129 return добавить для симметрии.

**[🟡] distiller.h:326, BK.h:138 — сброс alarm_t_min не overflow-safe.** `if (alarm_t_min > 0 && alarm_t_min <= millis())` — наивное сравнение; в nbk.h:800 та же строка написана правильно по идиоме [C-13]. Возле переполнения millis() (аптайм 49.7 суток) пауза сигнализации о критической температуре воды либо не сбрасывается ~49 суток (предупреждения и снижение мощности заглушены), либо спамится. Фикс: форма вычитания, как в nbk.h:800.

**[🟡] impurity_detector.h:349, 409–410, 424 — наивные сравнения дедлайнов millis().** `detector_manual_override_until > now`, `detector_grace_until < now + 30000UL` — при переполнении millis() грейс-период/override детектора «залипают» активными или мгновенно истекают. Соседние проверки в том же файле написаны через вычитание — непоследовательно. Фикс: перевести все три места.

**[🟡] nbk.h:453–454 — целочисленное деление `NBK_OPERATING_RANGE / 100`.** Сейчас = 1 (no-op), но любое значение 1–99 (для чего константа и заведена) даст множитель 0: `nbk_Mo`/`nbk_Po` обнулятся, «Работа» молча стартует с дефолтов 500 Вт / 1 л/ч (nbk.h:725–726). Фикс: `/ 100.0f`.

**[🟡] nbk.h:316–364 — пустая/невалидная программа НБК: беззвучное зависание в статусе 4000.** Инициализация запуска — внутри `handle_nbk_stage_heatup`, вызываемого только при `wtype == "H"`. Если программа пуста (set_nbk_program отверг ввод), после старта `nbk_proc` вечно проваливается мимо всех веток: нагрев не включён, сообщений нет. Фикс: при `startval == 4000 && wtype.length() == 0` — ALARM «Программа НБК не задана» + `SAMOVAR_RESET`.

**[🟡] distiller.h:396, BK.h:199 — снижение мощности «-5» без PWR_FACTOR: на SEM_AVR не работает.** Эталон в logic.h: `- 5 * PWR_FACTOR` с обработкой SEM_AVR. Здесь копипаста без масштабирования: на SEM_AVR (`target_power_volt` в ваттах, ~2000–3000) снижение на 5 Вт ничего не меняет → колонна перегревается, система каждые 30 с рапортует «Понижаем мощность», ничего не понижая. Фикс: унифицировать с logic.h (общая функция).

**[🟡] pumppwm.h:22 — setpoint ПИД-регулятора насоса задаётся один раз при загрузке.** `init_pump_pwm` вызывается только из sensorinit.h:460 при старте. Изменение «Т воды» в веб-настройках до перезагрузки не влияет на ПИД. Фикс: обновлять setpoint при сохранении настроек либо в начале `set_pump_speed_pid`.

**[🟡] impurity_detector.h:590–616 — расчёт теплопотерь даёт мусор при рестарте ESP посреди нагрева.** Guard только на длительность (60 с), не на deltaT: рестарт при кубе 69°C → `heatStartTemp = 69`, deltaT ≈ 1 → `CurrentHeatLoss` клампится в 1500 Вт и используется весь остаток сессии (`heatLossCalculated` сбрасывается только ребутом — в `reset_sensor_counter` его нет, вторая сессия наследует значение первой). Фикс: требовать deltaT ≥ 15°C; сбрасывать `heatLossCalculated`/`heatStartMillis` при старте новой сессии.

**[🟡] BK.h:173 — у бражной колонны нет защиты по температуре ТСА.** Дистиллятор при `ACPSensor.avgTemp >= MAX_ACP_TEMP` отключает нагрев (distiller.h:364) и заранее открывает клапан (distiller.h:333). В BK.h ACPSensor не упоминается вообще: перегрев ТСА (пар в атмосферу) не контролируется. Фикс: добавить ветки по образцу distiller.h:332–341, 364–374.

### 4.4. Мелкие находки

**[⚪] nbk.h:749, 778 — static `overheat_start_time` переживает сессию.** Если сессия завершилась в момент перегрева, при следующем запуске первое превышение 60°C ТСА сработает мгновенно без 60-секундной выдержки. Фикс: обнулять в `run_nbk_program(0)`/`nbk_finish()`.

**[⚪] mod_rmv.ino:20–60 — RMVK_cmd при таймауте возвращает `rmvk.conn` (0/1) как «показание».** На веб-морде «1 В» вместо признака ошибки; «связь упала» неотличимо от «регулятор выдал 0–1 В». Фикс: предыдущее валидное значение или код ошибки (255).

**[⚪] mod_rmv.ino:165 — `rmvkFn`: мёртвый код.** Только определение и прототип (mod_rmvk.h:45), вызовов нет. Фикс: удалить.

**[⚪] nbk.h:335 — String-копия на каждый проход loop.** Heap alloc/free тысячи раз в секунду многочасовой сессии — фрагментация кучи (сам снапшот — правильная защита, но дорогая). Фикс: сравнивать первый символ.

**[⚪] nbk.h:266, beer.h:299–308 — сентинель `ProgramNum = CAPACITY_NUM*2` читает «слот-пустышку» program[20].** Работает, пока `program[30]` и CAPACITY_NUM=10, но связь нигде не зафиксирована: CAPACITY_NUM=15 → индекс 30 — OOB. Фикс: `static_assert(CAPACITY_NUM * 2 < размер program[])`.

**[⚪] nbk.h:655–659 — финиш по ошибке программы печатает статистику от startTime = 0.** `totalTime = millis()/1000` — «работали 133 часа» при аптайме 5.5 суток. Фикс: печатать только при `stats.startTime > 0`.

**[⚪] pumppwm.h:41–47 — delay(1000) при старте насоса в контексте SysTicker.** Вызов из `check_alarm_*` → `set_pump_speed_pid` (core 0) — секундная заморозка опроса датчиков при каждом старте насоса. Фикс: неблокирующий прогрев по метке времени.

**[⚪] beer.h:584 — гранулярность паузы затирания: целые минуты против float Time.** Пауза 1.5 мин фактически длится 2 мин. Фикс: `/ 60000.0f`.

**[⚪] nbk.h:718–733 — `nbk_work_next_time` не инициализируется при входе в «Работу».** При повторном запуске наследует дедлайн прошлой сессии — первая регулировка откладывается на чужую паузу. Фикс: `nbk_work_next_time = millis();` при входе в "W".

**[⚪] distiller.h:369–372 — при одновременном перегреве воды и ТСА сообщение назовёт только «Воды».** Фикс: убрать `else`.

### 4.5. Дублирование логики (конкретные блоки)

1. **Ре-инициализация старта нагрева**: distiller.h:221–244 ↔ BK.h:109–125 — дословная копия; именно она растиражировала гонку 🔴№1 на два режима.
2. **Аварийный блок «вода»**: distiller.h:363–400 ↔ BK.h:172–205 ↔ nbk.h:799–831 ↔ logic.h (check_alarm) — четыре копии каскада; уже разъехались: PWR_FACTOR только у ректификации, ACP только у дистиллятора, overflow-safe alarm_t_min только у НБК.
3. **Закрытие клапана при остывании**: distiller.h:343–348 ↔ BK.h:165–170 ↔ nbk.h:788–793 — одинаковый блок с разными порогами (SetWaterTemp − DELTA_T_CLOSE_VALVE против TARGET_WATER_TEMP − 20 — вероятно, непреднамеренно).
4. **Парсеры программ**: set_beer_program ↔ set_dist_program ↔ set_nbk_program — общий каркас, валидация разной строгости.
5. **Генераторы get_\*_program** — три копии однотипной сборки строки.

Предложение: единый `mode_common.h` с `start_heating_session(...)`, `check_water_alarms(...)`, `parse_program_lines(...)`.

### 4.6. Предложения по улучшению

1. **Единый безопасный путь аварийного останова.** Все аварийные ветки сходятся в `sam_command_sync = SAMOVAR_POWER`, исполняемый в loop. Прямые `set_power(false)` из core 0 — источник обеих 🔴/🟠 гонок этого ревью.
2. **Хелпер `sensor_valid(DSSensor&)`** (`avgTemp >= 2 && ErrCount < N`) обязателен в контурах управления нагревом; при невалидном управляющем датчике — стоп процесса.
3. **Зафиксировать идиому [C-13] греп-линтом**: `<= millis()`, `> now`, `< now +` находятся паттерном; три файла зоны всё ещё содержат наивные формы.
4. **Гейтить применение PPM_\*-программ при активной сессии** режима.
5. **static_assert на инварианты**: `CAPACITY_NUM*2 < размер program[]`, `MAX_WATER_TEMP > ALARM_WATER_TEMP`.
6. **Убрать блокирующие delay из горячих контекстов**: delay(2500) при старте НБК (nbk.h:682), delay(1000)×2 в аварийном пути НБК, delay(1000) в pumppwm.

### 4.7. Что сделано хорошо

- **beer.h**: валидация границ программы с корректным сентинелем (beer.h:299–308); `default:` в switch по TempSensor с аварийным финишем (beer.h:404–406); гейт `if (startval <= 2000) return;` (:379); парсер с проверкой диапазонов и откатом.
- **nbk.h**: этап «Работа» актуализирует М и П из реального состояния железа перед каждым решением (:562–563); overflow-safe [C-13] в work-цикле и check_alarm_nbk; кэш SQRT в `fromPower` (:306–312); корректная интегральная статистика объёма.
- **distiller.h**: TimePredictor защищён от деления на ноль (MIN_TEMP_RATE/MIN_ALC_RATE, :205–206); `startAlcohol > 0` перед делением (:263); ветка отказа подачи воды использует безопасный путь `sam_command_sync = SAMOVAR_POWER` (:381) — образец для остальных аварий.
- **impurity_detector.h**: гистерезис выбора датчика [M-29] с защитой от невалидной температуры; guard'ы `ProgramNum < 30`; регрессия тренда с проверкой знаменателя.
- **Общее**: комментарии-маркеры прошлых фиксов ([C-13], [M-10], [L-1/M-31]) упрощают ревью; вынос записи program[] в loop через PPM — правильное решение, осталось довести до конца.

## 5. UI: основные страницы

Зона: `data/index.htm`, `data/setup.htm`, `data/program.htm`, `data/chart.htm`, `data/style.css`, `data/wifi.htm`, `data/edit.htm`, `data/calibrate.htm`, `data/brewxml.htm`.

**Модель обмена (контекст):** WebSocket/SSE нет — чистый поллинг. index.htm и chart.htm дёргают `GET /ajax` каждые 2 с (JSON ~1–1.5 КБ, WebServer.ino:345, Samovar.ino:1698), chart.htm дополнительно перезагружает **весь** `data.csv` каждые 15 с. Команды — `GET /command?...`, программа — `POST /program`, настройки — POST `/save` с 301-редиректом. index.htm (51 КБ) отдаётся через шаблонизатор с `no-store` — без gzip и кэша на каждый вход. gzip есть только у style.css и edit.htm.

### 5.1. Находки

**[🔴] index.htm:1032,1037; setup.htm:499,510 — опасные действия в один клик, без подтверждения.** «Выключить/Включить нагрев» (`sendbutton("power=1")`), «Сбросить процесс» (`reset=1`), «Перезагрузить Самовар» (`reboot`), «Сбросить настройки WiFI» (`resetwifi=1`) выполняются мгновенно; `resetwifi` выкидывает устройство из сети (WebServer.ino:1309–1310). wifi.htm:49–53 показывает, что авторы умеют в `confirm()` — просто не донесли до главной. Фикс: confirm для power/reset/reboot/resetwifi (для pause/start не надо).

**[🔴] WebServer.ino:1254–1260 — команды молча выбрасываются, UI рапортует успех.** Глобальный дебаунс: любая команда в течение 1500 мс после предыдущей возвращает `200 OK`, **не выполнившись**. Пользователь нажал «Пауза», через секунду «Выключить нагрев» — вторая команда проглочена, фронт получил OK, нагрев работает. Фикс: возвращать `429`/`"BUSY"` и обрабатывать на фронте, либо дебаунсить по имени команды.

**[🔴] chart.htm:11–13,297,455–458 — график полностью мёртв без интернета.** amCharts v4 (~1 МБ+) грузится с CDN без локального fallback. В AP-режиме `am4core` не определён → top-level `am4core.ready(...)` кидает ReferenceError → initTheme и `DOMContentLoaded` со `startPolling()` **не регистрируются**: вся страница мертва, даже температуры не обновляются, после десятков секунд висения на таймауте CDN. У edit.htm:647–654 fallback на локальный `/ace.js` есть — chart.htm обделили. Фикс минимум: `if (typeof am4core !== 'undefined')` + вызвать `startPolling()` независимо от графика. Правильно: локальная лёгкая библиотека (см. предложения).

**[🟠] index.htm:3–8 (и setup/program/chart/calibrate/brewxml) — нет `<meta name="viewport">`: весь мобильный CSS — мёртвый груз.** Медиа-запросы `@media (max-width: 900px/600px)` (style.css:802–882) никогда не срабатывают на телефоне. Фикс: одна строка в каждый head.

**[🟠] index.htm:1 (и setup/program/chart/calibrate/brewxml) — нет `<!DOCTYPE html>`: quirks mode.** Другой box-model, наследование шрифтов, непредсказуемые расхождения с media queries. wifi.htm и edit.htm doctype имеют. Фикс: добавить (и прогнать глазами вёрстку — standards mode может сдвинуть отступы).

**[🟠] index.htm:115–128 — тревожная сирена молча не играет.** `sound.play()` без `.catch()`: автоплей блокируется до первого жеста → NotAllowedError, а `sound_is_playing = true` уже выставлен — повторной попытки не будет никогда. Фикс: `.catch(() => { sound_is_playing = false; })` + разлочить аудио на первом клике (`{once:true}`) + визуальный fallback (мигание title).

**[🟠] index.htm:418–427,429–437 — «Установлено.» при провалившемся запросе.** `sendvoltage`/`sendpumpspeed` делают `await sendbutton(...)`, который глотает ошибки, после чего безусловно `alert("Установлено.")`. Фикс: `sendbutton` возвращает `resp.ok`, вызывающие проверяют.

**[🟠] calibrate.htm:28–35 — состояние кнопки меняется до ответа сервера.** Надпись переключается на «Зафиксировать 100 мл» **до** `fetch('/calibrate?...')`; если запрос упал, UI считает, что калибровка идёт, следующий клик отправит `finish` незапущенному насосу. Состояние машины хранится в тексте кнопки. Фикс: переключать value после `resp.ok`; состояние — в переменной.

**[🟠] index.htm:596–606 — белый текст на lightgreen: главная кнопка нечитаема.** При выключенном нагреве `backgroundColor = 'lightgreen'`, а `.button` (style.css:358) даёт `color: #fff` — контраст ~1.5:1. У pause `#3498db` + белый — ~3.1:1. Фикс: тёмный текст на светлых фонах или классы `.btn-on/.btn-off` вместо инлайновых цветов.

**[🟠] chart.htm:314–321 — полный лог каждые 15 секунд.** `reloadFrequency = 15000` перечитывает весь data.csv; за 8–12-часовую сессию файл вырастает до сотен КБ — ESP32 отдаёт его каждые 15 с параллельно с процессом. CategoryAxis с тысячами категорий убивает телефонный браузер. Фикс: инкрементальная догрузка или хотя бы reloadFrequency 60 с + децимация на сервере.

**[🟠] WebServer.ino:497 — `Access-Control-Allow-Origin: *` на GET-команды без авторизации.** Любая открытая страница может дёрнуть `http://<samovar>/command?power=1`. Устройство управляет ТЭНом. Фикс: убрать заголовок, опасные команды перевести на POST.

**[🟠] index.htm:1033 + WebServer.ino:1271 — «Начать отбор» при выключенном нагреве молча игнорируется.** Сервер выполняет start только `if (... && PowerOn)`, иначе `200 OK`. UI никак не реагирует. Фикс: сервер отвечает `"POWER_OFF"`, фронт показывает сообщение; или фронт проверяет `myObj.PowerOn` перед отправкой.

**[🟠] index.htm:915,953,1057; chart.htm:501 — тёмная тема сломана инлайновыми цветами.** `style="color: black"` у «Δ температур» — чёрный по `--bg-form:#21303d` невидим; статус-бар `#7cfc0063` с `color:#333`; блок `#F7F7F7`. Фикс: токены `var(--text-strong)` и т.п.

**[🟡] index.htm:16–262 ↔ chart.htm:17–231 (и страницы режимов) — весь «фреймворк» скопирован и разъехался.** `ConnectError`, `addMessage`, `showMessages`, `playSound`, `escapeHtml`, theme, `openTab`, `check_program`, `get_time` продублированы. Копии мутировали: порог обрыва в index.htm:22 — 3 отказа, в chart.htm:24 — 1, с опечаткой `OfflineCouner` и двойным `var IsOffline` (chart.htm:17,20); `IsCalmingPause` сбрасывается в chart.htm:187, но **не** в index.htm:215–228 — на главной «Продолжение через…» покажется один раз за сессию. Фикс: общий `/app.js` (+ .gz).

**[🟡] index.htm:194 vs 205–209 (то же chart.htm:158 vs 165–168) — деактивация старых сообщений никогда не срабатывает.** `replace('onclick=removeLastMessage() style="cursor: pointer"', '')` ищет строку без кавычек, в разметке — с кавычками и `;`. Замена — no-op: кликабельны все сообщения, клик по любому удаляет последнее. Фикс: рендерить через createElement + делегированный обработчик.

**[🟡] index.htm:527–534 — номер программы выскребается из локализованной строки статуса.** `indexOf('Прг №')` + `substring` + parseInt: поменяется текст статуса — подсветка тихо умрёт. Фикс: отдать `ProgramNum` полем в /ajax.

**[🟡] index.htm:143–147,156 — история: бесконечный рост localStorage и запятые в вёрстке.** `saveHistory` пишет навсегда; `innerHTML = historyArray` склеивается через запятую. Фикс: `join('')` и cap на 500 записей.

**[🟡] index.htm:646–740,739 — addLine вызывает calc_program на каждой строке: O(n²) с перезаписью textarea.** На 20 строках — 20 полных пересчётов при каждой перерисовке (а она случается из поллинга при смене строки, index.htm:532–534). Навигация `childNodes[2..7]` по магическим индексам. Фикс: `calc_program()` один раз после цикла; доступ по `querySelector`.

**[🟡] program.htm:66–76,182–189 — сетевые ошибки уходят в console или в никуда.** `updateColumnParams` — только `console.error`; `getProgramFromFile` — fetch без `.catch` и `response.ok` (404 → текст ошибки в textarea как «программа»). Фикс: проверять `r.ok`, показывать сообщение.

**[🟡] program.htm:557–561 — смена типа сырья молча затирает отредактированную программу.** `onchange="getProgramFromFile(this)"` перезагружает шаблон поверх ручных правок. Фикс: confirm при наличии изменений.

**[🟡] chart.htm:10,46–108 — ~3 КБ мёртвого кода.** `setPowerUnit`, `AddLuaButtons` не вызываются; элементов `PWR`, `SetVoltage`, `lua_btn_ln` в chart.htm нет; `run_lua` не определён; `%btn_list%` зря гоняется через шаблонизатор. Фикс: удалить.

**[🟡] brewxml.htm:456 + index.htm:397–401, program.htm:393–397 — контракт успеха /program вывернут наизнанку.** Сервер на успех возвращает **текст программы** (WebServer.ino:1387–1407), «OK» — только если параметра не было. Фронт: «если не OK → успех», а при настоящем «OK» пользователь не видит ничего. brewxml.htm:456 — `alert(program)`, сырой дамп, забытый debug. Фикс: JSON `{ok:true, program:"..."}` + тост.

**[🟡] brewxml.htm:525,533 — `className=` в HTML не работает.** JSX-изм; стили `.ingredients` не применяются. Тут же brewxml.htm:549: textarea с `visibility: hidden` без `position:absolute` — дыра на 7 строк внизу. Фикс: `class=` и `display:none`.

**[🟡] setup.htm:286,371 — дублирующийся `id='selftest'` на двух кнопках.** Невалидно. Тут же setup.htm:181: `style="min-width: 1024;"` — безъединичное, игнорируется. Фикс: разные id, min-width убрать.

**[🟡] style.css:542–553 — `img` и `select` глобально получают `margin-left: 21px !important` и `cursor: pointer`.** Селектор `.prgline input, img, select` — правило глобально для всех картинок/селектов; из-за этого индикатор связи отбивается инлайновым `margin: 0 !important` (index.htm:886). Фикс: `.prgline input, .prgline img, .prgline select`.

**[🟡] style.css:288–302,367–381,405–409,667–672,705–708 — мёртвые стили; `.message-box` не существует.** `.card-bordered/.card-padded/.row-between/.row-around/.text-center/.bold`, `.button_mob`, `.button_img`, `.pointer`, `.infotext` — не используются нигде. Обратное: `class="message-box"` в program.htm:553, chart.htm:480, brewxml.htm:477 — в CSS есть только `.messages_box`. Фикс: вычистить оба направления.

**[🟡] setup.htm:117–121 — rescanSensors перезагружает страницу по таймеру 1000 мс.** Скан OneWire отложен в loop (WebServer.ino:1316–1317), а страница перезагружается через фиксированную секунду — успел скан или нет, лотерея. Фикс: 2–3 с или опрос готовности.

**[🟡] index.htm:20–42,233–251 — после восстановления связи сирена может вернуться.** «Обрыв связи!» (message_0) остаётся в очереди после реконнекта; любой следующий `addMessage` прогоняет `showMessages`, который находит `class="message_0"` → `is_ALARM=true` → сирена при живой связи. Фикс: при реконнекте удалять сообщения об обрыве из `Messages_Array`.

**[⚪] index.htm:91,204,218,322,342,630,765,789,815–819 — россыпь неявных глобалов.** `for (i = 0...)`, `l = Math.trunc(tm)`, `previousMsg`, `lastMsg` без var/let. Фикс: `let` + `'use strict'` в будущем app.js.

**[⚪] index.htm:474–545 — `innerHTML` для чисел.** `textContent` быстрее и безопаснее (местами уже так — непоследовательно).

**[⚪] index.htm:99,712,718; program.htm:445–485 — инлайн-обработчики и `setAttribute('onclick', строка)`.** Генерация обработчиков конкатенацией строк — хрупко, несовместимо с CSP. Также `onclick='javascript:location.href=...'` (index.htm:1038–1039).

**[⚪] program.htm:364–372 — шапка таблицы `&nbsp;`-художеством.** На index.htm та же шапка сделана через `.program_header` с процентными ширинами (index.htm:753–762) — перенести.

**[⚪] index.htm:774 — `"#FFF;"` — невалидный цвет.** Точка с запятой внутри значения — дефолтная ветка set_bgcolor не красит.

**[⚪] setup.htm:57–71 — расширение `HTMLElement.prototype.serialize`.** Монкипатчинг ради одной формы. Обычная `serializeForm(el)` без риска коллизий.

**[⚪] edit.htm:158–165,190,224 — археология.** `ActiveXObject` (IE6); `if(!req instanceof Object)` — выполняется `(!req) instanceof Object`, всегда false; `p instanceof String` не срабатывает для литералов.

**[⚪] wifi.htm:11 — `input { width: 800 }` без единиц.** Игнорируется; хотели `100%`.

**[⚪] chart.htm:269 vs index.htm:525 — статус собирается в разном порядке.** `PrgType + Status` vs `Status + "; " + PrgType`.

**[⚪] style.css:92–97 — `-webkit-appearance: slider-horizontal` устарел.**

### 5.2. Предложения по улучшению (основные страницы)

1. **Общий `/app.js` + gzip.** Вынести продублированный каркас из index/chart/beer/distiller/nbk/bk в один статический файл через готовый `handleFileWithGzip` с `max-age`. Расхождения типа `IsCalmingPause`/`OfflineCouner` исчезают как класс. Trade-off: не забывать пересобирать `.gz` (процесс для style.css уже есть).
2. **index.htm — статикой, динамику — мини-JSON.** 51 КБ гоняются через шаблонизатор с `no-store` на каждый вход. Если `%pwr_unit%`, `%WProgram%`, `%Descr%`, btn_list отдавать крошечным `/boot.json` (или первым /ajax), index.htm становится кэшируемым gzip ~10 КБ. Trade-off: +1 запрос и рефакторинг инициализации; выигрыш — на порядок меньше трафика и CPU.
3. **SSE вместо поллинга.** `AsyncEventSource` уже есть в ESPAsyncWebServer: пуш того же JSON раз в 2 с всем подписчикам. Trade-off: постоянные соединения при лимите async_tcp, нужен reconnect; при одном операторе выигрыш умеренный — после пунктов 1–2.
4. **Инкрементальный лог для графика.** `GET /data.csv?from=<offset>` + `chart.addData()` вместо полной перезагрузки каждые 15 с. Единственное лекарство от «к десятому часу график ест 200 КБ каждые 15 секунд».
5. **Локальный график вместо amCharts CDN.** uPlot (~12 КБ gz) в LittleFS: 6 линий, зум, легенда, работает в AP-режиме, быстрее на телефоне. Закрывает 🔴 с мёртвой страницей офлайн.
6. **viewport + doctype на все страницы.** Две строки на файл. Trade-off: после перехода в standards mode прокликать вёрстку.
7. **confirm() на разрушающих действиях** (нагрев off во время процесса, reset, reboot, resetwifi, перезатирание программы шаблоном). «Пауза» и «Начать отбор» остаются одноклик.
8. **Тосты вместо `alert()`.** alert блокирует event loop: пока диалог открыт, poll-цикл стоит, статус и сирена заморожены — для аппарата с нагревом это не косметика. Trade-off: ~30 строк JS/CSS и ревизия всех alert.
9. **Явный контракт ответов.** `/command` и `/program` отвечают JSON `{ok, err:"POWER_OFF"|"BUSY", program}`. Закрывает молчаливый дебаунс и молчаливый start-без-нагрева. Trade-off: синхронная правка прошивки и всех страниц.
10. **`ProgramNum` и код состояния в /ajax.** Убирает парсинг «Прг №» из строки; UI получает честный ответ «что сейчас делает аппарат». Trade-off: пара строк в send_ajax_json + миграция подсветки.

### 5.3. Что сделано хорошо

- **Поллинг без утечек:** самопланирующийся `setTimeout` + `AbortController` 4 с (index.htm:461–465, 828–831); ни одного бесхозного setInterval.
- **Индикатор связи с дебаунсом** на 3 отказа и звуковой тревогой.
- **XSS в сообщениях закрыт:** `escapeHtml`, lua-кнопки через `<script type="application/json">` + JSON.parse.
- **Тёмная тема на CSS-переменных** с `prefers-color-scheme`, переключателем и localStorage (style.css:2–65).
- **Мобильный CSS написан осмысленно** (breakpoints 900/600, 16px против iOS-зума) — осталось включить viewport'ом.
- **gzip-инфраструктура готова:** `handleFileWithGzip` (WebServer.ino:218–232), style.css.gz, edit.htm.gz.
- **wifi.htm — образцовая страница:** doctype, viewport, confirm() на стирание кредов.
- **edit.htm имеет fallback на локальный /ace.js** (edit.htm:647–654) — паттерн для chart.htm.
- **Мелкая правильная доступность:** `inputmode='decimal'`, `:focus-visible`, `.tooltip:focus-within`.
- **Сервер выносит блокирующие операции из async-контекста в loop** (комментарии [C-*]/[W-*] в WebServer.ino) — на UI отражается стабильностью /ajax.

## 6. UI: страницы режимов

Зона: `data/beer.htm`, `data/distiller.htm`, `data/nbk.htm`, `data/bk.htm`, `data/i2cstepper.htm`, Lua-файлы. Все находки сверены с бэкендом (WebServer.ino, Samovar.ino).

### 6.1. Дублирование между страницами режимов — главный диагноз

Каждая страница режима несёт **~20–29 КБ инлайн-JS** (beer: 28.7K, distiller: 24.3K, nbk: 21.3K, bk: 19.9K), из которых **~12–15 КБ — один и тот же скопированный блок**, живущий в пяти экземплярах (включая index.htm).

**Идентичные копии (байт в байт или почти):**
- `AddLuaButtons` — beer.htm:74, distiller.htm:74, nbk.htm:77, bk.htm:75.
- `applyTheme`/`toggleTheme`/`initTheme` — 5 копий (плюс i2cstepper.htm:295–329).
- `openTab`, `escapeHtml`, `sendbutton`, `run_lua`, `run_strlua`, `sendI2CPump`/`stopI2CPump`, `getHistory`/`saveHistory`, `addMessage`, `showMessages`, poll-петля `pollLoop` — идентичны во всех четырёх.
- HTML-шапка (Samovar + версия + индикатор связи + messagesBox + «Работа»), блок «История», блок PWR-регулятора, блок lua_btn, мёртвый div `I2CPump` — скопированы 4 раза.

**Тонко разошедшиеся копии (рассадник багов):**
- `ConnectError`: nbk.htm:18 — порог `OfflineCounter < 4`, у остальных `< 3` (beer.htm:18, distiller.htm:18, bk.htm:19); комментарий в nbk врёт «считаем 3 обрыва подряд», а ветка восстановления сверяется с `>= 3` (nbk.htm:32) — рассинхрон внутри одной функции.
- Звук тревоги — **три разных поведения одной сирены**: beer.htm:112 и nbk.htm:115 — `sound.loop = true` (бесконечная сирена); distiller.htm:114–135 и bk.htm:115–136 — `loop = false` + `MAX_SOUND_PLAYS = 2`. При этом nbk.htm:225 и nbk.htm:261 присваивают `sound_play_count = 0`, **который в nbk нигде не объявлен** — немой рудимент копипасты (неявный глобал, ничего не делает).
- `removeLastMessage`: beer.htm:223 сбрасывает `IsCalmingPause`, distiller.htm:235/bk.htm:235/nbk.htm:225 — `sound_play_count`. Три варианта одной функции.
- `showHistory`/`clearHistory` vs **`showHystory`/`clearHystory`** — nbk.htm:149, 163, 592, 594 живут с опечаткой в имени; работает, но общий рефакторинг сломает именно nbk.
- `sendvoltage` — четыре варианта: beer.htm:401–410 и bk.htm:412–421 валидируют regex'ом; nbk.htm:421–430 валидирует со своим текстом; **distiller.htm:354–358 валидацию потерял полностью** (см. 🟠 ниже).
- `check_program` — есть в beer/bk/nbk, **в distiller отсутствует**: distiller-`set_program` шлёт программу без проверки.
- `set_program` — четыре варианта (beer валидирует + заменяет запятую, distiller только запятую, nbk/bk сначала `calc_program()`); тексты alert разошлись.
- `setPowerUnit`: distiller.htm:53 — `'visibility: hidden; margin: 0; padding: 0'`, beer.htm:53/bk.htm:54 — просто `'visibility: hidden'`; nbk.htm:41–74 — расширен `programPwrLabel`/`opt_*`.
- `loadDoc` — четыре варианта с ~60% общих строк; расхождения включают точность (`toFixed(3)` в beer/bk vs `toFixed(1)` в nbk/distiller) и обработку опциональных полей.

Вывод: это не «четыре страницы», это один файл, размноженный копипастой и мутировавший в четырёх направлениях. Каждый фикс (видно по истории sound-блока) вносится в 1–2 копии из 5.

### 6.2. Находки

**[🔴] beer.htm:918, distiller.htm:832, nbk.htm:739, bk.htm:731 — выключение нагрева без подтверждения.** Кнопка «Выключить нагрев» срабатывает по одному клику/тапу, `confirm()` нет нигде. Случайный тап на телефоне посреди 6-часовой дистилляции — нагрев выключен молча. То же с «Следующая программа» (beer.htm:919, distiller.htm:833, nbk.htm:740) — один клик необратимо перескакивает этап. Фикс: `if (!confirm('Выключить нагрев?')) return;` при выключении и аналогично для start=1.

**[🔴] beer.htm:383–386, distiller.htm:380–383 — «Установить программу» затирает правки пользователя старой программой.** Бэкенд применяет программу отложенно в `loop()` и отвечает **текущим (старым)** текстом (WebServer.ino:1386–1410). Фронт делает `if (text !== "OK") { WProgram.value = text; alert("Ok"); }` — textarea откатывается к старой программе. Ловушка на beer: пользователь правит → «Установить» → видит старое → жмёт ещё раз → на сервер уходит старая программа, реально откатывая правку. На nbk/bk защищает `calc_program()` перед отправкой. Фикс: не перезаписывать textarea ответом (или перечитать программу отдельным запросом через секунду); при ответе «OK» пользователь вообще не получает подтверждения — тоже исправить.

**[🟠] distiller.htm:354–358 — `sendvoltage` без валидации ставит мощность в 0.** Единственная из четырёх копий без regex-проверки. `"abc".toFloat()` на сервере = 0 → `set_current_power(0)` (WebServer.ino:1367–1369), а UI рапортует «Установлено.». Фикс: вернуть валидацию из beer.htm:404–407.

**[🟠] Все четыре страницы — ложные подтверждения успеха.** `sendvoltage` всегда алертит «Установлено.» — `sendbutton` глотает ошибку. Бэкенд молча дропает команды чаще, чем раз в 1500 мс (WebServer.ino:1255–1259, ответ всё равно «OK»), и игнорирует `pnbk`/`nbkopt` при выключенном нагреве (WebServer.ino:1324, 1331) — а nbk.htm:450 и nbk.htm:455 алертят успех в любом случае. Фикс: сервер отвечает отличимо («IGNORED»/«BUSY»), фронт показывает подтверждение только на реальный «OK»; минимум — убрать безусловные alert.

**[🟠] Все страницы режимов — нет `<meta name="viewport">`, мобильная вёрстка мертва.** В style.css:802 и style.css:817 есть адаптивные блоки под 900/600px, но без viewport-меты телефон рендерит в layout viewport ~980px — медиазапросы не срабатывают никогда. Из всего data/ мета есть только в wifi.htm:5. Управление с телефона (основной кейс!) — кнопка «Выключить нагрев» размером 4 мм. Фикс: `<meta name="viewport" content="width=device-width, initial-scale=1">` в каждый htm.

**[🟠] beer.htm:116–124 (и все копии) — сирена тревоги не сыграет без клика по странице.** `sound.play()` без пользовательского жеста блокируется autoplay-политикой; промис отклоняется, ошибка не обработана. Вкладка открыта с вечера, ночью тревога — красный текст есть, звука нет. Фикс: `sound.play().catch(...)` + одноразовый «разблокирующий» play/pause по первому клику и/или баннер «звук заблокирован браузером».

**[🟠] beer.htm:508–510, distiller.htm:615–617, nbk.htm:549–551, bk.htm:513–515 — catch в loadDoc превращает любую JS-ошибку в «Обрыв связи!».** Один try/catch на весь разбор: TypeError из-за отсутствующего поля = ConnectError(true) = красная лампа и сирена при живой связи. Реальный сценарий: устройство переключили в другой режим из другой вкладки — `/ajax` перестаёт слать `alc` (Samovar.ino:1884–1889, поле только для DIST/RECT/BK/NBK) → distiller.htm:559 `myObj.alc.toFixed(1)` кидает TypeError → вечный «обрыв». Фикс: отделить сетевую часть (fetch+json) от DOM-обновлений; ошибки DOM — в console.error.

**[🟠] bk.htm:664 + bk.htm:553–554 — слайдер насоса шлёт команду дважды.** Inline `onchange='sliderChange();'` И `addEventListener("change", sliderChange)` в DOMContentLoaded. Каждое движение = два `/command?watert=`, второй съедается серверным троттлингом 1500 мс — но и следующая осмысленная команда в этом окне будет съедена. В beer.htm:1025 — только inline (очередное расхождение копий). Фикс: убрать addEventListener.

**[🟠] nbk.htm:376–380, 389 — `getProgram` падает или алертит при загрузке страницы.** Вызывается из `window.onload` (nbk.htm:564): при пустой `%WProgram%` — alert «Ошибка в программе!» при каждом открытии; при программе >4 строк `t[i+1]` = undefined → TypeError → **onload прерван, poll-петля не стартует, страница мертва**. Фикс: молча пропускать пустую программу; ограничить цикл `Math.min(lines.length, t.length - 1)`.

**[🟠] beer.htm:373, distiller.htm:371 — `replace(",", ".")` чинит только первую запятую.** В многострочной программе с несколькими десятичными запятыми исправится одна; `toFloat()` на сервере обрежет дробную часть у остальных. Фикс: `replaceAll(",", ".")`.

**[🟠] beer.htm:889, distiller.htm:781, nbk.htm:692, bk.htm:687 — Enter в любом текстовом поле нажимает «Установить напряжение».** Все кнопки — `type='submit'` в форме; implicit submission по Enter кликает первую submit-кнопку — SetVoltage. Фикс: все кнопки-действия → `type='button'`.

**[🟡] distiller.htm:328–336, bk.htm:388–396, nbk.htm:397–405 — состояние «вкл/выкл» вычисляется из надписи на кнопке.** `if (power.value == "Выключить нагрев")` — UI-строка, обновляемая поллингом раз в 2 с, определяет команду. Окно гонки: состояние изменилось на устройстве, клик до следующего полла шлёт инверсную команду. beer.htm:918 шлёт `power=1`, и сервер сам делает toggle по фактическому PowerOn (WebServer.ino:1281–1299) — правильный паттерн уже есть, применён в одном режиме из четырёх. Фикс: везде слать `power=1`.

**[🟡] beer.htm:1055–1068, distiller.htm:930–943, nbk.htm:847–860, bk.htm:788–801 — мёртвая вкладка I2CPump ×4.** `div id="I2CPump"` не открывается ниоткуда — ни одного `openTab(event, 'I2CPump')` в проекте. Мертвы и `sendI2CPump`/`stopI2CPump`, и обновления `i2c_*` в loadDoc. Рудимент до появления i2cstepper.htm. Фикс: удалить (~60 строк ×4).

**[🟡] Мёртвый код — коллекция:** beer.htm:412–420 `sendpumpspeed` обращается к `#pumpspeed`, которого в beer нет; nbk.htm:416–419 `sendwaterpwm` — в nbk нет `#PWM`; bk.htm:739–765 — целый таб «Prog» недостижим (в панели вкладок bk.htm:577–581 кнопки нет), с ним мертвы `set_program`/`calc_program`/`check_program` (bk.htm:328–386); beer.htm:309 `glcalcnum = false` — необъявленный глобал; `IsCalmingPause` объявлен во всех четырёх, используется только в index.htm:550–552.

**[🟡] beer.htm:200–205 (и копии) — «деактивация» предыдущего сообщения никогда не срабатывает.** `previousMsg.replace('onclick=removeLastMessage() style="cursor: pointer"', '')` ищет строку без кавычек и без `;`, а в шаблоне (beer.htm:190) — `onclick="removeLastMessage()" style="cursor: pointer;"`. Replace — no-op: клик по любому старому сообщению удаляет последнее. Фикс: хранить сообщения объектами и рендерить, а не хирургией по HTML-строкам.

**[🟡] beer.htm:152, distiller.htm:164, nbk.htm:155, bk.htm:164 — история рендерится с запятыми-мусором.** `historyList.innerHTML = historyArray` — массив приводится к строке через `join(",")`. Фикс: `historyArray.join('')`.

**[🟡] `saveHistory` (все страницы) — localStorage растёт бесконечно.** Каждое сообщение навсегда в `samovarHistory`; лимита нет. За месяцы — деградация и упор в квоту. Фикс: `if (saved.length > 500) saved = saved.slice(-500);`.

**[🟡] nbk.htm:504 — висячий оператор `myObj.PipeTemp.toFixed(3)`.** Ничего не делает; строки 497–501 предполагают, что PipeTemp может отсутствовать — тогда эта строка кинет TypeError и через общий catch устроит фальшивый «Обрыв связи!». Фикс: удалить строку.

**[🟡] Все страницы режимов — нет `<!DOCTYPE html>`, браузер в quirks mode.** Доктайп есть только у edit.htm и wifi.htm. Проценты высот, box-sizing, line-height считаются по-старому — тема и адаптив недетерминированы. Фикс: одна строка сверху каждого файла.

**[🟡] Тёмная тема vs зашитые инлайн-цвета.** Статус-бар `background-color: #7cfc0063` + `color: #333` (beer.htm:870–873, distiller.htm:753–756, nbk.htm:679–682, bk.htm:653–656), bk.htm:626 `color: black`, nbk.htm:672 `color:#444` — в тёмной теме тёмное-на-тёмном. Фикс: CSS-переменные из style.css.

**[🟡] i2cstepper.htm:331–334 — поллинг двух эндпоинтов каждые 2 с даже когда устройств нет.** Фикс: при отсутствии девайса интервал 10 с. Плюс i2cstepper.htm:280–284: после клика «Запустить» ~2 с показывается старое состояние (сервер отвечает pre-command статусом, WebServer.ino:459) — повторный клик отправит вторую команду.

**[⚪] Разнобой мелочей между режимами:** Cache-Control meta «no-cache» (beer/distiller/bk) vs «no-store, max-age=0» (nbk/i2cstepper) — meta http-equiv браузеры игнорируют; id кнопки следующей программы `start` (beer/nbk) vs `nextprg` (distiller); блок кнопок в разных местах и компоновке: beer — строка из 4 ПОСЛЕ системных параметров (beer.htm:917–922), distiller — 2×2 (distiller.htm:830–839), nbk — строка из 4 ДО системных параметров (nbk.htm:737–744), bk — строка из 3 (bk.htm:729–735). «Выключить нагрев» на каждой странице в другом месте — мышечная память оператора не работает.

**[⚪] nbk.htm:727, 732 — магические `pnbk=8000/9000`.** Сервер трактует 9000 как «+шаг», 8000 как «−шаг», остальное как абсолютную скорость (WebServer.ino:1324–1330). Пользователь, вписавший 8000 в поле скорости, получит декремент. Фикс: отдельные параметры `pnbk_step=+1/-1`.

**Lua-файлы (по ролям):** init.lua — выключатель ежесекундного lua-цикла; dist.lua — «дистилляция по Габриелю» с переключением 3 ёмкостей; rectificat.lua — автозаполнение куба (check4volume — заглушка; `getNumVariable(WFflowRate)` без кавычек — обращение к nil-глобалу, вернёт мусор, если включат); beer.lua — термостат брожения; в beer.lua:45 `setLuaStatus(status)` вызывается **до** формирования `status` (строка 49) — статус всегда отстаёт на тик/nil на первом.

### 6.3. Предложения по улучшению (страницы режимов)

1. **Общий `app.js` вместо пяти инлайн-копий.** Вынести общий блок (ConnectError, messages/sound/history, theme, openTab, sendbutton, sendvoltage, poll-петля, escapeHtml) в один статический `/app.js`; страницы оставляют себе только режимную специфику (маппинг полей loadDoc, редакторы программ). Выигрыш: −12–15 КБ с каждой страницы; багфиксы чинятся один раз. Статический app.js можно **гзипнуть и закэшировать** (механизм `handleFileWithGzip` в WebServer.ino:214 уже есть, использован для style.css). Trade-off: +1 HTTP-запрос при первой загрузке; нужно аккуратно разнести режимные точки расширения (например, `loadDoc` вызывает `window.updateModeFields(myObj)`).
2. **Сборочная шаблонизация data/.** Простейший build-скрипт (Python/Node), который из `partials/` (шапка, история, PWR-блок, lua-блок) собирает 4 htm перед заливкой LittleFS. Trade-off: появляется шаг сборки; но именно его отсутствие породило 4 мутировавшие копии.
3. **Минификация и чистка мёртвого кода.** Gzip для страниц нельзя (шаблонизатор `%WProgram%` требует сырой текст), но удаление мёртвых блоков (I2CPump ×4, Prog в bk, мёртвые функции) — −3–5 КБ без инструментария; при сборке из п.2 минификация даст ещё ~30%.
4. **Дифференцированный поллинг.** `document.hidden` → интервал 10 с вместо 2 с. Фоновые вкладки сейчас не только грузят ESP32, но и **воруют одноразовые сообщения**: `/ajax` делает destructive read через `consume_web_message` (Samovar.ino:1826) — активная вкладка не увидит тревогу, которую забрала фоновая. Trade-off: тревога в фоновой вкладке — с задержкой до 10 с; серьёзная альтернатива — рассылка Msg всем клиентам с TTL на бэкенде.
5. **Подтверждения опасных действий + честный фидбек команд.** confirm на выключение нагрева/след. программу; сервер отвечает «IGNORED» на затроттленные/невыполнимые команды; кнопка после клика — disabled на 1.5 с (серверный троттлинг). Trade-off: +1 клик на легитимное выключение — для процесса длиной в часы дёшево.
6. **Viewport + doctype на все страницы.** Две строки на файл, мобильный CSS уже написан и просто не включается.

### 6.4. Что сделано хорошо

- **Poll-петля без наложений**: `await loadDoc(); setTimeout(pollLoop, 2000)` вместо `setInterval` — запросы не штабелируются; таймаут через `AbortController` (4 с) на всех страницах.
- **Индикация связи** с гистерезисом (3 сбоя подряд), зелёная/красная лампа, тревожное сообщение и звук.
- **escapeHtml для серверных сообщений** и `textContent` для Status — XSS-гигиена на месте.
- **Lua-кнопки через `<script type="application/json">`** с try/catch-парсингом — аккуратная передача данных без eval.
- **i2cstepper.htm — образец для остальных**: общий helper `requestJson` вместо копипасты, dirty-tracking полей (i2cstepper.htm:88–113), чтобы поллинг не затирал ввод, capability-driven видимость блоков. Общий app.js стоит писать в этом стиле.
- Кнопка нагрева меняет цвет по фактическому `PowerOn` с сервера; у distiller — прогноз времени, у beer — прогресс-процент.
- style.css вынесен и гзипован, тёмная тема через CSS-переменные с уважением к `prefers-color-scheme`.

## 7. Сводка и приоритеты

### 7.1. Критичные проблемы (чинить в первую очередь)

**Безопасность процесса (нагрев!):**
1. **Авто-рестарт нагрева после аварийного отключения** (distiller/BK, §4.1) — авария по перегреву превращается в перезапуск сессии с включённым нагревом. Самая опасная находка аудита.
2. **Отказ датчика температуры не останавливает нагрев** (все режимы, §4.1) — затор/куб выкипает без единой аварии при умершем DS18B20.
3. **Выключение нагрева и «Следующая программа» в один клик без confirm** на всех страницах UI (§5.1, §6.2) + **команды молча глотаются дебаунсом 1500 мс с ответом «OK»** (§5.1) — оператор уверен, что нагрев выключен, а он работает.

**Стабильность прошивки:**
4. **async_tcp реально работает на core 0 с приоритетом 5** — дефайны в скетче мертвы, веб вытесняет опрос датчиков и аварийные проверки (§1.2). Все остальные async-нарушения умножаются на этот факт.
5. **Блокирующие операции в async-хендлерах**: I2C-refresh на каждый `/ajax` (мимо собственного кэша), `vTaskDelay(100)`+UART в `voltage`, I2C-цепочка в `mixer`, SPIFFS в `lua`/`%btn_list%`/SPIFFSEditor, `flush()` общего лог-файла, `resetwifi` со стиранием NVS и рестартом до отправки ответа (§1.5, §3.1).
6. **Один `lua_State` из трёх задач на двух ядрах без мьютекса** (§1.5, §3.1) — порча интерпретатора при наложении.
7. **NVS: успешная запись пустой строки трактуется как сбой → полная неатомарная перестройка всех неймспейсов** с RAM-бэкапом — обрыв питания в этом окне теряет все настройки (§3.1).
8. **UI: chart.htm полностью мёртв без интернета** (amCharts с CDN без fallback, §5.1); **«Установить программу» затирает правки пользователя старой программой** (§6.2).

### 7.2. Системные темы (источники будущих багов)

- **Копипаста — главная болезнь проекта на обоих уровнях.** Прошивка: 4 копии аварийных блоков и парсеров программ уже разошлись поведением (PWR_FACTOR, 30/60 с, overflow-safe формы — §4.5). UI: ~12–15 КБ идентичного JS в 5 страницах, копии мутировали (пороги ConnectError, три поведения сирены, потерянная валидация — §6.1). Каждый багфикс доезжает до 1–2 копий из 4–5.
- **Идиома `pending_*` (async→loop) выполнена на ~80%** — оставшиеся 20% (mixer, voltage, watert, pumpspeed, resetwifi, stopst, lua) — как раз самые тяжёлые операции (§1.5, §3.1).
- **Правило «общие String — под локом» имеет точечные дыры**: SessionDescription, program[].WType, Lua_status, Msg из Lua, program_Wait_Type (§1.5, §2.2).
- **Идиома overflow-safe millis [C-13] применена не везде**: distiller.h:326, BK.h:138, impurity_detector.h ×3 (§4.3) — ищется греп-паттерном.
- **Молчаливые отказы**: сервер отвечает «OK» на проигнорированные команды, UI алертит успех при любом исходе, get_web_file пишет в переполненную FS без проверки (§3.1, §5.1, §6.2).
- **Мёртвый код накапливается**: quality.h (240 байт RAM), stacktrace_buffer (2 КБ RAM), verbose_print_reset_reason с неверным маппингом, вкладка I2CPump ×4 в UI, таб Prog в bk.htm, ~3 КБ в chart.htm (§2.2–2.3, §5.1, §6.2).

### 7.3. Рекомендуемая последовательность работ

**Этап 0 — часы (quick wins, почти без риска):**
- `<!DOCTYPE html>` + `<meta viewport>` на все страницы (включает уже написанный мобильный CSS).
- `confirm()` на выключение нагрева / следующую программу / reset / reboot / resetwifi.
- `/ajax`: заменить `get_stepper_speed()` на чтение `i2c_stepper_cache` (кэш уже есть).
- Фикс детектора сбоя NVS (`putString == 0 && value[0] != '\0'`).
- Blynk-токен: `== 32` + copyStringSafe.
- `{ distiller_finish(); return; }`; `#pragma once` в режимные .h; удалить корневой partitions.csv.

**Этап 1 — дни (закрывает критичные гонки):**
- Аварийные ветки всех режимов → единый путь `sam_command_sync = SAMOVAR_POWER` (образец уже есть: distiller.h:381).
- Хелпер `sensor_valid()` в контурах управления нагревом + стоп процесса при отказе управляющего датчика.
- Дочистить `pending_*` до 100% (mixer, voltage, watert, pumpspeed, resetwifi, stopst, lua-файл).
- Мьютекс/единая задача для `lua_State`.
- async_tcp: перенести CONFIG-дефайны в build_flags и принять осознанное решение по ядру/приоритету.
- Сервер: отвечать «BUSY»/«IGNORED»/«POWER_OFF» вместо безусловного «OK»; UI: показывать реальный результат.

**Этап 2 — недели (структурные):**
- `mode_common.h`: общие аварийные блоки + парсер программ (половина работы — решить, какая из разошедшихся копий права).
- Общий `/app.js` (+gzip через готовый handleFileWithGzip) вместо пяти инлайн-копий; за основу — стиль i2cstepper.htm.
- `handleSave` → staging-копия с валидацией диапазонов, применение в loop.
- FreeRTOS-очередь команд вместо одноместного `sam_command_sync` + реестр режимов `ModeOps` (§1.4, п.3–4).
- Локальный uPlot вместо amCharts CDN + инкрементальная догрузка data.csv.

### 7.4. Общая оценка

Проект в заметно лучшей форме, чем типичный Arduino-код такого объёма: системная работа над конкурентностью видна (pending-идиома с барьерами, runtime_state_lock без единого вложенного захвата, комментарии-маркеры инвариантов, string_utils, NVS-менеджер с миграцией и ретраями). Основные риски — (1) три двигающих нагрев гонки в аварийных путях режимов, (2) недоведённая до конца pending-идиома в веб-слое, (3) копипаста режимов/страниц, из-за которой исправления systematically не доезжают до всех копий. Все три класса лечатся уже существующими в проекте механизмами — нужна доводка, а не пересмотр архитектуры.
