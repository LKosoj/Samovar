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
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB_SERVER = ROOT / "WebServer.ino"
DATA = ROOT / "data"


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


def main() -> int:
    errors: list[str] = []
    web = read(WEB_SERVER)
    body = function_body(web, "void get_web_interface()", errors)
    if not body:
        for error in errors:
            print(f" - {error}")
        return 1

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
        "index.htm", "beer.htm", "bk.htm", "nbk.htm", "brewxml.htm.gz", "calibrate.htm",
        "chart.htm", "distiller.htm", "i2cstepper.htm.gz", "edit.htm.gz",
        "program.htm", "setup.htm",
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
