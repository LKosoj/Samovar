# Grep baseline: state inventory

Поиск выполнен по всем git-tracked `*.h/*.cpp/*.ino` файлам. Ниже сохранены все прямые вхождения ключевых state-переменных и связанных флагов.

## SamovarStatusInt

```text
Samovar.ino:337: volatile int16_t SamovarStatusInt;
app/loop_dispatch.h:29: if (SamovarStatusInt == SAMOVAR_STATUS_DISTILLATION) distiller_finish();
app/loop_dispatch.h:30: else if (SamovarStatusInt == SAMOVAR_STATUS_BEER)
app/loop_dispatch.h:32: else if (SamovarStatusInt == SAMOVAR_STATUS_BK)
app/loop_dispatch.h:34: else if (SamovarStatusInt == SAMOVAR_STATUS_NBK)
app/loop_dispatch.h:39: SamovarStatusInt = SAMOVAR_STATUS_RECTIFICATION_WARMUP;
app/loop_dispatch.h:65: SamovarStatusInt = SAMOVAR_STATUS_DISTILLATION;
app/loop_dispatch.h:70: SamovarStatusInt = SAMOVAR_STATUS_BEER;
app/loop_dispatch.h:81: SamovarStatusInt = SAMOVAR_STATUS_BK;
app/loop_dispatch.h:86: SamovarStatusInt = SAMOVAR_STATUS_NBK;
app/loop_dispatch.h:104: if (SamovarStatusInt > SAMOVAR_STATUS_OFF && SamovarStatusInt < SAMOVAR_STATUS_DISTILLATION) {
app/loop_dispatch.h:106: } else if (SamovarStatusInt == SAMOVAR_STATUS_DISTILLATION) {
app/loop_dispatch.h:108: } else if (SamovarStatusInt == SAMOVAR_STATUS_BK) {
app/loop_dispatch.h:110: } else if (SamovarStatusInt == SAMOVAR_STATUS_NBK) {
app/loop_dispatch.h:112: } else if (SamovarStatusInt == SAMOVAR_STATUS_BEER && startval == SAMOVAR_STARTVAL_BEER_ENTRY) {
app/orchestration.h:500: } else if (startval == SAMOVAR_STARTVAL_RECT_IDLE && SamovarStatusInt < SAMOVAR_STATUS_DISTILLATION) {
app/orchestration.h:502: } else if (startval != SAMOVAR_STARTVAL_RECT_IDLE && !program_Pause && SamovarStatusInt < SAMOVAR_STATUS_DISTILLATION) {
app/orchestration.h:504: } else if (startval != SAMOVAR_STARTVAL_RECT_IDLE && program_Pause && SamovarStatusInt < SAMOVAR_STATUS_DISTILLATION) {
app/process_common.h:23: SamovarStatusInt = SAMOVAR_STATUS_OFF;
app/status_text.h:16: if (!PowerOn && SamovarStatusInt == SAMOVAR_STATUS_OFF) {
app/status_text.h:20: SamovarStatusInt = SAMOVAR_STATUS_RECTIFICATION_RUN;
app/status_text.h:27: SamovarStatusInt = SAMOVAR_STATUS_RECTIFICATION_WAIT;
app/status_text.h:30: SamovarStatusInt = SAMOVAR_STATUS_RECTIFICATION_COMPLETE;
app/status_text.h:33: SamovarStatusInt = SAMOVAR_STATUS_CALIBRATION;
app/status_text.h:36: SamovarStatusInt = SAMOVAR_STATUS_RECTIFICATION_PAUSE;
app/status_text.h:38: if (SamovarStatusInt != SAMOVAR_STATUS_RECTIFICATION_STABILIZING &&
app/status_text.h:39: SamovarStatusInt != SAMOVAR_STATUS_RECTIFICATION_STABILIZED) {
app/status_text.h:41: SamovarStatusInt = SAMOVAR_STATUS_RECTIFICATION_WARMUP;
app/status_text.h:42: } else if (SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_STABILIZING) {
app/status_text.h:44: } else if (SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_STABILIZED) {
app/status_text.h:47: } else if (SamovarStatusInt == SAMOVAR_STATUS_DISTILLATION) {
app/status_text.h:51: } else if (SamovarStatusInt == SAMOVAR_STATUS_BK) {
app/status_text.h:53: } else if (SamovarStatusInt == SAMOVAR_STATUS_NBK) {
app/status_text.h:66: } else if (SamovarStatusInt == SAMOVAR_STATUS_BEER) {
app/status_text.h:130: if (SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_RUN ||
app/status_text.h:131: SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_WAIT ||
app/status_text.h:132: (SamovarStatusInt == SAMOVAR_STATUS_BEER && PowerOn)) {
impurity_detector.h:302: if (!SamSetup.useautospeed || SamovarStatusInt != SAMOVAR_STATUS_RECTIFICATION_RUN) {
io/actuators.h:47: if (!(SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_RUN ||
io/actuators.h:48: SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_WAIT ||
io/actuators.h:49: SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_PAUSE)) return;
io/sensor_scan.h:153: SamovarStatusInt = SAMOVAR_STATUS_OFF;
modes/beer/beer_runtime.h:100: if (SamovarStatusInt != SAMOVAR_STATUS_BEER) return;
modes/beer/beer_support.h:10: if (SamovarStatusInt != SAMOVAR_STATUS_BEER) return 0.0;
modes/dist/dist_runtime.h:29: //    SendMsg("Статус: " + String(SamovarStatusInt) +
modes/dist/dist_runtime.h:33: if (SamovarStatusInt != SAMOVAR_STATUS_DISTILLATION) return;
modes/nbk/nbk_runtime.h:65: SamovarStatusInt = SAMOVAR_STATUS_NBK; // Именно в таком порядке
modes/rect/rect_runtime.h:33: if (!(SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_RUN ||
modes/rect/rect_runtime.h:34: SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_WAIT ||
modes/rect/rect_runtime.h:35: SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_PAUSE)) return;
modes/rect/rect_runtime.h:378: if (SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_WARMUP &&
modes/rect/rect_runtime.h:567: if (SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_WARMUP &&
modes/rect/rect_runtime.h:583: SamovarStatusInt = SAMOVAR_STATUS_RECTIFICATION_STABILIZING;
modes/rect/rect_runtime.h:604: if (SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_STABILIZING && !boil_started) {
modes/rect/rect_runtime.h:613: if (SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_STABILIZING &&
modes/rect/rect_runtime.h:621: SamovarStatusInt = SAMOVAR_STATUS_RECTIFICATION_STABILIZED;
state/globals.h:176: extern volatile int16_t SamovarStatusInt;
ui/lua/bindings_process.h:60: lua_pushnumber(lua_state, (lua_Number)SamovarStatusInt);
ui/lua/runtime.h:30: Variables += "SamovarStatusInt = " + String(SamovarStatusInt) + "\r\n";
ui/web/ajax_snapshot.h:155: (SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_RUN ||
ui/web/ajax_snapshot.h:156: SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_WAIT ||
ui/web/ajax_snapshot.h:157: (SamovarStatusInt == SAMOVAR_STATUS_BEER && PowerOn))) {
ui/web/routes_setup.h:63: if (SamovarStatusInt == SAMOVAR_STATUS_DISTILLATION) {
ui/web/routes_setup.h:65: } else if (SamovarStatusInt == SAMOVAR_STATUS_BEER) {
ui/web/routes_setup.h:67: } else if (SamovarStatusInt == SAMOVAR_STATUS_BK) {
ui/web/routes_setup.h:69: } else if (SamovarStatusInt == SAMOVAR_STATUS_NBK) {
```

## sam_command_sync

