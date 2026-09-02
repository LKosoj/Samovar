#!/usr/bin/env python3
"""Браузерная проверка калькулятора ректификации (program.htm):

1. Объёмы в WProgram уходят целыми мл (прошивка parse_bounded_long).
2. «Применить рекомендации» масштабирует профиль скоростей, а не плющит
   все строки одного типа в одну скорость.
3. Смена диаметра 1.5 / 2 / 3 пересчитывает отбор пропорционально площади.
4. Файл с одним полем мощности — вольты; на ваттовый регулятор его нельзя
   поставить, пока не пересчитаны рекомендации. Два поля мощности — вольты
   и ватты, под регулятор берётся нужная колонка.
5. Допуск проверки распределения по строкам (headsBalanced/bodyBalanced в
   set_num()) масштабируется числом строк фракции (0.5 мл * count), а не
   фиксирован в 0.5 мл: многострочная фракция с накопленным округлением
   больше 0.5 мл, но в пределах 0.5*count, обязана пройти; фракция, реально
   не покрывающая бюджет, обязана быть отклонена независимо от числа строк.
6. Примечание colSpeedClampNote (В8) о том, что рекомендованная скорость
   упёрлась в предел сечения колонны, — все варианты: зажаты только головы
   (уже было), только тело, оба сразу, и «упора нет» (блок скрыт).
7. [Б7 правка 1] Пересчёт вольт->ватт не даёт молча поменять СМЫСЛ строки ни
   в одну из сторон: слишком слабый ТЭН не превращает абсолютную уставку в
   дельту, слишком мощный ТЭН не превращает дельту в абсолютную уставку -
   пересчёт всей программы в обоих случаях отменяется целиком (эталонная
   6-я колонка файла, без подмешивания пересчитанных строк), и это видно
   пользователю через showRequestError.
8. [Б7.4 правка 2] Программа из ОДНОЙ строки тоже проверяется на абсолютную
   уставку в первой строке — не только программы из двух и более строк.
9. [В5, formatDualProgramFile] Диагностика "смысл значения не совпадает после
   пересчёта" покрывает все четыре ветки функции, включая дельту БЕЗ опоры
   (нет абсолютной уставки выше по программе) - число копируется в оба
   столбца сырьём, но пороги V (40) и P (400) разные, значит то же число
   может быть дельтой в одной единице и абсолютной уставкой в другой.
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

BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  await page.route("**/ajax*", async route => {
    const reqUrl = route.request().url();
    let diam = 2;
    const match = reqUrl.match(/[?&]diam=([^&]+)/);
    if (match) diam = parseFloat(decodeURIComponent(match[1]));
    if (!(diam > 0)) diam = 2;
    const k = (diam * diam) / 4;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        floodPowerW: 3000 * k,
        workingPowerW: 2500 * k,
        maxFlowMlH: 1000 * k,
        theoreticalPlates: 20,
        headsFlowMlH: 100 * k,
        bodyFlowMinMlH: 200 * k,
        bodyFlowMaxMlH: 400 * k,
        bodyEndFlowMlH: 300 * k,
        tailsFlowMlH: 150 * k,
        headsPowerW: 1800 * k,
        bodyEndPowerW: 2200 * k,
        tailsPowerW: 2000 * k,
        headsSpeedClamped: false,
        bodySpeedClamped: false
      })
    });
  });
  await page.goto(baseUrl + "/program.htm", { waitUntil: "load" });
  await page.waitForTimeout(400);

  const result = await page.evaluate(() => {
    function firmwareVolumes(text) {
      return String(text).split("\n").filter(Boolean).map(function(line) {
        const f = line.split(";");
        return { type: f[0], volume: f[1], integer: /^\d+$/.test(f[1]) };
      });
    }
    function speedsByType(types) {
      const out = [];
      document.querySelectorAll(".prgline").forEach(function(line) {
        const typeEl = line.querySelector('select[name^="ptype"]');
        const speedEl = line.querySelector('input[name^="speed"]');
        if (!typeEl || !speedEl) return;
        if (types.indexOf(typeEl.value) < 0) return;
        out.push(Number(speedEl.value));
      });
      return out;
    }
    function paramsFor(diam) {
      const k = (diam * diam) / 4;
      return {
        floodPowerW: 3000 * k,
        workingPowerW: 2500 * k,
        maxFlowMlH: 1000 * k,
        theoreticalPlates: 20,
        headsFlowMlH: 100 * k,
        bodyFlowMinMlH: 200 * k,
        bodyFlowMaxMlH: 400 * k,
        bodyEndFlowMlH: 300 * k,
        tailsFlowMlH: 150 * k,
        headsPowerW: 1800 * k,
        bodyEndPowerW: 2200 * k,
        tailsPowerW: 2000 * k,
        headsSpeedClamped: false,
        bodySpeedClamped: false
      };
    }

    const volumes = firmwareVolumes(document.getElementById("WProgram").value);

    rememberUnscaledProgram(
      "0;0.200;50;H;135\n0;0.100;50;H;0\n4;1.000;50;B;140\n4;0.500;50;B;0\n7;0.400;100;T;140",
      "V"
    );
    columnParams = paramsFor(2);
    columnRecommendationsApplied = false;
    applyRecommendedSpeeds({ silent: true });
    const scaledHeads = speedsByType("H");
    const scaledBody = speedsByType("B");
    const scaledTails = speedsByType("T");

    columnParams = paramsFor(1.5);
    applyRecommendedSpeeds({ silent: true });
    const body15 = Math.max.apply(null, speedsByType("BC"));
    // [Ф5] На 3" предзахлёб фикстуры = 6750 Вт > ТЭН харнесса 5290 Вт - рекомендации
    // отказываются целиком (это проверяет test_program_flood_power_recommendations_browser).
    // Здесь измеряем масштаб по сечению, поэтому на время замера даём ТЭН, которого хватает.
    const heaterForDiam = document.getElementById("heaterMaxPower");
    const heaterBeforeDiam = heaterForDiam.value;
    heaterForDiam.value = "8000";
    columnParams = paramsFor(3);
    const applied30 = applyRecommendedSpeeds({ silent: true });
    const body30 = Math.max.apply(null, speedsByType("BC"));
    heaterForDiam.value = heaterBeforeDiam;

    columnRecommendationsApplied = false;
    loadedProgramPowerUnit = "V";
    pwr_unit = "P";
    const blocked = programPowerUnitFitsRegulator();
    applyRecommendedSpeeds({ silent: true });
    const afterApply = programPowerUnitFitsRegulator();
    const unitAfter = loadedProgramPowerUnit;

    const dual = parseProgramFileText("0;0.200;50;H;135;1199");

    // [В4/В5] ТЭН неизвестен: программа как есть, ватты берутся из шестой колонки файла.
    const heaterInput = document.getElementById("heaterMaxPower");
    const heaterKnownValue = heaterInput.value;
    heaterInput.value = "";
    const dualPNoHeater = programBodyForUnit(dual, "P");
    heaterInput.value = heaterKnownValue;

    // ТЭН известен (харнесс: HeaterR=10, MainsVoltage=230 -> heaterMaxPower=5290):
    // вольты (истина) пересчитываются в ватты под реальный ТЭН, а не берутся из файла.
    const dualV = programBodyForUnit(dual, "V");
    const dualP = programBodyForUnit(dual, "P");

    // Дельта пересчитывается как приращение вокруг предыдущей абсолютной уставки
    // (100 В), а не берётся из шестой колонки файла как попало (999 - заведомая
    // приманка, которая не должна попасть в результат).
    const dualDelta = parseProgramFileText("0;0.200;50;H;100;1000\n0;0.200;50;B;5;999");
    const dualDeltaP = programBodyForUnit(dualDelta, "P");

    // [Б7 правка 1] ТЭН слишком слабый: под heaterMaxPwr=1058 (R=50 Ом) и 135 В,
    // и 140 В (обе абсолютные в вольтах, порог 40) пересчитываются в ватты НИЖЕ
    // порога 400 (365 и 392) - то есть перестают быть абсолютными. Пересчёт всей
    // программы обязан отмениться (иначе строка B молча превратится из "поставить
    // 392 Вт" в "прибавить 392 Вт" - неконтролируемый разгон), и в результат
    // обязана уйти ГОТОВАЯ 6-я колонка файла (9001/9002/9003) БЕЗ ИЗМЕНЕНИЙ и без
    // подмешивания настоящего пересчёта хотя бы для одной строки.
    const weakHeaterProgram = parseProgramFileText(
      "0;0.200;50;H;135;9001\n0;0.100;50;H;5;9002\n4;1.000;50;B;140;9003"
    );
    heaterInput.value = "1058";
    const weakHeaterP = programBodyForUnit(weakHeaterProgram, "P");
    const weakHeaterErrorEl = document.getElementById("request_error");
    const weakHeaterErrorShown = !!weakHeaterErrorEl && weakHeaterErrorEl.style.display === "block";
    const weakHeaterErrorText = weakHeaterErrorEl ? weakHeaterErrorEl.textContent : "";
    heaterInput.value = heaterKnownValue;

    // [Б7 правка 1, зеркальная сторона] ТЭН СЛИШКОМ МОЩНЫЙ: реальная строка
    // предзахлёба шаблона program_fruit.txt ("5;1.1;40;C;3;68" после опорной
    // абсолютной уставки 170 В) - дельта +3 В. Под heaterMaxPwr=24045 (R=2.2 Ом)
    // она пересчитывается как round(watts(173)) - round(watts(170)) =
    // 13604 - 13136 = 468 Вт - ВЫШЕ порога 400, то есть дельта молча стала бы
    // абсолютной уставкой (регулятор прыгнет на фиксированные 468 Вт вместо
    // плавной подстройки поверх текущего значения - тот же обман смысла строки,
    // что и со слабым ТЭНом выше, только в другую сторону). Пересчёт всей
    // программы обязан отмениться тем же путём (эталонная 6-я колонка,
    // то же предупреждение).
    const powerfulHeaterProgram = parseProgramFileText(
      "0;200;0;P;170;9101\n5;1.1;40;C;3;9102"
    );
    heaterInput.value = "24045";
    const powerfulHeaterP = programBodyForUnit(powerfulHeaterProgram, "P");
    const powerfulHeaterErrorEl = document.getElementById("request_error");
    const powerfulHeaterErrorShown = !!powerfulHeaterErrorEl && powerfulHeaterErrorEl.style.display === "block";
    const powerfulHeaterErrorText = powerfulHeaterErrorEl ? powerfulHeaterErrorEl.textContent : "";
    heaterInput.value = heaterKnownValue;

    // [В5, ветка без опоры] formatDualProgramFile() на строке без абсолютной
    // уставки ВЫШЕ ПО ПРОГРАММЕ (lastAbsoluteNative === null - например первая
    // строка) копирует число сырьём в оба столбца, заменить его нечем - но
    // пороги V (40) и P (400) разные: 200 для ваттного регулятора - дельта
    // (ниже 400), а то же число 200 в вольтовом столбце читается уже как
    // АБСОЛЮТНАЯ уставка (выше 40). Значения столбцов не меняются, но
    // предупреждение обязано появиться - это была последняя из четырёх веток
    // функции, не проверявшая otherUnitGainsAbsolute.
    const noAnchorDeltaBody = formatDualProgramFile("0;0.200;50;H;200", "P");
    const noAnchorDeltaErrorEl = document.getElementById("request_error");
    const noAnchorDeltaErrorShown = !!noAnchorDeltaErrorEl && noAnchorDeltaErrorEl.style.display === "block";
    const noAnchorDeltaErrorText = noAnchorDeltaErrorEl ? noAnchorDeltaErrorEl.textContent : "";

    pwr_unit = "P";
    columnRecommendationsApplied = false;
    applyParsedProgramText(dual);
    const dualFits = programPowerUnitFitsRegulator();
    const dualLoaded = loadedProgramPowerUnit;
    const dualBody = document.getElementById("WProgram1").value;

    // [Б7.4] Первая строка программы с дельтой (не абсолютной уставкой) должна
    // подсветиться ошибкой интерфейса - иначе колонна разгоняется на полной мощности.
    pwr_unit = "V";
    columnRecommendationsApplied = false;
    applyParsedProgramText(parseProgramFileText("0;0.200;50;H;20\n4;1.000;50;B;140"));
    const b74Error = programErrorMessage.indexOf(
      "первая строка программы должна задавать абсолютную мощность/напряжение"
    ) >= 0;

    // [Б7.4 правка 2] Программа из ОДНОЙ строки тоже обязана проверяться: e[0] -
    // заголовок таблицы, e[1] - единственная строка, поэтому e.length у
    // однострочной программы равен 2 - условие "e.length > 2" требовало минимум
    // ДВЕ строки и молча пропускало однострочную программу с дельтой вместо
    // абсолютной уставки (прошивка, program_io.h, проверяет и draft.len == 1).
    pwr_unit = "V";
    columnRecommendationsApplied = false;
    applyParsedProgramText(parseProgramFileText("0;0.200;50;H;20"));
    const b74SingleRowError = programErrorMessage.indexOf(
      "первая строка программы должна задавать абсолютную мощность/напряжение"
    ) >= 0;

    // [допуск распределения масштабируется числом строк] Прибор хранит объём
    // строки в целых мл, поэтому округление КАЖДОЙ строки по отдельности даёт
    // накопленную погрешность, которая растёт вместе с числом строк фракции -
    // отсюда и допуск 0.5*count, а не фиксированные 0.5 мл. Числа посчитаны
    // независимо от кода страницы (по формуле из В1/prep_calc для ДЕФОЛТНЫХ
    // полей этой страницы: vless=12.25, vlssp=34%, vlp=94%, vlhp=8%, vltp=5%):
    //   tas = 12.25*0.34 = 4.165; thv = tas*0.08 = 0.3332; ttv = tas*0.05 = 0.20825
    //   pbas = (tas-thv-ttv)/vlp = (4.165-0.3332-0.20825)/0.94
    //     = 3.854840425531915 л -> targetBodyMl = round(pbas*1000) = 3855.
    // Тело из 4 строк (3xC + 1xB) по 25% каждая: объём строки =
    //   round(25/100 * pbas * 1000) = round(963.71...) = 964 мл,
    //   сумма 4*964 = 3856, |3856-3855| = 1 - СТРОГО БОЛЬШЕ старого
    //   однострочного допуска 0.5, но укладывается в 0.5*4 = 2.0 -> должно
    //   пройти. Первая строка программы - H на 100% (round(phv*1000) = 354,
    //   абсолютные 135 В) нужна только чтобы не отвлекать программу отдельной
    //   ошибкой по головам/Б7.4 - сама проверка ниже смотрит на тело.
    pwr_unit = "V";
    loadedProgramPowerUnit = "V";
    columnRecommendationsApplied = false;
    document.getElementById("WProgram1").value =
      "0;50;100.0;H;135\n" +
      "0;50;25.0;C;140\n" +
      "0;50;25.0;C;140\n" +
      "0;50;25.0;C;140\n" +
      "0;50;25.0;B;140";
    calc_program();
    const toleratedBodyClass = document.getElementById("summaryBodyDistribution").className;
    const toleratedProgramErr = programerr;
    const toleratedMsg = programErrorMessage;

    // [настоящая ошибка оператора всё ещё отклоняется] Те же 4 строки тела
    // (3xC + 1xB), но по 10% каждая - round(10/100*pbas*1000) = round(385.48)
    // = 385 мл на строку, сумма 4*385 = 1540 мл против бюджета 3855 мл,
    // |1540-3855| = 2315 - НИКАКИМ допуском на округление (0.5*4=2.0) не
    // объяснить, оператор реально не заполнил бюджет тела. "Записать" обязана
    // отклонить программу с той же меткой "Тело B+C" в тексте ошибки.
    document.getElementById("WProgram1").value =
      "0;50;100.0;H;135\n" +
      "0;50;10.0;C;140\n" +
      "0;50;10.0;C;140\n" +
      "0;50;10.0;C;140\n" +
      "0;50;10.0;B;140";
    calc_program();
    const brokenBodyClass = document.getElementById("summaryBodyDistribution").className;
    const brokenProgramErr = programerr;
    const brokenMsg = programErrorMessage;

    // [В8-UI] Бэкенд сообщает об упоре в предел сечения колонны через
    // headsSpeedClamped/bodySpeedClamped - примечание должно появиться и быть непустым.
    columnParams = Object.assign({}, paramsFor(2), { headsSpeedClamped: true, bodySpeedClamped: false });
    displayColumnParams();
    const clampNote = document.getElementById("colSpeedClampNote");
    const clampShown = !!clampNote && clampNote.style.display === "block";
    const clampText = clampNote ? clampNote.textContent : "";

    // [В8-UI] Оставшиеся варианты примечания: зажато только тело, зажаты оба
    // сразу, и случай "упора нет" - блок обязан скрыться и очистить текст
    // (иначе оператор видел бы устаревшее сообщение после того, как диаметр
    // колонны увеличили и упор снялся).
    columnParams = Object.assign({}, paramsFor(2), { headsSpeedClamped: false, bodySpeedClamped: true });
    displayColumnParams();
    const clampShownBodyOnly = !!clampNote && clampNote.style.display === "block";
    const clampTextBodyOnly = clampNote ? clampNote.textContent : "";

    columnParams = Object.assign({}, paramsFor(2), { headsSpeedClamped: true, bodySpeedClamped: true });
    displayColumnParams();
    const clampShownBoth = !!clampNote && clampNote.style.display === "block";
    const clampTextBoth = clampNote ? clampNote.textContent : "";

    columnParams = Object.assign({}, paramsFor(2), { headsSpeedClamped: false, bodySpeedClamped: false });
    displayColumnParams();
    const clampShownNone = !!clampNote && clampNote.style.display === "block";
    const clampTextNone = clampNote ? clampNote.textContent : "";

    return {
      volumes: volumes,
      scaledHeads: scaledHeads,
      scaledBody: scaledBody,
      scaledTails: scaledTails,
      body15: body15,
      body30: body30,
      applied30: applied30,
      blocked: blocked,
      afterApply: afterApply,
      unitAfter: unitAfter,
      dual: dual.dual,
      dualPNoHeater: dualPNoHeater,
      dualV: dualV,
      dualP: dualP,
      dualDeltaP: dualDeltaP,
      weakHeaterP: weakHeaterP,
      weakHeaterErrorShown: weakHeaterErrorShown,
      weakHeaterErrorText: weakHeaterErrorText,
      powerfulHeaterP: powerfulHeaterP,
      powerfulHeaterErrorShown: powerfulHeaterErrorShown,
      powerfulHeaterErrorText: powerfulHeaterErrorText,
      noAnchorDeltaBody: noAnchorDeltaBody,
      noAnchorDeltaErrorShown: noAnchorDeltaErrorShown,
      noAnchorDeltaErrorText: noAnchorDeltaErrorText,
      dualFits: dualFits,
      dualLoaded: dualLoaded,
      dualBody: dualBody,
      b74Error: b74Error,
      b74SingleRowError: b74SingleRowError,
      toleratedBodyClass: toleratedBodyClass,
      toleratedProgramErr: toleratedProgramErr,
      toleratedMsg: toleratedMsg,
      brokenBodyClass: brokenBodyClass,
      brokenProgramErr: brokenProgramErr,
      brokenMsg: brokenMsg,
      clampShown: clampShown,
      clampText: clampText,
      clampShownBodyOnly: clampShownBodyOnly,
      clampTextBodyOnly: clampTextBodyOnly,
      clampShownBoth: clampShownBoth,
      clampTextBoth: clampTextBoth,
      clampShownNone: clampShownNone,
      clampTextNone: clampTextNone
    };
  });

  if (!result.volumes.length || result.volumes.some(function(row) { return row.type !== "P" && !row.integer; })) {
    throw new Error("WProgram volumes must be integers: " + JSON.stringify(result.volumes));
  }
  if (result.scaledHeads.length !== 2 ||
      Math.abs(result.scaledHeads[0] - 0.1) > 0.001 ||
      Math.abs(result.scaledHeads[1] - 0.05) > 0.001) {
    throw new Error("head profile was flattened or not scaled from unscaled 0.2/0.1: " +
      JSON.stringify(result.scaledHeads));
  }
  if (result.scaledBody.length !== 2 ||
      Math.abs(result.scaledBody[0] - 0.4) > 0.001 ||
      Math.abs(result.scaledBody[1] - 0.2) > 0.001) {
    throw new Error("body profile was flattened or not scaled from unscaled 1.0/0.5: " +
      JSON.stringify(result.scaledBody));
  }
  if (result.scaledTails.length !== 1 || Math.abs(result.scaledTails[0] - 0.15) > 0.001) {
    throw new Error("tails speed not scaled to 0.150: " + JSON.stringify(result.scaledTails));
  }
  if (result.applied30 !== true) {
    throw new Error("recommendations for 3 inch column must be applied with an 8000 W heater");
  }
  const diamRatio = result.body15 / result.body30;
  if (!(Math.abs(diamRatio - 0.25) < 0.02)) {
    throw new Error("1.5/3 inch body speed ratio should be ~0.25, got " +
      JSON.stringify({ body15: result.body15, body30: result.body30, diamRatio: diamRatio }));
  }
  if (result.blocked !== false) {
    throw new Error("volt template must not fit watt regulator before recommendations");
  }
  if (result.afterApply !== true || result.unitAfter !== "P") {
    throw new Error("recommendations must convert program power to watts: " +
      JSON.stringify({ afterApply: result.afterApply, unitAfter: result.unitAfter }));
  }
  if (result.dual !== true || result.dualPNoHeater !== "0;0.200;50;H;1199") {
    throw new Error("6-field program with unknown heater must fall back to file watts: " +
      JSON.stringify({ dual: result.dual, dualPNoHeater: result.dualPNoHeater }));
  }
  if (result.dualV !== "0;0.200;50;H;135" || result.dualP !== "0;0.200;50;H;1823") {
    throw new Error("6-field program with known heater must recompute watts from volts: " +
      JSON.stringify({ dualV: result.dualV, dualP: result.dualP }));
  }
  if (result.dualDeltaP !== "0;0.200;50;H;1000\n0;0.200;50;B;103") {
    throw new Error("delta row must be recomputed around the last absolute setpoint: " +
      JSON.stringify({ dualDeltaP: result.dualDeltaP }));
  }
  if (result.weakHeaterP !== "0;0.200;50;H;9001\n0;0.100;50;H;9002\n4;1.000;50;B;9003") {
    throw new Error("a heater too weak to keep every absolute row absolute in watts must fall back " +
      "to the template's reference watt column for the WHOLE program, unmodified: " +
      JSON.stringify({ weakHeaterP: result.weakHeaterP }));
  }
  if (result.weakHeaterErrorShown !== true || result.weakHeaterErrorText.indexOf("отличается от эталонной") < 0) {
    throw new Error("a heater too weak to recompute the template into watts must show a visible warning: " +
      JSON.stringify({ shown: result.weakHeaterErrorShown, text: result.weakHeaterErrorText }));
  }
  if (result.powerfulHeaterP !== "0;200;0;P;9101\n5;1.1;40;C;9102") {
    throw new Error("a heater too powerful, which would push a delta row's recomputed watts past the " +
      "absolute threshold, must fall back to the template's reference watt column for the WHOLE " +
      "program, unmodified: " + JSON.stringify({ powerfulHeaterP: result.powerfulHeaterP }));
  }
  if (result.powerfulHeaterErrorShown !== true ||
      result.powerfulHeaterErrorText.indexOf("отличается от эталонной") < 0) {
    throw new Error("a heater too powerful to recompute the template into watts must show a visible warning: " +
      JSON.stringify({ shown: result.powerfulHeaterErrorShown, text: result.powerfulHeaterErrorText }));
  }
  if (result.noAnchorDeltaBody !== "0;0.200;50;H;200;200\n") {
    throw new Error("formatDualProgramFile() must still copy the raw value into both columns when there " +
      "is no absolute setpoint above it: " + JSON.stringify({ noAnchorDeltaBody: result.noAnchorDeltaBody }));
  }
  if (result.noAnchorDeltaErrorShown !== true ||
      result.noAnchorDeltaErrorText.indexOf("не совпадает с оригиналом") < 0) {
    throw new Error("a delta below the watt threshold but above the volt threshold, with no absolute " +
      "setpoint above it to anchor a real recompute, must still warn that the other column's meaning " +
      "flipped: " + JSON.stringify({ shown: result.noAnchorDeltaErrorShown, text: result.noAnchorDeltaErrorText }));
  }
  if (result.dualFits !== true || result.dualLoaded !== "P" ||
      !String(result.dualBody).includes("1823")) {
    throw new Error("6-field program must select watts for a watt regulator: " +
      JSON.stringify({
        dualFits: result.dualFits, dualLoaded: result.dualLoaded, dualBody: result.dualBody
      }));
  }
  if (result.b74Error !== true) {
    throw new Error("first program row with a delta setpoint must raise a validation error");
  }
  if (result.b74SingleRowError !== true) {
    throw new Error("a single-row program with a delta setpoint must also raise the Б7.4 validation error");
  }
  if (result.toleratedProgramErr !== false || result.toleratedBodyClass.indexOf("is-valid") < 0) {
    throw new Error("a 4-row body fraction (3xC+1xB) 1 mL off its 3855 mL budget (within 0.5*4=2.0 " +
      "rounding tolerance) must still pass distribution validation: " +
      JSON.stringify({
        err: result.toleratedProgramErr, cls: result.toleratedBodyClass, msg: result.toleratedMsg
      }));
  }
  if (result.brokenProgramErr !== true || result.brokenBodyClass.indexOf("is-invalid") < 0 ||
      result.brokenMsg.indexOf("Тело B+C") < 0) {
    throw new Error("a 4-row body fraction covering only 1540 of 3855 mL (a genuine operator " +
      "mistake, far outside any rounding tolerance) must still be rejected: " +
      JSON.stringify({ err: result.brokenProgramErr, cls: result.brokenBodyClass, msg: result.brokenMsg }));
  }
  if (result.clampShown !== true || !result.clampText) {
    throw new Error("column section-limit clamp note must show non-empty text: " +
      JSON.stringify({ clampShown: result.clampShown, clampText: result.clampText }));
  }
  if (result.clampShownBodyOnly !== true || result.clampTextBodyOnly.indexOf("тела") < 0 ||
      result.clampTextBodyOnly.indexOf("голов") >= 0) {
    throw new Error("body-only clamp note must mention only the body speed: " +
      JSON.stringify({ shown: result.clampShownBodyOnly, text: result.clampTextBodyOnly }));
  }
  if (result.clampShownBoth !== true || result.clampTextBoth.indexOf("голов и тела") < 0) {
    throw new Error("clamp note must mention both heads and body when both are clamped: " +
      JSON.stringify({ shown: result.clampShownBoth, text: result.clampTextBoth }));
  }
  if (result.clampShownNone !== false || result.clampTextNone) {
    throw new Error("clamp note must hide itself and clear its text when nothing is clamped: " +
      JSON.stringify({ shown: result.clampShownNone, text: result.clampTextNone }));
  }
  return result;
}'''


def main() -> int:
    cli = shutil.which("playwright-cli")
    if not cli:
        print("playwright-cli is required for this explicit browser gate", file=sys.stderr)
        return 2

    primary_error = None
    with tempfile.TemporaryDirectory(prefix="samovar-program-calc-") as temp_dir:
        temp = Path(temp_dir)
        site = temp / "site"
        render_site(site)
        handler = functools.partial(QuietHandler, directory=str(site))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        session = f"pc{os.getpid()}"

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
            browser_test = BROWSER_TEST.replace("__BASE_URL__", json.dumps(base_url))
            run_cli(cli, session, ["run-code", browser_test], temp, 60)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            primary_error = str(error)
        finally:
            cleanup_errors = cleanup(cli, session, server, thread)

    if primary_error or cleanup_errors:
        if primary_error:
            print(f"Program calc browser contract failed: {primary_error}", file=sys.stderr)
        for error in cleanup_errors:
            print(f"Program calc browser cleanup failed: {error}", file=sys.stderr)
        return 1

    print("Program calc browser contract passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
