#!/usr/bin/env python3
"""T02: блокер №2 (переполнение uint8_t CurMin давало сброс LCD раз в 256 с
вместо заявленных 120 с) + п.17 Уровня 2 (двойная инициализация lcd.init()
после lcd.begin() перебивала настройки шины) + Н3 (mode_dispatch_alarm()
вызывался последним в такте SysTicker, после кэша I2C и записи лога, а не
сразу после чтения датчиков; таймаут ожидания мьютекса I2C для фонового
обновления кэша был общим с таймаутом записи пользовательской конфигурации).

Проверки (все - вытаскиванием реальных тел функций/констант из исходников,
без переписывания логики в тесте):
  1. encoder_getvalue() (Menu.ino) больше не сравнивает CurMin == 120 (uint8_t,
     переполняется каждые 256 с), а использует дедлайн next_lcd_reset_ms.
  2. Samovar_ini.h объявляет #define LCD_RESET_PERIOD_MS (значение не пиним -
     это решение координатора, а не то, что тест обязан перепроверять).
  3. menu_reset_lcd() (Menu.ino) зовёт lcd.begin(20, 4) и не зовёт lcd.init() -
     init() внутри библиотеки сам вызывает Wire.begin()/begin(), вторая
     задержка ~1 с и сброс настроек шины, выставленных в setup().
  4. setup_wifi_stack_defaults() (Samovar.ino) настраивает Wire.setClock(100000)
     и Wire.setTimeOut(10) сразу после Wire.begin(LCD_SDA, LCD_SCL).
  5. В triggerSysTicker() (Samovar.ino) mode_dispatch_alarm() вызывается раньше
     первого refresh_i2c_stepper_cache( и раньше append_data() - аварийные
     проверки должны реагировать сразу после чтения датчиков, а не после того,
     как такт уже потратил время на кэш I2C и запись лога.
  6. refresh_i2c_stepper_cache() (Samovar.ino) передаёт в i2c_stepper_refresh()
     укороченный таймаут I2C_CACHE_LOCK_WAIT_MS (100 мс), а не таймаут по
     умолчанию (I2C_LOCK_WAIT_MS = 1000 мс, общий с записью конфигурации).
  7. setupMenu() (Menu.ino) зовёт lcd.begin(LCD_COLUMNS, LCD_ROWS) и не зовёт
     lcd.init() - setupMenu() выполняется в setup() ПОСЛЕ Wire.setClock/setTimeOut
     (setup_wifi_stack_defaults() вызывается раньше setup_init_menu_display_and_chip_id()),
     так что lcd.init() из библиотеки перебивал бы уже выставленные настройки шины.

Содержательность каждой проверки подтверждена мутацией: тело реальной функции
берётся из файла, точечно мутируется в памяти обратно к старому (сломанному)
варианту, и проверяется, что соответствующая check-функция теперь падает с
осмысленным сообщением, а не молча пропускает регресс.
"""
import sys
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]
MENU_PATH = ROOT / "Menu.ino"
SAMOVAR_INI_PATH = ROOT / "Samovar_ini.h"
SAMOVAR_INO_PATH = ROOT / "Samovar.ino"

ENCODER_SIGNATURE = "void encoder_getvalue()"
MENU_RESET_LCD_SIGNATURE = "void menu_reset_lcd()"
SETUP_MENU_SIGNATURE = "void setupMenu()"
SETUP_WIFI_SIGNATURE = "static void setup_wifi_stack_defaults()"
TRIGGER_SYSTICKER_SIGNATURE = "void triggerSysTicker(void *parameter)"
CACHE_REFRESH_SIGNATURE = "static void refresh_i2c_stepper_cache(I2CStepperDevice& device)"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# --- 1. encoder_getvalue(): дедлайн вместо переполняющегося CurMin == 120 -------------------
def check_lcd_reset_deadline(body: str, errors: list[str]) -> None:
    if "CurMin == 120" in body:
        errors.append(
            "encoder_getvalue: остался переполняющийся uint8_t-компаратор CurMin == 120 "
            "(срабатывает раз в 256 с из-за переполнения uint8_t, а не раз в заявленный период)"
        )
    if "next_lcd_reset_ms" not in body:
        errors.append("encoder_getvalue: нет дедлайн-переменной next_lcd_reset_ms")
        return
    require_ordered_tokens(
        "encoder_getvalue lcd reset deadline",
        body,
        [
            "static uint32_t next_lcd_reset_ms = LCD_RESET_PERIOD_MS;",
            "if ((int32_t)(millis() - next_lcd_reset_ms) >= 0) {",
            "menu_reset_lcd();",
            "next_lcd_reset_ms += LCD_RESET_PERIOD_MS;",
        ],
        errors,
    )


