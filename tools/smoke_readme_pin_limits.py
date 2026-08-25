#!/usr/bin/env python3
"""Проверяет, что README.md содержит раздел про ограничения выводов ESP32
и что упомянутые в нём номера пинов совпадают с Samovar_pin.h."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
PIN_HEADER = ROOT / "Samovar_pin.h"

SECTION_HEADING = "### Ограничения выводов ESP32"
HARDWARE_HEADING = "### Аппаратные"
SOFTWARE_HEADING = "### Программные"

errors = []

readme_text = README.read_text(encoding="utf-8")

# 1. Раздел присутствует и стоит между "### Аппаратные" и "### Программные".
hw_pos = readme_text.find(HARDWARE_HEADING)
section_pos = readme_text.find(SECTION_HEADING)
sw_pos = readme_text.find(SOFTWARE_HEADING)

if hw_pos == -1:
  errors.append(f"README.md: не найден заголовок {HARDWARE_HEADING!r}")
if section_pos == -1:
  errors.append(f"README.md: не найден заголовок {SECTION_HEADING!r}")
if sw_pos == -1:
  errors.append(f"README.md: не найден заголовок {SOFTWARE_HEADING!r}")

if hw_pos != -1 and section_pos != -1 and sw_pos != -1:
  if not (hw_pos < section_pos < sw_pos):
    errors.append(
      "README.md: раздел 'Ограничения выводов ESP32' должен быть между "
      "'### Аппаратные' и '### Программные' "
      f"(позиции: hw={hw_pos}, section={section_pos}, sw={sw_pos})"
    )

# Текст самого раздела (от его заголовка до следующего "### ").
section_text = ""
if section_pos != -1:
  next_heading = readme_text.find("### ", section_pos + len(SECTION_HEADING))
  section_text = readme_text[section_pos: next_heading if next_heading != -1 else len(readme_text)]

# 2. В тексте раздела упомянуты все ключевые выводы и требование внешней подтяжки.
REQUIRED_NUMBERS = ["34", "35", "36", "39", "15", "47"]
for number in REQUIRED_NUMBERS:
  if not re.search(r"(?<!\d)" + re.escape(number) + r"(?!\d)", section_text):
    errors.append(f"README.md: раздел не упоминает вывод {number}")

if "10 кОм" not in section_text:
  errors.append("README.md: раздел не упоминает требование '10 кОм'")
if "внешн" not in section_text.lower():
  errors.append("README.md: раздел не упоминает требование внешней подтяжки ('внешн...')")

# 3. Кросс-проверка с кодом: парсим #define из Samovar_pin.h по веткам плат.
pin_text = PIN_HEADER.read_text(encoding="utf-8")


def extract_board_block(text: str, board_marker: str) -> str:
  """Возвращает текст блока #elif/#if BOARD == <board_marker> ... до следующего #elif/#else."""
  start_match = re.search(r"#(?:if|elif)\s+BOARD\s*==\s*" + re.escape(board_marker) + r"\b", text)
  if not start_match:
    return ""
  start = start_match.end()
  next_branch = re.search(r"\n#(?:elif|else)\b", text[start:])
  end = start + next_branch.start() if next_branch else len(text)
  return text[start:end]


def find_define(block: str, name: str) -> str | None:
  match = re.search(r"#define\s+" + re.escape(name) + r"\s+(-?\d+)", block)
  return match.group(1) if match else None


devkit_block = extract_board_block(pin_text, "DEVKIT")
lilygo_block = extract_board_block(pin_text, "LILYGO")
s3_block = extract_board_block(pin_text, "ESP32S3")

if not devkit_block:
  errors.append("Samovar_pin.h: не найдена ветка BOARD == DEVKIT")
if not lilygo_block:
  errors.append("Samovar_pin.h: не найдена ветка BOARD == LILYGO")
if not s3_block:
  errors.append("Samovar_pin.h: не найдена ветка BOARD == ESP32S3")

CODE_CHECKS = [
  ("ALARM_BTN_PIN (DEVKIT)", devkit_block, "ALARM_BTN_PIN", "35"),
  ("WATERSENSOR_PIN (DEVKIT)", devkit_block, "WATERSENSOR_PIN", "36"),
  ("RELE_CHANNEL2 (DEVKIT)", devkit_block, "RELE_CHANNEL2", "15"),
  ("ENC_CLK (LILYGO)", lilygo_block, "ENC_CLK", "35"),
  ("ENC_DT (LILYGO)", lilygo_block, "ENC_DT", "39"),
  ("ENC_SW (LILYGO)", lilygo_block, "ENC_SW", "36"),
  ("BTN_PIN (ESP32S3)", s3_block, "BTN_PIN", "47"),
]

code_values = {}
for label, block, define_name, expected_value in CODE_CHECKS:
  if not block:
    continue
  actual_value = find_define(block, define_name)
  if actual_value is None:
    errors.append(f"Samovar_pin.h: не найден #define {define_name} в ветке для {label}")
    continue
  if actual_value != expected_value:
    errors.append(
      f"Samovar_pin.h: {define_name} для {label} = {actual_value}, "
      f"ожидалось {expected_value} (или README.md устарел)"
    )
  code_values[define_name] = actual_value

# Привязка числа к конкретному месту в тексте, а не "число встречается где-то в разделе":
# несколько пинов совпадают числом (например, 36 упомянут в трёх разных пунктах),
# поэтому просто искать цифру в section_text недостаточно - точечная подмена одного
# упоминания не будет поймана. Ниже сверяем конкретные фразы с конкретными #define.
CONTEXT_CHECKS = [
  ("ALARM_BTN_PIN (DEVKIT)", "аварийной кнопки (GPIO{ALARM_BTN_PIN} на DEVKIT)"),
  ("WATERSENSOR_PIN (DEVKIT)", "датчика протока (GPIO{WATERSENSOR_PIN} на DEVKIT) обязателен"),
  ("RELE_CHANNEL2 (DEVKIT)", "GPIO{RELE_CHANNEL2} и другие strapping"),
  ("BTN_PIN (ESP32S3)", "кнопка меню (GPIO{BTN_PIN})"),
  (
    "ENC_CLK/ENC_DT/ENC_SW (LILYGO)",
    "энкодера LILYGO (GPIO{ENC_CLK}/{ENC_DT}/{ENC_SW})",
  ),
]

for label, template in CONTEXT_CHECKS:
  try:
    expected_snippet = template.format(**code_values)
  except KeyError as exc:
    errors.append(f"Samovar_pin.h: не удалось определить пин {exc} для проверки {label}")
    continue
  if expected_snippet not in section_text:
    errors.append(
      f"README.md: раздел не содержит фрагмент {expected_snippet!r} "
      f"(сверка {label} с Samovar_pin.h)"
    )

if errors:
  print("README pin limits smoke check failed:")
  for error in errors:
    print(f" - {error}")
  sys.exit(1)

print("README pin limits smoke check passed")
