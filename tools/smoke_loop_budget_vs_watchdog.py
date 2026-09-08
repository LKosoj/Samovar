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
     readBytes()). Для ESP32 Blynk-адаптер переводит эти миллисекунды в секунды только
     перед WiFiClient::setTimeout(), а отправляет через send(..., MSG_DONTWAIT), поэтому
     запись не добавляет блокирующее ожидание. Значение задаётся #define BLYNK_TIMEOUT_MS в Samovar.h - первом
     включении всех заголовков с Blynk, раньше BlynkConfig.h (там #ifndef). Не флагом
     -D в platformio.ini: Arduino IDE флаги не видит. Не в Samovar.ino: logic.h выше
     уже втянул BlynkConfig.h, define опоздал бы и молча не подействовал.
  3. Blynk-бюджет + запас укладывается в порог.

Использование:
  python3 smoke_loop_budget_vs_watchdog.py
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
BLYNK_ADAPTER = ROOT / "libraries" / "Blynk" / "src" / "Adapters" / "BlynkArduinoClient.h"
BLYNK_PROTOCOL = ROOT / "libraries" / "Blynk" / "src" / "Blynk" / "BlynkProtocol.h"
BLYNK_SIMPLE_ESP32 = ROOT / "libraries" / "Blynk" / "src" / "BlynkSimpleEsp32.h"

# Запас на всё остальное содержимое итерации loop() (тики режимов, SPIFFS, журнал,
# датчики) помимо посчитанного участника (Blynk).
REQUIRED_HEADROOM_MS = 2000


def fail(message: str) -> int:
    print("loop budget vs watchdog smoke failed:")
    print(f"  {message}")
    return 1


def compile_and_run(harness: str, label: str, show_output: bool = True) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-blynk-watchdog-") as temp_dir:
        source = Path(temp_dir) / "blynk_watchdog_test.cpp"
        binary = Path(temp_dir) / "blynk_watchdog_test"
        source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        output = compile_result.stdout + compile_result.stderr
        if compile_result.returncode == 0:
            run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
            output += run_result.stdout + run_result.stderr
            result = run_result.returncode
        else:
            result = compile_result.returncode
        if show_output and output:
            print(f"[{label}] {output}", end="" if output.endswith("\n") else "\n")
        return result, output


def build_blynk_adapter_harness(timeout_body: str, write_body: str) -> str:
    return f'''\
#include <cassert>
#include <cstddef>
#include <cstdint>

#define BLYNK_TIMEOUT_MS 3000UL
#define MSG_DONTWAIT 0x40

static int nextSendResult = 0;
static int sendCalls = 0;
static int sentSocket = -1;
static int sentFlags = 0;

static int send(int socket, const uint8_t*, size_t, int flags) {{
  ++sendCalls;
  sentSocket = socket;
  sentFlags = flags;
  return nextSendResult;
}}

class WiFiClient {{
 public:
  int socket = -1;
  uint32_t timeoutSeconds = 0;
  void setTimeout(uint32_t seconds) {{ timeoutSeconds = seconds; }}
  int fd() const {{ return socket; }}
}};

static inline void blynk_client_set_timeout(WiFiClient* client) {{
{timeout_body}
}}

static inline size_t blynk_client_write(WiFiClient* client, const uint8_t* buffer, size_t length) {{
{write_body}
}}

int main() {{
  WiFiClient client;
  uint8_t payload[] = {{1, 2, 3}};

  blynk_client_set_timeout(&client);
  assert(client.timeoutSeconds == 3);

  assert(blynk_client_write(&client, payload, sizeof(payload)) == 0);
  assert(sendCalls == 0);

  client.socket = 17;
  nextSendResult = 2;
  assert(blynk_client_write(&client, payload, sizeof(payload)) == 2);
  assert(sendCalls == 1);
  assert(sentSocket == 17);
  assert(sentFlags == MSG_DONTWAIT);

  nextSendResult = 0;
  assert(blynk_client_write(&client, payload, sizeof(payload)) == 0);
  nextSendResult = -1;
  assert(blynk_client_write(&client, payload, sizeof(payload)) == 0);
}}
'''


def verify_blynk_adapter() -> str | None:
    adapter = BLYNK_ADAPTER.read_text(encoding="utf-8", errors="ignore")
    simple_esp32 = BLYNK_SIMPLE_ESP32.read_text(encoding="utf-8", errors="ignore")
    try:
        timeout_body = extract_function_body(
            adapter, "static inline void blynk_client_set_timeout(WiFiClient* client)")
        write_body = extract_function_body(
            adapter,
            "static inline size_t blynk_client_write(WiFiClient* client, const uint8_t* buffer, size_t length)",
        )
    except ValueError as error:
        return str(error)

    code, _ = compile_and_run(build_blynk_adapter_harness(timeout_body, write_body), "Blynk ESP32 adapter")
    if code != 0:
        return "ESP32 Blynk adapter violates the timeout or non-blocking write contract"

    timeout_mutant = timeout_body.replace("BLYNK_TIMEOUT_MS / 1000UL", "BLYNK_TIMEOUT_MS", 1)
    write_mutant = write_body.replace("MSG_DONTWAIT", "0", 1)
    if timeout_mutant == timeout_body or write_mutant == write_body:
        return "не удалось создать мутацию единиц или MSG_DONTWAIT для Blynk adapter"
    code, _ = compile_and_run(
        build_blynk_adapter_harness(timeout_mutant, write_body), "Blynk timeout mutant", show_output=False)
    if code == 0:
        return "мутация BLYNK_TIMEOUT_MS мс->с не убита содержательным assert"
    code, _ = compile_and_run(
        build_blynk_adapter_harness(timeout_body, write_mutant), "Blynk blocking-send mutant", show_output=False)
    if code == 0:
        return "мутация MSG_DONTWAIT не убита содержательным assert"

    protocol = BLYNK_PROTOCOL.read_text(encoding="utf-8", errors="ignore")
    try:
        send_command_body = extract_function_body(protocol, "void BlynkProtocol<Transp>::sendCmd(")
    except ValueError as error:
        return str(error)
    failed_write = send_command_body.find("if (w == 0)")
    disconnect = send_command_body.find("conn.disconnect()", failed_write)
    reconnect = send_command_body.find("state = CONNECTING", failed_write)
    if not (failed_write >= 0 and failed_write < disconnect < reconnect):
        return "BlynkProtocol::sendCmd() больше не разрывает transport после нулевой записи"
    for token in (
        "BlynkProtocol<BlynkArduinoClientGen<WiFiClient>>",
        "BlynkWifi(BlynkArduinoClientGen<WiFiClient>& transp)",
        "BlynkArduinoClientGen<WiFiClient> _blynkTransport(_blynkWifiClient)",
    ):
        if token not in simple_esp32:
            return f"BlynkSimpleEsp32 не создаёт transport с WiFiClient: {token}"
    return None


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

    samovar_h = (ROOT / "Samovar.h").read_text(encoding="utf-8", errors="ignore")
    match = re.search(r"^#define\s+BLYNK_TIMEOUT_MS\s+(\d+)UL\s*$", samovar_h, re.MULTILINE)
    if not match:
        return fail(
            "в Samovar.h нет #define BLYNK_TIMEOUT_MS: останутся заводские 6000 мс "
            "(BlynkConfig.h), и Blynk.run() один заберёт больше половины бюджета итерации")
    blynk = int(match.group(1))

    if "-DBLYNK_TIMEOUT_MS" in ini:
        return fail(
            "BLYNK_TIMEOUT_MS задан флагом в platformio.ini: Arduino IDE флаги не видит, "
            "единственный источник - Samovar.h")

    adapter_error = verify_blynk_adapter()
    if adapter_error:
        return fail(adapter_error)

    for index, line in enumerate(samovar.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        if re.match(r"#define\s+BLYNK_TIMEOUT_MS\b", stripped):
            return fail(
                f"Samovar.ino:{index}: #define BLYNK_TIMEOUT_MS здесь опаздывает (logic.h "
                "выше уже втянул BlynkConfig.h), молча не действует и даёт предупреждение "
                '"redefined" - значение задаётся в Samovar.h')

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