# --- 2. Samovar_ini.h: #define LCD_RESET_PERIOD_MS (значение не пиним) ----------------------
def check_lcd_reset_period_define(ini_source: str, errors: list[str]) -> None:
    if "#define LCD_RESET_PERIOD_MS" not in ini_source:
        errors.append("Samovar_ini.h: нет #define LCD_RESET_PERIOD_MS")


# --- 3. menu_reset_lcd(): lcd.begin(20, 4) есть, lcd.init() убран ---------------------------
def check_menu_reset_lcd(body: str, errors: list[str]) -> None:
    if "lcd.begin(20, 4)" not in body:
        errors.append("menu_reset_lcd: нет lcd.begin(20, 4)")
    if "lcd.init()" in body:
        errors.append(
            "menu_reset_lcd: остался lcd.init() - внутри библиотеки он сам зовёт "
            "Wire.begin()/begin(), вторая задержка ~1 с и сброс настроек шины"
        )


# --- 3b. setupMenu(): lcd.begin(LCD_COLUMNS, LCD_ROWS) есть, lcd.init() убран ---------------
def check_setup_menu_lcd_init(body: str, errors: list[str]) -> None:
    if "lcd.begin(LCD_COLUMNS, LCD_ROWS)" not in body:
        errors.append("setupMenu: нет lcd.begin(LCD_COLUMNS, LCD_ROWS)")
    if "lcd.init()" in body:
        errors.append(
            "setupMenu: остался lcd.init() - setupMenu() выполняется в setup() после "
            "Wire.setClock(100000)/Wire.setTimeOut(10) из setup_wifi_stack_defaults(), а "
            "lcd.init() внутри библиотеки сам зовёт Wire.begin()/begin() и перебивает эти "
            "настройки плюс добавляет лишнюю задержку ~1 с"
        )


# --- 4. setup_wifi_stack_defaults(): Wire.setClock/setTimeOut после Wire.begin --------------
def check_wire_setup(body: str, errors: list[str]) -> None:
    require_ordered_tokens(
        "setup Wire bus tuning after Wire.begin",
        body,
        [
            "Wire.begin(LCD_SDA, LCD_SCL);",
            "Wire.setClock(100000);",
            "Wire.setTimeOut(10);",
        ],
        errors,
    )


# --- 5. triggerSysTicker(): mode_dispatch_alarm() раньше кэша I2C и записи лога -------------
def check_systicker_alarm_order(body: str, errors: list[str]) -> None:
    alarm_idx = body.find("mode_dispatch_alarm();")
    cache_idx = body.find("refresh_i2c_stepper_cache(")
    append_idx = body.find("append_data();")
    if alarm_idx < 0:
        errors.append("triggerSysTicker: mode_dispatch_alarm() не найден")
        return
    if cache_idx < 0:
        errors.append("triggerSysTicker: refresh_i2c_stepper_cache( не найден")
    elif alarm_idx > cache_idx:
        errors.append(
            "triggerSysTicker: mode_dispatch_alarm() вызывается позже "
            "refresh_i2c_stepper_cache(...) - аварийные проверки реагируют не сразу "
            "после чтения датчиков, а после кэша I2C"
        )
    if append_idx < 0:
        errors.append("triggerSysTicker: append_data(); не найден")
    elif alarm_idx > append_idx:
        errors.append(
            "triggerSysTicker: mode_dispatch_alarm() вызывается позже append_data() - "
            "аварийные проверки реагируют не сразу после чтения датчиков, а после записи лога"
        )


