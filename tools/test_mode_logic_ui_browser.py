#!/usr/bin/env python3
"""Browser contract for mode-logic telemetry and controls."""

import functools
import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

from test_accessibility_ui_browser import (
    QuietHandler,
    render_site,
    run_cli,
    run_cli_report,
)
from test_numeric_input_ui_browser import UI_BOOTSTRAP_FIXTURE

ROOT = Path(__file__).resolve().parents[1]

BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  const telemetry = {
    version:"test",crnt_tm:"12:00:00",stm:"00:01:00",
    SteamTemp:78.1,PipeTemp:77.9,WaterTemp:20.2,TankTemp:82.3,ACPTemp:40.1,
    bme_pressure:760,start_pressure:759.5,prvl:1.2,VolumeAll:0,
    ActualVolumePerHour:0,WthdrwlProgress:0,CurrrentSpeed:0,CurrrentStepps:0,
    TargetStepps:0,WthdrwlStatus:0,ProgramNum:0,DetectorTrend:0.012,
    DetectorStatus:2,useDetector:true,useautospeed:true,
    BoilingEvidence:2,BoilingPrecisionSensorConfigured:1,
    current_power_volt:220,target_power_volt:220,current_power_mode:"WORK",
    current_power_p:2000,WFtotalMl:10,WFflowRate:2,bme_temp:24,heap:200000,
    rssi:-50,fr_bt:300000,UseBBuzzer:false,PauseOn:0,PrgType:"L",Status:"Работа",
    Lstatus:"",TimeRemaining:12,RowTotalTime:22,ProcessTimeRemaining:32,
    TotalTime:42,RowPredictionAvailable:1,ProcessPredictionAvailable:1,
    RowPredictionReason:2,ProcessPredictionReason:2,alc:50,stm_alc:70,ISspd:0,
    wp_spd:0,i2c_pump_present:0,i2c_pump_running:0,i2c_pump_remaining_ml:0,
    i2c_pump_speed:0,PowerOn:1,StepperStepMl:100,
    heaterAlarmLatched:0,heaterAlarmReason:'',latestMessageSequence:0,
    BeerBrewOrder:"allinone"
  };
  const i2cStepper = {
    present: 1, address: 2, everPresent: 1, capabilities: 30,
    config: { address: 2, mode: 3, optionFlags: 0, sensorFlags: 0, relayMask: 0,
      mixerRpm: 0, mixerRunSec: 0, mixerPauseSec: 0, pumpMlHour: 100,
      pumpPauseSec: 0, fillingMl: 100, fillingMlHour: 100, stepsPerMl: 100 },
    motion: { mode: 0, direction: 0, speedStepsPerSec: 100, targetSteps: 1000 },
    status: { mode: 3, flags: 0, result: 0, error: 0, stopReason: 0, generation: 1,
      currentSpeedStepsPerSec: 0, remainingSteps: 0 }
  };
  const i2cStepperResponse = { selected: i2cStepper, devices: [i2cStepper] };
  const failures = [];
  const consoleProblems = [];
  const beerProgramPosts = [];
  page.on("console", message => {
    if (message.type() === "warning" || message.type() === "error")
      consoleProblems.push(message.type() + ": " + message.text());
  });
  page.on("pageerror", error => consoleProblems.push("pageerror: " + error.message));
  await page.addInitScript(() => {
    window.Audio = function() {
      this.play = () => Promise.resolve(); this.pause = () => {};
    };
    window.__confirmMessages = [];
    window.confirm = function (message) {
      window.__confirmMessages.push(message);
      return false;
    };
  });
  await page.route("**/ajax*", route => {
    const operationMatch = route.request().url().match(/[?&]operationId=([^&]+)/);
    const operationId = operationMatch && Number(decodeURIComponent(operationMatch[1]));
    let body;
    if (operationId === null) {
      body = {...telemetry};
    } else {
      body = {operationId:operationId,state:"succeeded",error:"none"};
    }
    return route.fulfill({status:200,contentType:"application/json",body:JSON.stringify(body)});
  });
  await page.route("**/i2cstepper?address=2", route => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify(i2cStepperResponse)
  }));
  await page.route("**/program", route => {
    const request = route.request();
    if (request.method() === "POST") beerProgramPosts.push(request.postData() || "");
    return route.fulfill({
      status:202,
      contentType:"application/json",
      body:JSON.stringify({
        ok:true,err:"",program:"W;0;0;0^0^0^0^0;4",
        operationId:41,state:"queued",error:"none"
      })
    });
  });
  const commandPosts = [];
  await page.route("**/command", route => {
    const request = route.request();
    if (request.method() === "POST") commandPosts.push(request.postData() || "");
    return route.fulfill({status:200,contentType:"text/plain",body:"OK"});
  });
  function expect(value, message) { if (!value) failures.push(message); }
  // П46: на bk/distiller/nbk надпись кнопки решает не только текст подтверждения,
  // но и само значение (0/1) команды. Портим ТОЛЬКО надпись (как будто страница не
  // успела обновиться) при реальном PowerOn=1 и проверяем, что и подтверждение,
  // и отправленная команда следуют реальному состоянию, а не разметке.
  async function checkPowerStaleLabel(cmdPrefix, pageLabel) {
    await page.evaluate(() => {
      window.__confirmMessages.length = 0;
      window.confirm = function (message) {
        window.__confirmMessages.push(message);
        return true;
      };
      document.getElementById("power").value = "Включить нагрев";
    });
    const before = commandPosts.length;
    await page.locator("#power").click();
    const confirms = await page.evaluate(() => window.__confirmMessages.slice());
    expect(confirms.length === 1 && confirms[0] === "Выключить нагрев?",
           pageLabel + " power button skipped/changed the confirm when the label was stale " +
           "(decision must follow real PowerOn state, not markup text)");
    expect(commandPosts.length === before + 1 &&
           commandPosts[commandPosts.length - 1] === cmdPrefix + "0",
           pageLabel + " power button sent the wrong command value for a stale label " +
           "(command must follow real PowerOn state, not markup text)");
  }
  for (const viewport of [{width:390,height:844},{width:1440,height:900}]) {
    await page.setViewportSize(viewport);
    for (const theme of ["light","dark"]) {
      await page.goto(baseUrl + "/app.js");
      await page.evaluate(value => localStorage.setItem("theme", value), theme);

      await page.goto(baseUrl + "/index.htm", {waitUntil:"load"});
      await page.waitForFunction(() =>
        document.getElementById("detector_status_text").textContent.includes("ПРОСКОК")
      );
      expect((await page.locator("#detector_trend").textContent()).includes("0.012"),
             "index detector trend is not rendered");
      expect(await page.locator("#detector_steam_stability").count() === 0,
             "index must not show steam-stability debug dump on the main screen");

      // Подробности стабилизации пара (DetectorSteam*/DetectorRecovery*) прошивка
      // больше не отдаёт - их никто не читал. Основная телеметрия и тренд обязаны
      // рисоваться без них, поэтому фикстура их не содержит вовсе.
      expect((await page.locator("#SteamTemp").textContent()).trim() === "78.1",
             "core telemetry is not rendered without detector stability fields");
      const rowDelta = await page.evaluate(sample => {
        document.getElementById("WProgram").value = "H;106;0.07;0;0;135";
        SamovarApp.renderScheme({...sample, ProgramNum:1});
        const field = document.querySelector(".sec-program [data-tele='_delta']");
        const valueBox = field.parentElement.getBoundingClientRect();
        const cardBox = document.querySelector(".sec-program .line-card").getBoundingClientRect();
        return {label:field.parentElement.previousElementSibling.textContent.trim(),
                value:field.textContent.trim(),
                fits:valueBox.right <= cardBox.right && valueBox.bottom <= cardBox.bottom};
      }, telemetry);
      expect(rowDelta.label === "Дельта" && rowDelta.value === "-0.20",
             "rectification row must show sensor delta instead of unused program temperature");
      expect(rowDelta.fits, "rectification row delta must fit inside the program card");
      const changedDelta = await page.evaluate(sample => {
        SamovarApp.renderScheme({...sample, SteamTemp:77.3, PipeTemp:78.1, ProgramNum:1});
        return document.querySelector(".sec-program [data-tele='_delta']").textContent.trim();
      }, telemetry);
      expect(changedDelta === "+0.80", "rectification row delta must follow changed sensor readings");

      // П46: PowerOn=1 -> реальное состояние "нагрев включён". Портим ТОЛЬКО
      // надпись на кнопке (как будто страница не успела обновиться) и проверяем,
      // что решение "спрашивать подтверждение выключения" всё равно принимается
      // по реальному состоянию, а не по надписи в разметке.
      await page.evaluate(() => {
        document.getElementById("power").value = "Включить нагрев";
        window.__confirmMessages.length = 0;
      });
      await page.locator("#power").click();
      const indexConfirms = await page.evaluate(() => window.__confirmMessages.slice());
      expect(indexConfirms.length === 1 && indexConfirms[0] === "Выключить нагрев?",
             "index power button skipped/changed the confirm when the label was stale " +
             "(decision must follow real PowerOn state, not markup text)");

      await page.goto(baseUrl + "/distiller.htm", {waitUntil:"load"});
      await page.waitForFunction(() =>
        document.getElementById("TimeRemaining").textContent !== "--"
      );
      expect((await page.locator("#TimeRemaining").textContent()).trim() === "12",
             "row remaining forecast missing");
      expect((await page.locator("#ProcessTimeRemaining").textContent()).trim() === "32",
             "process remaining forecast missing");
      await checkPowerStaleLabel("distiller=", "distiller");

      await page.goto(baseUrl + "/bk.htm", {waitUntil:"load"});
      await page.waitForFunction(() =>
        document.getElementById("boiling_evidence").textContent.includes("царга")
      );
      const boiling = page.locator("#boiling_evidence");
      expect((await boiling.textContent()).includes("царга"),
             "BK boiling evidence missing");
      expect(await boiling.getAttribute("data-precision") === "precise",
             "BK precise evidence is not marked");
      await checkPowerStaleLabel("startbk=", "BK");

      await page.goto(baseUrl + "/nbk.htm", {waitUntil:"load"});
      await page.waitForFunction(() =>
        document.getElementById("Status").textContent === "Работа"
      );
      await checkPowerStaleLabel("startnbk=", "NBK");

      await page.goto(baseUrl + "/beer.htm", {waitUntil:"load"});
      await page.waitForFunction(() => !document.body.inert);
      expect(await page.evaluate(() => !beerMixerStepperAvailable && beerPumpStepperAvailable),
             "Beer did not recognize a single pump-mode I2CStepper");
      expect(await page.locator("#BeerBrewOrder").count() === 0,
             "brew order must not be chosen on beer.htm (settings only)");
      expect((await page.locator("body").textContent()).includes(
               "Вход ждёт подтверждённый запуск Lua-job"),
             "Beer Lua-stage safety explanation missing");
      const beerPostCount = beerProgramPosts.length;
      const beerW = await page.evaluate(async () => {
        const valid = "W;0;0;0^0^0^0^0;4";
        const invalid = "W;0;0;0^0^0^0^0;5";
        document.getElementById("WProgram").value = valid;
        await set_program();
        return {
          accepted:check_program(valid),
          rejected:!check_program(invalid),
          saved:document.getElementById("WProgram").value
        };
      });
      expect(beerW.accepted,
             "Beer W row with sensor 4 is rejected by UI validation");
      expect(beerW.rejected,
             "Beer W row with out-of-range sensor 5 is accepted by UI validation");
      expect(beerW.saved === "W;0;0;0^0^0^0^0;4",
             "Beer W row with sensor 4 changed before save");
      const beerWPost = beerProgramPosts[beerProgramPosts.length - 1] || "";
      expect(beerProgramPosts.length === beerPostCount + 1 && beerWPost.includes("W;0;0;0^0^0^0^0;4"),
             "Beer W row with sensor 4 was not sent to /program");

      // Жалоба с форума 17.09.2026: после смены типа строки на «Пауза» текст программы
      // становился неверным (время ещё 0), и calc_program() отказывалась переносить
      // в него дальнейшие правки полей - программа не устанавливалась без причины.
      const beerRowSync = await page.evaluate(() => {
        document.getElementById("WProgram").value = "W;0;0;0^0^0^0^0;1";
        document.getElementById("WProgram").dispatchEvent(new Event("change"));
        const row = document.getElementsByClassName("prgline")[1].childNodes;
        row[1].value = "P"; row[1].dispatchEvent(new Event("change"));
        row[2].value = "61.00"; row[2].dispatchEvent(new Event("change"));
        const broken = document.getElementById("WProgram").value;
        row[3].value = "20.00"; row[3].dispatchEvent(new Event("change"));
        return {
          broken:broken,
          text:document.getElementById("WProgram").value,
          reason:program_error("P;61.00;0.00;0^0^0^0^0;1"),
          fermentTimed:check_program("F;18;4320;0^0^0^0^0;0") && check_program("F;18;0;0^0^0^0^0;0"),
          fermentTooLong:program_error("F;18;43201;0^0^0^0^0;0"),
          relayPump:check_program("W;0;0;3^100^0^30^10;0"),
          relayMixer:check_program("W;0;0;3^0^1200^30^10;0"),
          bothRelays:check_program("W;0;0;3^0^0^30^10;0"),
          negativePump:program_error("W;0;0;2^0^-1^30^10;0")
        };
      });
      expect(beerRowSync.text.split("\n")[0].startsWith("P;61.00;20.00;"),
             "Beer row fields were not copied into program text after a temporarily invalid row: " +
             JSON.stringify(beerRowSync));
      expect(beerRowSync.reason.includes("Строка 1") && beerRowSync.reason.includes("Пауза"),
             "Beer program error does not name the row and the reason: " + beerRowSync.reason);
      expect(beerRowSync.fermentTimed, "Beer F row must accept time 0 and time > 0");
      expect(beerRowSync.fermentTooLong.includes("43200"),
             "Beer F row longer than 30 days must be rejected with the limit named");
      expect(beerRowSync.relayPump && beerRowSync.negativePump.includes("Строка 1"),
             "Beer relay pump program validation disagrees with firmware");
      expect(beerRowSync.relayMixer && beerRowSync.bothRelays,
             "Beer relay mixer program validation disagrees with firmware");

      // П46: та же проверка реального состояния для кнопки нагрева на beer.htm.
      await page.evaluate(() => {
        document.getElementById("power").value = "Включить нагрев";
        window.__confirmMessages.length = 0;
      });
      await page.locator("#power").click();
      const beerConfirms = await page.evaluate(() => window.__confirmMessages.slice());
      expect(beerConfirms.length === 1 && beerConfirms[0] === "Выключить нагрев?",
             "beer power button skipped/changed the confirm when the label was stale " +
             "(decision must follow real PowerOn state, not markup text)");

      // П54: время мешалки свыше предела прошивки (uint16_t Volume/Power в
      // program_io.h program_parse_beer_device, 0..65535 сек) не должно молча
      // превращаться в 0 - поле обязано остаться в допустимых границах, а предел
      // должен быть виден пользователю в подсказке до ввода.
      const mixerCheck = await page.evaluate(() => {
        const el = document.getElementById("m_time");
        el.value = "70000";
        SamovarApp.normalizeDeviceScheduleSeconds(el);
        return { clamped: el.value, maxConst: SamovarApp.deviceScheduleMaxSeconds };
      });
      expect(mixerCheck.maxConst === 65535,
             "beer mixer max seconds does not match the firmware uint16_t bound (program_io.h)");
      expect(mixerCheck.clamped === "65535",
             "beer mixer time above the firmware limit did not clamp to the real max " +
             "(silent zeroing / data loss regression)");
      const mixerTooltip = await page.locator('label[for="m_time"] .tooltiptext').textContent();
      expect(mixerTooltip.includes("65535"),
             "beer mixer tooltip does not show the real firmware limit before input");

      const deviceEditor = await page.evaluate(() => {
        const input = document.createElement("input");
        input.value = "3^-100^1200^30^10";
        const opened = SamovarApp.openDeviceScheduleModal(input, null, true, true);
        const loaded = ["m_type", "m_mixer_rpm", "m_pump_rate", "m_time", "m_pause"]
          .map(id => document.getElementById(id).value);
        const saved = SamovarApp.saveDeviceScheduleModal();
        const bothRelaysInput = document.createElement("input");
        bothRelaysInput.value = "3^0^0^30^10";
        const bothRelaysOpened = SamovarApp.openDeviceScheduleModal(bothRelaysInput, null, true, true);
        const mixerLabel = document.querySelector('label[for="m_mixer_rpm"]');
        const modal = document.querySelector('.popup__content').getBoundingClientRect();
        const mixerLabelFits = mixerLabel.getBoundingClientRect().right <= modal.right;
        const bothRelaysSaved = SamovarApp.saveDeviceScheduleModal();
        const noStepperInput = document.createElement("input");
        noStepperInput.value = "1^0^0^30^10";
        const noStepperOpened = SamovarApp.openDeviceScheduleModal(noStepperInput, null, false, false);
        const noStepperRelay = document.getElementById("m_mixer_relay").textContent ===
          "Мешалка: реле 2 ESP32" && !document.getElementById("m_mixer_relay").hidden;
        const noStepperSaved = SamovarApp.saveDeviceScheduleModal();
        const oldInput = document.createElement("input");
        oldInput.value = "1^-1^30^60";
        const oldOpened = SamovarApp.openDeviceScheduleModal(oldInput, null, true, true);
        const relayInput = document.createElement("input");
        relayInput.value = "3^-100^1200^30^10";
        const relayOpened = SamovarApp.openDeviceScheduleModal(relayInput, null, true, false);
        const relayOnly = document.getElementById("m_pump_rate").parentElement.hidden &&
          !document.getElementById("m_pump_relay").hidden;
        const relayNote = document.getElementById("m_pump_relay").textContent;
        const relaySaved = SamovarApp.saveDeviceScheduleModal();
        const pumpBoardInput = document.createElement("input");
        pumpBoardInput.value = "3^-100^0^30^10";
        const pumpBoardOpened = SamovarApp.openDeviceScheduleModal(pumpBoardInput, null, false, true);
        const mixerRelay = document.getElementById("m_mixer_rpm").parentElement.hidden &&
          !document.getElementById("m_mixer_relay").hidden;
        const pumpRateVisible = !document.getElementById("m_pump_rate").parentElement.hidden &&
          document.getElementById("m_pump_text").textContent === "Насос, мл/ч";
        const mixerRelayNote = document.getElementById("m_mixer_relay").textContent;
        document.getElementById("m_pump_rate").value = "1200";
        const pumpBoardSaved = SamovarApp.saveDeviceScheduleModal();
        return {opened, loaded, saved, value:input.value, bothRelaysOpened, mixerLabelFits,
          bothRelaysSaved, bothRelaysValue:bothRelaysInput.value,
          noStepperOpened, noStepperRelay, noStepperSaved,
          noStepperValue:noStepperInput.value, oldOpened,
          relayOpened, relayOnly, relayNote, relaySaved, relayValue:relayInput.value,
          pumpBoardOpened, mixerRelay, pumpRateVisible, mixerRelayNote,
          pumpBoardSaved, pumpBoardValue:pumpBoardInput.value};
      });
      expect(deviceEditor.opened && deviceEditor.saved &&
             JSON.stringify(deviceEditor.loaded) === JSON.stringify(["3", "-100", "1200", "30", "10"]) &&
             deviceEditor.value === "3^-100^1200^30^10",
             "beer device editor did not preserve independent mixer/pump speeds: " + JSON.stringify(deviceEditor));
      expect(deviceEditor.bothRelaysOpened && deviceEditor.mixerLabelFits &&
             deviceEditor.bothRelaysSaved &&
             deviceEditor.bothRelaysValue === "3^0^0^30^10",
             "Beer editor did not allow the ESP32 mixer relay with the I2C pump relay");
      expect(deviceEditor.noStepperOpened && deviceEditor.noStepperRelay &&
             deviceEditor.noStepperSaved && deviceEditor.noStepperValue === "1^0^0^30^10",
             "Beer editor did not allow the ESP32 mixer relay without I2CStepper");
      expect(deviceEditor.oldOpened === false,
             "beer device editor still accepted the removed four-part format");
      expect(deviceEditor.relayOpened && deviceEditor.relayOnly &&
             deviceEditor.relayNote === "Насос: реле 1 I2CStepper" && deviceEditor.relaySaved &&
             deviceEditor.relayValue === "3^-100^0^30^10",
             "one I2CStepper did not offer relay 1 only: " + JSON.stringify(deviceEditor));
      expect(deviceEditor.pumpBoardOpened && deviceEditor.mixerRelay &&
             deviceEditor.pumpRateVisible && deviceEditor.mixerRelayNote === "Мешалка: реле 2 ESP32" &&
             deviceEditor.pumpBoardSaved && deviceEditor.pumpBoardValue === "3^0^1200^30^10",
             "pump-mode I2CStepper did not use relay mixer and stepper pump: " + JSON.stringify(deviceEditor));

      await page.locator("[id^=pmixer]").first().dispatchEvent("focus");
      const pumpModeEditor = await page.evaluate(() => ({
        open:document.getElementById("popup").style.display,
        mixerRelay:!document.getElementById("m_mixer_relay").hidden,
        pumpRate:!document.getElementById("m_pump_rate").parentElement.hidden,
        mixerBoard:beerMixerStepperAvailable,pumpBoard:beerPumpStepperAvailable
      }));
      expect(pumpModeEditor.open === "block" && pumpModeEditor.mixerRelay &&
             pumpModeEditor.pumpRate,
             "Beer program row did not open the pump-mode editor: " + JSON.stringify(pumpModeEditor));
      await page.evaluate(() => SamovarApp.closeDeviceScheduleModal());

      await page.route("**/ui-bootstrap", route => route.fulfill({
        status:200,contentType:"application/json",body:JSON.stringify(__BOTH_I2C_BOOTSTRAP__)
      }));
      await page.reload({waitUntil:"load"});
      await page.waitForFunction(() => !document.body.inert);
      expect(await page.evaluate(() => beerMixerStepperAvailable && beerPumpStepperAvailable),
             "Beer did not offer both stepper drives when both I2C devices were present");
      await page.unroute("**/ui-bootstrap");

      await page.goto(baseUrl + "/setup.htm", {waitUntil:"load"});
      expect(await page.locator("#BeerBrewOrder").count() === 1,
             "brew order profile must be on setup.htm tab Пиво");
      expect(await page.locator("#SuvidTemp").count() === 0 &&
             await page.locator("#SuvidHoldMinutes").count() === 0,
             "Suvid controls must not be on setup.htm");
      expect(await page.locator('#mode option[value="5"]').count() === 0,
             "setup must not contain a Su-vid mode option, including hidden options");
      expect(await page.locator('#mode option[value="6"]').count() === 0,
             "setup must not contain a Lua mode option, including hidden options");
      const overflow = await page.evaluate(() =>
        document.documentElement.scrollWidth - document.documentElement.clientWidth
      );
      expect(overflow <= 1, "setup horizontal overflow " + overflow);
    }
  }
  expect(consoleProblems.length === 0, consoleProblems.join("\n"));
  return "__U05_RESULT__" + JSON.stringify({failures,consoleProblems});
}'''


def main() -> int:
    cli = shutil.which("playwright-cli")
    if not cli:
        print("playwright-cli is required for the mode logic browser gate", file=sys.stderr)
        return 1

    error = None
    cleanup_errors = []
    report = {}
    with tempfile.TemporaryDirectory(prefix="samovar-mode-ui-") as temp_dir:
        temp = Path(temp_dir)
        site = temp / "site"
        render_site(site)
        handler = functools.partial(QuietHandler, directory=str(site))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        session = f"samovar-mode-logic-ui-{os.getpid()}"
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
                "__BASE_URL__",
                json.dumps(f"http://127.0.0.1:{server.server_port}"),
            )
            both_devices = [
                {"address": 1, "present": True},
                {"address": 2, "present": True},
                *({} for _ in range(8)),
            ]
            code = code.replace(
                "__BOTH_I2C_BOOTSTRAP__",
                json.dumps({**UI_BOOTSTRAP_FIXTURE, "i2cSteppers": both_devices}),
            )
            report = run_cli_report(cli, session, code, temp, 120)
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

    failures = [str(item) for item in report.get("failures", [])]
    if failures and error is None:
        error = f"{len(failures)} assertions failed; first: {failures[0]}"
    if error or cleanup_errors:
        if error:
            print(f"mode logic UI browser gate failed: {error}", file=sys.stderr)
        for cleanup_error in cleanup_errors:
            print(f"browser cleanup failed: {cleanup_error}", file=sys.stderr)
        return 1
    print("mode logic UI browser gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
