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
