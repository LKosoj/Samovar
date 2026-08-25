#!/usr/bin/env python3
"""[Ревью 24.08] Сторож loop() (esp_task_wdt, порог LOOP_WDT_TIMEOUT_S) перезагружает
контроллер, если ОДНА итерация loop() не уложилась в порог: loopTask() ядра
Arduino-ESP32 вызывает esp_task_wdt_reset() ровно один раз за итерацию, ПЕРЕД loop().
Значит порог обязан покрывать СУММУ худших случаев блокирующих вызовов итерации, а не
каждый по отдельности. Ложная перезагрузка посреди перегонки хуже, чем отсутствие
сторожа, поэтому связь констант проверяется тестом, а не на глаз.

[Ревью 24.08, ошибка 1] Раньше здесь же суммировался путь I2C-степпера
(process_pending_i2c_operations() -> i2c_stepper_send_command()) - тест считал ровно
2 записи регистра + один дедлайн из тела send_command(). Это была ЧАСТИЧНАЯ модель:
process_pending_i2c_operations() может дойти до i2c_stepper_write_config() (12
последовательных записей регистра, КАЖДАЯ ждёт семафор шины до I2C_LOCK_WAIT_MS) плюс
i2c_stepper_send_command() плюс confirm_i2c_candidate() (ещё один i2c_stepper_refresh()),
а также до set_stepper_target()/set_mixer_state() из соседних tick_apply_pending_*() -
честно просуммировать ВСЕ эти цепочки в бюджет одной итерации означало бы поднять порог
LOOP_WDT_TIMEOUT_S до величины, которая перестала бы ловить настоящие бесконечные
зависания (ради чего сторож и существует).

Текущая модель: путь I2C-степпера ИСКЛЮЧЁН из бюджета итерации не молча, а явно -
process_pending_i2c_operations() (и её "тёзки" tick_apply_pending_pnbk()/
tick_apply_pending_mixer(), см. комментарии в Samovar.ino) кормят сторож сами через
feedLoopWDT() сразу после I2C-операции. Это не маскировка бесконечного зависания: каждое
ожидание внутри цепочки ограничено СВОИМ таймаутом семафора или дедлайном по millis(),
то есть цепочка целиком тоже ограничена сверху - просто может быть длиннее одной
итерации. Именно от НЕограниченных зависаний защищает сторож.

Тест проверяет:
  1. process_pending_i2c_operations() реально зовёт feedLoopWDT() (иначе исключение I2C
     из бюджета - враньё, а не факт).
  2. Оставшийся посчитанный участник бюджета - tick_blynk() -> Blynk.run(): на зависшем
     сокете блокирует ровно BLYNK_TIMEOUT_MS (client->setTimeout, читает блокирующим
     readBytes()). Значение задаётся флагом сборки -DBLYNK_TIMEOUT_MS в platformio.ini,
     а не #define в Samovar.ino: logic.h втягивает BlynkSimpleEsp32.h -> BlynkConfig.h
     РАНЬШЕ блока Blynk в Samovar.ino, где значение задано через #ifndef - #define в
     Samovar.ino опоздал бы и молча не подействовал бы (плюс warning "redefined").
     Флаг же в командной строке компилятора, раньше любого #include. Флаг обязан лежать
     в базовой секции [env:Samovar]: остальные окружения наследуют её build_flags, иначе
     часть прошивок собралась бы с заводскими 6000 мс.
  3. Blynk-бюджет + запас укладывается в порог.

Использование:
  python3 smoke_loop_budget_vs_watchdog.py
"""
import re
import sys
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

# Запас на всё остальное содержимое итерации loop() (тики режимов, SPIFFS, журнал,
# датчики) помимо посчитанного участника (Blynk).
REQUIRED_HEADROOM_MS = 2000


def fail(message: str) -> int:
    print("loop budget vs watchdog smoke failed:")
    print(f"  {message}")
    return 1


