#!/usr/bin/env python3
"""Браузерная проверка калькулятора ректификации (program.htm):

1. Объёмы в WProgram уходят целыми мл (прошивка parse_bounded_long).
2. «Применить рекомендации» масштабирует профиль скоростей, а не плющит
   все строки одного типа в одну скорость.
3. Смена диаметра 1.5 / 2 / 3 пересчитывает отбор пропорционально площади.
4. Файл с одним полем мощности — вольты; на ваттовый регулятор его нельзя
   поставить, пока не пересчитаны рекомендации. Два поля мощности — вольты
   и ватты, под регулятор берётся нужная колонка.
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
        tailsPowerW: 2000 * k
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
        tailsPowerW: 2000 * k
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
    columnParams = paramsFor(3);
    applyRecommendedSpeeds({ silent: true });
    const body30 = Math.max.apply(null, speedsByType("BC"));

    columnRecommendationsApplied = false;
    loadedProgramPowerUnit = "V";
    pwr_unit = "P";
    const blocked = programPowerUnitFitsRegulator();
    applyRecommendedSpeeds({ silent: true });
    const afterApply = programPowerUnitFitsRegulator();
    const unitAfter = loadedProgramPowerUnit;

    const dual = parseProgramFileText("0;0.200;50;H;135;1199");
    const dualV = programBodyForUnit(dual, "V");
    const dualP = programBodyForUnit(dual, "P");
    pwr_unit = "P";
    columnRecommendationsApplied = false;
    applyParsedProgramText(dual);
    const dualFits = programPowerUnitFitsRegulator();
    const dualLoaded = loadedProgramPowerUnit;
    const dualBody = document.getElementById("WProgram1").value;

    return {
      volumes: volumes,
      scaledHeads: scaledHeads,
      scaledBody: scaledBody,
      scaledTails: scaledTails,
      body15: body15,
      body30: body30,
      blocked: blocked,
      afterApply: afterApply,
      unitAfter: unitAfter,
      dual: dual.dual,
      dualV: dualV,
      dualP: dualP,
      dualFits: dualFits,
      dualLoaded: dualLoaded,
      dualBody: dualBody
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
  if (result.dual !== true || result.dualV !== "0;0.200;50;H;135" ||
      result.dualP !== "0;0.200;50;H;1199") {
    throw new Error("6-field program must expose both unit columns: " +
      JSON.stringify({ dual: result.dual, dualV: result.dualV, dualP: result.dualP }));
  }
  if (result.dualFits !== true || result.dualLoaded !== "P" ||
      !String(result.dualBody).includes("1199")) {
    throw new Error("6-field program must select watts for a watt regulator: " +
      JSON.stringify({
        dualFits: result.dualFits, dualLoaded: result.dualLoaded, dualBody: result.dualBody
      }));
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
