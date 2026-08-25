#!/usr/bin/env python3
"""Проверка, что обработчик прерывания шагового двигателя не обращается во флеш.

Прерывание StepperTicker зарегистрировано с ESP_INTR_FLAG_IRAM (см. USE_STEPPER_IRAM_ISR
в Samovar.h), поэтому оно продолжает работать, пока идёт запись в файл и кэш флеш-памяти
отключён. Если в обработчик попадёт хоть один вызов или литерал из флеша, прошивка
упадёт с "Cache disabled but cached memory region accessed" ровно в момент записи лога.

Проверка разбирает не только тело самого StepperTicker, но и весь граф вызовов, реально
достижимый из него: инструкции call0/call4/call8/call12 (прямой вызов по известному
адресу) разбираются рекурсивно для каждой найденной цели, лежащей в .iram0.text, пока не
будет обойдено всё достижимое. Множество уже посещённых адресов защищает от зацикливания
на рекурсивных/взаимных вызовах.

Инструкции callx0/callx4/callx8/callx12 (вызов по адресу из регистра) сами по себе НЕ
категорическое нарушение - очень часто это на самом деле вызов по константному адресу:
компилятор грузит адрес инструкцией l32r в регистр и тут же зовёт его через callx (типично
для вызовов масочного ПЗУ (ROM) - расстояние до ПЗУ на грани дальности прямого call на
Xtensa). Для каждой callx-инструкции проверка ищет ближайший вверх l32r в тот же регистр в
пределах небольшого окна того же базового блока (см. _trace_callx_source) - НЕ полноценный
анализ потока данных, а простой и надёжный частный случай; при малейшем сомнении (control
flow между l32r и callx, регистр перезаписан, окно исчерпано) трассировка честно не
находит цель. Дальше цель (прослеженная через callx или обычная call) классифицируется по
секции:
  - IRAM (.iram0.*) или ПЗУ (masked ROM, см. rom_symbols()) - безопасно, для IRAM обход
    идёт дальше рекурсивно;
  - .flash.* (или другая секция флеша) - нарушение, обращение во флеш;
  - трассировка не удалась или целевая секция не опознана - нарушение ("недоказуемо").
Так callx перестаёт быть огульным нарушением, но остаётся нарушением ровно тогда, когда
безопасность цели не удалось доказать.

Отдельно от этого - два обращения во флеш, которые проверка находит на КАЖДОМ окружении и
которые не являются багом прошивки: они лежат внутри вендорного кода ESP-IDF/FreeRTOS
(xPortEnterCriticalTimeout/vPortExitCritical), который нельзя ни поправить, ни обойти - его
вызывает сама реализация критической секции FreeRTOS при входе/выходе. Для НИХ, и только для
них, действует именной список TRUSTED_VENDOR_EXCEPTIONS (см. её и trusted_flash_target_reason
- там же обоснование по каждой цели и условие, при котором это перестанет быть правдой). Это
не "этой функции можно всё": проверяется КОНКРЕТНАЯ цель конкретной функции, и одно из двух
исключений (compare_and_set_extram) снимается сама проверкой find_psram_usage(), если найдёт
в исходниках проекта признаки размещения данных в PSRAM.

Версия Arduino core определяется по факту - из core_version.h установленного пакета
framework-arduinoespressif32 (см. detect_core_status()). Для core 3.x размещение кода в
IRAM управляется иначе (через конфигурацию IDF), эта проверка по секциям .elf для него не
годится - вместо ложного "всё хорошо" печатается явный пропуск.

Проверка работает по собранным прошивкам, поэтому не подходит под маску smoke_*.py.
Список окружений обязателен и не берётся из того, что случайно лежит в .pio/build -
иначе "собрали одно окружение, проверили одно и сказали OK". В CI вызывается по разу
на каждое окружение из матрицы сборки (все 7 - USE_STEPPER_IRAM_ISR определён
безусловно в Samovar.h и действует на все окружения platformio.ini одинаково).

    pio run -e Samovar && python3 tools/check_stepper_isr_iram.py Samovar

Самопроверка на синтетическом входе (доказывает, что рекурсия и детектор callx реально
работают, а не просто не мешают) - без сборки и без реального .elf:

    python3 tools/check_stepper_isr_iram.py --selftest
"""
import argparse
import functools
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
BUILD_DIR = ROOT / ".pio" / "build"
PACKAGES = Path.home() / ".platformio" / "packages"
ISR_SYMBOL = "_Z13StepperTickerv"
# Секции, размещённые во флеше: обращение к ним из обработчика недопустимо.
FLASH_SECTION_MARKERS = (".flash.", "irom", "drom")

# Признаки размещения данных в PSRAM В ИСХОДНИКАХ ПРОЕКТА (не пакета/тулчейна - там PSRAM
# API используется штатно и нас не касается). ps_malloc/ps_calloc/ps_realloc - обёртки
# esp32-hal-psram.h (Arduino core), MALLOC_CAP_SPIRAM - флаг, которым heap_caps_malloc/
# heap_caps_calloc/heap_caps_realloc (и их heap_caps_malloc_prefer-варианты) явно просят
# память именно из внешней PSRAM. Обычный malloc() сюда сознательно не входит: то, попадёт
# ли он в PSRAM, решает CONFIG_SPIRAM_USE_MALLOC в sdkconfig.h пакета (см. комментарий у
# TRUSTED_VENDOR_EXCEPTIONS) - это не то, чем управляет исходный текст этой прошивки.
PSRAM_API_MARKERS = ("ps_malloc", "ps_calloc", "ps_realloc", "MALLOC_CAP_SPIRAM")
PSRAM_SOURCE_GLOBS = ("*.h", "*.hpp", "*.ino", "*.cpp", "*.c", "*.cc")
# libraries/ - сторонние библиотеки (включая вложенные, например pro_mini_ntc/libraries),
# .pio/ - сборочный кэш и распакованные пакеты тулчейна: оба вне контроля владельца этой
# прошивки, проверять их бессмысленно (а .pio/ ещё и огромный).
PSRAM_EXCLUDED_DIR_NAMES = ("libraries", ".pio")


@functools.lru_cache(maxsize=1)
def find_psram_usage(root: Path) -> tuple[str, ...]:
    """Ищет в исходниках ПРОЕКТА (root) явные признаки работы с PSRAM (PSRAM_API_MARKERS).

    Область поиска - все *.h/*.hpp/*.ino/*.cpp/*.c/*.cc ПОД root, кроме каталогов из
    PSRAM_EXCLUDED_DIR_NAMES на любой глубине. Никакие другие вложенные проекты в
    репозитории (соседние прошивки в подпапках вроде ESP32-S3/, Stab-avr/ и т.п. - Arduino
    их не собирает, но они остаются в дереве) не исключаются: для проверки предпосылки
    "нигде не размещаем данные в PSRAM" лишняя строгость безопаснее пропуска.

    Результат кэшируется (@lru_cache) - root не меняется в пределах одного запуска
    инструмента, а check_env() вызывается по разу на окружение (до 7 раз за прогон);
    без кэша каждый вызов заново сканировал бы больше тысячи файлов.

    Это проверяемая опора исключения compare_and_set_extram (см. TRUSTED_VENDOR_EXCEPTIONS
    и spinlock_acquire() в soc/spinlock.h пакета framework-arduinoespressif32): сами
    спинлоки нигде явно не видны как отдельные объекты (спрятаны внутри portMUX_TYPE полей
    у объектов FreeRTOS), поэтому напрямую проверить "ни один спинлок не лежит в PSRAM"
    нельзя - но если проект вообще не пользуется PSRAM-аллокацией, то и подавно не может."""
    hits: list[str] = []
    seen: set[Path] = set()
    for pattern in PSRAM_SOURCE_GLOBS:
        for path in sorted(root.rglob(pattern)):
            if path in seen:
                continue
            seen.add(path)
            rel = path.relative_to(root)
            if any(part in PSRAM_EXCLUDED_DIR_NAMES for part in rel.parts):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for marker in PSRAM_API_MARKERS:
                if marker in text:
                    hits.append(f"{rel}: {marker}")
    return tuple(hits)


