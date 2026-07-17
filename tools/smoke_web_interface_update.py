#!/usr/bin/env python3
"""Обновление веб-интерфейса: источник правды о версии - СЕРВЕР, а не прошивка.

Здесь был регресс, который стоил возможности обновлять интерфейс без перепрошивки.
Историческое поведение: спросили у web.samovar-tool.ru/<SAMOVAR_VERSION>/version.txt,
сравнили с локальным /version.txt, разошлись - скачали весь список и только потом
переписали маркер. Промежуточная схема вкомпилировала целевую версию в прошивку
(WEB_UPDATE_VERSION) и сверялась с ней же - устройство сходилось к тому, что зашито
в него самого, и новый UI требовал перепрошивки. Отменено владельцем 16.07.2026.

Тест пинит СОГЛАСИЕ, а не числа:
  1. версия берётся из сети, а не из константы прошивки;
  2. качаем только когда серверная и локальная разошлись;
  3. маркер версии пишется последним и только если весь список доехал;
  4. список качаемого покрывает ровно data/ - иначе новый файл в data_raw/ молча
     не доедет до устройств, а это ровно то, что чинил весь этот механизм.
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

    # --- 3. маркер пишется последним и только при полном успехе ---------------
    marker = body.find('write_web_file_atomic("/version.txt"')
    last_download = body.rfind("updateFile(")
    if marker == -1:
        errors.append("get_web_interface: маркер версии не записывается")
    elif last_download != -1 and marker < last_download:
        errors.append(
            "get_web_interface: маркер версии пишется до конца закачки - оборвавшееся "
            "обновление притворится успешным и не повторится"
        )
    if "if (updateOk) {" not in body:
        errors.append(
            "get_web_interface: маркер версии пишется без проверки updateOk - "
            "частично скачанный набор закрепится как актуальный"
        )

    # --- 4. список покрывает ровно data/ --------------------------------------
    # Единственная защита от «положили файл в data_raw/ и забыли про апдейтер».
    entries = dict(re.findall(r'updateFile\("([^"]+)",\s*(\w+)\)', body))
    listed = set(entries)
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

    # --- 5. тип закачки соответствует смыслу файла ----------------------------
    # Lua-сценарии и program_*.txt пользователь правит под себя - затирать их
    # обновлением нельзя, поэтому SAVE_FILE_IF_NOT_EXIST. Всё остальное - наш UI,
    # он обязан ехать принудительно.
    # Пин обязателен, потому что подмена типа МОЛЧАЛИВАЯ: get_web_file() при
    # SAVE_FILE_IF_NOT_EXIST и существующем файле возвращает "" (не "<ERR>"),
    # updateOk остаётся true, маркер версии пишется как успех - и страница
    # замерзает навсегда при формально зелёном обновлении.
    for name, kind in sorted(entries.items()):
        user_editable = name.endswith(".lua") or name.startswith("program_")
        expected = "SAVE_FILE_IF_NOT_EXIST" if user_editable else "SAVE_FILE_OVERRIDE"
        if kind != expected:
            errors.append(
                f"get_web_interface: {name} качается как {kind}, ожидалось {expected}"
                + (
                    " - обновление затрёт пользовательский сценарий"
                    if user_editable
                    else " - файл молча перестанет обновляться, а маркер версии "
                    "всё равно запишется как успех"
                )
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
