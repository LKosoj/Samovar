# Step 2.2b mode/startval named-constant grep

Verified: `2026-03-15`

## Full Samovar_Mode / Samovar_CR_Mode / startval scan

```text
./storage/nvs_profiles.h:31:  int mode = (int)Samovar_CR_Mode;
./storage/nvs_profiles.h:188:  Samovar_CR_Mode = (SAMOVAR_MODE)lastMode;
./storage/nvs_migration.h:41:    SAMOVAR_MODE backupMode = Samovar_CR_Mode;
./storage/nvs_migration.h:46:    Samovar_CR_Mode = (SAMOVAR_MODE)SamSetup.Mode;
./storage/nvs_migration.h:51:    Samovar_CR_Mode = backupMode;
./storage/session_logs.h:26:  if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE || Samovar_Mode == SAMOVAR_BEER_MODE || Samovar_Mode == SAMOVAR_DISTILLATION_MODE || Samovar_Mode == SAMOVAR_NBK_MODE) {
./storage/session_logs.h:28:    if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE) {
./storage/session_logs.h:31:    } else if (Samovar_Mode == SAMOVAR_BEER_MODE) {
./storage/session_logs.h:34:    } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
./storage/session_logs.h:37:    } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
./storage/session_logs.h:82:  if ((Samovar_Mode == SAMOVAR_RECTIFICATION_MODE || Samovar_Mode == SAMOVAR_BEER_MODE || Samovar_Mode == SAMOVAR_DISTILLATION_MODE || Samovar_Mode == SAMOVAR_NBK_MODE) && STcnt > 10) {
./storage/session_logs.h:85:    if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE) {
./storage/session_logs.h:87:    } else if (Samovar_Mode == SAMOVAR_BEER_MODE) {
./io/sensor_scan.h:154:  startval = SAMOVAR_STARTVAL_RECT_IDLE;
./io/actuators.h:24:  if (startval != SAMOVAR_STARTVAL_RECT_IDLE && startval != SAMOVAR_STARTVAL_CALIBRATION) {
./io/actuators.h:29:    startval = SAMOVAR_STARTVAL_RECT_IDLE;
./io/actuators.h:37:    startval = SAMOVAR_STARTVAL_CALIBRATION;
./state/globals.h:36:extern char startval_text_val[20];
./state/globals.h:37:extern char* startval_text;
./state/globals.h:124:extern volatile SAMOVAR_MODE Samovar_Mode;
./state/globals.h:125:extern volatile SAMOVAR_MODE Samovar_CR_Mode;
./state/globals.h:183:extern volatile int16_t startval;
./impurity_detector.h:309:  if (Samovar_Mode != SAMOVAR_RECTIFICATION_MODE) {
./app/orchestration.h:497:    if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE) {
./app/orchestration.h:500:      } else if (startval == SAMOVAR_STARTVAL_RECT_IDLE && SamovarStatusInt < SAMOVAR_STATUS_DISTILLATION) {
./app/orchestration.h:502:      } else if (startval != SAMOVAR_STARTVAL_RECT_IDLE && !program_Pause && SamovarStatusInt < SAMOVAR_STATUS_DISTILLATION) {
./app/orchestration.h:504:      } else if (startval != SAMOVAR_STARTVAL_RECT_IDLE && program_Pause && SamovarStatusInt < SAMOVAR_STATUS_DISTILLATION) {
./app/orchestration.h:507:      if (startval == SAMOVAR_STARTVAL_CALIBRATION) {
./app/orchestration.h:508:        startval = SAMOVAR_STARTVAL_RECT_IDLE;
./app/orchestration.h:512:    } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
./app/orchestration.h:517:    } else if (Samovar_Mode == SAMOVAR_BK_MODE) {
./app/orchestration.h:522:    } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
./app/orchestration.h:527:    } else if (Samovar_Mode == SAMOVAR_BEER_MODE) {
./ui/lua/bindings_process.h:17:    if (Samovar_Mode == SAMOVAR_BEER_MODE && !PowerOn) {
./ui/lua/bindings_process.h:19:    } else if (Samovar_Mode == SAMOVAR_BK_MODE && !PowerOn) {
./ui/lua/bindings_process.h:21:    } else if (Samovar_Mode == SAMOVAR_NBK_MODE && !PowerOn) {
./ui/lua/bindings_process.h:23:    } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE && !PowerOn) {
./ui/lua/bindings_process.h:48:  if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE) {
./ui/lua/bindings_process.h:50:  } else if (Samovar_Mode == SAMOVAR_BEER_MODE) {
./ui/lua/bindings_process.h:52:  } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
./ui/lua/bindings_variables.h:46:  } else if (Var == "Samovar_Mode") {
./ui/lua/bindings_variables.h:47:    Samovar_Mode = (SAMOVAR_MODE)a;
./ui/lua/bindings_variables.h:48:  } else if (Var == "Samovar_CR_Mode") {
./ui/lua/bindings_variables.h:49:    Samovar_CR_Mode = (SAMOVAR_MODE)a;
./ui/lua/bindings_variables.h:109:  } else if (Var == "Samovar_Mode") {
./ui/lua/bindings_variables.h:110:    a = Samovar_Mode;
./ui/lua/bindings_variables.h:111:  } else if (Var == "Samovar_CR_Mode") {
./ui/lua/bindings_variables.h:112:    a = Samovar_CR_Mode;
./ui/lua/runtime.h:34:  //  Variables += "startval = " + String(startval) + "\r\n";
./ui/lua/runtime.h:332:  if (Samovar_CR_Mode == SAMOVAR_BEER_MODE) {
./ui/lua/runtime.h:334:  } else if (Samovar_CR_Mode == SAMOVAR_DISTILLATION_MODE) {
./ui/lua/runtime.h:336:  } else if (Samovar_CR_Mode == SAMOVAR_BK_MODE) {
./ui/lua/runtime.h:338:  } else if (Samovar_CR_Mode == SAMOVAR_NBK_MODE) {
./ui/menu/screens.h:17:inline const char* get_startval_text() {
./ui/menu/screens.h:18:  return startval_text_val;
./ui/menu/screens.h:93:static LiquidLine lql_start(0, 0, str_Start, get_startval_text);
./ui/menu/input.h:190:    if (startval == SAMOVAR_STARTVAL_CALIBRATION) {
./ui/menu/input.h:204:    if (startval == SAMOVAR_STARTVAL_CALIBRATION) {
./ui/menu/input.h:225:    if (startval == SAMOVAR_STARTVAL_CALIBRATION) {
./ui/menu/input.h:226:      startval = SAMOVAR_STARTVAL_RECT_IDLE;
./ui/menu/actions.h:143:  if (Samovar_Mode == SAMOVAR_BEER_MODE) {
./ui/menu/actions.h:151:  } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
./ui/menu/actions.h:159:  } else if (Samovar_Mode == SAMOVAR_BK_MODE) {
./ui/menu/actions.h:167:  } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
./ui/menu/actions.h:199:  if (startval > SAMOVAR_STARTVAL_RECT_IDLE && startval != SAMOVAR_STARTVAL_CALIBRATION) {
./ui/menu/actions.h:204:  if (startval == SAMOVAR_STARTVAL_CALIBRATION) {
./ui/menu/actions.h:213:    startval = SAMOVAR_STARTVAL_CALIBRATION;
./ui/menu/actions.h:221:  if (startval == SAMOVAR_STARTVAL_CALIBRATION) {
./ui/menu/actions.h:233:  if (Samovar_Mode != SAMOVAR_RECTIFICATION_MODE || !PowerOn) {
./ui/menu/actions.h:238:  if (startval == SAMOVAR_STARTVAL_RECT_PROGRAM_COMPLETE) {
./ui/menu/actions.h:239:    startval = SAMOVAR_STARTVAL_RECT_STOPPED;
./ui/menu/actions.h:240:  } else if (ProgramNum >= ProgramLen - 1 && startval != SAMOVAR_STARTVAL_RECT_IDLE) {
./ui/menu/actions.h:241:    startval = SAMOVAR_STARTVAL_RECT_PROGRAM_COMPLETE;
./ui/menu/actions.h:244:  if (startval == SAMOVAR_STARTVAL_RECT_IDLE) {
./ui/menu/actions.h:250:    startval = SAMOVAR_STARTVAL_RECT_PROGRAM_RUNNING;
./ui/menu/actions.h:255:  } else if (startval == SAMOVAR_STARTVAL_RECT_PROGRAM_RUNNING) {
./ui/menu/actions.h:259:  } else if (startval == SAMOVAR_STARTVAL_RECT_PROGRAM_COMPLETE) {
./ui/menu/actions.h:267:  copyStringSafe(startval_text_val, Str);
./ui/menu/actions.h:275:  memcpy(str, startval_text_val, 20);
./ui/web/routes_command.h:53:    if (Samovar_Mode == SAMOVAR_BEER_MODE) {
./ui/web/routes_command.h:55:    } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
./ui/web/routes_command.h:57:    } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
./ui/web/routes_command.h:63:    if (Samovar_Mode == SAMOVAR_BEER_MODE) {
./ui/web/routes_command.h:67:    } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
./ui/web/routes_command.h:71:    } else if (Samovar_Mode == SAMOVAR_BK_MODE) {
./ui/web/routes_command.h:75:    } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
./ui/web/template_keys.h:39:    if (Samovar_Mode == SAMOVAR_BEER_MODE) return get_beer_program();
./ui/web/template_keys.h:40:    else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) return get_dist_program();
./ui/web/template_keys.h:41:    else if (Samovar_Mode == SAMOVAR_NBK_MODE) return get_nbk_program();
./ui/web/template_keys.h:133:    if (Samovar_Mode == SAMOVAR_BEER_MODE) return get_beer_program();
./ui/web/routes_program.h:6:    if (Samovar_Mode == SAMOVAR_BEER_MODE) {
./ui/web/routes_program.h:9:    } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
./ui/web/routes_program.h:12:    } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
./ui/web/page_assets.h:44:  if (Samovar_Mode == SAMOVAR_BEER_MODE) {
./ui/web/page_assets.h:46:  } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
./ui/web/page_assets.h:48:  } else if (Samovar_Mode == SAMOVAR_BK_MODE) {
./ui/web/page_assets.h:50:  } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
./ui/web/page_assets.h:54:    Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
./ui/web/page_assets.h:56:  Samovar_CR_Mode = Samovar_Mode;
./ui/web/routes_service.h:19:      if (request->hasArg("start") && startval == SAMOVAR_STARTVAL_RECT_IDLE) {
./ui/web/routes_service.h:22:      if (request->hasArg("finish") && startval == SAMOVAR_STARTVAL_CALIBRATION) {
./ui/web/ajax_snapshot.h:106:  out.print(startval);
./ui/web/ajax_snapshot.h:154:  if ((Samovar_Mode == SAMOVAR_RECTIFICATION_MODE || Samovar_Mode == SAMOVAR_BEER_MODE || Samovar_Mode == SAMOVAR_DISTILLATION_MODE || Samovar_Mode == SAMOVAR_NBK_MODE) &&
./ui/web/ajax_snapshot.h:224:  if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE || Samovar_Mode == SAMOVAR_RECTIFICATION_MODE || Samovar_Mode == SAMOVAR_BK_MODE || Samovar_Mode == SAMOVAR_NBK_MODE) {
./ui/web/ajax_snapshot.h:228:    out.print(format_float(get_steam_alcohol(Samovar_Mode == SAMOVAR_RECTIFICATION_MODE ? SteamSensor.avgTemp : TankSensor.avgTemp), 2));
./ui/web/ajax_snapshot.h:231:  if (PowerOn && Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
./ui/web/routes_setup.h:87:  Samovar_Mode = (SAMOVAR_MODE)SamSetup.Mode;
./ui/web/routes_setup.h:88:  Samovar_CR_Mode = Samovar_Mode;
./ui/web/routes_setup.h:190:    if (Samovar_Mode == SAMOVAR_BEER_MODE) set_beer_program(request->arg("WProgram"));
./Blynk.ino:47:  if (startval > SAMOVAR_STARTVAL_RECT_IDLE && startval <= SAMOVAR_STARTVAL_RECT_STOPPED)
./Blynk.ino:170:  Blynk.virtualWrite(V20, Samovar_Mode);
./Blynk.ino:178:  if (Samovar_Mode == SAMOVAR_BEER_MODE || Samovar_Mode == SAMOVAR_SUVID_MODE) {
./Blynk.ino:180:  } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
./Blynk.ino:182:  } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
./Blynk.ino:238:    if (Samovar_Mode == SAMOVAR_BEER_MODE) {
./Blynk.ino:240:    } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
./Blynk.ino:262:  if (Samovar_Mode == SAMOVAR_BEER_MODE && !PowerOn) {
./Blynk.ino:264:  } else if (Samovar_Mode == SAMOVAR_BK_MODE && !PowerOn) {
./Blynk.ino:266:  } else if (Samovar_Mode == SAMOVAR_NBK_MODE && !PowerOn) {
./Blynk.ino:268:  } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE && !PowerOn) {
./modes/nbk/nbk_runtime.h:62:    if (startval == SAMOVAR_STARTVAL_NBK_ENTRY) {
./modes/nbk/nbk_runtime.h:63:      startval = SAMOVAR_STARTVAL_NBK_PROGRAM_RUNNING;
./modes/nbk/nbk_runtime.h:345: // if (Samovar_Mode != SAMOVAR_NBK_MODE || !PowerOn) return; //dranek: лишняя проверка, ломает запуск
./modes/dist/dist_runtime.h:30://            ", Режим: " + String(Samovar_Mode) +
./modes/rect/rect_runtime.h:54:      (startval == SAMOVAR_STARTVAL_RECT_PROGRAM_RUNNING ||
./modes/rect/rect_runtime.h:55:       startval == SAMOVAR_STARTVAL_RECT_PROGRAM_COMPLETE)) {
./modes/rect/rect_runtime.h:185:  if (Samovar_Mode != SAMOVAR_RECTIFICATION_MODE) return;
./modes/rect/rect_runtime.h:590:        wetting_autostart = (startval == SAMOVAR_STARTVAL_RECT_IDLE);
./modes/rect/rect_runtime.h:627:        if (wetting_autostart && startval == SAMOVAR_STARTVAL_RECT_IDLE) {
./modes/beer/beer_runtime.h:102:  if (startval == SAMOVAR_STARTVAL_BEER_ENTRY && !PowerOn) {
./modes/beer/beer_runtime.h:117:  if (Samovar_Mode != SAMOVAR_BEER_MODE || !PowerOn) return;
./modes/beer/beer_runtime.h:118:  if (startval == SAMOVAR_STARTVAL_BEER_ENTRY) startval = SAMOVAR_STARTVAL_BEER_MALT_HEATING;
./modes/beer/beer_runtime.h:183:  startval = SAMOVAR_STARTVAL_RECT_IDLE;
./modes/beer/beer_runtime.h:190:  if (startval <= SAMOVAR_STARTVAL_BEER_ENTRY) return;
./modes/beer/beer_runtime.h:271:    if (startval == SAMOVAR_STARTVAL_BEER_MALT_HEATING) {
./modes/beer/beer_runtime.h:275:    startval = SAMOVAR_STARTVAL_BEER_MALT_WAIT;
./Samovar.ino:171:char startval_text_val[20];
./Samovar.ino:172:char* startval_text = (char*)startval_text_val;
./Samovar.ino:254:volatile SAMOVAR_MODE Samovar_Mode;
./Samovar.ino:255:volatile SAMOVAR_MODE Samovar_CR_Mode;
./Samovar.ino:344:volatile int16_t startval = SAMOVAR_STARTVAL_RECT_IDLE;
./app/loop_dispatch.h:25:      Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
./app/loop_dispatch.h:38:      if (PowerOn && Samovar_Mode == SAMOVAR_RECTIFICATION_MODE) {
./app/loop_dispatch.h:64:      Samovar_Mode = SAMOVAR_DISTILLATION_MODE;
./app/loop_dispatch.h:66:      startval = SAMOVAR_STARTVAL_DISTILLATION_ENTRY;
./app/loop_dispatch.h:69:      Samovar_Mode = SAMOVAR_BEER_MODE;
./app/loop_dispatch.h:71:      startval = SAMOVAR_STARTVAL_BEER_ENTRY;
./app/loop_dispatch.h:80:      Samovar_Mode = SAMOVAR_BK_MODE;
./app/loop_dispatch.h:82:      startval = SAMOVAR_STARTVAL_BK_ENTRY;
./app/loop_dispatch.h:85:      Samovar_Mode = SAMOVAR_NBK_MODE;
./app/loop_dispatch.h:87:      startval = SAMOVAR_STARTVAL_NBK_ENTRY;
./app/loop_dispatch.h:112:  } else if (SamovarStatusInt == SAMOVAR_STATUS_BEER && startval == SAMOVAR_STARTVAL_BEER_ENTRY) {
./app/status_text.h:18:  } else if (PowerOn && startval == SAMOVAR_STARTVAL_RECT_PROGRAM_RUNNING && !PauseOn && !program_Wait) {
./app/status_text.h:21:  } else if (PowerOn && startval == SAMOVAR_STARTVAL_RECT_PROGRAM_RUNNING && program_Wait) {
./app/status_text.h:28:  } else if (PowerOn && startval == SAMOVAR_STARTVAL_RECT_PROGRAM_COMPLETE) {
./app/status_text.h:31:  } else if (PowerOn && startval == SAMOVAR_STARTVAL_CALIBRATION) {
./app/status_text.h:37:  } else if (PowerOn && startval == SAMOVAR_STARTVAL_RECT_IDLE && !stepper.getState()) {
./app/status_text.h:54:    if (startval == SAMOVAR_STARTVAL_NBK_PROGRAM_RUNNING) {
./app/status_text.h:72:    if (startval == SAMOVAR_STARTVAL_BEER_MALT_HEATING && program[ProgramNum].WType == "M") {
./app/status_text.h:78:    } else if (startval == SAMOVAR_STARTVAL_BEER_MALT_WAIT && program[ProgramNum].WType == "M") {
./app/config_apply.h:33:  Samovar_Mode = (SAMOVAR_MODE)SamSetup.Mode;
./app/default_programs.h:13:  if (Samovar_Mode == SAMOVAR_BEER_MODE || Samovar_Mode == SAMOVAR_SUVID_MODE) {
./app/default_programs.h:15:  } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
./app/default_programs.h:17:  } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
./app/runtime_tasks.h:222:      if (startval != SAMOVAR_STARTVAL_RECT_IDLE) {
./app/runtime_tasks.h:241:            s += format_float(get_steam_alcohol(Samovar_Mode == SAMOVAR_RECTIFICATION_MODE ? SteamSensor.avgTemp : TankSensor.avgTemp), 2);
./app/runtime_tasks.h:282:            s += ","; s += String((int)Samovar_Mode); // 24: mode
./app/runtime_tasks.h:292:      if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE) {
./app/runtime_tasks.h:294:      } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
./app/runtime_tasks.h:296:      } else if (Samovar_Mode == SAMOVAR_BK_MODE) {
./app/runtime_tasks.h:298:      } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
./app/runtime_tasks.h:300:      } else if (Samovar_Mode == SAMOVAR_BEER_MODE) {
./app/runtime_tasks.h:308:      if (Samovar_Mode == SAMOVAR_BEER_MODE) {
./app/runtime_tasks.h:349:      } else if (Samovar_Mode == SAMOVAR_BK_MODE) {
./app/runtime_tasks.h:351:      } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
./app/runtime_tasks.h:355:      else if (Samovar_Mode == SAMOVAR_RECTIFICATION_MODE && (TargetStepps > 0 || program[ProgramNum].WType == "P")) {
```

## Raw numeric literal matches for Samovar_Mode / Samovar_CR_Mode

_No raw numeric literal matches found._

## Raw numeric literal matches for startval

_No raw numeric literal matches found._