```text
Blynk.ino:239: sam_command_sync = SAMOVAR_BEER_NEXT;
Blynk.ino:241: sam_command_sync = SAMOVAR_DIST_NEXT;
Blynk.ino:243: sam_command_sync = SAMOVAR_START;
Blynk.ino:258: sam_command_sync = SAMOVAR_RESET;
Blynk.ino:263: sam_command_sync = SAMOVAR_BEER;
Blynk.ino:265: sam_command_sync = SAMOVAR_BK;
Blynk.ino:267: sam_command_sync = SAMOVAR_NBK;
Blynk.ino:269: sam_command_sync = SAMOVAR_DISTILLATION;
Blynk.ino:271: sam_command_sync = SAMOVAR_POWER;
Samovar.ino:252: volatile SamovarCommands sam_command_sync;
app/alarm_control.h:20: sam_command_sync = SAMOVAR_POWER;
app/loop_dispatch.h:21: if (sam_command_sync == SAMOVAR_NONE) return;
app/loop_dispatch.h:23: switch (sam_command_sync) {
app/loop_dispatch.h:98: if (sam_command_sync != SAMOVAR_RESET) {
app/loop_dispatch.h:99: sam_command_sync = SAMOVAR_NONE;
app/orchestration.h:514: sam_command_sync = SAMOVAR_DISTILLATION;
app/orchestration.h:519: sam_command_sync = SAMOVAR_BK;
app/orchestration.h:524: sam_command_sync = SAMOVAR_NBK;
app/orchestration.h:529: sam_command_sync = SAMOVAR_BEER;
io/power_control.h:53: sam_command_sync = SAMOVAR_RESET;
io/sensor_scan.h:110: sam_command_sync = SAMOVAR_NONE;
io/sensor_scan.h:188: sam_command_sync = SAMOVAR_NONE;
modes/bk/bk_alarm.h:63: sam_command_sync = SAMOVAR_POWER;
modes/dist/dist_alarm.h:59: sam_command_sync = SAMOVAR_POWER;
modes/nbk/nbk_alarm.h:48: sam_command_sync = SAMOVAR_POWER;
modes/rect/rect_runtime.h:542: sam_command_sync = SAMOVAR_POWER;
state/globals.h:122: extern volatile SamovarCommands sam_command_sync;
ui/lua/bindings_process.h:18: sam_command_sync = SAMOVAR_BEER;
ui/lua/bindings_process.h:20: sam_command_sync = SAMOVAR_BK;
ui/lua/bindings_process.h:22: sam_command_sync = SAMOVAR_NBK;
ui/lua/bindings_process.h:24: sam_command_sync = SAMOVAR_DISTILLATION;
ui/lua/bindings_process.h:26: sam_command_sync = SAMOVAR_POWER;
ui/lua/bindings_process.h:28: sam_command_sync = SAMOVAR_POWER;
ui/lua/bindings_process.h:49: sam_command_sync = SAMOVAR_START;
ui/lua/bindings_process.h:51: sam_command_sync = SAMOVAR_BEER_NEXT;
ui/lua/bindings_process.h:53: sam_command_sync = SAMOVAR_DIST_NEXT;
ui/lua/bindings_variables.h:7: while (sam_command_sync != SAMOVAR_NONE) {
ui/menu/actions.h:146: sam_command_sync = SAMOVAR_BEER;
ui/menu/actions.h:154: sam_command_sync = SAMOVAR_DISTILLATION;
ui/menu/actions.h:162: sam_command_sync = SAMOVAR_BK;
ui/menu/actions.h:170: sam_command_sync = SAMOVAR_NBK;
ui/menu/actions.h:178: sam_command_sync = SAMOVAR_POWER;
ui/menu/actions.h:280: sam_command_sync = SAMOVAR_NONE;
ui/web/routes_command.h:54: sam_command_sync = SAMOVAR_BEER_NEXT;
ui/web/routes_command.h:56: sam_command_sync = SAMOVAR_DIST_NEXT;
ui/web/routes_command.h:58: sam_command_sync = SAMOVAR_NBK_NEXT;
ui/web/routes_command.h:60: sam_command_sync = SAMOVAR_START;
ui/web/routes_command.h:64: if (!PowerOn) sam_command_sync = SAMOVAR_BEER;
ui/web/routes_command.h:66: sam_command_sync = SAMOVAR_POWER;
ui/web/routes_command.h:68: if (!PowerOn) sam_command_sync = SAMOVAR_DISTILLATION;
ui/web/routes_command.h:70: sam_command_sync = SAMOVAR_POWER;
ui/web/routes_command.h:72: if (!PowerOn) sam_command_sync = SAMOVAR_BK;
ui/web/routes_command.h:74: sam_command_sync = SAMOVAR_POWER;
ui/web/routes_command.h:76: if (!PowerOn) sam_command_sync = SAMOVAR_NBK;
ui/web/routes_command.h:78: sam_command_sync = SAMOVAR_POWER;
ui/web/routes_command.h:80: sam_command_sync = SAMOVAR_POWER;
ui/web/routes_command.h:82: sam_command_sync = SAMOVAR_SETBODYTEMP;
ui/web/routes_command.h:84: sam_command_sync = SAMOVAR_RESET;
ui/web/routes_command.h:90: sam_command_sync = SAMOVAR_SELF_TEST;
ui/web/routes_command.h:126: sam_command_sync = SAMOVAR_DISTILLATION;
ui/web/routes_command.h:128: sam_command_sync = SAMOVAR_POWER;
ui/web/routes_command.h:132: sam_command_sync = SAMOVAR_BK;
ui/web/routes_command.h:134: sam_command_sync = SAMOVAR_POWER;
ui/web/routes_command.h:138: sam_command_sync = SAMOVAR_NBK;
ui/web/routes_command.h:140: sam_command_sync = SAMOVAR_POWER;
ui/web/routes_command.h:148: sam_command_sync = SAMOVAR_CONTINUE;
ui/web/routes_command.h:150: sam_command_sync = SAMOVAR_PAUSE;
ui/web/routes_service.h:20: sam_command_sync = CALIBRATE_START;
ui/web/routes_service.h:23: sam_command_sync = CALIBRATE_STOP;
```

## Samovar_Mode

```text
Blynk.ino:170: Blynk.virtualWrite(V20, Samovar_Mode);
Blynk.ino:178: if (Samovar_Mode == SAMOVAR_BEER_MODE || Samovar_Mode == SAMOVAR_SUVID_MODE) {
Blynk.ino:180: } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
Blynk.ino:182: } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
Blynk.ino:238: if (Samovar_Mode == SAMOVAR_BEER_MODE) {
Blynk.ino:240: } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
Blynk.ino:262: if (Samovar_Mode == SAMOVAR_BEER_MODE && !PowerOn) {
Blynk.ino:264: } else if (Samovar_Mode == SAMOVAR_BK_MODE && !PowerOn) {
Blynk.ino:266: } else if (Samovar_Mode == SAMOVAR_NBK_MODE && !PowerOn) {
Blynk.ino:268: } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE && !PowerOn) {
Samovar.ino:254: volatile SAMOVAR_MODE Samovar_Mode;
app/config_apply.h:33: Samovar_Mode = (SAMOVAR_MODE)SamSetup.Mode;
app/default_programs.h:13: if (Samovar_Mode == SAMOVAR_BEER_MODE || Samovar_Mode == SAMOVAR_SUVID_MODE) {
app/default_programs.h:15: } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
app/default_programs.h:17: } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
app/loop_dispatch.h:25: Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
app/loop_dispatch.h:38: if (PowerOn && Samovar_Mode == SAMOVAR_RECTIFICATION_MODE) {
app/loop_dispatch.h:64: Samovar_Mode = SAMOVAR_DISTILLATION_MODE;
app/loop_dispatch.h:69: Samovar_Mode = SAMOVAR_BEER_MODE;
app/loop_dispatch.h:80: Samovar_Mode = SAMOVAR_BK_MODE;
app/loop_dispatch.h:85: Samovar_Mode = SAMOVAR_NBK_MODE;
app/orchestration.h:497: if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE) {
app/orchestration.h:512: } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
app/orchestration.h:517: } else if (Samovar_Mode == SAMOVAR_BK_MODE) {
app/orchestration.h:522: } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
app/orchestration.h:527: } else if (Samovar_Mode == SAMOVAR_BEER_MODE) {
app/runtime_tasks.h:241: s += format_float(get_steam_alcohol(Samovar_Mode == SAMOVAR_RECTIFICATION_MODE ? SteamSensor.avgTemp : TankSensor.avgTemp), 2);
app/runtime_tasks.h:282: s += ","; s += String((int)Samovar_Mode); // 24: mode
app/runtime_tasks.h:292: if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE) {
app/runtime_tasks.h:294: } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
app/runtime_tasks.h:296: } else if (Samovar_Mode == SAMOVAR_BK_MODE) {
app/runtime_tasks.h:298: } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
app/runtime_tasks.h:300: } else if (Samovar_Mode == SAMOVAR_BEER_MODE) {
app/runtime_tasks.h:308: if (Samovar_Mode == SAMOVAR_BEER_MODE) {
app/runtime_tasks.h:349: } else if (Samovar_Mode == SAMOVAR_BK_MODE) {
app/runtime_tasks.h:351: } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
app/runtime_tasks.h:355: else if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE && (TargetStepps > 0 || program[ProgramNum].WType == "P")) {
impurity_detector.h:309: if (Samovar_Mode != SAMOVAR_RECTIFICATION_MODE) {
modes/beer/beer_runtime.h:117: if (Samovar_Mode != SAMOVAR_BEER_MODE || !PowerOn) return;
modes/dist/dist_runtime.h:30: //            ", Режим: " + String(Samovar_Mode) +
modes/nbk/nbk_runtime.h:345: // if (Samovar_Mode != SAMOVAR_NBK_MODE || !PowerOn) return; //dranek: лишняя проверка, ломает запуск
modes/rect/rect_runtime.h:185: if (Samovar_Mode != SAMOVAR_RECTIFICATION_MODE) return;
state/globals.h:124: extern volatile SAMOVAR_MODE Samovar_Mode;
storage/session_logs.h:26: if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE || Samovar_Mode == SAMOVAR_BEER_MODE || Samovar_Mode == SAMOVAR_DISTILLATION_MODE || Samovar_Mode == SAMOVAR_NBK_MODE) {
storage/session_logs.h:28: if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE) {
storage/session_logs.h:31: } else if (Samovar_Mode == SAMOVAR_BEER_MODE) {
storage/session_logs.h:34: } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
storage/session_logs.h:37: } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
storage/session_logs.h:82: if ((Samovar_Mode == SAMOVAR_RECTIFICATION_MODE || Samovar_Mode == SAMOVAR_BEER_MODE || Samovar_Mode == SAMOVAR_DISTILLATION_MODE || Samovar_Mode == SAMOVAR_NBK_MODE) && STcnt > 10) {
storage/session_logs.h:85: if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE) {
storage/session_logs.h:87: } else if (Samovar_Mode == SAMOVAR_BEER_MODE) {
ui/lua/bindings_process.h:17: if (Samovar_Mode == SAMOVAR_BEER_MODE && !PowerOn) {
ui/lua/bindings_process.h:19: } else if (Samovar_Mode == SAMOVAR_BK_MODE && !PowerOn) {
ui/lua/bindings_process.h:21: } else if (Samovar_Mode == SAMOVAR_NBK_MODE && !PowerOn) {
ui/lua/bindings_process.h:23: } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE && !PowerOn) {
ui/lua/bindings_process.h:48: if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE) {
ui/lua/bindings_process.h:50: } else if (Samovar_Mode == SAMOVAR_BEER_MODE) {
ui/lua/bindings_process.h:52: } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
ui/lua/bindings_variables.h:46: } else if (Var == "Samovar_Mode") {
ui/lua/bindings_variables.h:47: Samovar_Mode = (SAMOVAR_MODE)a;
ui/lua/bindings_variables.h:109: } else if (Var == "Samovar_Mode") {
ui/lua/bindings_variables.h:110: a = Samovar_Mode;
ui/menu/actions.h:143: if (Samovar_Mode == SAMOVAR_BEER_MODE) {
ui/menu/actions.h:151: } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
ui/menu/actions.h:159: } else if (Samovar_Mode == SAMOVAR_BK_MODE) {
ui/menu/actions.h:167: } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
ui/menu/actions.h:233: if (Samovar_Mode != SAMOVAR_RECTIFICATION_MODE || !PowerOn) {
ui/web/ajax_snapshot.h:154: if ((Samovar_Mode == SAMOVAR_RECTIFICATION_MODE || Samovar_Mode == SAMOVAR_BEER_MODE || Samovar_Mode == SAMOVAR_DISTILLATION_MODE || Samovar_Mode == SAMOVAR_NBK_MODE) &&
ui/web/ajax_snapshot.h:224: if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE || Samovar_Mode == SAMOVAR_RECTIFICATION_MODE || Samovar_Mode == SAMOVAR_BK_MODE || Samovar_Mode == SAMOVAR_NBK_MODE) {
ui/web/ajax_snapshot.h:228: out.print(format_float(get_steam_alcohol(Samovar_Mode == SAMOVAR_RECTIFICATION_MODE ? SteamSensor.avgTemp : TankSensor.avgTemp), 2));
ui/web/ajax_snapshot.h:231: if (PowerOn && Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
ui/web/page_assets.h:44: if (Samovar_Mode == SAMOVAR_BEER_MODE) {
ui/web/page_assets.h:46: } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
ui/web/page_assets.h:48: } else if (Samovar_Mode == SAMOVAR_BK_MODE) {
ui/web/page_assets.h:50: } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
ui/web/page_assets.h:54: Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
ui/web/page_assets.h:56: Samovar_CR_Mode = Samovar_Mode;
ui/web/routes_command.h:53: if (Samovar_Mode == SAMOVAR_BEER_MODE) {
ui/web/routes_command.h:55: } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
ui/web/routes_command.h:57: } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
ui/web/routes_command.h:63: if (Samovar_Mode == SAMOVAR_BEER_MODE) {
ui/web/routes_command.h:67: } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
ui/web/routes_command.h:71: } else if (Samovar_Mode == SAMOVAR_BK_MODE) {
ui/web/routes_command.h:75: } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
ui/web/routes_program.h:6: if (Samovar_Mode == SAMOVAR_BEER_MODE) {
ui/web/routes_program.h:9: } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
ui/web/routes_program.h:12: } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
ui/web/routes_setup.h:87: Samovar_Mode = (SAMOVAR_MODE)SamSetup.Mode;
ui/web/routes_setup.h:88: Samovar_CR_Mode = Samovar_Mode;
ui/web/routes_setup.h:190: if (Samovar_Mode == SAMOVAR_BEER_MODE) set_beer_program(request->arg("WProgram"));
ui/web/template_keys.h:39: if (Samovar_Mode == SAMOVAR_BEER_MODE) return get_beer_program();
ui/web/template_keys.h:40: else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) return get_dist_program();
ui/web/template_keys.h:41: else if (Samovar_Mode == SAMOVAR_NBK_MODE) return get_nbk_program();
ui/web/template_keys.h:133: if (Samovar_Mode == SAMOVAR_BEER_MODE) return get_beer_program();
```