# Доверенные вендорные функции ESP-IDF/FreeRTOS: код, который проект не может ни поправить,
# ни обойти (его вызывает сама реализация критической секции FreeRTOS при входе/выходе - в
# том числе из ISR), и который вендор сам разместил в IRAM ровно для этого. Но "вендорная
# функция" - не пропуск для ЛЮБОГО обращения во флеш из неё: ключ словаря - имя функции ИЗ
# ГРАФА ВЫЗОВОВ ISR (см. iram_funcs), значение - ИМЕНА целей (символов), которые именно эта
# функция имеет право затрагивать через флеш. Новая, не перечисленная здесь цель остаётся
# нарушением (см. trusted_flash_target_reason() и её вызовы в analyze_call_graph()).
#
# "__assert_func" - vPortExitCritical()/xPortEnterCriticalTimeout() - это инлайненные
# spinlock_release()/spinlock_acquire() (soc/spinlock.h) с несколькими assert() внутри.
# Строки для них (__FILE__/__func__/текст выражения) лежат во флеше и грузятся в регистры
# ПЕРЕД вызовом __assert_func - но по коду ДО них (условный переход в disasm) эти инструкции
# исполняются, только если сама проверка assert() уже нарушена, а CONFIG_FREERTOS_ASSERT_
# FAIL_ABORT=1 (во всех 7 sdkconfig.h) превращает такое срабатывание в аварийный останов, а
# не в штатное продолжение работы. Сам __assert_func физически лежит в IRAM (проверено через
# nm/objdump на реальном .elf - 0x40092a18 в диапазоне .iram0.text), и всё, что ОНА сама
# вызывает (memset/itoa/strlen/memcpy/spi_flash_cache_enabled/esp_system_abort - тоже
# проверено) - там же; это исключение относится ТОЛЬКО к литералам-аргументам, которые
# vPortExitCritical/xPortEnterCriticalTimeout передают __assert_func САМИ - тело самой
# __assert_func (и всё достижимое из неё) по-прежнему разбирается обходом графа вызовов без
# всякого снисхождения и упадёт как обычное нарушение, если когда-нибудь окажется во флеше.
#
# "compare_and_set_extram" - только у xPortEnterCriticalTimeout() (spinlock_acquire()):
# ветка "if (esp_ptr_external_ram(lock)) compare_and_set_extram(&lock->owner, ...);" в
# spinlock_acquire() (framework-arduinoespressif32/tools/sdk/{esp32,esp32s3}/include/
# esp_hw_support/include/soc/spinlock.h) выбирается ПРОВЕРКОЙ ВРЕМЕНИ ВЫПОЛНЕНИЯ - лежит ли
# САМ объект-спинлок физически в PSRAM. CONFIG_SPIRAM=1 включено структурно во всех 7
# sdkconfig.h (заводской дефолт пакета для любого flash_mode, platformio.ini не содержит ни
# одного psram-флага), поэтому код ветки скомпилирован всегда - но это не значит, что она
# выполняется: наши спинлоки - статические переменные, а не куски памяти из PSRAM-кучи.
# Условие проверяется find_psram_usage(): если проект не пользуется ни одним PSRAM-
# аллокатором, ни один спинлок не может физически оказаться в PSRAM. Перестанет быть
# правдой (и ИМЕННО тогда обязано падать), если в проекте появится ps_malloc/ps_calloc/
# ps_realloc/heap_caps_*(..., MALLOC_CAP_SPIRAM) - find_psram_usage() найдёт это, и
# compare_and_set_extram сразу перестанет быть в списке разрешённых целей.
TRUSTED_VENDOR_EXCEPTIONS: dict[str, set[str]] = {
    "xPortEnterCriticalTimeout": {"__assert_func", "compare_and_set_extram"},
    "vPortExitCritical": {"__assert_func"},
}

FUNC_HEADER_RE = re.compile(r"^([0-9a-f]{8}) <(.+)>:$")
# call12 - тоже допустимый номер окна вызова (00/04/08/12), не только однозначные.
CALL_RE = re.compile(r"\bcall(?:0|4|8|12)\s+([0-9a-f]+)")
# С захватом регистра - нужен для трассировки источника (см. _trace_callx_source).
CALLX_RE = re.compile(r"\bcallx(?:0|4|8|12)\b\s+(a\d+)")
LITERAL_RE = re.compile(r"l32r\s+a\d+, (?:0x)?([0-9a-f]+)")
# То же самое, что LITERAL_RE, но с захватом регистра-получателя - нужен, чтобы найти ИМЕННО
# тот l32r, что кормит конкретный callx (регистр должен совпасть), а не любой l32r подряд.
L32R_REG_RE = re.compile(r"\bl32r\s+(a\d+),\s*(?:0x)?([0-9a-f]+)")
# Строка disassembly содержит "<...>" ровно тогда, когда objdump смог сослаться на символ -
# для call/callx/j/branch это ВСЕГДА цель перехода (аннотация нужна человеку, чтобы не
# считать адреса в уме). Используется как грубый, но безопасный признак границы базового
# блока при трассировке назад: как только встретили такую строку и это не искомый l32r -
# останавливаемся, а не гадаем, не мог ли регистр быть переписан за поворотом.
CONTROL_FLOW_HINT_RE = re.compile(r"<")
# "недалеко выше" - см. module docstring: простой случай, не анализ потока данных. Во всех
# трёх реальных случаях (esp_rom_delay_us, __assert_func x5, compare_and_set_extram) l32r
# оказался РОВНО соседней инструкцией (offset=1); запас на несколько строк - подстраховка
# на случай другой версии тулчейна/оптимизатора, не более того.
CALLX_TRACE_WINDOW = 6
INSN_ADDR_RE = re.compile(r"^\s*([0-9a-f]+):")
CORE_VERSION_HEADER = PACKAGES / "framework-arduinoespressif32" / "cores" / "esp32" / "core_version.h"
CORE_VERSION_RE = re.compile(r"#define\s+ARDUINO_ESP32_GIT_DESC\s+(\S+)")
# Линковочные скрипты масочного ПЗУ (ROM) - тот же формат для esp32 и esp32s3 (esp32c3/s2 не
# используются проектом, поэтому не перечислены). PROVIDE(name = 0xADDR) / "name = 0xADDR;" -
# это тот же источник, которым пользуется САМ линковщик при резолве вызовов ROM-функций,
# поэтому сверка по нему надёжнее, чем "адрес не попал ни в одну секцию .elf" (это тоже верно
# для ROM, но так же верно и для мусорного/битого адреса - ложная безопасность).
ROM_LD_ENTRY_RE = re.compile(r"([A-Za-z_]\w*)\s*=\s*(0x[0-9a-fA-F]+)\s*\)?\s*;")


