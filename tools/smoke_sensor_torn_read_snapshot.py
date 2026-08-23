#!/usr/bin/env python3
"""[П18] Поведенческая проверка согласованного снимка (ErrCount, avgTemp) в
sensor_reading_valid() (alarm.h).

DSSensor.avgTemp/ErrCount пишутся из задачи опроса датчиков, а sensor_reading_valid()
читает их из задачи аварийного надзора. Раздельные ("врозь") обращения к двум полям
могут разъехаться (torn read): реально пишущая сторона обновляет avgTemp, а
ErrCount ещё старое (или наоборот) - в момент чтения получаем несуществовавшую
комбинацию. Опасны оба направления:
  - ложный останов при исправном датчике (пара "выглядит" хуже, чем есть);
  - "показание валидно" на только что отказавшем датчике (хуже: это пропуск аварии).

Тест вытаскивает РЕАЛЬНОЕ тело sensor_reading_valid() из alarm.h и подставляет
вместо DSSensor тип с управляемыми полями: каждое обращение к ErrCount/avgTemp
считает номер обращения и в заданный момент "переключает" значение с ДО-записи на
ПОСЛЕ-записи - так моделируется реальная гонка писателя ровно между двумя чтениями
одного и того же поля, без изменения проверяемого кода.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]

SIGNATURE = "inline bool sensor_reading_valid(const DSSensor& sensor)"

HARNESS_TEMPLATE = r'''
#include <cstdint>
#include <iostream>

// Общий "тик" обращений к полям - считает КАЖДОЕ чтение ErrCount ИЛИ avgTemp,
// в том порядке, в каком их читает реальный код sensor_reading_valid().
static int g_tick = 0;
// -1 = гонки нет (стабильные значения на всём протяжении вызова).
static int g_writeAtTick = -1;

// Без инициализаторов членов по умолчанию - в C++11 они лишили бы структуру
// статуса агрегата, и фигурная инициализация ChaosInt{a, b} ниже перестала бы
// компилироваться.
struct ChaosInt {
  int before;
  int after;
  operator int() const {
    ++g_tick;
    return (g_writeAtTick >= 0 && g_tick >= g_writeAtTick) ? after : before;
  }
};

struct ChaosFloat {
  float before;
  float after;
  operator float() const {
    ++g_tick;
    return (g_writeAtTick >= 0 && g_tick >= g_writeAtTick) ? after : before;
  }
};

struct DSSensor {
  ChaosInt ErrCount;
  ChaosFloat avgTemp;
};

// ---- Реальный код под тестом ----
@SENSOR_READING_VALID_BODY@

static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

int main() {
  // --- Контроль: без гонки (запись не пересекается с окном чтения) - оба
  //     состояния (стабильно валидное и стабильно невалидное) читаются верно. ---
  {
    g_tick = 0;
    g_writeAtTick = -1;
    DSSensor s;
    s.ErrCount = ChaosInt{0, 0};
    s.avgTemp = ChaosFloat{50.0f, 50.0f};
    check(sensor_reading_valid(s) == true, "стабильно валидная пара должна читаться как валидная");
  }
  {
    g_tick = 0;
    g_writeAtTick = -1;
    DSSensor s;
    s.ErrCount = ChaosInt{20, 20};
    s.avgTemp = ChaosFloat{50.0f, 50.0f};
    check(sensor_reading_valid(s) == false, "стабильно невалидная пара (ErrCount>10) должна читаться как невалидная");
  }

  // --- Опасный случай А: датчик ТОЛЬКО ЧТО ОТКАЗАЛ (переход
  //     valid(ErrCount=0,avgTemp=50) -> invalid(ErrCount=20,avgTemp=50)) в самый
  //     момент чтения. Без защиты от torn read реально можно поймать комбинацию
  //     "старый ErrCount=0" + что угодно ещё и ошибочно признать датчик исправным -
  //     это опаснее (ложное ОК на отказавшем датчике), поэтому проверяем, что
  //     итоговый вердикт СОГЛАСОВАН (соответствует ДО или ПОСЛЕ целиком, а не смеси).
  {
    DSSensor s;
    s.ErrCount = ChaosInt{0, 20};
    s.avgTemp = ChaosFloat{50.0f, 50.0f};
    g_tick = 0;
    g_writeAtTick = 2;  // запись "происходит" сразу после первого чтения ErrCount
    bool result = sensor_reading_valid(s);
    check(result == false,
          "гонка на переходе valid->invalid обязана дать согласованный (итоговый = invalid) вердикт, не смешанный");
  }

  // --- Опасный случай Б: датчик ТОЛЬКО ЧТО ВОССТАНОВИЛСЯ (переход
  //     invalid(ErrCount=15,avgTemp=50) -> valid(ErrCount=0,avgTemp=80)) ровно между
  //     чтением ErrCount и avgTemp. Требуем ИТОГОВЫЙ вердикт, соответствующий одному
  //     согласованному снимку (ДО целиком невалиден, ПОСЛЕ целиком валиден) - оба
  //     приемлемы, а вот "невалиден из-за протухшего ErrCount, при живой новой
  //     avgTemp" - смешанная, запрещённая комбинация была бы неопределённым
  //     поведением старого (небезопасного) кода.
  {
    DSSensor s;
    s.ErrCount = ChaosInt{15, 0};
    s.avgTemp = ChaosFloat{50.0f, 80.0f};
    g_tick = 0;
    g_writeAtTick = 3;  // запись между вторым чтением ErrCount и первым чтением avgTemp
    bool result = sensor_reading_valid(s);
    // Ретрай сходится ровно на 2-й попытке к состоянию "после" (валидно) целиком -
    // без защиты от torn read здесь можно поймать смешанную комбинацию
    // "protuhший ErrCount=15 (invalid)" + "свежую valid avgTemp=80", то есть
    // ошибочно признать датчик невалидным сразу ПОСЛЕ его восстановления.
    check(result == true, "после восстановления датчика итоговый вердикт обязан стать valid, а не застрять на смеси до/после");
  }

  if (failures != 0) return 1;
  std::cout << "sensor_reading_valid torn-read snapshot behaviour checks passed\n";
  return 0;
}
'''


def build_harness() -> str:
    source = (ROOT / "alarm.h").read_text(encoding="utf-8")
    body = extract_function_body(source, SIGNATURE)
    return HARNESS_TEMPLATE.replace(
        "@SENSOR_READING_VALID_BODY@",
        "static bool sensor_reading_valid(const DSSensor& sensor) {" + body + "}",
    )


def compile_and_run(harness: str) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-sensor-torn-read-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "sensor_torn_read_test.cpp"
        binary = temp / "sensor_torn_read_test"
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
    try:
        harness = build_harness()
    except ValueError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return compile_and_run(harness)


if __name__ == "__main__":
    sys.exit(main())
