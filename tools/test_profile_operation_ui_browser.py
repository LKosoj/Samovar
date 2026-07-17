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

from test_numeric_input_ui_browser import render_site


ROOT = Path(__file__).resolve().parents[1]

BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  const problems = [];
  const covered = [];
  let scenario = "startup";

  page.on("console", message => {
    if (message.type() === "warning" || message.type() === "error") {
      problems.push(scenario + " console " + message.type() + ": " + message.text());
    }
  });
  page.on("pageerror", error => problems.push(scenario + " pageerror: " + error.message));
  page.on("response", response => {
    if (response.status() >= 400) {
      problems.push(scenario + " HTTP " + response.status() + ": " + response.url());
    }
  });
  await page.route("**/ajax?messageCursor=*", route => route.fulfill({
    status: 200, contentType: "application/json", body: "{}"
  }));
  await page.route("**/ajax_col_params?*", route => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      floodPowerW: 3000, workingPowerW: 2500, maxFlowMlH: 1000,
      theoreticalPlates: 20, headsFlowMlH: 100, bodyFlowMinMlH: 200,
      bodyFlowMaxMlH: 400, bodyEndFlowMlH: 300, tailsFlowMlH: 150,
      headsPowerW: 1800, bodyEndPowerW: 2200, tailsPowerW: 2000
    })
  }));

  async function installFetch(config) {
    await page.evaluate(settings => {
      if (!window.__profileOperationNativeFetch) {
        window.__profileOperationNativeFetch = window.fetch.bind(window);
      }
      window.__mutationRequests = [];
      window.__lookupRequests = [];
      window.__mutationPlans = (settings.mutationPlans || []).slice();
      window.__lookupPlans = (settings.lookupPlans || []).slice();
      window.__repeatLookup = settings.repeatLookup || null;
      window.__releaseLookup = null;
      window.fetch = async (url, options) => {
        const raw = typeof url === "string" ? url : url.url;
        if (raw.startsWith("/ajax?operationId=")) {
          window.__lookupRequests.push(raw);
          const plan = window.__lookupPlans.length
            ? window.__lookupPlans.shift()
            : window.__repeatLookup;
          if (!plan) throw new Error("Missing lookup plan for " + raw);
          if (plan.hold) {
            await new Promise(resolve => { window.__releaseLookup = resolve; });
          }
          if (plan.network) throw new TypeError(plan.network);
          if (plan.hungBody) {
            const stream = new ReadableStream({
              start(controller) {
                const abort = () => controller.error(new DOMException("aborted", "AbortError"));
                if (options.signal.aborted) abort();
                else options.signal.addEventListener("abort", abort, { once: true });
              }
            });
            return new Response(stream, {
              status: plan.status,
              headers: { "Content-Type": plan.contentType || "application/json" }
            });
          }
          return new Response(
            plan.body === undefined ? "" : JSON.stringify(plan.body),
            {
              status: plan.status,
              headers: { "Content-Type": plan.contentType || "application/json" }
            }
          );
        }
        if (settings.path && raw === settings.path) {
          const plan = window.__mutationPlans.shift();
          if (!plan) throw new Error("Missing mutation plan for " + raw);
          const body = options && options.body instanceof FormData
            ? Array.from(options.body.entries())
            : options && options.body !== undefined ? String(options.body) : null;
          window.__mutationRequests.push({ url: raw, method: options && options.method, body });
          if (plan.network) throw new TypeError(plan.network);
          return new Response(
            plan.body === undefined ? "" : JSON.stringify(plan.body),
            {
              status: plan.status,
              headers: { "Content-Type": plan.contentType || "application/json" }
            }
          );
        }
        return window.__profileOperationNativeFetch(url, options);
      };
    }, config);
  }

  async function waiter(name, lookupPlans, expectedText, repeatLookup, accelerateClock) {
    scenario = "waiter/" + name;
    await installFetch({ lookupPlans, repeatLookup });
    const result = await page.evaluate(async accelerate => {
      const realNow = Date.now;
      const realSetTimeout = window.setTimeout;
      let fakeNow = 0;
      if (accelerate) {
        Date.now = () => fakeNow;
        window.setTimeout = (callback, delay) => realSetTimeout(() => {
          fakeNow += delay;
          callback();
        }, delay >= 1000 ? 10 : 0);
      }
      try {
        const value = await SamovarApp.waitForOperation(17);
        return { ok: true, value, lookups: window.__lookupRequests.length };
      } catch (error) {
        return { ok: false, error: String(error), lookups: window.__lookupRequests.length };
      } finally {
        Date.now = realNow;
        window.setTimeout = realSetTimeout;
      }
    }, !!accelerateClock);
    if (expectedText === "succeeded") {
      if (!result.ok || result.value.state !== "succeeded") {
        throw new Error(scenario + " mismatch: " + JSON.stringify(result));
      }
    } else if (result.ok || !result.error.includes(expectedText)) {
      throw new Error(scenario + " mismatch: " + JSON.stringify(result));
    }
    covered.push(scenario);
    return result;
  }

  await page.goto(baseUrl + "/setup.htm", { waitUntil: "load" });
  await waiter("lifecycle", [
    { status: 200, body: { operationId: 17, state: "queued", error: "none" } },
    { status: 200, body: { operationId: 17, state: "running", error: "none" } },
    { status: 200, body: { operationId: 17, state: "succeeded", error: "none" } }
  ], "succeeded");
  await waiter("transient-503", [
    { status: 503, body: { operationId: 17, error: "operation_store_busy" } },
    { status: 200, body: { operationId: 17, state: "running", error: "none" } },
    { status: 200, body: { operationId: 17, state: "succeeded", error: "none" } }
  ], "succeeded");
  await waiter("malformed-503", [{
    status: 503,
    body: { operationId: 17, error: "operation_store_busy", extra: true }
  }], "Некорректный контракт HTTP 503");
  await waiter("other-503", [{
    status: 503,
    body: { operationId: 17, error: "operation_runtime_busy" }
  }], "Некорректный контракт HTTP 503");
  for (const code of [
    "operation_cancelled", "profile_persist_failed", "mode_switch_failed", "operation_runtime_busy"
  ]) {
    await waiter("failed-" + code, [
      { status: 200, body: { operationId: 17, state: "failed", error: code } }
    ], code);
  }
  await waiter("expired", [{ status: 404, body: { error: "operation_not_found" } }], "HTTP 404");
  await waiter("network", [{ network: "offline" }], "Ошибка сети");
  await waiter("cardinality", [{
    status: 200,
    body: { operationId: 17, state: "succeeded", error: "none", extra: true }
  }], "Некорректный контракт");
  const timeoutResult = await waiter(
    "busy-timeout",
    [],
    "последний ответ HTTP 503",
    { status: 503, body: { operationId: 17, error: "operation_store_busy" } },
    true
  );
  if (timeoutResult.lookups < 100) {
    throw new Error("busy timeout was not bounded by the common deadline: " + JSON.stringify(timeoutResult));
  }
  for (const contentType of ["application/json", "text/plain"]) {
    const hungBodyResult = await waiter(
      "hung-" + (contentType === "application/json" ? "json" : "text") + "-body",
      [{ status: contentType === "application/json" ? 200 : 500, contentType, hungBody: true }],
      "не завершилась за 45 секунд",
      null,
      true
    );
    if (hungBodyResult.lookups !== 1) {
      throw new Error("hung body timeout issued another lookup: " + JSON.stringify(hungBodyResult));
    }
  }

  scenario = "acceptance-shape";
  const acceptance = await page.evaluate(async () => {
    const cases = [
      { operationId: 0, state: "queued", error: "none" },
      { operationId: 1, state: "running", error: "none" },
      { operationId: 1, state: "queued", error: "none", extra: true }
    ];
    const errors = [];
    for (const body of cases) {
      try {
        await SamovarApp.readOperationAcceptance(new Response(JSON.stringify(body), {
          status: 202, headers: { "Content-Type": "application/json" }
        }));
      } catch (error) {
        errors.push(String(error));
      }
    }
    return errors;
  });
  if (acceptance.length !== 3 || acceptance.some(text => !text.includes("Некоррект") && !text.includes("queued"))) {
    throw new Error("acceptance strictness mismatch: " + JSON.stringify(acceptance));
  }
  covered.push(scenario);

  function acceptedSave(operationId) {
    return { status: 202, body: { operationId, state: "queued", error: "none" } };
  }
  function acceptedProgram(operationId) {
    return {
      status: 202,
      body: { ok: true, err: "", program: "", operationId, state: "queued", error: "none" }
    };
  }
  function terminal(operationId, state, error) {
    return { status: 200, body: { operationId, state, error } };
  }

  async function prepareSetup() {
    await page.goto(baseUrl + "/setup.htm", { waitUntil: "load" });
    await page.evaluate(() => {
      const form = document.getElementById("setupform");
      setupNumericSchema.forEach(rule => {
        const input = form.elements[rule.name];
        const value = rule.min !== undefined
          ? rule.min
          : rule.exclusiveMin !== undefined ? rule.exclusiveMin + 1 : 0;
        if (input.tagName === "SELECT" &&
            !Array.from(input.options).some(option => option.value === String(value))) {
          input.add(new Option(String(value), String(value)));
        }
        input.value = String(value);
      });
      form.dispatchEvent(new Event("input", { bubbles: true }));
    });
  }

  scenario = "setup/failed";
  await prepareSetup();
  await installFetch({
    path: "/save",
    mutationPlans: [acceptedSave(31)],
    lookupPlans: [terminal(31, "failed", "profile_persist_failed")]
  });
  const setupFailed = await page.evaluate(async () => {
    const form = document.getElementById("setupform");
    const result = await submitSetupForm({ preventDefault() {}, currentTarget: form });
    const error = document.getElementById("request_error");
    return {
      result,
      dirty: form.dataset.dirty,
      submitting: form.dataset.submitting,
      disabled: document.getElementById("save").disabled,
      message: error && error.textContent,
      mutations: window.__mutationRequests.length,
      lookups: window.__lookupRequests.length,
      path: location.pathname
    };
  });
  if (setupFailed.result !== false || setupFailed.dirty !== "true" ||
      setupFailed.submitting !== "false" || setupFailed.disabled ||
      !setupFailed.message.includes("profile_persist_failed") ||
      setupFailed.mutations !== 1 || setupFailed.lookups !== 1 || setupFailed.path !== "/setup.htm") {
    throw new Error(scenario + " mismatch: " + JSON.stringify(setupFailed));
  }
  covered.push(scenario);

  for (const status of [400, 409, 503]) {
    scenario = "setup/rejected-" + status;
    await prepareSetup();
    await installFetch({
      path: "/save",
      mutationPlans: [{
        status,
        body: { error: status === 400 ? "default_program_invalid" : "operation_runtime_busy" }
      }]
    });
    const rejected = await page.evaluate(async () => {
      const form = document.getElementById("setupform");
      const result = await submitSetupForm({ preventDefault() {}, currentTarget: form });
      const error = document.getElementById("request_error");
      return {
        result,
        dirty: form.dataset.dirty,
        disabled: document.getElementById("save").disabled,
        message: error && error.textContent,
        mutations: window.__mutationRequests.length,
        lookups: window.__lookupRequests.length
      };
    });
    if (rejected.result !== false || rejected.dirty !== "true" || rejected.disabled ||
        !rejected.message.includes("HTTP " + status) || rejected.mutations !== 1 || rejected.lookups !== 0) {
      throw new Error(scenario + " mismatch: " + JSON.stringify(rejected));
    }
    covered.push(scenario);
  }

  scenario = "setup/edit-during-pending";
  await prepareSetup();
  await installFetch({
    path: "/save",
    mutationPlans: [acceptedSave(33)],
    lookupPlans: [
      terminal(33, "running", "none"),
      { ...terminal(33, "succeeded", "none"), hold: true }
    ]
  });
  await page.evaluate(() => {
    const form = document.getElementById("setupform");
    window.__editedSetup = submitSetupForm({ preventDefault() {}, currentTarget: form });
  });
  await page.waitForFunction(() => typeof window.__releaseLookup === "function");
  await page.evaluate(() => {
    const input = document.forms.setupform.elements.DistTemp;
    input.value = "2";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    window.__releaseLookup();
  });
  const editedSetup = await page.evaluate(async () => {
    const result = await window.__editedSetup;
    const form = document.getElementById("setupform");
    const error = document.getElementById("request_error");
    return {
      result,
      dirty: form.dataset.dirty,
      disabled: document.getElementById("save").disabled,
      value: form.elements.DistTemp.value,
      message: error && error.textContent,
      mutations: window.__mutationRequests.length,
      path: location.pathname
    };
  });
  if (!editedSetup.result || editedSetup.dirty !== "true" || editedSetup.disabled ||
      editedSetup.value !== "2" ||
      !editedSetup.message.includes("новые изменения формы ещё не сохранены") ||
      editedSetup.mutations !== 1 || editedSetup.path !== "/setup.htm") {
    throw new Error(scenario + " mismatch: " + JSON.stringify(editedSetup));
  }
  covered.push(scenario);

  scenario = "setup/success-double-submit";
  await prepareSetup();
  await installFetch({
    path: "/save",
    mutationPlans: [acceptedSave(32)],
    lookupPlans: [
      terminal(32, "queued", "none"),
      { ...terminal(32, "succeeded", "none"), hold: true }
    ]
  });
  await page.evaluate(() => {
    const form = document.getElementById("setupform");
    window.__firstSetup = submitSetupForm({ preventDefault() {}, currentTarget: form });
  });
  await page.waitForFunction(() => typeof window.__releaseLookup === "function");
  const setupPending = await page.evaluate(async () => {
    const form = document.getElementById("setupform");
    const second = await submitSetupForm({ preventDefault() {}, currentTarget: form });
    return {
      second,
      dirty: form.dataset.dirty,
      disabled: document.getElementById("save").disabled,
      mutations: window.__mutationRequests.length,
      path: location.pathname
    };
  });
  if (setupPending.second !== false || setupPending.dirty !== "true" ||
      !setupPending.disabled || setupPending.mutations !== 1 || setupPending.path !== "/setup.htm") {
    throw new Error(scenario + " early state mismatch: " + JSON.stringify(setupPending));
  }
  await Promise.all([
    page.waitForURL(baseUrl + "/"),
    page.evaluate(() => window.__releaseLookup())
  ]);
  covered.push(scenario);

  scenario = "program/success-double-submit";
  await page.goto(baseUrl + "/program.htm", { waitUntil: "load" });
  await page.evaluate(() => {
    document.getElementById("WProgram1").value = "T;1;2;3;0";
    document.getElementById("vless").value = "1";
  });
  await installFetch({
    path: "/program",
    mutationPlans: [acceptedProgram(41)],
    lookupPlans: [
      terminal(41, "queued", "none"),
      { ...terminal(41, "succeeded", "none"), hold: true }
    ]
  });
  await page.evaluate(() => {
    window.__firstProgram = SamovarApp.postProgram(document.forms.mainform);
  });
  await page.waitForFunction(() => typeof window.__releaseLookup === "function");
  const programPending = await page.evaluate(async () => {
    const second = await SamovarApp.postProgram(document.forms.mainform);
    return { second, mutations: window.__mutationRequests.length };
  });
  if (programPending.second.ok || !programPending.second.err.includes("уже выполняется") ||
      programPending.mutations !== 1) {
    throw new Error(scenario + " double-submit mismatch: " + JSON.stringify(programPending));
  }
  await page.evaluate(() => window.__releaseLookup());
  const programSucceeded = await page.evaluate(async () => {
    const first = await window.__firstProgram;
    return { first, mutations: window.__mutationRequests.length, lookups: window.__lookupRequests.length };
  });
  if (!programSucceeded.first.ok || programSucceeded.first.state !== "succeeded" ||
      programSucceeded.first.queued || programSucceeded.mutations !== 1 || programSucceeded.lookups !== 2) {
    throw new Error(scenario + " terminal mismatch: " + JSON.stringify(programSucceeded));
  }
  covered.push(scenario);

  scenario = "program/failed";
  await installFetch({
    path: "/program",
    mutationPlans: [acceptedProgram(42)],
    lookupPlans: [terminal(42, "failed", "mode_switch_failed")]
  });
  const programFailed = await page.evaluate(async () => {
    const result = await SamovarApp.postProgram(document.forms.mainform);
    const error = document.getElementById("request_error");
    return {
      result,
      message: error && error.textContent,
      mutations: window.__mutationRequests.length,
      lookups: window.__lookupRequests.length
    };
  });
  if (programFailed.result.ok || !programFailed.result.err.includes("mode_switch_failed") ||
      !programFailed.message.includes("mode_switch_failed") ||
      programFailed.mutations !== 1 || programFailed.lookups !== 1) {
    throw new Error(scenario + " mismatch: " + JSON.stringify(programFailed));
  }
  covered.push(scenario);

  for (const status of [409, 503]) {
    scenario = "program/rejected-" + status;
    await installFetch({
      path: "/program",
      mutationPlans: [{
        status,
        body: { ok: false, err: "operation_runtime_busy", program: "" }
      }]
    });
    const rejected = await page.evaluate(async () => {
      const result = await SamovarApp.postProgram(document.forms.mainform);
      const error = document.getElementById("request_error");
      return {
        result,
        message: error && error.textContent,
        mutations: window.__mutationRequests.length,
        lookups: window.__lookupRequests.length
      };
    });
    if (rejected.result.ok || rejected.result.httpStatus !== status ||
        !rejected.message.includes("HTTP " + status) ||
        rejected.mutations !== 1 || rejected.lookups !== 0) {
      throw new Error(scenario + " mismatch: " + JSON.stringify(rejected));
    }
    covered.push(scenario);
  }

  scenario = "clear/terminal-message";
  await installFetch({
    path: "/program",
    mutationPlans: [acceptedProgram(43)],
    lookupPlans: [
      terminal(43, "running", "none"),
      { ...terminal(43, "succeeded", "none"), hold: true }
    ]
  });
  await page.evaluate(() => {
    window.confirm = () => true;
    localStorage.removeItem("samovarHistoryV2");
    window.__clearCall = SamovarApp.clearProgram();
  });
  await page.waitForFunction(() => typeof window.__releaseLookup === "function");
  const clearPending = await page.evaluate(async () => {
    const second = await SamovarApp.clearProgram();
    const history = JSON.parse(localStorage.getItem("samovarHistoryV2") || "[]");
    return {
      second,
      earlySuccess: history.some(item => item.msg === "Программа очищена."),
      mutations: window.__mutationRequests.length
    };
  });
  if (clearPending.second || clearPending.earlySuccess || clearPending.mutations !== 1) {
    throw new Error(scenario + " early state mismatch: " + JSON.stringify(clearPending));
  }
  await page.evaluate(() => window.__releaseLookup());
  const clearDone = await page.evaluate(async () => {
    const result = await window.__clearCall;
    const history = JSON.parse(localStorage.getItem("samovarHistoryV2") || "[]");
    return { result, last: history.length ? history.at(-1).msg : "" };
  });
  if (!clearDone.result || clearDone.last !== "Программа очищена.") {
    throw new Error(scenario + " terminal mismatch: " + JSON.stringify(clearDone));
  }
  covered.push(scenario);

  if (problems.length) throw new Error(problems.join("\n"));
  return { covered: covered.length };
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
  if check and (result.returncode != 0 or "### Error" in result.stdout):
    raise RuntimeError(f"playwright-cli {' '.join(arguments[:1])} failed")
  return result.returncode


