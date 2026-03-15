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


========================================================================
State contracts baseline regression
========================================================================

========================================================================
State contracts baseline test
========================================================================

[1] Verifying SamovarStatusInt exact numeric baseline...
    ✓ SamovarStatusInt=[0, 10, 15, 20, 30, 40, 50, 51, 52, 1000, 2000, 3000, 4000]

[2] Verifying startval exact numeric baseline...
    ✓ startval=[0, 1, 2, 3, 100, 1000, 2000, 2001, 2002, 3000, 4000, 4001]

[3] Verifying sam_command_sync exact numeric baseline...
    ✓ sam_command_sync={'SAMOVAR_NONE': 0, 'SAMOVAR_START': 1, 'SAMOVAR_POWER': 2, 'SAMOVAR_RESET': 3, 'CALIBRATE_START': 4, 'CALIBRATE_STOP': 5, 'SAMOVAR_PAUSE': 6, 'SAMOVAR_CONTINUE': 7, 'SAMOVAR_SETBODYTEMP': 8, 'SAMOVAR_DISTILLATION': 9, 'SAMOVAR_BEER': 10, 'SAMOVAR_BEER_NEXT': 11, 'SAMOVAR_BK': 12, 'SAMOVAR_NBK': 13, 'SAMOVAR_SELF_TEST': 14, 'SAMOVAR_DIST_NEXT': 15, 'SAMOVAR_NBK_NEXT': 16}

[4] Verifying Samovar_Mode exact numeric baseline...
    ✓ Samovar_Mode={'SAMOVAR_RECTIFICATION_MODE': 0, 'SAMOVAR_DISTILLATION_MODE': 1, 'SAMOVAR_BEER_MODE': 2, 'SAMOVAR_BK_MODE': 3, 'SAMOVAR_NBK_MODE': 4, 'SAMOVAR_SUVID_MODE': 5, 'SAMOVAR_LUA_MODE': 6}

========================================================================
State contracts baseline: PASS
========================================================================