def toolchain_prefix(env_name: str) -> Path:
    if env_name.endswith("_s3"):
        return PACKAGES / "toolchain-xtensa-esp32s3" / "bin" / "xtensa-esp32s3-elf-"
    return PACKAGES / "toolchain-xtensa-esp32" / "bin" / "xtensa-esp32-elf-"


def run_tool(tool: Path, *args: str) -> str:
    return subprocess.run([str(tool), *args], capture_output=True, text=True, check=True).stdout


def section_map(objdump: Path, elf: Path) -> list[tuple[str, int, int]]:
    sections = []
    for line in run_tool(objdump, "-h", str(elf)).splitlines():
        match = re.match(r"\s*\d+\s+(\S+)\s+([0-9a-f]{8})\s+([0-9a-f]{8})", line)
        if match:
            sections.append((match.group(1), int(match.group(3), 16), int(match.group(2), 16)))
    return sections


def symbol_map(nm: Path, elf: Path) -> dict[int, str]:
    symbols: dict[int, str] = {}
    for line in run_tool(nm, str(elf)).splitlines():
        parts = line.split(" ", 2)
        if len(parts) == 3:
            try:
                symbols.setdefault(int(parts[0], 16), parts[2].strip())
            except ValueError:
                pass
    return symbols


def rom_symbols(env_name: str) -> dict[int, str]:
    """Адреса функций масочного ПЗУ (ROM) для чипа этого окружения: адрес -> имя.

    Источник - esp32.rom*.ld / esp32s3.rom*.ld в пакете framework-arduinoespressif32 (тот
    же пакет и та же версия, которыми был собран .elf - см. detect_core_status()). Чип
    определяется по суффиксу имени окружения так же, как в toolchain_prefix() - "_s3"
    значит esp32s3, иначе esp32 (единственные два чипа проекта, esp32c3/s2 не используются).

    Почему это надёжный способ провести границу ПЗУ, а не "адрес не входит ни в одну секцию
    .elf": код ПЗУ физически не линкуется в прошивку (это часть кристалла), поэтому ЛЮБОЙ
    адрес вне линкованных секций формально прошёл бы такую негативную проверку - в том числе
    мусорный/битый адрес от ошибки чтения литерала. Здесь же сверка ПОЗИТИВНАЯ: адрес должен
    буквально совпасть с тем, что перечислил производитель тулчейна как реальную ROM-функцию.
    """
    chip = "esp32s3" if env_name.endswith("_s3") else "esp32"
    ld_dir = PACKAGES / "framework-arduinoespressif32" / "tools" / "sdk" / chip / "ld"
    symbols: dict[int, str] = {}
    for ld_file in sorted(ld_dir.glob(f"{chip}.rom*.ld")):
        text = ld_file.read_text(encoding="utf-8", errors="ignore")
        for match in ROM_LD_ENTRY_RE.finditer(text):
            try:
                symbols[int(match.group(2), 16)] = match.group(1)
            except ValueError:
                continue
    return symbols


def read_word(objdump: Path, elf: Path, address: int) -> int | None:
    dump = run_tool(objdump, "-s", f"--start-address={address:#x}", f"--stop-address={address + 4:#x}", str(elf))
    for line in dump.splitlines():
        match = re.match(r"\s*([0-9a-f]{8}) ([0-9a-f]{8})", line)
        if match and int(match.group(1), 16) == address:
            raw = match.group(2)
            return int("".join(reversed([raw[i:i + 2] for i in range(0, 8, 2)])), 16)
    return None


def iram_functions(objdump: Path, elf: Path) -> dict[int, tuple[str, list[str]]]:
    """Все функции целиком в .iram0.text: адрес начала -> (имя, инструкции тела).

    Разбирается вся секция за один проход objdump, а не по одной функции - иначе на
    каждый шаг обхода графа вызовов понадобился бы отдельный вызов инструмента."""
    listing = run_tool(objdump, "-d", "--section=.iram0.text", str(elf)).splitlines()
    functions: dict[int, tuple[str, list[str]]] = {}
    addr: int | None = None
    name = ""
    body: list[str] = []
    for line in listing:
        match = FUNC_HEADER_RE.match(line)
        if match:
            if addr is not None:
                functions[addr] = (name, body)
            addr = int(match.group(1), 16)
            name = match.group(2)
            body = []
            continue
        if addr is not None and line.strip():
            body.append(line)
    if addr is not None:
        functions[addr] = (name, body)
    return functions


def _trace_callx_source(body: list[str], callx_idx: int, register: str) -> tuple[int, int] | None:
    """Ищет l32r, загрузивший РЕГИСТР непосредственно перед callx на позиции callx_idx, в
    пределах CALLX_TRACE_WINDOW инструкций того же базового блока (см. module docstring).

    НЕ анализ потока данных - при малейшем сомнении возвращает None:
      - другой l32r/переход между целевым l32r и callx (распознаётся по "<...>" в строке -
        так objdump помечает вызовы/переходы/l32r, но l32r с ЧУЖИМ регистром тоже попадёт
        под этот стоп-сигнал, и это осознанный компромисс в пользу "не нашли" вместо "нашли
        неверно");
      - окно исчерпано.
    Возвращает (индекс строки l32r, адрес литерал-пула) или None."""
    for offset in range(1, CALLX_TRACE_WINDOW + 1):
        idx = callx_idx - offset
        if idx < 0:
            return None
        line = body[idx]
        l32r = L32R_REG_RE.search(line)
        if l32r and l32r.group(1) == register:
            return idx, int(l32r.group(2), 16)
        if CONTROL_FLOW_HINT_RE.search(line):
            return None
    return None


def _insn_mnemonic(line: str) -> str:
    """Извлекает мнемонику инструкции из строки дизассемблера.

    Два реальных формата в этом файле: настоящий objdump - "адрес:\tбайты-кода\tмнемоника\t
    операнды" (байты-кода - отдельная колонка), и упрощённые синтетические строки selftest -
    "адрес:\tмнемоника\tоперанды" (колонки байт-кода нет вовсе). Различаем их не по числу
    колонок (это было бы двумя путями кода на один и тот же смысл), а по содержимому: вторая
    колонка настоящего objdump-формата состоит ТОЛЬКО из шестнадцатеричных цифр - если это
    так, мнемоника - следующая колонка, иначе сама вторая колонка."""
    parts = line.split("\t")
    if len(parts) < 2:
        return ""
    candidate = parts[1].strip()
    if len(parts) >= 3 and re.fullmatch(r"[0-9a-f]+", candidate):
        candidate = parts[2].strip()
    return candidate.split()[0] if candidate else ""


