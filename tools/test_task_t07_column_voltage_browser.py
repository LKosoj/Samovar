#!/usr/bin/env python3
"""Браузерный контракт T07: рекомендации в вольтах не доходят до клампа 230 В."""
import functools
import contextlib
import http.server
import io
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


BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  await page.goto(baseUrl + "/program.htm", { waitUntil: "load" });
  await page.waitForTimeout(400);

  const result = await page.evaluate(() => {
    const rows = ["0;50;0;H;1", "0;50;0;C;1", "0;50;0;B;1", "0;50;0;T;1"];
    function values() {
      return Array.from(document.querySelectorAll('#prg input[name^="pvolt"]')).map(input => input.value);
    }
    function types() {
      return Array.from(document.querySelectorAll('#prg select[name^="ptype"]')).map(select => select.value);
    }
    function snapshot() {
      return { body: document.getElementById("WProgram1").value, types: types(), powers: values() };
    }
    function recommended(flood) {
      return {
        floodPowerW: flood, workingPowerW: 1500, headsPowerW: 1000,
        bodyEndPowerW: 1400, tailsPowerW: 1300,
        headsFlowMlH: 100, bodyFlowMaxMlH: 400, tailsFlowMlH: 150,
        bodyFlowMinMlH: 200, bodyEndFlowMlH: 300, maxFlowMlH: 1000,
        theoreticalPlates: 20, headsSpeedClamped: false, bodySpeedClamped: false
      };
    }
    function scenario(mains, resistance, unit, flood) {
      mainsVolt = mains;
      heaterResistance = resistance;
      pwr_unit = unit;
      loadedProgramPowerUnit = unit;
      document.getElementById("heaterMaxPower").value = String(Math.round(mains * mains / resistance));
      rememberUnscaledProgram(rows.join("\n"), unit);
      columnParams = recommended(flood);
      columnRecommendationsApplied = false;
      document.getElementById("WProgram1").value = rows.join("\n");
      calc_program();
      const before = values();
      const applied = applyRecommendedSpeeds({ silent: true });
      return { applied, before, after: values(), ceiling: Math.min(mains, 230) };
    }
    function blockedAfterApplied() {
      mainsVolt = 250;
      heaterResistance = 10;
      pwr_unit = "V";
      loadedProgramPowerUnit = "V";
      document.getElementById("heaterMaxPower").value = "6250";
      rememberUnscaledProgram(rows.join("\n"), "V");
      document.getElementById("WProgram1").value = rows.join("\n");
      columnParams = recommended(3000);
      calc_program();
      if (!applyRecommendedSpeeds({ silent: true })) throw new Error("setup recommendation was not applied");
      const before = { body: document.getElementById("WProgram1").value, powers: values() };
      columnParams = recommended(6000);
      const applied = applyRecommendedSpeeds({ silent: true });
      return { applied, before, after: { body: document.getElementById("WProgram1").value, powers: values() } };
    }
    function changedTypeBeforeApply(mains, flood) {
      const template = ["0;50;0;H;1", "0;50;0;C;1"];
      mainsVolt = mains;
      heaterResistance = 10;
      pwr_unit = "V";
      loadedProgramPowerUnit = "V";
      document.getElementById("heaterMaxPower").value = String(Math.round(mains * mains / heaterResistance));
      rememberUnscaledProgram(template.join("\n"), "V");
      document.getElementById("WProgram1").value = template.join("\n");
      columnParams = recommended(flood);
      calc_program();
      const type = document.getElementById("ptype1");
      type.value = "H";
      type.dispatchEvent(new Event("change", { bubbles: true }));
      const before = snapshot();
      const applied = applyRecommendedSpeeds({ silent: true });
      return { applied, before, after: snapshot() };
    }
    function safeCandidateWithUnsafeCurrentType() {
      const template = ["0;50;0;H;1", "0;50;0;H;1"];
      mainsVolt = 250;
      heaterResistance = 10;
      pwr_unit = "V";
      loadedProgramPowerUnit = "V";
      document.getElementById("heaterMaxPower").value = "6250";
      rememberUnscaledProgram(template.join("\n"), "V");
      document.getElementById("WProgram1").value = template.join("\n");
      columnParams = recommended(6000);
      calc_program();
      const type = document.getElementById("ptype1");
      type.value = "C";
      type.dispatchEvent(new Event("change", { bubbles: true }));
      const before = snapshot();
      const applied = applyRecommendedSpeeds({ silent: true });
      return { applied, before, after: snapshot() };
    }
    function adjacentC() {
      const template = ["0;50;0;H;1", "0;50;0;C;1", "0;50;0;C;1", "0;50;0;T;1"];
      mainsVolt = 220;
      heaterResistance = 10;
      pwr_unit = "V";
      loadedProgramPowerUnit = "V";
      document.getElementById("heaterMaxPower").value = "4840";
      rememberUnscaledProgram(template.join("\n"), "V");
      document.getElementById("WProgram1").value = template.join("\n");
      columnParams = recommended(3000);
      calc_program();
      const applied = applyRecommendedSpeeds({ silent: true });
      return { applied, after: snapshot() };
    }
    return {
      v220: scenario(220, 10, "V", 3000),
      v230: scenario(230, 10, "V", 3000),
      v240: scenario(240, 20, "V", 2000),
      v250Blocked: scenario(250, 10, "V", 6000),
      v250BlockedAfterApplied: blockedAfterApplied(),
      p250: scenario(250, 10, "P", 6000),
      candidate250: changedTypeBeforeApply(250, 6000),
      candidate220: changedTypeBeforeApply(220, 5000),
      safeCandidate: safeCandidateWithUnsafeCurrentType(),
      adjacentC: adjacentC()
    };
  });

  function accepted(name, expected) {
    const item = result[name];
    if (item.applied !== true || JSON.stringify(item.after) !== JSON.stringify(expected) ||
        item.after.some(value => Number(value) > item.ceiling)) {
      throw new Error(name + " must apply accessible voltage recommendations: " + JSON.stringify(item));
    }
  }
  accepted("v220", ["100", "173", "122", "114"]);
  accepted("v230", ["100", "173", "122", "114"]);
  accepted("v240", ["141", "200", "173", "161"]);
  if (result.v250Blocked.applied !== false ||
      JSON.stringify(result.v250Blocked.after) !== JSON.stringify(result.v250Blocked.before)) {
    throw new Error("250 V request above 230 V clamp must leave the program byte-for-byte unchanged: " +
      JSON.stringify(result.v250Blocked));
  }
  if (result.v250BlockedAfterApplied.applied !== false ||
      JSON.stringify(result.v250BlockedAfterApplied.after) !==
      JSON.stringify(result.v250BlockedAfterApplied.before)) {
    throw new Error("failed repeated V recommendation must preserve the already scaled program: " +
      JSON.stringify(result.v250BlockedAfterApplied));
  }
  if (result.p250.applied !== true || JSON.stringify(result.p250.after) !==
      JSON.stringify(["1000", "6000", "1500", "1300"])) {
    throw new Error("watt regulator recommendations must remain watts: " + JSON.stringify(result.p250));
  }
  for (const name of ["candidate250", "candidate220"]) {
    const item = result[name];
    if (item.applied !== false || JSON.stringify(item.after) !== JSON.stringify(item.before)) {
      throw new Error(name + " must reject the restored candidate and preserve the current program byte-for-byte: " +
        JSON.stringify(item));
    }
  }
  if (result.safeCandidate.applied !== true || JSON.stringify(result.safeCandidate.after.types) !==
      JSON.stringify(["H", "H"]) || JSON.stringify(result.safeCandidate.after.powers) !== JSON.stringify(["100", "100"])) {
    throw new Error("safe restored candidate must not be rejected because of a changed current type: " +
      JSON.stringify(result.safeCandidate));
  }
  if (result.adjacentC.applied !== true || JSON.stringify(result.adjacentC.after.types) !==
      JSON.stringify(["H", "C", "C", "T"]) || JSON.stringify(result.adjacentC.after.powers) !==
      JSON.stringify(["100", "173", "0", "114"])) {
    throw new Error("adjacent C rows must keep their order and the second C must remain unmodified: " +
      JSON.stringify(result.adjacentC));
  }
  return result;
}'''


def run_browser(site: Path, temp: Path, label: str, report_errors=True) -> tuple[int, str]:
    cli = shutil.which("playwright-cli")
    if not cli:
        print("playwright-cli is required for T07 browser contract", file=sys.stderr)
        return 2, "playwright-cli is required"
    handler = functools.partial(QuietHandler, directory=str(site))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    session = f"t07{os.getpid()}{label}"
    primary_error = None
    try:
        open_args = ["open"]
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            config = temp / f"playwright-{label}.json"
            config.write_text(json.dumps({"browser": {"browserName": "chromium", "launchOptions": {"chromiumSandbox": False}}}), encoding="utf-8")
            open_args.append(f"--config={config}")
        run_cli(cli, session, open_args, temp, 30)
        browser_test = BROWSER_TEST.replace("__BASE_URL__", json.dumps(f"http://127.0.0.1:{server.server_port}"))
        captured = io.StringIO()
        try:
            with contextlib.redirect_stdout(captured):
                run_cli(cli, session, ["run-code", browser_test], temp, 60)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            primary_error = captured.getvalue()
            if not primary_error:
                primary_error = str(error)
        else:
            print(captured.getvalue(), end="")
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        primary_error = str(error)
    cleanup_errors = cleanup(cli, session, server, thread)
    if primary_error or cleanup_errors:
        if primary_error and report_errors:
            print(f"T07 {label} browser contract failed: {primary_error}", file=sys.stderr)
        if report_errors:
            for error in cleanup_errors:
                print(f"T07 {label} browser cleanup failed: {error}", file=sys.stderr)
        return 1, primary_error or "\n".join(cleanup_errors)
    return 0, ""


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="samovar-t07-browser-") as temp_dir:
        temp = Path(temp_dir)
        site = temp / "site"
        render_site(site)
        original_rc, original_error = run_browser(site, temp, "original")

        page = site / "program.htm"
        source = page.read_text(encoding="utf-8")
        mutations = [
            ("voltage", "Math.min(mainsVolt, 230)", "Math.max(mainsVolt, 230)",
             "250 V request above 230 V clamp must leave the program byte-for-byte unchanged"),
            ("candidate", 'if (unscaledProgramBody) {\n      const candidateLines', 'if (false) {\n      const candidateLines',
             "candidate250 must reject the restored candidate"),
        ]
        if original_rc:
            print(f"T07 original browser contract failed: {original_error}", file=sys.stderr)
            return original_rc
        for label, anchor, replacement, expected_error in mutations:
            mutated = source.replace(anchor, replacement, 1)
            if mutated == source:
                print(f"T07 {label} mutation anchor not found", file=sys.stderr)
                return 1
            page.write_text(mutated, encoding="utf-8")
            mutation_rc, mutation_error = run_browser(site, temp, f"mutation-{label}", report_errors=False)
            error_section = mutation_error.split("### Ran Playwright code", 1)[0]
            if mutation_rc == 0 or expected_error not in error_section:
                print(f"T07 {label} mutation did not fail with its expected assertion", file=sys.stderr)
                if mutation_error:
                    print(mutation_error, file=sys.stderr)
                return 1
    print("T07 column voltage browser contract passed; mutations detected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
