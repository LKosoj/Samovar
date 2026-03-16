# Step 2 Regression Run Log

**Date:** 2026-03-16  
**Task:** Step 2.6a - Full regression test suite  
**Scope:** Required Step 2 tool-tests from the task statement

---

## Summary

| Metric | Value |
|--------|-------|
| Total Tests | 6 |
| Passed | 6 |
| Failed | 0 |
| Pass Rate | 100% |
| Duration | 8s |

**Status:** PASSED

---

## Executed Test Set

1. `python3 tools/tests/test_state_contracts_baseline.py`
2. `python3 tools/tests/test_mode_switching_behavior.py`
3. `python3 tools/tests/test_reset_pipeline_invariant.py`
4. `python3 tools/tests/test_web_mode_integration.py`
5. `python3 tools/tests/test_menu_mode_integration.py`
6. `python3 tools/tests/test_lua_mode_selection.py`

---

## Acceptance Criteria Verification

| Criterion | Status | Evidence |
|-----------|--------|----------|
| All Step 2 regression tests pass (100% pass rate) | PASSED | 6/6 tests passed |
| Test run log saved to docs/result/delivery/regression_run_log.md | PASSED | This document contains the full raw output below |

---

## Raw Test Output

```text
========================================================================
Command: `python3 tools/tests/test_state_contracts_baseline.py`
========================================================================

========================================================================
State contracts baseline test
========================================================================

[1] Verifying SamovarStatusInt exact numeric baseline...
    ✓ SamovarStatusInt={'SAMOVAR_STATUS_OFF': 0, 'SAMOVAR_STATUS_RECTIFICATION_RUN': 10, 'SAMOVAR_STATUS_RECTIFICATION_WAIT': 15, 'SAMOVAR_STATUS_RECTIFICATION_COMPLETE': 20, 'SAMOVAR_STATUS_CALIBRATION': 30, 'SAMOVAR_STATUS_RECTIFICATION_PAUSE': 40, 'SAMOVAR_STATUS_RECTIFICATION_WARMUP': 50, 'SAMOVAR_STATUS_RECTIFICATION_STABILIZING': 51, 'SAMOVAR_STATUS_RECTIFICATION_STABILIZED': 52, 'SAMOVAR_STATUS_DISTILLATION': 1000, 'SAMOVAR_STATUS_BEER': 2000, 'SAMOVAR_STATUS_BK': 3000, 'SAMOVAR_STATUS_NBK': 4000}

[2] Verifying startval exact numeric baseline...
    ✓ startval={'SAMOVAR_STARTVAL_RECT_IDLE': 0, 'SAMOVAR_STARTVAL_RECT_PROGRAM_RUNNING': 1, 'SAMOVAR_STARTVAL_RECT_PROGRAM_COMPLETE': 2, 'SAMOVAR_STARTVAL_RECT_STOPPED': 3, 'SAMOVAR_STARTVAL_CALIBRATION': 100, 'SAMOVAR_STARTVAL_DISTILLATION_ENTRY': 1000, 'SAMOVAR_STARTVAL_BEER_ENTRY': 2000, 'SAMOVAR_STARTVAL_BEER_MALT_HEATING': 2001, 'SAMOVAR_STARTVAL_BEER_MALT_WAIT': 2002, 'SAMOVAR_STARTVAL_BK_ENTRY': 3000, 'SAMOVAR_STARTVAL_NBK_ENTRY': 4000, 'SAMOVAR_STARTVAL_NBK_PROGRAM_RUNNING': 4001}

[3] Verifying sam_command_sync exact numeric baseline...
    ✓ sam_command_sync={'SAMOVAR_NONE': 0, 'SAMOVAR_START': 1, 'SAMOVAR_POWER': 2, 'SAMOVAR_RESET': 3, 'CALIBRATE_START': 4, 'CALIBRATE_STOP': 5, 'SAMOVAR_PAUSE': 6, 'SAMOVAR_CONTINUE': 7, 'SAMOVAR_SETBODYTEMP': 8, 'SAMOVAR_DISTILLATION': 9, 'SAMOVAR_BEER': 10, 'SAMOVAR_BEER_NEXT': 11, 'SAMOVAR_BK': 12, 'SAMOVAR_NBK': 13, 'SAMOVAR_SELF_TEST': 14, 'SAMOVAR_DIST_NEXT': 15, 'SAMOVAR_NBK_NEXT': 16}

[4] Verifying Samovar_Mode exact numeric baseline...
    ✓ Samovar_Mode={'SAMOVAR_RECTIFICATION_MODE': 0, 'SAMOVAR_DISTILLATION_MODE': 1, 'SAMOVAR_BEER_MODE': 2, 'SAMOVAR_BK_MODE': 3, 'SAMOVAR_NBK_MODE': 4, 'SAMOVAR_SUVID_MODE': 5, 'SAMOVAR_LUA_MODE': 6}

========================================================================
State contracts baseline: PASS
========================================================================

Result: PASSED


========================================================================
Command: `python3 tools/tests/test_mode_switching_behavior.py`
========================================================================

========================================================================
Mode switching behavior harness
========================================================================

[1] Verifying static mode-switch contract...
    ✓ handleSaveProcessSettings resets runtime, reloads defaults and rebinds routes
    ✓ load_default_program_for_mode selects beer/suvid, dist, nbk and rect families
    ✓ change_samovar_mode exposes dedicated pages and rect fallback runtime
    ✓ get_lua_mode_name keeps beer/dist/bk/nbk branches and rect fallback

[2] Compiling and running mode-switch matrix harness...
    ✓ Harness compiled
    rect_to_dist|ok|saved=1|runtime=1|route=/distiller.htm|program=dist|lua=/dist.lua|ns=sam_dist
    rect_to_beer|ok|saved=2|runtime=2|route=/beer.htm|program=beer|lua=/beer.lua|ns=sam_beer
    rect_to_bk|ok|saved=3|runtime=3|route=/bk.htm|program=rect|lua=/bk.lua|ns=sam_bk
    rect_to_nbk|ok|saved=4|runtime=4|route=/nbk.htm|program=nbk|lua=/nbk.lua|ns=sam_nbk
    rect_to_suvid|ok|saved=5|runtime=0|route=/index.htm|program=beer|lua=/rectificat.lua|ns=sam_suvid
    rect_to_lua|ok|saved=6|runtime=0|route=/index.htm|program=rect|lua=/rectificat.lua|ns=sam_lua
    dist_to_rect|ok|saved=0|runtime=0|route=/index.htm|program=rect|lua=/rectificat.lua|ns=sam_rect
    dist_to_beer|ok|saved=2|runtime=2|route=/beer.htm|program=beer|lua=/beer.lua|ns=sam_beer
    dist_to_bk|ok|saved=3|runtime=3|route=/bk.htm|program=rect|lua=/bk.lua|ns=sam_bk
    dist_to_nbk|ok|saved=4|runtime=4|route=/nbk.htm|program=nbk|lua=/nbk.lua|ns=sam_nbk
    dist_to_suvid|ok|saved=5|runtime=0|route=/index.htm|program=beer|lua=/rectificat.lua|ns=sam_suvid
    dist_to_lua|ok|saved=6|runtime=0|route=/index.htm|program=rect|lua=/rectificat.lua|ns=sam_lua
    beer_to_rect|ok|saved=0|runtime=0|route=/index.htm|program=rect|lua=/rectificat.lua|ns=sam_rect
    beer_to_dist|ok|saved=1|runtime=1|route=/distiller.htm|program=dist|lua=/dist.lua|ns=sam_dist
    beer_to_bk|ok|saved=3|runtime=3|route=/bk.htm|program=rect|lua=/bk.lua|ns=sam_bk
    beer_to_nbk|ok|saved=4|runtime=4|route=/nbk.htm|program=nbk|lua=/nbk.lua|ns=sam_nbk
    beer_to_suvid|ok|saved=5|runtime=0|route=/index.htm|program=beer|lua=/rectificat.lua|ns=sam_suvid
    beer_to_lua|ok|saved=6|runtime=0|route=/index.htm|program=rect|lua=/rectificat.lua|ns=sam_lua
    bk_to_rect|ok|saved=0|runtime=0|route=/index.htm|program=rect|lua=/rectificat.lua|ns=sam_rect
    bk_to_dist|ok|saved=1|runtime=1|route=/distiller.htm|program=dist|lua=/dist.lua|ns=sam_dist
    bk_to_beer|ok|saved=2|runtime=2|route=/beer.htm|program=beer|lua=/beer.lua|ns=sam_beer
    bk_to_nbk|ok|saved=4|runtime=4|route=/nbk.htm|program=nbk|lua=/nbk.lua|ns=sam_nbk
    bk_to_suvid|ok|saved=5|runtime=0|route=/index.htm|program=beer|lua=/rectificat.lua|ns=sam_suvid
    bk_to_lua|ok|saved=6|runtime=0|route=/index.htm|program=rect|lua=/rectificat.lua|ns=sam_lua
    nbk_to_rect|ok|saved=0|runtime=0|route=/index.htm|program=rect|lua=/rectificat.lua|ns=sam_rect
    nbk_to_dist|ok|saved=1|runtime=1|route=/distiller.htm|program=dist|lua=/dist.lua|ns=sam_dist
    nbk_to_beer|ok|saved=2|runtime=2|route=/beer.htm|program=beer|lua=/beer.lua|ns=sam_beer
    nbk_to_bk|ok|saved=3|runtime=3|route=/bk.htm|program=rect|lua=/bk.lua|ns=sam_bk
    nbk_to_suvid|ok|saved=5|runtime=0|route=/index.htm|program=beer|lua=/rectificat.lua|ns=sam_suvid
    nbk_to_lua|ok|saved=6|runtime=0|route=/index.htm|program=rect|lua=/rectificat.lua|ns=sam_lua
    suvid_to_rect|ok|saved=0|runtime=0|route=/index.htm|program=rect|lua=/rectificat.lua|ns=sam_rect
    suvid_to_dist|ok|saved=1|runtime=1|route=/distiller.htm|program=dist|lua=/dist.lua|ns=sam_dist
    suvid_to_beer|ok|saved=2|runtime=2|route=/beer.htm|program=beer|lua=/beer.lua|ns=sam_beer
    suvid_to_bk|ok|saved=3|runtime=3|route=/bk.htm|program=rect|lua=/bk.lua|ns=sam_bk
    suvid_to_nbk|ok|saved=4|runtime=4|route=/nbk.htm|program=nbk|lua=/nbk.lua|ns=sam_nbk
    suvid_to_lua|ok|saved=6|runtime=0|route=/index.htm|program=rect|lua=/rectificat.lua|ns=sam_lua
    lua_to_rect|ok|saved=0|runtime=0|route=/index.htm|program=rect|lua=/rectificat.lua|ns=sam_rect
    lua_to_dist|ok|saved=1|runtime=1|route=/distiller.htm|program=dist|lua=/dist.lua|ns=sam_dist
    lua_to_beer|ok|saved=2|runtime=2|route=/beer.htm|program=beer|lua=/beer.lua|ns=sam_beer
    lua_to_bk|ok|saved=3|runtime=3|route=/bk.htm|program=rect|lua=/bk.lua|ns=sam_bk
    lua_to_nbk|ok|saved=4|runtime=4|route=/nbk.htm|program=nbk|lua=/nbk.lua|ns=sam_nbk
    lua_to_suvid|ok|saved=5|runtime=0|route=/index.htm|program=beer|lua=/rectificat.lua|ns=sam_suvid
    mode_switching_behavior|ok

========================================================================
Mode switching behavior: PASS
========================================================================

Result: PASSED


========================================================================
Command: `python3 tools/tests/test_reset_pipeline_invariant.py`
========================================================================

========================================================================
Reset pipeline invariant test
========================================================================

[1] Verifying explicit web mode-switch reset order...
    ✓ Active mode shutdown, Lua stop gate, reset, profile reload and route rebinding are explicit

[2] Verifying samovar_reset() UI stage...
    ✓ Menu/UI reset delegates runtime cleanup and clears command queue

[3] Verifying reset_sensor_counter() runtime cleanup set...
    ✓ Runtime reset covers power, stepper, I2C pump, counters, self-test and Lua status string

[4] Verifying route rebinding and profile sequence...
    ✓ Profile namespace/mode metadata and route rebinding order are explicit

[5] Compiling and running sequential reset harness...
    ✓ Harness compiled
    dist_to_beer|ok|target=/beer.htm|save_load=1/1|route_rebind=1/1
    beer_to_bk|ok|target=/bk.htm|save_load=1/1|route_rebind=1/1
    bk_to_nbk|ok|target=/nbk.htm|save_load=1/1|route_rebind=1/1
    nbk_to_rect|ok|target=/index.htm|save_load=1/1|route_rebind=1/1
    rect_to_dist|ok|target=/distiller.htm|save_load=1/1|route_rebind=1/1
    same_mode_noop|ok|route_unchanged=1
    reset_pipeline_invariant|ok

========================================================================
Reset pipeline invariant: PASS
========================================================================

Result: PASSED


========================================================================
Command: `python3 tools/tests/test_web_mode_integration.py`
========================================================================

========================================================================
Web mode integration
========================================================================

[1] Verifying web setup/save state contract...
    ✓ handleSave/handleSaveProcessSettings keep explicit save-switch-rebind order

[2] Running focused web route baseline tests...
    .............
    ----------------------------------------------------------------------
    Ran 13 tests in 0.894s
    
    OK
    ✓ web route/unit harness suite passed

[3] Running web mode-switch integration harness...
    ========================================================================
    Mode switching behavior harness
    ========================================================================
    
    [1] Verifying static mode-switch contract...
        ✓ handleSaveProcessSettings resets runtime, reloads defaults and rebinds routes
        ✓ load_default_program_for_mode selects beer/suvid, dist, nbk and rect families
        ✓ change_samovar_mode exposes dedicated pages and rect fallback runtime
        ✓ get_lua_mode_name keeps beer/dist/bk/nbk branches and rect fallback
    
    [2] Compiling and running mode-switch matrix harness...
        ✓ Harness compiled
        rect_to_dist|ok|saved=1|runtime=1|route=/distiller.htm|program=dist|lua=/dist.lua|ns=sam_dist
        rect_to_beer|ok|saved=2|runtime=2|route=/beer.htm|program=beer|lua=/beer.lua|ns=sam_beer
        rect_to_bk|ok|saved=3|runtime=3|route=/bk.htm|program=rect|lua=/bk.lua|ns=sam_bk
        rect_to_nbk|ok|saved=4|runtime=4|route=/nbk.htm|program=nbk|lua=/nbk.lua|ns=sam_nbk
        rect_to_suvid|ok|saved=5|runtime=0|route=/index.htm|program=beer|lua=/rectificat.lua|ns=sam_suvid
        rect_to_lua|ok|saved=6|runtime=0|route=/index.htm|program=rect|lua=/rectificat.lua|ns=sam_lua
        dist_to_rect|ok|saved=0|runtime=0|route=/index.htm|program=rect|lua=/rectificat.lua|ns=sam_rect
        dist_to_beer|ok|saved=2|runtime=2|route=/beer.htm|program=beer|lua=/beer.lua|ns=sam_beer
        dist_to_bk|ok|saved=3|runtime=3|route=/bk.htm|program=rect|lua=/bk.lua|ns=sam_bk
        dist_to_nbk|ok|saved=4|runtime=4|route=/nbk.htm|program=nbk|lua=/nbk.lua|ns=sam_nbk
        dist_to_suvid|ok|saved=5|runtime=0|route=/index.htm|program=beer|lua=/rectificat.lua|ns=sam_suvid
        dist_to_lua|ok|saved=6|runtime=0|route=/index.htm|program=rect|lua=/rectificat.lua|ns=sam_lua
        beer_to_rect|ok|saved=0|runtime=0|route=/index.htm|program=rect|lua=/rectificat.lua|ns=sam_rect
        beer_to_dist|ok|saved=1|runtime=1|route=/distiller.htm|program=dist|lua=/dist.lua|ns=sam_dist
        beer_to_bk|ok|saved=3|runtime=3|route=/bk.htm|program=rect|lua=/bk.lua|ns=sam_bk
        beer_to_nbk|ok|saved=4|runtime=4|route=/nbk.htm|program=nbk|lua=/nbk.lua|ns=sam_nbk
        beer_to_suvid|ok|saved=5|runtime=0|route=/index.htm|program=beer|lua=/rectificat.lua|ns=sam_suvid
        beer_to_lua|ok|saved=6|runtime=0|route=/index.htm|program=rect|lua=/rectificat.lua|ns=sam_lua
        bk_to_rect|ok|saved=0|runtime=0|route=/index.htm|program=rect|lua=/rectificat.lua|ns=sam_rect
        bk_to_dist|ok|saved=1|runtime=1|route=/distiller.htm|program=dist|lua=/dist.lua|ns=sam_dist
        bk_to_beer|ok|saved=2|runtime=2|route=/beer.htm|program=beer|lua=/beer.lua|ns=sam_beer
        bk_to_nbk|ok|saved=4|runtime=4|route=/nbk.htm|program=nbk|lua=/nbk.lua|ns=sam_nbk
        bk_to_suvid|ok|saved=5|runtime=0|route=/index.htm|program=beer|lua=/rectificat.lua|ns=sam_suvid
        bk_to_lua|ok|saved=6|runtime=0|route=/index.htm|program=rect|lua=/rectificat.lua|ns=sam_lua
        nbk_to_rect|ok|saved=0|runtime=0|route=/index.htm|program=rect|lua=/rectificat.lua|ns=sam_rect
        nbk_to_dist|ok|saved=1|runtime=1|route=/distiller.htm|program=dist|lua=/dist.lua|ns=sam_dist
        nbk_to_beer|ok|saved=2|runtime=2|route=/beer.htm|program=beer|lua=/beer.lua|ns=sam_beer
        nbk_to_bk|ok|saved=3|runtime=3|route=/bk.htm|program=rect|lua=/bk.lua|ns=sam_bk
        nbk_to_suvid|ok|saved=5|runtime=0|route=/index.htm|program=beer|lua=/rectificat.lua|ns=sam_suvid
        nbk_to_lua|ok|saved=6|runtime=0|route=/index.htm|program=rect|lua=/rectificat.lua|ns=sam_lua
        suvid_to_rect|ok|saved=0|runtime=0|route=/index.htm|program=rect|lua=/rectificat.lua|ns=sam_rect
        suvid_to_dist|ok|saved=1|runtime=1|route=/distiller.htm|program=dist|lua=/dist.lua|ns=sam_dist
        suvid_to_beer|ok|saved=2|runtime=2|route=/beer.htm|program=beer|lua=/beer.lua|ns=sam_beer
        suvid_to_bk|ok|saved=3|runtime=3|route=/bk.htm|program=rect|lua=/bk.lua|ns=sam_bk
        suvid_to_nbk|ok|saved=4|runtime=4|route=/nbk.htm|program=nbk|lua=/nbk.lua|ns=sam_nbk
        suvid_to_lua|ok|saved=6|runtime=0|route=/index.htm|program=rect|lua=/rectificat.lua|ns=sam_lua
        lua_to_rect|ok|saved=0|runtime=0|route=/index.htm|program=rect|lua=/rectificat.lua|ns=sam_rect
        lua_to_dist|ok|saved=1|runtime=1|route=/distiller.htm|program=dist|lua=/dist.lua|ns=sam_dist
        lua_to_beer|ok|saved=2|runtime=2|route=/beer.htm|program=beer|lua=/beer.lua|ns=sam_beer
        lua_to_bk|ok|saved=3|runtime=3|route=/bk.htm|program=rect|lua=/bk.lua|ns=sam_bk
        lua_to_nbk|ok|saved=4|runtime=4|route=/nbk.htm|program=nbk|lua=/nbk.lua|ns=sam_nbk
        lua_to_suvid|ok|saved=5|runtime=0|route=/index.htm|program=beer|lua=/rectificat.lua|ns=sam_suvid
        mode_switching_behavior|ok
    
    ========================================================================
    Mode switching behavior: PASS
    ========================================================================
    ✓ setup/save mode switching is confirmed for all target mode families

========================================================================
Web mode integration: PASS
========================================================================

Result: PASSED


========================================================================
Command: `python3 tools/tests/test_menu_mode_integration.py`
========================================================================

========================================================================
Menu mode integration
========================================================================

[1] Verifying menu state semantics with named values...
    ✓ menu actions/input use named mode/startval/status semantics in transition points

[2] Running focused menu integration tests...
    ...
    ----------------------------------------------------------------------
    Ran 3 tests in 2.783s
    
    OK
    ✓ menu behavior harness suite passed

========================================================================
Menu mode integration: PASS
========================================================================

Result: PASSED


========================================================================
Command: `python3 tools/tests/test_lua_mode_selection.py`
========================================================================

========================================================================
Lua mode selection integration
========================================================================

[1] Verifying static Lua mode-selection contract...
    ✓ get_lua_mode_name maps every runtime mode to an explicit Lua family
    ✓ Lua numeric bindings expose SamSetup_Mode, Samovar_Mode and Samovar_CR_Mode
    ✓ setup/save mode switching reloads Lua under USE_LUA before route rebinding
    ✓ USE_LUA guards isolate runtime include and globals from non-Lua builds

[2] Running existing Lua unit suites...
........
----------------------------------------------------------------------
Ran 8 tests in 0.002s

OK
    ✓ existing Lua runtime/bindings suites passed

[3] Running extracted C++ harness...
Lua runtime mode-selection matrix
SAMOVAR_RECTIFICATION_MODE|ok|numeric=0|family=rect|filename=/rectificat.lua|samovar_mode=0|samovar_cr_mode=0|setup_mode=0
SAMOVAR_DISTILLATION_MODE|ok|numeric=1|family=dist|filename=/dist.lua|samovar_mode=1|samovar_cr_mode=1|setup_mode=1
SAMOVAR_BEER_MODE|ok|numeric=2|family=beer|filename=/beer.lua|samovar_mode=2|samovar_cr_mode=2|setup_mode=2
SAMOVAR_BK_MODE|ok|numeric=3|family=bk|filename=/bk.lua|samovar_mode=3|samovar_cr_mode=3|setup_mode=3
SAMOVAR_NBK_MODE|ok|numeric=4|family=nbk|filename=/nbk.lua|samovar_mode=4|samovar_cr_mode=4|setup_mode=4
SAMOVAR_SUVID_MODE|ok|numeric=5|family=rect|filename=/rectificat.lua|samovar_mode=5|samovar_cr_mode=5|setup_mode=5
SAMOVAR_LUA_MODE|ok|numeric=6|family=rect|filename=/rectificat.lua|samovar_mode=6|samovar_cr_mode=6|setup_mode=6
lua_mode_selection|ok

Lua mode selection: PASS

Result: PASSED


```
