#pragma once

#include "Samovar.h"
#include "runtime_helpers.h"

using ModeVoidFn = void (*)();
using ModeStatusFn = String (*)();

struct ModeOps {
  SAMOVAR_MODE mode;
  int16_t activeStatus;
  const char* pagePath;
  SamovarCommands powerOnCommand;
  SamovarCommands startCommand;
  ModeVoidFn alarm;
  ModeVoidFn finish;
  ModeStatusFn status;
};

inline void mode_alarm_nbk() {
  if (!check_nbk_critical_alarms()) check_alarm_nbk();
}

inline void mode_alarm_beer() {
  check_alarm_beer();
  water_pulse_count_set(100);
}

inline const ModeOps* mode_registry() {
  static const ModeOps ops[] = {
    {SAMOVAR_RECTIFICATION_MODE, 0, "/index.htm", SAMOVAR_POWER, SAMOVAR_START, check_alarm, nullptr, nullptr},
    {SAMOVAR_DISTILLATION_MODE, 1000, "/distiller.htm", SAMOVAR_DISTILLATION, SAMOVAR_DIST_NEXT, check_alarm_distiller, distiller_finish, get_distiller_status_text},
    {SAMOVAR_BEER_MODE, 2000, "/beer.htm", SAMOVAR_BEER, SAMOVAR_BEER_NEXT, mode_alarm_beer, beer_finish, get_beer_status_text},
    {SAMOVAR_BK_MODE, 3000, "/bk.htm", SAMOVAR_BK, SAMOVAR_START, check_alarm_bk, bk_finish, get_bk_status_text},
    {SAMOVAR_NBK_MODE, 4000, "/nbk.htm", SAMOVAR_NBK, SAMOVAR_NBK_NEXT, mode_alarm_nbk, nbk_finish, get_nbk_status_text},
    {SAMOVAR_SUVID_MODE, 0, "/index.htm", SAMOVAR_POWER, SAMOVAR_START, nullptr, nullptr, nullptr},
    {SAMOVAR_LUA_MODE, 0, "/index.htm", SAMOVAR_POWER, SAMOVAR_START, nullptr, nullptr, nullptr},
  };
  return ops;
}

inline size_t mode_registry_count() {
  return 7;
}

inline const ModeOps* mode_ops_by_mode(SAMOVAR_MODE mode) {
  const ModeOps* ops = mode_registry();
  for (size_t i = 0; i < mode_registry_count(); i++) {
    if (ops[i].mode == mode) return &ops[i];
  }
  return nullptr;
}

inline const ModeOps* mode_ops_by_status(int16_t status) {
  if (status <= 0) return nullptr;
  if (status > 0 && status < 1000) return mode_ops_by_mode(SAMOVAR_RECTIFICATION_MODE);
  const ModeOps* ops = mode_registry();
  for (size_t i = 0; i < mode_registry_count(); i++) {
    if (ops[i].activeStatus == status) return &ops[i];
  }
  return nullptr;
}

inline const ModeOps* mode_ops_by_power_on_command(SamovarCommands command) {
  const ModeOps* ops = mode_registry();
  for (size_t i = 0; i < mode_registry_count(); i++) {
    if (ops[i].powerOnCommand == command) return &ops[i];
  }
  return nullptr;
}

inline const char* mode_page_path(SAMOVAR_MODE mode) {
  const ModeOps* ops = mode_ops_by_mode(mode);
  return ops != nullptr ? ops->pagePath : "/index.htm";
}

inline SamovarCommands mode_power_on_command(SAMOVAR_MODE mode) {
  const ModeOps* ops = mode_ops_by_mode(mode);
  return ops != nullptr ? ops->powerOnCommand : SAMOVAR_POWER;
}

inline SamovarCommands mode_start_command(SAMOVAR_MODE mode) {
  const ModeOps* ops = mode_ops_by_mode(mode);
  return ops != nullptr ? ops->startCommand : SAMOVAR_START;
}

inline bool mode_is_program_owner(SAMOVAR_MODE mode) {
  return mode == SAMOVAR_RECTIFICATION_MODE ||
         mode == SAMOVAR_DISTILLATION_MODE ||
         mode == SAMOVAR_BEER_MODE ||
         mode == SAMOVAR_BK_MODE ||
         mode == SAMOVAR_NBK_MODE;
}

inline bool program_update_session_active() {
  if (PowerOn && mode_is_program_owner(Samovar_Mode)) return true;
  if (SamovarStatusInt > 0 && SamovarStatusInt < 1000) return true;
  if (SamovarStatusInt == 1000 || SamovarStatusInt == 2000 ||
      SamovarStatusInt == 3000 || SamovarStatusInt == 4000) return true;
  if (startval > 0 && startval < 1000) return true;
  if (startval == 1000 || (startval >= 2000 && startval < 3000) ||
      startval == 3000 || (startval >= 4000 && startval < 5000)) return true;
  return false;
}

inline bool mode_apply_power_on_command(SamovarCommands command) {
  if (command == SAMOVAR_START) {
    Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
    change_samovar_mode();
    menu_samovar_start();
    return true;
  }

  const ModeOps* ops = mode_ops_by_power_on_command(command);
  if (ops == nullptr || ops->activeStatus <= 0) return false;

  Samovar_Mode = ops->mode;
  change_samovar_mode();
  SamovarStatusInt = ops->activeStatus;
  startval = ops->activeStatus;
  return true;
}

inline bool mode_finish_by_status(int16_t status) {
  const ModeOps* ops = mode_ops_by_status(status);
  if (ops == nullptr || ops->finish == nullptr) return false;
  ops->finish();
  return true;
}

inline bool mode_status_by_status(int16_t status, String& text) {
  const ModeOps* ops = mode_ops_by_status(status);
  if (ops == nullptr || ops->status == nullptr) return false;
  text = ops->status();
  return true;
}

inline void mode_dispatch_alarm() {
  const ModeOps* ops = mode_ops_by_mode(Samovar_Mode);
  if (ops != nullptr && ops->alarm != nullptr) ops->alarm();
}

inline void mode_dispatch_loop() {
  const ModeOps* ops = mode_ops_by_status(SamovarStatusInt);
  if (ops == nullptr) return;

  switch (ops->mode) {
    case SAMOVAR_RECTIFICATION_MODE:
      withdrawal();
      break;
    case SAMOVAR_DISTILLATION_MODE:
      distiller_proc();
      break;
    case SAMOVAR_BK_MODE:
      bk_proc();
      break;
    case SAMOVAR_NBK_MODE:
      nbk_proc();
      break;
    case SAMOVAR_BEER_MODE:
      if (startval == 2000) beer_proc();
      break;
    case SAMOVAR_SUVID_MODE:
    case SAMOVAR_LUA_MODE:
    default:
      break;
  }
}
