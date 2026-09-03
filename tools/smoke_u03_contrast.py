#!/usr/bin/env python3
import gzip
import hashlib
import re
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data_raw"
# Сборка: сюда build_web_assets.py кладёт .gz. Содержимое читаем из источника,
# продукты сжатия - отсюда.
BUILD = ROOT / "data"


def read_page(name: str) -> str:
    """Разворачивает <!--#include--> (data_raw/partials/) той же функцией, что
    использует сама сборка - не копией её логики. Импорт лениво (внутри функции):
    build_web_assets.py сам импортирует canonical_gzip из этого модуля, а прямой
    импорт на уровне модуля дал бы цикл."""
    from build_web_assets import resolve_includes
    return resolve_includes(name, (DATA / name).read_bytes()).decode("utf-8")


SENSOR_TOKENS = ("SteamColor", "PipeColor", "WaterColor", "TankColor", "ACPColor")
SENSOR_PAGES = (
    "index.htm", "beer.htm", "distiller.htm", "bk.htm", "nbk.htm",
    "setup.htm", "chart.htm",
)
DELTA_PAGES = ("index.htm", "bk.htm", "chart.htm")
STYLE_TOKEN_ALLOWLIST = (
    "accent", "accent-hover", "bg-page", "text-main", "text-strong",
    "text-on-accent", "text-history-link", "border-input", "border-soft",
    "msg-alarm", "state-danger-bg", "detector-ok-text", "detector-ok-bg",
    "detector-warn-text", "detector-warn-bg", "detector-alarm-text",
    "detector-alarm-bg",
)
NORMALIZED_SHA256 = {
    # 01.09.2026: палитра и размеры вернулись к 6.27 (решение владельца - вид
    # важнее контраста). От HEAD остались только правки раскладки, цветов не
    # касающиеся: высота обёртки графика (легенда наезжала на форму статуса),
    # box-sizing плашек сообщений, перенос шапки таблицы программы, порог nowrap
    # 601->901 px, подсказка полосой у нижнего края на узком экране и отступ
    # формы под верхние кнопки.
    # 01.09.2026 (обход UI на телефоне и компьютере): box-sizing строк и колонок
    # карточек (рамка вылезала за карточку), перенос длинных слов в плашках
    # сообщений и подсказках .dvcs, ширина ячеек шапки программы по тексту на
    # узком экране (подписи наезжали друг на друга) и width: auto/display: block
    # для списка ингредиентов рецепта. Цветов и размеров шрифта не касается:
    # набор цветовых литералов и значений переменных совпадает с HEAD.
    # 01.09.2026 (отложенная косметика): кнопка выбора файла считает ширину по
    # рамке и не берёт боковые отступы в контейнере 200px, у ползунка на телефоне
    # убран боковой отступ браузера, кнопка "Повторить" у графика не прибавляет
    # отступ слева к ширине 100%. Только геометрия: набор цветовых литералов (103)
    # и значений переменных (39) по-прежнему совпадает с HEAD.
    # 01.09.2026 (повторная проверка UI): боковые отступы гасятся у кнопок, которые
    # на телефоне растянуты на всю ширину - инлайновый margin из разметки сдвигал
    # "Начать отбор" (index.htm, i2cstepper.htm) и "Установить" (nbk.htm) из ряда.
    # Частное правило для кнопки "Повторить" убрано как частный случай общего.
    # 01.09.2026 (выравнивание кнопок): обёртки кнопок (.tooltip, .text и блок
    # внутри строки) на телефоне тянутся во всю ширину, чтобы соседние кнопки
    # не выходили разной ширины; добавлен класс .nowrap для диапазона "60-100"
    # в настройках. Только геометрия: набор цветовых литералов (103), значений
    # переменных (39) и размеров шрифта совпадает с HEAD.
    # 01.09.2026 (масштаб графика): .chart-scroll/.chart-scroll-thumb заменены на
    # полосу участка с двумя ручками (.chart-range/-fill/-grip), а touch-action:
    # none снят с холста (пальцем по графику должна прокручиваться страница).
    # Цветовых литералов по-прежнему 103, значений переменных 39, шрифты те же.
    "style.css": "3c16ef9880bee815427252eded8795f7e682339fdb40baa6b96c163bfd6f0673",
    "index.htm": "30ce70e0ba34abb51afa88a192dcb207090a04188a9b6e8f7491bbc66a1e92b4",
    # beer.htm / program.htm / setup.htm 01.09.2026: инлайновая ширина 200px у
    # ячеек с кнопками заменена классом .btn-cell (на телефоне ячейка тянется во
    # всю строку, кнопки выходят одной ширины). Цветов не касается.
    # 02.09.2026 (Пиво C2/C4): кнопка "Пауза" (как index.htm:689, те же
    # переменные --accent/--state-active-bg через SamovarApp.cssVar - новых
    # цветовых литералов нет) и расширенная подсказка про направление мешалки.
    "beer.htm": "a8be4fec71e5b67b0ddc301c681d7f24c8a4e6e743a4ef43fcb0c33b4cf823a8",
    # 02.09.2026: подсказки к колонкам "№ ёмкости" и "Напряжение" программы
    # дистилляции расписаны подробнее (когда применяется значение строки, правило
    # "первая ненулевая строка напряжения - абсолютная величина, а не поправка" с
    # порогами 40 В / 400 Вт для сборки с регулятором в ваттах), подсказка
    # "Значение" получила границы S/R строго между 0 и 1, пример программы заменён
    # на новый (значения в вольтах, о чём теперь сказано явным текстом). Цветов не
    # касается.
    # 02.09.2026 (задача 9c): таблица программы вынесена в общий партиал
    # program_table_dist.htm (4 колонки, PROGRAM_STEAM_COLUMN=false), мёртвый
    # дубль calc_program/removeLine/addLine/getProgram/set_bgcolor удалён из
    # <head>. Разметка и текст не изменились, цветов не касается.
    "distiller.htm": "eaa40d9155dd2762cee914c89b4fbf4c9959d8ae50863fd7ea497a695353d86b",
    # 02.09.2026 (задача A3, п.5): changetxtpwm() читает нижнюю границу текстового
    # поля ШИМ насоса из атрибута min ползунка (PWM_LV), а не хардкодит 0.
    # Цветов не касается.
    # 02.09.2026 (задача 9c): новая вкладка "Программа" (5 колонок через тот же
    # партиал program_table_dist.htm, PROGRAM_STEAM_COLUMN=true) с бейджем
    # "Вода: авто/вручную", кнопкой "Автомат" (.btn-cell) и подсказкой про ШИМ-
    # насос; удалён мёртвый дубль check_program/calc_program/set_program.
    # Цветов не касается.
    # 02.09.2026 (правки ревью 9c): справка про напряжение получила фразу
    # "Значения в примере ниже - в вольтах" (как у distiller.htm), кнопка
    # "Автомат" переоформлена в обёртку .btn-cell вокруг input (как везде в
    # проекте), а не класс на самом input. Цветов не касается.
    "bk.htm": "0c8df0be9ee8303035d95349f033b703af6376850df7c4c26b5a06a8600a9475",
    # 03.09.2026 (НБК, T6): новый спойлер "Как работает автоматика и что влияет
    # на НБК" на вкладке Prog - 7 пунктов, обычный <ul><li>, без новых цветов/inline-стилей.
    # Итоговое ревью 03.09.2026: уточнение текста про автовход по давлению (только после найденного оптимума).
    "nbk.htm": "143f735c0f14e7e2b8d869ece26370ffdcc51ae240a7191efb69747d2af73f23",
    # setup.htm: клиентские нижние границы StepperStepMl (0->1) и PackDens (0->60)
    # изменились - цветов/разметки не касалось (см. tools/smoke_u04_responsive_layout.py
    # STRUCTURE_SHA256 для DOM-структуры).
    # setup.htm дополнительно: подпись ползунка плотности насадки не рвётся
    # переносом ("80 % (60-" / "100)").
    # 02.09.2026 (П11, пакет C): новая подсказка у DistTemp (недостижимый порог
    # на высоте без коррекции давления и без контроля по времени) и дополнение
    # подсказки UseST про дистилляцию. Цветов не касается.
    # 02.09.2026 (задача A3, п.5/6): подпись DistTemp упоминает БК ("Ректификация,
    # дистилляция и БК до температуры в кубе"), подсказка DistTimeF упоминает, что
    # плато завершения действует и для БК. Цветов не касается.
    # 03.09.2026 (НБК, T6): три новые подсказки (.tooltip/.tooltiptext) на вкладке
    # NBK - у "Инерция", "Давление захлёба" и "Т завершения (барда)".
    # Разметка по образцу MaxPressureValue. Цветов не касается.
    # 03.09.2026: в подсказке DistTimeF голый "%" заменён на &#37; - шаблонизатор
    # ESPAsyncWebServer спаривает любые два "%" и молча вырезал кусок текста.
    "setup.htm": "5eb098d1a61ba8e9299eafb6b3c3372668432472f7bd1a44d2d1e88ea02c1e23",
    "chart.htm": "ea21546aff7f36f86abfaf61bfe3b7e50e395ce4d0da44119454e49aa189fd06",
    # program.htm: пин был устаревшим уже на HEAD (унаследованный долг, не наш) -
    # накопилась функциональная правка редактора программ (шаблоны В1-В8: разбор
    # программы прибора, дельты мощности/напряжения, примечание про предзахлёб и
    # т.д.), плюс новый блок colSpeedClampNote, переиспользующий уже проверенный
    # токен --bg-program-example. Новых цветовых литералов diff не содержит.
    # 31.08.2026: правка находки код-ревью В1 - ветка window.onload для программы
    # прибора теперь фиксирует currentProgramTemplateValue/programTemplateLoaded
    # (точка отката СПИСКА шаблонов), это чистый JS без новых цветовых литералов.
    # 31.08.2026 (повторно): правка Б7.4 - проверка "первая строка программы должна
    # быть абсолютной уставкой" теперь пропускается на сборках без регулятора
    # мощности (pwr_unit === "") тем же условием, что и прошивка (#ifdef
    # SAMOVAR_USE_POWER в program_io.h). Только JS-условие и комментарий, новых
    # цветовых литералов нет.
    # 31.08.2026 (в третий раз): фикс регрессии В1 - поле "Процент" обрубалось до
    # целого числа уже на первой прорисовке импортированной программы прибора
    # (set_num() обрубал ЛЮБУЮ незафокусированную строку на каждый пересчёт, а
    # после programmatic-заполнения ни одна строка не в фокусе). Обрубание
    # перенесено на onchange самого поля "Процент" (truncatePercentField(this)) -
    # срабатывает только когда оператор закончил печатать и увёл фокус. Только
    # JS-логика и комментарий, новых цветовых литералов нет.
    # 31.08.2026 (в четвёртый раз): distributionStatus() сравнивал сумму долей
    # со 100 строгим равенством - программа прибора, прочитанная и не тронутая
    # оператором, из-за округления объёма до целого мл почти никогда не даёт
    # сумму ровно 100 и "Записать" отказывала. Проверка "распределено полностью"
    # переведена в те же единицы, что уходят на прибор (целые мл, допуск 0.5
    # мл/строку) - только JS-логика set_num()/distributionStatus(), новых
    # цветовых литералов нет.
    # 31.08.2026 (в пятый раз): комментарий над programPowerAbsThreshold() ссылался
    # на устаревшее расположение константы PROGRAM_POWER_ABS_THRESHOLD
    # (power_regulator.h) - она переехала в program_types.h правкой Б7.1. Только
    # текст комментария, новых цветовых литералов нет.
    # 31.08.2026 (в шестой раз): пересчёт вольт->ватт при загрузке шаблона/файла
    # (programBodyForUnit) на слишком слабом ТЭНе мог молча превратить абсолютную
    # уставку в дельту (isProgramPowerAbsolute после пересчёта - ложь) - добавлена
    # проверка programTemplateWattsStayAbsolute() перед пересчётом; если она не
    # проходит, пересчёт всей программы отменяется (используется уже
    # существующая ветка "готовая 6-я колонка", heaterKnown=false) и показывается
    # SamovarApp.showRequestError(). Тем же приёмом (диагностика, без эталонной
    # колонки) прикрыт formatDualProgramFile(). Плюс в set_num() условие проверки
    # первой строки программы "e.length > 2" исправлено на "e.length > 1" -
    # программа из одной строки тоже должна проверяться (как в прошивке,
    # program_io.h: draft.len > 0). Только JS-логика и комментарии, новых
    # цветовых литералов нет.
    # 31.08.2026 (в седьмой раз): programTemplateWattsStayAbsolute() ловила только
    # одну сторону (абсолют -> дельта на слабом ТЭНе) - зеркальная сторона (дельта
    # -> абсолют на слишком МОЩНОМ ТЭНе, например реальная строка предзахлёба
    # "5;1.1;40;C;3;68" из program_fruit.txt) не проверялась. Функция теперь ведёт
    # lastAbsoluteVolts той же формулой, что и основной цикл programBodyForUnit,
    # и ловит обе стороны; formatDualProgramFile() получил зеркальную проверку
    # (otherUnitGainsAbsolute) тем же приёмом. Текст предупреждения обобщён под
    # обе стороны ("отличается от эталонной" / "не совпадает с оригиналом" вместо
    # одностороннего "слишком слабый"). Только JS-логика и комментарии, новых
    # цветовых литералов нет.
    # 31.08.2026 (в восьмой раз): formatDualProgramFile() - четвёртая ветка (дельта
    # без опоры выше по программе, lastAbsoluteNative === null) не проверяла
    # otherUnitGainsAbsolute, в отличие от трёх соседних. Число копируется в оба
    # столбца сырьём (это поведение не менялось), но теперь та же проверка
    # isProgramPowerAbsolute(power, otherUnit) взведена и здесь - только
    # диагностика/предупреждение, значения столбцов прежние.
    # 01.09.2026: ячейки кнопок переведены на .btn-cell, а высота насадки и
    # оценка времени ("2 ч 54 мин") склеены неразрывными пробелами - на телефоне
    # единица уезжала на следующую строку. Цветов не касается.
    # 02.09.2026: рекомендации мощности - отказ целиком, если ТЭН слабее
    # рекомендованной; пауза с ненулевой мощностью получает мощность
    # предзахлёба; пауза больше 65535 с даёт понятную ошибку. Цветов не касается.
    "program.htm": "20d47974aaa61b5ea6e3c70ac0e9ea72b67878af728550909d691d55d794b515",
    "i2cstepper.htm": "8e0b828032807735a731082df9249487684a8c9d47e95b4819b89d8d64258dcc",
    # 01.09.2026: масштаб графика полностью перешёл на полосу участка с двумя
    # ручками (колёсико, выделение рамкой и двойной щелчок по холсту убраны -
    # они умели только приближать). Палитра рядов не менялась (её отдельно
    # держит verify_chart_palette), исчез лишь цвет заливки рамки выделения.
    "chart.js": "08669ea36ca8a73e7c041b7a5c0149b48286affe144c79787183a9cb7021919c",
}
FROZEN_SHA256 = {
    # 02.09.2026: общая функция beerRowTypeOk (правила типов строк пива) для
    # beer.htm/check_program и brewxml.htm/validateBeerProgramText. Цветов не касается.
    # 02.09.2026 (задача A3, п.5): новый токен COMMAND_TOKENS.PWM_TOO_LOW -
    # текст отказа /command watert при слишком низком ШИМ насоса воды во время
    # нагрева БК. Цветов не касается.
    # 02.09.2026 (задача 9c): три новых токена COMMAND_TOKENS.NOT_RUNNING/
    # NO_SETPOINT/NO_PUMP - отказы /command waterauto=1 (авто-вода БК).
    # Цветов не касается.
    "app.js": "66899ddcfc950f988870921348e80838ef7748a920b5483d36c131db3684765d",
    # 01.09.2026: панель файлов получила мобильную раскладку (до 900 px её
    # кнопки переносились под дерево файлов и не нажимались).
    "edit.htm": "e50cababe8cd7421a250eb9ecfdd9dcdda26ab1d5ea61b5a6ada6aff64e536bb",
    "edit.htm.gz": "0cc91264dd1da80e76faffb7ca2c293cf2777031449f82f9edf99e49c81baa84",
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_gzip(content: bytes) -> bytes:
    compressor = zlib.compressobj(
        level=9, method=zlib.DEFLATED, wbits=-15, memLevel=8,
        strategy=zlib.Z_DEFAULT_STRATEGY,
    )
    deflated = compressor.compress(content) + compressor.flush(zlib.Z_FINISH)
    header = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x02\xff"
    trailer = struct.pack("<II", zlib.crc32(content) & 0xFFFFFFFF, len(content) & 0xFFFFFFFF)
    return header + deflated + trailer


def normalize_style(text: str) -> str:
    for token in STYLE_TOKEN_ALLOWLIST:
        text = re.sub(
            rf"(--{re.escape(token)}\s*:)\s*[^;]+;",
            rf"\1 <U03:{token}>;",
            text,
        )
    text = text.replace(
        ".message_0 { background: var(--msg-alarm); color: white; }",
        "<U03:message-0>",
    )
    text = text.replace(
        ".message_0 { background: var(--state-danger-bg); color: var(--text-on-accent); }",
        "<U03:message-0>",
    )
    text = re.sub(r"^\s+--msg-alarm: <U03:msg-alarm>;\n", "", text, flags=re.MULTILINE)

    def normalize_property(selector: str, property_name: str, marker: str) -> None:
        nonlocal text
        pattern = re.compile(
            rf"({re.escape(selector)}\s*\{{[^}}]*?\n\s*{re.escape(property_name)}\s*:)\s*[^;]+;",
            re.DOTALL,
        )
        text, count = pattern.subn(rf"\1 <U03:{marker}>;", text, count=1)
        if count != 1:
            raise AssertionError(f"CSS owner missing: {selector} {property_name}")

    normalize_property(".tab input", "border", "tab-input-border")
    normalize_property(".button:hover", "color", "button-hover-color")
    normalize_property(".button:active", "color", "button-active-color")
    normalize_property(
        'a[href]:focus-visible,\nbutton:focus-visible,\ninput:not([type="hidden"]):focus-visible,\nselect:focus-visible,\ntextarea:focus-visible,\nsummary:focus-visible,\ninput[type="checkbox"]:focus-visible + label,\n.file-upload-control:focus-within .custom-file-upload',
        "outline",
        "interactive-focus-outline",
    )
    normalize_property(".popup__button", "background-color", "popup-button-bg")
    normalize_property(".popup__button", "color", "popup-button-color")
    normalize_property(".theme-toggle", "border", "theme-toggle-border")
    normalize_property(".theme-toggle", "color", "theme-toggle-color")
    normalize_property(
        'input[type="radio"]:not(:checked) + label:before',
        "border",
        "choice-border",
    )
    normalize_property(
        'input[type="radio"]:not(:checked) + label:before',
        "background-color",
        "choice-background",
    )
    normalize_property(
        'input[type="checkbox"]:not(:checked) + label:after',
        "border-left",
        "checkbox-mark-left",
    )
    normalize_property(
        'input[type="checkbox"]:not(:checked) + label:after',
        "border-bottom",
        "checkbox-mark-bottom",
    )
    text = text.replace("fill='%23444'", "fill='<U03:select-arrow>'")
    text = text.replace("fill='%23777'", "fill='<U03:select-arrow>'")
    return text


def normalize_page(text: str) -> str:
    for token in SENSOR_TOKENS:
        source = f'style="color: %{token}%;"'
        target = (
            'style="color: var(--text-strong); text-decoration-line: underline; '
            f'text-decoration-color: %{token}%;"'
        )
        short_target = (
            'style="text-decoration-line: underline; '
            f'text-decoration-color: %{token}%;"'
        )
        marker = f'style="<U03:{token}>"'
        text = (
            text.replace(source, marker)
            .replace(target, marker)
            .replace(short_target, marker)
        )
    text = text.replace('style="color: black;"', 'style="<U03:delta>"')
    text = text.replace('style="color: var(--text-strong);"', 'style="<U03:delta>"')
    text = text.replace("background: #fafafa;", "background: <U03:program-panel>;")
    text = text.replace(
        "background: var(--bg-program-panel);", "background: <U03:program-panel>;"
    )
    text = text.replace("background: #fff;", "background: <U03:program-example>;")
    text = text.replace("background: #eee;", "background: <U03:program-example>;")
    text = text.replace(
        "background: var(--bg-program-example);", "background: <U03:program-example>;"
    )
    for source, marker in (
        ("#32CD3229", "row-b"), ("#B8E6B8", "row-b"),
        ("#FFFF0039", "row-c"), ("#FFF59D", "row-c"),
        ("#8B451334", "row-t"), ("#D8B9A4", "row-t"),
        ("#FF2929", "row-autotune"), ("#FF3838", "row-autotune"),
        ("#27ae60", "i2c-on"), ("#19733c", "i2c-on"),
        ("#229954", "i2c-on-hover"), ("#176b3a", "i2c-on-hover"),
    ):
        text = text.replace(source, f"<U03:{marker}>")

    text = text.replace("        l.style.color = '#17212B';\n", "")
    text = text.replace("          e[q].style.color = '#17212B';\n", "")
    text = text.replace("          e[q].style.borderColor = '#17212B';\n", "")
    text = text.replace("l.style.color = '#8B0000';", "l.style.color = 'red';")
    text = text.replace("e[q].style.color = '#8B0000';", "e[q].style.color = 'red';")
    text = text.replace(
        '      color += "color: #17212B; border-color: #17212B;";\n', ""
    )
    text = text.replace(
        '  color += "color: #17212B; border-color: #17212B;";\n', ""
    )

    text = text.replace(
        'style="font-size: xx-large; color:#444"',
        'style="font-size: xx-large; color:<U03:nbk-speed>"',
    )
    text = text.replace(
        'style="font-size: xx-large; color:var(--text-strong)"',
        'style="font-size: xx-large; color:<U03:nbk-speed>"',
    )
    for background in ("#FF6347", "#FFFF00", "#00BFFF", "#98FB98"):
        text = text.replace(
            f'style="background-color: {background}; color: #17212B;"',
            f'style="background-color: {background};"',
        )
    for old_color in ("honeydew", "navy", "#17212B"):
        text = text.replace(
            f'style="width:200px;display:inline-block;color:{old_color};"',
            'style="width:200px;display:inline-block;color:<U03:nbk-row-label>;"',
        )
    text = text.replace("color:#17212B;border-color:#17212B;", "")

    for source in (
        "color: #3498db; font-weight: bold; margin-bottom: 10px;",
        "color: var(--text-strong); font-weight: bold; margin-bottom: 10px;",
    ):
        text = text.replace(source, "color: <U03:program-heading>; font-weight: bold; margin-bottom: 10px;")
    for source in (
        "font-size: 0.9em; margin-bottom: 10px; color: #666;",
        "font-size: 0.9em; margin-bottom: 10px; color: var(--text-main);",
    ):
        text = text.replace(source, "font-size: 0.9em; margin-bottom: 10px; color: <U03:program-copy>;")
    for source in (
        "width: 100%; background: #3498db; color: white;",
        "width: 100%; background: var(--accent); color: var(--text-on-accent);",
    ):
        text = text.replace(source, "width: 100%; background: <U03:program-button>; color: <U03:program-button-text>;")
    return text


def normalize_chart(text: str) -> str:
    pattern = re.compile(r"(\{ key: '([^']+)', label: '[^']+', color: ')[^']+(' \})")
    normalized, count = pattern.subn(
        lambda match: match.group(1) + f"<U03:{match.group(2)}>" + match.group(3),
        text,
    )
    if count != 6:
        raise AssertionError(f"chart series cardinality changed: {count}")
    return normalized


def verify_source_boundary() -> None:
    for name, expected in FROZEN_SHA256.items():
        # .gz - продукт сборки, сырьё - источник.
        source = (BUILD if name.endswith(".gz") else DATA) / name
        actual = digest(source.read_bytes())
        if actual != expected:
            raise AssertionError(f"frozen data/{name} changed: {actual}")

    for name, expected in NORMALIZED_SHA256.items():
        text = read_page(name)
        if name == "style.css":
            text = normalize_style(text)
        elif name == "chart.js":
            text = normalize_chart(text)
        else:
            text = normalize_page(text)
        actual = digest(text.encode("utf-8"))
        if actual != expected:
            raise AssertionError(f"U-03 source boundary changed for data/{name}: {actual}")


def verify_mandatory_fixes() -> None:
    index = read_page("index.htm")
    if index.count("l.style.color = '#8B0000';") != 1:
        raise AssertionError("data/index.htm: active row foreground cardinality")
    if index.count("e[q].style.color = '#8B0000';") != 1:
        raise AssertionError("data/index.htm: active row control foreground cardinality")
    if "l.style.color = 'red';" in index or "e[q].style.color = 'red';" in index:
        raise AssertionError("data/index.htm: unverified active row red remains")

    for name in DELTA_PAGES:
        text = read_page(name)
        if 'style="color: black;"' in text:
            raise AssertionError(f"data/{name}: DeltaTemp still uses black")
        if text.count('style="color: var(--text-strong);"') != 1:
            raise AssertionError(f"data/{name}: DeltaTemp theme color cardinality")

    program = read_page("program.htm")
    for literal in ("background: #fafafa;", "background: #fff;", "background: #eee;"):
        if literal in program:
            raise AssertionError(f"data/program.htm: fixed audit surface remains: {literal}")
    if program.count("background: var(--bg-program-panel);") != 1:
        raise AssertionError("data/program.htm: program panel token cardinality")
    # Было 2 (columnParamsResults, strategyNote), стало 3: добавлен блок-примечание
    # colSpeedClampNote (сигнал "рекомендованная скорость упёрлась в предел сечения
    # колонны"). Новый цвет не вводится - переиспользован уже проверенный на
    # контраст токен --bg-program-example.
    if program.count("background: var(--bg-program-example);") != 3:
        raise AssertionError("data/program.htm: program example token cardinality")

    full_target_template = (
        'style="color: var(--text-strong); text-decoration-line: underline; '
        'text-decoration-color: %{token}%;"'
    )
    short_target_template = (
        'style="text-decoration-line: underline; text-decoration-color: %{token}%;"'
    )
    for name in SENSOR_PAGES:
        text = read_page(name)
        target_template = (
            full_target_template if name == "setup.htm" else short_target_template
        )
        for token in SENSOR_TOKENS:
            target = target_template.format(token=token)
            if text.count(target) != 1:
                raise AssertionError(f"data/{name}: {token} readable accent cardinality")
            if f'style="color: %{token}%;"' in text:
                raise AssertionError(f"data/{name}: {token} remains a foreground")

    style = read_page("style.css")
    if style.count("#file-input {\n  padding: 0;\n  border: 1px solid #ddd;\n") != 1:
        raise AssertionError("data/style.css: file input baseline border changed")
    expected_message = (
        ".message_0 { background: var(--state-danger-bg); "
        "color: var(--text-on-accent); }"
    )
    if style.count(expected_message) != 1:
        raise AssertionError("message_0 foreground/background ownership")


def relative_luminance(color: str) -> float:
    text = color.strip()
    if re.fullmatch(r"#[0-9a-fA-F]{3}", text):
        text = "#" + "".join(channel * 2 for channel in text[1:])
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", text):
        raise AssertionError(f"opaque #rgb or #rrggbb color required, got {color!r}")
    channels = []
    for offset in (1, 3, 5):
        value = int(text[offset:offset + 2], 16) / 255
        channels.append(value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast_ratio(first: str, second: str) -> float:
    high, low = sorted((relative_luminance(first), relative_luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def verify_button_contrast() -> None:
    """Цвета кнопок как в 6.27: --accent #3498db, hover #3498db97.

    WCAG 4.5 для этой палитры не выполняется (белый на #3498db - 3.15), это
    исходный вид интерфейса, и решением владельца от 01.09.2026 вид имеет
    приоритет над контрастом: более тёмный --accent сюда не подставляем.
    Замеренная цена решения зафиксирована списком ACCEPTED_CONTRAST в
    tools/test_u03_contrast_browser.py - там же ловится любое УХУДШЕНИЕ этих пар.

    Важно, что текст на наведении при этой палитре тёмный (--text-strong):
    фон #3498db97 полупрозрачный, его итоговый цвет зависит от подложки, и
    белый текст на нём давал 1.96 - хуже, чем что-либо в самой палитре 6.27."""
    style = read_page("style.css")
    values = {}
    for token in ("accent", "accent-hover", "text-on-accent"):
        found = re.findall(rf"--{token}:\s*([^;]+);", style)
        if len(found) != 1:
            raise AssertionError(f"data/style.css: --{token} declaration cardinality={len(found)}")
        values[token] = found[0].strip()
    if values["accent"].lower() != "#3498db":
        raise AssertionError(f"data/style.css: --accent must stay 6.27 #3498db, got {values['accent']}")
    if values["accent-hover"].lower() != "#3498db97":
        raise AssertionError(
            f"data/style.css: --accent-hover must stay 6.27 #3498db97, got {values['accent-hover']}"
        )
    if values["text-on-accent"].lower() not in ("#fff", "#ffffff"):
        raise AssertionError(
            f"data/style.css: --text-on-accent must stay white, got {values['text-on-accent']}"
        )
    # Текст на наведении обязан быть тёмным: фон полупрозрачный, белый на нём - 1.96.
    hover_rules = re.findall(r"\.button:(?:hover|active)[^{}]*\{([^{}]*)\}", style)
    if len(hover_rules) != 2 or any(
        "var(--text-strong)" not in body for body in hover_rules
    ):
        raise AssertionError("data/style.css: .button hover/active text must stay --text-strong")


def verify_chart_palette() -> None:
    text = read_page("chart.js")
    colors = re.findall(r"\{ key: '[^']+', label: '[^']+', color: '([^']+)' \}", text)
    if len(colors) != 6 or len(set(colors)) != 6:
        raise AssertionError("chart series palette must contain six distinct colors")


def verify_canonical_gzip() -> None:
    source = (DATA / "style.css").read_bytes()
    stored = (BUILD / "style.css.gz").read_bytes()
    first = canonical_gzip(source)
    second = canonical_gzip(source)
    if first != second or stored != first:
        raise AssertionError("style.css.gz is not the canonical deterministic projection")
    if stored[:10].hex() != "1f8b08000000000002ff":
        raise AssertionError(f"style.css.gz header changed: {stored[:10].hex()}")
    stream = zlib.decompressobj(wbits=31)
    expanded = stream.decompress(stored) + stream.flush()
    if not stream.eof or stream.unused_data or expanded != source:
        raise AssertionError("style.css.gz must be one complete member matching style.css")
    if gzip.decompress(stored) != source:
        raise AssertionError("style.css.gz standard decompression mismatch")


def main() -> int:
    try:
        verify_source_boundary()
        verify_mandatory_fixes()
        verify_button_contrast()
        verify_chart_palette()
        verify_canonical_gzip()
    except (AssertionError, OSError, ValueError, RuntimeError) as error:
        print(f"U-03 contrast smoke failed: {error}", file=sys.stderr)
        return 1
    print("U-03 contrast smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
