#!/usr/bin/env python3
"""T30: сторож основного loop() (esp_task_wdt / enableLoopWDT).

Обязательный ПРЕДварительный аудит (см. отчёт T30a/T30) подтвердил: единственная
операция, достижимая из loop(), которая структурно может занять больше
LOOP_WDT_TIMEOUT_S секунд - это ArduinoOTA::_runUpdate() (вендоренная библиотека,
framework-arduinoespressif32/libraries/ArduinoOTA) - она получает и пишет в flash
ВЕСЬ образ прошивки ОДНИМ синхронным вызовом изнутри ArduinoOTA.handle() (вызывается
из tick_ota() в loop()), без единой точки, куда можно вставить feedLoopWDT() (чужой
код, `while` внутри библиотеки нам не принадлежит). Поэтому вместо честной пометки
"сторож не включать" (что оставило бы T30 невыполненным целиком) сторож loop()
включается, но на время OTA-сессии выключается отдельно - через уже существующие
колбэки ArduinoOTA.onStart()/onEnd()/onError() (там же, где ota_running переключает
Blynk/MQTT). Все остальные операции reachable из loop() (7 тиков режимов, Blynk.run()
при живом соединении, I2C/степпер/насос, SPIFFS/event log, локи) подтверждены
аудитом уложенными в 10 с - см. таблицу в отчёте.

Второе обязательное уточнение, найденное этим же аудитом: в Samovar.h уже есть
отладочный рубильник `//#define __SAMOVAR_NOT_USE_WDT` (используется
setup_disable_watchdogs(), раньше по setup()) - предназначен для работы под JTAG,
где сторож ложно сработал бы на точке останова. Без защиты этим же макросом новый
код в конце setup() молча включил бы сторож обратно сразу после того, как
разработчик его выключил - тест это тоже фиксирует.

Тест проверяет РЕАЛЬНЫЙ исходник (Samovar.ino) структурно: без компиляции, но с
мутациями на СОБРАННОМ тексте (как smoke_lock_order.py и другие проверки порядка
вызовов в этом репозитории) - see require_ordered_tokens/extract_function_body.
"""
import sys
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []

samovar_raw = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
samovar_text = strip_cpp_comments(samovar_raw)

# ==== 1. LOOP_WDT_TIMEOUT_S - именованная константа, а не голое число ==========
if "constexpr uint32_t LOOP_WDT_TIMEOUT_S = 10;" not in samovar_text:
    errors.append(
        "Samovar.ino: не найдена constexpr uint32_t LOOP_WDT_TIMEOUT_S = 10; "
        "(порог сторожа должен быть именованной константой, а не голым числом "
        "в вызове esp_task_wdt_init)"
    )

# ==== 2. setup(): порядок и положение вызовов =================================
try:
    setup_body = extract_function_body(samovar_text, "void setup() {")
except ValueError as error:
    print(f"FAIL: {error}", file=sys.stderr)
    sys.exit(1)

# 2a. init_power_outputs_safe_off() - ПЕРВАЯ исполняемая строка setup() (нагрев
# должен стать безопасным раньше вообще любого другого кода - см. её же комментарий
# в файле про strapping-вывод RELE_CHANNEL2).
setup_body_stripped = setup_body.lstrip()
if not setup_body_stripped.startswith("init_power_outputs_safe_off();"):
    errors.append(
        "Samovar.ino: init_power_outputs_safe_off() должна быть ПЕРВОЙ строкой "
        "setup() - иначе есть окно между сбросом и переводом реле в безопасное "
        "состояние"
    )

# 2b. Сторож - в САМОМ КОНЦЕ setup(): и esp_task_wdt_init(), и enableLoopWDT()
# обязаны идти ПОСЛЕ всей остальной разовой инициализации (маркер -
# state_snapshot_report_pending(), последний вызов перед сторожем по текущему
# исходнику) и быть последними исполняемыми строками перед закрывающей скобкой.
require_ordered_tokens(
    "setup",
    setup_body,
    [
        "init_power_outputs_safe_off();",
        # Вся содержательная инициализация (WiFi, задачи, NVS, OTA-колбэки) обязана
        # идти МЕЖДУ этими двумя точками - esp_task_wdt_init() не должна оказаться
        # раньше state_snapshot_report_pending() (иначе сторож считает и время
        # разовой инициализации, а не только одну итерацию loop()).
        "state_snapshot_report_pending();",
        "esp_task_wdt_init(LOOP_WDT_TIMEOUT_S, true);",
        "enableLoopWDT();",
    ],
    errors,
)

