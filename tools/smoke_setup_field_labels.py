#!/usr/bin/env python3
"""[T35 п.4а] Подпись ошибочного поля берётся из DOM (текст <label for="...">), а не из
технического имени параметра ("NbkDelta" вместо человеческого "Дельта НБК").

Ловушка, которую чинили: часть меток на setup.htm несёт вложенную подсказку
<span class="tooltiptext">...</span> (см. useDetector в data_raw/setup.htm) - её текст в
подпись попадать не должен, иначе пользователь увидит "Использовать детектордетектор
примесей на всех строках программы...".

Тест грузит НАСТОЯЩИЙ data_raw/app.js в Node vm (DOM - минимальная своя реализация: только
то, что использует fieldLabelFromDom()/validateNumericInput() - querySelector по
`label[for="..."]`, cloneNode(true), querySelectorAll('.tooltiptext'), remove(),
textContent) и гоняет реальные SamovarApp.fieldLabelFromDom()/validateNumericInput().
"""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "data_raw" / "app.js"

DRIVER = r'''
"use strict";
const fs = require("fs");
const vm = require("vm");

const appPath = process.argv[2];
const appSource = fs.readFileSync(appPath, "utf8");

const failures = [];
function check(cond, msg) { if (!cond) failures.push(msg); }

function TextNode(text) {
  return {
    nodeType: 3,
    textContent: text,
    cloneNode: function () { return TextNode(text); },
  };
}

function makeElement(tag) {
  const el = {
    tagName: (tag || "div").toUpperCase(),
    nodeType: 1,
    _attrs: {},
    _class: [],
    _children: [],
    parentNode: null,
    style: {},
    value: "",
  };
  el.setAttribute = function (name, val) {
    el._attrs[name] = String(val);
    if (name === "class") el._class = String(val).split(/\s+/).filter(Boolean);
  };
  el.getAttribute = function (name) {
    return Object.prototype.hasOwnProperty.call(el._attrs, name) ? el._attrs[name] : null;
  };
  el.hasAttribute = function (name) {
    return Object.prototype.hasOwnProperty.call(el._attrs, name);
  };
  el.appendChild = function (child) {
    child.parentNode = el;
    el._children.push(child);
    return child;
  };
  el.appendText = function (text) { el.appendChild(TextNode(text)); };
  el.remove = function () {
    if (el.parentNode) {
      const siblings = el.parentNode._children;
      const idx = siblings.indexOf(el);
      if (idx !== -1) siblings.splice(idx, 1);
      el.parentNode = null;
    }
  };
  Object.defineProperty(el, "textContent", {
    get: function () {
      let out = "";
      for (const child of el._children) out += child.textContent;
      return out;
    },
  });
  el.cloneNode = function (deep) {
    const clone = makeElement(el.tagName);
    clone._attrs = Object.assign({}, el._attrs);
    clone._class = el._class.slice();
    if (deep) {
      for (const child of el._children) {
        const childClone = child.cloneNode(true);
        childClone.parentNode = clone;
        clone._children.push(childClone);
      }
    }
    return clone;
  };
  function collect(node, cls, out) {
    for (const child of node._children) {
      if (child.nodeType === 1 && child._class.indexOf(cls) !== -1) out.push(child);
      if (child.nodeType === 1) collect(child, cls, out);
    }
  }
  el.querySelectorAll = function (selector) {
    const cls = selector.replace(/^\./, "");
    const out = [];
    collect(el, cls, out);
    return out;
  };
  return el;
}

function freshEnv() {
  const elements = {};
  const labelsByFor = {};
  const doc = {
    getElementById: function (id) {
      if (!elements[id]) elements[id] = makeElement("input");
      return elements[id];
    },
    createElement: function (tag) { return makeElement(tag); },
    querySelector: function (selector) {
      const m = /^label\[for="([^"]+)"\]$/.exec(selector);
      if (m) return labelsByFor[m[1]] || null;
      return null;
    },
    documentElement: {},
    body: makeElement("body"),
    addEventListener: function () {},
  };
  doc.body.insertBefore = function () {};
  doc.body.appendChild = function () {};

  // Регистрирует <label for="name" class="tooltip">text<span
  // class="tooltiptext">tip</span></label> ровно как в setup.htm.
  function registerLabel(forName, text, tooltip) {
    const label = makeElement("label");
    label.setAttribute("for", forName);
    label.setAttribute("class", "tooltip");
    label.appendText(text);
    if (tooltip) {
      const span = makeElement("span");
      span.setAttribute("class", "tooltiptext");
      span.appendText(tooltip);
      label.appendChild(span);
    }
    labelsByFor[forName] = label;
    return label;
  }

  const env = {
    window: {},
    document: doc,
    console: console,
  };
  const context = vm.createContext(env);
  vm.runInContext(appSource, context, { filename: "app.js" });
  return { app: context.window.SamovarApp, elements: elements, registerLabel: registerLabel };
}

(function () {
  // 1) fieldLabelFromDom() снимает подпись метки и отбрасывает вложенную подсказку.
  {
    const { app, registerLabel } = freshEnv();
    registerLabel("useDetector", "Использовать детектор", "детектор примесей на всех строках программы");
    const label = app.fieldLabelFromDom("useDetector");
    check(label === "Использовать детектор",
      "fieldLabelFromDom должен вернуть подпись без текста подсказки: " + JSON.stringify(label));
  }

  // 2) Поля без метки в DOM - null (не бросает исключение, не выдумывает текст).
  {
    const { app } = freshEnv();
    const label = app.fieldLabelFromDom("noSuchField");
    check(label === null, "fieldLabelFromDom для отсутствующей метки должен вернуть null: " + JSON.stringify(label));
  }

  // 3) validateNumericInput() без явного label подставляет человеческую подпись из DOM,
  //    а не техническое имя параметра - это и есть цель T35 п.4а.
  {
    const { app, elements, registerLabel } = freshEnv();
    registerLabel("useDetector", "Использовать детектор", "детектор примесей...");
    const input = elements.useDetector = makeElement("input");
    input.name = "useDetector";
    input.value = "";
    const result = app.validateNumericInput(input, {});
    check(result.ok === false, "пустое значение обязано быть ошибкой");
    check(result.error.indexOf("Использовать детектор") !== -1,
      "ошибка обязана содержать человеческую подпись из DOM: " + result.error);
    check(result.error.indexOf("useDetector") === -1,
      "ошибка не должна содержать техническое имя параметра, когда есть подпись из DOM: " + result.error);
  }

  // 4) Явный label (используют другие страницы) обязан побеждать DOM - регресс.
  {
    const { app, elements, registerLabel } = freshEnv();
    registerLabel("useDetector", "Использовать детектор", "детектор примесей...");
    const input = elements.useDetector = makeElement("input");
    input.name = "useDetector";
    input.value = "";
    const result = app.validateNumericInput(input, { label: "Кастомная подпись" });
    check(result.error.indexOf("Кастомная подпись") !== -1,
      "явный spec.label обязан иметь приоритет над DOM: " + result.error);
  }

  // 5) Поле без метки в DOM по-прежнему падает на техническое имя (старое поведение для
  //    страниц/полей без <label for>).
  {
    const { app, elements } = freshEnv();
    const input = elements.orphanField = makeElement("input");
    input.name = "orphanField";
    input.value = "";
    const result = app.validateNumericInput(input, {});
    check(result.error.indexOf("orphanField") !== -1,
      "без DOM-метки должно остаться техническое имя: " + result.error);
  }

  if (failures.length) {
    for (const f of failures) console.log("FAIL: " + f);
    process.exit(1);
  }
  console.log("js ok");
})();
'''


def main() -> int:
    if not APP_JS.exists():
        print("smoke_setup_field_labels failed: data_raw/app.js not found")
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        harness = Path(tmp) / "harness.js"
        harness.write_text(DRIVER, encoding="utf-8")
        proc = subprocess.run(["node", str(harness), str(APP_JS)], capture_output=True, text=True)
    if proc.returncode != 0:
        print("smoke_setup_field_labels failed:")
        print(proc.stdout)
        print(proc.stderr)
        return 1
    print("setup field labels (DOM label lookup) smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
