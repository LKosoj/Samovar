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