def cleanup(cli, session, server, thread):
  errors = []
  try:
    if run_cli(cli, session, ["close"], ROOT, 30, check=False) != 0:
      errors.append("playwright-cli close failed")
  except (OSError, subprocess.TimeoutExpired) as error:
    errors.append(f"playwright-cli close failed: {error}")
  try:
    server.shutdown()
    server.server_close()
  except OSError as error:
    errors.append(f"HTTP server cleanup failed: {error}")
  thread.join(timeout=5)
  if thread.is_alive():
    errors.append("HTTP server thread did not stop")
  return errors


def main():
  cli = shutil.which("playwright-cli")
  if not cli:
    print("playwright-cli is required for the profile operation browser gate", file=sys.stderr)
    return 2

  primary_error = None
  cleanup_errors = []
  with tempfile.TemporaryDirectory(prefix="samovar-profile-operation-ui-") as temp_dir:
    temp = Path(temp_dir)
    site = temp / "site"
    render_site(site)

    handler = functools.partial(QuietHandler, directory=str(site))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    session = f"samovar-profile-operation-ui-{os.getpid()}"
    try:
      open_args = ["open"]
      if hasattr(os, "geteuid") and os.geteuid() == 0:
        config = temp / "playwright.json"
        config.write_text(json.dumps({
          "browser": {
            "browserName": "chromium",
            "launchOptions": {"chromiumSandbox": False},
          }
        }), encoding="utf-8")
        open_args.append(f"--config={config}")
      run_cli(cli, session, open_args, temp, 30)
      code = BROWSER_TEST.replace(
        "__BASE_URL__", json.dumps(f"http://127.0.0.1:{server.server_port}")
      )
      run_cli(cli, session, ["run-code", code], temp, 240)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
      primary_error = str(error)
    finally:
      cleanup_errors = cleanup(cli, session, server, thread)

  if primary_error or cleanup_errors:
    if primary_error:
      print(f"Profile operation UI browser gate failed: {primary_error}", file=sys.stderr)
    for error in cleanup_errors:
      print(f"Profile operation UI browser cleanup failed: {error}", file=sys.stderr)
    return 1

  print("Profile operation UI browser gate passed")
  return 0


if __name__ == "__main__":
  sys.exit(main())
