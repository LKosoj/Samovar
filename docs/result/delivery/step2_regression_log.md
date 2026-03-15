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
