#!/usr/bin/env python3
import sys
from pathlib import Path

from smoke_helpers import extract_braced_block_after, extract_function_body

ROOT = Path(__file__).resolve().parents[1]
errors = []

nbk_text = (ROOT / "nbk.h").read_text(encoding="utf-8", errors="ignore")

# [SOLUTIONS_2026-08-24.md, Уровень 3 п.7 — ОТМЕНЕНО 24.08.2026 как ложная
# находка] nbk_overflow_happened уже сбрасывается в двух местах: внутри
# commitProgram (после того как приводы подтвердили новую программу) и в
# nbk_resume_work_after_safe_wait() (после выхода из безопасного ожидания).
# Оба пути покрывают единственную точку чтения флага (nbk.h ~908). Пин
# защищает эти два сброса от потери при будущем рефакторинге.
try:
    commit_body, _ = extract_braced_block_after(
        nbk_text, "if (nbkActuatorCommand.commitProgram) {"
    )
except ValueError as exc:
    errors.append(str(exc))
    commit_body = ""

if commit_body and "nbk_overflow_happened = false;" not in commit_body:
    errors.append(
        "commitProgram block no longer resets nbk_overflow_happened "
        "(SOLUTIONS_2026-08-24.md, Уровень 3 п.7)"
    )

try:
    resume_body = extract_function_body(
        nbk_text, "void nbk_resume_work_after_safe_wait()"
    )
except ValueError as exc:
    errors.append(str(exc))
    resume_body = ""

if resume_body and "nbk_overflow_happened = false;" not in resume_body:
    errors.append(
        "nbk_resume_work_after_safe_wait() no longer resets nbk_overflow_happened"
    )

# [SOLUTIONS_2026-08-24.md, Н2] nbk_dP теперь инициализируется
# NBK_DP_DEFAULT - симметрично соседней "float nbk_dM = NBK_DM_DEFAULT;".
# Значение перезаписывается из nbkSessionConfig до первого использования, но
# начальный дефолт не должен молча разъехаться с соседним полем.
if "float nbk_dP = NBK_DP_DEFAULT;" not in nbk_text:
    errors.append("nbk_dP no longer defaults to NBK_DP_DEFAULT (symmetry with nbk_dM)")

if errors:
    print("NBK overflow flag reset / nbk_dP default smoke check failed:")
    for err in errors:
        print(f" - {err}")
    sys.exit(1)

print("NBK overflow flag reset / nbk_dP default smoke check passed")