def main() -> int:
    samovar = (ROOT / "Samovar.ino").read_text(encoding="utf-8", errors="ignore")
    ini = (ROOT / "platformio.ini").read_text(encoding="utf-8", errors="ignore")

    wdt = re.search(r"constexpr\s+uint32_t\s+LOOP_WDT_TIMEOUT_S\s*=\s*(\d+)\s*;", samovar)
    if not wdt:
        return fail("не найдена константа LOOP_WDT_TIMEOUT_S в Samovar.ino")
    threshold_ms = int(wdt.group(1)) * 1000

    # [Ревью 24.08, ошибка 1] Без этой проверки исключение I2C-пути из бюджета ниже было
    # бы враньём: сама process_pending_i2c_operations() обязана реально кормить сторож.
    try:
        i2c_operations_body = extract_function_body(
            samovar, "static void process_pending_i2c_operations() {")
    except ValueError as error:
        return fail(f"{error}")
    if "feedLoopWDT()" not in i2c_operations_body:
        return fail(
            "process_pending_i2c_operations() не зовёт feedLoopWDT(): I2C-путь "
            "(i2c_stepper_write_config()/i2c_stepper_send_command()/confirm_i2c_candidate(), "
            "суммарно способен растянуться дольше одной итерации loop()) исключён из "
            "бюджета ниже только на словах - сторож по-прежнему получит его в бюджет "
            "одной итерации и может ложно перезагрузить контроллер")

    # [Ревью 24.08, ошибка 1] Та же природа обнаружена ещё в двух местах loop():
    # tick_apply_pending_pnbk() (set_stepper_target() при найденном I2C-насосе) и
    # tick_apply_pending_mixer() (set_mixer() -> set_mixer_state(), до двух I2C-цепочек
    # подряд - степпер мешалки и реле через select_relay_capable_device()). Остальные
    # tick_apply_pending_*() в loop() проверены и НЕ используют I2C (например,
    # tick_apply_pending_pump_speed() -> set_pump_speed() идёт только через локальные
    # stepper_safe_*()) - им feedLoopWDT() не добавлялся, см. отчёт ревью.
    for fn_signature, fn_label in (
        ("static void tick_apply_pending_pnbk() {", "tick_apply_pending_pnbk()"),
        ("static void tick_apply_pending_mixer() {", "tick_apply_pending_mixer()"),
    ):
        try:
            fn_body = extract_function_body(samovar, fn_signature)
        except ValueError as error:
            return fail(f"{error}")
        if "feedLoopWDT()" not in fn_body:
            return fail(
                f"{fn_label} не зовёт feedLoopWDT(): эта функция тоже может дойти до "
                "ограниченной, но не мгновенной цепочки I2C (см. process_pending_i2c_"
                "operations() выше) - без сброса сторож снова считает её частью "
                "бюджета одной итерации")

    blynk = None
    for line in ini.splitlines():
        stripped = line.strip()
        if stripped.startswith(";"):
            continue
        match = re.match(r"-DBLYNK_TIMEOUT_MS=(\d+)", stripped)
        if match:
            blynk = int(match.group(1))
            break
    if blynk is None:
        return fail(
            "в platformio.ini нет флага -DBLYNK_TIMEOUT_MS: останутся заводские 6000 мс "
            "(BlynkConfig.h), и Blynk.run() один заберёт больше половины бюджета итерации")

    base = ini[ini.find("[env:Samovar]"):]
    next_section = base.find("\n[env:")
    if next_section > 0:
        base = base[:next_section]
    if "-DBLYNK_TIMEOUT_MS" not in base:
        return fail(
            "флаг -DBLYNK_TIMEOUT_MS задан не в базовой секции [env:Samovar]: остальные "
            "окружения наследуют ${env:Samovar.build_flags} и собрались бы с 6000 мс")

    for index, line in enumerate(samovar.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        if re.match(r"#define\s+BLYNK_TIMEOUT_MS\b", stripped):
            return fail(
                f"Samovar.ino:{index}: #define BLYNK_TIMEOUT_MS здесь опаздывает (logic.h "
                "выше уже втянул BlynkConfig.h), молча не действует и даёт предупреждение "
                '"redefined" - значение задаётся флагом сборки в platformio.ini')

    total = blynk + REQUIRED_HEADROOM_MS
    if total > threshold_ms:
        return fail(
            f"бюджет итерации loop() не влезает в сторож: Blynk.run() {blynk} мс + запас "
            f"{REQUIRED_HEADROOM_MS} мс = {total} мс > порога {threshold_ms} мс "
            f"(LOOP_WDT_TIMEOUT_S). Зависшая сеть вызовет ложную перезагрузку.")

    print(
        f"loop budget vs watchdog smoke passed: feedLoopWDT() подтверждён в "
        f"process_pending_i2c_operations(), Blynk {blynk} мс + запас {REQUIRED_HEADROOM_MS} "
        f"мс = {total} мс <= {threshold_ms} мс (путь I2C-степпера кормит сторож отдельно)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
