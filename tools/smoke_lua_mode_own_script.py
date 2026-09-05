#!/usr/bin/env python3
"""Находка 24.08.2026: get_lua_mode_name(bool filename) (lua.h) была цепочкой
if/else if по режиму (beer/dist/bk/nbk/suvid), а SAMOVAR_LUA_MODE отдельной
ветки не имел и молча падал в финальный else - тот же, что и
SAMOVAR_RECTIFICATION_MODE. В результате пользователь, выбравший режим Lua
(там вся логика должна жить в его собственном /script.lua - у режима нет
своего tick в mode_registry.h, т.е. никакой встроенной автоматики), получал
ЕЩЁ и /rectificat.lua - штатный доп-скрипт заполнения куба насосом для
ректификации. do_lua_script() (lua.h) выполняет "режимный" скрипт (script2)
периодически НЕЗАВИСИМО от того, что делает пользовательский script.lua,
пока он успешно скомпилирован (local_s2.length() > 0 && lua_chunk_ref_valid) -
т.е. это было реальным управлением насосом (setPumpPwm в rectificat.lua) в
режиме, где пользователь ожидает только свой собственный скрипт.

Это же имя используется как ключ инвалидации object-store между режимами
(load_lua_script(): "if (lua_last_loaded_type_script != lua_type_script)") -
пока LUA_MODE и RECTIFICATION_MODE делили одно и то же имя "rect", состояние
setObject()/getObject() между ними тоже не изолировалось при переключении.

Проверяем РЕАЛЬНОЕ тело get_lua_mode_name() (извлечённое из lua.h, без
переписывания) для всех режимов: у SAMOVAR_LUA_MODE обе перегрузки
(filename=true/false) обязаны возвращать пустую строку - "режимного скрипта
нет" - а не "rect"/"/rectificat.lua". Пустая строка безопасна для обоих
потребителей (проверено по исходникам framework-arduinoespressif32/libraries/
FS/vfs_api.cpp: SPIFFS.open("/") у пустого имени открывается как директория,
но File::available()/readString() на директории гарантированно возвращают 0/"" -
get_lua_script("") ведёт себя как "файл не найден", без ошибки и без побочных
эффектов; lua_compile_chunk_locked("") тоже сразу выходит по
"script.length() == 0" без записи в лог).

Тест пинит именно РАЗВИЛКУ по режиму (компилирует и запускает реальный код), а
не просто наличие строки "SAMOVAR_LUA_MODE" где-то в файле - если ветку для
SAMOVAR_LUA_MODE убрать, режим снова провалится в rect-fallback и одна из
проверок ниже упадёт.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
LUA_H = ROOT / "lua.h"

HARNESS_TEMPLATE = """
#include <iostream>
#include <string>

// Минимальная замена Arduino String - только то, что использует реальное
// тело get_lua_mode_name() (конкатенация со строковыми литералами и с
// пустыми #define-макросами LUA_BEER/... ниже, которые сами - "").
class String {
 public:
  String() = default;
  String(const char* text) : value_(text ? text : "") {}
  String(const std::string& text) : value_(text) {}

  friend String operator+(const char* lhs, const String& rhs) {
    return String(std::string(lhs ? lhs : "") + rhs.value_);
  }
  String operator+(const char* rhs) const {
    return String(value_ + std::string(rhs ? rhs : ""));
  }
  String operator+(const String& rhs) const {
    return String(value_ + rhs.value_);
  }
  String& operator=(const char* text) {
    value_ = text ? text : "";
    return *this;
  }

  const std::string& value() const { return value_; }

 private:
  std::string value_;
};

enum SAMOVAR_MODE {
  SAMOVAR_RECTIFICATION_MODE,
  SAMOVAR_DISTILLATION_MODE,
  SAMOVAR_BEER_MODE,
  SAMOVAR_BK_MODE,
  SAMOVAR_NBK_MODE,
  SAMOVAR_SUVID_MODE,
  SAMOVAR_LUA_MODE,
  SAMOVAR_CHEESE_MODE,
};
static SAMOVAR_MODE Samovar_CR_Mode;

