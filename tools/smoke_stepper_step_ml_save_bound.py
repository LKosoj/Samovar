#!/usr/bin/env python3
"""[Б1.2] Поведенческий тест нижней границы StepperStepMl в /save.

WebServer.ino::kSaveU16Fields поднял нижнюю границу StepperStepMl с 0 до 1
(при StepperStepMl==0 цель TargetStepps = Volume * StepperStepMl всегда 0,
строка программы ректификации по объёму никогда не завершается). Структурная
страховка уже есть - tools/smoke_sanitize_setup_profile_ranges.py требует,
чтобы ЛЮБОЕ сужение границ в kSaveU16Fields было учтено в sanitize_setup_profile_ranges().
Но она проверяет только "границы вообще сужены", а не КОНКРЕТНО это поле и не
поведение самого /save - откат границы StepperStepMl обратно на 0 прошёл бы
её зелёным.

Этот тест компилирует настоящее тело apply_save_u16_arg() и настоящий
numeric_parse.h, находит запись "StepperStepMl" в РЕАЛЬНОМ, дословно
извлечённом массиве kSaveU16Fields (границы 1/65535 из него не переписаны
вручную), и гоняет её через apply_save_u16_arg() как настоящий обработчик
/save это делает в цикле `for (const SaveU16Field &f : kSaveU16Fields)`:
значение "0" обязано быть отвергнуто, значение "1" - принято.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
WEBSERVER = ROOT / "WebServer.ino"
SAMOVAR_H = ROOT / "Samovar.h"

errors: list[str] = []

APPLY_U16_SIGNATURE = (
    "static bool apply_save_u16_arg(AsyncWebServerRequest *request, const char *name, "
    "uint16_t& target, long minValue, long maxValue) {"
)
KSAVE_U16_MARKER = "static const SaveU16Field kSaveU16Fields[] = {"


def extract_ksave_u16_fields(web_text: str) -> str:
    start = web_text.find(KSAVE_U16_MARKER)
    if start < 0:
        raise ValueError("WebServer.ino: kSaveU16Fields не найдена")
    end = web_text.find("};", start)
    if end < 0:
        raise ValueError("WebServer.ino: kSaveU16Fields не закрыта")
    return web_text[start:end + 2]


def extract_setup_eeprom_struct(samovar_h_text: str) -> str:
    start = samovar_h_text.find("struct SetupEEPROM")
    if start < 0:
        raise ValueError("Samovar.h: struct SetupEEPROM не найдена")
    end = samovar_h_text.find("};", start)
    if end < 0:
        raise ValueError("Samovar.h: struct SetupEEPROM не закрыта")
    return samovar_h_text[start:end + 2]


CPP_HARNESS_TEMPLATE = r"""
#include <cstdint>
#include <string>
#include <map>
#include <numeric_parse.h>
using namespace std;

class String {
 public:
  String() {}
  String(const char* s) : v(s ? s : "") {}
  const char* c_str() const { return v.c_str(); }
  std::string v;
};

// ---- реальная struct SetupEEPROM (Samovar.h, извлечена дословно) ----
@SETUP_EEPROM_STRUCT@

struct SaveU16Field { const char* name; uint16_t SetupEEPROM::* member; long minValue; long maxValue; };

// ---- реальная таблица kSaveU16Fields (WebServer.ino, извлечена дословно) ----
@SAVE_U16_FIELDS@

class AsyncWebParameter {
 public:
  AsyncWebParameter(String value, bool file) : value_(value), file_(file) {}
  const String& value() const { return value_; }
  bool isFile() const { return file_; }
 private:
  String value_;
  bool file_;
};

class AsyncWebServerRequest {
 public:
  void set(const char* name, const char* value, bool file = false) {
    params_[name] = new AsyncWebParameter(String(value), file);
  }
  bool hasArg(const char* name) const { return params_.count(name) != 0; }
  AsyncWebParameter* param(const char* name) const {
    auto it = params_.find(name);
    return it == params_.end() ? nullptr : it->second;
  }
 private:
  std::map<std::string, AsyncWebParameter*> params_;
};

static const AsyncWebParameter *get_request_param(AsyncWebServerRequest *request, const char *name) {
  return request->param(name);
}

