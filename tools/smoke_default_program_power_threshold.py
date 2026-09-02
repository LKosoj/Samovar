#!/usr/bin/env python3
"""[Б7.2/Б7.4] Регресс-тест на дефолтную программу ректификации (sensorinit.h).

load_default_program_for_mode() зовётся при КАЖДОЙ загрузке прошивки для
SAMOVAR_RECTIFICATION_MODE (режим по умолчанию на новом приборе) и проходит
через ту же проверку первой строки, что и обычная загрузка программы
(program_io.h::prepare_program_for_mode(): первая строка обязана задавать
АБСОЛЮТНУЮ мощность/напряжение). Порог абсолютной уставки -
PROGRAM_POWER_ABS_THRESHOLD (program_types.h): 400 Вт при SAMOVAR_USE_SEM_AVR,
40 В иначе. Если дефолтная программа окажется на пороге или ниже - свежий
прибор ректификации будет уходить в аварийную блокировку при каждой загрузке.

Тест читает РЕАЛЬНЫЕ program_types.h и sensorinit.h и парсит текст без
компиляции: пороги берутся из program_types.h, а не хардкодятся здесь.

[Б7.2] Дефолт для не-SEM_AVR веток (#else ректификации и Lua) - это ОДИН
#define DEFAULT_PROGRAM_HBH45 (сведено к единому источнику истины, раньше было
два независимых строковых литерала). Тест резолвит имя макроса через его
#define И дополнительно сверяет, что ветка Lua ссылается на ТОТ ЖЕ дефолт,
что и #else ректификации - иначе компилятор расхождение копий не поймает.

[БК п.9] У БК теперь собственный case и собственный формат строки программы
(PROGRAM_FORMAT_BK, program_io.h) - дефолт "T;93;1;0;0\n" c Power=0 (4-е поле)
под новое правило "первая строка с ненулевой мощностью" (распространённое на БК
так же, как на дистилляцию) не попадает, но тест держит это под контролем на
будущее теми же двумя проверками, что и для dist_first_power ниже.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

THRESHOLD_MARKER = "PROGRAM_POWER_ABS_THRESHOLD"
SEM_IFDEF = "#ifdef SAMOVAR_USE_SEM_AVR"
CASE_MARKER = "case SAMOVAR_RECTIFICATION_MODE:"
LUA_CASE_MARKER = "case SAMOVAR_LUA_MODE:"
BK_CASE_MARKER = "case SAMOVAR_BK_MODE:"
DIST_CASE_MARKER = "case SAMOVAR_DISTILLATION_MODE:"


def parse_thresholds(types_source: str) -> tuple[float, float]:
    """Возвращает (порог_SEM_AVR, порог_остальных) из program_types.h."""
    first = types_source.find(THRESHOLD_MARKER)
    if first < 0:
        raise ValueError(f"constant not found: {THRESHOLD_MARKER}")
    ifdef_idx = types_source.rfind(SEM_IFDEF, 0, first)
    if ifdef_idx < 0:
        raise ValueError(f"enclosing {SEM_IFDEF} not found before threshold constant")
    endif_idx = types_source.find("#endif", first)
    if endif_idx < 0:
        raise ValueError("closing #endif for threshold constant not found")
    block = types_source[ifdef_idx:endif_idx]

    else_idx = block.find("#else")
    if else_idx < 0:
        raise ValueError("#else branch of threshold constant not found")
    sem_block = block[:else_idx]
    default_block = block[else_idx:]

    def extract_value(text: str) -> float:
        match = re.search(rf"{THRESHOLD_MARKER}\s*=\s*([0-9.]+)f?\s*;", text)
        if not match:
            raise ValueError(f"threshold value not found in block: {text!r}")
        return float(match.group(1))

    return extract_value(sem_block), extract_value(default_block)


def resolve_macro(source: str, name: str) -> str:
    """Возвращает строковый литерал из #define NAME "..." в source."""
    match = re.search(rf'#define\s+{re.escape(name)}\s+"((?:[^"\\]|\\.)*)"', source)
    if not match:
        raise ValueError(f"macro not defined: {name}")
    return match.group(1)


