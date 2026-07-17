#!/usr/bin/env python3
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


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data_raw"

BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  const pages = ["index.htm", "beer.htm", "distiller.htm", "bk.htm", "nbk.htm"];
  const viewports = [
    { name: "desktop", width: 1440, height: 900 },
    { name: "mobile", width: 390, height: 844 }
  ];
  const base = {
    version: "test", crnt_tm: "12:00:00", stm: "00:01:00", SteamTemp: 78.1, PipeTemp: 77.9,
    WaterTemp: 20.2, TankTemp: 82.3, ACPTemp: 40.1, bme_pressure: 760, start_pressure: 759.5,
    prvl: 1.2, VolumeAll: 0, ActualVolumePerHour: 0, WthdrwlProgress: 0, CurrrentSpeed: 0,
    CurrrentStepps: 0, TargetStepps: 0, WthdrwlStatus: 0, ProgramNum: 0, DetectorTrend: 0,
    DetectorStatus: 0, useautospeed: false, current_power_volt: 0, target_power_volt: 0,
    current_power_mode: "0", current_power_p: 0, WFtotalMl: 0, WFflowRate: 0, bme_temp: 24,
    heap: 200000, rssi: -50, fr_bt: 300000, UseBBuzzer: false, PauseOn: 0, PrgType: "",
    Status: "Готов", Lstatus: "", TimeRemaining: 0,
    TotalTime: 0, alc: 0, stm_alc: 0, ISspd: 0, wp_spd: 0, i2c_pump_present: 0,
    i2c_pump_running: 0, i2c_pump_remaining_ml: 0, i2c_pump_speed: 0, PowerOn: 0
  };
  const remainingAttack = '<img src=x onerror="window.__i2cInjected=1">';
  const speedAttack = '<img src=x onerror="window.__i2cInjected=2">';
  let fixture = Object.assign({}, base);
  let scenario = "setup";
  const errors = [];
  const passed = [];

  page.on("console", message => {
    if (message.type() === "error") errors.push(scenario + " console: " + message.text());
  });
  page.on("pageerror", error => errors.push(scenario + " pageerror: " + error.message));
  await page.route("**/ajax?messageCursor=*", route => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(fixture)
  }));

  for (const viewport of viewports) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    for (const file of pages) {
      scenario = viewport.name + "/" + file;
      fixture = Object.assign({}, base, {
        i2c_pump_present: 0,
        i2c_pump_remaining_ml: 99,
        i2c_pump_speed: 88,
        PowerOn: 1
      });
      await page.goto(baseUrl + "/" + file, { waitUntil: "load" });
      await page.waitForFunction(() => document.getElementById("power").value === "Выключить нагрев");

      let state = await page.evaluate(() => ({
        hidden: document.getElementById("i2c_pump_status").hidden,
        status: document.getElementById("i2c_status").textContent,
        remaining: document.getElementById("i2c_remaining").textContent,
        speed: document.getElementById("i2c_speed_cur").textContent,
        power: document.getElementById("power").value
      }));
      if (!state.hidden || state.status !== "Не подключён" || state.remaining !== "0" || state.speed !== "0" ||
          state.power !== "Выключить нагрев") {
        throw new Error(scenario + " initial absent mismatch: " + JSON.stringify(state));
      }

      fixture = Object.assign({}, base, {
        i2c_pump_present: 1,
        i2c_pump_running: 1,
        i2c_pump_remaining_ml: remainingAttack,
        i2c_pump_speed: speedAttack,
        PowerOn: 0
      });
      await page.evaluate(() => { delete window.__i2cInjected; });
      await page.waitForFunction(expected =>
        document.getElementById("i2c_pump_status").hidden === false &&
        document.getElementById("i2c_remaining").textContent === expected,
        remainingAttack,
        { timeout: 5000 }
      );
      state = await page.evaluate(() => ({
        hidden: document.getElementById("i2c_pump_status").hidden,
        status: document.getElementById("i2c_status").textContent,
        remaining: document.getElementById("i2c_remaining").textContent,
        speed: document.getElementById("i2c_speed_cur").textContent,
        power: document.getElementById("power").value,
        injectedNodes: document.getElementById("i2c_pump_status").querySelectorAll("img").length,
        injectedEvent: window.__i2cInjected
      }));
      if (state.hidden || state.status !== "Работает" || state.remaining !== remainingAttack ||
          state.speed !== speedAttack || state.power !== "Включить нагрев" || state.injectedNodes !== 0 ||
          state.injectedEvent !== undefined) {
        throw new Error(scenario + " present/injection mismatch: " + JSON.stringify(state));
      }

      fixture = Object.assign({}, base, {
        i2c_pump_present: 0,
        i2c_pump_remaining_ml: remainingAttack,
        i2c_pump_speed: speedAttack,
        PowerOn: 1
      });
      await page.waitForFunction(() =>
        document.getElementById("i2c_pump_status").hidden === true &&
        document.getElementById("power").value === "Выключить нагрев",
        null,
        { timeout: 5000 }
      );
      state = await page.evaluate(() => ({
        hidden: document.getElementById("i2c_pump_status").hidden,
        status: document.getElementById("i2c_status").textContent,
        remaining: document.getElementById("i2c_remaining").textContent,
        speed: document.getElementById("i2c_speed_cur").textContent,
        power: document.getElementById("power").value,
        injectedNodes: document.getElementById("i2c_pump_status").querySelectorAll("img").length,
        injectedEvent: window.__i2cInjected
      }));
      if (!state.hidden || state.status !== "Не подключён" || state.remaining !== "0" || state.speed !== "0" ||
          state.power !== "Выключить нагрев" || state.injectedNodes !== 0 || state.injectedEvent !== undefined) {
        throw new Error(scenario + " final absent mismatch: " + JSON.stringify(state));
      }
      passed.push(scenario);
    }
  }

  const missingMount = await page.evaluate(() => {
    document.getElementById("i2c_pump_status").remove();
    try {
      SamovarApp.renderI2cPumpStatus({ i2c_pump_present: 1 });
    } catch (error) {
      return error.message;
    }
    return "NO_ERROR";
  });
  if (missingMount !== "I2C pump UI contract: missing #i2c_pump_status") {
    errors.push("missing mount: " + missingMount);
  }
  if (errors.length > 0) throw new Error(errors.join("\n"));
  return { passed: passed, missingMount: missingMount };
}'''


class QuietHandler(http.server.SimpleHTTPRequestHandler):
  def log_message(self, format, *args):
    pass


def run_cli(cli, session, arguments, cwd, timeout, check=True):
  result = subprocess.run(
    [cli, f"-s={session}", *arguments],
    cwd=cwd,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    check=False,
    timeout=timeout,
  )
  if result.stdout:
    print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
  if check and result.returncode != 0:
    raise RuntimeError(f"playwright-cli {' '.join(arguments[:1])} failed with exit {result.returncode}")
  return result.returncode


def cleanup_resources(cli, session, server, thread):
  errors = []
  try:
    try:
      close_code = run_cli(cli, session, ["close"], ROOT, 30, check=False)
      if close_code != 0:
        errors.append(f"playwright-cli close failed with exit {close_code}")
    except (OSError, subprocess.TimeoutExpired) as error:
      errors.append(f"playwright-cli close failed: {error}")
  finally:
    try:
      try:
        server.shutdown()
      except Exception as error:
        errors.append(f"HTTP server shutdown failed: {error}")
    finally:
      try:
        try:
          server.server_close()
        except Exception as error:
          errors.append(f"HTTP server close failed: {error}")
      finally:
        try:
          thread.join(timeout=5)
          if thread.is_alive():
            errors.append("HTTP server thread did not stop")
        except Exception as error:
          errors.append(f"HTTP server thread join failed: {error}")
  return errors


def main():
  cli = shutil.which("playwright-cli")
  if not cli:
    print("playwright-cli is required for this explicit browser gate", file=sys.stderr)
    return 2

  handler = functools.partial(QuietHandler, directory=str(DATA))
  server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
  thread = threading.Thread(target=server.serve_forever, daemon=True)
  thread.start()
  session = f"samovar-i2c-contract-{os.getpid()}"
  primary_error = None
  cleanup_errors = []

  try:
    with tempfile.TemporaryDirectory(prefix="samovar-i2c-browser-") as temp_dir:
      open_args = ["open"]
      if hasattr(os, "geteuid") and os.geteuid() == 0:
        config = Path(temp_dir) / "playwright.json"
        config.write_text(json.dumps({
          "browser": {
            "browserName": "chromium",
            "launchOptions": {"chromiumSandbox": False},
          }
        }), encoding="utf-8")
        open_args.append(f"--config={config}")

      run_cli(cli, session, open_args, temp_dir, 30)
      base_url = f"http://127.0.0.1:{server.server_port}"
      browser_test = BROWSER_TEST.replace("__BASE_URL__", json.dumps(base_url))
      run_cli(cli, session, ["run-code", browser_test], temp_dir, 120)
  except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
    primary_error = str(error)
  finally:
    cleanup_errors = cleanup_resources(cli, session, server, thread)

  if primary_error or cleanup_errors:
    if primary_error:
      print(f"I2C pump UI browser contract failed: {primary_error}", file=sys.stderr)
    for error in cleanup_errors:
      print(f"I2C pump UI browser cleanup failed: {error}", file=sys.stderr)
    return 1

  print("I2C pump UI browser contract passed")
  return 0


if __name__ == "__main__":
  sys.exit(main())
