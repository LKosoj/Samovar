#!/usr/bin/env python3
import re
import sys
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]
PROGRAM_PAGE = ROOT / "data" / "program.htm"

errors = []

if not PROGRAM_PAGE.exists():
  errors.append("data/program.htm not found")
  text = ""
else:
  text = PROGRAM_PAGE.read_text(encoding="utf-8", errors="ignore")

if text:
  for token in [
    "var programTemplateBaseline",
    "var currentProgramTemplateValue",
    "var programTemplateLoaded",
    "function getProgramTemplateFile(value)",
    "function updateProgramTemplateBaseline()",
    "function programTemplateDirty()",
    "function restoreProgramTemplateSelect(selectObject)",
  ]:
    if token not in text:
      errors.append(f"data/program.htm missing W7.5 template state token: {token}")

  try:
    load_file_body = extract_function_body(text, "function loadFile(e)")
  except ValueError as exc:
    errors.append(str(exc))
    load_file_body = ""
  if "updateProgramTemplateBaseline" in load_file_body:
    errors.append("data/program.htm loadFile() marks user-loaded program as clean template baseline")

  try:
    dirty_body = extract_function_body(text, "function programTemplateDirty()")
  except ValueError as exc:
    errors.append(str(exc))
    dirty_body = ""
  if dirty_body:
    for token in [
      "if (!program) return false;",
      'programTemplateLoaded ? program.value !== programTemplateBaseline : program.value !== ""',
    ]:
      if token not in dirty_body:
        errors.append(f"programTemplateDirty() missing token: {token}")

  try:
    update_percent_body = extract_function_body(text, "function updateHeadsTailsPercent(recalculate)")
  except ValueError as exc:
    errors.append(str(exc))
    update_percent_body = ""
  if update_percent_body and "recalculate !== false && typeof set_num === 'function'" not in update_percent_body:
    errors.append("updateHeadsTailsPercent() cannot suppress stale-program recalculation")

  try:
    template_body = extract_function_body(text, "async function getProgramFromFile(selectObject, options)")
  except ValueError as exc:
    errors.append(str(exc))
    template_body = ""
  if template_body:
    require_ordered_tokens(
      "program template overwrite UX",
      template_body,
      [
        "var fn = getProgramTemplateFile(value);",
        "var skipConfirm = options && options.skipConfirm;",
        "if (!fn)",
        "if (!skipConfirm && programTemplateDirty() && !confirm(",
        "var response = await fetch(fn);",
        "if (!response.ok) throw new Error",
        "var data = await response.text();",
        "updateHeadsTailsPercent(false);",
        "updateColumnParams();",
        "document.getElementById('WProgram1').value = data;",
        "calc_program();",
        "programTemplateLoaded = true;",
        "currentProgramTemplateValue = String(value);",
        "updateProgramTemplateBaseline();",
        "return true;",
        "restoreProgramTemplateSelect(selectObject);",
        'alert("Ошибка загрузки шаблона программы: " + err);',
        "return false;",
      ],
      errors,
    )

  try:
    column_body = extract_function_body(text, "function updateColumnParams()")
  except ValueError as exc:
    errors.append(str(exc))
    column_body = ""
  if column_body:
    for token in [
      'fetch("/ajax_col_params?mat=" + mat)',
      "if (!r.ok) throw new Error",
      'alert("Ошибка загрузки параметров колонны: " + err);',
    ]:
      if token not in column_body:
        errors.append(f"updateColumnParams() missing visible error handling token: {token}")
    if "console.error" in column_body:
      errors.append("updateColumnParams() still hides failures in console-only error handling")

  if re.search(r"\b(?:async\s+)?function\s+sendbutton\s*\(", text):
    errors.append("data/program.htm still defines stale local sendbutton()")
  if re.search(r"\bfetch\s*\(\s*['\"]\/command\?", text):
    errors.append("data/program.htm still calls /command through direct fetch()")
  if "getProgramFromFile(loadProgramSelect, { skipConfirm: true });" not in text:
    errors.append("program.htm initial template load is not explicitly confirm-free")

if errors:
  print("Program UX smoke check failed:")
  for error in errors:
    print(f" - {error}")
  sys.exit(1)

print("Program UX smoke check passed")
