# БК: план внедрения правок 1–9 (2026-09-02)

Основание: `docs/plans/2026-09-02-bk-program-auto-water-design.md` (проект
согласован владельцем). Этот документ раскладывает девять пунктов на задачи,
владельцев файлов, волны, тесты и гейты. Термины: волна — группа задач, которые
идут параллельно и не трогают одни и те же файлы; гейт — проверка, без которой
следующая волна не начинается.

## Правила для всех задач

- Сабагенты: модель Sonnet, `run_in_background: false`. Три роли на задачу:
  планировщик (только чтение, пишет `.claude/experts/plans/bk-<задача>.md`),
  разработчик (правит только свои файлы), ревьюер (только чтение, формат
  `[Файл:Строка] - CRITICAL/WARNING/Nitpick`).
- Никакого git (commit/checkout/restore/stash/reset/clean). nbk.h не трогать.
- Сабагенты не запускают `pio run`. Сборку семи окружений и smoke-тесты
  запускает координатор между волнами, строго последовательно.
- Веб: править только `data_raw/`, затем `python3 tools/build_web_assets.py`;
  пины u03/u04 обновлять с комментарием-причиной.
- Тесты: харнесс на g++ с `-Werror`, мутация должна умирать от assert, а не от
  компилятора; заглушка-константа запрещена (минимум два значения);
  `strip_cpp_comments` до `extract_function_body`.
- Без запасных веток «на всякий случай», без новых полей NVS, без правок «для
  красоты». Одно решение на пункт.

## Владение файлами по задачам

| Задача | Пункты | Файлы кода | Тесты |
|---|---|---|---|
| A1 | 1, 2, 6, 8 | `BK.h`, `distiller.h` (только вынос плато DistTimeF в хелпер) | `smoke_dist_bk_small_fixes.py`, новый `smoke_bk_start_refusal.py`, новый `smoke_bk_plateau_finish.py`, при необходимости `smoke_bk_full_route.py` |
| A2 | 3 | `pumppwm.h` | переписать `smoke_pump_pwm_soft_start_target.py` |
| A3 | 5, текст 6 | `data_raw/bk.htm` (только `readNumericInput('PWMt', …)`), `data_raw/setup.htm` (подпись DistTemp), `WebServer.ino` (отказ `watert` < PWM_LOW_VALUE*10 при PowerOn в БК), `data/` через build_web_assets, пины u03/u04 | новый `smoke_bk_water_pwm_floor.py` |
| 9a | 9 (данные) | `program_io.h`, `sensorinit.h` (только `prepare_default_program_for_mode`) | новый `smoke_bk_program_rows.py`, обновить `smoke_program_io_contract.py`, `smoke_default_program_power_threshold.py` при необходимости |
| 9b | 9 (исполнение, вода, API) | `BK.h`, `distiller.h` (вынос `program_threshold_row_done`), `Samovar_ini.h`, `sensorinit.h` (`reset_process_state`), `samovar_api.h`, `Samovar.ino` (поля `/ajax`, pending-флаг `waterauto`), `WebServer.ino` (действие `waterauto`) | новый `smoke_bk_water_auto_step.py`, новый `smoke_bk_program_run.py`, обновить `smoke_bk_full_route.py`, `smoke_dist_bk_small_fixes.py`, `smoke_api_routes.py` при необходимости |
| 9c | 9 (страница) | `data_raw/bk.htm`, `data_raw/partials/program_table_dist.htm` (новый партиал), `data_raw/distiller.htm` (подключить партиал), `data_raw/program_bk.txt` (пример), `data/` через build_web_assets, пины u03/u04, `get_web_interface()` в `WebServer.ino` только строкой для `program_bk.txt` (согласовано с 9b: 9b не трогает этот список) | расширить `test_program_clear_ui_browser.py`, `test_program_calc_browser.py` на bk.htm; обновить `smoke_web_interface_update.py` при необходимости |

Пункт 4 (сброс `bk_pwm` при работающем насосе, `sensorinit.h:675`) делает
координатор до волны A одной строкой: `#ifdef USE_WATER_PUMP if (!pump_started) #endif bk_pwm = PWM_LOW_VALUE * 40;`
с тестом внутри `smoke_bk_water_auto_step.py` (9b) или отдельным пином.

Item 7 поглощён задачей 9c.

## Волны