// Реальные дефолты этих макросов в Samovar.h - пустая строка (см. ifndef там).
#ifndef LUA_BEER
#define LUA_BEER ""
#endif
#ifndef LUA_DIST
#define LUA_DIST ""
#endif
#ifndef LUA_BK
#define LUA_BK ""
#endif
#ifndef LUA_NBK
#define LUA_NBK ""
#endif
#ifndef LUA_SUVID
#define LUA_SUVID ""
#endif
#ifndef LUA_RECT
#define LUA_RECT ""
#endif

@FUNCTION_BODY@

int main() {
  int failures = 0;
  auto check = [&](SAMOVAR_MODE mode, bool filename, const std::string& expected, const char* label) {
    Samovar_CR_Mode = mode;
    String result = get_lua_mode_name(filename);
    if (result.value() != expected) {
      std::cerr << "FAIL " << label << ": expected '" << expected << "', got '" << result.value() << "'\\n";
      failures++;
    }
  };

  check(SAMOVAR_RECTIFICATION_MODE, true, "/rectificat.lua", "rect filename");
  check(SAMOVAR_RECTIFICATION_MODE, false, "rect", "rect name");
  check(SAMOVAR_BEER_MODE, true, "/beer.lua", "beer filename");
  check(SAMOVAR_BEER_MODE, false, "beer", "beer name");
  check(SAMOVAR_DISTILLATION_MODE, true, "/dist.lua", "dist filename");
  check(SAMOVAR_DISTILLATION_MODE, false, "dist", "dist name");
  check(SAMOVAR_BK_MODE, true, "/bk.lua", "bk filename");
  check(SAMOVAR_BK_MODE, false, "bk", "bk name");
  check(SAMOVAR_NBK_MODE, true, "/nbk.lua", "nbk filename");
  check(SAMOVAR_NBK_MODE, false, "nbk", "nbk name");
  check(SAMOVAR_SUVID_MODE, true, "/suvid.lua", "suvid filename");
  check(SAMOVAR_SUVID_MODE, false, "suvid", "suvid name");
  check(SAMOVAR_CHEESE_MODE, true, "/cheese.lua", "cheese filename");
  check(SAMOVAR_CHEESE_MODE, false, "cheese", "cheese name");

  // Ключевая проверка находки: LUA_MODE не должен унаследовать rect-fallback.
  check(SAMOVAR_LUA_MODE, true, "", "lua mode filename must be empty (no rectificat.lua leak into user's own script)");
  check(SAMOVAR_LUA_MODE, false, "", "lua mode name must be empty (no borrowed rect buttons)");

  if (failures) {
    std::cerr << failures << " check(s) failed\\n";
    return 1;
  }
  std::cout << "get_lua_mode_name behavioural checks passed (8 modes, filename=true/false)\\n";
  return 0;
}
"""


def build_harness() -> str:
    source = LUA_H.read_text(encoding="utf-8", errors="ignore")
    body = extract_function_body(source, "String get_lua_mode_name(bool filename) {")
    function_text = f"String get_lua_mode_name(bool filename) {{\n{body}\n}}"
    return HARNESS_TEMPLATE.replace("@FUNCTION_BODY@", function_text)


def compile_and_run(harness: str, label: str) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-lua-mode-own-script-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "lua_mode_own_script_test.cpp"
        binary = temp / "lua_mode_own_script_test"
        source.write_text(harness, encoding="utf-8")
        compiled = subprocess.run(
            ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
             str(source), "-o", str(binary)],
            capture_output=True,
            text=True,
            check=False,
        )
        if compiled.returncode:
            output = compiled.stdout + compiled.stderr
            sys.stderr.write(f"[{label}] compile failed:\n{output}")
            return compiled.returncode, output
        ran = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
        output = ran.stdout + ran.stderr
        sys.stdout.write(ran.stdout)
        sys.stderr.write(ran.stderr)
        return ran.returncode, output


def main() -> int:
    try:
        harness = build_harness()
    except ValueError as exc:
        print(f"lua mode own-script smoke failed: {exc}", file=sys.stderr)
        return 1

    code, _ = compile_and_run(harness, "get_lua_mode_name behavioural")
    if code != 0:
        print("lua mode own-script smoke failed", file=sys.stderr)
        return 1

    print("lua mode own-script smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
