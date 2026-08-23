#!/usr/bin/env python3
"""Хелперы, у которых действия обязаны идти парой.

Волна дедупликации свернула повторяющиеся куски в общие хелперы. У выигрыша есть
обратная сторона: раньше пропажа строки ломала одно место, теперь - все точки вызова
разом. Опаснее всего пары «взял замок - отдал замок» и «выставил флаг - обновил его
метку времени»: компилятор молчит (это не неиспользуемая переменная, а логика),
а последствие - зависший навсегда замок или замерший счётчик связи.

Тест не повторяет логику хелперов, а вынимает их тела из исходников и требует, чтобы
обязательные строки стояли в нужном порядке. Добавляя очередной такой хелпер, допишите
сюда кортеж - отдельный тест заводить не нужно.
"""
import sys
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens, strip_cpp_comments

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []

# (файл, сигнатура для поиска тела, зачем это важно, обязательные токены по порядку)
HELPERS = [
    (
        "runtime_helpers.h",
        "inline bool assign_locked_runtime_field(",
        "не отдав runtime_state_lock, вешает ajax-снимок состояния и Lua-мост",
        [
            "runtime_state_lock(timeout)",
            "if (!locked) return false;",
            "destination = value;",
            "runtime_state_unlock(true);",
            "return true;",
        ],
    ),
    (
        "Menu.ino",
        "struct LcdLockGuard",
        "деструктор - единственное место, где отдаётся I2C-замок всех восьми функций меню",
        [
            "acquired(xSemaphoreTake(xI2CSemaphore, timeout) == pdTRUE)",
            "~LcdLockGuard() { if (acquired) xSemaphoreGive(xI2CSemaphore); }",
            "explicit operator bool() const { return acquired; }",
        ],
    ),
    (
        "I2CStepper.h",
        "inline bool set_mixer_pump_target(",
        "не закрыв конфигурацию, устройство остаётся в режиме настройки и не исполняет команды",
        [
            "if (!i2c_stepper_config_begin(*dev)) return false;",
            "i2c_stepper_config_end(*dev);",
            "return ok;",
        ],
    ),
    (
        "I2CStepper.h",
        "inline bool set_i2c_rele_state(",
        "не закрыв конфигурацию, устройство остаётся в режиме настройки и не исполняет команды",
        [
            "if (!i2c_stepper_config_begin(*dev)) return false;",
            "i2c_stepper_config_end(*dev);",
            "return ok;",
        ],
    ),
    (
        "mod_rmv.ino",
        "static void rmvk_mark_online()",
        "без метки времени признак «регулятор на связи» больше не обновляется",
        [
            "reg_online = true;",
            "last_reg_online = millis();",
        ],
    ),
]


def main() -> int:
    for file_name, signature, why, tokens in HELPERS:
        path = ROOT / file_name
        if not path.exists():
            errors.append(f"{file_name} not found")
            continue
        # strip_cpp_comments до поиска тела: закомментированная строка кода всё ещё
        # содержит текст токена как подстроку, поэтому без вырезания комментариев тест
        # пропустил бы «// xSemaphoreGive(...)» - замок навсегда занят, а тест зелёный.
        source = strip_cpp_comments(path.read_text(encoding="utf-8", errors="ignore"))
        try:
            body = extract_function_body(source, signature)
        except ValueError as exc:
            errors.append(f"{file_name}: {exc} ({why})")
            continue
        require_ordered_tokens(f"{file_name} {signature.strip()} [{why}]", body, tokens, errors)

    if errors:
        print("helper paired actions smoke failed:")
        for error in errors:
            print(f" - {error}")
        return 1
    print("helper paired actions smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
