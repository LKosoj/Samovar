#!/usr/bin/env python3
"""Обновление веб-интерфейса: источник правды о версии - СЕРВЕР, а не прошивка.

Здесь был регресс, который стоил возможности обновлять интерфейс без перепрошивки.
Историческое поведение: спросили у web.samovar-tool.ru/<SAMOVAR_VERSION>/version.txt,
сравнили с локальным /version.txt, разошлись - скачали весь список и только потом
переписали маркер. Промежуточная схема вкомпилировала целевую версию в прошивку
(WEB_UPDATE_VERSION) и сверялась с ней же - устройство сходилось к тому, что зашито
в него самого, и новый UI требовал перепрошивки. Отменено владельцем 16.07.2026.

[WP7 п.20] Второй регресс, который чинит этот файл сейчас: набор файлов интерфейса
кладётся во временные "*.tmp" (write_web_file_stage) и переставляется на место одной
короткой серией переименований (write_web_file_commit) только если ВЕСЬ набор
скачался - иначе временные файлы подчищаются (discard_web_file_stage), а старый
рабочий набор остаётся нетронутым. Раньше каждый файл менялся на месте сразу же:
обрыв связи на середине оставлял новую index.htm со старым app.js.gz - сочетание
файлов на диске становилось нерабочим, а раз маркер версии не переписывался, это
повторялось на каждой следующей перезагрузке.

Тест пинит СОГЛАСИЕ, а не числа:
  1. версия берётся из сети, а не из константы прошивки;
  2. качаем только когда серверная и локальная разошлись;
  3. набор файлов интерфейса сначала весь ставится в очередь (stage), и только потом
     ставится на место (commit) одним проходом - ни один файл не подменяется раньше,
     чем скачан весь набор;
  4. при неполной закачке временные файлы подчищаются (discard), а установка (commit)
     не выполняется вовсе;
  5. маркер версии пишется последним и только если весь список доехал;
  6. список качаемого покрывает ровно data/ - иначе новый файл в data_raw/ молча
     не доедет до устройств, а это ровно то, что чинил весь этот механизм;
  7. пользовательские файлы (*.lua, program_*.txt) по-прежнему качаются только если
     их ещё нет на устройстве - иначе обновление затрёт то, что человек правил под себя.
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

    # --- 3/4. набор файлов интерфейса: сначала stage всего набора, потом единый commit,
    #          при неполном stage - discard без commit -------------------------------
    stage_loop = re.search(
        r"for\s*\([^)]*\)\s*\{[^}]*write_web_file_stage\(", body
    )
    commit_loop = re.search(
        r"if\s*\(updateOk\)\s*\{\s*for\s*\([^)]*\)\s*\{[^}]*write_web_file_commit\(",
        body,
    )
    discard_block = re.search(
        r"else\s*\{[^}]*for\s*\([^)]*\)\s*\{[^}]*discard_web_file_stage\(", body
    )
    if not stage_loop:
        errors.append(
            "get_web_interface: набор файлов интерфейса больше не скачивается во "
            "временные имена (write_web_file_stage) - файлы снова подменяются на "
            "месте по одному, обрыв связи оставит несовместимую смесь старых и новых"
        )
    if not commit_loop:
        errors.append(
            "get_web_interface: установка набора (write_web_file_commit) не "
            "выполняется единым проходом под if (updateOk) - частично скачанный "
            "набор может частично же и установиться"
        )
    elif stage_loop and commit_loop.start() < stage_loop.start():
        errors.append(
            "get_web_interface: commit идёт раньше stage - часть файлов встанет "
            "на место раньше, чем весь набор подтвердит успешную закачку"
        )
    if not discard_block:
        errors.append(
            "get_web_interface: при неполной закачке набора временные "
            "*.tmp-файлы (discard_web_file_stage) не подчищаются - мусор "
            "останется на SPIFFS, где и так мало места"
        )

    # --- 5. маркер пишется последним и только при полном успехе ---------------
    marker = body.find('write_web_file_atomic("/version.txt"')
    last_download = body.rfind("updateFile(")
    commit_pos = commit_loop.start() if commit_loop else -1
    if marker == -1:
        errors.append("get_web_interface: маркер версии не записывается")
    else:
        if last_download != -1 and marker < last_download:
            errors.append(
                "get_web_interface: маркер версии пишется до конца закачки "
                "пользовательских файлов - оборвавшееся обновление притворится "
                "успешным и не повторится"
            )
        if commit_pos != -1 and marker < commit_pos:
            errors.append(
                "get_web_interface: маркер версии пишется до установки набора "
                "файлов интерфейса - оборвавшееся обновление притворится "
                "успешным и не повторится"
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
