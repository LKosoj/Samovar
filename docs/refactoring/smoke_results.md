# Финальные smoke-результаты

Дата: 2026-03-15

Контекст: финальная верификация после завершения фаз 8-9 structural refactor, удаления `Menu.ino`, выноса menu/frontend логики в модульные headers/`common.js` и cleanup legacy/shim-остатков.

## Сборка

- Команда: `pio run`
- Ожидаемый gate: полная сборка прошивки `Samovar`
- Фактический результат: passed
- Evidence:
  - `RAM: 18.3% (59904 bytes from 327680 bytes)`
  - `Flash: 70.1% (1148905 bytes from 1638400 bytes)`
  - PlatformIO завершил сборку статусом `[SUCCESS]`

## Автоматизированные smoke-проверки

- Команда: `python3 -m unittest tests/test_final_smoke_artifacts.py tests/test_ui_menu_integration_behavior.py tests/test_legacy_cleanup_phase9.py tests/test_ui_web_routes_setup_save.py`
- Ожидаемый gate: menu/frontend/cleanup smoke без legacy-регрессий
- Проверяемые точки:
  - `tests/test_final_smoke_artifacts.py`: синтаксическая валидность inline-script блоков HTML после template-подстановки и наличие этого отчёта
  - `tests/test_ui_menu_integration_behavior.py`: интеграция `ui/menu/screens.h` + `ui/menu/input.h` + `ui/menu/actions.h`, навигация и режимные menu actions
  - `tests/test_legacy_cleanup_phase9.py`: отсутствие zero-byte production sources, empty legacy-shell и compatibility/proxy API
  - `tests/test_ui_web_routes_setup_save.py`: сохранение web setup/process contracts
- Фактический результат: passed

## Ручные browser smoke-сценарии

Локальный сервер:

- Команда: `python3 -m http.server 18080 --directory data`
- Назначение: отдать статические `data/*.htm` и `common.js` для browser-smoke

Browser automation:

- Команда: `PLAYWRIGHT_MCP_SANDBOX=false playwright-cli open http://127.0.0.1:18080/index.htm`
- Причина флага: в root-окружении Chrome не стартует с включённым sandbox

### Сценарий 1: `index.htm`

- Команды:
  - `PLAYWRIGHT_MCP_SANDBOX=false playwright-cli open http://127.0.0.1:18080/index.htm`
  - `PLAYWRIGHT_MCP_SANDBOX=false playwright-cli dialog-accept`
  - `PLAYWRIGHT_MCP_SANDBOX=false playwright-cli eval "() => document.title"`
  - `PLAYWRIGHT_MCP_SANDBOX=false playwright-cli eval "() => Array.from(document.querySelectorAll('input.tablinks')).map(el => el.value).join('|')"`
- Результат:
  - страница открылась
  - `document.title === "Самовар"`
  - вкладки присутствуют: `Ректификация|Программа|Дополнительно|Внешний насос`
- Наблюдения:
  - при открытии появился dialog `Program error!`
  - в console локального static-server smoke были ошибки `404 /ajax`

### Сценарий 2: `setup.htm`

- Команды:
  - `PLAYWRIGHT_MCP_SANDBOX=false playwright-cli goto http://127.0.0.1:18080/setup.htm`
  - `PLAYWRIGHT_MCP_SANDBOX=false playwright-cli eval "() => document.title"`
  - `PLAYWRIGHT_MCP_SANDBOX=false playwright-cli eval "() => Array.from(document.querySelectorAll('input.tablinks')).map(el => el.value).join('|')"`
- Результат:
  - страница открылась
  - `document.title === "Самовар"`
  - вкладки присутствуют: `Ректификация|Программа|Дополнительно|Внешний насос`
- Наблюдения:
  - console: `0 errors, 5 warnings`
  - warnings связаны с сырыми template placeholders `%SteamColor%/%PipeColor%/...` при статической раздаче без серверной подстановки

### Сценарий 3: `program.htm`

- Команды:
  - `PLAYWRIGHT_MCP_SANDBOX=false playwright-cli goto http://127.0.0.1:18080/program.htm`
  - `PLAYWRIGHT_MCP_SANDBOX=false playwright-cli eval "() => document.title"`
  - `PLAYWRIGHT_MCP_SANDBOX=false playwright-cli eval "() => Array.from(document.querySelectorAll('input.button')).map(el => el.value).slice(0,8).join('|')"`
- Результат:
  - страница открылась после устранения синтаксических хвостов в inline-script
  - `document.title === "Самовар"`
  - ключевые кнопки доступны: `ПРИМЕНИТЬ РЕКОМЕНДАЦИИ|Сохранить расчет||Установить программу|На главную`
- Наблюдения:
  - console ошибки связаны с отсутствием backend endpoint `/ajax_col_params` на локальном static-server и JSON parse на HTML 404-ответе

## Ограничения

- Browser-smoke выполнялся на локальном `http.server`, а не на живом ESP32 backend. Поэтому XHR к `/ajax`, `/ajax_col_params` и template placeholders вида `%SteamColor%` не разрешаются и дают ожидаемые ограничения smoke-среды.
- Ручной hardware smoke дисплейного меню на реальном LCD/encoder в этом окружении недоступен. Поведение menu-layer подтверждено автоматизированным harness-тестом `tests/test_ui_menu_integration_behavior.py`.
- Этот документ фиксирует фактически выполненные проверки и ограничения среды; он не имитирует отсутствующий аппаратный стенд.