## Samovar_CR_Mode

```text
Samovar.ino:255: volatile SAMOVAR_MODE Samovar_CR_Mode;
state/globals.h:125: extern volatile SAMOVAR_MODE Samovar_CR_Mode;
storage/nvs_migration.h:41: SAMOVAR_MODE backupMode = Samovar_CR_Mode;
storage/nvs_migration.h:46: Samovar_CR_Mode = (SAMOVAR_MODE)SamSetup.Mode;
storage/nvs_migration.h:51: Samovar_CR_Mode = backupMode;
storage/nvs_profiles.h:31: int mode = (int)Samovar_CR_Mode;
storage/nvs_profiles.h:188: Samovar_CR_Mode = (SAMOVAR_MODE)lastMode;
ui/lua/bindings_variables.h:48: } else if (Var == "Samovar_CR_Mode") {
ui/lua/bindings_variables.h:49: Samovar_CR_Mode = (SAMOVAR_MODE)a;
ui/lua/bindings_variables.h:111: } else if (Var == "Samovar_CR_Mode") {
ui/lua/bindings_variables.h:112: a = Samovar_CR_Mode;
ui/lua/runtime.h:332: if (Samovar_CR_Mode == SAMOVAR_BEER_MODE) {
ui/lua/runtime.h:334: } else if (Samovar_CR_Mode == SAMOVAR_DISTILLATION_MODE) {
ui/lua/runtime.h:336: } else if (Samovar_CR_Mode == SAMOVAR_BK_MODE) {
ui/lua/runtime.h:338: } else if (Samovar_CR_Mode == SAMOVAR_NBK_MODE) {
ui/web/page_assets.h:56: Samovar_CR_Mode = Samovar_Mode;
ui/web/routes_setup.h:88: Samovar_CR_Mode = Samovar_Mode;
```

## startval

```text
Blynk.ino:47: if (startval > SAMOVAR_STARTVAL_RECT_IDLE && startval <= SAMOVAR_STARTVAL_RECT_STOPPED)
Samovar.ino:344: volatile int16_t startval = SAMOVAR_STARTVAL_RECT_IDLE;
app/loop_dispatch.h:66: startval = SAMOVAR_STARTVAL_DISTILLATION_ENTRY;
app/loop_dispatch.h:71: startval = SAMOVAR_STARTVAL_BEER_ENTRY;
app/loop_dispatch.h:82: startval = SAMOVAR_STARTVAL_BK_ENTRY;
app/loop_dispatch.h:87: startval = SAMOVAR_STARTVAL_NBK_ENTRY;
app/loop_dispatch.h:112: } else if (SamovarStatusInt == SAMOVAR_STATUS_BEER && startval == SAMOVAR_STARTVAL_BEER_ENTRY) {
app/orchestration.h:500: } else if (startval == SAMOVAR_STARTVAL_RECT_IDLE && SamovarStatusInt < SAMOVAR_STATUS_DISTILLATION) {
app/orchestration.h:502: } else if (startval != SAMOVAR_STARTVAL_RECT_IDLE && !program_Pause && SamovarStatusInt < SAMOVAR_STATUS_DISTILLATION) {
app/orchestration.h:504: } else if (startval != SAMOVAR_STARTVAL_RECT_IDLE && program_Pause && SamovarStatusInt < SAMOVAR_STATUS_DISTILLATION) {
app/orchestration.h:507: if (startval == SAMOVAR_STARTVAL_CALIBRATION) {
app/orchestration.h:508: startval = SAMOVAR_STARTVAL_RECT_IDLE;
app/runtime_tasks.h:222: if (startval != SAMOVAR_STARTVAL_RECT_IDLE) {
app/status_text.h:18: } else if (PowerOn && startval == SAMOVAR_STARTVAL_RECT_PROGRAM_RUNNING && !PauseOn && !program_Wait) {
app/status_text.h:21: } else if (PowerOn && startval == SAMOVAR_STARTVAL_RECT_PROGRAM_RUNNING && program_Wait) {
app/status_text.h:28: } else if (PowerOn && startval == SAMOVAR_STARTVAL_RECT_PROGRAM_COMPLETE) {
app/status_text.h:31: } else if (PowerOn && startval == SAMOVAR_STARTVAL_CALIBRATION) {
app/status_text.h:37: } else if (PowerOn && startval == SAMOVAR_STARTVAL_RECT_IDLE && !stepper.getState()) {
app/status_text.h:54: if (startval == SAMOVAR_STARTVAL_NBK_PROGRAM_RUNNING) {
app/status_text.h:72: if (startval == SAMOVAR_STARTVAL_BEER_MALT_HEATING && program[ProgramNum].WType == "M") {
app/status_text.h:78: } else if (startval == SAMOVAR_STARTVAL_BEER_MALT_WAIT && program[ProgramNum].WType == "M") {
io/actuators.h:24: if (startval != SAMOVAR_STARTVAL_RECT_IDLE && startval != SAMOVAR_STARTVAL_CALIBRATION) {
io/actuators.h:29: startval = SAMOVAR_STARTVAL_RECT_IDLE;
io/actuators.h:37: startval = SAMOVAR_STARTVAL_CALIBRATION;
io/sensor_scan.h:154: startval = SAMOVAR_STARTVAL_RECT_IDLE;
modes/beer/beer_runtime.h:102: if (startval == SAMOVAR_STARTVAL_BEER_ENTRY && !PowerOn) {
modes/beer/beer_runtime.h:118: if (startval == SAMOVAR_STARTVAL_BEER_ENTRY) startval = SAMOVAR_STARTVAL_BEER_MALT_HEATING;
modes/beer/beer_runtime.h:183: startval = SAMOVAR_STARTVAL_RECT_IDLE;
modes/beer/beer_runtime.h:190: if (startval <= SAMOVAR_STARTVAL_BEER_ENTRY) return;
modes/beer/beer_runtime.h:271: if (startval == SAMOVAR_STARTVAL_BEER_MALT_HEATING) {
modes/beer/beer_runtime.h:275: startval = SAMOVAR_STARTVAL_BEER_MALT_WAIT;
modes/nbk/nbk_runtime.h:62: if (startval == SAMOVAR_STARTVAL_NBK_ENTRY) {
modes/nbk/nbk_runtime.h:63: startval = SAMOVAR_STARTVAL_NBK_PROGRAM_RUNNING;
modes/rect/rect_runtime.h:54: (startval == SAMOVAR_STARTVAL_RECT_PROGRAM_RUNNING ||
modes/rect/rect_runtime.h:55: startval == SAMOVAR_STARTVAL_RECT_PROGRAM_COMPLETE)) {
modes/rect/rect_runtime.h:590: wetting_autostart = (startval == SAMOVAR_STARTVAL_RECT_IDLE);
modes/rect/rect_runtime.h:627: if (wetting_autostart && startval == SAMOVAR_STARTVAL_RECT_IDLE) {
state/globals.h:183: extern volatile int16_t startval;
ui/lua/runtime.h:34: //  Variables += "startval = " + String(startval) + "\r\n";
ui/menu/actions.h:199: if (startval > SAMOVAR_STARTVAL_RECT_IDLE && startval != SAMOVAR_STARTVAL_CALIBRATION) {
ui/menu/actions.h:204: if (startval == SAMOVAR_STARTVAL_CALIBRATION) {
ui/menu/actions.h:213: startval = SAMOVAR_STARTVAL_CALIBRATION;
ui/menu/actions.h:221: if (startval == SAMOVAR_STARTVAL_CALIBRATION) {
ui/menu/actions.h:238: if (startval == SAMOVAR_STARTVAL_RECT_PROGRAM_COMPLETE) {
ui/menu/actions.h:239: startval = SAMOVAR_STARTVAL_RECT_STOPPED;
ui/menu/actions.h:240: } else if (ProgramNum >= ProgramLen - 1 && startval != SAMOVAR_STARTVAL_RECT_IDLE) {
ui/menu/actions.h:241: startval = SAMOVAR_STARTVAL_RECT_PROGRAM_COMPLETE;
ui/menu/actions.h:244: if (startval == SAMOVAR_STARTVAL_RECT_IDLE) {
ui/menu/actions.h:250: startval = SAMOVAR_STARTVAL_RECT_PROGRAM_RUNNING;
ui/menu/actions.h:255: } else if (startval == SAMOVAR_STARTVAL_RECT_PROGRAM_RUNNING) {
ui/menu/actions.h:259: } else if (startval == SAMOVAR_STARTVAL_RECT_PROGRAM_COMPLETE) {
ui/menu/input.h:190: if (startval == SAMOVAR_STARTVAL_CALIBRATION) {
ui/menu/input.h:204: if (startval == SAMOVAR_STARTVAL_CALIBRATION) {
ui/menu/input.h:225: if (startval == SAMOVAR_STARTVAL_CALIBRATION) {
ui/menu/input.h:226: startval = SAMOVAR_STARTVAL_RECT_IDLE;
ui/web/ajax_snapshot.h:106: out.print(startval);
ui/web/routes_service.h:19: if (request->hasArg("start") && startval == SAMOVAR_STARTVAL_RECT_IDLE) {
ui/web/routes_service.h:22: if (request->hasArg("finish") && startval == SAMOVAR_STARTVAL_CALIBRATION) {
```