def extract_program(text: str, full_source: str) -> str:
    """defaultProgram = "..."; ИЛИ defaultProgram = MACRO_NAME; - второе (общий
    дефолт #else ректификации / БК / Lua, см. DEFAULT_PROGRAM_HBH45) резолвится
    через #define в full_source."""
    match = re.search(r'defaultProgram\s*=\s*"((?:[^"\\]|\\.)*)"\s*;', text)
    if match:
        return match.group(1)
    match = re.search(r'defaultProgram\s*=\s*(\w+)\s*;', text)
    if match:
        return resolve_macro(full_source, match.group(1))
    raise ValueError(f"defaultProgram literal/macro not found in block: {text!r}")


def parse_default_programs(sensorinit_source: str) -> tuple[str, str]:
    """Возвращает (программа_SEM_AVR, программа_остальных) из case
    SAMOVAR_RECTIFICATION_MODE. Дополнительно сверяет, что case
    SAMOVAR_LUA_MODE ссылается на ТОТ ЖЕ дефолт, что и #else ректификации
    (раньше это был независимый дублирующий литерал, который мог незаметно
    разойтись с оригиналом). [БК п.9] До разделения case-блоков этот же
    маркер (BK_LUA_CASE_MARKER) находил ОБЩИЙ блок БК+LUA; теперь у БК
    собственный case со своим форматом строки - см. parse_default_bk_program()
    и отдельные проверки в main()."""
    case_idx = sensorinit_source.find(CASE_MARKER)
    if case_idx < 0:
        raise ValueError(f"case not found: {CASE_MARKER}")
    break_idx = sensorinit_source.find("break;", case_idx)
    if break_idx < 0:
        raise ValueError("closing break; for RECT case not found")
    block = sensorinit_source[case_idx:break_idx]

    ifdef_idx = block.find(SEM_IFDEF)
    if ifdef_idx < 0:
        raise ValueError(f"{SEM_IFDEF} not found in default rectification program case")
    else_idx = block.find("#else", ifdef_idx)
    endif_idx = block.find("#endif", ifdef_idx)
    if else_idx < 0 or endif_idx < 0:
        raise ValueError("#else/#endif not found in default rectification program case")
    sem_block = block[ifdef_idx:else_idx]
    default_block = block[else_idx:endif_idx]

    sem_program = extract_program(sem_block, sensorinit_source)
    default_program = extract_program(default_block, sensorinit_source)

    lua_case_idx = sensorinit_source.find(LUA_CASE_MARKER, break_idx)
    if lua_case_idx < 0:
        raise ValueError(f"case not found after RECT case: {LUA_CASE_MARKER}")
    lua_break_idx = sensorinit_source.find("break;", lua_case_idx)
    if lua_break_idx < 0:
        raise ValueError("closing break; for LUA case not found")
    lua_block = sensorinit_source[lua_case_idx:lua_break_idx]
    lua_program = extract_program(lua_block, sensorinit_source)

    if lua_program != default_program:
        raise ValueError(
            "LUA default program diverged from rectification's #else default: "
            f"{lua_program!r} != {default_program!r}"
        )

    return sem_program, default_program


def parse_default_bk_program(sensorinit_source: str) -> str:
    """[БК п.9] Возвращает литерал дефолтной программы БК (case
    SAMOVAR_BK_MODE, теперь отдельный от LUA). Формат строки -
    Тип;Порог;Ёмкость;Мощность;Тпара (program_io.h::bk_program_parse_spec) -
    Power четвёртое поле (индекс 3), как и у dist, поэтому
    dist_first_nonzero_power() ниже подходит без изменений: пятое поле Тпара
    на разбор индекса 3 не влияет."""
    case_idx = sensorinit_source.find(BK_CASE_MARKER)
    if case_idx < 0:
        raise ValueError(f"case not found: {BK_CASE_MARKER}")
    break_idx = sensorinit_source.find("break;", case_idx)
    if break_idx < 0:
        raise ValueError("closing break; for BK case not found")
    block = sensorinit_source[case_idx:break_idx]
    return extract_program(block, sensorinit_source)


def parse_default_dist_program(sensorinit_source: str) -> str:
    """Возвращает литерал дефолтной программы дистилляции (case
    SAMOVAR_DISTILLATION_MODE). В отличие от ректификации, здесь нет ветки
    #ifdef SAMOVAR_USE_SEM_AVR - один и тот же литерал компилируется во ВСЕ
    окружения, поэтому его нужно проверять сразу против обоих порогов ниже."""
    case_idx = sensorinit_source.find(DIST_CASE_MARKER)
    if case_idx < 0:
        raise ValueError(f"case not found: {DIST_CASE_MARKER}")
    break_idx = sensorinit_source.find("break;", case_idx)
    if break_idx < 0:
        raise ValueError("closing break; for DIST case not found")
    block = sensorinit_source[case_idx:break_idx]
    return extract_program(block, sensorinit_source)


