#!/usr/bin/env python3
"""[A1 п.6] dist_plateau_finish_due() (distiller.h) - общий хелпер "плато": Т куба
выше 90°C, нагрев включён, SamSetup.DistTimeF > 0 минут задано пользователем, и
температура куба не растёт больше чем на 0.1°C за DistTimeF минут. Используется и
distiller_proc(), и bk_proc() (новая функциональность для БК). Состояние
(d_s_temp_finish/d_s_time_min) общее и сбрасывается уже в reset_process_state()
(sensorinit.h) - здесь не проверяется, это тело ЧИСТОГО хелпера в изоляции.

Этот тест компилирует РЕАЛЬНОЕ тело хелпера (извлечённое из distiller.h) и
проверяет поведение по scenarios ниже, а не переписывает логику заново.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

SIGNATURE = "inline bool dist_plateau_finish_due()"

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>

// Arduino.h определяет abs() как generic-макрос (не int-специфичный
// std::abs(int) из <cstdlib>, который бы обрезал дробную часть при
// неявном приведении float->int).
#define abs(x) ((x) > 0 ? (x) : -(x))

enum MESSAGE_TYPE { ALARM_MSG = 0, WARNING_MSG = 1, NOTIFY_MSG = 2 };

class String {
 public:
  String(const char* value) : value_(value) {}
 private:
  const char* value_;
};

struct Sensor { float avgTemp = 0; };
static Sensor TankSensor;

static bool PowerOn = false;

struct Setup { uint8_t DistTimeF = 0; };
static Setup SamSetup;

static float d_s_temp_finish = 0;
static unsigned long d_s_time_min = 0;

static unsigned long fakeMillis = 0;
static unsigned long millis() { return fakeMillis; }

static int sendMsgCalls = 0;
static void SendMsg(const String&, MESSAGE_TYPE) { sendMsgCalls++; }

@PLATEAU_BODY@

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) { std::cerr << "FAIL: " << message << '\n'; failures++; }
}

static void reset_all() {
  TankSensor = Sensor();
  PowerOn = true;
  SamSetup = Setup();
  d_s_temp_finish = 0;
  d_s_time_min = 0;
  fakeMillis = 0;
  sendMsgCalls = 0;
}

int main() {
  // Сценарий 1: DistTimeF == 0 -> хелпер всегда false, даже если температура
  // держится сколько угодно тиков и avgTemp > 90 (ветка "выкл").
  reset_all();
  SamSetup.DistTimeF = 0;
  TankSensor.avgTemp = 92.0f;
  for (int i = 0; i < 20; i++) {
    fakeMillis += 60000UL;
    check(!dist_plateau_finish_due(), "DistTimeF == 0 должен держать хелпер выключенным");
  }
  check(sendMsgCalls == 0, "DistTimeF == 0 не должен слать сообщение");

  // Сценарий 2: DistTimeF == N (5), PowerOn == true, avgTemp держится N минут ->
  // на тике, где millis() - d_s_time_min > N*60*1000, хелпер возвращает true
  // РОВНО один раз, SendMsg вызван 1 раз.
  reset_all();
  const uint8_t N = 5;
  SamSetup.DistTimeF = N;
  TankSensor.avgTemp = 92.0f;
  fakeMillis = 0;
  check(!dist_plateau_finish_due(), "первый вызов должен захватить baseline и вернуть false");
  check(d_s_temp_finish == 92.0f, "baseline температуры должен захватиться");
  for (int minute = 1; minute <= N; minute++) {
    fakeMillis = (unsigned long)minute * 60000UL;
    check(!dist_plateau_finish_due(),
          "плато не должно сработать, пока интервал DistTimeF не истёк строго");
  }
  fakeMillis = (unsigned long)N * 60000UL + 1;
  check(dist_plateau_finish_due(), "плато должно сработать сразу после истечения полного интервала");
  check(sendMsgCalls == 1, "SendMsg должен быть вызван ровно один раз");

  // Сценарий 3: скачок температуры на середине выдержки перезапускает таймер
  // плато (d_s_time_min обновляется), хелпер продолжает возвращать false, пока
  // не пройдёт полный N-минутный интервал заново.
  reset_all();
  SamSetup.DistTimeF = N;
  TankSensor.avgTemp = 92.0f;
  fakeMillis = 0;
  dist_plateau_finish_due(); // захват baseline
  fakeMillis = 3 * 60000UL;
  check(!dist_plateau_finish_due(), "плато не должно сработать за 3 минуты из 5");
  TankSensor.avgTemp = 93.0f; // скачок больше 0.1°C - перезапуск таймера
  unsigned long restartTime = fakeMillis;
  check(!dist_plateau_finish_due(), "скачок температуры должен перезапустить таймер (вернуть false)");
  check(d_s_time_min == restartTime, "d_s_time_min должен обновиться при скачке температуры");
  fakeMillis = restartTime + (N - 1) * 60000UL;
  check(!dist_plateau_finish_due(), "после перезапуска старый прогресс не должен засчитываться");
  fakeMillis = restartTime + N * 60000UL + 1;
  check(dist_plateau_finish_due(), "после перезапуска плато обязано сработать через полный новый интервал");

  // Сценарий 3b: шум датчика (DS18B20, шаг квантования 0.0625°C) в пределах
  // порога 0.1°C НЕ должен перезапускать таймер плато - иначе плато никогда не
  // сработает на реальном оборудовании (температура почти никогда не стоит на
  // месте абсолютно точно).
  reset_all();
  SamSetup.DistTimeF = N;
  TankSensor.avgTemp = 92.00f;
  fakeMillis = 0;
  dist_plateau_finish_due(); // захват baseline
  for (int minute = 1; minute <= N; minute++) {
    fakeMillis = (unsigned long)minute * 60000UL;
    TankSensor.avgTemp = 92.00f + (minute % 2 == 0 ? 0.05f : -0.05f);
    check(!dist_plateau_finish_due(),
          "шум датчика в пределах порога 0.1 не должен перезапускать таймер плато");
  }
  fakeMillis = (unsigned long)N * 60000UL + 1;
  check(dist_plateau_finish_due(),
        "плато обязано сработать по расписанию, несмотря на шум датчика в пределах порога");

  // Сценарий 4: avgTemp <= 90 или PowerOn == false -> хелпер false независимо от
  // остального состояния (верхний гейт).
  reset_all();
  SamSetup.DistTimeF = N;
  TankSensor.avgTemp = 90.0f;
  PowerOn = true;
  fakeMillis = 100UL * 60000UL;
  check(!dist_plateau_finish_due(), "avgTemp <= 90 должно держать хелпер выключенным");

  reset_all();
  SamSetup.DistTimeF = N;
  TankSensor.avgTemp = 92.0f;
  PowerOn = false;
  fakeMillis = 0;
  check(!dist_plateau_finish_due(), "PowerOn == false, первый вызов должен вернуть false");
  // Второй вызов после истечения интервала: без гейта по PowerOn (мутация)
  // baseline уже захвачен первым вызовом, и таймер сработал бы - гейт обязан
  // держать хелпер false даже здесь.
  fakeMillis = (unsigned long)N * 60000UL + 1;
  check(!dist_plateau_finish_due(), "PowerOn == false должно держать хелпер выключенным и после истечения интервала");

  if (failures != 0) return 1;
  std::cout << "dist_plateau_finish_due checks passed\n";
  return 0;
}
'''


def build_harness(distiller_source: str) -> str:
    body = extract_function_body(distiller_source, SIGNATURE)
    return HARNESS_TEMPLATE.replace(
        "@PLATEAU_BODY@", "static bool dist_plateau_finish_due() {" + body + "}"
    )


def compile_and_run(harness: str, name: str = "bk_plateau_finish_test") -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-bk-plateau-finish-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / f"{name}.cpp"
        binary = temp / name
        source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            sys.stderr.write("compile failed:\n")
            sys.stderr.write(compile_result.stdout)
            sys.stderr.write(compile_result.stderr)
            return compile_result.returncode
        run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        sys.stdout.write(run_result.stdout)
        sys.stderr.write(run_result.stderr)
        return run_result.returncode


def main() -> int:
    distiller_source = (ROOT / "distiller.h").read_text(encoding="utf-8")
    try:
        harness = build_harness(distiller_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    result = compile_and_run(harness)
    if result != 0:
        return result

    # Мутация: убрать PowerOn из верхнего гейта - сценарий 4 (часть про PowerOn)
    # должен упасть, т.к. хелпер сработает и при выключенном нагреве.
    mutant_power = harness.replace(
        "TankSensor.avgTemp > 90 && PowerOn && SamSetup.DistTimeF > 0",
        "TankSensor.avgTemp > 90 && SamSetup.DistTimeF > 0",
        1,
    )
    if mutant_power == harness:
        print("FAIL: не удалось построить мутацию PowerOn gate", file=sys.stderr)
        return 1
    if compile_and_run(mutant_power, name="bk_plateau_finish_power_mutant") == 0:
        print("FAIL: мутация PowerOn gate (хелпер срабатывает без нагрева) пережила тест", file=sys.stderr)
        return 1

    # Мутация: порог нечувствительности 0.1 -> 0.0 - сценарий 3 должен упасть иначе
    # (перезапуск таймера по любому шуму температуры, включая отсутствие изменения).
    mutant_threshold = harness.replace('> 0.1) {', '> 0.0) {', 1)
    if mutant_threshold == harness:
        print("FAIL: не удалось построить мутацию порога нечувствительности", file=sys.stderr)
        return 1
    if compile_and_run(mutant_threshold, name="bk_plateau_finish_threshold_mutant") == 0:
        print("FAIL: мутация порога нечувствительности (0.1 -> 0.0) пережила тест", file=sys.stderr)
        return 1

    # Мутация: потерян множитель минут->секунды (DistTimeF * 60 * 1000 ->
    # DistTimeF * 1000) - сценарий 2 должен упасть на количестве тиков до true
    # (сработает в ~16.6 раза раньше ожидаемого).
    mutant_minutes = harness.replace(
        "SamSetup.DistTimeF * 60 * 1000",
        "SamSetup.DistTimeF * 1000",
        1,
    )
    if mutant_minutes == harness:
        print("FAIL: не удалось построить мутацию множителя минут", file=sys.stderr)
        return 1
    if compile_and_run(mutant_minutes, name="bk_plateau_finish_minutes_mutant") == 0:
        print("FAIL: мутация множителя минут (потерян *60) пережила тест", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