# Related Flags

## PowerOn

```text
Blynk.ino:44: Blynk.virtualWrite(V4, PowerOn);
Blynk.ino:235: if (!PowerOn) return;
Blynk.ino:256: if (Value3 == 1 && PowerOn) menu_samovar_start();
Blynk.ino:262: if (Samovar_Mode == SAMOVAR_BEER_MODE && !PowerOn) {
Blynk.ino:264: } else if (Samovar_Mode == SAMOVAR_BK_MODE && !PowerOn) {
Blynk.ino:266: } else if (Samovar_Mode == SAMOVAR_NBK_MODE && !PowerOn) {
Blynk.ino:268: } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE && !PowerOn) {
Samovar.ino:307: volatile bool PowerOn = false;
app/alarm_control.h:19: if (PowerOn) {
app/loop_dispatch.h:37: set_power(!PowerOn);
app/loop_dispatch.h:38: if (PowerOn && Samovar_Mode == SAMOVAR_RECTIFICATION_MODE) {
app/orchestration.h:498: if (!PowerOn) {
app/orchestration.h:513: if (!PowerOn) {
app/orchestration.h:518: if (!PowerOn) {
app/orchestration.h:523: if (!PowerOn) {
app/orchestration.h:528: if (!PowerOn) {
app/runtime_tasks.h:425: if (TankSensor.avgTemp > (OPEN_VALVE_TANK_TEMP + 2) && PowerOn && waterPulses == 0 && !SamSetup.UseWS) {
app/status_text.h:16: if (!PowerOn && SamovarStatusInt == SAMOVAR_STATUS_OFF) {
app/status_text.h:18: } else if (PowerOn && startval == SAMOVAR_STARTVAL_RECT_PROGRAM_RUNNING && !PauseOn && !program_Wait) {
app/status_text.h:21: } else if (PowerOn && startval == SAMOVAR_STARTVAL_RECT_PROGRAM_RUNNING && program_Wait) {
app/status_text.h:28: } else if (PowerOn && startval == SAMOVAR_STARTVAL_RECT_PROGRAM_COMPLETE) {
app/status_text.h:31: } else if (PowerOn && startval == SAMOVAR_STARTVAL_CALIBRATION) {
app/status_text.h:37: } else if (PowerOn && startval == SAMOVAR_STARTVAL_RECT_IDLE && !stepper.getState()) {
app/status_text.h:107: if (PowerOn) {
app/status_text.h:123: if (PowerOn && (program[ProgramNum].WType == "P" || program[ProgramNum].WType == "B") && begintime > 0) {
app/status_text.h:132: (SamovarStatusInt == SAMOVAR_STATUS_BEER && PowerOn)) {
impurity_detector.h:526: if (heatLossCalculated || BoilerVolume <= 0 || !PowerOn) return;
io/actuators.h:122: if (boil_started || !PowerOn || !valve_status) {
io/power_control.h:22: PowerOn = On;
io/power_control.h:134: if (PowerOn) {
io/power_control.h:223: if (SamSetup.CheckPower && PowerOn) {
io/power_control.h:256: if (!PowerOn) {
io/power_control.h:271: if (!PowerOn) return;
io/sensors.h:74: if (SamSetup.UsePreccureCorrect && bme_pressure > 0 && PowerOn) {
modes/beer/beer_runtime.h:102: if (startval == SAMOVAR_STARTVAL_BEER_ENTRY && !PowerOn) {
modes/beer/beer_runtime.h:109: PowerOn = true;
modes/beer/beer_runtime.h:117: if (Samovar_Mode != SAMOVAR_BEER_MODE || !PowerOn) return;
modes/beer/beer_runtime.h:181: PowerOn = false;
modes/beer/beer_runtime.h:221: if (program[ProgramNum].WType != "C" && program[ProgramNum].WType != "F" && valve_status && PowerOn && program[ProgramNum].WType != "L") {
modes/beer/beer_runtime.h:264: if ((temp < program[ProgramNum].Temp + tempDelta - 0.1) && valve_status && PowerOn) {
modes/bk/bk_alarm.h:22: if (PowerOn && !valve_status && TankSensor.avgTemp >= OPEN_VALVE_TANK_TEMP) {
modes/bk/bk_alarm.h:43: if (!PowerOn && !is_self_test && valve_status && WaterSensor.avgTemp <= TARGET_WATER_TEMP - 20) {
modes/bk/bk_alarm.h:51: if ((WaterSensor.avgTemp >= MAX_WATER_TEMP) && PowerOn) {
modes/bk/bk_alarm.h:60: if (WFAlarmCount > WF_ALARM_COUNT && PowerOn) {
modes/bk/bk_alarm.h:68: if ((WaterSensor.avgTemp >= ALARM_WATER_TEMP - 5) && PowerOn && alarm_t_min == 0) {
modes/bk/bk_runtime.h:19: if (!PowerOn) {
modes/dist/dist_alarm.h:22: } else if (TankSensor.avgTemp >= OPEN_VALVE_TANK_TEMP && PowerOn) {
modes/dist/dist_alarm.h:28: if (!PowerOn && !is_self_test && valve_status && WaterSensor.avgTemp <= SamSetup.SetWaterTemp - DELTA_T_CLOSE_VALVE) {
modes/dist/dist_alarm.h:45: if ((WaterSensor.avgTemp >= MAX_WATER_TEMP || ACPSensor.avgTemp >= MAX_ACP_TEMP) && PowerOn) {
modes/dist/dist_alarm.h:57: if (WFAlarmCount > WF_ALARM_COUNT && PowerOn) {
modes/dist/dist_alarm.h:64: if ((WaterSensor.avgTemp >= ALARM_WATER_TEMP - 5) && PowerOn && alarm_t_min == 0) {
modes/dist/dist_runtime.h:31: //            ", PowerOn: " + String(PowerOn), NOTIFY_MSG);
modes/dist/dist_runtime.h:35: if (!PowerOn) {
modes/dist/dist_runtime.h:79: if (TankSensor.avgTemp > 90 && PowerOn && SamSetup.DistTimeF > 0) {
modes/nbk/nbk_alarm.h:16: if (!PowerOn && !is_self_test && valve_status && WaterSensor.avgTemp <= TARGET_WATER_TEMP - 20) {
modes/nbk/nbk_alarm.h:23: if (!PowerOn) {
modes/nbk/nbk_alarm.h:31: if (PowerOn && !valve_status && TankSensor.avgTemp >= OPEN_VALVE_TANK_TEMP) {
modes/nbk/nbk_alarm.h:46: if (WFAlarmCount > WF_ALARM_COUNT && PowerOn) {
modes/nbk/nbk_alarm.h:53: if ((WaterSensor.avgTemp >= ALARM_WATER_TEMP - 5) && PowerOn && alarm_t_min == 0) {
modes/nbk/nbk_flow_control.h:17: if (PowerOn) {
modes/nbk/nbk_runtime.h:345: // if (Samovar_Mode != SAMOVAR_NBK_MODE || !PowerOn) return; //dranek: лишняя проверка, ломает запуск
modes/nbk/nbk_runtime.h:353: //PowerOn=true;// костыль 2 от незапуска по кнопке Включить нагрев
modes/rect/rect_runtime.h:380: PowerOn) {
modes/rect/rect_runtime.h:397: if (SamSetup.UseHLS && PowerOn) {
modes/rect/rect_runtime.h:485: } else if (TankSensor.avgTemp >= OPEN_VALVE_TANK_TEMP && PowerOn) {
modes/rect/rect_runtime.h:491: if (!PowerOn && !is_self_test && valve_status && WaterSensor.avgTemp <= SamSetup.SetWaterTemp - DELTA_T_CLOSE_VALVE && ACPSensor.avgTemp <= MAX_ACP_TEMP - 10) {
modes/rect/rect_runtime.h:518: if ((SteamSensor.avgTemp >= MAX_STEAM_TEMP || WaterSensor.avgTemp >= MAX_WATER_TEMP || TankSensor.avgTemp >= SamSetup.DistTemp || ACPSensor.avgTemp >= MAX_ACP_TEMP) && PowerOn) {
modes/rect/rect_runtime.h:539: if (WFAlarmCount > WF_ALARM_COUNT && PowerOn) {
modes/rect/rect_runtime.h:547: if ((WaterSensor.avgTemp >= ALARM_WATER_TEMP - 5) && PowerOn && alarm_t_min == 0) {
state/globals.h:146: extern volatile bool PowerOn;
ui/lua/bindings_process.h:16: if (a && !PowerOn) {
ui/lua/bindings_process.h:17: if (Samovar_Mode == SAMOVAR_BEER_MODE && !PowerOn) {
ui/lua/bindings_process.h:19: } else if (Samovar_Mode == SAMOVAR_BK_MODE && !PowerOn) {
ui/lua/bindings_process.h:21: } else if (Samovar_Mode == SAMOVAR_NBK_MODE && !PowerOn) {
ui/lua/bindings_process.h:23: } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE && !PowerOn) {
ui/lua/bindings_process.h:27: } else if (!a && PowerOn)
ui/lua/bindings_variables.h:157: } else if (Var == "PowerOn") {
ui/lua/bindings_variables.h:158: a = PowerOn;
ui/lua/runtime.h:42: Variables += "PowerOn = " + String(PowerOn) + "\r\n";
ui/menu/actions.h:144: if (!PowerOn) {
ui/menu/actions.h:152: if (!PowerOn) {
ui/menu/actions.h:160: if (!PowerOn) {
ui/menu/actions.h:168: if (!PowerOn) {
ui/menu/actions.h:176: if (!PowerOn) {
ui/menu/actions.h:233: if (Samovar_Mode != SAMOVAR_RECTIFICATION_MODE || !PowerOn) {
ui/web/ajax_snapshot.h:95: jsonAddKey(out, first, "PowerOn");
ui/web/ajax_snapshot.h:96: out.print(PowerOn);
ui/web/ajax_snapshot.h:157: (SamovarStatusInt == SAMOVAR_STATUS_BEER && PowerOn))) {
ui/web/ajax_snapshot.h:231: if (PowerOn && Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
ui/web/routes_command.h:52: if (request->hasArg("start") && PowerOn) {
ui/web/routes_command.h:64: if (!PowerOn) sam_command_sync = SAMOVAR_BEER;
ui/web/routes_command.h:68: if (!PowerOn) sam_command_sync = SAMOVAR_DISTILLATION;
ui/web/routes_command.h:72: if (!PowerOn) sam_command_sync = SAMOVAR_BK;
ui/web/routes_command.h:76: if (!PowerOn) sam_command_sync = SAMOVAR_NBK;
ui/web/routes_command.h:101: } else if (request->hasArg("pnbk") && PowerOn) {
ui/web/routes_command.h:118: } else if (request->hasArg("nbkopt") && PowerOn) { // устанавливаем текущие М и Р как оптимальные Мо и Ро
ui/web/routes_setup.h:62: if (PowerOn) {
```

