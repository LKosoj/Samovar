#!/usr/bin/env python3
import re
import sys
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens

ROOT = Path(__file__).resolve().parents[1]
PROGRAM_PAGE = ROOT / "data_raw" / "program.htm"

errors = []

if not PROGRAM_PAGE.exists():
  errors.append("data_raw/program.htm not found")
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
    "function parseProgramFileText(text)",
    "function programBodyForUnit(parsed, unit)",
    "function applyParsedProgramText(parsed)",
    "function programVoltsToWatts(volts, heaterMaxPwr)",
    "function formatDualProgramFile(body, unit)",
    "function programPowerUnitFitsRegulator()",
    "function scaleProgramSpeedsByType(programLines, typeChars, targetMlH)",
    "function wattsToProgramVolts(watts, heaterMaxPwr)",
    'id="programPowerUnitHint"',
    'id="coldiam"',
    "function onColumnDiameterChange(selectObject)",
    "function rememberUnscaledProgram(body, unit)",
    "rememberUnscaledProgram(body, unit)",
    "Math.round(Number(ll) * 1000)",
    "function restoreProgramTemplateSelect(selectObject)",
    'id="colSpeedClampNote"',
    "первая строка программы должна задавать абсолютную мощность/напряжение",
  ]:
    if token not in text:
      errors.append(f"data_raw/program.htm missing W7.5 template state token: {token}")

  try:
    apply_recommended_body = extract_function_body(text, "function applyRecommendedSpeeds(options)")
  except ValueError as exc:
    errors.append(str(exc))
    apply_recommended_body = ""
  if apply_recommended_body:
    # [В2] Ветка "C после C" не должна сбрасывать накопленную подстройку
    # предзахлёба абсолютной уставкой - проверяем, что она идёт РАНЬШЕ
    # основного каскада выбора мощности (let rPwr = 0;).
    require_ordered_tokens(
      "applyRecommendedSpeeds() C-after-C guard order",
      apply_recommended_body,
      [
        "if (type == 'C' && prevType === 'C')",
        "let rPwr = 0;",
      ],
      errors,
    )

  try:
    program_body_for_unit_body = extract_function_body(text, "function programBodyForUnit(parsed, unit)")
  except ValueError as exc:
    errors.append(str(exc))
    program_body_for_unit_body = ""
  if program_body_for_unit_body and "lastAbsoluteVolts" not in program_body_for_unit_body:
    errors.append("programBodyForUnit() missing lastAbsoluteVolts tracking for delta rows")

  try:
    load_file_body = extract_function_body(text, "function loadFile(e)")
  except ValueError as exc:
    errors.append(str(exc))
    load_file_body = ""
  if "updateProgramTemplateBaseline" in load_file_body:
    errors.append("data_raw/program.htm loadFile() marks user-loaded program as clean template baseline")

  try:
    dirty_body = extract_function_body(text, "function programTemplateDirty()")
  except ValueError as exc:
    errors.append(str(exc))
    dirty_body = ""
  if dirty_body:
    # Упрощено до сравнения с baseline: programTemplateBaseline пуст ровно до
    # первого updateProgramTemplateBaseline(), поэтому ветка по
    # programTemplateLoaded стала не нужна - см. data_raw/program.htm.
    for token in [
      "if (!program) return false;",
      "return program.value !== programTemplateBaseline;",
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
        "var parsed = parseProgramFileText(data);",
        "var err = validateProgramFileText(data);",
        "updateHeadsTailsPercent(false);",
        "applyParsedProgramText(parsed);",
        "programTemplateLoaded = true;",
        "currentProgramTemplateValue = String(value);",
        "await updateColumnParams();",
        "applyRecommendedSpeeds({ silent: true });",
        "updateProgramTemplateBaseline();",
        "updateProgramPowerUnitHint();",
        "return true;",
        "restoreProgramTemplateSelect(selectObject);",
        'SamovarApp.showRequestError("Ошибка загрузки шаблона программы: " + err);',
        "return false;",
      ],
      errors,
    )

  try:
    column_body = extract_function_body(text, "async function updateColumnParams()")
  except ValueError as exc:
    errors.append(str(exc))
    column_body = ""
  if column_body:
    for token in [
      "SamovarApp.readNumericInput(matSelect",
      "SamovarApp.readNumericInput(diamSelect",
      "'&diam=' + encodeURIComponent(diam.text)",
      "if (!response.ok)",
      "SamovarApp.responseErrorText",
      "SamovarApp.showRequestError",
    ]:
      if token not in column_body:
        errors.append(f"updateColumnParams() missing visible error handling token: {token}")
    if "console.error" in column_body:
      errors.append("updateColumnParams() still hides failures in console-only error handling")

  if re.search(r"\b(?:async\s+)?function\s+sendbutton\s*\(", text):
    errors.append("data_raw/program.htm still defines stale local sendbutton()")
  if re.search(r"\bfetch\s*\(\s*['\"]\/command\?", text):
    errors.append("data_raw/program.htm still calls /command through direct fetch()")
  if "getProgramFromFile(loadProgramSelect, { skipConfirm: true });" not in text:
    errors.append("program.htm initial template load is not explicitly confirm-free")
  if "buildEditorBodyFromDeviceProgram" in text or 'id="deviceProgramNotice"' in text:
    errors.append("program.htm must open the fruit template, not import the device program")
  if '<option value="0">Фрукты</option>' not in text:
    errors.append("program.htm default template option is not Фрукты")

  for token in [
    'id="programSummary"',
    'id="summaryHeadsAs"',
    'id="summaryHeadsVolume"',
    'id="summaryHeadsTime"',
    'id="summaryHeadsDistribution"',
    'id="summaryBodyAs"',
    'id="summaryBodyVolume"',
    'id="summaryBodyTime"',
    'id="summaryBodyDistribution"',
    'id="summaryTailsAs"',
    'id="summaryTailsVolume"',
    'id="summaryTailsTime"',
    'id="summaryTailsDistribution"',
    'id="summaryTotalVolume"',
    'id="summaryTotalTime"',
    'id="summaryPauseTime"',
    "function renderProgramSummary(summary)",
    "programErrorMessage",
  ]:
    if token not in text:
      errors.append(f"data_raw/program.htm missing fraction summary token: {token}")

  for name in ("program_fruit.txt", "program_grain.txt", "program_shugar.txt"):
    tpl = (ROOT / "data_raw" / name).read_text(encoding="utf-8")
    if "# unit=" in tpl:
      errors.append(f"data_raw/{name} must not use a # unit= header")
    data_lines = [ln for ln in tpl.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    if not data_lines or any(len(ln.split(";")) != 6 for ln in data_lines):
      errors.append(f"data_raw/{name} must store both volts and watts (6 fields)")

if errors:
  print("Program UX smoke check failed:")
  for error in errors:
    print(f" - {error}")
  sys.exit(1)

print("Program UX smoke check passed")