1. Волна 0 (координатор): пункт 4; планировщики всех шести задач параллельно.
2. Волна A (параллельно): A1, A2, A3, 9a. Файлы не пересекаются.
   Гейт A: ревью 4 задач параллельно, исправления, затем сборка 7/7 без
   предупреждений, `python3 tools/run_smoke_tests.py`, браузерные гейты.
3. Волна B (параллельно): 9b и 9c. Контракт между ними зафиксирован ниже.
   Гейт B: ревью 2 задач, исправления, сборка 7/7, smoke, браузерные.
4. Петля «до чистого ревью»: два ревьюера по полному `git diff` (код и тесты)
   → исправления → гейт → повтор, пока оба не вернут «ошибок и предупреждений
   нет».

## Контракт 9b ↔ 9c (веб-API)

- Действие `waterauto=1` (POST /command, как `watert`). Ответы: 200 при
  включении; 409 `NOT_RUNNING`, если статус не БК или PowerOn == false или
  ProgramNum >= ProgramLen; 409 `NO_SETPOINT`, если у текущей строки
  `Temp == 0`; 400 при любом другом значении; в сборках без USE_WATER_PUMP
  409 `NO_PUMP`. Из async_tcp только очередь: `queue_pending_flag`, применение
  в loop().
- `/ajax`: `bk_water_auto` (bool), `bk_steam_setpoint` (float, 1 знак, 0 когда
  авторежим выключен). Всегда присутствуют (без USE_WATER_PUMP: false и 0).
- Формат строки программы БК: `Тип;Порог;Ёмкость;Мощность;Тпара`, пятое поле
  0 или 30..100.

## Задача A1 (BK.h): пункты 1, 2, 6, 8

1. Пункт 1. Локальный флаг `static bool bk_work_power_pending` в BK.h.
   Взводится при успешном `mode_run_heating_start` в `bk_proc`, снимается в
   `check_alarm_bk` при применении BKPower. Условие перехода на BKPower:
   `bk_work_power_pending && (boilingNow || пар/труба > CHANGE_POWER_MODE_STEAM_TEMP)`
   вместо `current_power_mode_is(POWER_SPEED_MODE)`. При предупреждении по
   воде во время разгона (ветка `mode_handle_water_pre_alarm_if_due`, см.
   `mode_water_alarm_power_base`) переход не должен теряться: если флаг ещё
   взведён, применить BKPower сразу и снять флаг. Также снимать флаг в
   `bk_finish`.
   Проверка: `smoke_bk_full_route.py` (харнесс) сценарий «регулятор уже не в
   SPEED, флаг взведён, кипение → BKPower применён один раз», мутация
   «вернуть current_power_mode_is(POWER_SPEED_MODE)» умирает.
2. Пункт 2. В `bk_proc` до `process_sensor_failed("БК","куба")`: при
   `!PowerOn && !sensor_valid(TankSensor) && !heater_safety_latched()` →
   `mode_cancel_process_start("БК не запущена: датчик куба не назначен или не отвечает")`,
   как `distiller.h:92–99`. Тест `smoke_bk_start_refusal.py` по образцу
   `smoke_dist_start_refusal.py` (сценарии A–D, три мутации).
3. Пункт 6. Вынести плато DistTimeF (`distiller.h:176–185`) в
   `inline bool dist_plateau_finish_due()` (или аналогичное имя) в distiller.h;
   звать из `distiller_proc` и `bk_proc` перед проверкой DistTemp. Состояние
   плато (`d_s_temp_finish`, `d_s_time_min`) общее, сбрасывается уже в
   `reset_process_state`. Тест `smoke_bk_plateau_finish.py`: харнесс тела
   хелпера (два значения DistTimeF: 0 → выкл; N → срабатывает после N минут
   без роста температуры).
4. Пункт 8. Удалить мёртвое предупреждение T16 (`BK.h:115`) и обновить пины в
   `smoke_dist_bk_small_fixes.py` (там закреплён порядок токенов
   `SamSetup.BKPower < power_work_mode_threshold()` → WARNING_MSG →
   `set_current_power`; выяснить, что именно относится к T16, остальное
   сохранить).

## Задача A2 (pumppwm.h): пункт 3

Убрать ветвление `duty != PWM_LOW_VALUE * 40` в обеих ветках `set_pump_pwm`:
плавный пуск всегда пишет `PWM_START_VALUE * 10` в первом вызове и первые 10
тиков, затем `duty`. Переписать `smoke_pump_pwm_soft_start_target.py`: сценарии
«duty == 400» и «duty == 700» ведут себя одинаково во время пуска; мутация
«вернуть сравнение с 400» умирает по assert. Проверить остальные вызывающие
(`beer.h`, самотест, `mode_update_water_pump_pid`).