## PauseOn

```text
Blynk.ino:53: if (PauseOn)
Blynk.ino:249: pause_withdrawal(!PauseOn);
Samovar.ino:308: volatile bool PauseOn = false;
app/orchestration.h:503: pause_withdrawal(!PauseOn);
app/status_text.h:18: } else if (PowerOn && startval == SAMOVAR_STARTVAL_RECT_PROGRAM_RUNNING && !PauseOn && !program_Wait) {
app/status_text.h:34: } else if (PauseOn) {
impurity_detector.h:322: // Детектор не работает во время ручной паузы пользователя (PauseOn)
impurity_detector.h:324: if (PauseOn) {
impurity_detector.h:426: if (!program_Wait && !PauseOn) {
impurity_detector.h:446: if (!PauseOn && !isDetectorPause) {
impurity_detector.h:504: if (impurityDetector.correctionFactor < 1.0f && !PauseOn && !program_Wait) {
io/sensor_scan.h:155: PauseOn = false;
modes/rect/rect_runtime.h:88: if (!PauseOn && !program_Wait) {
modes/rect/rect_runtime.h:137: if (!PauseOn && !program_Wait) {
modes/rect/rect_runtime.h:186: if (!stepper.getState() && !PauseOn) return;
modes/rect/rect_runtime.h:187: PauseOn = Pause;
modes/rect/rect_runtime.h:258: PauseOn = false;
state/globals.h:147: extern volatile bool PauseOn;
ui/lua/bindings_variables.h:167: } else if (Var == "PauseOn") {
ui/lua/bindings_variables.h:168: a = PauseOn;
ui/lua/runtime.h:43: Variables += "PauseOn = " + String(PauseOn) + "\r\n";
ui/menu/actions.h:187: pause_withdrawal(!PauseOn);
ui/menu/actions.h:188: if (PauseOn) {
ui/web/ajax_snapshot.h:97: jsonAddKey(out, first, "PauseOn");
ui/web/ajax_snapshot.h:98: out.print(PauseOn);
ui/web/routes_command.h:147: if (PauseOn) {
```

## program_Wait

```text
Blynk.ino:251: program_Wait = false;
Samovar.ino:311: volatile bool program_Wait;
app/loop_dispatch.h:57: program_Wait = false;
app/runtime_tasks.h:267: uint8_t eventCode = program_Wait ? 1 : 0;
app/status_text.h:18: } else if (PowerOn && startval == SAMOVAR_STARTVAL_RECT_PROGRAM_RUNNING && !PauseOn && !program_Wait) {
app/status_text.h:21: } else if (PowerOn && startval == SAMOVAR_STARTVAL_RECT_PROGRAM_RUNNING && program_Wait) {
impurity_detector.h:332: if (program_Wait && (program_Wait_Type == "(царга)" || program_Wait_Type == "(пар)")) {
impurity_detector.h:425: bool isDetectorPause = (program_Wait && program_Wait_Type == "(Детектор)");
impurity_detector.h:426: if (!program_Wait && !PauseOn) {
impurity_detector.h:428: program_Wait = true;
impurity_detector.h:445: bool isDetectorPause = (program_Wait && program_Wait_Type == "(Детектор)");
impurity_detector.h:498: bool isDetectorPause = (program_Wait && program_Wait_Type == "(Детектор)");
impurity_detector.h:504: if (impurityDetector.correctionFactor < 1.0f && !PauseOn && !program_Wait) {
io/sensor_scan.h:156: program_Wait = false;
modes/rect/rect_runtime.h:88: if (!PauseOn && !program_Wait) {
modes/rect/rect_runtime.h:90: program_Wait = true;
modes/rect/rect_runtime.h:102: } else if ((program[ProgramNum].WType == "B" || program[ProgramNum].WType == "C") && SteamSensor.avgTemp < SteamSensor.BodyTemp + SteamSensor.SetTemp && millis() >= t_min && t_min > 0 && program_Wait) {
modes/rect/rect_runtime.h:106: program_Wait = false;
modes/rect/rect_runtime.h:137: if (!PauseOn && !program_Wait) {
modes/rect/rect_runtime.h:139: program_Wait = true;
modes/rect/rect_runtime.h:151: } else if ((program[ProgramNum].WType == "B" || program[ProgramNum].WType == "C") && PipeSensor.avgTemp < PipeSensor.BodyTemp + PipeSensor.SetTemp && millis() >= t_min && t_min > 0 && program_Wait) {
modes/rect/rect_runtime.h:155: program_Wait = false;
modes/rect/rect_runtime.h:174: if (program_Wait && program_Wait_Type == "(Детектор)" && t_min > 0 && millis() >= t_min) {
modes/rect/rect_runtime.h:177: program_Wait = false;
modes/rect/rect_runtime.h:257: program_Wait = false;
state/globals.h:150: extern volatile bool program_Wait;
ui/lua/bindings_variables.h:169: } else if (Var == "program_Wait") {
ui/lua/bindings_variables.h:170: a = program_Wait;
ui/lua/runtime.h:46: Variables += "program_Wait = " + String(program_Wait) + "\r\n";
ui/menu/actions.h:193: program_Wait = false;
```

## program_Pause

```text
Samovar.ino:310: volatile bool program_Pause;
app/orchestration.h:502: } else if (startval != SAMOVAR_STARTVAL_RECT_IDLE && !program_Pause && SamovarStatusInt < SAMOVAR_STATUS_DISTILLATION) {
app/orchestration.h:504: } else if (startval != SAMOVAR_STARTVAL_RECT_IDLE && program_Pause && SamovarStatusInt < SAMOVAR_STATUS_DISTILLATION) {
modes/rect/rect_runtime.h:42: if (program_Pause) {
modes/rect/rect_runtime.h:256: program_Pause = false;
modes/rect/rect_runtime.h:335: program_Pause = true;
state/globals.h:149: extern volatile bool program_Pause;
ui/lua/runtime.h:45: Variables += "program_Pause = " + String(program_Pause) + "\r\n";
```

## stepper.getState()