# --- 6. refresh_i2c_stepper_cache(): укороченный таймаут I2C_CACHE_LOCK_WAIT_MS -------------
def check_cache_refresh_timeout(body: str, errors: list[str]) -> None:
    if "i2c_stepper_refresh(device, true, I2C_CACHE_LOCK_WAIT_MS)" not in body:
        errors.append(
            "refresh_i2c_stepper_cache: не передаёт укороченный таймаут "
            "I2C_CACHE_LOCK_WAIT_MS в i2c_stepper_refresh()"
        )
    if "i2c_stepper_refresh(device, true);" in body:
        errors.append(
            "refresh_i2c_stepper_cache: использует таймаут по умолчанию (1000 мс, общий "
            "с записью пользовательской конфигурации) вместо укороченного"
        )


def run_check(label: str, body: str, check_fn) -> list[str]:
    errors: list[str] = []
    check_fn(body, errors)
    return errors


# --- мутационная проверка: тело мутируется точечными заменами токенов, без ------------------
# знания точных пробелов вокруг (strip_cpp_comments уже съедает комментарии и часть
# форматирования) - поэтому мутации бьют по уникальным литералам, а не по целым блокам.
def mutate_lcd_reset_deadline(body: str) -> str:
    mutated = body.replace("static uint32_t next_lcd_reset_ms = LCD_RESET_PERIOD_MS;", "")
    mutated = mutated.replace(
        "if ((int32_t)(millis() - next_lcd_reset_ms) >= 0) {", "if (CurMin == 120) {"
    )
    mutated = mutated.replace("next_lcd_reset_ms += LCD_RESET_PERIOD_MS;\n", "")
    return mutated


def mutate_menu_reset_lcd(body: str) -> str:
    return body.replace("lcd.begin(20, 4);", "lcd.begin(20, 4);\n    lcd.init();")


def mutate_setup_menu_lcd_init(body: str) -> str:
    return body.replace(
        "lcd.begin(LCD_COLUMNS, LCD_ROWS);", "lcd.init();\n  lcd.begin(LCD_COLUMNS, LCD_ROWS);"
    )


def mutate_wire_setup(body: str) -> str:
    mutated = body.replace("Wire.setClock(100000);\n", "")
    mutated = mutated.replace("Wire.setTimeOut(10);\n", "")
    return mutated


def mutate_systicker_alarm_order(body: str) -> str:
    # Симулируем старый порядок: убираем вызов из ранней точки и ставим его
    # сразу после последнего append_data() - как было до правки Н3.
    mutated = body.replace("mode_dispatch_alarm();", "", 1)
    anchor = "append_data();"
    pos = mutated.rfind(anchor)
    if pos < 0:
        return mutated
    pos += len(anchor)
    return mutated[:pos] + "\n      mode_dispatch_alarm();" + mutated[pos:]


def mutate_cache_refresh_timeout(body: str) -> str:
    return body.replace(
        "i2c_stepper_refresh(device, true, I2C_CACHE_LOCK_WAIT_MS)",
        "i2c_stepper_refresh(device, true)",
    )


def mutate_lcd_reset_period_define(ini_source: str) -> str:
    return ini_source.replace("#define LCD_RESET_PERIOD_MS 240000UL", "")


