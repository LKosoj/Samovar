========================================================================
Step 2.2a final regression verification
========================================================================
Date: 2026-03-15
Context: Введение именованных констант для статусов и команд

========================================================================
State contracts baseline test
========================================================================

[1] Verifying SamovarStatusInt exact numeric baseline...
    ✓ SamovarStatusInt={'SAMOVAR_STATUS_OFF': 0, 'SAMOVAR_STATUS_RECTIFICATION_RUN': 10, 'SAMOVAR_STATUS_RECTIFICATION_WAIT': 15, 'SAMOVAR_STATUS_RECTIFICATION_COMPLETE': 20, 'SAMOVAR_STATUS_CALIBRATION': 30, 'SAMOVAR_STATUS_RECTIFICATION_PAUSE': 40, 'SAMOVAR_STATUS_RECTIFICATION_WARMUP': 50, 'SAMOVAR_STATUS_RECTIFICATION_STABILIZING': 51, 'SAMOVAR_STATUS_RECTIFICATION_STABILIZED': 52, 'SAMOVAR_STATUS_DISTILLATION': 1000, 'SAMOVAR_STATUS_BEER': 2000, 'SAMOVAR_STATUS_BK': 3000, 'SAMOVAR_STATUS_NBK': 4000}

[2] Verifying startval exact numeric baseline...
    ✓ startval=[0, 1, 2, 3, 100, 1000, 2000, 2001, 2002, 3000, 4000, 4001]

[3] Verifying sam_command_sync exact numeric baseline...
    ✓ sam_command_sync={'SAMOVAR_NONE': 0, 'SAMOVAR_START': 1, 'SAMOVAR_POWER': 2, 'SAMOVAR_RESET': 3, 'CALIBRATE_START': 4, 'CALIBRATE_STOP': 5, 'SAMOVAR_PAUSE': 6, 'SAMOVAR_CONTINUE': 7, 'SAMOVAR_SETBODYTEMP': 8, 'SAMOVAR_DISTILLATION': 9, 'SAMOVAR_BEER': 10, 'SAMOVAR_BEER_NEXT': 11, 'SAMOVAR_BK': 12, 'SAMOVAR_NBK': 13, 'SAMOVAR_SELF_TEST': 14, 'SAMOVAR_DIST_NEXT': 15, 'SAMOVAR_NBK_NEXT': 16}

[4] Verifying Samovar_Mode exact numeric baseline...
    ✓ Samovar_Mode={'SAMOVAR_RECTIFICATION_MODE': 0, 'SAMOVAR_DISTILLATION_MODE': 1, 'SAMOVAR_BEER_MODE': 2, 'SAMOVAR_BK_MODE': 3, 'SAMOVAR_NBK_MODE': 4, 'SAMOVAR_SUVID_MODE': 5, 'SAMOVAR_LUA_MODE': 6}

========================================================================
State contracts baseline: PASS
========================================================================

========================================================================
Step 2.2a attempt 4 evidence refresh
========================================================================
Date: 2026-03-15
Context: Повторная фиксация evidence по шагу 2.2a после ревью

Command: `python3 tools/tests/test_state_contracts_baseline.py`

