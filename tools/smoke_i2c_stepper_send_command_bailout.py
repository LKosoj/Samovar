#!/usr/bin/env python3
"""The v3 FakeWire operation gate proves retry of one exact command frame/sequence."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
result = subprocess.run(
    [sys.executable, str(ROOT / "tools/smoke_i2c_operation_results.py")],
    check=False)
raise SystemExit(result.returncode)