def _is_control_transfer_mnemonic(mnemonic: str) -> bool:
    """True для мнемоник, передающих управление КУДА-ТО ЕЩЁ (переход/возврат/цикл) - список
    остановки для _trace_forward_call_target(). call/callx сюда сознательно не входят - вызов
    это как раз то, что там ищут, он обработан отдельно в самой функции. На Xtensa ЛЮБАЯ
    мнемоника условного перехода начинается с "b" (beqz/bnez/bge/blt/ball/bbci/... - весь
    набор перечислять смысла нет, префикса достаточно и это безопасно: проверяется УЖЕ
    выделенная мнемоника - см. _insn_mnemonic, - а не сырой текст строки, где похожий на "b…"
    фрагмент мог бы случайно найтись в байтах кода или в операнде)."""
    base = mnemonic.split(".", 1)[0]  # "bnez.n" -> "bnez", "ret.n" -> "ret"
    return base in {"j", "jx", "ret", "retw", "loop", "loopnez", "loopgtz"} or base.startswith("b")


def _trace_forward_call_target(body: list[str], literal_idx: int, window: int = CALLX_TRACE_WINDOW) -> str | None:
    """Ищет ближайший ВПЕРЁД call (не callx) в пределах window инструкций от literal_idx -
    проверяет догадку "этот литерал - аргумент, переданный вот этому вызову". Останов на
    первой же инструкции, реально передающей управление (branch/jump/ret/loop/callx/другой
    call) - тот же принцип "при малейшем сомнении - не нашли", что и у _trace_callx_source(),
    только вперёд по потоку инструкций, а не назад (см. её docstring). Инструкции между
    литералом и вызовом (l32r других аргументов, movi и т.п.) не останавливают поиск - именно
    так реально выглядит подготовка нескольких аргументов подряд перед call8.

    Возвращает шестнадцатеричный адрес цели call (как в CALL_RE.group(1)) или None."""
    for offset in range(1, window + 1):
        idx = literal_idx + offset
        if idx >= len(body):
            return None
        mnemonic = _insn_mnemonic(body[idx])
        if not mnemonic:
            continue
        if mnemonic.startswith("call") and not mnemonic.startswith("callx"):
            call_m = CALL_RE.search(body[idx])
            return call_m.group(1) if call_m else None
        if mnemonic.startswith("callx") or _is_control_transfer_mnemonic(mnemonic):
            return None
    return None


def trusted_flash_target_reason(
    func_name: str,
    idx: int,
    body: list[str],
    target_addr: int,
    symbol_name: Callable[[int], str],
    psram_clear: bool,
) -> str | None:
    """Решает, применимо ли доверенное исключение (TRUSTED_VENDOR_EXCEPTIONS) к КОНКРЕТНОМУ
    обращению во флеш на позиции idx тела func_name - вызывается ИЗ analyze_call_graph() в
    точности там, где иначе это обращение попало бы в problems. Возвращает имя разрешённой
    цели (для отчёта о применённых исключениях) или None (исключение не применяется, значит
    остаётся обычным нарушением).

    Не "этой функции можно всё": функция должна быть ключом TRUSTED_VENDOR_EXCEPTIONS, а имя
    ЦЕЛИ - в её персональном наборе. Для callx (body[idx] - строка callx, target_addr - уже
    прослеженная через l32r цель, см. _trace_callx_source) имя цели сверяется напрямую. Для
    обычного литерала (body[idx] - строка l32r, target_addr - адрес самих ДАННЫХ, не функции)
    целью считается ближайший call ВПЕРЁД по потоку (_trace_forward_call_target) - литерал
    сам по себе не цель, а аргумент, переданный вызову.

    psram_clear=False снимает "compare_and_set_extram" из разрешённых целей независимо от
    имени функции (см. find_psram_usage() и комментарий у TRUSTED_VENDOR_EXCEPTIONS) - это
    единственная цель в списке, чья безопасность зависит от предпосылки, проверяемой не
    структурой кода, а фактом использования PSRAM в проекте."""
    allowed = set(TRUSTED_VENDOR_EXCEPTIONS.get(func_name, ()))
    if not psram_clear:
        allowed.discard("compare_and_set_extram")
    if not allowed:
        return None
    if CALLX_RE.search(body[idx]):
        name = symbol_name(target_addr)
        return name if name in allowed else None
    target_hex = _trace_forward_call_target(body, idx)
    if target_hex is None:
        return None
    name = symbol_name(int(target_hex, 16))
    return name if name in allowed else None


def analyze_call_graph(
    start_addr: int,
    iram_funcs: dict[int, tuple[str, list[str]]],
    section_of: Callable[[int], str],
    symbol_name: Callable[[int], str],
    read_literal: Callable[[int], int | None],
    in_flash: Callable[[int], bool],
    in_rom: Callable[[int], bool],
    trusted_exception: Callable[[str, int, list[str], int], str | None] | None = None,
) -> tuple[list[str], list[str], set[int], int, list[str]]:
    """Обход графа вызовов вглубь начиная с start_addr.

    Разворачивается только по функциям, чьё тело есть в iram_funcs (обычно .iram0.text) -
    за их пределами разбирать нечего (тело недоступно для дальнейшего анализа), а вызов во
    флеш и так уже сам по себе нарушение независимо от того, что там дальше. Множество
    visited защищает от зацикливания на рекурсивных/взаимных вызовах: каждый адрес
    обрабатывается не больше одного раза.

    callx-инструкции сначала пытаются быть прослежены до константного адреса через
    _trace_callx_source() (см. её docstring и module docstring). Прослеженная (или прямая
    call-) цель классифицируется по секции: IRAM/ПЗУ - безопасно (для IRAM обход идёт дальше
    рекурсивно), флеш - нарушение (problems), не прослежено или секция не опознана -
    нарушение (callx_problems, "недоказуемо"). l32r, использованный для трассировки
    конкретного callx, не разбирается ещё раз как "обычный" литерал - иначе одна и та же
    проблема попала бы в отчёт дважды.

    trusted_exception(func_name, idx, body, target_addr), если передан, вызывается ровно в
    двух точках ниже - непосредственно перед тем, как обращение во флеш иначе попало бы в
    problems (для callx target_addr - прослеженная цель вызова, для литерала - адрес самих
    данных). Если он вернул имя цели (не None), обращение уходит в applied_exceptions вместо
    problems - это НЕ отдельный обход, а точечная замена вердикта для конкретной инструкции;
    остальная классификация (IRAM/ПЗУ/недоказуемо) не затронута и не может быть замаскирована
    таким образом.

    Возвращает (нарушения-обращения-во-флеш, нарушения-callx/недоказуемо, посещённые
    адреса, суммарное число разобранных инструкций, применённые доверенные исключения).
    """
    problems: list[str] = []
    callx_problems: list[str] = []
    applied_exceptions: list[str] = []
    visited: set[int] = set()
    queue = [start_addr]
    instruction_count = 0
    while queue:
        addr = queue.pop()
        if addr in visited:
            continue
        visited.add(addr)
        entry = iram_funcs.get(addr)
        if entry is None:
            continue
        name, body = entry
        instruction_count += len(body)

        # Первый проход по телу: для каждого callx находим породивший его l32r (если
        # получилось) и помечаем этот l32r как "уже разобран в контексте callx" - см. выше.
        callx_trace: dict[int, tuple[int, int] | None] = {}
        consumed_l32r_idx: set[int] = set()
        for idx, line in enumerate(body):
            callx_m = CALLX_RE.search(line)
            if not callx_m:
                continue
            traced = _trace_callx_source(body, idx, callx_m.group(1))
            callx_trace[idx] = traced
            if traced is not None:
                consumed_l32r_idx.add(traced[0])

        for idx, line in enumerate(body):
            insn_match = INSN_ADDR_RE.match(line)
            insn_addr = insn_match.group(1) if insn_match else "?"

            callx_m = CALLX_RE.search(line)
            if callx_m:
                traced = callx_trace.get(idx)
                if traced is None:
                    callx_problems.append(
                        f"{name} @ 0x{insn_addr}: не удалось проследить цель callx (регистр "
                        f"{callx_m.group(1)}) через ближайший l32r - статически недоказуемо, "
                        "что вызов безопасен"
                    )
                    continue
                _l32r_idx, pool_addr = traced
                target = read_literal(pool_addr)
                if target is None:
                    callx_problems.append(
                        f"{name} @ 0x{insn_addr}: не удалось прочитать литерал по адресу "
                        f"{pool_addr:#x} (источник callx через l32r)"
                    )
                elif in_flash(target):
                    reason = trusted_exception(name, idx, body, target) if trusted_exception else None
                    if reason:
                        applied_exceptions.append(reason)
                    else:
                        problems.append(
                            f"{name} @ 0x{insn_addr}: косвенный вызов (l32r -> callx) ведёт на "
                            f"{target:#x} ({symbol_name(target)}) в {section_of(target)}"
                        )
                elif in_rom(target):
                    pass  # ПЗУ - безопасно; тела для рекурсии нет, это не часть .elf.
                elif "iram" in section_of(target).lower():
                    if target in iram_funcs and target not in visited:
                        queue.append(target)
                else:
                    callx_problems.append(
                        f"{name} @ 0x{insn_addr}: цель косвенного вызова {target:#x} "
                        f"(секция {section_of(target)}) не опознана ни как IRAM, ни как ПЗУ - "
                        "безопасность не доказана"
                    )
                continue

            if idx in consumed_l32r_idx:
                continue  # уже разобран выше как источник конкретного callx

            call = CALL_RE.search(line)
            if call:
                target = int(call.group(1), 16)
                if in_flash(target):
                    problems.append(
                        f"{name} @ 0x{insn_addr}: вызов {target:#x} ({symbol_name(target)}) в {section_of(target)}"
                    )
                elif target in iram_funcs and target not in visited:
                    queue.append(target)
                continue

            literal = LITERAL_RE.search(line)
            if literal:
                address = int(literal.group(1), 16)
                value = read_literal(address)
                if value is None:
                    problems.append(f"{name} @ 0x{insn_addr}: не удалось прочитать литерал по адресу {address:#x}")
                elif in_flash(value):
                    reason = trusted_exception(name, idx, body, value) if trusted_exception else None
                    if reason:
                        applied_exceptions.append(reason)
                    else:
                        problems.append(
                            f"{name} @ 0x{insn_addr}: адрес {value:#x} ({symbol_name(value)}) в {section_of(value)}"
                        )
    return problems, callx_problems, visited, instruction_count, applied_exceptions


