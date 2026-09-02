#!/usr/bin/env python3
"""Поведенческая проверка [Пиво B1]: детектор кипения (beer.h::isBoilingStarted)
не должен принимать медленный нагрев за кипение, но обязан зафиксировать
настоящее кипение в разумный срок.

До правки наклон считался по 10 точкам раз в секунду, критерий стабильности -
"stddev<=0.08 И |посекундный тренд|<=0.02". Квантование датчика до 1/16 °C
ломало посекундный тренд на медленном нагреве (0.3-1.2 °C/мин): несколько
секунд подряд датчик показывал одно и то же квантованное значение, тренд
падал ниже порога, и через ~15-20 с детектор ошибочно решал, что кипение уже
идёт (см. sim_boil.py и отчёт).

Правка: децимированная история на TEMP_HISTORY_SIZE=7 точек раз в
BOILING_HISTORY_INTERVAL_MS (10 с) - окно ~60 с; вместо посекундного тренда -
рост средней температуры конца окна относительно начала (по крайним третям
точек), порог MAX_RISE_PER_WINDOW.

Тест вытаскивает РЕАЛЬНОЕ тело isBoilingStarted() и resetBoilingDetector() из
beer.h через extract_function_body - без переписывания логики. Значения всех
шести #define, от которых зависит детектор, тоже читаются из beer.h
python-поиском (extract_define_value), а не дублируются литералами в
харнессе: это единственный способ, которым мутация константы в beer.h будет
поймана именно ЭТИМ тестом при следующем запуске (harness всегда собирается
из актуального текста файла).

Важная находка (подтверждена симуляцией sim_boil.py и сканированием
production-точной C++ арифметики, scan_rise_boundary.cpp): при скорости
рампы >= ~0.25 °C/мин критерий по стандартному отклонению окна
(BOILING_DETECT_THRESHOLD, эта правка его не меняет) уже сам по себе не даёт
ложных срабатываний НЕЗАВИСИМО от MAX_RISE_PER_WINDOW - для эволюции окна на
7 децимированных точках с шагом 10 с дисперсия равномерной рампы 0.3 °C/мин
и быстрее всегда выше 0.08. Поэтому рампы 0.3 и 0.9 °C/мин (требуемый рабочий
диапазон) сами по себе НЕ ловят мутацию MAX_RISE_PER_WINDOW - его роль
проявляется только в узкой зоне 0.15-0.24 °C/мин, где дисперсия уже мала, а
решает именно рост окна. Рампа 0.2 °C/мин (медленнее рабочего минимума 0.3,
поэтому по тому же требованию тоже обязана не считаться кипением) добавлена
в тест именно для того, чтобы мутация MAX_RISE_PER_WINDOW реально валила
assert, а не пряталась за независимым критерием stddev.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

ISBOILINGSTARTED_SIGNATURE = "bool isBoilingStarted(float currentTemp)"
RESET_BOILING_DETECTOR_SIGNATURE = "static inline void resetBoilingDetector()"

DEFINE_NAMES = (
    "TEMP_HISTORY_SIZE",
    "BOILING_HISTORY_INTERVAL_MS",
    "BOILING_DETECT_THRESHOLD",
    "MIN_BOILING_TEMP",
    "STABLE_WINDOWS_REQUIRED",
    "MAX_RISE_PER_WINDOW",
)


def extract_define_value(source: str, name: str) -> str:
    match = re.search(rf"#define\s+{name}\s+(\S+)", source)
    if not match:
        raise ValueError(f"#define not found in beer.h: {name}")
    return match.group(1)


HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <cmath>
#include <iostream>
#include <sstream>
#include <string>

@DEFINES@

struct BoilingDetector {
    float tempHistory[TEMP_HISTORY_SIZE];
    uint8_t historyIndex = 0;
    uint8_t samplesFilled = 0;
    bool isBoiling = false;
    unsigned long lastUpdateTime = 0;
    unsigned long lastSampleTime = 0;
    uint8_t stableCount = 0;
};

static BoilingDetector boilingDetector;
static unsigned long fakeMillis = 0;
unsigned long millis() { return fakeMillis; }

static inline void resetBoilingDetector() {
@RESET_BOILING_DETECTOR_BODY@
}

bool isBoilingStarted(float currentTemp) {
@ISBOILINGSTARTED_BODY@
}

// --- Тестовая обвязка (не производственный код): квантование датчика 1/16 °C. ---
static float quantize16(float t) {
    return roundf(t / (1.0f / 16.0f)) * (1.0f / 16.0f);
}

static long ramp_duration_s(float rate_c_per_min, float start_temp) {
    double crossS = (98.0 - (double)start_temp) * 60.0 / (double)rate_c_per_min;
    if (crossS < 0) crossS = 0;
    return (long)crossS + 15 * 60;  // +15 минут запаса выше 98.0
}

// Прогоняет чистую рампу (без шума) от start_temp вверх со скоростью
// rate_c_per_min; проверяет, что isBoilingStarted() НИ РАЗУ не вернул true.
// При срабатывании возвращает false и кладёт содержательное сообщение
// (скорость рампы и секунду срабатывания) в failMsg.
static bool run_ramp_no_false_boil(float rate_c_per_min, float start_temp, std::string& failMsg) {
    resetBoilingDetector();
    fakeMillis = 0;
    const long durationS = ramp_duration_s(rate_c_per_min, start_temp);
    const long crossS = durationS - 15 * 60;  // секунда пересечения 98.0 (см. ramp_duration_s)
    const double ratePerS = (double)rate_c_per_min / 60.0;
    for (long t = 0; t <= durationS; t++) {
        float raw = start_temp + (float)(ratePerS * (double)t);
        float temp = quantize16(raw);
        fakeMillis = (unsigned long)(t * 1000);
        if (isBoilingStarted(temp)) {
            std::ostringstream oss;
            oss << "ложное \"кипение\" на рампе " << rate_c_per_min
                << " С/мин: isBoilingStarted() вернул true на секунде t=" << t
                << " (T=" << temp << " С, через " << t - crossS << " с после пересечения 98.0)";
            failMsg = oss.str();
            return false;
        }
    }
    return true;
}

// Детерминированный "шум" датчика вокруг плато: не настоящий ГПСЧ (не нужна
// переносимость RNG между Python-симуляцией и g++), просто заранее заданный
// набор смещений в пределах +-0.06 °C, циклически используемый по секундам.
static const float PLATEAU_OFFSETS[] = {
    0.00f, 0.03f, -0.04f, 0.06f, -0.06f, 0.02f, -0.02f, 0.05f, -0.05f, 0.01f
};
static const int PLATEAU_OFFSETS_N = 10;

// Плато 98.3+-0.06 °C - настоящее кипение. Требование (PLAN_B): не раньше
// 50-й секунды (иначе окно проверки на практике короче заявленного) и не
// позже 100-й.
static bool run_plateau_confirms_within_100s(std::string& failMsg) {
    resetBoilingDetector();
    fakeMillis = 0;
    for (long t = 0; t <= 100; t++) {
        float raw = 98.3f + PLATEAU_OFFSETS[t % PLATEAU_OFFSETS_N];
        float temp = quantize16(raw);
        fakeMillis = (unsigned long)(t * 1000);
        bool boiling = isBoilingStarted(temp);
        if (t <= 50 && boiling) {
            std::ostringstream oss;
            oss << "плато 98.3+-0.06 С: детектор сработал слишком рано, на секунде t=" << t
                << " (ожидали не раньше 50-й секунды)";
            failMsg = oss.str();
            return false;
        }
        if (t == 100 && !boiling) {
            failMsg = "плато 98.3+-0.06 С: реальное кипение не зафиксировано за 100 с (t=100, isBoiling всё ещё false)";
            return false;
        }
    }
    return true;
}

// [Пиво 02.09 B] Просадка ниже MIN_BOILING_TEMP посреди уже накопленного окна
// не должна оставлять старые точки истории: после возврата на плато детектор
// обязан набрать НОВОЕ окно (~60-70 с), а не досчитать стабильность по точкам
// ДО просадки за ~10 с. Плато 98.3+-0.06 65 с (тот же детерминированный шум,
// что и в run_plateau_confirms_within_100s - буфер успевает заполниться),
// затем 300 с при 90.0 С (явно ниже порога), затем возврат на то же плато.
static bool run_dip_below_min_restarts_window(std::string& failMsg) {
    resetBoilingDetector();
    fakeMillis = 0;
    long t = 0;
    for (long i = 0; i < 65; i++, t++) {
        float raw = 98.3f + PLATEAU_OFFSETS[i % PLATEAU_OFFSETS_N];
        float temp = quantize16(raw);
        fakeMillis = (unsigned long)(t * 1000);
        isBoilingStarted(temp);
    }
    for (long i = 0; i < 300; i++, t++) {
        fakeMillis = (unsigned long)(t * 1000);
        if (isBoilingStarted(90.0f)) {
            failMsg = "просадка до 90.0 С ниже MIN_BOILING_TEMP не должна давать isBoiling=true";
            return false;
        }
    }
    const long returnStart = t;
    for (long i = 0; i <= 100; i++) {
        float raw = 98.3f + PLATEAU_OFFSETS[i % PLATEAU_OFFSETS_N];
        float temp = quantize16(raw);
        fakeMillis = (unsigned long)((returnStart + i) * 1000);
        bool boiling = isBoilingStarted(temp);
        if (i < 50 && boiling) {
            std::ostringstream oss;
            oss << "просадка+возврат на плато: детектор сработал слишком рано после "
                   "возврата, на секунде " << i << " после возврата (T=" << temp
                << " С, ожидали не раньше 50-й секунды после возврата - похоже, история "
                   "не была сброшена при просадке)";
            failMsg = oss.str();
            return false;
        }
        if (i == 100 && !boiling) {
            failMsg = "просадка+возврат на плато: реальное кипение не зафиксировано за "
                      "100 с после возврата (isBoiling всё ещё false)";
            return false;
        }
    }
    return true;
}

int main() {
    int failures = 0;
    auto check = [&](bool condition, const std::string& message) {
        if (!condition) {
            std::cerr << "FAIL: " << message << '\n';
            failures++;
        }
    };

    // Основное требование B1: рабочий диапазон медленного нагрева куба
    // (0.3 и 0.9 С/мин, два разных значения) не должен маскироваться под
    // кипение.
    {
        std::string msg;
        bool ok = run_ramp_no_false_boil(0.3f, 92.0f, msg);
        check(ok, msg);
    }
    {
        std::string msg;
        bool ok = run_ramp_no_false_boil(0.9f, 92.0f, msg);
        check(ok, msg);
    }
    // Зона, где решает именно MAX_RISE_PER_WINDOW (см. docstring файла) -
    // нужна, чтобы мутация этой константы валила именно этот тест.
    {
        std::string msg;
        bool ok = run_ramp_no_false_boil(0.2f, 92.0f, msg);
        check(ok, msg);
    }

    // Настоящее кипение обязано зафиксироваться в пределах ~100 с.
    {
        std::string msg;
        bool ok = run_plateau_confirms_within_100s(msg);
        check(ok, msg);
    }

    // [Пиво 02.09 B] Просадка ниже порога обязана начинать новое окно истории.
    {
        std::string msg;
        bool ok = run_dip_below_min_restarts_window(msg);
        check(ok, msg);
    }

    if (failures != 0) return 1;
    std::cout << "beer boiling ramp/plateau detector behaviour checks passed\n";
    return 0;
}
'''


def build_harness(beer_source: str) -> str:
    isboiling_body = extract_function_body(beer_source, ISBOILINGSTARTED_SIGNATURE)
    reset_body = extract_function_body(beer_source, RESET_BOILING_DETECTOR_SIGNATURE)
    defines_block = "\n".join(
        f"#define {name} {extract_define_value(beer_source, name)}" for name in DEFINE_NAMES
    )

    harness = HARNESS_TEMPLATE.replace("@DEFINES@", defines_block)
    harness = harness.replace("@RESET_BOILING_DETECTOR_BODY@", reset_body)
    harness = harness.replace("@ISBOILINGSTARTED_BODY@", isboiling_body)
    return harness


def compile_and_run(harness: str) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-beer-boiling-ramp-") as temp_dir:
        source = Path(temp_dir) / "beer_boiling_ramp_detector.cpp"
        binary = Path(temp_dir) / "beer_boiling_ramp_detector"
        source.write_text(harness, encoding="utf-8")
        compiled = subprocess.run(
            ["g++", "-std=c++11", "-O1", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compiled.returncode:
            return compiled.returncode, compiled.stdout + compiled.stderr
        ran = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        return ran.returncode, ran.stdout + ran.stderr


def mutate_define(harness: str, name: str, new_value: str) -> str:
    pattern = re.compile(rf"(#define {name} )(\S+)")
    mutated, count = pattern.subn(rf"\g<1>{new_value}", harness, count=1)
    if count != 1:
        raise ValueError(f"could not mutate #define {name} in harness")
    return mutated


def main() -> int:
    beer_source = (ROOT / "beer.h").read_text(encoding="utf-8")
    try:
        harness = build_harness(beer_source)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    code, output = compile_and_run(harness)
    sys.stdout.write(output)
    if code:
        return code

    # Мутация 1: MAX_RISE_PER_WINDOW 0.12 -> 0.5 (порог роста за окно
    # ослаблен) обязана завалить рампу 0.2 С/мин.
    mutant_rise = mutate_define(harness, "MAX_RISE_PER_WINDOW", "0.5")
    code, output = compile_and_run(mutant_rise)
    if code == 0:
        print(
            "FAIL: мутация MAX_RISE_PER_WINDOW->0.5 пережила тест рампы",
            file=sys.stderr,
        )
        return 1
    if "MAX_RISE_PER_WINDOW" not in output and "рамп" not in output.lower():
        print(
            "FAIL: мутация MAX_RISE_PER_WINDOW->0.5 упала не там, где ожидалось "
            f"(вывод: {output!r})",
            file=sys.stderr,
        )
        return 1
    print("Beer boiling ramp detector MAX_RISE_PER_WINDOW mutation was rejected as expected:")
    sys.stdout.write(output)

    # Мутация 2: STABLE_WINDOWS_REQUIRED 2 -> 20 (нужно в 10 раз больше
    # подтверждений подряд) обязана завалить фиксацию кипения за 100 с.
    mutant_stable = mutate_define(harness, "STABLE_WINDOWS_REQUIRED", "20")
    code, output = compile_and_run(mutant_stable)
    if code == 0:
        print(
            "FAIL: мутация STABLE_WINDOWS_REQUIRED->20 пережила тест плато",
            file=sys.stderr,
        )
        return 1
    print("Beer boiling ramp detector STABLE_WINDOWS_REQUIRED mutation was rejected as expected:")
    sys.stdout.write(output)

    # Мутация 3: [Пиво 02.09 B] убрать сброс samplesFilled в ветке
    # "currentTemp < MIN_BOILING_TEMP" - просадка перестаёт начинать новое
    # окно истории, и после возврата на плато детектор досчитывает
    # стабильность по старым (донедавним) точкам почти мгновенно вместо
    # нового окна ~60-70 с (см. run_dip_below_min_restarts_window).
    dip_reset_target = (
        "boilingDetector.stableCount = 0;\n"
        "        boilingDetector.samplesFilled = 0;\n"
        "        boilingDetector.historyIndex = 0;\n"
        "        return false;"
    )
    dip_reset_mutant_text = (
        "boilingDetector.stableCount = 0;\n"
        "        boilingDetector.historyIndex = 0;\n"
        "        return false;"
    )
    if harness.count(dip_reset_target) != 1:
        print(
            "FAIL: could not build dip-reset (samplesFilled) mutation - target text not found exactly once",
            file=sys.stderr,
        )
        return 1
    mutant_dip_reset = harness.replace(dip_reset_target, dip_reset_mutant_text, 1)
    code, output = compile_and_run(mutant_dip_reset)
    if code == 0:
        print(
            "FAIL: мутация (убран сброс samplesFilled при просадке) пережила тест",
            file=sys.stderr,
        )
        return 1
    if "секунде" not in output:
        print(
            "FAIL: мутация (убран сброс samplesFilled при просадке) упала не там, где ожидалось "
            f"(вывод: {output!r})",
            file=sys.stderr,
        )
        return 1
    print("Beer boiling ramp detector dip-reset (samplesFilled) mutation was rejected as expected:")
    sys.stdout.write(output)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