```text
========================================================================
State contracts baseline test
========================================================================

[1] Verifying SamovarStatusInt exact numeric baseline...
    ✓ SamovarStatusInt={'SAMOVAR_STATUS_OFF': 0, 'SAMOVAR_STATUS_RECTIFICATION_RUN': 10, 'SAMOVAR_STATUS_RECTIFICATION_WAIT': 15, 'SAMOVAR_STATUS_RECTIFICATION_COMPLETE': 20, 'SAMOVAR_STATUS_CALIBRATION': 30, 'SAMOVAR_STATUS_RECTIFICATION_PAUSE': 40, 'SAMOVAR_STATUS_RECTIFICATION_WARMUP': 50, 'SAMOVAR_STATUS_RECTIFICATION_STABILIZING': 51, 'SAMOVAR_STATUS_RECTIFICATION_STABILIZED': 52, 'SAMOVAR_STATUS_DISTILLATION': 1000, 'SAMOVAR_STATUS_BEER': 2000, 'SAMOVAR_STATUS_BK': 3000, 'SAMOVAR_STATUS_NBK': 4000}

[2] Verifying startval exact numeric baseline...
    ✓ startval=[0, 1, 2, 3, 100, 1000, 2000, 2001, 2002, 3000, 4000, 4001]

[3] Verifying sam_command_sync exact numeric baseline...
    ✓ sam_command_sync={'SAMOVAR_NONE': 0, 'SAMOVAR_START': 1, 'SAMOVAR_POWER': 2, 'SAMOVAR_RESET': 3, 'CALIBRATE_START': 4, 'CALIBRATE_STOP': 5, 'SAMOVAR_PAUSE': 6, 'SAMOVAR_CONTINUE': 7, 'SAMOVAR_SETBODYTEMP': 8, 'SAMOVAR_DISTILLATION': 9, 'SAMOVAR_BEER': 10, 'SAMOVAR_BEER_NEXT': 11, 'SAMOVAR_BK': 12, 'SAMOVAR_NBK': 13, 'SAMOVAR_SELF_TEST': 14, 'SAMOVAR_DIST_NEXT': 15, 'SAMOVAR_NBK_NEXT': 16}

[4] Verifying Samovar_Mode exact numeric baseline...
    ✓ Samovar_Mode={'SAMOVAR_RECTIFICATION_MODE': 0, 'SAMOVAR_DISTILLATION_MODE': 1, 'SAMOVAR_BEER_MODE': 2, 'SAMOVAR_BK_MODE': 3, 'SAMOVAR_NBK_MODE': 4, 'SAMOVAR_SUVID_MODE': 5, 'SAMOVAR_LUA_MODE': 6}

========================================================================
State contracts baseline: PASS
========================================================================
```

Command: `python3 -m unittest tests.test_status_code_constants`

```text
...
----------------------------------------------------------------------
Ran 3 tests in 0.041s

OK
```

Command: `python3 -m ruff check tools/tests/test_state_contracts_baseline.py tests/test_status_code_constants.py`

```text
All checks passed!
```

========================================================================
Step 2.2b mode/startval regression verification
========================================================================
Date: 2026-03-15
Context: Введение именованных констант для Samovar_Mode, Samovar_CR_Mode и startval

Command: `python3 tools/tests/test_state_contracts_baseline.py`

```text
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
```

Command: `python3 -m unittest tests.test_mode_code_constants tests.test_state_runtime_types tests.test_app_status_text_baseline tests.test_modes_integration_dispatch tests.test_state_code_inventory_baseline`

```text
........................
----------------------------------------------------------------------
Ran 24 tests in 21.636s

OK
```

Command: `python3 tools/tests/test_reset_pipeline_invariant.py`

```text
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
```

Command: `python3 -m unittest tests.test_change_samovar_mode_behavior tests.test_ui_menu_actions_behavior tests.test_ui_menu_input_behavior tests.test_ui_menu_integration_behavior`

```text
....
----------------------------------------------------------------------
Ran 4 tests in 3.163s

OK
```

Command: `python3 -m ruff check tools/state_inventory.py tools/tests/test_state_contracts_baseline.py tools/tests/test_reset_pipeline_invariant.py tests/test_state_runtime_types.py tests/test_app_status_text_baseline.py tests/test_modes_integration_dispatch.py tests/test_mode_code_constants.py tests/test_ui_menu_actions_behavior.py tests/test_ui_menu_input_behavior.py tests/test_ui_menu_integration_behavior.py tests/test_change_samovar_mode_behavior.py`

```text
All checks passed!
```

========================================================================
Behavioral mode-switch harness verification
========================================================================
Date: 2026-03-15
Context: Behavioral harness test for switching between RECT, DIST, BEER, BK, NBK, SUVID, LUA

Command: `python3 tools/tests/test_mode_switching_behavior.py`

```text
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
```

Command: `python3 -m ruff check tools/tests/test_mode_switching_behavior.py`

```text
All checks passed!
```