def detect_core_status() -> tuple[str, str]:
    """Определяет версию Arduino core ПО ФАКТУ.

    Источник - core_version.h реально установленного пакета framework-arduinoespressif32.
    Это тот же заголовок, который компилятор подключал при сборке .elf в .pio/build:
    platformio.ini пинит ОДНУ версию пакета через platform_packages и наследует её во всех
    7 окружениях (extends = env:Samovar), отдельного пакета на окружение нет - значит
    единственный установленный пакет надёжно отражает то, чем всё было собрано. Не
    хардкодим "сейчас 2.x, значит всё ок" - читаем макрос ARDUINO_ESP32_GIT_DESC и по
    старшей цифре решаем, применима ли посекционная проверка .elf (для core 3.x она не
    годится - IRAM-размещение там управляется конфигурацией IDF, а не набором атрибутов,
    которые отражаются в .iram0.text так же, как в 2.x).
    """
    if not CORE_VERSION_HEADER.exists():
        return "error", f"core_version.h не найден ({CORE_VERSION_HEADER}) - пакет framework-arduinoespressif32 не установлен"
    text = CORE_VERSION_HEADER.read_text(encoding="utf-8", errors="ignore")
    match = CORE_VERSION_RE.search(text)
    if not match:
        return "error", f"не удалось прочитать ARDUINO_ESP32_GIT_DESC из {CORE_VERSION_HEADER}"
    version = match.group(1)
    major_match = re.match(r"(\d+)", version)
    if not major_match:
        return "error", f"не удалось разобрать номер версии {version!r} из {CORE_VERSION_HEADER}"
    major = int(major_match.group(1))
    if major >= 3:
        return "skip", f"проверка неприменима для core {version} (>= 3.x, IRAM управляется конфигурацией IDF)"
    return "ok", f"core {version}"


def check_env(env_name: str) -> tuple[bool, str]:
    """Возвращает (True, сообщение) для ok/skip и (False, сообщение) для fail/error -
    тройное состояние для печати ("OK"/"ПРОПУСК"/"ОШИБКА") различает main() отдельным
    вызовом detect_core_status(), не расширяя эту сигнатуру: check_env() - публичный
    контракт (см. tools/smoke_ci_contract.py::StepperIsrCliTests), менять его форму нет
    причины - skip не является провалом проверки, поэтому логически он тоже True."""
    core_status, core_message = detect_core_status()
    if core_status == "error":
        return False, f"{env_name}: {core_message}"
    if core_status == "skip":
        return True, f"{env_name}: {core_message}"

    elf = BUILD_DIR / env_name / "firmware.elf"
    if not elf.exists():
        return False, f"{env_name}: не найден {elf} - окружение не собрано"
    prefix = toolchain_prefix(env_name)
    objdump = Path(str(prefix) + "objdump")
    nm = Path(str(prefix) + "nm")
    if not objdump.exists():
        return False, f"{env_name}: не найден {objdump}"

    iram_funcs = iram_functions(objdump, elf)
    isr_addr = None
    for addr, (name, _body) in iram_funcs.items():
        if name == ISR_SYMBOL:
            isr_addr = addr
            break
    if isr_addr is None:
        return False, f"{env_name}: {ISR_SYMBOL} отсутствует в .iram0.text (обработчик не в IRAM)"

    sections = section_map(objdump, elf)
    symbols = symbol_map(nm, elf)
    rom_syms = rom_symbols(env_name)

    def section_of(address: int) -> str:
        for name, vma, size in sections:
            if vma <= address < vma + size:
                return name
        return "?"

    def in_flash(address: int) -> bool:
        name = section_of(address)
        return any(marker in name for marker in FLASH_SECTION_MARKERS)

    def in_rom(address: int) -> bool:
        return address in rom_syms

    def symbol_name(address: int) -> str:
        # nm(elf) уже включает и обычные, и ROM-символы (ROM видна как абсолютный 'A'-символ,
        # если хоть один вызов её резолвнул при линковке) - rom_syms как запасной источник на
        # случай ROM-адреса, который линковщик знает (мы читаем из тех же *.rom*.ld), но по
        # какой-то причине не отразил в таблице символов .elf.
        return symbols.get(address) or rom_syms.get(address, "?")

    def read_literal(address: int) -> int | None:
        return read_word(objdump, elf, address)

    # Считается один раз на процесс (см. @functools.lru_cache у find_psram_usage) - гейт
    # исключения compare_and_set_extram (см. TRUSTED_VENDOR_EXCEPTIONS): найден хоть один
    # признак работы с PSRAM в исходниках проекта - исключение снимается для ЭТОГО прогона.
    psram_hits = find_psram_usage(ROOT)

    def trusted_exception(func_name: str, idx: int, body: list[str], target_addr: int) -> str | None:
        return trusted_flash_target_reason(func_name, idx, body, target_addr, symbol_name, not psram_hits)

    problems, callx_problems, visited, instruction_count, applied_exceptions = analyze_call_graph(
        isr_addr, iram_funcs, section_of, symbol_name, read_literal, in_flash, in_rom, trusted_exception
    )

    psram_note = ""
    if psram_hits:
        psram_note = (
            "\n    ПРЕДПОСЫЛКА PSRAM НАРУШЕНА - исключение compare_and_set_extram снято "
            "(найдены признаки работы с PSRAM в исходниках проекта):\n        "
            + "\n        ".join(psram_hits)
        )

    if callx_problems:
        return False, (
            f"{env_name}: обработчик содержит недоказуемые косвенные вызовы (callx) - не "
            "удалось статически подтвердить, что цель безопасна (IRAM/ПЗУ):\n    "
            + "\n    ".join(callx_problems) + psram_note
        )
    if problems:
        return False, f"{env_name}: обработчик обращается во флеш:\n    " + "\n    ".join(problems) + psram_note

    exception_note = ""
    if applied_exceptions:
        counts = Counter(applied_exceptions)
        exception_note = ", применены доверенные исключения (TRUSTED_VENDOR_EXCEPTIONS): " + ", ".join(
            f"{target_name} x{n}" for target_name, n in sorted(counts.items())
        )
    return True, (
        f"{env_name}: обращений во флеш нет ({instruction_count} инструкций, "
        f"{len(visited)} функций в графе вызовов от {ISR_SYMBOL}{exception_note})"
    )