// ---- реальное тело apply_save_u16_arg (WebServer.ino) ----
@APPLY_SAVE_U16_ARG@

int main() {
  const SaveU16Field* stepperField = nullptr;
  for (const SaveU16Field &f : kSaveU16Fields) {
    if (std::string(f.name) == "StepperStepMl") { stepperField = &f; break; }
  }
  if (!stepperField) {
    printf("FIELD_NOT_FOUND\n");
    return 0;
  }
  printf("BOUNDS %ld %ld\n", stepperField->minValue, stepperField->maxValue);

  {
    AsyncWebServerRequest req;
    req.set("StepperStepMl", "0");
    SetupEEPROM staged{};
    bool ok = apply_save_u16_arg(&req, stepperField->name, staged.*(stepperField->member),
                                  stepperField->minValue, stepperField->maxValue);
    printf("ZERO_ACCEPTED %d\n", ok ? 1 : 0);
  }
  {
    AsyncWebServerRequest req;
    req.set("StepperStepMl", "1");
    SetupEEPROM staged{};
    bool ok = apply_save_u16_arg(&req, stepperField->name, staged.*(stepperField->member),
                                  stepperField->minValue, stepperField->maxValue);
    printf("ONE_ACCEPTED %d\n", ok ? 1 : 0);
    printf("ONE_VALUE %d\n", (int)(staged.*(stepperField->member)));
  }
  return 0;
}
"""


def main() -> int:
    web_text = WEBSERVER.read_text(encoding="utf-8", errors="ignore")
    samovar_h_text = SAMOVAR_H.read_text(encoding="utf-8", errors="ignore")

    try:
        save_u16_fields = extract_ksave_u16_fields(web_text)
        setup_eeprom_struct = extract_setup_eeprom_struct(samovar_h_text)
        apply_u16 = extract_function_body(web_text, APPLY_U16_SIGNATURE)
    except ValueError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    program = (
        CPP_HARNESS_TEMPLATE
        .replace("@SETUP_EEPROM_STRUCT@", setup_eeprom_struct)
        .replace("@SAVE_U16_FIELDS@", save_u16_fields)
        .replace("@APPLY_SAVE_U16_ARG@", f"{APPLY_U16_SIGNATURE}\n{apply_u16}\n}}")
    )

    with tempfile.TemporaryDirectory(prefix="samovar-stepper-step-ml-save-") as tmp:
        src = Path(tmp) / "stepper_step_ml.cpp"
        exe = Path(tmp) / "stepper_step_ml"
        src.write_text(program, encoding="utf-8")
        compile_proc = subprocess.run(
            ["g++", "-std=c++17", "-Wall", "-Wextra", f"-I{ROOT}", "-o", str(exe), str(src)],
            capture_output=True, text=True,
        )
        if compile_proc.returncode != 0:
            print("FAIL: harness did not compile:\n" + compile_proc.stderr, file=sys.stderr)
            return 1
        run_proc = subprocess.run([str(exe)], capture_output=True, text=True)
        if run_proc.returncode != 0:
            print("FAIL: harness crashed:\n" + run_proc.stderr, file=sys.stderr)
            return 1

    lines = dict(line.split(" ", 1) for line in run_proc.stdout.strip("\n").split("\n") if " " in line)

    if "FIELD_NOT_FOUND" in run_proc.stdout:
        errors.append("kSaveU16Fields: запись StepperStepMl не найдена")
    else:
        bounds = lines.get("BOUNDS", "")
        if bounds != "1 65535":
            errors.append(f"kSaveU16Fields: ожидались границы StepperStepMl '1 65535', получено {bounds!r}")
        if lines.get("ZERO_ACCEPTED") != "0":
            errors.append("apply_save_u16_arg приняла StepperStepMl=0 - нижняя граница не держится")
        if lines.get("ONE_ACCEPTED") != "1":
            errors.append("apply_save_u16_arg отвергла StepperStepMl=1 - граница слишком узкая")
        if lines.get("ONE_VALUE") != "1":
            errors.append(f"StepperStepMl=1 должно записаться в staged как 1, получено {lines.get('ONE_VALUE')!r}")

    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    print("OK: StepperStepMl=0 отвергается, StepperStepMl=1 принимается через реальную kSaveU16Fields")
    print("stepper step ml save bound smoke check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
