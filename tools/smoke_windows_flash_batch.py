#!/usr/bin/env python3
"""Проверяет Windows-запуск установщика и конфигуратора Samovar."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "flash_windows.bat"


def validate(source: str) -> list[str]:
    errors: list[str] = []
    required = {
        "проверка pio": "call :find_pio",
        "проверка Python": "call :ensure_python || goto :failed",
        "PlatformIO при имени пользователя с кириллицей": 'C:\\.platformio\\penv\\Scripts\\pio.exe',
        "установка без winget": "Python и winget не найдены",
        "официальный установщик PlatformIO": "platformio/platformio-core-installer/master/get-platformio.py",
        "поддерживаемая архитектура": 'if /I "%PROCESSOR_ARCHITECTURE%"=="AMD64"',
        "исключение псевдонима Microsoft Store": '\\Microsoft\\WindowsApps\\',
        "проверка Tkinter": "import sys, tkinter",
        "установка Tkinter": "Include_tcltk=1",
        "запуск конфигуратора": 'tools\\samovar_configurator.py" --project-root "%~dp0." --pio "%PIO_EXE%"',
    }
    for name, token in required.items():
        if token not in source:
            errors.append(f"нет обязательного элемента: {name}")

    if '"%PIO_EXE%" run ' in source:
        errors.append("батник не должен сам запускать сборку или прошивку")
    if source.find("call :ensure_python") > source.find("call :find_pio"):
        errors.append("Python должен проверяться до PlatformIO")
    if 'sys.version_info ^< (3, 7)' in source or '$release.assets ^|' in source:
        errors.append("символ внутри кавычек ошибочно экранирован для cmd.exe")
    for token in ("call :ensure_git", ":ensure_git", ":find_git", "Git.Git", "samovar-git-64-bit.exe"):
        if token in source:
            errors.append(f"батник всё ещё устанавливает ненужный Git: {token}")
    return errors


def main() -> int:
    source = SOURCE.read_text(encoding="utf-8")
    errors = validate(source)
    mutations = {
        "путь проекта снова заканчивается обратной косой чертой": source.replace(
            '--project-root "%~dp0."',
            '--project-root "%~dp0"',
            1,
        ),
        "нет проверки Tkinter": source.replace("import sys, tkinter", "import sys"),
        "конфигуратор не запущен": source.replace("tools\\samovar_configurator.py", "tools\\missing.py", 1),
        "батник снова прошивает сам": source.replace(
            "echo Запуск окна настройки Samovar...",
            '"%PIO_EXE%" run -e "Samovar" -t upload',
            1,
        ),
    }
    for name, mutant in mutations.items():
        if not validate(mutant):
            errors.append(f'проверка не обнаружила мутацию "{name}"')
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print("PASS: Windows-батник устанавливает зависимости и запускает конфигуратор")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