# 2c. После enableLoopWDT() в setup() не должно остаться содержательного кода -
# "в конце" означает буквально последние строки, а не "где-то после середины".
setup_body_rstripped = setup_body.rstrip()
tail_marker = "enableLoopWDT();"
tail_index = setup_body_rstripped.rfind(tail_marker)
if tail_index < 0:
    errors.append("Samovar.ino: enableLoopWDT() не найдена в setup()")
else:
    trailing = setup_body_rstripped[tail_index + len(tail_marker):].strip()
    # Единственное, чему разрешено остаться после enableLoopWDT() - закрывающий
    # #endif охранного #ifndef __SAMOVAR_NOT_USE_WDT (см. пункт 3 ниже).
    if trailing not in ("", "#endif"):
        errors.append(
            f"Samovar.ino: после enableLoopWDT() в setup() остался код "
            f"({trailing!r}) - сторож должен включаться последним действием setup()"
        )

# ==== 3. Не ломает существующий отладочный рубильник __SAMOVAR_NOT_USE_WDT =====
# setup_disable_watchdogs() (раньше по setup()) под этим же макросом выключает все
# сторожи для отладки под JTAG - новый код обязан быть под тем же #ifndef, иначе
# молча включает сторож обратно.
guard_index = samovar_text.find("#ifndef __SAMOVAR_NOT_USE_WDT")
init_call_index = samovar_text.find("esp_task_wdt_init(LOOP_WDT_TIMEOUT_S, true);")
enable_call_index = samovar_text.find("enableLoopWDT();", init_call_index if init_call_index >= 0 else 0)
endif_index = samovar_text.find("#endif", enable_call_index if enable_call_index >= 0 else 0)
if not (0 <= guard_index < init_call_index < enable_call_index < endif_index):
    errors.append(
        "Samovar.ino: esp_task_wdt_init(LOOP_WDT_TIMEOUT_S, true) и enableLoopWDT() "
        "должны лежать МЕЖДУ #ifndef __SAMOVAR_NOT_USE_WDT и его #endif - иначе "
        "существующий отладочный рубильник (Samovar.h: //#define __SAMOVAR_NOT_USE_WDT, "
        "используется setup_disable_watchdogs()) перестаёт работать"
    )

# ==== 4. OTA-сессия выключает сторож на время (ArduinoOTA::_runUpdate() блокирует
#         на весь образ прошивки одним вызовом - см. заголовок файла) ===========
for signature, expected_call, description in [
    ("ota_running = true;", "disableLoopWDT();", "onStart()"),
    ("ota_running = false;", "enableLoopWDT();", None),  # проверяется дважды ниже
]:
    pass  # обычный ordered_tokens не различит два разных ota_running=false, делаем вручную

onstart_index = samovar_text.find("ArduinoOTA.onStart([]() {")
onend_index = samovar_text.find("ArduinoOTA.onEnd([]() {")
onerror_index = samovar_text.find("ArduinoOTA.onError([](ota_error_t error) {")
if onstart_index < 0 or onend_index < 0 or onerror_index < 0:
    errors.append("Samovar.ino: не найдены ArduinoOTA.onStart/onEnd/onError")
else:
    onstart_body = samovar_text[onstart_index:onend_index]
    onend_body = samovar_text[onend_index:onerror_index]
    onerror_body = samovar_text[onerror_index:onerror_index + 600]
    if "ota_running = true;" not in onstart_body or "disableLoopWDT();" not in onstart_body:
        errors.append(
            "Samovar.ino: ArduinoOTA.onStart() обязан выключать сторож loop() "
            "(disableLoopWDT()) вместе с установкой ota_running = true - иначе "
            "первая же OTA-передача перезагрузит устройство через LOOP_WDT_TIMEOUT_S секунд"
        )
    elif onstart_body.find("ota_running = true;") > onstart_body.find("disableLoopWDT();"):
        errors.append(
            "Samovar.ino: в ArduinoOTA.onStart() disableLoopWDT() должна идти после "
            "ota_running = true (порядок не критичен функционально, но фиксируем как "
            "в исходнике)"
        )
    if "ota_running = false;" not in onend_body or "enableLoopWDT();" not in onend_body:
        errors.append(
            "Samovar.ino: ArduinoOTA.onEnd() обязан включать сторож loop() обратно "
            "(enableLoopWDT()) - иначе после OTA без перезагрузки (_rebootOnSuccess "
            "выключен) loop() остаётся без защиты навсегда"
        )
    if "ota_running = false;" not in onerror_body or "enableLoopWDT();" not in onerror_body:
        errors.append(
            "Samovar.ino: ArduinoOTA.onError() обязан включать сторож loop() обратно "
            "(enableLoopWDT()) - неудачная OTA НЕ перезагружает устройство "
            "(ArduinoOTA::_runUpdate() при ошибке просто возвращается), поэтому без "
            "этого вызова loop() остаётся без сторожа до следующей ручной перезагрузки"
        )