```text
app/status_text.h:37: } else if (PowerOn && startval == SAMOVAR_STARTVAL_RECT_IDLE && !stepper.getState()) {
io/actuators.h:38: if (!stepper.getState()) stepper.setCurrent(0);
io/actuators.h:52: if (!stepper.getState()) cp = false;
modes/rect/rect_runtime.h:186: if (!stepper.getState() && !PauseOn) return;
ui/web/ajax_snapshot.h:108: out.print(round(stepper.getSpeed() * (uint8_t)stepper.getState()));
```

## wetting_autostart

```text
Samovar.ino:327: bool wetting_autostart = false;
io/sensor_scan.h:132: wetting_autostart = false;
modes/rect/rect_runtime.h:590: wetting_autostart = (startval == SAMOVAR_STARTVAL_RECT_IDLE);
modes/rect/rect_runtime.h:627: if (wetting_autostart && startval == SAMOVAR_STARTVAL_RECT_IDLE) {
modes/rect/rect_runtime.h:628: wetting_autostart = false;
state/globals.h:166: extern bool wetting_autostart;
```

## boil_started

```text
Samovar.ino:317: bool boil_started;
io/actuators.h:106: if (!boil_started) {
io/actuators.h:107: boil_started = true;
io/actuators.h:122: if (boil_started || !PowerOn || !valve_status) {
io/actuators.h:192: if (boil_started) {
io/actuators.h:201: return boil_started;
io/sensor_scan.h:177: boil_started = false;
io/sensors.h:52: //    if (!boil_started)SteamSensor.avgTemp += 1;
io/sensors.h:57: //    if (!boil_started)TankSensor.avgTemp += 0.2;
modes/rect/rect_runtime.h:604: if (SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_STABILIZING && !boil_started) {
modes/rect/rect_runtime.h:606: if (boil_started) {
state/globals.h:156: extern bool boil_started;
support/process_math.h:80: if (!boil_started) return 100;
support/process_math.h:177: if (!boil_started) return 100;
```

# Enum Tokens

## SAMOVAR_NONE

```text
app/loop_dispatch.h:21: if (sam_command_sync == SAMOVAR_NONE) return;
app/loop_dispatch.h:95: case SAMOVAR_NONE:
app/loop_dispatch.h:99: sam_command_sync = SAMOVAR_NONE;
io/sensor_scan.h:110: sam_command_sync = SAMOVAR_NONE;
io/sensor_scan.h:188: sam_command_sync = SAMOVAR_NONE;
src/core/state/status_codes.h:21: SAMOVAR_NONE,
src/core/state/status_codes.h:40: static constexpr SamovarCommands SAMOVAR_COMMAND_NONE = SAMOVAR_NONE;
ui/lua/bindings_variables.h:7: while (sam_command_sync != SAMOVAR_NONE) {
ui/menu/actions.h:280: sam_command_sync = SAMOVAR_NONE;
```

## SAMOVAR_START

```text
Blynk.ino:243: sam_command_sync = SAMOVAR_START;
app/loop_dispatch.h:24: case SAMOVAR_START:
src/core/state/status_codes.h:22: SAMOVAR_START,
src/core/state/status_codes.h:41: static constexpr SamovarCommands SAMOVAR_COMMAND_START = SAMOVAR_START;
ui/lua/bindings_process.h:49: sam_command_sync = SAMOVAR_START;
ui/web/routes_command.h:60: sam_command_sync = SAMOVAR_START;
```

## SAMOVAR_POWER

```text
Blynk.ino:271: sam_command_sync = SAMOVAR_POWER;
app/alarm_control.h:20: sam_command_sync = SAMOVAR_POWER;
app/loop_dispatch.h:28: case SAMOVAR_POWER:
modes/bk/bk_alarm.h:63: sam_command_sync = SAMOVAR_POWER;
modes/dist/dist_alarm.h:59: sam_command_sync = SAMOVAR_POWER;
modes/nbk/nbk_alarm.h:48: sam_command_sync = SAMOVAR_POWER;
modes/rect/rect_runtime.h:542: sam_command_sync = SAMOVAR_POWER;
src/core/state/status_codes.h:23: SAMOVAR_POWER,
src/core/state/status_codes.h:42: static constexpr SamovarCommands SAMOVAR_COMMAND_POWER = SAMOVAR_POWER;
ui/lua/bindings_process.h:26: sam_command_sync = SAMOVAR_POWER;
ui/lua/bindings_process.h:28: sam_command_sync = SAMOVAR_POWER;
ui/menu/actions.h:178: sam_command_sync = SAMOVAR_POWER;
ui/web/routes_command.h:66: sam_command_sync = SAMOVAR_POWER;
ui/web/routes_command.h:70: sam_command_sync = SAMOVAR_POWER;
ui/web/routes_command.h:74: sam_command_sync = SAMOVAR_POWER;
ui/web/routes_command.h:78: sam_command_sync = SAMOVAR_POWER;
ui/web/routes_command.h:80: sam_command_sync = SAMOVAR_POWER;
ui/web/routes_command.h:128: sam_command_sync = SAMOVAR_POWER;
ui/web/routes_command.h:134: sam_command_sync = SAMOVAR_POWER;
ui/web/routes_command.h:140: sam_command_sync = SAMOVAR_POWER;
```

## SAMOVAR_RESET

```text
Blynk.ino:258: sam_command_sync = SAMOVAR_RESET;
app/loop_dispatch.h:42: case SAMOVAR_RESET:
app/loop_dispatch.h:98: if (sam_command_sync != SAMOVAR_RESET) {
io/power_control.h:53: sam_command_sync = SAMOVAR_RESET;
src/core/state/status_codes.h:24: SAMOVAR_RESET,
src/core/state/status_codes.h:43: static constexpr SamovarCommands SAMOVAR_COMMAND_RESET = SAMOVAR_RESET;
ui/web/routes_command.h:84: sam_command_sync = SAMOVAR_RESET;
```

## CALIBRATE_START

```text
app/loop_dispatch.h:45: case CALIBRATE_START:
src/core/state/status_codes.h:25: CALIBRATE_START,
src/core/state/status_codes.h:44: static constexpr SamovarCommands SAMOVAR_COMMAND_CALIBRATE_START = CALIBRATE_START;
ui/web/routes_service.h:20: sam_command_sync = CALIBRATE_START;
```

## CALIBRATE_STOP

```text
app/loop_dispatch.h:48: case CALIBRATE_STOP:
src/core/state/status_codes.h:26: CALIBRATE_STOP,
src/core/state/status_codes.h:45: static constexpr SamovarCommands SAMOVAR_COMMAND_CALIBRATE_STOP = CALIBRATE_STOP;
ui/web/routes_service.h:23: sam_command_sync = CALIBRATE_STOP;
```

## SAMOVAR_PAUSE

```text
app/loop_dispatch.h:51: case SAMOVAR_PAUSE:
src/core/state/status_codes.h:27: SAMOVAR_PAUSE,
src/core/state/status_codes.h:46: static constexpr SamovarCommands SAMOVAR_COMMAND_PAUSE = SAMOVAR_PAUSE;
ui/web/routes_command.h:150: sam_command_sync = SAMOVAR_PAUSE;
```

## SAMOVAR_CONTINUE

```text
app/loop_dispatch.h:54: case SAMOVAR_CONTINUE:
src/core/state/status_codes.h:28: SAMOVAR_CONTINUE,
src/core/state/status_codes.h:47: static constexpr SamovarCommands SAMOVAR_COMMAND_CONTINUE = SAMOVAR_CONTINUE;
ui/web/routes_command.h:148: sam_command_sync = SAMOVAR_CONTINUE;
```

## SAMOVAR_SETBODYTEMP

```text
app/loop_dispatch.h:60: case SAMOVAR_SETBODYTEMP:
src/core/state/status_codes.h:29: SAMOVAR_SETBODYTEMP,
src/core/state/status_codes.h:48: static constexpr SamovarCommands SAMOVAR_COMMAND_SETBODYTEMP = SAMOVAR_SETBODYTEMP;
ui/web/routes_command.h:82: sam_command_sync = SAMOVAR_SETBODYTEMP;
```

## SAMOVAR_DISTILLATION

```text
Blynk.ino:269: sam_command_sync = SAMOVAR_DISTILLATION;
app/loop_dispatch.h:63: case SAMOVAR_DISTILLATION:
app/orchestration.h:514: sam_command_sync = SAMOVAR_DISTILLATION;
src/core/state/status_codes.h:30: SAMOVAR_DISTILLATION,
src/core/state/status_codes.h:49: static constexpr SamovarCommands SAMOVAR_COMMAND_DISTILLATION = SAMOVAR_DISTILLATION;
ui/lua/bindings_process.h:24: sam_command_sync = SAMOVAR_DISTILLATION;
ui/menu/actions.h:154: sam_command_sync = SAMOVAR_DISTILLATION;
ui/web/routes_command.h:68: if (!PowerOn) sam_command_sync = SAMOVAR_DISTILLATION;
ui/web/routes_command.h:126: sam_command_sync = SAMOVAR_DISTILLATION;
```

## SAMOVAR_BEER

```text
Blynk.ino:263: sam_command_sync = SAMOVAR_BEER;
app/loop_dispatch.h:68: case SAMOVAR_BEER:
app/orchestration.h:529: sam_command_sync = SAMOVAR_BEER;
src/core/state/status_codes.h:31: SAMOVAR_BEER,
src/core/state/status_codes.h:50: static constexpr SamovarCommands SAMOVAR_COMMAND_BEER = SAMOVAR_BEER;
ui/lua/bindings_process.h:18: sam_command_sync = SAMOVAR_BEER;
ui/menu/actions.h:146: sam_command_sync = SAMOVAR_BEER;
ui/web/routes_command.h:64: if (!PowerOn) sam_command_sync = SAMOVAR_BEER;
```

## SAMOVAR_BEER_NEXT

