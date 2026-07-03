#!/usr/bin/env python3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BREWXML_PAGE = ROOT / "data" / "brewxml.htm"
INDEX_PAGE = ROOT / "data" / "index.htm"

errors = []


def read_text(path):
  if not path.exists():
    errors.append(f"{path.relative_to(ROOT)} not found")
    return ""
  return path.read_text(encoding="utf-8", errors="ignore")


brewxml = read_text(BREWXML_PAGE)
index = read_text(INDEX_PAGE)

if brewxml:
  if re.search(r"<[A-Za-z][^>]*\bclassName\s*=", brewxml):
    errors.append("data/brewxml.htm still uses React-style className in static HTML")
  if "margin: 20 auto" in brewxml:
    errors.append("data/brewxml.htm still has unitless margin: 20 auto")
  if 'class="ingredients"' not in brewxml:
    errors.append("data/brewxml.htm missing class=\"ingredients\" sections")
  if 'id=\'WProgram\' name=\'WProgram\' style="display: none;"' not in brewxml:
    errors.append("data/brewxml.htm hidden WProgram textarea still reserves layout space")
  if re.search(r"<textarea[^>]+id=['\"]WProgram['\"][^>]+visibility:\s*hidden", brewxml):
    errors.append("data/brewxml.htm WProgram textarea still uses visibility:hidden")

if index:
  if '"#FFF;"' in index or "'#FFF;'" in index:
    errors.append("data/index.htm still contains invalid #FFF; color token")
  if "margin-right: 100;" in index:
    errors.append("data/index.htm still has unitless margin-right: 100")
  for token in [
    "for (let z = 0; z < varr.length; z++)",
    "let bckg = \"#fff\"",
    "for (let q = 0; q < e.length; q++)",
  ]:
    if token not in index:
      errors.append(f"data/index.htm missing HTML cleanup token: {token}")

program = read_text(ROOT / "data" / "program.htm")
if program:
  if "width: 20;" in program:
    errors.append("data/program.htm hidden textarea still has unitless width: 20")
  for token in [
    'id=\'WProgram1\' name=\'WProgram1\' style="visibility: hidden;position: absolute;width: 20px;"',
    'id=\'WProgram\' name=\'WProgram\' style="visibility: hidden;position: absolute;width: 20px;"',
  ]:
    if token not in program:
      errors.append(f"data/program.htm missing fixed hidden textarea style: {token}")

if errors:
  print("HTML cleanup smoke check failed:")
  for error in errors:
    print(f" - {error}")
  sys.exit(1)

print("HTML cleanup smoke check passed")
