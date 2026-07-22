#pragma once

#include "Samovar.h"
#include "runtime_helpers.h"

using ModeVoidFn = void (*)();
using ModeStatusFn = String (*)();

struct ModeOps {
  SAMOVAR_MODE mode;
  int16_t activeStatus;
  int16_t startvalRangeLow;    // включительно
  int16_t startvalRangeHigh;   // исключительно
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
  beer_check_cooling_limits();
  water_pulse_count_set(100);  // в пиве нет постоянного протока — авария глушится намеренно
}

inline const ModeOps* mode_registry() {
  static const ModeOps ops[] = {
    {SAMOVAR_RECTIFICATION_MODE, SAMOVAR_STATUS_IDLE, 1, SAMOVAR_STATUS_DISTILLATION, "/index.htm", SAMOVAR_POWER, SAMOVAR_START, check_alarm, nullptr, nullptr},
    {SAMOVAR_DISTILLATION_MODE, SAMOVAR_STATUS_DISTILLATION, SAMOVAR_STATUS_DISTILLATION, SAMOVAR_STATUS_DISTILLATION + 1, "/distiller.htm", SAMOVAR_DISTILLATION, SAMOVAR_DIST_NEXT, check_alarm_distiller, distiller_finish, get_distiller_status_text},
    {SAMOVAR_BEER_MODE, SAMOVAR_STATUS_BEER, SAMOVAR_STATUS_BEER, SAMOVAR_STATUS_BEER + 1000, "/beer.htm", SAMOVAR_BEER, SAMOVAR_BEER_NEXT, mode_alarm_beer, beer_finish, get_beer_status_text},
    {SAMOVAR_BK_MODE, SAMOVAR_STATUS_BK, SAMOVAR_STATUS_BK, SAMOVAR_STATUS_BK + 1, "/bk.htm", SAMOVAR_BK, SAMOVAR_START, check_alarm_bk, bk_finish, get_bk_status_text},
    {SAMOVAR_NBK_MODE, SAMOVAR_STATUS_NBK, SAMOVAR_STATUS_NBK, SAMOVAR_STATUS_NBK + 1000, "/nbk.htm", SAMOVAR_NBK, SAMOVAR_NBK_NEXT, mode_alarm_nbk, nbk_finish, get_nbk_status_text},
    {SAMOVAR_SUVID_MODE, SAMOVAR_STATUS_IDLE, 0, 0, "/index.htm", SAMOVAR_POWER, SAMOVAR_START, check_alarm_suvid, nullptr, nullptr},
    {SAMOVAR_LUA_MODE, SAMOVAR_STATUS_IDLE, 0, 0, "/index.htm", SAMOVAR_POWER, SAMOVAR_START, nullptr, nullptr, nullptr},
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
  if (status <= SAMOVAR_STATUS_IDLE) return nullptr;
  if (status > SAMOVAR_STATUS_IDLE && status < SAMOVAR_STATUS_DISTILLATION) return mode_ops_by_mode(SAMOVAR_RECTIFICATION_MODE);
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
         mode == SAMOVAR_NBK_MODE ||
         mode == SAMOVAR_SUVID_MODE ||
         mode == SAMOVAR_LUA_MODE;
}

inline bool mode_status_session_active(int16_t status) {
  if (status > SAMOVAR_STATUS_IDLE && status < SAMOVAR_STATUS_DISTILLATION) return true;  // ректификация — спец-диапазон
  const ModeOps* ops = mode_registry();
  for (size_t i = 0; i < mode_registry_count(); i++) {
    if (ops[i].activeStatus > SAMOVAR_STATUS_IDLE && ops[i].activeStatus == status) return true;
  }
  return false;
}

inline bool mode_startval_session_active(int16_t value) {
  const ModeOps* ops = mode_registry();
  for (size_t i = 0; i < mode_registry_count(); i++) {
    if (ops[i].startvalRangeHigh > ops[i].startvalRangeLow &&
        value >= ops[i].startvalRangeLow && value < ops[i].startvalRangeHigh) return true;
  }
  return false;
}

inline bool program_update_session_active() {
  if (PowerOn && mode_is_program_owner(Samovar_Mode)) return true;
  if (mode_status_session_active(SamovarStatusInt)) return true;
  if (mode_startval_session_active(startval)) return true;
  return false;
}

inline bool mode_runtime_owner_idle() {
  return SamovarStatusInt == SAMOVAR_STATUS_IDLE && startval == SAMOVAR_STARTVAL_IDLE && ProgramNum == 0;
}

inline bool mode_apply_power_on_command(SamovarCommands command) {
  if (mode_switch_in_progress()) {
    SendMsg("Команда запуска отклонена: смена режима ещё не завершена", WARNING_MSG);
    return false;
  }
  if (command == SAMOVAR_START) {
    Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
    change_samovar_mode();
    menu_samovar_start();
    return true;
  }

  const ModeOps* ops = mode_ops_by_power_on_command(command);
  if (ops == nullptr || ops->activeStatus <= SAMOVAR_STATUS_IDLE) return false;

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
  // [PKG-B п.9] Инвариант: при смене режима надзор аварий пропускается НАМЕРЕННО — реле
  // выключены синхронно ДО входа в mode switch (барьер рубит их в emergencyStopMux).
  // Порядок не менять: синхронное снятие реле обязано предшествовать этому skip'у.
  if (mode_switch_in_progress()) return;
  const ModeOps* ops = mode_ops_by_mode(Samovar_Mode);
  if (ops != nullptr && ops->alarm != nullptr) ops->alarm();
}

inline void mode_dispatch_loop() {
  if (mode_switch_in_progress()) return;
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
      if (startval == SAMOVAR_STARTVAL_BEER_START) beer_proc();
      else if (startval > SAMOVAR_STARTVAL_BEER_START) beer_stage_tick();
      break;
    case SAMOVAR_SUVID_MODE:
    case SAMOVAR_LUA_MODE:
    default:
      break;
  }
}