```text
Blynk.ino:239: sam_command_sync = SAMOVAR_BEER_NEXT;
app/loop_dispatch.h:73: case SAMOVAR_BEER_NEXT:
src/core/state/status_codes.h:32: SAMOVAR_BEER_NEXT,
src/core/state/status_codes.h:51: static constexpr SamovarCommands SAMOVAR_COMMAND_BEER_NEXT = SAMOVAR_BEER_NEXT;
ui/lua/bindings_process.h:51: sam_command_sync = SAMOVAR_BEER_NEXT;
ui/web/routes_command.h:54: sam_command_sync = SAMOVAR_BEER_NEXT;
```

## SAMOVAR_BK

```text
Blynk.ino:265: sam_command_sync = SAMOVAR_BK;
app/loop_dispatch.h:79: case SAMOVAR_BK:
app/orchestration.h:519: sam_command_sync = SAMOVAR_BK;
src/core/state/status_codes.h:33: SAMOVAR_BK,
src/core/state/status_codes.h:52: static constexpr SamovarCommands SAMOVAR_COMMAND_BK = SAMOVAR_BK;
ui/lua/bindings_process.h:20: sam_command_sync = SAMOVAR_BK;
ui/menu/actions.h:162: sam_command_sync = SAMOVAR_BK;
ui/web/routes_command.h:72: if (!PowerOn) sam_command_sync = SAMOVAR_BK;
ui/web/routes_command.h:132: sam_command_sync = SAMOVAR_BK;
```

## SAMOVAR_NBK

```text
Blynk.ino:267: sam_command_sync = SAMOVAR_NBK;
app/loop_dispatch.h:84: case SAMOVAR_NBK:
app/orchestration.h:524: sam_command_sync = SAMOVAR_NBK;
src/core/state/status_codes.h:34: SAMOVAR_NBK,
src/core/state/status_codes.h:53: static constexpr SamovarCommands SAMOVAR_COMMAND_NBK = SAMOVAR_NBK;
ui/lua/bindings_process.h:22: sam_command_sync = SAMOVAR_NBK;
ui/menu/actions.h:170: sam_command_sync = SAMOVAR_NBK;
ui/web/routes_command.h:76: if (!PowerOn) sam_command_sync = SAMOVAR_NBK;
ui/web/routes_command.h:138: sam_command_sync = SAMOVAR_NBK;
```

## SAMOVAR_SELF_TEST

```text
app/loop_dispatch.h:92: case SAMOVAR_SELF_TEST:
src/core/state/status_codes.h:35: SAMOVAR_SELF_TEST,
src/core/state/status_codes.h:54: static constexpr SamovarCommands SAMOVAR_COMMAND_SELF_TEST = SAMOVAR_SELF_TEST;
ui/web/routes_command.h:90: sam_command_sync = SAMOVAR_SELF_TEST;
```

## SAMOVAR_DIST_NEXT

```text
Blynk.ino:241: sam_command_sync = SAMOVAR_DIST_NEXT;
app/loop_dispatch.h:76: case SAMOVAR_DIST_NEXT:
src/core/state/status_codes.h:36: SAMOVAR_DIST_NEXT,
src/core/state/status_codes.h:55: static constexpr SamovarCommands SAMOVAR_COMMAND_DIST_NEXT = SAMOVAR_DIST_NEXT;
ui/lua/bindings_process.h:53: sam_command_sync = SAMOVAR_DIST_NEXT;
ui/web/routes_command.h:56: sam_command_sync = SAMOVAR_DIST_NEXT;
```

## SAMOVAR_NBK_NEXT

```text
app/loop_dispatch.h:89: case SAMOVAR_NBK_NEXT:
src/core/state/status_codes.h:37: SAMOVAR_NBK_NEXT
src/core/state/status_codes.h:56: static constexpr SamovarCommands SAMOVAR_COMMAND_NBK_NEXT = SAMOVAR_NBK_NEXT;
ui/web/routes_command.h:58: sam_command_sync = SAMOVAR_NBK_NEXT;
```

## SAMOVAR_RECTIFICATION_MODE

```text
app/loop_dispatch.h:25: Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
app/loop_dispatch.h:38: if (PowerOn && Samovar_Mode == SAMOVAR_RECTIFICATION_MODE) {
app/orchestration.h:497: if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE) {
app/runtime_tasks.h:241: s += format_float(get_steam_alcohol(Samovar_Mode == SAMOVAR_RECTIFICATION_MODE ? SteamSensor.avgTemp : TankSensor.avgTemp), 2);
app/runtime_tasks.h:292: if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE) {
app/runtime_tasks.h:355: else if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE && (TargetStepps > 0 || program[ProgramNum].WType == "P")) {
impurity_detector.h:309: if (Samovar_Mode != SAMOVAR_RECTIFICATION_MODE) {
modes/rect/rect_runtime.h:185: if (Samovar_Mode != SAMOVAR_RECTIFICATION_MODE) return;
storage/nvs_migration.h:44: SamSetup.Mode = SAMOVAR_RECTIFICATION_MODE;
storage/nvs_profiles.h:24: case SAMOVAR_RECTIFICATION_MODE:
storage/nvs_profiles.h:32: if (mode < SAMOVAR_RECTIFICATION_MODE || mode > SAMOVAR_LUA_MODE) {
storage/nvs_profiles.h:33: mode = SAMOVAR_RECTIFICATION_MODE;
storage/nvs_profiles.h:41: return (uint8_t)SAMOVAR_RECTIFICATION_MODE;
storage/nvs_profiles.h:43: uint8_t lastMode = meta.getUChar("last_mode", (uint8_t)SAMOVAR_RECTIFICATION_MODE);
storage/nvs_profiles.h:46: lastMode = (uint8_t)SAMOVAR_RECTIFICATION_MODE;
storage/nvs_profiles.h:53: mode = (uint8_t)SAMOVAR_RECTIFICATION_MODE;
storage/session_logs.h:26: if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE || Samovar_Mode == SAMOVAR_BEER_MODE || Samovar_Mode == SAMOVAR_DISTILLATION_MODE || Samovar_Mode == SAMOVAR_NBK_MODE) {
storage/session_logs.h:28: if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE) {
storage/session_logs.h:82: if ((Samovar_Mode == SAMOVAR_RECTIFICATION_MODE || Samovar_Mode == SAMOVAR_BEER_MODE || Samovar_Mode == SAMOVAR_DISTILLATION_MODE || Samovar_Mode == SAMOVAR_NBK_MODE) && STcnt > 10) {
storage/session_logs.h:85: if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE) {
ui/lua/bindings_process.h:48: if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE) {
ui/menu/actions.h:233: if (Samovar_Mode != SAMOVAR_RECTIFICATION_MODE || !PowerOn) {
ui/web/ajax_snapshot.h:154: if ((Samovar_Mode == SAMOVAR_RECTIFICATION_MODE || Samovar_Mode == SAMOVAR_BEER_MODE || Samovar_Mode == SAMOVAR_DISTILLATION_MODE || Samovar_Mode == SAMOVAR_NBK_MODE) &&
ui/web/ajax_snapshot.h:224: if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE || Samovar_Mode == SAMOVAR_RECTIFICATION_MODE || Samovar_Mode == SAMOVAR_BK_MODE || Samovar_Mode == SAMOVAR_NBK_MODE) {
ui/web/ajax_snapshot.h:228: out.print(format_float(get_steam_alcohol(Samovar_Mode == SAMOVAR_RECTIFICATION_MODE ? SteamSensor.avgTemp : TankSensor.avgTemp), 2));
ui/web/page_assets.h:54: Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
ui/web/template_keys.h:278: } else if (var == "RECT" && (SAMOVAR_MODE)SamSetup.Mode == SAMOVAR_RECTIFICATION_MODE)
```

## SAMOVAR_DISTILLATION_MODE

```text
Blynk.ino:180: } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
Blynk.ino:240: } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
Blynk.ino:268: } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE && !PowerOn) {
app/default_programs.h:15: } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
app/loop_dispatch.h:64: Samovar_Mode = SAMOVAR_DISTILLATION_MODE;
app/orchestration.h:512: } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
app/runtime_tasks.h:294: } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
storage/nvs_profiles.h:19: case SAMOVAR_DISTILLATION_MODE: return "sam_dist";
storage/session_logs.h:26: if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE || Samovar_Mode == SAMOVAR_BEER_MODE || Samovar_Mode == SAMOVAR_DISTILLATION_MODE || Samovar_Mode == SAMOVAR_NBK_MODE) {
storage/session_logs.h:34: } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
storage/session_logs.h:82: if ((Samovar_Mode == SAMOVAR_RECTIFICATION_MODE || Samovar_Mode == SAMOVAR_BEER_MODE || Samovar_Mode == SAMOVAR_DISTILLATION_MODE || Samovar_Mode == SAMOVAR_NBK_MODE) && STcnt > 10) {
ui/lua/bindings_process.h:23: } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE && !PowerOn) {
ui/lua/bindings_process.h:52: } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
ui/lua/runtime.h:334: } else if (Samovar_CR_Mode == SAMOVAR_DISTILLATION_MODE) {
ui/menu/actions.h:151: } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
ui/web/ajax_snapshot.h:154: if ((Samovar_Mode == SAMOVAR_RECTIFICATION_MODE || Samovar_Mode == SAMOVAR_BEER_MODE || Samovar_Mode == SAMOVAR_DISTILLATION_MODE || Samovar_Mode == SAMOVAR_NBK_MODE) &&
ui/web/ajax_snapshot.h:224: if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE || Samovar_Mode == SAMOVAR_RECTIFICATION_MODE || Samovar_Mode == SAMOVAR_BK_MODE || Samovar_Mode == SAMOVAR_NBK_MODE) {
ui/web/ajax_snapshot.h:231: if (PowerOn && Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
ui/web/page_assets.h:46: } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
ui/web/routes_command.h:55: } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
ui/web/routes_command.h:67: } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
ui/web/routes_program.h:9: } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
ui/web/template_keys.h:40: else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) return get_dist_program();
ui/web/template_keys.h:280: else if (var == "DIST" && (SAMOVAR_MODE)SamSetup.Mode == SAMOVAR_DISTILLATION_MODE)
```

