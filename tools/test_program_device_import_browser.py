#!/usr/bin/env python3
"""Браузерная проверка В1: разбор программы прибора для редактора (program.htm).

parseDeviceProgramRows / deviceProgramRowVlc / deviceProgramRowToEditorRow /
buildEditorBodyFromDeviceProgram - обратное к set_num() преобразование
"прошивка -> редактор". Формула: percent = (volumeMl/1000)/vlc, округление до
6 знаков (vlc = phv/100, ptv/100 или pbas/100 в зависимости от типа строки -
те же делители, что использует set_num()).

Проверяется:
1. Нормальная rect-программа: разбор в редактор, а затем ЗАМКНУТОСТЬ круга по
   формуле из собственного комментария deviceProgramRowToEditorRow()
   ("Обратное к set_num(): ll = percent*vlc, Объём_мл = round(ll*1000)") -
   должны получиться исходные объёмы в мл. Обратную сборку НЕ гоняем через
   живой calc_program()/set_num(): там есть не относящийся к В1 предохранитель
   живого редактирования (поле "Процент" обрубается до целого, если оно не в
   фокусе - see set_num(): `if (e[i].childNodes[3] !== document.activeElement)
   ... substring(0, indexOf('.'))`), который безусловно уничтожает дробную
   часть у только что созданных addLine() строк. Через calc_program() тест
   проверял бы этот сторонний обрубающий предохранитель, а не разбор
   программы прибора - при ручной проверке (см. отчёт) это оказался реальный,
   не связанный с этой правкой путь потери точности в проде: "Записать" без
   клика по полю процента после автозагрузки программы прибора огрубляет её
   проценты до целых.
2. Деление на ноль (доля голов = 0% -> делитель для типа H равен 0), пустое поле
   объёма и нечисловое поле объёма - процент должен остаться 0 в каждом случае, но
   по разной причине: пустое поле - это Number("") === 0 (обычный нулевой объём,
   защита isFinite() тут вообще не участвует), а нечисловое ("abc") - это
   Number("abc") === NaN, и от превращения в NaN/Infinity здесь действительно
   спасает guard isFinite(volumeMl) в deviceProgramRowToEditorRow().
3. Чужой формат: другое число колонок и неизвестный тип строки - разбор
   должен отбросить программу ЦЕЛИКОМ (null), а не показать её наполовину.
4. Пустая программа (пустая строка и строка из одних пробелов) - null.
5. ЗАМКНУТОСТЬ КРУГА ЧЕРЕЗ НАСТОЯЩИЙ ПУТЬ СТРАНИЦЫ (а не в обход, как в п.1):
   программа прибора в WProgram при загрузке страницы -> window.onload сам
   вызывает buildEditorBodyFromDeviceProgram()+calc_program() -> оператор жмёт
   "Установить программу" (#setprogram, set_program()) НЕ трогая ни одного
   поля -> WProgram, ушедший в POST /program, должен побайтово совпасть с тем,
   что было в приборе. Раньше этого не было: обрубающий предохранитель поля
   "Процент" из п.1 (set_num(): `if (e[i].childNodes[3] !== document.
   activeElement) ... substring(0, indexOf('.'))`) применялся на КАЖДЫЙ вызов
   set_num() к ЛЮБОЙ строке таблицы, а не только к той, что редактируют - а
   после programmatic-заполнения из В1 ни одна строка не в фокусе. В итоге уже
   первая прорисовка (внутри onload) обрубала дробные проценты до целых, и
   именно ЭТО, а не разбор программы прибора, портило объём при "Записать" -
   ту самую регрессию из п.1 воспроизводили в обход. Правка перенесла обрубание
   на onchange САМОГО поля "Процент" (так обрезка срабатывает только когда
   оператор реально закончил печатать в это поле и увёл фокус), поэтому теперь
   и этот тест гоняет полный путь, а не формулу в обход UI.

Ожидаемые проценты посчитаны независимо в Node по документированной формуле
(без обращения к коду страницы) для дефолтных полей формы на этой странице
(vless=12.25, vlssp=34%, vlp=94%, vlhp=8%, vltp=5% -> phv=0.354468085106383,
ptv=0.44308510638297877, pbas=3.854840425531915):
  H;1000 -> percent 282.112845 (round-trip даёт обратно 1000)
  C;250  -> percent 6.485353  (C делит объём тем же делителем, что и B)
  B;1234 -> percent 32.011701
  T;100  -> percent 22.569028
"""
import functools
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_numeric_input_ui_browser import QuietHandler, cleanup, render_site, run_cli

ROOT = Path(__file__).resolve().parents[1]

