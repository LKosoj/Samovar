#!/bin/sh
set -u

fail() {
  printf '\nОшибка: %s\n' "$1" >&2
  exit 1
}

find_python() {
  PYTHON_EXE=""
  for candidate in python3 python3.13 python3.12 python3.11 python3.10 python3.9 python; do
    candidate_path=$(command -v "$candidate" 2>/dev/null) || continue
    if "$candidate_path" -c 'import sys, tkinter; raise SystemExit(sys.version_info < (3, 7))' >/dev/null 2>&1; then
      PYTHON_EXE=$candidate_path
      return 0
    fi
  done
  return 1
}

run_as_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
    return
  fi
  command -v sudo >/dev/null 2>&1 || fail "для установки системных пакетов требуется sudo."
  sudo "$@"
}

install_python() {
  system_name=$(uname -s) || fail "не удалось определить операционную систему."
  case "$system_name" in
    Darwin)
      command -v brew >/dev/null 2>&1 || fail "Homebrew не найден. Установите Homebrew с https://brew.sh и запустите скрипт снова."
      printf 'Python или Tkinter не найдены. Установка через Homebrew...\n'
      brew install python-tk@3.13 || fail "Homebrew не смог установить Python и Tkinter."
      ;;
    Linux)
      if command -v apt-get >/dev/null 2>&1; then
        printf 'Python или Tkinter не найдены. Установка через apt...\n'
        run_as_root apt-get update || fail "apt не смог обновить список пакетов."
        run_as_root apt-get install -y python3 python3-tk python3-venv || fail "apt не смог установить Python и Tkinter."
      elif command -v dnf >/dev/null 2>&1; then
        printf 'Python или Tkinter не найдены. Установка через dnf...\n'
        run_as_root dnf install -y python3 python3-tkinter || fail "dnf не смог установить Python и Tkinter."
      elif command -v pacman >/dev/null 2>&1; then
        printf 'Python или Tkinter не найдены. Установка через pacman...\n'
        run_as_root pacman -S --needed python tk || fail "pacman не смог установить Python и Tkinter."
      else
        fail "поддерживаемый менеджер пакетов не найден. Нужен apt, dnf или pacman."
      fi
      ;;
    *)
      fail "поддерживается только macOS или Linux."
      ;;
  esac
}

check_pio_candidate() {
  candidate=$1
  if [ -n "$candidate" ] && [ -x "$candidate" ] && "$candidate" --version >/dev/null 2>&1; then
    PIO_EXE=$candidate
    return 0
  fi
  return 1
}

find_pio() {
  PIO_EXE=""
  if [ -n "${PLATFORMIO_CORE_DIR:-}" ]; then
    check_pio_candidate "$PLATFORMIO_CORE_DIR/penv/bin/pio" && return 0
    check_pio_candidate "$PLATFORMIO_CORE_DIR/penv/bin/platformio" && return 0
  fi
  check_pio_candidate "${HOME}/.platformio/penv/bin/pio" && return 0
  check_pio_candidate "${HOME}/.platformio/penv/bin/platformio" && return 0
  candidate_path=$(command -v pio 2>/dev/null) && check_pio_candidate "$candidate_path" && return 0
  candidate_path=$(command -v platformio 2>/dev/null) && check_pio_candidate "$candidate_path" && return 0
  return 1
}

install_platformio() {
  printf 'Скачивание официального установщика PlatformIO...\n'
  installer_dir=$(mktemp -d "${TMPDIR:-/tmp}/samovar-platformio.XXXXXX") || fail "не удалось создать временную папку."
  installer_path="$installer_dir/get-platformio.py"
  trap 'rm -f "$installer_path"; rmdir "$installer_dir" 2>/dev/null' 0
  if ! "$PYTHON_EXE" - "$installer_path" <<'PY'
import sys
from urllib.request import urlretrieve

urlretrieve(
    "https://raw.githubusercontent.com/platformio/platformio-core-installer/master/get-platformio.py",
    sys.argv[1],
)
PY
  then
    fail "не удалось скачать установщик PlatformIO."
  fi
  "$PYTHON_EXE" "$installer_path" || fail "PlatformIO не установился."
}

SCRIPT_DIR=$(CDPATH='' cd "$(dirname "$0")" && pwd) || fail "не удалось открыть папку проекта."

if find_python; then
  printf 'Python найден: %s\n' "$PYTHON_EXE"
else
  install_python
  find_python || fail "Python установлен, но Python с Tkinter не найден."
  printf 'Python найден: %s\n' "$PYTHON_EXE"
fi

if find_pio; then
  printf 'PlatformIO найден: %s\n' "$PIO_EXE"
else
  printf 'PlatformIO не найден. Начинается автоматическая установка.\n'
  install_platformio
  find_pio || fail "PlatformIO установлен, но исполняемый файл не найден."
  printf 'PlatformIO найден: %s\n' "$PIO_EXE"
fi

printf '\nЗапуск окна настройки Samovar...\n'
"$PYTHON_EXE" "$SCRIPT_DIR/tools/samovar_configurator.py" --project-root "$SCRIPT_DIR" --pio "$PIO_EXE" || \
  fail "окно настройки Samovar завершилось с ошибкой."
