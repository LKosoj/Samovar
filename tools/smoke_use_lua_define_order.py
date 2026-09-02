#!/usr/bin/env python3
"""
Удерживает ПОРЯДОК: трансляция `SAMOVAR_BUILD_LUA -> #define USE_LUA`
(сейчас в Samovar_ini.h) обязана происходить РАНЬШЕ первого места, где
Samovar.h проверяет `#ifdef USE_LUA`, чтобы объявить `xLuaSemaphore`.

Почему это хрупко: раньше эта же трансляция стояла в Samovar.h НИЖЕ строки,
объявляющей xLuaSemaphore под `#ifdef USE_LUA` - из-за этого окружение
Samovar_lua_mqtt не собиралось ("'xLuaSemaphore' was not declared in this
scope"). Перенос трансляции в Samovar_ini.h (который Samovar.h подключает
задолго до xLuaSemaphore, строка `#include "Samovar_ini.h"`) это исправил,
но ничем не удержан: удаление строки, перенос её обратно ниже xLuaSemaphore,
обёртывание блока в лишнее условие или переименование макроса сломает сборку
Samovar_lua_mqtt молча - ни один другой тест этого не заметит (окружение
просто не попадает в обычный smoke-прогон).

СТАРАЯ версия этого теста вырезала блок трансляции регулярным выражением и
сравнивала позиции ИЗВЛЕЧЁННЫХ фрагментов - это тавтология: если блок снаружи
обернуть в `#if НЕОПРЕДЕЛЁННЫЙ_ФЛАГ` (нигде не определённый), регулярка всё
равно найдёт и извлечёт вложенную тройку строк, а обёртку - потерянную при
извлечении - никто не проверит. Тест бы печатал успех, хотя USE_LUA в реальной
сборке никогда бы не определился.

НОВАЯ версия доказывает поведение НАСТОЯЩИМ препроцессором (cpp) на настоящих
Samovar_ini.h/Samovar.h, а не на вырезанных фрагментах:
  1. Прогоняет cpp с -DSAMOVAR_BUILD_LUA и без него и проверяет: с флагом
     строка `SemaphoreHandle_t xLuaSemaphore = NULL;` (настоящая строка из
     Samovar.h, не выдуманный маркер) обязана попасть в результат
     препроцессирования; без флага - не попасть.
  2. Мутационная самопроверка: 4 варианта поломки (удаление блока трансляции;
     перенос его в Samovar.h НИЖЕ xLuaSemaphore; обёртывание в `#if` с
     заведомо неопределённым флагом; переименование USE_LUA в другое имя) -
     каждый обязан заставить xLuaSemaphore исчезнуть из результата ДАЖЕ при
     -DSAMOVAR_BUILD_LUA. Мутации накладываются на копии текста В ПАМЯТИ,
     реальные файлы прошивки не трогаются.

Честно о границах проверки (см. также docstring - что тест НЕ доказывает):
  - Samovar.h подключает библиотеки Arduino/сторонние (<OneWire.h>,
    <ESPAsyncWebServer.h> и т.п.), которых на машине сборки теста нет. Для
    ВОПРОСА "к какому моменту определён USE_LUA" их содержимое не нужно -
    препроцессору важны только директивы (#include/#ifdef/#define), а не
    объявления внутри библиотек - поэтому они заменены на ПУСТЫЕ заглушки
    (см. _STUB_INCLUDE_NAMES).
  - Samovar.h - 800+ строк и дальше (после xLuaSemaphore) подключает ещё
    много всего (LittleFS/SPIFFS, GyverStepper2, PCF8575 и т.д.), что для
    ЭТОГО инварианта не имеет значения и штатно недоступно тестовому
    окружению. Поэтому в cpp передаётся РЕАЛЬНЫЙ текст Samovar.h, обрезанный
    сразу после блока xLuaSemaphore (`_slice_after_checkpoint`), с
    компенсирующими #endif на конец - ровно по числу директив #if/#ifdef/
    #ifndef этого файла, оставшихся открытыми на момент среза (в первую
    очередь это его собственный include guard `#ifndef __SAMOVAR_H_`).
    Всё ДО среза - дословный текст настоящего файла, включая порядок
    #include "Samovar_ini.h" и весь путь до xLuaSemaphore.
  - Samovar_pin.h содержит `#if not defined(BOARD)` - альтернативный токен
    "not" распознаётся препроцессором только в режиме C++, поэтому cpp
    запускается с `-x c++` (эти файлы и так компилируются как C++).
  - Это ДОКАЗЫВАЕТ: при реальном порядке файлов и реальном содержимом от
    начала Samovar.h до конца блока xLuaSemaphore, флаг SAMOVAR_BUILD_LUA
    действительно управляет тем, определён ли USE_LUA к моменту проверки.
    Это НЕ проверяет побочные эффекты USE_LUA дальше по файлу (остальные
    ifdef USE_LUA в Samovar.ino/WebServer.ino и т.п.) - для них нужна была бы
    полная сборка окружения Samovar_lua_mqtt через PlatformIO.
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TRANSITION_BLOCK = "#ifdef SAMOVAR_BUILD_LUA\n#define USE_LUA\n#endif"
CHECKPOINT_BLOCK = (
    "#ifdef USE_LUA\n"
    "SemaphoreHandle_t xLuaSemaphore = NULL;\n"
    "StaticSemaphore_t xLuaSemaphoreBuffer;\n"
    "#endif"
)
XLUA_DECLARATION = "SemaphoreHandle_t xLuaSemaphore = NULL;"

# Библиотеки, которые #include'ит Samovar.h/Samovar_ini.h до конца блока
# xLuaSemaphore. Их РЕАЛЬНОГО содержимого на машине сборки теста нет и для
# вопроса "к какому моменту определён USE_LUA" оно не требуется - препроцессору
# нужны только директивы, а не объявления внутри библиотек.
_STUB_INCLUDE_NAMES = (
    "Arduino.h", "OneWire.h", "DallasTemperature.h", "ESPAsyncWebServer.h",
    "ESP32Servo.h", "PID_v1.h", "PID_AutoTune_v0.h", "iarduino_I2C_connect.h",
    "GyverEncoder.h", "GyverButton.h", "ESPmDNS.h", "LiquidMenu.h", "WebSerial.h",
)

# Реальные соседние заголовки, которые Samovar.h подключает ДО конца блока
# xLuaSemaphore и которые сами по себе не участвуют в трансляции USE_LUA -
# берутся с диска как есть, мутировать их незачем.
_SUPPORT_HEADER_NAMES = ("user_config_override.h", "Samovar_pin.h", "program_types.h")

_CONDITIONAL_OPEN_RE = re.compile(r"#\s*(if|ifdef|ifndef)\b")
_CONDITIONAL_CLOSE_RE = re.compile(r"#\s*endif\b")


def _close_dangling_conditionals(text: str) -> str:
    """Добавляет в конец text ровно столько #endif, сколько нужно, чтобы
    закрыть #if/#ifdef/#ifndef этого же текста, оставшиеся без пары - мы режем
    настоящий Samovar.h посередине, поэтому его собственный include guard
    формально остаётся не закрытым."""
    depth = 0
    for line in text.splitlines():
        stripped = line.strip()
        if _CONDITIONAL_OPEN_RE.match(stripped):
            depth += 1
        elif _CONDITIONAL_CLOSE_RE.match(stripped):
            depth -= 1
    return text + ("\n#endif" * max(depth, 0)) + "\n"


def slice_samovar_h_after_checkpoint(samovar_text: str) -> str:
    """Берёт дословный текст Samovar.h от начала до конца блока xLuaSemaphore
    (включительно) и закрывает оставшиеся открытыми условия. Всё, что дальше
    по файлу (LittleFS, SPIFFS, GyverStepper2, ...), для этого инварианта не
    нужно и требует библиотек, недоступных тестовому окружению."""
    idx = samovar_text.find(CHECKPOINT_BLOCK)
    if idx < 0:
        raise ValueError(
            "в Samovar.h не найден блок `#ifdef USE_LUA / SemaphoreHandle_t xLuaSemaphore "
            "= NULL; / StaticSemaphore_t xLuaSemaphoreBuffer; / #endif` - объявление "
            "семафора переписали или удалили"
        )
    return _close_dangling_conditionals(samovar_text[: idx + len(CHECKPOINT_BLOCK)])


def _build_stub_includes(stub_dir: Path) -> None:
    for name in _STUB_INCLUDE_NAMES:
        (stub_dir / name).write_text("", encoding="utf-8")


def preprocess(ini_text: str, samovar_slice_text: str, *, build_lua: bool) -> str:
    """Прогоняет настоящий `cpp` над переданным содержимым Samovar_ini.h и
    (уже обрезанного до конца блока xLuaSemaphore) Samovar.h - содержимое
    может быть как реальным, так и мутированной копией в памяти; на диск
    пишутся только временные файлы. Возвращает текст после препроцессора."""
    with tempfile.TemporaryDirectory(prefix="samovar-use-lua-order-") as tmp:
        tmp_path = Path(tmp)
        stub_dir = tmp_path / "stub_includes"
        stub_dir.mkdir()
        _build_stub_includes(stub_dir)

        (tmp_path / "Samovar_ini.h").write_text(ini_text, encoding="utf-8")
        (tmp_path / "Samovar.h").write_text(samovar_slice_text, encoding="utf-8")
        for name in _SUPPORT_HEADER_NAMES:
            shutil.copyfile(ROOT / name, tmp_path / name)

        cmd = [
            "cpp", "-x", "c++", "-P", "-nostdinc", "-DESP32",
            "-I", str(stub_dir), "-I", str(tmp_path),
        ]
        if build_lua:
            cmd.append("-DSAMOVAR_BUILD_LUA")
        cmd.append(str(tmp_path / "Samovar.h"))

        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"cpp завершился с ошибкой (build_lua={build_lua}): {result.stderr}")
        return result.stdout


def xlua_declared(preprocessed_text: str) -> bool:
    return XLUA_DECLARATION in preprocessed_text


def check_mutation(name: str, mutated_ini: str, mutated_samovar_slice: str) -> list[str]:
    """С -DSAMOVAR_BUILD_LUA даже после мутации xLuaSemaphore ОБЯЗАН исчезнуть
    из результата - иначе поломка молча пройдёт мимо теста."""
    try:
        output = preprocess(mutated_ini, mutated_samovar_slice, build_lua=True)
    except RuntimeError as error:
        return [f"мутация «{name}»: cpp неожиданно упал: {error}"]
    if xlua_declared(output):
        return [
            f"мутация «{name}» пережита - xLuaSemaphore всё равно попадает в результат "
            "препроцессора даже с -DSAMOVAR_BUILD_LUA, эта поломка осталась бы незамеченной"
        ]
    return []


def main() -> int:
    if shutil.which("cpp") is None:
        print("FAIL: утилита cpp не найдена в PATH, не могу доказать поведение препроцессора", file=sys.stderr)
        return 1

    for name in ("Samovar_ini.h", "Samovar.h", *_SUPPORT_HEADER_NAMES):
        if not (ROOT / name).exists():
            print(f"FAIL: {ROOT / name} not found", file=sys.stderr)
            return 1

    ini_text = (ROOT / "Samovar_ini.h").read_text(encoding="utf-8")
    samovar_text = (ROOT / "Samovar.h").read_text(encoding="utf-8")

    if TRANSITION_BLOCK not in ini_text:
        print(
            f"FAIL: блок `#ifdef SAMOVAR_BUILD_LUA / #define USE_LUA / #endif` не найден "
            f"в Samovar_ini.h дословно - его удалили, переместили или переформатировали "
            f"(anchor: {TRANSITION_BLOCK!r})",
            file=sys.stderr,
        )
        return 1

    try:
        samovar_slice = slice_samovar_h_after_checkpoint(samovar_text)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    errors: list[str] = []

    try:
        with_flag = preprocess(ini_text, samovar_slice, build_lua=True)
    except RuntimeError as error:
        errors.append(str(error))
    else:
        if not xlua_declared(with_flag):
            errors.append(
                "с флагом -DSAMOVAR_BUILD_LUA объявление xLuaSemaphore НЕ попало в результат "
                "препроцессора Samovar.h - окружение Samovar_lua_mqtt не соберётся "
                "(\"'xLuaSemaphore' was not declared in this scope\")"
            )

    try:
        without_flag = preprocess(ini_text, samovar_slice, build_lua=False)
    except RuntimeError as error:
        errors.append(str(error))
    else:
        if xlua_declared(without_flag):
            errors.append(
                "без -DSAMOVAR_BUILD_LUA объявление xLuaSemaphore всё равно попало в "
                "результат препроцессора - USE_LUA определяется, когда флаг не задан"
            )

    if errors:
        print("USE_LUA define-order smoke check failed:", file=sys.stderr)
        for error in errors:
            print(f" - {error}", file=sys.stderr)
        return 1

    print("OK: с -DSAMOVAR_BUILD_LUA настоящий препроцессор видит объявление xLuaSemaphore")
    print("OK: без -DSAMOVAR_BUILD_LUA настоящий препроцессор его не видит")

    # ---- Мутационная самопроверка: 4 поломки, каждая обязана красить тест ----
    # Мутации накладываются на копии текста В ПАМЯТИ (ini_text/samovar_slice),
    # реальные файлы прошивки не трогаются и не перезаписываются.
    mutations = [
        (
            "удаление блока трансляции",
            ini_text.replace(TRANSITION_BLOCK, "", 1),
            samovar_slice,
        ),
        (
            "перенос блока трансляции в Samovar.h ниже xLuaSemaphore",
            ini_text.replace(TRANSITION_BLOCK, "", 1),
            samovar_slice.replace(CHECKPOINT_BLOCK, CHECKPOINT_BLOCK + "\n\n" + TRANSITION_BLOCK, 1),
        ),
        (
            "обёртывание блока в #if неопределённого флага",
            ini_text.replace(
                TRANSITION_BLOCK,
                "#if SAMOVAR_UNDEFINED_LUA_GATE\n" + TRANSITION_BLOCK + "\n#endif",
                1,
            ),
            samovar_slice,
        ),
        (
            "переименование USE_LUA в другое имя",
            ini_text.replace(TRANSITION_BLOCK, TRANSITION_BLOCK.replace("USE_LUA", "USE_LUA_RENAMED"), 1),
            samovar_slice,
        ),
    ]

    for name, mutated_ini, mutated_samovar_slice in mutations:
        mutation_errors = check_mutation(name, mutated_ini, mutated_samovar_slice)
        if mutation_errors:
            print("USE_LUA define-order smoke check failed:", file=sys.stderr)
            for error in mutation_errors:
                print(f" - {error}", file=sys.stderr)
            return 1
        print(f"OK: мутация «{name}» ловится (сборка Samovar_lua_mqtt была бы сломана)")

    print("USE_LUA define-order smoke check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