## Задача A3 (веб-минимум): пункт 5 и подпись 6

- `data_raw/bk.htm`: `readNumericInput('PWMt', {min: PWM_LV, max: 1023})`, где
  PWM_LV берётся из атрибута `min` ползунка.
- `WebServer.ino`, ветка `watert`: после успешного разбора, если
  `Samovar_Mode == SAMOVAR_BK_MODE && PowerOn && waterPwm < PWM_LOW_VALUE * 10`
  → 409 `PWM_TOO_LOW`. Значение 0 без нагрева остаётся допустимым (остановка
  насоса вручную).
- `data_raw/setup.htm:346`: «Ректификация, дистилляция и БК до температуры в
  кубе».
- Пересобрать `data/`, обновить пины u03/u04 с комментарием.
- Тест `smoke_bk_water_pwm_floor.py`: пин ветки `watert` (порядок токенов) и
  строки `readNumericInput('PWMt'` с `min: PWM_LV`.

## Задача 9a (program_io.h): формат BK

- `PROGRAM_FORMAT_BK`, `bk_program_parse_spec()` (типы "TASPR", fieldCount 5),
  `program_parse_bk_row` (первые четыре поля через существующий разбор DIST без
  копирования кода: вынести общую часть в `program_parse_threshold_fields`),
  `program_append_bk_row`. Пятое поле: 0 или 30..100, иначе ошибка с текстом
  «Т пара: 0 или 30..100». `program_format_for_mode(SAMOVAR_BK_MODE)` → BK;
  LUA остаётся RECT. `serialize_program_for_mode`, `prepare_program_for_mode`
  (правило первой ненулевой мощности распространяется на BK так же, как на
  DIST). `PROGRAM_FIELD_TEMP` для пятого поля.
- `sensorinit.h`: `case SAMOVAR_BK_MODE:` отделить от LUA, дефолт
  `"T;93;1;0;0\n"` (одна строка, вода вручную; пустая программа парсером
  отвергается, см. `PROGRAM_PARSE_EMPTY_INPUT`).
- Тест `smoke_bk_program_rows.py`: харнесс парсера (валидная строка, 0 →
  вручную, 29.9 и 100.1 отбиты, лишний токен отбит, четыре поля отбиты для BK,
  DIST-парсер по-прежнему отбивает пять полей), сериализация обратима,
  дефолт БК разбирается. Мутации: убрать нижнюю границу; убрать верхнюю.

## Задача 9b (исполнение и вода)

- `distiller.h`: `inline bool program_threshold_row_done(const WProgram& row)`
  из `distiller.h:152–173`; `distiller_proc` зовёт хелпер. Пины
  `smoke_dist_bk_small_fixes.py` обновить.
- `BK.h`: `run_bk_program(uint8_t num)` по образцу `run_dist_program` (ёмкость,
  мощность строки при Power != 0, сообщение, `bk_steam_setpoint = row.Temp`,
  `bk_water_auto = row.Temp > 0`); старт строки 0 в точке применения BKPower
  (после A1: мощность строки 0 при Power > 0 перекрывает BKPower); в
  `bk_proc` при `PowerOn && ProgramNum < ProgramLen && program_threshold_row_done(program[ProgramNum])`
  → `run_bk_program(ProgramNum + 1)`; конец строк: сообщение «Выполнение
  программ закончилось, продолжение отбора», `ProgramNum = ProgramLen`.
- Проверка на старте (в `bk_proc`, до `mode_run_heating_start`): если в
  программе есть строка с `Temp > 0` и `!sensor_valid(SteamSensor)` →
  `mode_cancel_process_start("БК не запущена: программа требует датчик пара")`
  (только при `!heater_safety_latched()`). В сборках без USE_WATER_PUMP
  проверка не нужна: уставка игнорируется.
- Регулятор в `check_alarm_bk` (под USE_WATER_PUMP): условия из проекта
  (auto, valve_status, wp_count >= 10, датчик пара валиден, период). Датчик
  пара невалиден при auto → `process_sensor_failed("БК","пара")`. Защита по
  воде: `WaterSensor.avgTemp >= ALARM_WATER_TEMP - 5` → только вверх. Границы
  `[PWM_LOW_VALUE*10, 1023]`, запись `set_pump_pwm(bk_pwm)`.