def main() -> int:
    errors: list[str] = []

    menu_source = read(MENU_PATH)
    ini_source = read(SAMOVAR_INI_PATH)
    samovar_source = read(SAMOVAR_INO_PATH)

    try:
        encoder_body = extract_function_body(menu_source, ENCODER_SIGNATURE)
    except ValueError as exc:
        errors.append(str(exc))
        encoder_body = ""
    try:
        menu_reset_lcd_body = extract_function_body(menu_source, MENU_RESET_LCD_SIGNATURE)
    except ValueError as exc:
        errors.append(str(exc))
        menu_reset_lcd_body = ""
    try:
        setup_menu_body = extract_function_body(menu_source, SETUP_MENU_SIGNATURE)
    except ValueError as exc:
        errors.append(str(exc))
        setup_menu_body = ""
    try:
        setup_wifi_body = extract_function_body(samovar_source, SETUP_WIFI_SIGNATURE)
    except ValueError as exc:
        errors.append(str(exc))
        setup_wifi_body = ""
    try:
        systicker_body = extract_function_body(samovar_source, TRIGGER_SYSTICKER_SIGNATURE)
    except ValueError as exc:
        errors.append(str(exc))
        systicker_body = ""
    try:
        cache_refresh_body = extract_function_body(samovar_source, CACHE_REFRESH_SIGNATURE)
    except ValueError as exc:
        errors.append(str(exc))
        cache_refresh_body = ""

    if errors:
        print("LCD reset & I2C order smoke check failed (source parsing):")
        for err in errors:
            print(f" - {err}")
        return 1

    if encoder_body:
        check_lcd_reset_deadline(encoder_body, errors)
    check_lcd_reset_period_define(ini_source, errors)
    if menu_reset_lcd_body:
        check_menu_reset_lcd(menu_reset_lcd_body, errors)
    if setup_menu_body:
        check_setup_menu_lcd_init(setup_menu_body, errors)
    if setup_wifi_body:
        check_wire_setup(setup_wifi_body, errors)
    if systicker_body:
        check_systicker_alarm_order(systicker_body, errors)
    if cache_refresh_body:
        check_cache_refresh_timeout(cache_refresh_body, errors)

    if errors:
        print("LCD reset & I2C order smoke check failed:")
        for err in errors:
            print(f" - {err}")
        return 1

    # --- мутационная проверка содержательности каждой из 6 проверок -------------------------
    mutation_problems: list[str] = []

    mutation_cases = [
        ("lcd reset deadline (encoder_getvalue)", encoder_body, mutate_lcd_reset_deadline, check_lcd_reset_deadline),
        ("menu_reset_lcd no lcd.init()", menu_reset_lcd_body, mutate_menu_reset_lcd, check_menu_reset_lcd),
        ("setupMenu no lcd.init()", setup_menu_body, mutate_setup_menu_lcd_init, check_setup_menu_lcd_init),
        ("Wire.setClock/setTimeOut after Wire.begin", setup_wifi_body, mutate_wire_setup, check_wire_setup),
        ("mode_dispatch_alarm order in SysTicker", systicker_body, mutate_systicker_alarm_order, check_systicker_alarm_order),
        ("refresh_i2c_stepper_cache short lock timeout", cache_refresh_body, mutate_cache_refresh_timeout, check_cache_refresh_timeout),
    ]
    for label, original_body, mutator, check_fn in mutation_cases:
        mutated_body = mutator(original_body)
        if mutated_body == original_body:
            mutation_problems.append(f"{label}: мутация не изменила тело функции")
            continue
        mutant_errors = run_check(label, mutated_body, check_fn)
        if not mutant_errors:
            mutation_problems.append(f"{label}: mutation survived (мутация не поймана проверкой)")

    mutated_ini = mutate_lcd_reset_period_define(ini_source)
    if mutated_ini == ini_source:
        mutation_problems.append("LCD_RESET_PERIOD_MS define: мутация не изменила текст Samovar_ini.h")
    else:
        mutant_errors: list[str] = []
        check_lcd_reset_period_define(mutated_ini, mutant_errors)
        if not mutant_errors:
            mutation_problems.append(
                "LCD_RESET_PERIOD_MS define: mutation survived (мутация не поймана проверкой)"
            )

    if mutation_problems:
        print("LCD reset & I2C order smoke check: mutation testing failed:")
        for problem in mutation_problems:
            print(f" - {problem}")
        return 1

    print("LCD reset & I2C order smoke check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