def _selftest_check(failures: list[str], label: str, condition: bool, detail: str = "") -> None:
    if not condition:
        failures.append(f"{label}" + (f" ({detail})" if detail else ""))


def run_selftest() -> int:
    """Самопроверка на синтетическом (без .elf) входе.

    Доказывает, что analyze_call_graph() реально разворачивает граф вызовов вглубь (а не
    только смотрит тело стартовой функции), останавливается на циклах, не теряет call12 (в
    исходном варианте проверки регэксп call[048] его не распознавал), и что callx
    классифицируется по прослеженной через l32r цели (IRAM/ПЗУ - безопасно, флеш и
    "не удалось проследить" - нарушение), а не огульно.

    Сценарии 5-10 доказывают то же самое про TRUSTED_VENDOR_EXCEPTIONS: применяется, когда
    и функция, и цель совпали (5 - литерал-аргумент __assert_func, 6 - callx на
    compare_and_set_extram), снимается при найденном использовании PSRAM (7), НЕ маскирует
    ни новую цель у доверенной функции (8), ни ту же цель у НЕдоверенной (9) - список пар
    "функция -> цели", а не огульное доверие; 10 проверяет сам сканер find_psram_usage() на
    реальной файловой системе (временный каталог), а не только логику гейта."""
    failures: list[str] = []

    # 1. Нарушение спрятано на ВТОРОМ уровне вызовов: FuncA (в IRAM) зовёт FuncB (в IRAM),
    #    FuncB зовёт адрес во флеше. Проверка теле FuncA ничего не найдёт - нужен обход.
    two_level_funcs = {
        0x1000: ("FuncA", ["    1000:\tcall4\t1100 <FuncB>"]),
        0x1100: ("FuncB", ["    1100:\tcall8\t2000 <DangerousFlashFunc>"]),
    }
    def flash_section_of(addr: int) -> str:
        return ".flash.text" if addr == 0x2000 else ".iram0.text"
    def flash_in(addr: int) -> bool:
        return "flash" in flash_section_of(addr)
    def flash_symbol(addr: int) -> str:
        return {0x2000: "DangerousFlashFunc"}.get(addr, "?")

    problems, callx_problems, visited, _count, _applied = analyze_call_graph(
        0x1000, two_level_funcs, flash_section_of, flash_symbol, lambda a: None, flash_in, lambda a: False
    )
    _selftest_check(
        failures, "рекурсия не нашла нарушение на 2 уровне вызовов",
        any("DangerousFlashFunc" in p and "FuncB" in p for p in problems), str(problems),
    )
    _selftest_check(
        failures, "рекурсия не дошла до FuncB (обход не развернулся вглубь)",
        visited == {0x1000, 0x1100}, str(visited),
    )
    _selftest_check(failures, "ложный callx там, где его нет", not callx_problems, str(callx_problems))

    # 2. Цикл: FuncA зовёт FuncB, FuncB зовёт обратно FuncA. Без visited это обход без конца.
    cyclic_funcs = {
        0x1000: ("FuncA", ["    1000:\tcall4\t1100 <FuncB>"]),
        0x1100: ("FuncB", ["    1100:\tcall4\t1000 <FuncA>"]),
    }
    problems2, callx2, visited2, _count2, _applied2 = analyze_call_graph(
        0x1000, cyclic_funcs, lambda a: ".iram0.text", lambda a: "?", lambda a: None, lambda a: False, lambda a: False
    )
    _selftest_check(failures, "обход зациклился/не завершился на взаимной рекурсии", visited2 == {0x1000, 0x1100})
    _selftest_check(failures, "цикл дал ложные нарушения", not problems2 and not callx2)

    # 3a. callx, чья цель прослежена через l32r ПРЯМО В IRAM (соседняя функция) - НЕ
    #     нарушение, и обход обязан развернуться в найденную функцию (как для call).
    #     Регресс на реальный случай 1 (StepperTicker -> esp_rom_delay_us) сделан бы этим
    #     тестом, если бы цель была ПЗУ, а не IRAM - для ПЗУ есть отдельный сценарий 3d.
    traced_iram_funcs = {
        0x1000: ("FuncTracedCallxIram", ["    1000:\tl32r\ta8, 3000 <SomeFuncPtr>", "    1004:\tcallx8\ta8"]),
        0x1200: ("TracedIramTarget", []),
    }
    problems3a, callx3a, visited3a, _c3a, _a3a = analyze_call_graph(
        0x1000, traced_iram_funcs, lambda a: ".iram0.text", lambda a: "?",
        lambda a: 0x1200 if a == 0x3000 else None, lambda a: False, lambda a: False,
    )
    _selftest_check(
        failures, "callx с целью в IRAM (прослежена через l32r) ошибочно помечен нарушением",
        not callx3a and not problems3a, str(callx3a) + str(problems3a),
    )
    _selftest_check(
        failures, "обход не развернулся в IRAM-цель, прослеженную через callx",
        0x1200 in visited3a, str(visited3a),
    )

    # 3b. callx, чья цель прослежена через l32r и ведёт во флеш - нарушение (в общем списке
    #     проблем "обращение во флеш", а не в отдельном списке "недоказуемо" - цель как раз
    #     доказана, просто она небезопасна). Регресс на реальный случай 3 (compare_and_set_
    #     extram): l32r действительно грузит адрес, который затем реально ведёт в .flash.text.
    traced_flash_funcs = {
        0x1000: ("FuncTracedCallxFlash", ["    1000:\tl32r\ta8, 3000 <SomeFuncPtr>", "    1004:\tcallx8\ta8"]),
    }
    def flash3b_section(a: int) -> str:
        return ".flash.text" if a == 0x2000 else ".iram0.text"
    problems3b, callx3b, _v3b, _c3b, _a3b = analyze_call_graph(
        0x1000, traced_flash_funcs, flash3b_section, lambda a: "DangerousViaCallx",
        lambda a: 0x2000 if a == 0x3000 else None, lambda a: "flash" in flash3b_section(a), lambda a: False,
    )
    _selftest_check(
        failures, "callx с целью во флеше (прослежена через l32r) не помечен нарушением",
        len(problems3b) == 1 and not callx3b, str(problems3b) + str(callx3b),
    )

    # 3c. callx БЕЗ прослеживаемого источника - нарушение "недоказуемо" (как раньше для
    #     любого callx, но теперь только для этого случая). l32r здесь грузит ДРУГОЙ регистр
    #     (a9, не a8) - именно так на реальном коде выглядит "не нашли": он либо отсутствует,
    #     либо адресован не в тот регистр, который использует сам callx.
    untraceable_funcs = {
        0x1000: ("FuncUntraceableCallx", ["    1000:\tl32r\ta9, 3000 <UnrelatedPtr>", "    1004:\tcallx8\ta8"]),
    }
    # l32r грузит a9, а не a8 - для callx (a8) это "не нашли", но сам по себе l32r в a9 -
    # обычный безопасный литерал (не флеш), читаем ему валидное значение, иначе тест поймает
    # ПОСТОРОННЮЮ проблему ("не удалось прочитать литерал") вместо целевого сценария.
    problems3c, callx3c, _v3c, _c3c, _a3c = analyze_call_graph(
        0x1000, untraceable_funcs, lambda a: ".iram0.text", lambda a: "?",
        lambda a: 0x1200 if a == 0x3000 else None, lambda a: False, lambda a: False,
    )
    _selftest_check(
        failures, "callx без прослеживаемого l32r в свой регистр не помечен нарушением",
        len(callx3c) == 1 and not problems3c, str(callx3c) + str(problems3c),
    )
    if callx3c:
        _selftest_check(failures, "в сообщении о недоказанном callx нет имени функции", "FuncUntraceableCallx" in callx3c[0], callx3c[0])
        _selftest_check(failures, "в сообщении о недоказанном callx нет адреса инструкции", "0x1004" in callx3c[0], callx3c[0])

    # 3d. callx, чья цель прослежена через l32r и ведёт в ПЗУ (ROM) - НЕ нарушение, рекурсия
    #     не требуется (у ROM нет тела в .elf). Регресс на реальный случай 1 дословно:
    #     StepperTicker -> esp_rom_delay_us по адресу 0x40008534.
    traced_rom_funcs = {
        0x1000: ("FuncTracedCallxRom", ["    1000:\tl32r\ta8, 3000 <RomFuncPtr>", "    1004:\tcallx8\ta8"]),
    }
    problems3d, callx3d, _v3d, _c3d, _a3d = analyze_call_graph(
        0x1000, traced_rom_funcs, lambda a: "?", lambda a: "esp_rom_delay_us",
        lambda a: 0x40008534 if a == 0x3000 else None, lambda a: False, lambda a: a == 0x40008534,
    )
    _selftest_check(
        failures, "callx с целью в ПЗУ (прослежена через l32r) ошибочно помечен нарушением",
        not callx3d and not problems3d, str(callx3d) + str(problems3d),
    )

    # 4. call12 - номер окна из двух цифр, старый регэксп call[048] его бы не заметил.
    call12_funcs = {
        0x1000: ("FuncCall12", ["    1000:\tcall12\t2000 <Target12>"]),
    }
    def call12_section_of(addr: int) -> str:
        return ".flash.text" if addr == 0x2000 else ".iram0.text"
    problems4, _callx4, _visited4, _count4, _a4 = analyze_call_graph(
        0x1000, call12_funcs, call12_section_of, lambda a: "Target12", lambda a: None,
        lambda a: "flash" in call12_section_of(a), lambda a: False,
    )
    _selftest_check(failures, "call12 не распознан (регэксп потерял двузначный номер окна)", any("Target12" in p for p in problems4))

    # 5. Положительный случай, дословно повторяющий реальный vPortExitCritical: доверенная
    #    функция грузит 3 литерала (аргументы __FILE__/__func__/выражение) и зовёт __assert_func
    #    - все три должны замаскироваться и попасть в applied, а НЕ в problems.
    trusted_literal_funcs = {
        0x1000: (
            "vPortExitCritical",
            [
                "    1000:\tl32r\ta13, 3000 <FileStr>",
                "    1004:\tmovi.n\ta11, 154",
                "    1008:\tl32r\ta12, 3004 <FuncStr>",
                "    100c:\tl32r\ta10, 3008 <ExprStr>",
                "    1010:\tcall8\t5000 <__assert_func>",
            ],
        ),
    }
    def assert_literal_section(a: int) -> str:
        return ".flash.rodata" if a in (0x9000, 0x9004, 0x9008) else ".iram0.text"
    def assert_literal_symbol(a: int) -> str:
        return "__assert_func" if a == 0x5000 else "?"
    problems5, callx5, _v5, _c5, applied5 = analyze_call_graph(
        0x1000, trusted_literal_funcs, assert_literal_section, lambda a: "?",
        lambda a: {0x3000: 0x9000, 0x3004: 0x9004, 0x3008: 0x9008}.get(a),
        lambda a: "flash" in assert_literal_section(a), lambda a: False,
        lambda fn, idx, body, addr: trusted_flash_target_reason(fn, idx, body, addr, assert_literal_symbol, True),
    )
    _selftest_check(
        failures, "аргументы __assert_func у доверенной vPortExitCritical ошибочно помечены нарушением",
        not problems5 and not callx5, str(problems5) + str(callx5),
    )
    _selftest_check(
        failures, "доверенное исключение __assert_func не применилось ко всем 3 аргументам",
        applied5.count("__assert_func") == 3, str(applied5),
    )

    # 6. Положительный случай, дословно повторяющий реальный xPortEnterCriticalTimeout: callx
    #    прослежен на compare_and_set_extram, PSRAM в проекте не используется (psram_clear=True)
    #    - должно замаскироваться.
    trusted_callx_funcs = {
        0x1000: ("xPortEnterCriticalTimeout", ["    1000:\tl32r\ta8, 3000 <PtrPool>", "    1004:\tcallx8\ta8"]),
    }
    def callx_flash_section(a: int) -> str:
        return ".flash.text" if a == 0x9000 else ".iram0.text"
    def callx_flash_symbol(a: int) -> str:
        return "compare_and_set_extram" if a == 0x9000 else "?"
    problems6, callx6, _v6, _c6, applied6 = analyze_call_graph(
        0x1000, trusted_callx_funcs, callx_flash_section, lambda a: "?",
        lambda a: 0x9000 if a == 0x3000 else None, lambda a: "flash" in callx_flash_section(a), lambda a: False,
        lambda fn, idx, body, addr: trusted_flash_target_reason(fn, idx, body, addr, callx_flash_symbol, True),
    )
    _selftest_check(
        failures, "compare_and_set_extram при чистом PSRAM (psram_clear=True) ошибочно помечен нарушением",
        not problems6 and not callx6, str(problems6) + str(callx6),
    )
    _selftest_check(
        failures, "доверенное исключение compare_and_set_extram не применилось", applied6 == ["compare_and_set_extram"], str(applied6),
    )

    # 7 (приёмка, п.3-в). Тот же callx, но find_psram_usage() нашла использование PSRAM в
    #    проекте (psram_clear=False) - предпосылка исключения снята, вызов остаётся нарушением.
    problems7, callx7, _v7, _c7, applied7 = analyze_call_graph(
        0x1000, trusted_callx_funcs, callx_flash_section, lambda a: "?",
        lambda a: 0x9000 if a == 0x3000 else None, lambda a: "flash" in callx_flash_section(a), lambda a: False,
        lambda fn, idx, body, addr: trusted_flash_target_reason(fn, idx, body, addr, callx_flash_symbol, False),
    )
    _selftest_check(
        failures, "compare_and_set_extram остался разрешён, хотя PSRAM в проекте найдена (psram_clear=False)",
        len(problems7) == 1 and not callx7 and not applied7, str(problems7) + str(callx7) + str(applied7),
    )

    # 8 (приёмка, п.3-а). У доверенной функции появилась НОВАЯ флеш-цель, которой нет в
    #    TRUSTED_VENDOR_EXCEPTIONS - литерал перед ret.n, а __assert_func вызывается ТОЛЬКО
    #    ПОСЛЕ этого перехода (двумя строками ниже, ещё в пределах окна трассировки). Если бы
    #    forward-трассировка не останавливалась на переходах (реальная мутация, пойманная при
    #    ручной проверке этого инструмента - trace прошла бы "сквозь" ret.n и ошибочно
    #    приписала бы литерал этому дальнему call), тест ниже покраснел бы: len(problems8)
    #    стал бы 0. Голого "call ведёт не туда" (как раньше) недостаточно - нужна была именно
    #    ПРОВЕРКА остановки на переходе, отдельная от проверки самого имени цели.
    unknown_target_funcs = {
        0x1000: (
            "xPortEnterCriticalTimeout",
            [
                "    1000:\tl32r\ta13, 3000 <SomeNewDiagString>",
                "    1004:\tret.n",
                "    1006:\tcall8\t5000 <__assert_func>",
            ],
        ),
    }
    def unknown_literal_section(a: int) -> str:
        return ".flash.rodata" if a == 0x9000 else ".iram0.text"
    def unknown_literal_symbol(a: int) -> str:
        return "__assert_func" if a == 0x5000 else "SomeNewDiagString"
    problems8, callx8, _v8, _c8, applied8 = analyze_call_graph(
        0x1000, unknown_target_funcs, unknown_literal_section, unknown_literal_symbol,
        lambda a: 0x9000 if a == 0x3000 else None, lambda a: "flash" in unknown_literal_section(a), lambda a: False,
        lambda fn, idx, body, addr: trusted_flash_target_reason(fn, idx, body, addr, unknown_literal_symbol, True),
    )
    _selftest_check(
        failures,
        "литерал замаскирован по call __assert_func, лежащему ЗА переходом (ret.n) - "
        "forward-трассировка обязана останавливаться на переходах, а не идти сквозь них",
        len(problems8) == 1 and not callx8 and not applied8, str(problems8) + str(callx8) + str(applied8),
    )

    # 9 (приёмка, п.3-б). Тот же паттерн "литерал -> call __assert_func", что и в сценарии 5,
    #    но у ФУНКЦИИ, которой нет в TRUSTED_VENDOR_EXCEPTIONS - имя цели совпадает с
    #    разрешённым у ДРУГИХ функций, но само по себе это не пропуск: список пар
    #    "функция -> цели", а не "эта цель безопасна где угодно".
    untrusted_func_funcs = {
        0x1000: ("SomeOtherIsrHelper", ["    1000:\tl32r\ta13, 3000 <Str>", "    1004:\tcall8\t5000 <__assert_func>"]),
    }
    problems9, callx9, _v9, _c9, applied9 = analyze_call_graph(
        0x1000, untrusted_func_funcs, unknown_literal_section, lambda a: "?",
        lambda a: 0x9000 if a == 0x3000 else None, lambda a: "flash" in unknown_literal_section(a), lambda a: False,
        lambda fn, idx, body, addr: trusted_flash_target_reason(fn, idx, body, addr, assert_literal_symbol, True),
    )
    _selftest_check(
        failures, "флеш-обращение у НЕдоверенной функции замаскировано исключением по одному лишь имени цели",
        len(problems9) == 1 and not callx9 and not applied9, str(problems9) + str(callx9) + str(applied9),
    )

    # 10. find_psram_usage() - реальное сканирование файловой системы, а не заглушка: во
    #     временном каталоге с одним маркером PSRAM должен найтись ровно он, а libraries/
    #     обязана быть исключена, даже если маркер лежит именно там.
    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        (tmp_root / "real_code.h").write_text("void* p = ps_malloc(16);\n", encoding="utf-8")
        (tmp_root / "libraries").mkdir()
        (tmp_root / "libraries" / "vendor.h").write_text("void* p = ps_malloc(16);\n", encoding="utf-8")
        hits10 = find_psram_usage(tmp_root)
    _selftest_check(
        failures, "find_psram_usage не находит реальный маркер PSRAM в исходнике проекта",
        any("real_code.h" in h and "ps_malloc" in h for h in hits10), str(hits10),
    )
    _selftest_check(
        failures, "find_psram_usage не исключает libraries/ из сканирования",
        not any("libraries" in h for h in hits10), str(hits10),
    )

    if failures:
        print("Самопроверка check_stepper_isr_iram.py: ЕСТЬ ОШИБКИ")
        for failure in failures:
            print(f" - {failure}")
        return 1
    print(
        "Самопроверка check_stepper_isr_iram.py: все сценарии пройдены "
        "(рекурсия, защита от цикла, трассировка callx в IRAM/ПЗУ/флеш/недоказуемо, call12, "
        "доверенные исключения __assert_func/compare_and_set_extram, гейт по PSRAM, "
        "сканирование find_psram_usage)"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "environments",
        nargs="*",
        help="имена окружений platformio.ini для проверки (обязательны, без умолчаний по .pio/build)",
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="самопроверка на синтетическом входе, без сборки и без .elf",
    )
    args = parser.parse_args()

    if args.selftest:
        return run_selftest()

    if not args.environments:
        # Текст должен содержать "required" - см. tools/smoke_ci_contract.py::
        # StepperIsrCliTests.test_environments_argument_is_required_not_defaulted_from_build_dir.
        parser.error("environments: at least one is required (or use --selftest)")

    # detect_core_status() лёгкий (одно чтение маленького заголовка) - второй вызов
    # здесь только ради подписи в выводе (OK/ПРОПУСК/ОШИБКА), не влияет на check_env().
    core_status, _core_message = detect_core_status()
    failed = False
    for env_name in args.environments:
        ok, message = check_env(env_name)
        if core_status == "skip":
            label = "ПРОПУСК "
        elif ok:
            label = "OK   "
        else:
            label = "ОШИБКА "
            failed = True
        print(label + message)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
