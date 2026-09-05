#!/usr/bin/env python3
"""Обновление веб-интерфейса: источник правды о версии - СЕРВЕР, а не прошивка.

Здесь был регресс, который стоил возможности обновлять интерфейс без перепрошивки.
Историческое поведение: спросили у web.samovar-tool.ru/<SAMOVAR_VERSION>/version.txt,
сравнили с локальным /version.txt, разошлись - скачали весь список и только потом
переписали маркер. Промежуточная схема вкомпилировала целевую версию в прошивку
(WEB_UPDATE_VERSION) и сверялась с ней же - устройство сходилось к тому, что зашито
в него самого, и новый UI требовал перепрошивки. Отменено владельцем 16.07.2026.

[WP7 п.20] Второй регресс: набор файлов интерфейса сначала кладётся во временные
"*.tmp" (write_web_file_stage) и переставляется на место одной короткой серией
переименований (write_web_file_commit) только если ВЕСЬ набор скачался - иначе
временные файлы подчищаются (discard_web_file_stage), а старый рабочий набор остаётся
нетронутым.

[T20] Третий регресс: двухфазная схема держала на диске старый комплект и новый
во временных "*.tmp" - пик не помещался в раздел. Файлы качаются по одному и
пишутся сразу в конечный путь, тело HTTP сливается во флеш чанками.

Тест пинит СОГЛАСИЕ, а не числа:
  1. версия берётся из сети, а не из константы прошивки;
  2. качаем только когда серверная и локальная разошлись;
  3. набор файлов интерфейса ставится ОДНИМ проходом через updateFile(fn,
     SAVE_FILE_OVERRIDE) (http_sync_download_file внутри get_web_file: тело HTTP
     пишется во флеш чанками, без Arduino String на весь файл), с явным break при
     первой же неудаче - остатки набора не докачиваются вслепую;
  4. двухфазной схемы (stage/commit/discard всего набора разом) в get_web_interface()
     больше нет - на диске никогда не живут одновременно два полных комплекта;
  5. маркер версии пишется последним и только если весь список доехал (в том числе
     набор из kWebOverrideFiles[]);
  6. список качаемого покрывает ровно data/ - иначе новый файл в data_raw/ молча
     не доедет до устройств, а это ровно то, что чинил весь этот механизм;
  7. пользовательские файлы (*.lua, program_*.txt) по-прежнему качаются только если
     их ещё нет на устройстве - иначе обновление затрёт то, что человек правил под себя.
  8. гейт свободного места проверяется до начала закачки набора, а в kWebOverrideFiles[]
     общие ресурсы (картинки/звук/стили/скрипты) идут раньше HTML-страниц - при обрыве
     связи риск нерабочей одной страницы ниже риска нерабочего общего ресурса.
  9. после подтверждённой загрузки каждой из десяти gzip-страниц удаляется только её
     legacy raw-файл; ошибка удаления останавливает обновление до записи версии.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB_SERVER = ROOT / "WebServer.ino"
DATA = ROOT / "data"

LEGACY_RAW_PAGES = (
    "index.htm", "beer.htm", "cheese.htm", "distiller.htm", "bk.htm",
    "nbk.htm", "chart.htm", "program.htm", "calibrate.htm", "calibrate_ph.htm",
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="strict")


def function_body(source: str, signature: str, errors: list[str]) -> str:
    start = source.find(signature)
    if start == -1:
        errors.append(f"WebServer.ino: не найдена {signature}")
        return ""
    depth = 0
    for index in range(source.find("{", start), len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    errors.append(f"WebServer.ino: не закрыта {signature}")
    return ""


def cleanup_harness(cleanup_body: str) -> str:
    return f'''\
#include <cstring>
#include <iostream>
#include <set>
#include <string>

class String {{
 public:
  String() = default;
  String(const char *value) : value_(value) {{}}
  String(const std::string& value) : value_(value) {{}}
  const std::string& value() const {{ return value_; }}
 private:
  std::string value_;
}};

String operator+(const String& lhs, const char *rhs) {{
  return String(lhs.value() + rhs);
}}

String operator+(const char *lhs, const String& rhs) {{
  return String(std::string(lhs) + rhs.value());
}}

struct MockFs {{
  std::set<std::string> files;
  std::set<std::string> removeFailures;
  int removeCalls = 0;

  bool exists(const String& path) const {{ return files.count(path.value()) != 0; }}
  bool remove(const String& path) {{
    removeCalls++;
    if (removeFailures.count(path.value())) return false;
    return files.erase(path.value()) == 1;
  }}
}} SPIFFS;

struct MockSerial {{
  void println(const String&) {{}}
}} Serial;

static bool cleanup_legacy_raw_web_page(const char* downloadedFile) {{
{cleanup_body}
}}

static void expect(bool value, const char *message) {{
  if (!value) {{
    std::cerr << message << "\\n";
    std::exit(1);
  }}
}}

int main() {{
  const char *rawPages[] = {{
    "/index.htm", "/beer.htm", "/cheese.htm", "/distiller.htm", "/bk.htm",
    "/nbk.htm", "/chart.htm", "/program.htm", "/calibrate.htm", "/calibrate_ph.htm"
  }};
  const char *gzipPages[] = {{
    "index.htm.gz", "beer.htm.gz", "cheese.htm.gz", "distiller.htm.gz", "bk.htm.gz",
    "nbk.htm.gz", "chart.htm.gz", "program.htm.gz", "calibrate.htm.gz", "calibrate_ph.htm.gz"
  }};
  SPIFFS.files = {{"/setup.htm"}};
  for (const char *rawPage : rawPages) SPIFFS.files.insert(rawPage);
  for (size_t i = 0; i < 10; i++) {{
    expect(cleanup_legacy_raw_web_page(gzipPages[i]), "legacy cleanup failed");
    expect(!SPIFFS.exists(String(rawPages[i])), "legacy raw survived cleanup");
  }}
  const int callsAfterPages = SPIFFS.removeCalls;
  expect(cleanup_legacy_raw_web_page("setup.htm"), "unrelated file rejected");
  expect(SPIFFS.removeCalls == callsAfterPages, "unrelated file triggered removal");
  expect(SPIFFS.exists(String("/setup.htm")), "unrelated raw file removed");

  expect(cleanup_legacy_raw_web_page("index.htm.gz"), "repeat cleanup rejected absent raw");
  SPIFFS.files.insert("/beer.htm");
  SPIFFS.removeFailures.insert("/beer.htm");
  expect(!cleanup_legacy_raw_web_page("beer.htm.gz"), "remove failure was hidden");
  expect(SPIFFS.exists(String("/beer.htm")), "failed removal changed raw file");
  return 0;
}}
'''


def compile_and_run_cleanup(cleanup_body: str) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="samovar-web-legacy-cleanup-") as tmp:
        source = Path(tmp) / "cleanup.cpp"
        binary = Path(tmp) / "cleanup"
        source.write_text(cleanup_harness(cleanup_body), encoding="utf-8")
        compiled = subprocess.run(
            ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
            text=True,
            capture_output=True,
            check=False,
        )
        if compiled.returncode != 0:
            return compiled.returncode, compiled.stdout + compiled.stderr
        ran = subprocess.run([str(binary)], text=True, capture_output=True, check=False)
        return ran.returncode, ran.stdout + ran.stderr


def validate_cleanup_flow(body: str) -> list[str]:
    errors: list[str] = []
    tokens = (
        "String result = get_web_file(fn, type);",
        "if (result == \"<ERR>\") {",
        "return;",
        "if (type == SAVE_FILE_OVERRIDE && !cleanup_legacy_raw_web_page(fn.c_str())) {",
        "updateFile(kWebOverrideFiles[i], SAVE_FILE_OVERRIDE);",
        "if (!updateOk) break;",
    )
    positions: list[int] = []
    offset = 0
    for token in tokens:
        position = body.find(token, offset)
        positions.append(position)
        if position >= 0:
            offset = position + len(token)
    if any(position < 0 for position in positions):
        errors.append(
            "get_web_interface: legacy raw cleanup must follow its successful gzip "
            "download, propagate removal failure, and precede the loop break"
        )
    cleanup_pos = body.find(
        "if (type == SAVE_FILE_OVERRIDE && !cleanup_legacy_raw_web_page(fn.c_str())) {"
    )
    cleanup_end = body.find("}", cleanup_pos)
    if cleanup_pos < 0 or "updateOk = false;" not in body[cleanup_pos:cleanup_end]:
        errors.append(
            "get_web_interface: legacy raw removal failure must set updateOk=false"
        )
    marker = body.find('write_web_file("/version.txt"')
    if marker < 0 or (positions[-1] >= 0 and marker < positions[-1]):
        errors.append(
            "get_web_interface: version marker can be written before legacy raw cleanup succeeds"
        )
    return errors


def main() -> int:
    errors: list[str] = []
    web = read(WEB_SERVER)
    body = function_body(web, "void get_web_interface()", errors)
    if not body:
        for error in errors:
            print(f" - {error}")
        return 1

    cleanup = function_body(
        web, "static bool cleanup_legacy_raw_web_page(const char* downloadedFile)", errors
    )
    if cleanup:
        cleanup_names = {
            raw for _, raw in re.findall(
                r'\{"([^"]+\.htm\.gz)",\s*"([^"]+\.htm)"\}', cleanup
            )
        }
        if cleanup_names != set(LEGACY_RAW_PAGES):
            errors.append(
                "cleanup_legacy_raw_web_page: mapping must cover exactly the ten legacy raw pages"
            )
        cleanup_open = cleanup.find("SPIFFS.exists(rawPath)")
        cleanup_remove = cleanup.find("SPIFFS.remove(rawPath)")
        if cleanup_open < 0 or cleanup_remove < cleanup_open:
            errors.append(
                "cleanup_legacy_raw_web_page: absent raw page must be accepted before remove()"
            )
        cleanup_signature_end = cleanup.find("{")
        cleanup_body = cleanup[cleanup_signature_end + 1:-1]
        cleanup_rc, cleanup_output = compile_and_run_cleanup(cleanup_body)
        if cleanup_rc != 0:
            errors.append(
                "cleanup_legacy_raw_web_page: source-derived behavior failed:\n" + cleanup_output
            )
        cleanup_mutants = (
            (
                "if (!SPIFFS.exists(rawPath)) return true;",
                "if (!SPIFFS.exists(rawPath)) return false;",
                "absent-raw-repeat",
            ),
            (
                "Serial.println(\"WEB interface cleanup failed: \" + rawPath);\n"
                "      return false;",
                "Serial.println(\"WEB interface cleanup failed: \" + rawPath);\n"
                "      return true;",
                "remove-failure-hidden",
            ),
        )
        for old, new, label in cleanup_mutants:
            if cleanup_body.count(old) != 1:
                errors.append(f"cleanup_legacy_raw_web_page: mutation anchor missing: {label}")
                continue
            mutant_rc, _ = compile_and_run_cleanup(cleanup_body.replace(old, new, 1))
            if mutant_rc == 0:
                errors.append(f"cleanup_legacy_raw_web_page: mutation survived: {label}")

    errors.extend(validate_cleanup_flow(body))

    cleanup_flow_mutants = (
        (
            "if (type == SAVE_FILE_OVERRIDE && !cleanup_legacy_raw_web_page(fn.c_str())) {",
            "if (false && !cleanup_legacy_raw_web_page(fn.c_str())) {",
            "cleanup-disabled",
        ),
        (
            "updateOk = false;\n        return;\n      }\n"
            "      if (type == SAVE_FILE_OVERRIDE",
            "updateOk = false;\n      }\n"
            "      if (type == SAVE_FILE_OVERRIDE",
            "cleanup-after-download-failure",
        ),
    )
    for old, new, label in cleanup_flow_mutants:
        if body.count(old) != 1:
            errors.append(f"get_web_interface: mutation anchor missing: {label}")
            continue
        mutant = body.replace(old, new, 1)
        if not validate_cleanup_flow(mutant):
            errors.append(f"get_web_interface: cleanup mutation survived: {label}")

    # --- 1. версия приходит из сети ------------------------------------------
    # Самый важный пин файла. Если версия снова станет вкомпилированной константой,
    # устройства перестанут получать новый интерфейс без перепрошивки - и заметить
    # это можно будет только по жалобам пользователей.
    if 'get_web_file("version.txt", GET_CONTENT)' not in body:
        errors.append(
            "get_web_interface: версия не запрашивается у сервера через "
            'get_web_file("version.txt", GET_CONTENT) - интерфейс перестанет '
            "обновляться без перепрошивки"
        )
    for compiled_source in ("WEB_UPDATE_VERSION", "WEB_UPDATE_ENTRIES"):
        if compiled_source in web:
            errors.append(
                f"WebServer.ino: {compiled_source} - целевая версия/список снова "
                "вкомпилированы в прошивку, сервер перестал быть источником правды"
            )

    # --- 2. качаем только при расхождении ------------------------------------
    if "if (version != local_version)" not in body:
        errors.append(
            "get_web_interface: пропало сравнение серверной и локальной версий - "
            "устройство будет перекачивать весь список на каждой загрузке"
        )

    # --- 3/4. набор файлов интерфейса ставится ОДНИМ проходом через SAVE_FILE_OVERRIDE,
    #          двухфазной схемы (stage весь набор / commit весь набор / discard) нет ---
    override_loop = re.search(
        r"for\s*\([^)]*\)\s*\{[^}]*updateFile\([^)]*SAVE_FILE_OVERRIDE\)[^}]*\}",
        body,
    )
    if not override_loop:
        errors.append(
            "get_web_interface: набор файлов интерфейса больше не ставится одним "
            "циклом через updateFile(fn, SAVE_FILE_OVERRIDE) - см. kWebOverrideFiles[]"
        )
    elif "if (!updateOk) break;" not in override_loop.group(0):
        errors.append(
            "get_web_interface: цикл по kWebOverrideFiles[] не прерывается по "
            "!updateOk (break) - неудачная закачка одного файла не остановит попытки "
            "качать остальные"
        )
    for removed_call in (
        "write_web_file_stage(",
        "write_web_file_commit(",
        "discard_web_file_stage(",
    ):
        if removed_call in body:
            errors.append(
                f"get_web_interface: остался вызов {removed_call} - вернулась "
                "двухфазная схема (весь набор во временные файлы, потом коммит "
                "разом), пик места для неё (942080 байт) не помещается в раздел "
                "spiffs (786432 байта)"
            )

    # --- 5. маркер пишется последним и только при полном успехе ---------------
    marker = body.find('write_web_file("/version.txt"')
    last_download = body.rfind("updateFile(")
    override_pos = override_loop.start() if override_loop else -1
    if marker == -1:
        errors.append("get_web_interface: маркер версии не записывается")
    else:
        if last_download != -1 and marker < last_download:
            errors.append(
                "get_web_interface: маркер версии пишется до конца закачки "
                "пользовательских файлов - оборвавшееся обновление притворится "
                "успешным и не повторится"
            )
        if override_pos != -1 and marker < override_pos:
            errors.append(
                "get_web_interface: маркер версии пишется до установки набора "
                "файлов интерфейса (kWebOverrideFiles) - оборвавшееся обновление "
                "притворится успешным и не повторится"
            )
    if "if (updateOk) {" not in body:
        errors.append(
            "get_web_interface: маркер версии пишется без проверки updateOk - "
            "частично скачанный набор закрепится как актуальный"
        )

    # --- 6. список покрывает ровно data/ --------------------------------------
    # Единственная защита от «положили файл в data_raw/ и забыли про апдейтер».
    # Раньше это были только updateFile("name", TYPE) - теперь принудительно
    # обновляемые файлы (SAVE_FILE_OVERRIDE) перечислены в kWebOverrideFiles[],
    # а updateFile(..., SAVE_FILE_IF_NOT_EXIST) остался для пользовательских файлов.
    override_array = re.search(
        r"kWebOverrideFiles\[\]\s*=\s*\{(?P<items>.*?)\};", body, re.S
    )
    if not override_array:
        errors.append(
            "get_web_interface: не найден список kWebOverrideFiles[] - нечем "
            "проверить полноту закачиваемого набора"
        )
        override_names: list[str] = []
    else:
        override_names = re.findall(r'"([^"]+)"', override_array.group("items"))

    required_gzip_pages = (
        "index.htm.gz", "beer.htm.gz", "cheese.htm.gz", "distiller.htm.gz",
        "bk.htm.gz", "nbk.htm.gz", "chart.htm.gz", "program.htm.gz",
        "calibrate.htm.gz", "calibrate_ph.htm.gz",
    )
    for name in required_gzip_pages:
        if name not in override_names:
            errors.append(
                f"get_web_interface: {name} не входит в SAVE_FILE_OVERRIDE набор"
            )
    for name in ("index.htm", "beer.htm", "cheese.htm", "distiller.htm", "bk.htm",
                 "nbk.htm", "chart.htm", "program.htm", "calibrate.htm", "calibrate_ph.htm"):
        if name in override_names:
            errors.append(
                f"get_web_interface: {name} должен обновляться только как gzip"
            )
    if "setup.htm" not in override_names or "setup.htm.gz" in override_names:
        errors.append("get_web_interface: setup.htm должен остаться несжатым шаблоном")

    if_not_exist_entries = dict(
        re.findall(r'updateFile\("([^"]+)",\s*(SAVE_FILE_IF_NOT_EXIST)\)', body)
    )
    override_only = dict(
        re.findall(r'updateFile\("([^"]+)",\s*(SAVE_FILE_OVERRIDE)\)', body)
    )
    if override_only:
        errors.append(
            "get_web_interface: остались updateFile(..., SAVE_FILE_OVERRIDE) "
            f"вызовы ({sorted(override_only)}) - список принудительно "
            "обновляемых файлов должен жить в одном месте (kWebOverrideFiles[])"
        )

    listed = set(override_names) | set(if_not_exist_entries)
    on_disk = {path.name for path in DATA.iterdir() if path.is_file()}
    # version.txt - это маркер, его пишет сам апдейтер, а не качает списком.
    on_disk.discard("version.txt")
    for missing in sorted(on_disk - listed):
        errors.append(
            f"get_web_interface: data/{missing} не качается - на устройствах "
            "его не будет"
        )
    for stale in sorted(listed - on_disk):
        errors.append(
            f"get_web_interface: качается {stale}, которого нет в data/ - "
            "закачка отвалится по <ERR> и заблокирует всё обновление"
        )

    # --- 7. тип закачки соответствует смыслу файла ----------------------------
    # Lua-сценарии и program_*.txt пользователь правит под себя - затирать их
    # обновлением нельзя, поэтому SAVE_FILE_IF_NOT_EXIST, а не безусловный набор
    # kWebOverrideFiles[]. Всё остальное - наш UI, он обязан ехать принудительно.
    for name in override_names:
        user_editable = name.endswith(".lua") or name.startswith("program_")
        if user_editable:
            errors.append(
                f"get_web_interface: {name} принудительно затирается "
                "(kWebOverrideFiles) - обновление сотрёт пользовательский сценарий"
            )
    for name, kind in sorted(if_not_exist_entries.items()):
        user_editable = name.endswith(".lua") or name.startswith("program_")
        if not user_editable:
            errors.append(
                f"get_web_interface: {name} качается как {kind}, но не является "
                "пользовательским файлом (*.lua/program_*) - файл молча "
                "перестанет обновляться, а маркер версии всё равно запишется "
                "как успех"
            )

    # --- 8. гейт свободного места стоит раньше закачки, ресурсы - раньше страниц ---
    margin_pos = body.find("WEB_UPDATE_FREE_SPACE_MARGIN_BYTES")
    if margin_pos == -1:
        errors.append(
            "get_web_interface: нет гейта свободного места "
            "(WEB_UPDATE_FREE_SPACE_MARGIN_BYTES) - обновление на почти полном "
            "диске начнёт качать файлы, которым физически некуда встать"
        )
    elif override_loop and margin_pos > override_loop.start():
        errors.append(
            "get_web_interface: гейт свободного места проверяется после начала "
            "закачки набора файлов интерфейса - место может кончиться уже "
            "во время обновления"
        )

    RESOURCE_NAMES = [
        "Green.png", "Red_light.gif", "alarm.mp3", "favicon.ico",
        "minus.png", "plus.png", "style.css.gz", "app.js.gz", "chart.js.gz",
    ]
    PAGE_NAMES = [
        "index.htm.gz", "beer.htm.gz", "cheese.htm.gz", "distiller.htm.gz",
        "bk.htm.gz", "nbk.htm.gz", "chart.htm.gz", "program.htm.gz",
        "calibrate.htm.gz", "calibrate_ph.htm.gz", "brewxml.htm.gz",
        "i2cstepper.htm.gz", "edit.htm.gz", "setup.htm",
    ]
    resource_positions = [override_names.index(n) for n in RESOURCE_NAMES if n in override_names]
    page_positions = [override_names.index(n) for n in PAGE_NAMES if n in override_names]
    if resource_positions and page_positions and max(resource_positions) > min(page_positions):
        errors.append(
            "get_web_interface: в kWebOverrideFiles[] общий ресурс идёт после "
            "HTML-страницы - при обрыве связи риск нерабочей одной страницы должен "
            "быть ниже риска нерабочего общего ресурса, от которого зависят все "
            "страницы разом"
        )

    get_file = function_body(web, "String get_web_file(String fn, get_web_type type)", errors)
    if get_file:
        if "http_sync_download_file(" not in get_file:
            errors.append(
                "get_web_file: SAVE-файлы снова идут через http_sync_request_get()/String - "
                "index.htm (~51 КБ) не копируется в непрерывный String при живом xbuf "
                "и обновление обрывается с incomplete: 0/Content-Length"
            )
        if "responseText(" in get_file:
            errors.append(
                "get_web_file: responseText() вернул загрузку файлов интерфейса в String"
            )

    download = function_body(web, "static bool http_sync_download_file(const String& url, const String& path)", errors)
    if download:
        if "&wf" not in download or "http_sync_request_connect_and_send" not in download:
            errors.append(
                "http_sync_download_file: тело не сливается во файл во время HTTP"
            )
        if "responseText(" in download:
            errors.append(
                "http_sync_download_file: responseText() снова держит весь файл в String"
            )
        if "commit_web_file_tmp(" in download or ".tmp" in download:
            errors.append(
                "http_sync_download_file: снова пишет через .tmp/rename"
            )
        if "FILE_WRITE" not in download and '"w"' not in download:
            errors.append(
                "http_sync_download_file: не открывает целевой путь на запись"
            )

    drain = function_body(
        web,
        "static bool drain_http_body_to_file(asyncHTTPrequest& request, File& wf, size_t& total)",
        errors,
    )
    if drain and "responseRead(" not in drain:
        errors.append(
            "drain_http_body_to_file: нет responseRead() - тело должно стекаться "
            "во флеш чанками, не через responseText()"
        )

    if errors:
        print("web interface update smoke failed:")
        for error in errors:
            print(f" - {error}")
        return 1
    print(
        f"web interface update smoke passed "
        f"({len(listed)} files, server-driven version)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
