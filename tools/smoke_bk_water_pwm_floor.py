#!/usr/bin/env python3
"""Нижняя граница ШИМ насоса воды дефлегматора БК - согласована в двух местах.

Задача A3 (docs/plans/2026-09-02-bk-implementation-plan.md, пункт 5):
ползунок ШИМ насоса воды на bk.htm имеет min="%PWM_LV%" (сервер подставляет
PWM_LOW_VALUE * 10), но текстовое поле рядом (PWMt) раньше валидировалось в
changetxtpwm() с хардкодом min: 0 - пользователь мог вписать число ниже
рабочего порога, оно уходило на сервер через watert=, и при работающем нагреве
БК молча душило подачу воды в дефлегматор.

Два места обязаны быть согласованы:
  1. data_raw/bk.htm::changetxtpwm() - нижняя граница текстового поля читается
     из атрибута min самого ползунка (PWM), а не из хардкода.
  2. WebServer.ino::web_command(), ветка action == "watert" (исполнение
     команды, не разбор параметра) - серверный отказ 409 PWM_TOO_LOW для ЛЮБОГО
     клиента (не только браузерной страницы), когда Samovar_Mode == БК,
     PowerOn и waterPwm ниже PWM_LOW_VALUE * 10.

Как и smoke_bk_power_floor.py - это не компилируемый харнесс (web_command живёт
внутри AsyncWebServerRequest и десятков глобалов, городить g++-заглушки ради
одного if избыточно), а статический пин: extract_function_body/
extract_braced_block_after/require_ordered_tokens те же, что уже использует
smoke_api_routes.py для этой же функции.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_helpers import extract_braced_block_after, extract_function_body, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]
WEB_SERVER = ROOT / "WebServer.ino"
BK_PAGE = ROOT / "data_raw" / "bk.htm"


def main() -> int:
    errors: list[str] = []

    if not WEB_SERVER.exists():
        errors.append("WebServer.ino: файл не найден")
    if not BK_PAGE.exists():
        errors.append("data_raw/bk.htm: файл не найден")
    if errors:
        for error in errors:
            print(f" - {error}")
        return 1

    web_text = WEB_SERVER.read_text(encoding="utf-8", errors="ignore")

    try:
        command_body = extract_function_body(
            web_text, "void web_command(AsyncWebServerRequest *request)"
        )
    except ValueError as exc:
        errors.append(str(exc))
        command_body = ""

    watert_body = ""
    if command_body:
        # "action == \"watert\"" встречается в web_command дважды: сперва в
        # разборе параметра (parseResult = parse_control_water_pwm(...)), затем
        # в ветке исполнения команды - именно вторую мы правили. Якорь
        # "String commandKey = action;" лежит строго между ними (один раз на
        # функцию, это же проверяет smoke_api_routes.py) - им и отделяем разбор
        # от исполнения, иначе offset=0 молча найдёт не ту ветку.
        dispatch_end = command_body.find("String commandKey = action;")
        if dispatch_end < 0:
            errors.append(
                "web_command: не найден якорь 'String commandKey = action;' - "
                "нечем отделить разбор параметра watert от исполнения команды"
            )
        else:
            try:
                watert_body, _ = extract_braced_block_after(
                    command_body, 'action == "watert"', offset=dispatch_end
                )
            except ValueError as exc:
                errors.append(str(exc))

    if watert_body:
        require_ordered_tokens(
            "/command watert rejects sub-floor PWM while BK is heating",
            watert_body,
            [
                "Samovar_Mode == SAMOVAR_BK_MODE",
                "PowerOn",
                "waterPwm < PWM_LOW_VALUE * 10",
                'send_web_command_response(request, 409, "PWM_TOO_LOW")',
                "return;",
                "queue_pending_value(pending_water_temp_flag, pending_water_temp_value, waterPwm)",
            ],
            errors,
        )

        # Порядок токенов сам по себе не ловит регрессию "проверка есть, но
        # return не внутри if, а всегда выполняется" - извлекаем именно
        # вложенный блок этого if (как smoke_api_routes.py делает для
        # rescands_active_body) и убеждаемся, что 409-ответ и return лежат
        # внутри него, а постановка в очередь - уже после закрывающей скобки.
        try:
            floor_if_body, floor_if_end = extract_braced_block_after(
                watert_body,
                "if (Samovar_Mode == SAMOVAR_BK_MODE && PowerOn && waterPwm < PWM_LOW_VALUE * 10)",
            )
            if 'send_web_command_response(request, 409, "PWM_TOO_LOW")' not in floor_if_body:
                errors.append(
                    "/command watert floor-check body does not send 409 PWM_TOO_LOW"
                )
            if "return;" not in floor_if_body:
                errors.append(
                    "/command watert floor-check body does not return before queueing"
                )
            if "queue_pending_value(pending_water_temp_flag" in floor_if_body:
                errors.append(
                    "/command watert floor-check body still queues the pending value"
                )
            after_floor_check = watert_body[floor_if_end:]
            if "queue_pending_value(pending_water_temp_flag, pending_water_temp_value, waterPwm)" not in after_floor_check:
                errors.append(
                    "/command watert queues pending value before/without the floor check "
                    "(порог должен быть безусловной проверкой ДО постановки в очередь)"
                )
        except ValueError as exc:
            errors.append(str(exc))


    # --- bk.htm: changetxtpwm() читает нижнюю границу из атрибута min ползунка ---
    bk_text = BK_PAGE.read_text(encoding="utf-8", errors="ignore")
    try:
        changetxtpwm_body = extract_function_body(bk_text, "function changetxtpwm ()")
    except ValueError as exc:
        errors.append(str(exc))
        changetxtpwm_body = ""

    if changetxtpwm_body:
        if "min: 0" in changetxtpwm_body or "min:0" in changetxtpwm_body:
            errors.append(
                "data_raw/bk.htm: changetxtpwm() снова хардкодит min:0 - "
                "нижняя граница текстового поля разойдётся с ползунком (PWM_LV)"
            )
        if "document.getElementById('PWM').min" not in changetxtpwm_body:
            errors.append(
                "data_raw/bk.htm: changetxtpwm() не читает нижнюю границу из "
                "атрибута min ползунка PWM"
            )

    if errors:
        print("BK water PWM floor smoke failed:")
        for error in errors:
            print(f" - {error}")
        return 1
    print("BK water PWM floor smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
