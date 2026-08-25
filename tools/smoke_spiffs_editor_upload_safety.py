#!/usr/bin/env python3
"""Behavioral check for пункт 19: загрузка файла через встроенный редактор (/edit).

Три подпроблемы, которые чинит правка в SPIFFSEditor.h:
  (а) имя загружаемого файла не проверялось - можно было затереть index.htm или залить
      файл с ".." / вложенным путём / без расширения. Чинит spiffsEditorNameAllowed().
  (б) данные писались сразу в целевой файл - обрыв на середине уничтожал рабочий файл.
      Чинит запись во "<path>.tmp" и spiffsEditorFinalizeUpload() (rename поверх
      целевого, тот же приём, что write_web_file_atomic() в WebServer.ino:2789).
  (в) результат write() не проверялся. Чинит явная проверка written != len в
      handleUpload() (проверяется здесь архитектурно, по реальному телу функции).

Тест из трёх частей:
  1. Поведенческая: реальное тело spiffsEditorNameAllowed() из SPIFFSEditor.h,
     скомпилированное g++, прогнанное на РЕАЛЬНЫХ именах файлов из data_raw/ (все
     обязаны пройти) и на заведомо посторонних/опасных именах (все обязаны быть
     отклонены).
  2. Поведенческая: реальное тело spiffsEditorFinalizeUpload() поверх мока fs::FS,
     который в самом деле пишет/переименовывает файлы во временном каталоге на диске -
     проверяет и штатную публикацию, и то, что при отказе финального rename() старый
     рабочий файл остаётся НЕТРОНУТЫМ (это и есть защита от "обрыв убил рабочий файл").
  3. Архитектурная: в реальном теле handleUpload() есть проверка written != len
     ДО закрытия/финализации файла, и имя проверяется ДО открытия файла на запись -
     ловит будущую правку, которая тихо уберёт одну из трёх проверок.
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
# edit.htm.gz, i2cstepper.htm.gz, style.css.gz). Проверяем оба каталога, чтобы тест
# ловил регрессии и в именах исходников, и в именах, которые реально лежат на приборе.
DATA_DIR = ROOT / "data"

NAME_ALLOWED_SIGNATURE = "static bool spiffsEditorNameAllowed(const String &path)"
FINALIZE_SIGNATURE = (
    "static bool spiffsEditorFinalizeUpload(fs::FS &fs, const String &tmpPath, "
    "const String &finalPath)"
)
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


# ---------- Часть 2: атомарная публикация файла ----------

FINALIZE_HARNESS = r'''
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <sstream>
#include <string>

class String {
 public:
  String() = default;
  String(const char* s) : v(s ? s : "") {}
  String(const std::string& s) : v(s) {}
  String operator+(const char* s) const { return String(v + s); }
  const char* c_str() const { return v.c_str(); }
  std::string v;
};

// Мок fs::FS, который в самом деле читает/пишет/переименовывает файлы в реальном
// временном каталоге (CWD процесса) - никакой фальсификации поведения ФС, только
// возможность заставить ВТОРОЙ rename() (tmp -> finalPath) отказать, чтобы проверить
// путь отката.
namespace fs {
class FS {
 public:
  bool force_second_rename_fail = false;
  int rename_calls = 0;

  bool exists(const String& p) const {
    std::ifstream f(p.c_str());
    return f.good();
  }
  bool remove(const String& p) { return ::remove(p.c_str()) == 0; }
  bool rename(const String& from, const String& to) {
    rename_calls++;
    if (force_second_rename_fail && rename_calls == 2) return false;
    return ::rename(from.c_str(), to.c_str()) == 0;
  }
};
}

@EXTRACTED@

static int failures = 0;

static void writeFile(const char* path, const char* content) {
  std::ofstream f(path);
  f << content;
}

static std::string readFile(const char* path) {
  std::ifstream f(path);
  if (!f.good()) return "<absent>";
  std::ostringstream ss;
  ss << f.rdbuf();
  return ss.str();
}

static void expectEq(const std::string& actual, const std::string& expected, const char* what) {
  if (actual != expected) {
    fprintf(stderr, "FAIL: %s - ожидали '%s', получили '%s'\n",
            what, expected.c_str(), actual.c_str());
    failures++;
  }
}

int main() {
  // 1) Публикация нового файла (finalPath ещё не существует).
  {
    ::remove("new.lua.tmp"); ::remove("new.lua"); ::remove("new.lua.bak");
    writeFile("new.lua.tmp", "NEW CONTENT");
    fs::FS storage;
    bool ok = spiffsEditorFinalizeUpload(storage, String("new.lua.tmp"), String("new.lua"));
    if (!ok) { fprintf(stderr, "FAIL: публикация нового файла вернула false\n"); failures++; }
    expectEq(readFile("new.lua"), "NEW CONTENT", "новый файл опубликован");
    expectEq(readFile("new.lua.tmp"), "<absent>", "временный файл убран после публикации");
  }

  // 2) Перезапись существующего файла - штатный сценарий (пользователь заливает новую
  //    версию скрипта поверх старой).
  {
    ::remove("existing.lua.tmp"); ::remove("existing.lua"); ::remove("existing.lua.bak");
    writeFile("existing.lua", "OLD CONTENT");
    writeFile("existing.lua.tmp", "NEW CONTENT");
    fs::FS storage;
    bool ok = spiffsEditorFinalizeUpload(storage, String("existing.lua.tmp"), String("existing.lua"));
    if (!ok) { fprintf(stderr, "FAIL: перезапись существующего файла вернула false\n"); failures++; }
    expectEq(readFile("existing.lua"), "NEW CONTENT", "существующий файл заменён новым содержимым");
    expectEq(readFile("existing.lua.bak"), "<absent>", "резервная копия убрана после успеха");
  }

  // 3) Отказ финального rename() (диск разъединился/не хватило места между двумя
  //    rename()) - РАБОЧИЙ ФАЙЛ ДОЛЖЕН ОСТАТЬСЯ НЕТРОНУТЫМ. Это ключевая проверка
  //    пункта (б): именно от этого защищает запись через временный файл.
  {
    ::remove("keep.lua.tmp"); ::remove("keep.lua"); ::remove("keep.lua.bak");
    writeFile("keep.lua", "PRECIOUS OLD CONTENT");
    writeFile("keep.lua.tmp", "UPLOAD THAT NEVER LANDS");
    fs::FS storage;
    storage.force_second_rename_fail = true;
    bool ok = spiffsEditorFinalizeUpload(storage, String("keep.lua.tmp"), String("keep.lua"));
    if (ok) { fprintf(stderr, "FAIL: finalize должен был сообщить об отказе\n"); failures++; }
    expectEq(readFile("keep.lua"), "PRECIOUS OLD CONTENT",
             "рабочий файл не тронут при отказе финального rename()");
  }

  if (failures) {
    fprintf(stderr, "%d проверок провалено\n", failures);
    return 1;
  }
  printf("spiffsEditorFinalizeUpload: все проверки прошли\n");
  return 0;
}
'''


def run_finalize_test() -> None:
    editor_source = (ROOT / "SPIFFSEditor.h").read_text(encoding="utf-8")
    try:
        body = extract_function_body(editor_source, FINALIZE_SIGNATURE)
    except ValueError as exc:
        errors.append(f"spiffsEditorFinalizeUpload: {exc}")
        return
    extracted = (
        "static bool spiffsEditorFinalizeUpload(fs::FS &fs, const String &tmpPath, "
        f"const String &finalPath) {{\n{body}\n}}"
    )
    source = FINALIZE_HARNESS.replace("@EXTRACTED@", extracted)
    _compile_and_run(source, "spiffsEditorFinalizeUpload", run_in_own_tmpdir=True)


# ---------- Часть 3: архитектурная проверка проводки внутри handleUpload() ----------

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
            "_tempFile = _fs.open(tmpPath",
        ],
        errors,
    )
    require_ordered_tokens(
        "handleUpload: отказ open() фиксируется причиной, а не молчанием",
        body,
        [
            "_tempFile = _fs.open(tmpPath",
            "if (!request->_tempFile) {",
            "SPIFFS_EDITOR_UPLOAD_WRITE_FAILED",
        ],
        errors,
    )
    require_ordered_tokens(
        "handleUpload: результат write() проверяется прежде, чем файл закрывается",
        body,
        [
            "size_t written = request->_tempFile.write(data, len);",
            "if (written != len) {",
            "SPIFFS_EDITOR_UPLOAD_WRITE_FAILED",
        ],
        errors,
    )
    require_ordered_tokens(
        "handleUpload: финализация через rename, а не прямая запись в целевой файл",
        body,
        [
            "if (final) {",
            "request->_tempFile.close();",
            "spiffsEditorFinalizeUpload(_fs, tmpPath, p)",
            "SPIFFS_EDITOR_UPLOAD_WRITE_FAILED",
        ],
        errors,
    )
    if '_fs.open(p, "w")' in body:
        errors.append("handleUpload: всё ещё открывает целевой файл напрямую (мимо .tmp)")


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
    run_finalize_test()
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
