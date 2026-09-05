#!/usr/bin/env python3
"""Browser contract for versioned beer program backup import/export."""

import functools
import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

from test_accessibility_ui_browser import QuietHandler, render_site, run_cli

ROOT = Path(__file__).resolve().parents[1]

BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  const telemetry = {
    version:"test",crnt_tm:"12:00:00",stm:"00:01:00",
    SteamTemp:78.1,PipeTemp:77.9,WaterTemp:20.2,TankTemp:82.3,ACPTemp:40.1,
    bme_pressure:760,start_pressure:759.5,prvl:1.2,VolumeAll:0,
    ActualVolumePerHour:0,WthdrwlProgress:0,CurrrentSpeed:0,CurrrentStepps:0,
    TargetStepps:0,WthdrwlStatus:0,ProgramNum:0,DetectorTrend:0,
    DetectorStatus:0,useautospeed:false,current_power_volt:0,target_power_volt:0,
    current_power_mode:"0",current_power_p:0,WFtotalMl:0,WFflowRate:0,
    bme_temp:24,heap:200000,rssi:-50,fr_bt:300000,UseBBuzzer:false,
    PauseOn:0,BeerManualPause:0,PrgType:"",Status:"Готов",Lstatus:"",
    TimeRemaining:0,TotalTime:0,alc:0,stm_alc:0,ISspd:0,wp_spd:0,
    i2c_pump_present:0,i2c_pump_running:0,i2c_pump_remaining_ml:0,
    i2c_pump_speed:0,PowerOn:0,heaterAlarmLatched:0,heaterAlarmReason:'',
    latestMessageSequence:0
  };
  const consoleProblems = [];
  page.on("console", message => {
    if (message.type() === "warning" || message.type() === "error")
      consoleProblems.push(message.type() + ": " + message.text());
  });
  page.on("pageerror", error => consoleProblems.push("pageerror: " + error.message));
  await page.route("**/ajax*", route => route.fulfill({
    status:200, contentType:"application/json", body:JSON.stringify(telemetry)
  }));
  function expect(value, message) { if (!value) throw new Error(message); }

  await page.goto(baseUrl + "/beer.htm", {waitUntil:"load"});
  await page.waitForFunction(() => document.getElementById("prg").children.length > 0);
  await page.evaluate(() => {
    window.__backupNotifications = [];
    window.__backupDownloads = [];
    const originalNotify = SamovarApp.notify;
    SamovarApp.notify = function(message, level) {
      window.__backupNotifications.push({message:String(message), level:level});
      return originalNotify.apply(this, arguments);
    };
    HTMLAnchorElement.prototype.click = function() {
      window.__backupDownloads.push({href:this.href, download:this.download});
    };
  });

  const program = "P;60.00;1;0^0^0^0;0\nW;0.00;0;1^1^1^1;0\n";
  const description250 = "я".repeat(125);
  await page.evaluate(({program, description}) => {
    document.getElementById("WProgram").value = program;
    document.getElementById("Descr").value = description;
    SaveProgramToFile();
  }, {program, description:description250});
  const exported = await page.evaluate(() => window.__backupDownloads[0]);
  expect(exported && exported.download === "programbackup.txt", "backup download was not created");
  const payload = JSON.parse(decodeURIComponent(exported.href.split(",", 2)[1]));
  expect(JSON.stringify(Object.keys(payload)) === JSON.stringify(["version", "program", "description"]),
         "backup JSON has unexpected fields: " + JSON.stringify(payload));
  expect(payload.version === 1 && payload.program === program && payload.description === description250,
         "backup JSON did not preserve program and 250-byte description");

  await page.evaluate(() => {
    document.getElementById("Descr").value = "я".repeat(126);
    SaveProgramToFile();
  });
  const overlongExport = await page.evaluate(() => ({
    downloads:window.__backupDownloads.length,
    last:window.__backupNotifications.at(-1)
  }));
  expect(overlongExport.downloads === 1, "overlong description was exported");
  expect(overlongExport.last.message.includes("описание длиннее 250 байт"),
         "overlong export did not show the byte-limit error");

  const input = page.locator("#fileToLoad");
  const importedProgram = "M;45.00;0;0^0^0^0;0\n";
  await input.setInputFiles(__STRUCTURED_PATH__);
  await page.waitForFunction(({program, description}) =>
    document.getElementById("WProgram").value === program &&
    document.getElementById("Descr").value === description,
    {program:importedProgram, description:description250});

  await page.evaluate(() => {
    document.getElementById("WProgram").value = "P;55;2;0^0^0^0;0\n";
    document.getElementById("Descr").value = "не менять";
  });
  await input.setInputFiles(__BROKEN_PATH__);
  await page.waitForFunction(() =>
    window.__backupNotifications.at(-1).message.includes("повреждён JSON"));
  const afterBroken = await page.evaluate(() => ({
    program:document.getElementById("WProgram").value,
    description:document.getElementById("Descr").value
  }));
  expect(afterBroken.program === "P;55;2;0^0^0^0;0\n" && afterBroken.description === "не менять",
         "malformed JSON fell back to plain text or changed description");

  await input.setInputFiles(__UNSUPPORTED_PATH__);
  await page.waitForFunction(() =>
    window.__backupNotifications.at(-1).message.includes("неподдерживаемый формат"));
  const afterUnsupported = await page.evaluate(() => ({
    program:document.getElementById("WProgram").value,
    description:document.getElementById("Descr").value
  }));
  expect(JSON.stringify(afterUnsupported) === JSON.stringify(afterBroken),
         "unsupported backup version changed the form");

  await input.setInputFiles(__TOO_LONG_PATH__);
  await page.waitForFunction(() =>
    window.__backupNotifications.at(-1).message.includes("описание длиннее 250 байт"));
  const afterTooLong = await page.evaluate(() => ({
    program:document.getElementById("WProgram").value,
    description:document.getElementById("Descr").value
  }));
  expect(JSON.stringify(afterTooLong) === JSON.stringify(afterBroken),
         "overlong imported description changed the form");

  const legacyProgram = "B;0.00;1;0^0^0^0;0\n";
  await input.setInputFiles(__LEGACY_PATH__);
  await page.waitForFunction(programText =>
    document.getElementById("WProgram").value === programText, legacyProgram);
  const legacyDescription = await page.locator("#Descr").inputValue();
  expect(legacyDescription === "не менять", "legacy import unexpectedly cleared description");
  expect(consoleProblems.length === 0,
         "unexpected console warnings/errors: " + consoleProblems.join("; "));
  return "ok";
}'''


def main() -> int:
    cli = shutil.which("playwright-cli")
    if not cli:
        print("playwright-cli is required for the beer backup browser gate", file=sys.stderr)
        return 1

    error = None
    cleanup_errors = []
    with tempfile.TemporaryDirectory(prefix="samovar-beer-backup-ui-") as temp_dir:
        temp = Path(temp_dir)
        site = temp / "site"
        render_site(site)
        imported_program = "M;45.00;0;0^0^0^0;0\n"
        fixtures = {
            "__STRUCTURED_PATH__": temp / "structured.txt",
            "__BROKEN_PATH__": temp / "broken.txt",
            "__UNSUPPORTED_PATH__": temp / "unsupported.txt",
            "__TOO_LONG_PATH__": temp / "too-long.txt",
            "__LEGACY_PATH__": temp / "legacy.txt",
        }
        fixtures["__STRUCTURED_PATH__"].write_text(
            json.dumps({
                "version": 1,
                "program": imported_program,
                "description": "я" * 125,
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        fixtures["__BROKEN_PATH__"].write_text("  {broken", encoding="utf-8")
        fixtures["__UNSUPPORTED_PATH__"].write_text(
            json.dumps({
                "version": 2,
                "program": imported_program,
                "description": "новая версия",
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        fixtures["__TOO_LONG_PATH__"].write_text(
            json.dumps({
                "version": 1,
                "program": imported_program,
                "description": "я" * 126,
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        fixtures["__LEGACY_PATH__"].write_text(
            "B;0.00;1;0^0^0^0;0\n", encoding="utf-8",
        )
        handler = functools.partial(QuietHandler, directory=str(site))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        session = f"samovar-beer-backup-ui-{os.getpid()}"
        opened = False
        try:
            config = temp / "playwright.json"
            config.write_text(
                json.dumps({
                    "browser": {
                        "browserName": "chromium",
                        "launchOptions": {"chromiumSandbox": False},
                    }
                }),
                encoding="utf-8",
            )
            run_cli(cli, session, ["open", f"--config={config}"], temp, 30)
            opened = True
            code = BROWSER_TEST.replace(
                "__BASE_URL__", json.dumps(f"http://127.0.0.1:{server.server_port}"),
            )
            for marker, path in fixtures.items():
                code = code.replace(marker, json.dumps(str(path)))
            run_cli(cli, session, ["run-code", code], temp, 60)
        except (OSError, RuntimeError) as caught:
            error = str(caught)
        finally:
            if opened:
                try:
                    if run_cli(cli, session, ["close"], temp, 30, check=False) != 0:
                        cleanup_errors.append("playwright-cli close failed")
                except OSError as caught:
                    cleanup_errors.append(str(caught))
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    if error or cleanup_errors:
        if error:
            print(f"beer backup browser gate failed: {error}", file=sys.stderr)
        for cleanup_error in cleanup_errors:
            print(f"browser cleanup failed: {cleanup_error}", file=sys.stderr)
        return 1
    print("beer backup browser gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