========================================================================
Step 2.3 mode ownership verification
========================================================================
Date: 2026-03-16
Context: Явное описание mode ownership и runtime routing

Command: `python3 -m unittest tests.test_mode_ownership_mapping tests.test_app_default_programs_extracted tests.test_app_orchestration tests.test_change_samovar_mode_behavior`

```text
..............
----------------------------------------------------------------------
Ran 14 tests in 1.678s

OK
```

Command: `python3 tools/tests/test_mode_switching_behavior.py`

```text
Mode switching behavior: PASS
```

Command: `python3 tools/tests/test_reset_pipeline_invariant.py`

```text
Reset pipeline invariant: PASS
```

Command: `python3 -m ruff check tools/tests/test_mode_switching_behavior.py tools/tests/test_reset_pipeline_invariant.py tests/test_app_default_programs_extracted.py tests/test_app_orchestration.py tests/test_change_samovar_mode_behavior.py tests/test_mode_ownership_mapping.py`

```text
All checks passed!
```

========================================================================
Step 2.5 magic number cleanup verification
========================================================================
Date: 2026-03-16
Context: финальная зачистка magic numbers в state-логике и обновление финального inventory

Command: `python3 tools/tests/test_state_contracts_baseline.py`

```text
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
```

Command: `python3 -m unittest tests.test_state_magic_cleanup tests.test_state_code_inventory_baseline tests.test_status_code_constants tests.test_mode_code_constants tests.test_app_status_text_baseline tests.test_modes_integration_dispatch tests.test_app_orchestration tests.test_change_samovar_mode_behavior tests.test_mode_ownership_mapping`

```text
.....................................
----------------------------------------------------------------------
Ran 37 tests in 24.939s

OK
```

Command: `python3 -m unittest tests.test_state_runtime_types`

```text
.....
----------------------------------------------------------------------
Ran 5 tests in 0.001s

OK
```

Command: `python3 tools/tests/test_mode_switching_behavior.py`

```text
Mode switching behavior: PASS
```

Command: `python3 tools/tests/test_reset_pipeline_invariant.py`

```text
Reset pipeline invariant: PASS
```

Command: `python3 -m ruff check tools/state_inventory.py tools/state_magic_cleanup.py tools/tests/test_state_contracts_baseline.py tools/tests/test_mode_switching_behavior.py tools/tests/test_reset_pipeline_invariant.py tests/test_state_code_inventory_baseline.py tests/test_status_code_constants.py tests/test_mode_code_constants.py tests/test_state_magic_cleanup.py tests/test_app_status_text_baseline.py tests/test_modes_integration_dispatch.py tests/test_app_orchestration.py tests/test_change_samovar_mode_behavior.py tests/test_mode_ownership_mapping.py`

```text
All checks passed!
```

========================================================================
Web/Menu state transition integration
========================================================================
Date: 2026-03-16
Context: web routes и menu actions integration с именованными state constants

Command: `python3 tools/tests/test_web_mode_integration.py`

```text
========================================================================
Web mode integration
========================================================================

[1] Verifying web setup/save state contract...
    ✓ handleSave/handleSaveProcessSettings keep explicit save-switch-rebind order

[2] Running focused web route baseline tests...
    .............
    ----------------------------------------------------------------------
    Ran 13 tests in 1.083s
    
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
```

Command: `python3 tools/tests/test_menu_mode_integration.py`

```text
========================================================================
Menu mode integration
========================================================================

[1] Verifying menu state semantics with named values...
    ✓ menu actions/input use named mode/startval/status semantics in transition points

[2] Running focused menu integration tests...
    ...
    ----------------------------------------------------------------------
    Ran 3 tests in 2.512s
    
    OK
    ✓ menu behavior harness suite passed

========================================================================
Menu mode integration: PASS
========================================================================
```

Command: `python3 -m ruff check tools/tests/test_web_mode_integration.py tools/tests/test_menu_mode_integration.py tests/test_ui_menu_actions_behavior.py tests/test_ui_menu_integration_behavior.py`

```text
All checks passed!
```
