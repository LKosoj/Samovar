#!/usr/bin/env python3
"""[WP7 п.21] html_escape() - единственная точка экранирования HTML в WebServer.ino.

До этого теста описание программы (Descr) и цвета датчиков (SteamColor/PipeColor/...)
подставлялись шаблонизатором в страницу КАК ЕСТЬ. Значение вида "</textarea><h1>x"
ломало разметку у ВСЕХ, кто потом открывал главную страницу, а починить это можно было
только повторной отправкой корректного значения - то есть пользователь мог сам себя
запереть вне интерфейса, которым чинится баг. json_write_escaped() (string_utils.h) для
этого не годится - он экранирует под JSON/<script>-контекст, а не под HTML body/атрибут.

Тест из двух частей, как и smoke_json_escape_canon.py:
1. Архитектурная (без компиляции): все шесть точек подстановки пользовательских данных в
   HTML (Descr x2, videourl, 4 цвета через kGetColorFields, blynkauth/tgtoken/tgchatid)
   обязаны звать html_escape(...), а не подставлять сырое значение.
2. Поведенческая: g++-харнесс с РЕАЛЬНЫМ телом html_escape(), прогнанный на двух разных
   пейлоадах (правило AGENTS.md против теста на одном значении) - один рвёт <textarea>
   HTML-тегом, второй выходит из одинарной кавычки атрибута value='...'. Проверяется, что
   опасные байты (< > ' ") в выводе больше не встречаются НИГДЕ вне ссылки на entity, и
   что экранирование обратимо (entity расшифровывается обратно в исходный символ) -
   значит данные не потеряны, только нейтрализованы.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
WEB_SERVER = ROOT / "WebServer.ino"

HTML_ESCAPE_SIGNATURE = "static String html_escape(const String &s)"

# A: рвёт <textarea>...</textarea> закрывающим тегом и открывает новый заголовок - ровно
#    сценарий из описания дефекта (Descr в data_raw/*.htm сидит внутри <textarea>).
# B: выходит из одинарной кавычки HTML-атрибута value='...' (videourl/blynkauth/tgtoken/
#    tgchatid/цвета в setup.htm) и добавляет обработчик onmouseover - другой контекст,
#    другой опасный символ (одинарная кавычка, а не тег).
VALUE_A = "</textarea><h1>pwned</h1>"
VALUE_B = "x' onmouseover='alert(1)"

assert "<" in VALUE_A and ">" in VALUE_A, "фикстура A обязана содержать теги"
assert "'" in VALUE_B, "фикстура B обязана содержать одинарную кавычку"

# (файл, сигнатура, требуемая подстрока с вызовом html_escape) - шесть точек подстановки,
# перечисленных в отчёте по п.21 как места правки.
DELEGATES = [
    ("indexKeyProcessor", 'html_escape((String)SamSetup.SteamColor)'),
    ("indexKeyProcessor", 'html_escape((String)SamSetup.videourl)'),
    ("indexKeyProcessorWithSnapshots", 'html_escape(description)'),
    ("setupKeyProcessor", 'html_escape(String(SamSetup.*f.member))'),
    ("setupKeyProcessor", 'html_escape(String(SamSetup.blynkauth))'),
    ("setupKeyProcessor", 'html_escape(String(SamSetup.tg_token))'),
    ("setupKeyProcessor", 'html_escape(String(SamSetup.tg_chat_id))'),
]


def check_delegates(source: str, errors: list[str]) -> None:
    for label, needle in DELEGATES:
        if needle not in source:
            errors.append(
                f"WebServer.ino: не найдено {needle!r} ({label}) - подстановка "
                "пользовательских данных в HTML снова идёт без html_escape(), "
                "страница ломается для всех последующих посетителей"
            )


HARNESS_TEMPLATE = r'''
#include <cstdio>
#include <cstring>
#include <string>

#define F(x) x

class String {
 public:
  String() = default;
  String(const char* s) : v(s ? s : "") {}
  size_t length() const { return v.size(); }
  char charAt(unsigned int i) const { return v[i]; }
  void reserve(size_t) {}
  String& operator+=(char c) { v += c; return *this; }
  String& operator+=(const char* s) { v += s; return *this; }
  const char* c_str() const { return v.c_str(); }
  std::string v;
};

{BODY}

int main() {
  const char* payloads[] = { {PAYLOADS} };
  for (const char* raw : payloads) {
    String out = html_escape(String(raw));
    printf("%s\n", out.c_str());
  }
  return 0;
}
'''


def cpp_literal(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def check_behavior(source: str, errors: list[str]) -> None:
    try:
        body = extract_function_body(source, HTML_ESCAPE_SIGNATURE)
    except ValueError as exc:
        errors.append(f"WebServer.ino: не найдено тело html_escape(): {exc}")
        return

    payloads_literal = ", ".join(cpp_literal(v) for v in (VALUE_A, VALUE_B))
    cpp_source = HARNESS_TEMPLATE.replace(
        "{BODY}", f"String html_escape(const String &s) {{{body}}}"
    ).replace("{PAYLOADS}", payloads_literal)

    with tempfile.TemporaryDirectory() as tmp:
        src_path = Path(tmp) / "harness.cpp"
        bin_path = Path(tmp) / "harness"
        src_path.write_text(cpp_source, encoding="utf-8")
        compile_result = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
             str(src_path), "-o", str(bin_path)],
            capture_output=True, text=True,
        )
        if compile_result.returncode != 0:
            errors.append(
                "html_escape harness: ошибка компиляции:\n" + compile_result.stderr
            )
            return
        run_result = subprocess.run([str(bin_path)], capture_output=True, text=True)
        if run_result.returncode != 0:
            errors.append(
                f"html_escape harness: завершился с кодом {run_result.returncode}, "
                f"stderr={run_result.stderr!r}"
            )
            return
        lines = run_result.stdout.splitlines()

    if len(lines) != 2:
        errors.append(
            f"html_escape harness: ожидались 2 строки вывода, получено {len(lines)}: {lines!r}"
        )
        return

    for raw, escaped in zip((VALUE_A, VALUE_B), lines):
        # Опасные байты не должны встречаться в выводе НИГДЕ, кроме как в виде entity.
        entity_free = re.sub(r"&(amp|lt|gt|quot|#39);", "", escaped)
        for bad_char, name in (("<", "<"), (">", ">"), ("'", "'"), ('"', '"')):
            if bad_char in entity_free:
                errors.append(
                    f"html_escape harness: сырой символ {name!r} остался в выводе "
                    f"вне entity для входа {raw!r} -> {escaped!r} - разметку/атрибут "
                    "снова можно разорвать"
                )
        # Обратимость: раскрутив entity назад, должны получить исходную строку -
        # значит символы не потеряны и не искажены, а именно нейтрализованы.
        roundtrip = (
            escaped.replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&quot;", '"')
            .replace("&#39;", "'")
        )
        if roundtrip != raw:
            errors.append(
                f"html_escape harness: раскрутка entity не совпала с исходником: "
                f"{raw!r} -> {escaped!r} -> {roundtrip!r}"
            )
        # '&' обязан экранироваться первым (иначе '&lt;' от '<' задвоится в '&amp;lt;').
        if "&amp;lt;" in escaped or "&amp;amp;" in escaped:
            errors.append(
                f"html_escape harness: похоже на двойное экранирование '&': {escaped!r}"
            )


def main() -> int:
    errors: list[str] = []
    source = WEB_SERVER.read_text(encoding="utf-8")
    check_delegates(source, errors)
    check_behavior(source, errors)
    if errors:
        print("html escape canon smoke failed:")
        for error in errors:
            print(f" - {error}")
        return 1
    print("html escape canon smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
