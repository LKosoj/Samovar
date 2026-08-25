#!/usr/bin/env python3
"""[T28] Мигрированный из старого EEPROM профиль обязан пройти те же границы,
что и форма /save, а не остаться "рабочими настройками" из битого сектора.

migrate_from_eeprom() (NVS_Manager.ino) при переходе со старой EEPROM-схемы
проверяет только flag и Mode - ещё ~30 числовых полей (температуры, дельты,
коэффициенты PID, диаметр колонны и т.д.) переносятся как есть. Если сектор
битый, мусор молча становится "рабочими настройками" на годы вперёд - до
следующей ручной правки в setup.htm.

Координатор явно запретил трогать NVS_Manager.ino. Решение реализовано в
WebServer.ino: новая функция sanitize_setup_profile_ranges() переиспользует
ТЕ ЖЕ таблицы границ, что уже проверяют форму /save (kSaveFloatFields -
NaN/меньше min/больше max, kSaveU8Fields - меньше min/больше max), сбрасывает
плохие поля на дефолт (set_default_setup_profile()) и перечисляет их имена.
Вызывается из setup() (Samovar.ino) только когда migratedFromLegacy == true,
сразу после лечения HeaterResistant и до персиста в NVS - так, чтобы
починенный профиль лёг в NVS насовсем, а не чинился на каждой загрузке заново.

Тест не использует заглушечные таблицы/дефолты - только РЕАЛЬНЫЕ:
  - struct SetupEEPROM (Samovar.h) - извлечена целиком, дословно;
  - struct SaveFloatField/SaveU8Field и массивы kSaveFloatFields/kSaveU8Fields
    (WebServer.ino) - извлечены дословно;
  - set_default_setup_profile() (NVS_Manager.ino) вместе с настоящим
    #include "profile_setup_fields.h" (тот же X-macro список полей, которым
    её тело реально пользуется) - не переписанные вручную дефолты;
  - sanitize_setup_profile_ranges() (WebServer.ino) - извлечена дословно;
  - блок `if (migratedFromLegacy) { ... }` из setup() (Samovar.ino) - извлечён
    дословно тем же extract_braced_block_after, что использует
    smoke_save_param_allowlist_sync.py для соседнего save_param_name_allowed.

Мок только один - report_degraded_boot(stage, error) (не static: тело
`if (migratedFromLegacy)` реально его вызывает, static без вызова уронил бы
сборку на -Wunused-function раньше, чем дойдёт до runtime-проверки).

Сценарии:
  1. migratedFromLegacy=true, профиль с NaN (DeltaSteamTemp), значением ниже
     минимума (Kp < 0), значениями выше максимума (ColDiam, TimeZone) и
     валидными полями (autospeed, SetSteamTemp) - функция возвращает true,
     плохие поля становятся РЕАЛЬНЫМИ дефолтами set_default_setup_profile(),
     валидные поля не тронуты, имена собраны через запятую; вызывающий блок
     setup() зовёт report_degraded_boot("profile_migration", ...) ровно один
     раз с причиной, упоминающей все четыре имени.
  2. migratedFromLegacy=true, полностью валидный профиль - функция возвращает
     false, report_degraded_boot не вызывается.
  3. migratedFromLegacy=false - sanitize_setup_profile_ranges не вызывается
     вовсе (даже для битого профиля), report_degraded_boot не вызывается -
     починка касается только пути миграции из легаси EEPROM.

Мутация: условие NaN-проверки `if (!isfinite(v) || v < f.minValue || v > f.maxValue)`
в цикле по kSaveFloatFields заменяется на `if (false)` - обязана завалить
харнесс на "поле DeltaSteamTemp осталось NaN".
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []

web_text = (ROOT / "WebServer.ino").read_text(encoding="utf-8", errors="ignore")
samovar_h_text = (ROOT / "Samovar.h").read_text(encoding="utf-8", errors="ignore")
nvs_text = (ROOT / "NVS_Manager.ino").read_text(encoding="utf-8", errors="ignore")
samovar_ino_text = (ROOT / "Samovar.ino").read_text(encoding="utf-8", errors="ignore")
api_text = (ROOT / "samovar_api.h").read_text(encoding="utf-8", errors="ignore")


# ---- Текстовые проверки расположения/подключения -----------------------

if "bool sanitize_setup_profile_ranges(SetupEEPROM& profile, String& fixedFieldsOut);" not in api_text:
    errors.append("samovar_api.h: нет прототипа sanitize_setup_profile_ranges")

save_allowed_end = web_text.find("bool save_param_name_allowed(const String& name) {")
sanitize_pos = web_text.find("bool sanitize_setup_profile_ranges(SetupEEPROM& profile, String& fixedFieldsOut) {")
if save_allowed_end < 0:
    errors.append("WebServer.ino: save_param_name_allowed не найден")
elif sanitize_pos < 0:
    errors.append("WebServer.ino: sanitize_setup_profile_ranges не найден")
elif sanitize_pos < save_allowed_end:
    errors.append(
        "sanitize_setup_profile_ranges должна идти ПОСЛЕ save_param_name_allowed, "
        "а не до неё (иначе попадёт в блок, извлекаемый extract_braced_block_after "
        "в smoke_save_param_allowlist_sync.py, и исказит проверку allowlist)"
    )

if "NVS_Manager.ino" and "sanitize_setup_profile_ranges" in nvs_text:
    errors.append("NVS_Manager.ino не должен звать sanitize_setup_profile_ranges - координатор запретил его трогать")


# ---- Извлечение реальных фрагментов -------------------------------------

def extract(source: str, signature: str, label: str) -> str:
    try:
        return extract_function_body(source, signature)
    except ValueError as exc:
        errors.append(f"{label}: {exc}")
        return ""


setup_eeprom_struct = ""
start = samovar_h_text.find("struct SetupEEPROM")
end = samovar_h_text.find("};", start) if start >= 0 else -1
if start < 0 or end < 0:
    errors.append("Samovar.h: struct SetupEEPROM не найдена")
else:
    setup_eeprom_struct = samovar_h_text[start:end + 2]

sanitize_body = extract(
    web_text,
    "bool sanitize_setup_profile_ranges(SetupEEPROM& profile, String& fixedFieldsOut) {",
    "sanitize_setup_profile_ranges",
)

default_profile_body = extract(
    nvs_text, "void set_default_setup_profile(SetupEEPROM& candidate) {", "set_default_setup_profile"
)

save_float_fields = ""
start = web_text.find("static const SaveFloatField kSaveFloatFields[]")
end = web_text.find("};", start) if start >= 0 else -1
if start < 0 or end < 0:
    errors.append("WebServer.ino: kSaveFloatFields не найдена")
else:
    save_float_fields = web_text[start:end + 2]

save_u8_fields = ""
start = web_text.find("static const SaveU8Field kSaveU8Fields[]")
end = web_text.find("};", start) if start >= 0 else -1
if start < 0 or end < 0:
    errors.append("WebServer.ino: kSaveU8Fields не найдена")
else:
    save_u8_fields = web_text[start:end + 2]

# Страж дыры: sanitize обходит только float- и u8-таблицы. Сегодня это безопасно,
# потому что у ВСЕХ полей kSaveU16Fields границы - полный диапазон uint16_t, то есть
# проверять там нечего. Как только кто-нибудь сузит границы хотя бы одного поля
# (например, ограничит SuvidHoldMinutes разумным максимумом), значение из старого
# EEPROM проедет мимо санитайзера - форма /save его отобьёт, а миграция пропустит.
# Тест обязан упасть ИМЕННО в этот момент, а не молча пропустить расхождение.
start = web_text.find("static const SaveU16Field kSaveU16Fields[]")
end = web_text.find("};", start) if start >= 0 else -1
if start < 0 or end < 0:
    errors.append("WebServer.ino: kSaveU16Fields не найдена")
elif "kSaveU16Fields" not in sanitize_body:
    narrowed = [
        name for name, lo, hi in re.findall(
            r'\{"(\w+)",[^,]+,\s*(-?\d+),\s*(-?\d+)\}', web_text[start:end + 2])
        if (lo, hi) != ("0", "65535")
    ]
    if narrowed:
        errors.append(
            "kSaveU16Fields: у полей " + ", ".join(narrowed) + " границы сужены, "
            "но sanitize_setup_profile_ranges эту таблицу не обходит - "
            "после миграции со старого EEPROM значение проедет без проверки")

migration_block = ""
try:
    inner, _ = extract_braced_block_after(samovar_ino_text, "if (migratedFromLegacy) {")
    migration_block = "if (migratedFromLegacy) {\n" + inner + "\n}\n"
except ValueError as exc:
    errors.append(f"Samovar.ino: {exc}")

if errors:
    print("sanitize_setup_profile_ranges smoke failed (extraction):")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)


# ---- Харнесс --------------------------------------------------------------

HARNESS_TEMPLATE = r'''
#include <cmath>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <string>

using std::isfinite;

// Мини-String вместо Arduino String - настоящему коду нужны только length(),
// c_str(), operator+=(const char*/String) и operator+(String, String).
struct String {
  std::string data;
  String() = default;
  String(const char* s) : data(s ? s : "") {}
  size_t length() const { return data.size(); }
  const char* c_str() const { return data.c_str(); }
  String& operator+=(const char* s) { data += s; return *this; }
  String& operator+=(const String& s) { data += s.data; return *this; }
  String operator+(const String& other) const { String r; r.data = data + other.data; return r; }
  bool contains(const char* needle) const { return data.find(needle) != std::string::npos; }
};

// ---- реальная struct SetupEEPROM (Samovar.h, извлечена дословно) ----
@SETUP_EEPROM_STRUCT@

// ---- реальные таблицы диапазонов (WebServer.ino, извлечены дословно) ----
struct SaveFloatField { const char* name; float SetupEEPROM::* member; float minValue; float maxValue; };
struct SaveU8Field  { const char* name; uint8_t  SetupEEPROM::* member; long minValue; long maxValue; };

// Зависимости внутри самих таблиц (не мок содержательной логики - только
// численные константы-заглушки, реальные значения зависят от варианта платы
// KVIC/RMVK/SEM_AVR и подключаются через #ifdef, которого у хост-харнесса нет).
inline float power_work_mode_threshold() { return 40.0f; }              // power_regulator.h: POWER_WORK_MODE_THRESHOLD (KVIC/RMVK)
static const float CONTROL_HEATER_R_MIN = 2.0f;                          // control_numeric_input.h (реальное значение)
static const float CONTROL_HEATER_R_MAX = 65.0f;                         // control_numeric_input.h (реальное значение)

@SAVE_FLOAT_FIELDS@

@SAVE_U8_FIELDS@

// ---- реальный set_default_setup_profile() (NVS_Manager.ino) + настоящий
// #include "profile_setup_fields.h" (тот же X-macro список полей) ----
static const int SAMOVAR_RECTIFICATION_MODE = 0;  // Samovar.h: enum SAMOVAR_MODE { SAMOVAR_RECTIFICATION_MODE, ... }
static const int STEPPER_STEP_ML = 1020;                      // Samovar_pin.h (реальное значение)
static const float DEFAULT_DIST_TEMP = 99.9f;                 // Samovar_ini.h (реальное значение)
static const int NBK_COLUMN_INERTIA_DEFAULT = 180;            // nbk.h (реальное значение)
static const float NBK_DT_DEFAULT = 0.5f;                     // nbk.h (реальное значение)
static const int NBK_DM_DEFAULT = 100;                        // nbk.h (реальное значение)
static const float NBK_DP_DEFAULT = 0.5f;                     // nbk.h (реальное значение)
static const int NBK_TP_DEFAULT = 81;                         // nbk.h (реальное значение)
static const int NBK_OVERFLOW_PRESSURE_DEFAULT = 40;          // nbk.h (реальное значение)
static const int I2C_STEPPER_STEP_ML_DEFAULT = 16000;         // Samovar.h (реальное значение)
static const float NBK_TN_DEFAULT = 98.5f;                    // nbk.h (реальное значение)

// copyStringSafe (string_utils.h) - настоящее тело, используется дефолтами
// цветовых/строковых полей X-macro.
template <size_t N>
inline void copyStringSafe(char (&dst)[N], const String& src) {
  size_t n = src.length();
  if (n >= N) n = N - 1;
  if (n > 0) memcpy(dst, src.c_str(), n);
  dst[n] = '\0';
}

#include "profile_setup_fields.h"

void set_default_setup_profile(SetupEEPROM& candidate) {
@DEFAULT_PROFILE_BODY@
}

// ---- реальное тело sanitize_setup_profile_ranges (WebServer.ino) ----
bool sanitize_setup_profile_ranges(SetupEEPROM& profile, String& fixedFieldsOut) {
@SANITIZE_BODY@
}

// ---- мок report_degraded_boot (не static: реально вызывается извлечённым
// ниже блоком setup(), static без вызова уронил бы -Wunused-function) ----
int reportDegradedBootCalls = 0;
std::string lastStage;
std::string lastError;
void report_degraded_boot(const char* stage, const char* error) {
  reportDegradedBootCalls++;
  lastStage = stage ? stage : "";
  lastError = error ? error : "";
}

// ---- реальный блок setup() из Samovar.ino (извлечён дословно) ----
static void run_migration_step(bool migratedFromLegacy, SetupEEPROM& startupProfile) {
@MIGRATION_BLOCK@
}

// ---- тесты ----
static int failures = 0;
static void check(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    failures++;
  }
}

int main() {
  SetupEEPROM defaults{};
  set_default_setup_profile(defaults);

  // --- Сценарий 1: NaN + ниже минимума + выше максимума + валидные поля ---
  {
    SetupEEPROM profile{};
    set_default_setup_profile(profile);
    profile.DeltaSteamTemp = NAN;      // float: isfinite() ловит
    profile.Kp = -5.0f;                // float: ниже минимума (0.0f)
    profile.ColDiam = 999.0f;          // float: выше максимума (10.0f)
    profile.TimeZone = 200;            // u8: выше максимума (23)
    profile.autospeed = 5;             // u8: валиден (0..99) - не должен тронуться
    profile.SetSteamTemp = 80.0f;      // float: валиден (0..150) - не должен тронуться

    String fixedFields;
    bool changed = sanitize_setup_profile_ranges(profile, fixedFields);
    check(changed, "профиль с NaN/выходами за диапазон должен дать changed=true");
    check(isfinite(profile.DeltaSteamTemp) && profile.DeltaSteamTemp == defaults.DeltaSteamTemp,
          "DeltaSteamTemp (NaN) должен стать реальным дефолтом, а не остаться NaN");
    check(profile.Kp == defaults.Kp, "Kp (ниже минимума) должен стать реальным дефолтом");
    check(profile.ColDiam == defaults.ColDiam, "ColDiam (выше максимума) должен стать реальным дефолтом");
    check(profile.TimeZone == defaults.TimeZone, "TimeZone (выше максимума) должен стать реальным дефолтом");
    check(profile.autospeed == 5, "валидный autospeed не должен быть тронут");
    check(profile.SetSteamTemp == 80.0f, "валидный SetSteamTemp не должен быть тронут");
    check(fixedFields.contains("DeltaSteamTemp"), "имя DeltaSteamTemp должно попасть в fixedFieldsOut");
    check(fixedFields.contains("Kp"), "имя Kp должно попасть в fixedFieldsOut");
    check(fixedFields.contains("ColDiam"), "имя ColDiam должно попасть в fixedFieldsOut");
    check(fixedFields.contains("TimeZone"), "имя TimeZone должно попасть в fixedFieldsOut");
    check(!fixedFields.contains("autospeed"), "валидное autospeed не должно попасть в fixedFieldsOut");
    check(!fixedFields.contains("SetSteamTemp"), "валидное SetSteamTemp не должно попасть в fixedFieldsOut");

    // Тот же профиль (испорченный) через реальный блок setup(): migratedFromLegacy=true.
    reportDegradedBootCalls = 0;
    lastStage.clear();
    lastError.clear();
    SetupEEPROM viaSetup{};
    set_default_setup_profile(viaSetup);
    viaSetup.DeltaSteamTemp = NAN;
    viaSetup.Kp = -5.0f;
    run_migration_step(true, viaSetup);
    check(reportDegradedBootCalls == 1,
          "migratedFromLegacy=true с испорченным профилем должен вызвать report_degraded_boot ровно один раз");
    check(lastStage == "profile_migration", "report_degraded_boot должен получить stage=profile_migration");
    check(lastError.find("out of range, reset to defaults:") != std::string::npos,
          "report_degraded_boot должен получить причину с текстом 'out of range, reset to defaults:'");
    check(lastError.find("DeltaSteamTemp") != std::string::npos, "причина должна упоминать DeltaSteamTemp");
    check(lastError.find("Kp") != std::string::npos, "причина должна упоминать Kp");
  }

  // --- Сценарий 2: полностью валидный профиль - ничего не трогается ---
  {
    SetupEEPROM profile{};
    set_default_setup_profile(profile);
    String fixedFields;
    bool changed = sanitize_setup_profile_ranges(profile, fixedFields);
    check(!changed, "полностью валидный профиль (сами дефолты) должен дать changed=false");
    check(fixedFields.length() == 0, "полностью валидный профиль не должен собрать ни одного имени");

    reportDegradedBootCalls = 0;
    run_migration_step(true, profile);
    check(reportDegradedBootCalls == 0,
          "валидный профиль при migratedFromLegacy=true не должен вызывать report_degraded_boot");
  }

  // --- Сценарий 3: migratedFromLegacy=false - починка не применяется вовсе ---
  {
    SetupEEPROM profile{};
    set_default_setup_profile(profile);
    profile.DeltaSteamTemp = NAN;  // испорчено, но путь миграции не пройден

    reportDegradedBootCalls = 0;
    run_migration_step(false, profile);
    check(reportDegradedBootCalls == 0,
          "migratedFromLegacy=false не должен запускать починку диапазонов вовсе");
    check(!isfinite(profile.DeltaSteamTemp),
          "migratedFromLegacy=false: испорченное поле должно остаться нетронутым (не наша забота при этом пути)");
  }

  if (failures != 0) return 1;
  std::cout << "sanitize_setup_profile_ranges behaviour checks passed\n";
  return 0;
}
'''


def build_harness() -> str:
    harness = HARNESS_TEMPLATE
    harness = harness.replace("@SETUP_EEPROM_STRUCT@", setup_eeprom_struct)
    harness = harness.replace("@SAVE_FLOAT_FIELDS@", save_float_fields)
    harness = harness.replace("@SAVE_U8_FIELDS@", save_u8_fields)
    harness = harness.replace("@DEFAULT_PROFILE_BODY@", default_profile_body)
    harness = harness.replace("@SANITIZE_BODY@", sanitize_body)
    harness = harness.replace("@MIGRATION_BLOCK@", migration_block)
    return harness


def compile_and_run(harness: str, show_output: bool = True) -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-sanitize-setup-profile-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "sanitize_setup_profile_ranges_test.cpp"
        binary = temp / "sanitize_setup_profile_ranges_test"
        source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            [
                "g++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
                "-I", str(ROOT), str(source), "-o", str(binary),
            ],
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
        if show_output:
            sys.stdout.write(run_result.stdout)
            sys.stderr.write(run_result.stderr)
        return run_result.returncode


def main() -> int:
    harness = build_harness()
    if compile_and_run(harness) != 0:
        return 1

    # ---- Мутация: NaN/диапазонная проверка float-цикла -> ветка никогда не входит ----
    # Буквальное `if (false) {` компилятор бы не пропустил: `float v = profile.*f.member;`
    # выше по тексту стала бы неиспользованной, и -Werror=unused-variable уронил бы
    # СБОРКУ раньше, чем дойдёт до содержательной runtime-проверки - тот самый
    # известный по проекту трюк "мутацию ловит компилятор, а не assert" (см. память
    # проекта: "-Werror маскирует мутации"). `(void)v,` держит v использованной, оставляя
    # условие всё так же тождественно ложным - ветка по-прежнему никогда не входит.
    mutant = harness.replace(
        "if (!isfinite(v) || v < f.minValue || v > f.maxValue) {",
        "if ((void)v, false) {",
        1,
    )
    if mutant == harness:
        print("FAIL: не удалось построить мутацию if (false) для float-цикла", file=sys.stderr)
        return 1
    if compile_and_run(mutant, show_output=False) == 0:
        print(
            "FAIL: мутация (условие float-цикла отключено) пережила тест - "
            "поле DeltaSteamTemp осталось бы NaN вместо реального дефолта",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
