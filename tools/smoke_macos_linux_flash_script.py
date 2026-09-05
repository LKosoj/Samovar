#!/usr/bin/env python3
"""Проверяет запуск конфигуратора Samovar в macOS и Linux."""

import stat
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "flash_macos_linux.sh"


def validate(source: str, mode: int) -> list[str]:
    errors: list[str] = []
    required = {
        "POSIX shell": "#!/bin/sh",
        "проверка Python и Tkinter": "import sys, tkinter",
        "macOS": "\n    Darwin)\n",
        "Linux": "\n    Linux)\n",
        "Homebrew Python и Tkinter": "brew install python-tk@3.13",
        "apt Python и Tkinter": "apt-get install -y python3 python3-tk python3-venv",
        "dnf Python и Tkinter": "dnf install -y python3 python3-tkinter",
        "pacman Python и Tkinter": "pacman -S --needed python tk",
        "официальный установщик PlatformIO": "platformio/platformio-core-installer/master/get-platformio.py",
        "проверка PlatformIO": '"$candidate" --version',
        "запуск конфигуратора": '"$SCRIPT_DIR/tools/samovar_configurator.py"',
        "явная передача PlatformIO": '--project-root "$SCRIPT_DIR" --pio "$PIO_EXE"',
    }
    for name, token in required.items():
        if token not in source:
            errors.append(f"нет обязательного элемента: {name}")

    if mode & stat.S_IXUSR == 0:
        errors.append("flash_macos_linux.sh не имеет права на исполнение")
    for token in ('"$PIO_EXE" run ', 'pio run ', 'platformio run '):
        if token in source:
            errors.append("shell-скрипт не должен сам запускать сборку или прошивку")
    return errors


def main() -> int:
    source = SOURCE.read_text(encoding="utf-8")
    mode = SOURCE.stat().st_mode
    errors = validate(source, mode)
    mutations = {
        "не проверяется Tkinter": source.replace("import sys, tkinter", "import sys", 1),
        "не поддерживается macOS": source.replace("\n    Darwin)\n", "\n    UnsupportedDarwin)\n", 1),
        "не поддерживается Linux": source.replace("\n    Linux)\n", "\n    UnsupportedLinux)\n", 1),
        "конфигуратор не запущен": source.replace("tools/samovar_configurator.py", "tools/missing.py", 1),
        "путь PlatformIO не передан": source.replace(' --pio "$PIO_EXE"', "", 1),
    }
    for name, mutant in mutations.items():
        if not validate(mutant, mode):
            errors.append(f'проверка не обнаружила мутацию "{name}"')

    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print("PASS: shell-скрипт устанавливает зависимости и запускает конфигуратор")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
