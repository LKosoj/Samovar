#!/usr/bin/env python3
"""Behavioral check for пункт 19: загрузка файла через встроенный редактор (/edit).

Три подпроблемы, которые чинит правка в SPIFFSEditor.h:
  (а) имя загружаемого файла не проверялось - можно было затереть index.htm или залить
      файл с ".." / вложенным путём / без расширения. Чинит spiffsEditorNameAllowed().
  (б) чанки пишутся сразу в целевой путь (без *.tmp/rename). Неполный upload не
      считается успехом: 200 только если handleUpload дошёл до final и выставил
      SPIFFS_EDITOR_UPLOAD_COMMITTED; иначе файл снимается и клиент получает 500.
  (в) результат write() не проверялся. Чинит явная проверка written != len в
      handleUpload() (проверяется здесь архитектурно, по реальному телу функции).

Тест из двух частей:
  1. Поведенческая: реальное тело spiffsEditorNameAllowed() из SPIFFSEditor.h,
     скомпилированное g++, прогнанное на РЕАЛЬНЫХ именах файлов из data_raw/ (все
     обязаны пройти) и на заведомо посторонних/опасных именах (все обязаны быть
     отклонены).
  2. Архитектурная: в реальном теле handleUpload() есть проверка written != len
     ДО закрытия файла, имя проверяется ДО открытия файла на запись, открывается
     целевой путь, нет .tmp/rename.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_helpers import extract_function_body, strip_cpp_comments, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]
DATA_RAW = ROOT / "data_raw"
# data/ - то, что реально прошивается на устройство: tools/build_web_assets.py
# заменяет часть файлов из data_raw/ сжатыми *.gz (app.js.gz, chart.js.gz,
# edit.htm.gz, i2cstepper.htm.gz, brewxml.htm.gz, style.css.gz). Проверяем оба каталога, чтобы тест
# ловил регрессии и в именах исходников, и в именах, которые реально лежат на приборе.
DATA_DIR = ROOT / "data"

NAME_ALLOWED_SIGNATURE = "static bool spiffsEditorNameAllowed(const String &path)"
HANDLE_UPLOAD_SIGNATURE = (
    "void SPIFFSEditor::handleUpload(AsyncWebServerRequest *request, "
    "const String& filename, size_t index, uint8_t *data, size_t len, bool final)"
)

errors: list[str] = []


def real_data_raw_names() -> list[str]:
    names = set()
    for directory in (DATA_RAW, DATA_DIR):
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                names.add("/" + path.name)
    assert names, "data_raw/ и data/ пусты - фикстура сломана"
    assert any(name.endswith(".gz") for name in names), (
        "среди реальных имён нет .gz - фикстура больше не отражает состав data/ "
        "(build_web_assets.py кладёт туда сжатые ассеты интерфейса)"
    )
    return sorted(names)


# ---------- Часть 1: белый список имён ----------

NAME_HARNESS = r'''
#include <cstdio>
#include <cstring>
#include <string>

class String {
 public:
  String() = default;
  String(const char* s) : v(s ? s : "") {}
  size_t length() const { return v.size(); }
  char operator[](size_t i) const { return v[i]; }
  int indexOf(const char* needle) const {
    auto pos = v.find(needle);
    return pos == std::string::npos ? -1 : (int)pos;
  }
  int indexOf(char c, int from) const {
    if (from < 0) from = 0;
    auto pos = v.find(c, (size_t)from);
    return pos == std::string::npos ? -1 : (int)pos;
  }
  int lastIndexOf(char c) const {
    auto pos = v.rfind(c);
    return pos == std::string::npos ? -1 : (int)pos;
  }
  String substring(int from) const { return String(v.substr((size_t)from).c_str()); }
  String substring(int from, int to) const {
    return String(v.substr((size_t)from, (size_t)(to - from)).c_str());
  }
  void toLowerCase() { for (auto& c : v) c = (char)tolower((unsigned char)c); }
  bool operator==(const char* s) const { return v == s; }
  const char* c_str() const { return v.c_str(); }
  std::string v;
};

#define SPIFFS_MAXLENGTH_FILEPATH 32

@EXTRACTED@

static int failures = 0;

static void expectAllowed(const char* name) {
  if (!spiffsEditorNameAllowed(String(name))) {
    fprintf(stderr, "FAIL: реальное имя из data_raw/ отклонено: %s\n", name);
    failures++;
  }
}

static void expectRejected(const char* name, const char* why) {
  if (spiffsEditorNameAllowed(String(name))) {
    fprintf(stderr, "FAIL: должно быть отклонено (%s): %s\n", why, name);
    failures++;
  }
}

int main() {
@REAL_NAME_CHECKS@

  expectRejected("", "пустое имя");
  expectRejected("/noext", "нет расширения");
  expectRejected("/index.htm.", "точка в конце - расширение пустое");
  expectRejected("/../../etc/passwd", "directory traversal");
  expectRejected("/a/../b.lua", "traversal внутри имени");
  expectRejected("/sub/dir/file.lua", "вложенный путь - второй '/'");
  expectRejected("/firmware.bin", "чужое расширение");
  expectRejected("/photo.jpg", "чужое расширение (случайно перетащенное фото)");
  expectRejected("/script.exe", "чужое расширение");
  expectRejected("/this_name_is_way_too_long_for_spiffs_32.lua", "длиннее лимита SPIFFS");

  // Ключевой сценарий из формулировки пункта 19: index.htm - легитимное, штатное имя,
  // редактор обязан разрешать его перезалив (это официальный способ починить устройство).
  expectAllowed("/index.htm");

  if (failures) {
    fprintf(stderr, "%d проверок провалено\n", failures);
    return 1;
  }
  printf("spiffsEditorNameAllowed: все проверки прошли\n");
  return 0;
}
'''


def run_name_allowed_test() -> None:
    editor_source = (ROOT / "SPIFFSEditor.h").read_text(encoding="utf-8")
    try:
        body = extract_function_body(editor_source, NAME_ALLOWED_SIGNATURE)
    except ValueError as exc:
        errors.append(f"spiffsEditorNameAllowed: {exc}")
        return
    extracted = f"static bool spiffsEditorNameAllowed(const String &path) {{\n{body}\n}}"

    checks = "\n".join(f'  expectAllowed("{name}");' for name in real_data_raw_names())

    source = NAME_HARNESS.replace("@EXTRACTED@", extracted).replace(
        "@REAL_NAME_CHECKS@", checks
    )
    _compile_and_run(source, "spiffsEditorNameAllowed")


# ---------- Архитектурная проверка проводки внутри handleUpload() ----------

def run_wiring_check() -> None:
    editor_source = strip_cpp_comments((ROOT / "SPIFFSEditor.h").read_text(encoding="utf-8"))
    try:
        body = extract_function_body(editor_source, HANDLE_UPLOAD_SIGNATURE)
    except ValueError as exc:
        errors.append(f"handleUpload: {exc}")
        return

    require_ordered_tokens(
        "handleUpload: имя проверяется до открытия файла на запись",
        body,
        [
            "if (!spiffsEditorNameAllowed(p)) {",
            "SPIFFS_EDITOR_UPLOAD_BAD_NAME",
            'log_file_lock(0)',
            '_fs.open(p, index ? "a" : "w")',
        ],
        errors,
    )
    require_ordered_tokens(
        "handleUpload: отказ open() фиксируется причиной, а не молчанием",
        body,
        [
            '_fs.open(p, index ? "a" : "w")',
            "if (!wf) {",
            "SPIFFS_EDITOR_UPLOAD_WRITE_FAILED",
        ],
        errors,
    )
    require_ordered_tokens(
        "handleUpload: результат write() проверяется прежде, чем файл закрывается",
        body,
        [
            "size_t written = wf.write(data, len);",
            "if (written != len) {",
            "SPIFFS_EDITOR_UPLOAD_WRITE_FAILED",
        ],
        errors,
    )
    require_ordered_tokens(
        "handleUpload: успех только после final-чанка, замок отпущен до Lua",
        body,
        [
            "wf.close();",
            "log_file_unlock(true);",
            "if (final) {",
            "SPIFFS_EDITOR_UPLOAD_COMMITTED",
        ],
        errors,
    )
    if "tmpPath" in body or ".tmp" in body or "spiffsEditorFinalizeUpload" in body:
        errors.append("handleUpload: снова пишет через .tmp/rename")
    if "samovar_process_active()" in body:
        errors.append("handleUpload: снова гейт по флагу процесса вместо xLogFileSemaphore")


# ---------- служебное ----------

def _compile_and_run(source: str, label: str, run_in_own_tmpdir: bool = False) -> None:
    with tempfile.TemporaryDirectory(prefix="samovar-spiffs-editor-") as tmpdir:
        cpp_path = Path(tmpdir) / "harness.cpp"
        cpp_path.write_text(source, encoding="utf-8")
        binary_path = Path(tmpdir) / "harness"
        compiled = subprocess.run(
            ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
             str(cpp_path), "-o", str(binary_path)],
            capture_output=True, text=True,
        )
        if compiled.returncode != 0:
            errors.append(f"{label}: харнесс не компилируется:\n{compiled.stderr}")
            return
        run = subprocess.run([str(binary_path)], capture_output=True, text=True, cwd=tmpdir)
        if run.returncode != 0:
            errors.append(f"{label}: {run.stdout}{run.stderr}")


def main() -> int:
    run_name_allowed_test()
    run_wiring_check()

    if errors:
        print("SPIFFSEditor upload safety smoke failed:")
        for error in errors:
            print(f" - {error}")
        return 1
    print("SPIFFSEditor upload safety smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