- Константы `Samovar_ini.h` под `#ifndef`: `BK_WATER_ADJUST_PERIOD_MS 60000`,
  `BK_WATER_DEADBAND 0.2f`, `BK_WATER_PWM_STEP 30`, `BK_STEAM_SETPOINT_MIN 30`,
  `BK_STEAM_SETPOINT_MAX 100` (последние две использует и 9a — 9a объявляет их
  сам, 9b только использует; конфликт исключён, потому что 9a идёт раньше).
- Ручной `watert` при auto: в `tick_apply_pending_water_temp` (Samovar.ino)
  или в `set_water_temp` (BK.h) — выбрать одно место: `set_water_temp` в BK.h,
  так как это владелец состояния; при `bk_water_auto` → выключить, `SendMsg`
  «Вода дефлегматора: ручное управление» (NOTIFY_MSG).
- `waterauto`: `WebServer.ino` разбор и коды 409 по контракту; в loop()
  `tick_apply_pending_water_auto()` → `bk_water_auto_resume()` в BK.h
  (включает с уставкой текущей строки, стартовая точка = текущий `bk_pwm`).
- `/ajax`: два поля в `AjaxTelemetrySnapshot` и `writeAjaxTelemetryFields`.
- `reset_process_state`: сброс трёх переменных состояния (объявить их в BK.h,
  предоставить `bk_reset_water_auto()`; sensorinit.h включён после BK.h).
- Тесты: `smoke_bk_water_auto_step.py` (харнесс шага регулятора: период,
  мёртвая зона, шаг вверх/вниз, границы, приоритет воды, авария по датчику,
  мутации на каждое); `smoke_bk_program_run.py` (харнесс `run_bk_program` +
  переход строк + отказ старта без датчика пара, сценарий «штатный старт»);
  обновить `smoke_bk_full_route.py`; пин действия `waterauto` и полей `/ajax`.

## Задача 9c (страница bk.htm)

- Партиал `data_raw/partials/program_table_dist.htm`: разметка и JS таблицы
  программы (`addLine`, `getProgram`, `set_bgcolor`, кнопки +/−,
  «Установить программу», `SamovarApp.clearProgram`), параметризованный
  пятой колонкой: на bk.htm колонка «Т пара, °C» (input, 0 = вручную), на
  distiller.htm колонки нет. Если партиалы не поддерживают параметры,
  допускается один партиал только для bk.htm без изменения distiller.htm;
  копипаст JS в bk.htm запрещён.
- bk.htm: удалить мёртвые `check_program/calc_program/set_program`, кнопку
  «Очистить программу» перенести во вкладку программы; бейдж «Вода: авто
  78,0 °C» / «Вода: вручную» рядом с ползунком; кнопка «Автомат» (шлёт
  `waterauto=1`), видна при `!bk_water_auto && PowerOn && уставка строки > 0`
  (уставку строки берём из `bk_steam_setpoint`, которое при ручном режиме
  сервер отдаёт как уставку текущей строки, а при отсутствии уставки 0 —
  уточнить с 9b: поле `bk_steam_setpoint` = уставка текущей строки всегда,
  `bk_water_auto` = включён ли автомат). Подсказка «нужен ШИМ-насос» в сборках
  без USE_WATER_PUMP: по существующему признаку страницы (найти, как bk.htm
  сейчас скрывает блок насоса).
- `data_raw/program_bk.txt`: пример с комментариями (40 В/400 Вт, датчик над
  дефлегматором). Добавить в `get_web_interface()` и в COMPRESS/список сборки,
  если примеры туда входят (сверить с program_fruit.txt).
- Пересобрать `data/`, обновить пины u03/u04; браузерные тесты через
  playwright-cli: `test_program_clear_ui_browser.py` (bk.htm уже в списке
  страниц — проверить, что таблица рендерится) и `test_program_calc_browser.py`
  или новый `test_bk_program_ui_browser.py`: пять колонок, ввод строки, POST
  /program с пятым полем, бейдж и кнопка «Автомат» по фикстуре `/ajax`.

## Гейты

- Сборка: `for e in Samovar Samovar_s3 Samovar_no_power Samovar_rmvk Samovar_sem Samovar_lua_mqtt Samovar_alarm_button; do pio run -e $e; done`, подсчёт `warning:` = 0.
- `python3 tools/run_smoke_tests.py` — все зелёные.
- `python3 tools/run_browser_tests.py` — все зелёные (не параллельно со сборкой).
- Ревью-петля до «ошибок и предупреждений нет».