if errors:
    print("Loop watchdog setup smoke check failed:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print(
    "Loop watchdog setup smoke check passed: LOOP_WDT_TIMEOUT_S - именованная "
    "константа, esp_task_wdt_init/enableLoopWDT в самом конце setup() после "
    "init_power_outputs_safe_off(), отладочный рубильник __SAMOVAR_NOT_USE_WDT не "
    "сломан, OTA-сессия (onStart/onEnd/onError) корректно выключает и включает "
    "сторож обратно"
)


# ==== ЧАСТЬ 2: мутации (ровно те 3, что требует ТЗ T30) ========================

def run_check() -> tuple[bool, list[str]]:
    """Повторяет проверки пункта 2b/1 над ТЕКУЩИМ содержимым файла на диске."""
    text = strip_cpp_comments((ROOT / "Samovar.ino").read_text(encoding="utf-8"))
    local_errors: list[str] = []
    if "constexpr uint32_t LOOP_WDT_TIMEOUT_S = 10;" not in text:
        local_errors.append("missing named constant")
    try:
        body = extract_function_body(text, "void setup() {")
    except ValueError as error:
        return False, [str(error)]
    if not body.lstrip().startswith("init_power_outputs_safe_off();"):
        local_errors.append("init_power_outputs_safe_off() not first")
    require_ordered_tokens(
        "setup",
        body,
        [
            "init_power_outputs_safe_off();",
            "state_snapshot_report_pending();",
            "esp_task_wdt_init(LOOP_WDT_TIMEOUT_S, true);",
            "enableLoopWDT();",
        ],
        local_errors,
    )
    return len(local_errors) == 0, local_errors


def require_mutation(old: str, new: str, description: str) -> bool:
    original = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
    if old not in original:
        print(f"FAIL: cannot construct mutation for {description!r} - anchor text not found", file=sys.stderr)
        return False
    mutated = original.replace(old, new, 1)
    (ROOT / "Samovar.ino").write_text(mutated, encoding="utf-8")
    try:
        ok, mutation_errors = run_check()
    finally:
        (ROOT / "Samovar.ino").write_text(original, encoding="utf-8")
    restored = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
    if restored != original:
        print(f"FAIL: Samovar.ino was not byte-for-byte restored after mutation {description!r}", file=sys.stderr)
        return False
    if ok:
        print(f"FAIL: mutation survived ({description})", file=sys.stderr)
        return False
    return True


def main() -> int:
    mutations = [
        (
            "  esp_task_wdt_init(LOOP_WDT_TIMEOUT_S, true);\n  enableLoopWDT();\n",
            "  esp_task_wdt_init(LOOP_WDT_TIMEOUT_S, true);\n",
            "remove enableLoopWDT() call",
        ),
        (
            "esp_task_wdt_init(LOOP_WDT_TIMEOUT_S, true);",
            "esp_task_wdt_init(10, true);",
            "replace named constant with a bare literal at the call site",
        ),
        (
            "  init_power_outputs_safe_off();",
            "  esp_task_wdt_init(LOOP_WDT_TIMEOUT_S, true);\n  enableLoopWDT();\n  init_power_outputs_safe_off();",
            "move watchdog calls to the start of setup()",
        ),
    ]
    for old, new, description in mutations:
        if not require_mutation(old, new, description):
            return 1
    print(
        "Loop watchdog setup mutations were rejected as expected: removing "
        "enableLoopWDT(), inlining the threshold as a bare literal, and moving the "
        "calls to the start of setup() are all caught - Samovar.ino restored "
        "byte-for-byte after each"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
