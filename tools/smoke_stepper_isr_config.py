#!/usr/bin/env python3
"""Проверяет совместимость настроек шагового двигателя в Arduino-сборке."""

import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SAMOVAR_HEADER = ROOT / "Samovar.h"
SAMOVAR_INI = ROOT / "Samovar_ini.h"
BLOCK_START = "#define USE_STEPPER_IRAM_ISR"
BLOCK_END = "\n#include <GyverStepper2.h>"


def extract_stepper_selection(source: str) -> str:
    start = source.find(BLOCK_START)
    end = source.find(BLOCK_END, start)
    if start < 0 or end < 0:
        raise ValueError("в Samovar.h не найден блок выбора ISR и ускорения")
    return source[start:end]


def preprocess(
    source: str, defines: tuple[str, ...] = ()
) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix="samovar-stepper-config-") as temp_dir:
        source_path = Path(temp_dir) / "check.cpp"
        source_path.write_text(source, encoding="utf-8")
        command = ["cpp", "-x", "c++", "-P"]
        command.extend(f"-D{define}" for define in defines)
        command.append(str(source_path))
        return subprocess.run(command, capture_output=True, text=True, check=False)


def enabled_flags(block: str, defines: tuple[str, ...]) -> set[str]:
    probe = (
        block
        + """
#ifdef USE_STEPPER_IRAM_ISR
ISR_ENABLED
#endif
#ifdef USE_STEPPER_ACCELERATION
ACCELERATION_ENABLED
#endif
#ifdef GS_FAST_PROFILE
FAST_PROFILE_ENABLED
#endif
#ifdef GS_NO_ACCEL
NO_ACCELERATION_ENABLED
#endif
"""
    )
    result = preprocess(probe, defines)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    return set(result.stdout.split())


def validate(block: str) -> list[str]:
    errors: list[str] = []
    cases = (
        (
            ("USE_STEPPER_ACCELERATION",),
            {"ISR_ENABLED", "ACCELERATION_ENABLED", "FAST_PROFILE_ENABLED"},
        ),
        ((), {"ISR_ENABLED", "NO_ACCELERATION_ENABLED"}),
    )
    for defines, expected in cases:
        try:
            actual = enabled_flags(block, defines)
        except RuntimeError as error:
            errors.append(f"препроцессор завершился с ошибкой для {defines}: {error}")
            continue
        if actual != expected:
            errors.append(
                f"для {defines} ожидалось {sorted(expected)}, получено {sorted(actual)}"
            )
    return errors


def main() -> int:
    if shutil.which("cpp") is None:
        print("FAIL: cpp не найден, невозможно проверить настройки Arduino")
        return 1

    header = SAMOVAR_HEADER.read_text(encoding="utf-8")
    ini = SAMOVAR_INI.read_text(encoding="utf-8")
    try:
        block = extract_stepper_selection(header)
    except ValueError as error:
        print(f"FAIL: {error}")
        return 1

    errors = validate(block)

    include_ini_twice = '#include "Samovar_ini.h"\n#include "Samovar_ini.h"\n'
    with tempfile.TemporaryDirectory(prefix="samovar-ini-guard-") as temp_dir:
        temp_path = Path(temp_dir)
        (temp_path / "Samovar_ini.h").write_text(ini, encoding="utf-8")
        (temp_path / "Arduino.h").write_text("", encoding="utf-8")
        wrapper = temp_path / "check.cpp"
        wrapper.write_text(include_ini_twice, encoding="utf-8")
        result = subprocess.run(
            ["cpp", "-x", "c++", "-P", "-I", str(temp_path), str(wrapper)],
            capture_output=True,
            text=True,
            check=False,
        )
    if result.returncode != 0:
        errors.append(
            f"Samovar_ini.h не проходит препроцессор Arduino: {result.stderr.strip()}"
        )
    elif result.stdout.count("int8_t servoDelta") != 1:
        errors.append("защита Samovar_ini.h от повторного подключения работает неверно")

    if not ini.rstrip().endswith("#endif  // __SAMOVAR_I_H_"):
        errors.append(
            "последний #endif Samovar_ini.h не подписан как закрытие защиты файла"
        )

    ini_include = header.find('#include "Samovar_ini.h"')
    override_include = header.find('#include "user_config_override.h"')
    stepper_selection = header.find(BLOCK_START)
    if not (0 <= ini_include < override_include < stepper_selection):
        errors.append(
            "выбор ISR и ускорения должен выполняться после Samovar_ini.h и user_config_override.h"
        )

    mutations = {
        "удалён быстрый профиль ускорения": block.replace(
            "#define GS_FAST_PROFILE 10", ""
        ),
        "ускорение снова отключено при ISR": block.replace(
            "#define USE_STEPPER_IRAM_ISR",
            "#define USE_STEPPER_IRAM_ISR\n#ifdef USE_STEPPER_ACCELERATION\n"
            "#undef USE_STEPPER_ACCELERATION\n#endif",
        ),
    }
    for name, mutant in mutations.items():
        if not validate(mutant):
            errors.append(f"проверка не обнаружила мутацию «{name}»")

    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1

    print("PASS: Samovar_ini.h корректен, ISR совместим с быстрым профилем ускорения")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
