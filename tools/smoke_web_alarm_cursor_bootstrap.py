#!/usr/bin/env python3
"""Behavioral check for the /ajax message-cursor bootstrap + heater-alarm siren.

Executes the real data/app.js in a Node vm context (fetch/DOM/localStorage/Audio
stubbed) so the assertions exercise SamovarApp.pollAjax()/removeLastMessage()
exactly as shipped, not a regex-pinned reflection of the source text. Covers two
bugs fixed together:

  (a) A fresh page load (messageCursor == 0) must not replay the up-to-16-entry
      backlog of the runtime event ring one message per 2s poll - it must jump
      straight to the ring's current end (mirrors reset_lua_message_cursor()).
  (b) The alarm siren must track the real hardware latch (heaterAlarmLatched,
      refreshed every poll) OR'd with any currently-displayed live alarm
      message - not merely "a message happened to be read from the ring" -
      so a replayed backlog alarm can never sound, and a genuine latch keeps
      sounding even if the toast is dismissed or a second tab never saw the
      original message.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DRIVER = r'''
"use strict";
const fs = require("fs");
const vm = require("vm");

const appPath = process.argv[2];
const appSource = fs.readFileSync(appPath, "utf8");

const failures = [];
function check(condition, message) {
  if (!condition) failures.push(message);
}

function freshEnv() {
  const storage = {};
  function makeElement() {
    return { style: {}, innerHTML: "", scrollTop: 0, scrollHeight: 0 };
  }
  // Пред-созданы как в реальном DOM: реальные .htm уже содержат #messagesBox/#messages
  // до загрузки app.js, поэтому byId() их только находит, а не лениво создаёт.
  const elements = { messagesBox: makeElement(), messages: makeElement() };
  function AudioStub() {
    this.loop = false;
    this.preload = "";
    this.autoplay = false;
    this.currentTime = 0;
    this.playing = false;
    AudioStub.instances.push(this);
  }
  AudioStub.instances = [];
  AudioStub.prototype.play = function () {
    this.playing = true;
    return Promise.resolve();
  };
  AudioStub.prototype.pause = function () {
    this.playing = false;
  };

  const env = {
    window: {},
    document: {
      getElementById: function (id) {
        if (!elements[id]) elements[id] = makeElement();
        return elements[id];
      },
      documentElement: {},
      addEventListener: function () {},
    },
    localStorage: {
      getItem: function (key) {
        return Object.prototype.hasOwnProperty.call(storage, key) ? storage[key] : null;
      },
      setItem: function (key, value) {
        storage[key] = String(value);
      },
    },
    Audio: AudioStub,
    getComputedStyle: function () {
      return { getPropertyValue: function () { return ""; } };
    },
    console: console,
    setTimeout: setTimeout,
    clearTimeout: clearTimeout,
    AbortController: AbortController,
  };
  return { env: env, elements: elements, audio: AudioStub.instances };
}

function loadApp(fetchImpl) {
  const fresh = freshEnv();
  fresh.env.fetch = fetchImpl;
  const context = vm.createContext(fresh.env);
  vm.runInContext(appSource, context, { filename: "app.js" });
  return { app: context.window.SamovarApp, elements: fresh.elements, audio: fresh.audio };
}

function makeFetch(responses) {
  let index = 0;
  const calls = [];
  const fetchImpl = function (url) {
    calls.push(url);
    const body = responses[Math.min(index, responses.length - 1)];
    index++;
    return Promise.resolve({
      ok: true,
      status: 200,
      json: function () { return Promise.resolve(body); },
    });
  };
  fetchImpl.calls = calls;
  return fetchImpl;
}

const noopRender = function () {};

async function scenarioBootstrapSkipsBacklogText() {
  const fetchImpl = makeFetch([
    { messageSequence: 3, Msg: "old backlog message", msglvl: 2,
      heaterAlarmLatched: 0, latestMessageSequence: 5 },
  ]);
  const { app, elements } = loadApp(fetchImpl);
  const ok = await app.pollAjax(noopRender);
  check(ok, "bootstrap poll must report success");
  check(elements.messages.innerHTML === "",
    "bootstrap must not render the ring backlog as a live message");

  await app.pollAjax(noopRender);
  check(fetchImpl.calls[1].indexOf("messageCursor=5") !== -1,
    "bootstrap must jump the cursor straight to latestMessageSequence, " +
    "not replay the backlog one entry at a time (got: " + fetchImpl.calls[1] + ")");
}

async function scenarioBootstrapDoesNotSoundStaleAlarm() {
  const fetchImpl = makeFetch([
    { messageSequence: 3, Msg: "STALE ALARM must not resound", msglvl: 0,
      heaterAlarmLatched: 0, latestMessageSequence: 5 },
  ]);
  const { app, audio } = loadApp(fetchImpl);
  await app.pollAjax(noopRender);
  check(audio.length === 1 && audio[0].playing === false,
    "a replayed backlog ALARM_MSG must not trigger the siren");
}

async function scenarioHardwareLatchSoundsWithoutAnyMessage() {
  const fetchImpl = makeFetch([
    { heaterAlarmLatched: 1, latestMessageSequence: 0 },
  ]);
  const { app, audio, elements } = loadApp(fetchImpl);
  await app.pollAjax(noopRender);
  check(elements.messages.innerHTML === "",
    "this scenario must not rely on any message ever being shown");
  check(audio.length === 1 && audio[0].playing === true,
    "heaterAlarmLatched=1 must sound the siren even with zero messages " +
    "(covers reload/second-tab mid-alarm and dismissed-toast cases)");
}

async function scenarioLiveAlarmMessageStillSounds() {
  const fetchImpl = makeFetch([
    { messageSequence: 1, Msg: "bootstrap filler", msglvl: 2,
      heaterAlarmLatched: 0, latestMessageSequence: 1 },
    { messageSequence: 2, Msg: "Сработал датчик захлёба!", msglvl: 0,
      heaterAlarmLatched: 0, latestMessageSequence: 2 },
  ]);
  const { app, audio, elements } = loadApp(fetchImpl);
  await app.pollAjax(noopRender);
  await app.pollAjax(noopRender);
  check(elements.messages.innerHTML.indexOf("message_0") !== -1,
    "a genuine live ALARM_MSG must still render (non-regression)");
  check(audio.length === 1 && audio[0].playing === true,
    "a genuine live ALARM_MSG must still sound the siren even when " +
    "heaterAlarmLatched is false (not every alarm trips the heater latch)");
}

async function scenarioFirstEventEverOnEmptyRingIsNotSwallowed() {
  const fetchImpl = makeFetch([
    // Кольцо пустое: сервер не отдаёт событие, latestMessageSequence = 0.
    { heaterAlarmLatched: 0, latestMessageSequence: 0 },
    // Первое в жизни устройства событие - авария, которая НЕ взводит аппаратную
    // защёлку, поэтому существует только как текст сообщения.
    { messageSequence: 1, Msg: "Сработал датчик захлёба!", msglvl: 0,
      heaterAlarmLatched: 0, latestMessageSequence: 1 },
  ]);
  const { app, audio, elements } = loadApp(fetchImpl);
  await app.pollAjax(noopRender);
  check(elements.messages.innerHTML === "",
    "пустое кольцо на бутстрапе не должно ничего рендерить");

  await app.pollAjax(noopRender);
  check(elements.messages.innerHTML.indexOf("Сработал датчик захлёба!") !== -1,
    "первое в жизни устройства событие обязано отображаться: бутстрап считается " +
    "выполненным по флагу, а не по messageCursor === 0, иначе на пустом кольце " +
    "курсор остаётся нулевым и первое событие молча съедается");
  check(elements.messages.innerHTML.indexOf("разрыв") === -1,
    "sequence 1 после пустого кольца - это не разрыв последовательности");
  check(audio.length === 1 && audio[0].playing === true,
    "сирена обязана звучать по первому же событию-аварии на пустом кольце");
}

async function scenarioDismissingToastKeepsSirenWhileLatched() {
  const fetchImpl = makeFetch([
    { messageSequence: 1, Msg: "bootstrap filler", msglvl: 2,
      heaterAlarmLatched: 0, latestMessageSequence: 1 },
    { messageSequence: 2, Msg: "Сработал датчик захлёба!", msglvl: 0,
      heaterAlarmLatched: 0, latestMessageSequence: 2 },
    // Аппаратный latch сработал уже после того, как тост показан.
    { heaterAlarmLatched: 1, latestMessageSequence: 2 },
  ]);
  const { app, audio, elements } = loadApp(fetchImpl);
  await app.pollAjax(noopRender);
  await app.pollAjax(noopRender);
  await app.pollAjax(noopRender);
  app.removeLastMessage();
  check(elements.messagesBox.style.display === "none",
    "dismissing the last toast must hide the message box");
  check(audio.length === 1 && audio[0].playing === true,
    "dismissing the toast must NOT silence the siren while heaterAlarmLatched " +
    "is still true (hardware alarm outlives the toast)");
}

async function main() {
  await scenarioBootstrapSkipsBacklogText();
  await scenarioBootstrapDoesNotSoundStaleAlarm();
  await scenarioHardwareLatchSoundsWithoutAnyMessage();
  await scenarioLiveAlarmMessageStillSounds();
  await scenarioFirstEventEverOnEmptyRingIsNotSwallowed();
  await scenarioDismissingToastKeepsSirenWhileLatched();

  if (failures.length) {
    for (const message of failures) console.error("FAIL: " + message);
    process.exit(1);
  }
  console.log("web alarm cursor bootstrap smoke passed (6 scenarios)");
}

main().catch(function (err) {
  console.error("FAIL: uncaught error: " + (err && err.stack ? err.stack : err));
  process.exit(1);
});
'''


def run_driver(app_js_path: Path) -> subprocess.CompletedProcess:
    node = shutil.which("node")
    if not node:
        print("FAIL: node executable not found on PATH", file=sys.stderr)
        raise SystemExit(1)
    with tempfile.TemporaryDirectory(prefix="samovar-alarm-bootstrap-") as tmp:
        driver_path = Path(tmp) / "driver.js"
        driver_path.write_text(DRIVER, encoding="utf-8")
        return subprocess.run(
            [node, str(driver_path), str(app_js_path)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )


def main() -> int:
    app_js_path = ROOT / "data_raw" / "app.js"
    if len(sys.argv) > 1:
        app_js_path = Path(sys.argv[1]).resolve()
    if not app_js_path.exists():
        print(f"FAIL: {app_js_path} not found", file=sys.stderr)
        return 1

    result = run_driver(app_js_path)
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.returncode != 0:
        if result.stderr:
            print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
