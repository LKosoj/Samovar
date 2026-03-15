# Step 2.2a status/command named-constant grep

## Full SamovarStatusInt / sam_command_sync scan

```text
./ui/lua/bindings_process.h:18:      sam_command_sync = SAMOVAR_BEER;
./ui/lua/bindings_process.h:20:      sam_command_sync = SAMOVAR_BK;
./ui/lua/bindings_process.h:22:      sam_command_sync = SAMOVAR_NBK;
./ui/lua/bindings_process.h:24:      sam_command_sync = SAMOVAR_DISTILLATION;
./ui/lua/bindings_process.h:26:      sam_command_sync = SAMOVAR_POWER;
./ui/lua/bindings_process.h:28:    sam_command_sync = SAMOVAR_POWER;
./ui/lua/bindings_process.h:49:    sam_command_sync = SAMOVAR_START;
./ui/lua/bindings_process.h:51:    sam_command_sync = SAMOVAR_BEER_NEXT;
./ui/lua/bindings_process.h:53:    sam_command_sync = SAMOVAR_DIST_NEXT;
./ui/lua/bindings_process.h:60:  lua_pushnumber(lua_state, (lua_Number)SamovarStatusInt);
./io/sensor_scan.h:110:  sam_command_sync = SAMOVAR_NONE;
./io/sensor_scan.h:153:  SamovarStatusInt = SAMOVAR_STATUS_OFF;
./io/sensor_scan.h:188:  sam_command_sync = SAMOVAR_NONE;
./Blynk.ino:239:      sam_command_sync = SAMOVAR_BEER_NEXT;
./Blynk.ino:241:      sam_command_sync = SAMOVAR_DIST_NEXT;
./Blynk.ino:243:      sam_command_sync = SAMOVAR_START;
./Blynk.ino:258:    sam_command_sync = SAMOVAR_RESET;
./Blynk.ino:263:    sam_command_sync = SAMOVAR_BEER;
./Blynk.ino:265:    sam_command_sync = SAMOVAR_BK;
./Blynk.ino:267:    sam_command_sync = SAMOVAR_NBK;
./Blynk.ino:269:    sam_command_sync = SAMOVAR_DISTILLATION;
./Blynk.ino:271:    sam_command_sync = SAMOVAR_POWER;
./io/power_control.h:53:    sam_command_sync = SAMOVAR_RESET;
./io/actuators.h:46:  if (!(SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_RUN ||
./io/actuators.h:47:        SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_WAIT ||
./io/actuators.h:48:        SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_PAUSE)) return;
./app/alarm_control.h:20:    sam_command_sync = SAMOVAR_POWER;
./app/orchestration.h:500:      } else if (startval == 0 && SamovarStatusInt < SAMOVAR_STATUS_DISTILLATION) {
./app/orchestration.h:502:      } else if (startval != 0 && !program_Pause && SamovarStatusInt < SAMOVAR_STATUS_DISTILLATION) {
./app/orchestration.h:504:      } else if (startval != 0 && program_Pause && SamovarStatusInt < SAMOVAR_STATUS_DISTILLATION) {
./app/orchestration.h:514:        sam_command_sync = SAMOVAR_DISTILLATION;
./app/orchestration.h:519:        sam_command_sync = SAMOVAR_BK;
./app/orchestration.h:524:        sam_command_sync = SAMOVAR_NBK;
./app/orchestration.h:529:        sam_command_sync = SAMOVAR_BEER;
./app/orchestration.h:536:  process_sam_command_sync();
./app/loop_dispatch.h:20:inline void process_sam_command_sync() {
./app/loop_dispatch.h:21:  if (sam_command_sync == SAMOVAR_NONE) return;
./app/loop_dispatch.h:23:  switch (sam_command_sync) {
./app/loop_dispatch.h:29:      if (SamovarStatusInt == SAMOVAR_STATUS_DISTILLATION) distiller_finish();
./app/loop_dispatch.h:30:      else if (SamovarStatusInt == SAMOVAR_STATUS_BEER)
./app/loop_dispatch.h:32:      else if (SamovarStatusInt == SAMOVAR_STATUS_BK)
./app/loop_dispatch.h:34:      else if (SamovarStatusInt == SAMOVAR_STATUS_NBK)
./app/loop_dispatch.h:39:        SamovarStatusInt = SAMOVAR_STATUS_RECTIFICATION_WARMUP;
./app/loop_dispatch.h:65:      SamovarStatusInt = SAMOVAR_STATUS_DISTILLATION;
./app/loop_dispatch.h:70:      SamovarStatusInt = SAMOVAR_STATUS_BEER;
./app/loop_dispatch.h:81:      SamovarStatusInt = SAMOVAR_STATUS_BK;
./app/loop_dispatch.h:86:      SamovarStatusInt = SAMOVAR_STATUS_NBK;
./app/loop_dispatch.h:98:  if (sam_command_sync != SAMOVAR_RESET) {
./app/loop_dispatch.h:99:    sam_command_sync = SAMOVAR_NONE;
./app/loop_dispatch.h:104:  if (SamovarStatusInt > SAMOVAR_STATUS_OFF && SamovarStatusInt < SAMOVAR_STATUS_DISTILLATION) {
./app/loop_dispatch.h:106:  } else if (SamovarStatusInt == SAMOVAR_STATUS_DISTILLATION) {
./app/loop_dispatch.h:108:  } else if (SamovarStatusInt == SAMOVAR_STATUS_BK) {
./app/loop_dispatch.h:110:  } else if (SamovarStatusInt == SAMOVAR_STATUS_NBK) {
./app/loop_dispatch.h:112:  } else if (SamovarStatusInt == SAMOVAR_STATUS_BEER && startval == 2000) {
./app/status_text.h:15:  if (!PowerOn && SamovarStatusInt == SAMOVAR_STATUS_OFF) {
./app/status_text.h:19:    SamovarStatusInt = SAMOVAR_STATUS_RECTIFICATION_RUN;
./app/status_text.h:26:    SamovarStatusInt = SAMOVAR_STATUS_RECTIFICATION_WAIT;
./app/status_text.h:29:    SamovarStatusInt = SAMOVAR_STATUS_RECTIFICATION_COMPLETE;
./app/status_text.h:32:    SamovarStatusInt = SAMOVAR_STATUS_CALIBRATION;
./app/status_text.h:35:    SamovarStatusInt = SAMOVAR_STATUS_RECTIFICATION_PAUSE;
./app/status_text.h:37:    if (SamovarStatusInt != SAMOVAR_STATUS_RECTIFICATION_STABILIZING &&
./app/status_text.h:38:        SamovarStatusInt != SAMOVAR_STATUS_RECTIFICATION_STABILIZED) {
./app/status_text.h:40:      SamovarStatusInt = SAMOVAR_STATUS_RECTIFICATION_WARMUP;
./app/status_text.h:41:    } else if (SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_STABILIZING) {
./app/status_text.h:43:    } else if (SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_STABILIZED) {
./app/status_text.h:46:  } else if (SamovarStatusInt == SAMOVAR_STATUS_DISTILLATION) {
./app/status_text.h:50:  } else if (SamovarStatusInt == SAMOVAR_STATUS_BK) {
./app/status_text.h:52:  } else if (SamovarStatusInt == SAMOVAR_STATUS_NBK) {
./app/status_text.h:65:  } else if (SamovarStatusInt == SAMOVAR_STATUS_BEER) {
./app/status_text.h:129:  if (SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_RUN ||
./app/status_text.h:130:      SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_WAIT ||
./app/status_text.h:131:      (SamovarStatusInt == SAMOVAR_STATUS_BEER && PowerOn)) {
./app/process_common.h:23:  SamovarStatusInt = SAMOVAR_STATUS_OFF;
./impurity_detector.h:302:  if (!SamSetup.useautospeed || SamovarStatusInt != SAMOVAR_STATUS_RECTIFICATION_RUN) {
./modes/nbk/nbk_alarm.h:48:    sam_command_sync = SAMOVAR_POWER;
./modes/nbk/nbk_runtime.h:65:      SamovarStatusInt = SAMOVAR_STATUS_NBK; // Именно в таком порядке
./modes/dist/dist_runtime.h:29://    SendMsg("Статус: " + String(SamovarStatusInt) +
./modes/dist/dist_runtime.h:33:  if (SamovarStatusInt != SAMOVAR_STATUS_DISTILLATION) return;
./modes/dist/dist_alarm.h:59:    sam_command_sync = SAMOVAR_POWER;
./modes/rect/rect_runtime.h:33:  if (!(SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_RUN ||
./modes/rect/rect_runtime.h:34:        SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_WAIT ||
./modes/rect/rect_runtime.h:35:        SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_PAUSE)) return;
./modes/rect/rect_runtime.h:376:  if (SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_WARMUP &&
./modes/rect/rect_runtime.h:540:    sam_command_sync = SAMOVAR_POWER;
./modes/rect/rect_runtime.h:565:  if (SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_WARMUP &&
./modes/rect/rect_runtime.h:581:        SamovarStatusInt = SAMOVAR_STATUS_RECTIFICATION_STABILIZING;
./modes/rect/rect_runtime.h:602:  if (SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_STABILIZING && !boil_started) {
./modes/rect/rect_runtime.h:611:  if (SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_STABILIZING &&
./modes/rect/rect_runtime.h:619:        SamovarStatusInt = SAMOVAR_STATUS_RECTIFICATION_STABILIZED;
./modes/beer/beer_runtime.h:100:  if (SamovarStatusInt != SAMOVAR_STATUS_BEER) return;
./modes/beer/beer_support.h:10:  if (SamovarStatusInt != SAMOVAR_STATUS_BEER) return 0.0;
./modes/bk/bk_alarm.h:63:    sam_command_sync = SAMOVAR_POWER;
./Samovar.ino:252:volatile SamovarCommands sam_command_sync;
./Samovar.ino:337:volatile int16_t SamovarStatusInt;
./ui/lua/bindings_variables.h:7:  while (sam_command_sync != SAMOVAR_NONE) {
./ui/lua/runtime.h:30:  Variables += "SamovarStatusInt = " + String(SamovarStatusInt) + "\r\n";
./ui/menu/actions.h:146:      sam_command_sync = SAMOVAR_BEER;
./ui/menu/actions.h:154:      sam_command_sync = SAMOVAR_DISTILLATION;
./ui/menu/actions.h:162:      sam_command_sync = SAMOVAR_BK;
./ui/menu/actions.h:170:      sam_command_sync = SAMOVAR_NBK;
./ui/menu/actions.h:178:      sam_command_sync = SAMOVAR_POWER;
./ui/menu/actions.h:280:  sam_command_sync = SAMOVAR_NONE;
./ui/web/routes_command.h:54:      sam_command_sync = SAMOVAR_BEER_NEXT;
./ui/web/routes_command.h:56:      sam_command_sync = SAMOVAR_DIST_NEXT;
./ui/web/routes_command.h:58:      sam_command_sync = SAMOVAR_NBK_NEXT;
./ui/web/routes_command.h:60:      sam_command_sync = SAMOVAR_START;
./ui/web/routes_command.h:64:      if (!PowerOn) sam_command_sync = SAMOVAR_BEER;
./ui/web/routes_command.h:66:        sam_command_sync = SAMOVAR_POWER;
./ui/web/routes_command.h:68:      if (!PowerOn) sam_command_sync = SAMOVAR_DISTILLATION;
./ui/web/routes_command.h:70:        sam_command_sync = SAMOVAR_POWER;
./ui/web/routes_command.h:72:      if (!PowerOn) sam_command_sync = SAMOVAR_BK;
./ui/web/routes_command.h:74:        sam_command_sync = SAMOVAR_POWER;
./ui/web/routes_command.h:76:      if (!PowerOn) sam_command_sync = SAMOVAR_NBK;
./ui/web/routes_command.h:78:        sam_command_sync = SAMOVAR_POWER;
./ui/web/routes_command.h:80:      sam_command_sync = SAMOVAR_POWER;
./ui/web/routes_command.h:82:    sam_command_sync = SAMOVAR_SETBODYTEMP;
./ui/web/routes_command.h:84:    sam_command_sync = SAMOVAR_RESET;
./ui/web/routes_command.h:90:    sam_command_sync = SAMOVAR_SELF_TEST;
./ui/web/routes_command.h:126:      sam_command_sync = SAMOVAR_DISTILLATION;
./ui/web/routes_command.h:128:      sam_command_sync = SAMOVAR_POWER;
./ui/web/routes_command.h:132:      sam_command_sync = SAMOVAR_BK;
./ui/web/routes_command.h:134:      sam_command_sync = SAMOVAR_POWER;
./ui/web/routes_command.h:138:      sam_command_sync = SAMOVAR_NBK;
./ui/web/routes_command.h:140:      sam_command_sync = SAMOVAR_POWER;
./ui/web/routes_command.h:148:      sam_command_sync = SAMOVAR_CONTINUE;
./ui/web/routes_command.h:150:      sam_command_sync = SAMOVAR_PAUSE;
./ui/web/routes_service.h:20:        sam_command_sync = CALIBRATE_START;
./ui/web/routes_service.h:23:        sam_command_sync = CALIBRATE_STOP;
./ui/web/ajax_snapshot.h:155:      (SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_RUN ||
./ui/web/ajax_snapshot.h:156:       SamovarStatusInt == SAMOVAR_STATUS_RECTIFICATION_WAIT ||
./ui/web/ajax_snapshot.h:157:       (SamovarStatusInt == SAMOVAR_STATUS_BEER && PowerOn))) {
./ui/web/routes_setup.h:63:    if (SamovarStatusInt == SAMOVAR_STATUS_DISTILLATION) {
./ui/web/routes_setup.h:65:    } else if (SamovarStatusInt == SAMOVAR_STATUS_BEER) {
./ui/web/routes_setup.h:67:    } else if (SamovarStatusInt == SAMOVAR_STATUS_BK) {
./ui/web/routes_setup.h:69:    } else if (SamovarStatusInt == SAMOVAR_STATUS_NBK) {
./state/globals.h:122:extern volatile SamovarCommands sam_command_sync;
./state/globals.h:176:extern volatile int16_t SamovarStatusInt;
```

## Raw numeric literal matches for SamovarStatusInt

_No raw numeric literal matches found._

## Raw numeric literal matches for sam_command_sync

_No raw numeric literal matches found._
