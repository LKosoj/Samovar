#!/usr/bin/env python3
"""Контракт ADS1115 как единственного источника pH при USE_ADS1115."""

import subprocess
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body


ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


cheese = (ROOT / "cheese.h").read_text(encoding="utf-8")
samovar = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
web = (ROOT / "WebServer.ino").read_text(encoding="utf-8")
lua = (ROOT / "lua.h").read_text(encoding="utf-8")
calibration = (ROOT / "data_raw/calibrate_ph.htm").read_text(encoding="utf-8")
configurator = (ROOT / "tools/samovar_configurator.py").read_text(encoding="utf-8")
readme = (ROOT / "README.md").read_text(encoding="utf-8")
readme_en = (ROOT / "README_EN.md").read_text(encoding="utf-8")

for source in (
    cheese, samovar, web, lua, calibration, configurator, readme, readme_en,
    (ROOT / "Samovar_ini.h").read_text(encoding="utf-8"),
    (ROOT / "user_config_override.example.h").read_text(encoding="utf-8"),
):
    require("CHEESE_PH_ADS1115_CHANNEL" not in source,
            "Не должна появляться отдельная настройка канала ADS1115")

require('OptionalSpec("USE_ADS1115"' in configurator,
        "Конфигуратор не предлагает адрес ADS1115")
require("USE_ADS1115 автоматически переводит pH на AIN0" in configurator,
        "В конфигураторе не объяснён автоматический выбор AIN0")
require("`#define USE_ADS1115 0x48` автоматически переводит датчик pH на вход AIN0" in readme and
        "Отдельной настройки канала нет" in readme,
        "README.md не описывает автоматический AIN0 без отдельной настройки канала")
require("`#define USE_ADS1115 0x48` automatically moves the pH sensor to ADS1115 input AIN0" in readme_en and
        "There is no separate channel setting" in readme_en,
        "README_EN.md не синхронизирован с инструкцией ADS1115")
require("cheese_ph_init();" in samovar,
        "ADS1115 не инициализируется после запуска Wire")

start = extract_function_body(cheese, "void cheese_proc()")
require("cheese_ph_prepare()" in start and
        start.find("cheese_ph_prepare()") < start.find("create_data()") < start.find("set_power(true)"),
        "Недоступный ADS1115 должен отменять старт до журнала и нагрева")
require("#ifndef USE_ADS1115" in start and "pinMode(LUA_PIN, INPUT);" in start,
        "LUA_PIN должен настраиваться для pH только без ADS1115")

reserved = extract_function_body(lua, "inline bool lua_pin_reserved_for_cheese_ph(int pin)")
require("#ifdef USE_ADS1115" in reserved and "return false;" in reserved,
        "ADS1115 должен освобождать LUA_PIN для Lua")

save = extract_function_body(web, "void handleSave(AsyncWebServerRequest *request)")
require("cheese_ph_calibration_requested(request)" in save and
        "!cheese_ph_available()" in save,
        "Сервер не блокирует сохранение pH-калибровки без ADS1115")
for token in ("cheesePhAvailable", "cheesePhAds1115Address"):
    require(token in web, f"/ui-bootstrap не отдаёт {token}")
    require(token in calibration, f"Страница калибровки не использует {token}")
for element_id in ("capturePoint1", "capturePoint2", "calculatePh", "savePh"):
    require(element_id in calibration, f"Нет блокировки элемента {element_id}")
require("ADS1115" in calibration and "AIN0" in calibration,
        "Инструкция калибровки не описывает ADS1115 AIN0")

configure = extract_function_body(cheese, "inline bool cheese_ads1115_configure()")
read_raw = extract_function_body(cheese, "inline bool cheese_ads1115_read_raw(int& raw)")
harness = f'''\
#include <cstdint>
#include <iostream>
#define USE_ADS1115 0x48
static bool cheesePhAds1115Ready = false;
static bool writeOk = true;
static bool readOk = true;
static uint8_t writtenAddress = 0;
static uint8_t writtenRegister = 0;
static uint16_t writtenValue = 0;
static uint16_t nextRead = 0;
bool i2c_stepper_write_u16(uint8_t address, uint8_t reg, uint16_t value) {{
  writtenAddress = address; writtenRegister = reg; writtenValue = value;
  return writeOk;
}}
bool i2c_stepper_read_u16(uint8_t address, uint8_t reg, uint16_t& value, uint32_t) {{
  writtenAddress = address; writtenRegister = reg;
  if (!readOk) return false;
  value = nextRead;
  return true;
}}
inline bool cheese_ads1115_configure() {{ {configure} }}
inline bool cheese_ads1115_read_raw(int& raw) {{ {read_raw} }}
static int failures = 0;
void check(bool ok, const char* message) {{
  if (!ok) {{ std::cerr << "FAIL: " << message << '\\n'; ++failures; }}
}}
int main() {{
  check(cheese_ads1115_configure(), "configuration failed");
  check(cheesePhAds1115Ready, "successful configuration did not mark ready");
  check(writtenAddress == 0x48 && writtenRegister == 1 && writtenValue == 0xC283,
        "AIN0 continuous 128 SPS +-4.096 V configuration is wrong");
  int raw = 777;
  nextRead = 1234;
  check(cheese_ads1115_read_raw(raw) && raw == 1234,
        "positive ADS1115 sample was not returned");
  nextRead = static_cast<uint16_t>(static_cast<int16_t>(-1234));
  check(cheese_ads1115_read_raw(raw) && raw == -1234,
        "signed ADS1115 sample was not returned");
  readOk = false;
  raw = 321;
  check(!cheese_ads1115_read_raw(raw) && raw == 321 && !cheesePhAds1115Ready,
        "read failure must invalidate ADS1115 without changing raw");
  writeOk = false;
  check(!cheese_ads1115_configure() && !cheesePhAds1115Ready,
        "configuration failure must leave ADS1115 unavailable");
  return failures == 0 ? 0 : 1;
}}
'''

def compile_and_run(source_text: str) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix="samovar-ads1115-") as tmp:
        source = Path(tmp) / "ads.cpp"
        binary = Path(tmp) / "ads"
        source.write_text(source_text, encoding="utf-8")
        built = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
            capture_output=True, text=True, check=False,
        )
        require(built.returncode == 0, "ADS1115 harness не компилируется:\n" + built.stderr)
        return subprocess.run([str(binary)], capture_output=True, text=True, check=False)


ran = compile_and_run(harness)
require(ran.returncode == 0,
        "ADS1115 harness завершился с ошибкой:\n" + ran.stdout + ran.stderr)

mutations = (
    ("0xC283", "0xC183", "конфигурация AIN0"),
    ("raw = static_cast<int16_t>(value);", "raw = value;", "знаковое значение ADS1115"),
    ("cheesePhAds1115Ready = false;\n    return false;",
     "cheesePhAds1115Ready = true;\n    return false;", "сброс доступности при ошибке чтения"),
)
for old, new, label in mutations:
    require(old in harness, f"Не найдена точка мутации: {label}")
    mutant = harness.replace(old, new, 1)
    mutated_run = compile_and_run(mutant)
    require(mutated_run.returncode != 0, f"Мутация выжила: {label}")

print("OK: ADS1115 AIN0 pH source, scoped blocking and UI contract")