def dist_first_nonzero_power(program_literal: str) -> float | None:
    """[П1] Формат строки дистилляции - Type;Speed;Capacity;Power
    (program_io.h::dist_program_parse_spec), Power - 4-е поле (индекс 3), в
    отличие от 6-полевой строки ректификации. Возвращает Power первой строки
    с ненулевой мощностью, либо None, если все строки Power == 0 (штатный
    случай - разгон длится весь процесс, дефолт sensorinit.h именно такой).
    [БК п.9] У БК (program_io.h::bk_program_parse_spec) Power - тоже 4-е поле
    (5-е, Тпара, на разбор индекса 3 не влияет), поэтому функция годится и
    для БК без изменений - переименовывать не нужно."""
    for row in program_literal.split("\\n"):
        if not row:
            continue
        fields = row.split(";")
        if len(fields) < 4:
            raise ValueError(f"dist row has too few fields: {row!r}")
        power = float(fields[3])
        if power != 0:
            return power
    return None


def first_row_power(program_literal: str) -> float:
    # program_literal - это C-строковый литерал как есть в исходнике, "\n" -
    # это два символа (backslash + n), а не настоящий перевод строки.
    first_line_end = program_literal.find("\\n")
    first_line = program_literal[:first_line_end] if first_line_end >= 0 else program_literal
    fields = first_line.split(";")
    if len(fields) < 6:
        raise ValueError(f"first row has too few fields: {first_line!r}")
    return float(fields[5])


def main() -> int:
    types_source = (ROOT / "program_types.h").read_text(encoding="utf-8")
    sensorinit_source = (ROOT / "sensorinit.h").read_text(encoding="utf-8")

    try:
        sem_threshold, default_threshold = parse_thresholds(types_source)
        sem_program, default_program = parse_default_programs(sensorinit_source)
        dist_program = parse_default_dist_program(sensorinit_source)
        bk_program = parse_default_bk_program(sensorinit_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    sem_power = first_row_power(sem_program)
    default_power = first_row_power(default_program)
    dist_first_power = dist_first_nonzero_power(dist_program)
    bk_first_power = dist_first_nonzero_power(bk_program)

    errors = []
    if not (sem_power > sem_threshold):
        errors.append(
            f"SEM_AVR default first-row Power={sem_power} must be strictly > threshold {sem_threshold}"
        )
    if not (default_power > default_threshold):
        errors.append(
            f"default (KVIC/RMVK) first-row Power={default_power} must be strictly > threshold {default_threshold}"
        )
    # [П1] Один и тот же литерал дистилляции компилируется во все окружения -
    # проверяем против ОБОИХ порогов (SEM_AVR и остальных), как и рект-дефолты выше.
    if dist_first_power is not None:
        if not (dist_first_power > sem_threshold):
            errors.append(
                f"[П1] dist default first nonzero-power row Power={dist_first_power} "
                f"must be strictly > SEM_AVR threshold {sem_threshold}"
            )
        if not (dist_first_power > default_threshold):
            errors.append(
                f"[П1] dist default first nonzero-power row Power={dist_first_power} "
                f"must be strictly > default threshold {default_threshold}"
            )
    # [БК п.9] Дефолт БК ("T;93;1;0;0\n") сегодня Power=0 у единственной строки,
    # bk_first_power == None и обе проверки молчат - но если кто-то потом впишет
    # в дефолт ненулевую Power ниже порога, тест это поймает.
    if bk_first_power is not None:
        if not (bk_first_power > sem_threshold):
            errors.append(
                f"[БК п.9] bk default first nonzero-power row Power={bk_first_power} "
                f"must be strictly > SEM_AVR threshold {sem_threshold}"
            )
        if not (bk_first_power > default_threshold):
            errors.append(
                f"[БК п.9] bk default first nonzero-power row Power={bk_first_power} "
                f"must be strictly > default threshold {default_threshold}"
            )

    if errors:
        print("Default rectification program power threshold check failed:")
        for error in errors:
            print(f" - {error}")
        return 1

    print(
        "Default rectification program power threshold check passed "
        f"(SEM_AVR: {sem_power} > {sem_threshold}, default: {default_power} > {default_threshold})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
