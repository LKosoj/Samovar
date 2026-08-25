#!/usr/bin/env python3
"""[WP7 п.5] Отдача страницы больше не переключает активный режим прошивки.

Было: send_index_page()/send_mode_specific_htm() писали глобальную Samovar_Mode из
задачи async_tcp (другое ядро, произвольный момент, в т.ч. во время активного
процесса). mode_dispatch_alarm() (SysTicker) выбирает набор аварийных проверок по
Samovar_Mode, а mode_dispatch_loop() - по SamovarStatusInt: открытие "не той" страницы
во время работы молча переключало часть аварийного надзора на чужой режим, пока
рабочий цикл продолжал крутить исходный. Синхронизация с SamSetup.Mode перенесена в
change_samovar_mode() - она уже вызывается ровно в момент старта режима
(mode_registry.h::mode_apply_power_on_command) и при загрузке (Samovar.ino), где
Samovar_Mode заведомо достоверен.

Тест архитектурный (без компиляции - функции дёргают глобальное состояние прошивки,
которое здесь не поднять): вырезает РЕАЛЬНЫЕ тела трёх функций и проверяет структурный
инвариант, который мутационная проверка (см. ниже, в отчёте) подтверждает как ловящий
регресс - "подстрока есть в файле" тут не при чём, проверяется именно тело функции,
найденное балансировкой скобок (extract_function_body из smoke_helpers.py).
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_helpers import extract_function_body, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]
WEB_SERVER = ROOT / "WebServer.ino"
MODE_SWITCH = ROOT / "mode_switch.h"

ASSIGNS_SAMOVAR_MODE = re.compile(r"Samovar_Mode\s*=")


def main() -> int:
    errors: list[str] = []
    source = WEB_SERVER.read_text(encoding="utf-8")
    mode_switch_source = MODE_SWITCH.read_text(encoding="utf-8")

    for signature in (
        "void send_index_page(AsyncWebServerRequest *request)",
        "void send_mode_specific_htm(AsyncWebServerRequest *request, const char *spiffsPath, SAMOVAR_MODE requiredMode)",
    ):
        try:
            body = strip_cpp_comments(extract_function_body(source, signature))
        except ValueError as exc:
            errors.append(f"WebServer.ino: не найдено тело: {exc}")
            continue
        if ASSIGNS_SAMOVAR_MODE.search(body):
            errors.append(
                f"WebServer.ino: {signature.split('(')[0]} снова пишет Samovar_Mode - "
                "запись из веб-задачи (async_tcp, другое ядро) может ударить по "
                "аварийному надзору активного режима (mode_dispatch_alarm читает "
                "Samovar_Mode, mode_dispatch_loop - SamovarStatusInt)"
            )

    try:
        change_body = strip_cpp_comments(
            extract_function_body(mode_switch_source, "void change_samovar_mode()")
        )
    except ValueError as exc:
        errors.append(f"mode_switch.h: не найдено тело change_samovar_mode(): {exc}")
        change_body = ""
    if change_body and "SamSetup.Mode = " not in change_body and "SamSetup.Mode=" not in change_body:
        errors.append(
            "mode_switch.h: change_samovar_mode() больше не синхронизирует "
            "SamSetup.Mode - синхронизация в момент старта режима "
            "(mode_registry.h/Samovar.ino зовут change_samovar_mode()) потерялась, "
            "а без неё вернётся старый способ через веб-обработчики"
        )

    # send_mode_specific_htm обязан сверяться с живым Samovar_Mode (а не с SamSetup.Mode,
    # который без записи из веб-обработчиков может быть устаревшим) при решении о редиректе.
    try:
        htm_body = strip_cpp_comments(
            extract_function_body(
                source,
                "void send_mode_specific_htm(AsyncWebServerRequest *request, const char *spiffsPath, SAMOVAR_MODE requiredMode)",
            )
        )
    except ValueError:
        htm_body = ""
    if htm_body and "Samovar_Mode != requiredMode" not in htm_body:
        errors.append(
            "WebServer.ino: send_mode_specific_htm() больше не сверяет запрошенную "
            "страницу с живым Samovar_Mode - редирект на чужую страницу режима может "
            "снова опираться на устаревший SamSetup.Mode"
        )

    if errors:
        print("mode page-load no-switch smoke failed:")
        for error in errors:
            print(f" - {error}")
        return 1
    print("mode page-load no-switch smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