## SAMOVAR_BEER_MODE

```text
Blynk.ino:178: if (Samovar_Mode == SAMOVAR_BEER_MODE || Samovar_Mode == SAMOVAR_SUVID_MODE) {
Blynk.ino:238: if (Samovar_Mode == SAMOVAR_BEER_MODE) {
Blynk.ino:262: if (Samovar_Mode == SAMOVAR_BEER_MODE && !PowerOn) {
app/default_programs.h:13: if (Samovar_Mode == SAMOVAR_BEER_MODE || Samovar_Mode == SAMOVAR_SUVID_MODE) {
app/loop_dispatch.h:69: Samovar_Mode = SAMOVAR_BEER_MODE;
app/orchestration.h:527: } else if (Samovar_Mode == SAMOVAR_BEER_MODE) {
app/runtime_tasks.h:300: } else if (Samovar_Mode == SAMOVAR_BEER_MODE) {
app/runtime_tasks.h:308: if (Samovar_Mode == SAMOVAR_BEER_MODE) {
modes/beer/beer_runtime.h:117: if (Samovar_Mode != SAMOVAR_BEER_MODE || !PowerOn) return;
storage/nvs_profiles.h:18: case SAMOVAR_BEER_MODE: return "sam_beer";
storage/session_logs.h:26: if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE || Samovar_Mode == SAMOVAR_BEER_MODE || Samovar_Mode == SAMOVAR_DISTILLATION_MODE || Samovar_Mode == SAMOVAR_NBK_MODE) {
storage/session_logs.h:31: } else if (Samovar_Mode == SAMOVAR_BEER_MODE) {
storage/session_logs.h:82: if ((Samovar_Mode == SAMOVAR_RECTIFICATION_MODE || Samovar_Mode == SAMOVAR_BEER_MODE || Samovar_Mode == SAMOVAR_DISTILLATION_MODE || Samovar_Mode == SAMOVAR_NBK_MODE) && STcnt > 10) {
storage/session_logs.h:87: } else if (Samovar_Mode == SAMOVAR_BEER_MODE) {
ui/lua/bindings_process.h:17: if (Samovar_Mode == SAMOVAR_BEER_MODE && !PowerOn) {
ui/lua/bindings_process.h:50: } else if (Samovar_Mode == SAMOVAR_BEER_MODE) {
ui/lua/runtime.h:332: if (Samovar_CR_Mode == SAMOVAR_BEER_MODE) {
ui/menu/actions.h:143: if (Samovar_Mode == SAMOVAR_BEER_MODE) {
ui/web/ajax_snapshot.h:154: if ((Samovar_Mode == SAMOVAR_RECTIFICATION_MODE || Samovar_Mode == SAMOVAR_BEER_MODE || Samovar_Mode == SAMOVAR_DISTILLATION_MODE || Samovar_Mode == SAMOVAR_NBK_MODE) &&
ui/web/page_assets.h:44: if (Samovar_Mode == SAMOVAR_BEER_MODE) {
ui/web/routes_command.h:53: if (Samovar_Mode == SAMOVAR_BEER_MODE) {
ui/web/routes_command.h:63: if (Samovar_Mode == SAMOVAR_BEER_MODE) {
ui/web/routes_program.h:6: if (Samovar_Mode == SAMOVAR_BEER_MODE) {
ui/web/routes_setup.h:190: if (Samovar_Mode == SAMOVAR_BEER_MODE) set_beer_program(request->arg("WProgram"));
ui/web/template_keys.h:39: if (Samovar_Mode == SAMOVAR_BEER_MODE) return get_beer_program();
ui/web/template_keys.h:133: if (Samovar_Mode == SAMOVAR_BEER_MODE) return get_beer_program();
ui/web/template_keys.h:282: else if (var == "BEER" && (SAMOVAR_MODE)SamSetup.Mode == SAMOVAR_BEER_MODE)
```

## SAMOVAR_BK_MODE

```text
Blynk.ino:264: } else if (Samovar_Mode == SAMOVAR_BK_MODE && !PowerOn) {
app/loop_dispatch.h:80: Samovar_Mode = SAMOVAR_BK_MODE;
app/orchestration.h:517: } else if (Samovar_Mode == SAMOVAR_BK_MODE) {
app/runtime_tasks.h:296: } else if (Samovar_Mode == SAMOVAR_BK_MODE) {
app/runtime_tasks.h:349: } else if (Samovar_Mode == SAMOVAR_BK_MODE) {
storage/nvs_profiles.h:20: case SAMOVAR_BK_MODE: return "sam_bk";
ui/lua/bindings_process.h:19: } else if (Samovar_Mode == SAMOVAR_BK_MODE && !PowerOn) {
ui/lua/runtime.h:336: } else if (Samovar_CR_Mode == SAMOVAR_BK_MODE) {
ui/menu/actions.h:159: } else if (Samovar_Mode == SAMOVAR_BK_MODE) {
ui/web/ajax_snapshot.h:224: if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE || Samovar_Mode == SAMOVAR_RECTIFICATION_MODE || Samovar_Mode == SAMOVAR_BK_MODE || Samovar_Mode == SAMOVAR_NBK_MODE) {
ui/web/page_assets.h:48: } else if (Samovar_Mode == SAMOVAR_BK_MODE) {
ui/web/routes_command.h:71: } else if (Samovar_Mode == SAMOVAR_BK_MODE) {
ui/web/template_keys.h:284: else if (var == "BK" && (SAMOVAR_MODE)SamSetup.Mode == SAMOVAR_BK_MODE)
```

## SAMOVAR_NBK_MODE

```text
Blynk.ino:182: } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
Blynk.ino:266: } else if (Samovar_Mode == SAMOVAR_NBK_MODE && !PowerOn) {
app/default_programs.h:17: } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
app/loop_dispatch.h:85: Samovar_Mode = SAMOVAR_NBK_MODE;
app/orchestration.h:522: } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
app/runtime_tasks.h:298: } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
app/runtime_tasks.h:351: } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
modes/nbk/nbk_runtime.h:345: // if (Samovar_Mode != SAMOVAR_NBK_MODE || !PowerOn) return; //dranek: лишняя проверка, ломает запуск
storage/nvs_profiles.h:21: case SAMOVAR_NBK_MODE: return "sam_nbk";
storage/session_logs.h:26: if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE || Samovar_Mode == SAMOVAR_BEER_MODE || Samovar_Mode == SAMOVAR_DISTILLATION_MODE || Samovar_Mode == SAMOVAR_NBK_MODE) {
storage/session_logs.h:37: } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
storage/session_logs.h:82: if ((Samovar_Mode == SAMOVAR_RECTIFICATION_MODE || Samovar_Mode == SAMOVAR_BEER_MODE || Samovar_Mode == SAMOVAR_DISTILLATION_MODE || Samovar_Mode == SAMOVAR_NBK_MODE) && STcnt > 10) {
ui/lua/bindings_process.h:21: } else if (Samovar_Mode == SAMOVAR_NBK_MODE && !PowerOn) {
ui/lua/runtime.h:338: } else if (Samovar_CR_Mode == SAMOVAR_NBK_MODE) {
ui/menu/actions.h:167: } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
ui/web/ajax_snapshot.h:154: if ((Samovar_Mode == SAMOVAR_RECTIFICATION_MODE || Samovar_Mode == SAMOVAR_BEER_MODE || Samovar_Mode == SAMOVAR_DISTILLATION_MODE || Samovar_Mode == SAMOVAR_NBK_MODE) &&
ui/web/ajax_snapshot.h:224: if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE || Samovar_Mode == SAMOVAR_RECTIFICATION_MODE || Samovar_Mode == SAMOVAR_BK_MODE || Samovar_Mode == SAMOVAR_NBK_MODE) {
ui/web/page_assets.h:50: } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
ui/web/routes_command.h:57: } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
ui/web/routes_command.h:75: } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
ui/web/routes_program.h:12: } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
ui/web/template_keys.h:41: else if (Samovar_Mode == SAMOVAR_NBK_MODE) return get_nbk_program();
ui/web/template_keys.h:286: else if (var == "NBK" && (SAMOVAR_MODE)SamSetup.Mode == SAMOVAR_NBK_MODE)
```

## SAMOVAR_SUVID_MODE

```text
Blynk.ino:178: if (Samovar_Mode == SAMOVAR_BEER_MODE || Samovar_Mode == SAMOVAR_SUVID_MODE) {
app/default_programs.h:13: if (Samovar_Mode == SAMOVAR_BEER_MODE || Samovar_Mode == SAMOVAR_SUVID_MODE) {
storage/nvs_profiles.h:22: case SAMOVAR_SUVID_MODE: return "sam_suvid";
ui/web/template_keys.h:288: else if (var == "SUVID" && (SAMOVAR_MODE)SamSetup.Mode == SAMOVAR_SUVID_MODE)
```

## SAMOVAR_LUA_MODE

```text
app/config_apply.h:32: if (SamSetup.Mode > SAMOVAR_LUA_MODE) SamSetup.Mode = 0;
storage/nvs_migration.h:43: if (SamSetup.Mode > SAMOVAR_LUA_MODE) {
storage/nvs_profiles.h:23: case SAMOVAR_LUA_MODE: return "sam_lua";
storage/nvs_profiles.h:32: if (mode < SAMOVAR_RECTIFICATION_MODE || mode > SAMOVAR_LUA_MODE) {
storage/nvs_profiles.h:45: if (lastMode > (uint8_t)SAMOVAR_LUA_MODE) {
storage/nvs_profiles.h:52: if (mode > (uint8_t)SAMOVAR_LUA_MODE) {
ui/web/template_keys.h:290: else if (var == "LUA_MODE" && (SAMOVAR_MODE)SamSetup.Mode == SAMOVAR_LUA_MODE)
```
