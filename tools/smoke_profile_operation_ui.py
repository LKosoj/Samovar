#!/usr/bin/env python3
import sys
from pathlib import Path

from smoke_helpers import extract_function_body, require_ordered_tokens


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data_raw"
errors = []


def read(path):
  if not path.exists():
    errors.append(f"missing file: {path.relative_to(ROOT)}")
    return ""
  return path.read_text(encoding="utf-8", errors="ignore")


def body(source, signature):
  try:
    return extract_function_body(source, signature)
  except ValueError as error:
    errors.append(str(error))
    return ""


app = read(DATA / "app.js")
waiter = body(app, "async function waitForOperation")
program = body(app, "async function postProgram")
clear = body(app, "async function clearProgram")
acceptance = body(app, "async function readOperationAcceptance")

for token in [
  "const OPERATION_POLL_INTERVAL_MS = 250;",
  "const OPERATION_TIMEOUT_MS = 45000;",
  "function hasExactKeys(value, expectedKeys)",
  "function validateOperationPayload(value, expectedKeys, expectedOperationId, context)",
  "readOperationAcceptance: readOperationAcceptance",
  "waitForOperation: waitForOperation",
]:
  if token not in app:
    errors.append(f"shared operation contract missing token: {token}")

require_ordered_tokens(
  "strict operation waiter",
  waiter,
  [
    "const startedAt = Date.now();",
    "while (Date.now() - startedAt < OPERATION_TIMEOUT_MS)",
    "const controller = new AbortController();",
    "fetch('/ajax?operationId='",
    "if (resp.status === 503)",
    "hasExactKeys(busy, ['operationId', 'error'])",
    "busy.operationId !== operationId",
    "busy.error !== 'operation_store_busy'",
    "if (resp.status === 404)",
    "validateOperationPayload(",
    "if (result.state === 'succeeded') return result;",
    "if (result.state === 'failed')",
    "setTimeout(resolve, OPERATION_POLL_INTERVAL_MS)",
    "не завершилась за 45 секунд",
  ],
  errors,
)
for token in [
  "['operationId', 'state', 'error']",
  "result.state !== 'queued'",
  "result.error !== 'none'",
]:
  if token not in acceptance:
    errors.append(f"save acceptance contract missing token: {token}")

require_ordered_tokens(
  "program mutation waits for terminal state",
  program,
  [
    "if (programMutationPending)",
    "programMutationPending = true;",
    "fetch('/program', { method: 'POST', body: body })",
    "if (!result.queued)",
    "await waitForOperation(result.operationId);",
    "result.state = 'succeeded';",
    "programMutationPending = false;",
  ],
  errors,
)
if program.count("fetch('/program'") != 1:
  errors.append("postProgram must issue the mutation request exactly once")

require_ordered_tokens(
  "program clear waits for terminal state",
  clear,
  [
    "if (programMutationPending)",
    "programMutationPending = true;",
    "fetch('/program', { method: 'POST', body: body })",
    "await waitForOperation(result.operationId);",
    "notify('Программа очищена.', 2);",
    "programMutationPending = false;",
  ],
  errors,
)
if clear.count("fetch('/program'") != 1:
  errors.append("clearProgram must issue the mutation request exactly once")

setup = read(DATA / "setup.htm")
submit = body(setup, "async function submitSetupForm")
require_ordered_tokens(
  "setup waits before clean state and redirect",
  submit,
  [
    "if (form.dataset.submitting === 'true') return false;",
    "form.dataset.dirty = 'true';",
    "button.disabled = true;",
    "fetch('/save', { method: 'POST', body: new FormData(form) })",
    "if (!response.ok)",
    "SamovarApp.readOperationAcceptance(response)",
    "SamovarApp.waitForOperation(accepted.operationId)",
    "form.dataset.editRevision !== submittedRevision",
    "новые изменения формы ещё не сохранены",
    "form.dataset.dirty = 'false';",
    "window.location.assign('/');",
    "form.dataset.submitting = 'false';",
    "button.disabled = false;",
  ],
  errors,
)
if submit.count("fetch('/save'") != 1:
  errors.append("submitSetupForm must issue the mutation request exactly once")
for token in [
  "setupForm.dataset.editRevision = '0';",
  "setupForm.dataset.editRevision = String(Number(setupForm.dataset.editRevision) + 1);",
  "setupForm.addEventListener('input', markSetupDirty);",
  "setupForm.addEventListener('change', markSetupDirty);",
]:
  if token not in setup:
    errors.append(f"setup edit revision contract missing token: {token}")

pages = [
  "setup.htm", "program.htm", "index.htm", "beer.htm", "distiller.htm",
  "bk.htm", "nbk.htm", "brewxml.htm",
]
for name in pages:
  text = read(DATA / name)
  if "Изменение программы принято в обработку" in text:
    errors.append(f"{name} still reports queued program state as success")

if errors:
  print("Profile operation UI smoke failed:")
  for error in errors:
    print(f" - {error}")
  sys.exit(1)

print("Profile operation UI smoke passed")
