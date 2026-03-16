# Step 2 Regression Test Run Log

**Date:** 2026-03-16  
**Task:** Step 2.6a - Full regression test suite  
**Scope:** All Step 2 tests

---

## Summary

| Metric | Value |
|--------|-------|
| Total Tests | 6 |
| Passed | 6 |
| Failed | 0 |
| Pass Rate | 100% |
| Duration | 1.85s |

**Status:** ✅ ALL TESTS PASSED

---

## Test Results

### 1. test_state_contracts_baseline.py

- **Status:** ✅ PASSED
- **Purpose:** Verify state/status/mode numeric values unchanged from baseline
- **Details:** Checks exact numeric values for SamovarStatusInt, sam_command_sync, Samovar_Mode, startval

### 2. test_mode_switching_behavior.py

- **Status:** ✅ PASSED
- **Purpose:** Verify correct mode switching behavior
- **Details:** Tests transitions between all 7 modes (RECT, DIST, BEER, BK, NBK, SUVID, LUA), runtime initialization, reset on mode change

### 3. test_reset_pipeline_invariant.py

- **Status:** ✅ PASSED
- **Purpose:** Verify reset pipeline invariants
- **Details:** Tests runtime status reset, power/stepper/I2C pump cleanup, Lua state reset, menu/UI reset, sensor counters reset

### 4. test_frontend_contracts_smoke.py

- **Status:** ✅ PASSED
- **Purpose:** Verify frontend contracts (AJAX JSON keys, HTML form fields)
- **Details:** Checks 55 AJAX JSON keys, form fields in 4 HTML files, 6 common.js functions

### 5. test_frontend_interface_correctness.py

- **Status:** ✅ PASSED
- **Purpose:** Verify frontend interface correctness
- **Details:** Tests JavaScript syntax, HTML structure, common.js function accessibility

### 6. test_common_js_extraction_smoke.py

- **Status:** ✅ PASSED
- **Purpose:** Verify common.js extraction
- **Details:** Checks common.js exists (20599 bytes, 28 functions), 9 HTML files reference it, 0 duplicate function definitions

---

## Raw Test Output

```text
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-8.3.4, pluggy-1.6.0
PySide6 6.10.2 -- Qt runtime 6.10.2 -- Qt compiled 6.10.2
rootdir: /srv/git_projects/Samovar
configfile: pytest.ini
plugins: anyio-4.12.1, asyncio-0.24.0, qt-4.3.1
asyncio: mode=Mode.STRICT, default_loop_scope=None
collecting ... collected 6 items

tools/tests/test_state_contracts_baseline.py::main PASSED                [ 16%]
tools/tests/test_mode_switching_behavior.py::main PASSED                 [ 33%]
tools/tests/test_reset_pipeline_invariant.py::main PASSED                [ 50%]
tools/tests/test_frontend_contracts_smoke.py::main PASSED                [ 66%]
tools/tests/test_frontend_interface_correctness.py::main PASSED          [ 83%]
tools/tests/test_common_js_extraction_smoke.py::main PASSED              [100%]

=============================== warnings summary ===============================
tools/tests/test_reset_pipeline_invariant.py::main
  /usr/local/lib/python3.12/dist-packages/_pytest/python.py:163: PytestReturnNotNoneWarning: Expected None, but tools/tests/test_reset_pipeline_invariant.py::main returned 0, which will be an error in a future version of pytest.  Did you mean to use `assert` instead of `return`?
    warnings.warn(

tools/tests/test_frontend_contracts_smoke.py::main
  /usr/local/lib/python3.12/dist-packages/_pytest/python.py:163: PytestReturnNotNoneWarning: Expected None, but tools/tests/test_frontend_contracts_smoke.py::main returned 0, which will be an error in a future version of pytest.  Did you mean to use `assert` instead of `return`?
    warnings.warn(

tools/tests/test_frontend_interface_correctness.py::main
  /usr/local/lib/python3.12/dist-packages/_pytest/python.py:163: PytestReturnNotNoneWarning: Expected None, but tools/tests/test_frontend_interface_correctness.py::main returned 0, which will be an error in a future version of pytest.  Did you mean to use `assert` instead of `return`?
    warnings.warn(

tools/tests/test_common_js_extraction_smoke.py::main
  /usr/local/lib/python3.12/dist-packages/_pytest/python.py:163: PytestReturnNotNoneWarning: Expected None, but tools/tests/test_common_js_extraction_smoke.py::main returned 0, which will be an error in a future version of pytest.  Did you mean to use `assert` instead of `return`?
    warnings.warn(

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================== 6 passed, 4 warnings in 1.85s =========================
```

---

## Acceptance Criteria Verification

| Criterion | Status | Evidence |
|-----------|--------|----------|
| All Step 2 regression tests pass (100% pass rate) | ✅ Done | 6/6 tests passed, pytest output shows 100% pass rate |
| Test run log saved to docs/result/delivery/regression_run_log.md | ✅ Done | This document created with full test results |

---

## Notes

- Warnings are pytest deprecation warnings about `return` vs `assert` in test functions - these are informational and do not affect test results
- All tests completed in 1.85 seconds
- No test failures detected

---

**Next Step:** Proceed to Step 2.6b (Build matrix verification) or Step 2.6c (Final closure report)