# Программа для п.5 (замкнутость круга через настоящий window.onload -> "Записать").
# Поля расчёта - ДЕФОЛТНЫЕ значения страницы (vless=12.25, vlssp=34%, vlp=94%,
# vlhp=8%, vltp=5%, см. докстринг выше) - phv=0.354468085106383 и
# pbas=3.854840425531915 дробные, поэтому по каждой строке в мл берём РОВНО весь
# бюджет фракции одной строкой (round(phv*1000)=354, round(pbas*1000)=3855) - это
# именно тот сценарий, из-за которого distributionStatus раньше сравнивал сумму
# процентов со 100 строгим равенством: обратный пересчёт (В1) даёт 99.867947% для
# головы и 100.004140% для тела, а не ровно 100 - округление до целого мл при
# импорте программы прибора неустранимо. Программа, прочитанная с прибора и не
# тронутая оператором, обязана уйти обратно без ошибки распределения. Строка T
# намеренно произвольная (137 мл, не привязана к бюджету) - сумма по хвостам ни на
# что не блокирует (distributionStatus для хвостов - всегда is-info).
CLOSED_LOOP_DEVICE_PROGRAM = (
    "H;354;50;0;0;135\n"
    "B;3855;80;1;0;140\n"
    "T;137;30;2;0;120\n"
    "P;30;30;0;0;0"
)


def seed_device_program_page(site: Path) -> None:
    """Готовит program_device_seed.htm: WProgram заполнен ДО загрузки страницы (в
    отличие от остальных сценариев файла, которые правят DOM уже ПОСЛЕ
    window.onload) - только так можно проверить именно то, что делает onload сам,
    без посторонней помощи из теста. Поля расчёта НЕ переопределяются - страница
    открывается с СОБСТВЕННЫМИ дефолтами (vless=12.25 и т.д.), это и есть
    реалистичный случай: оператор ничего на странице не трогал."""
    program = site / "program.htm"
    original = program.read_text(encoding="utf-8")
    marker = (
        "id='WProgram' name='WProgram' style=\"visibility: hidden;position: absolute;width: 20px;\" hidden>"
        "</textarea>"
    )
    if marker not in original:
        raise RuntimeError(
            "program.htm markup changed, update seed_device_program_page(): " + marker[:80]
        )
    patched = original.replace(
        marker,
        marker.replace("</textarea>", "") + CLOSED_LOOP_DEVICE_PROGRAM + "</textarea>",
        1,
    )
    (site / "program_device_seed.htm").write_text(patched, encoding="utf-8")


BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  await page.goto(baseUrl + "/program.htm", { waitUntil: "load" });
  await page.waitForTimeout(400);

  const result = await page.evaluate(() => {
    const normalDevice =
      "H;1000;50;0;0;135\n" +
      "C;250;80;1;0;140\n" +
      "B;1234;80;1;0;140\n" +
      "T;100;30;2;0;120\n" +
      "P;30;30;0;0;0";

    const editorBody = buildEditorBodyFromDeviceProgram(normalDevice);

    // Замкнутость круга проверяем формулой из собственного комментария
    // deviceProgramRowToEditorRow() ("Обратное к set_num(): ll = percent*vlc,
    // Объём_мл = round(ll*1000)"), а не живым calc_program()/set_num(): у
    // set_num() есть НЕСВЯЗАННАЯ с В1 логика живого редактирования - поле
    // "Процент" обрубается до целого, если оно не в фокусе (см. код set_num():
    // "if (e[i].childNodes[3] !== document.activeElement) { ... substring(0,
    // indexOf('.')) ... }"), и она безусловно съедает дробную часть у СВЕЖИХ
    // строк (a они у нас всегда свежие - addLine создаёт новые DOM-узлы).
    // Через calc_program() проверка ловила бы не разбор программы прибора,
    // а этот сторонний обрубающий предохранитель.
    function editorRowToDeviceVolume(percentValue, type) {
      const vlc = deviceProgramRowVlc(type);
      return Math.round(Number(percentValue) * vlc * 1000);
    }
    const editorRows = editorBody.split("\n").map(function(row) { return row.split(";"); });
    const roundTrippedVolumes = editorRows.map(function(fields) {
      const type = fields[3];
      if (type === "P") return null; // тип 'P' не использует процент/объём фракции
      return editorRowToDeviceVolume(fields[2], type);
    });

    // [деление на ноль] Доля голов = 0% -> делитель для типа H равен 0.
    // deviceProgramRowVlc() читает глобальные phv/ptv/pbas, которые считает
    // только prep_calc() - без явного вызова после правки поля они останутся
    // от предыдущего prep_calc() внутри buildEditorBodyFromDeviceProgram() выше.
    const vlhpField = document.getElementById("vlhp");
    const originalVlhp = vlhpField.value;
    vlhpField.value = "0";
    prep_calc();
    const zeroVlcRow = deviceProgramRowToEditorRow(["H", "500", "50", "0", "0", "135"]);
    vlhpField.value = originalVlhp;
    prep_calc();

    // [пустое поле объёма] - делитель обычный (>0), но Number("") === 0: это обычный
    // нулевой объём, а не защита от NaN - isFinite(volumeMl) тут пропускает 0 как есть.
    const emptyVolumeRow = deviceProgramRowToEditorRow(["H", "", "50", "0", "0", "135"]);
    // [нечисловое поле объёма] - Number("abc") === NaN, и именно ЭТОТ кейс проверяет
    // guard isFinite(volumeMl) в deviceProgramRowToEditorRow().
    const nonNumericVolumeRow = deviceProgramRowToEditorRow(["H", "abc", "50", "0", "0", "135"]);

    // [чужой формат]
    const wrongColumnCount = parseDeviceProgramRows("H;100;50;0;20");
    const unknownType = parseDeviceProgramRows("H;100;50;0;20;135\nX;200;50;0;20;140");
    const mixedGoodBadColumns = parseDeviceProgramRows("H;100;50;0;20;135\nB;200;50;0;20;140;999");

    // [пустая программа]
    const emptyText = parseDeviceProgramRows("");
    const blankText = parseDeviceProgramRows("   \n  \n");
    const emptyBuiltBody = buildEditorBodyFromDeviceProgram("");
    const blankBuiltBody = buildEditorBodyFromDeviceProgram("   ");

    return {
      editorBody: editorBody,
      roundTrippedVolumes: roundTrippedVolumes,
      zeroVlcRow: zeroVlcRow,
      emptyVolumeRow: emptyVolumeRow,
      nonNumericVolumeRow: nonNumericVolumeRow,
      wrongColumnCount: wrongColumnCount,
      unknownType: unknownType,
      mixedGoodBadColumns: mixedGoodBadColumns,
      emptyText: emptyText,
      blankText: blankText,
      emptyBuiltBody: emptyBuiltBody,
      blankBuiltBody: blankBuiltBody
    };
  });

  const expectedEditorBody =
    "0;50;282.112845;H;135\n" +
    "1;80;6.485353;C;140\n" +
    "1;80;32.011701;B;140\n" +
    "2;30;22.569028;T;120\n" +
    "0;30;0;P;0";
  if (result.editorBody !== expectedEditorBody) {
    throw new Error("parseDeviceProgramRows/deviceProgramRowToEditorRow mismatch: " +
      JSON.stringify({ got: result.editorBody, expected: expectedEditorBody }));
  }

  const expectedVolumes = [1000, 250, 1234, 100, null];
  if (JSON.stringify(result.roundTrippedVolumes) !== JSON.stringify(expectedVolumes)) {
    throw new Error("device program -> editor -> device volume round trip is not closed: " +
      JSON.stringify({ got: result.roundTrippedVolumes, expected: expectedVolumes }));
  }

  if (result.zeroVlcRow !== "0;50;0;H;135") {
    throw new Error("zero divisor (heads%=0) must yield percent 0, not NaN/Infinity: " +
      JSON.stringify(result.zeroVlcRow));
  }
  if (result.emptyVolumeRow !== "0;50;0;H;135") {
    throw new Error("empty volume field must yield percent 0: " + JSON.stringify(result.emptyVolumeRow));
  }
  if (result.nonNumericVolumeRow !== "0;50;0;H;135") {
    throw new Error("non-numeric volume field must yield percent 0, not NaN: " +
      JSON.stringify(result.nonNumericVolumeRow));
  }

  if (result.wrongColumnCount !== null) {
    throw new Error("5-field row (foreign format) must be rejected entirely: " +
      JSON.stringify(result.wrongColumnCount));
  }
  if (result.unknownType !== null) {
    throw new Error("unknown row type must reject the whole program: " + JSON.stringify(result.unknownType));
  }
  if (result.mixedGoodBadColumns !== null) {
    throw new Error("one malformed row must reject the whole program, not just that row: " +
      JSON.stringify(result.mixedGoodBadColumns));
  }

  if (result.emptyText !== null || result.blankText !== null) {
    throw new Error("empty/blank program text must parse to null: " +
      JSON.stringify({ emptyText: result.emptyText, blankText: result.blankText }));
  }
  if (result.emptyBuiltBody !== null || result.blankBuiltBody !== null) {
    throw new Error("empty/blank program text must build to null editor body: " +
      JSON.stringify({ emptyBuiltBody: result.emptyBuiltBody, blankBuiltBody: result.blankBuiltBody }));
  }

  // ===== п.5: замкнутость круга через НАСТОЯЩИЙ путь страницы =====
  // program_device_seed.htm - отдельная страница (см. seed_device_program_page() в
  // Python-части этого файла): WProgram и поля расчёта заполнены ДО загрузки, поэтому
  // весь разбор запускает сам window.onload, а не тестовый код в обход него.
  const closedLoopProgram = __CLOSED_LOOP_DEVICE_PROGRAM__;
  await page.goto(baseUrl + "/program_device_seed.htm", { waitUntil: "load" });
  await page.waitForTimeout(400);

  // Строка T (третья, addLine нумерует с 0 -> percent2) - единственная с нетривиальной
  // дробной частью. Если поле уже показывает целое - обрубание сработало ДО того, как
  // оператор хоть раз коснулся страницы, и дальше можно не проверять "Записать".
  const importedPercent = await page.evaluate(() => document.getElementById("percent2").value);
  if (importedPercent.indexOf(".") < 0) {
    throw new Error("percent field was truncated on the very first render (before any user " +
      "interaction), expected a fractional value: " + JSON.stringify(importedPercent));
  }

  await page.evaluate(() => {
    // Как в tools/test_program_clear_ui_browser.py: подменяем window.fetch, а не
    // page.route, потому что postProgram() ждёт ещё и опрос /ajax?operationId=...
    // после успешной постановки в очередь - оба конца проще держать в одном месте.
    window.alert = function () {};
    window.__programRequests = [];
    const nativeFetch = window.fetch.bind(window);
    window.fetch = function (url, options) {
      if (typeof url === "string" && url.indexOf("/ajax?operationId=") === 0) {
        return Promise.resolve(new Response(
          JSON.stringify({ operationId: 1, state: "succeeded", error: "none" }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        ));
      }
      if (url === "/program") {
        window.__programRequests.push(Array.from(options.body.entries()));
        const body = { ok: true, err: "", program: "", operationId: 1, state: "queued", error: "none" };
        return Promise.resolve(new Response(
          JSON.stringify(body),
          { status: 202, headers: { "Content-Type": "application/json" } }
        ));
      }
      return nativeFetch(url, options);
    };
  });

  // Настоящий клик по кнопке "Установить программу" - ни одно поле программы при
  // этом не трогаем (замкнутость круга проверяется именно как "открыл и сразу нажал").
  await page.click("#setprogram");
  await page.waitForFunction(
    () => window.__programRequests && window.__programRequests.length > 0,
    null,
    { timeout: 5000 }
  );

  const closedLoop = await page.evaluate(() => {
    const entries = window.__programRequests[0];
    const field = entries.find(function (entry) { return entry[0] === "WProgram"; });
    return { blocked: programerr, posted: field ? field[1] : null };
  });
  if (closedLoop.blocked) {
    throw new Error("closed-loop program was rejected by validation before \"Установить " +
      "программу\" could send it, expected it to be accepted unmodified");
  }
  if (closedLoop.posted !== closedLoopProgram) {
    throw new Error("device program is not byte-identical after open page -> press " +
      "\"Установить программу\" without touching anything: " +
      JSON.stringify({ got: closedLoop.posted, expected: closedLoopProgram }));
  }

  return result;
}'''


def main() -> int:
    cli = shutil.which("playwright-cli")
    if not cli:
        print("playwright-cli is required for this explicit browser gate", file=sys.stderr)
        return 2

    primary_error = None
    with tempfile.TemporaryDirectory(prefix="samovar-program-device-import-") as temp_dir:
        temp = Path(temp_dir)
        site = temp / "site"
        render_site(site)
        seed_device_program_page(site)
        handler = functools.partial(QuietHandler, directory=str(site))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        session = f"pdi{os.getpid()}"

        cleanup_errors = []
        try:
            open_args = ["open"]
            if hasattr(os, "geteuid") and os.geteuid() == 0:
                config = temp / "playwright.json"
                config.write_text(json.dumps({
                    "browser": {"browserName": "chromium", "launchOptions": {"chromiumSandbox": False}}
                }), encoding="utf-8")
                open_args.append(f"--config={config}")

            run_cli(cli, session, open_args, temp, 30)
            base_url = f"http://127.0.0.1:{server.server_port}"
            browser_test = (
                BROWSER_TEST
                .replace("__BASE_URL__", json.dumps(base_url))
                .replace("__CLOSED_LOOP_DEVICE_PROGRAM__", json.dumps(CLOSED_LOOP_DEVICE_PROGRAM))
            )
            run_cli(cli, session, ["run-code", browser_test], temp, 60)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            primary_error = str(error)
        finally:
            cleanup_errors = cleanup(cli, session, server, thread)

    if primary_error or cleanup_errors:
        if primary_error:
            print(f"Program device import browser contract failed: {primary_error}", file=sys.stderr)
        for error in cleanup_errors:
            print(f"Program device import browser cleanup failed: {error}", file=sys.stderr)
        return 1

    print("Program device import browser contract passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
