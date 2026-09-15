#!/usr/bin/env python3
"""The pinned v3 pump has no local/singleton fallback for STOP."""

import sys
from pathlib import Path

from smoke_helpers import extract_function_body

ROOT = Path(__file__).resolve().parents[1]
I2C = (ROOT / "I2CStepper.h").read_text(encoding="utf-8")
SAMOVAR = (ROOT / "Samovar.ino").read_text(encoding="utf-8")
errors = []


def body(source: str, signature: str) -> str:
  try:
    return extract_function_body(source, signature)
  except ValueError as exc:
    errors.append(str(exc))
    return ""


stop = body(I2C, "inline bool stop_i2c_pump_confirmed()")
if "i2c_stepper_selected_pump()" not in stop or "i2c_stepper_stop(*device)" not in stop:
  errors.append("STOP must address only the selected v3 pump")
for obsolete in ("use_I2C_dev", "i2cStepperPump", "set_stepper_target("):
  if obsolete in stop:
    errors.append(f"STOP must not fall back through {obsolete}")

loss = body(I2C, "inline void i2c_stepper_note_refresh_failure")
for token in ("i2cStepperSessionMixerAddress", "i2cStepperSessionPumpAddress",
              "SendMsg(", "device.address", "device.present = false"):
  if token not in loss:
    errors.append(f"pinned-device loss must retain {token}")

executor = SAMOVAR[SAMOVAR.rfind("static OperationError execute_pending_i2c_pump"):]
executor = body(executor, "static OperationError execute_pending_i2c_pump")
if "i2c_stepper_device(command.address)" not in executor:
  errors.append("queued pump STOP must use DTO physical address")
if "i2c_stepper_stop(candidate)" not in executor:
  errors.append("queued pump STOP must send v3 STOP")

if errors:
  print("I2C pump pinned STOP smoke failed:")
  for error in errors:
    print(f" - {error}")
  sys.exit(1)
print("I2C pump pinned STOP smoke passed")
