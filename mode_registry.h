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
  ModeVoidFn buttonPressAction;  // короткое нажатие при PowerOn == true; nullptr — режим кнопку не обслуживает
  const char* startBusyName;     // имя режима для сообщения об занятой очереди команд
  ModeVoidFn tick;                // тик loop() пока режим активен; nullptr — режим не тикает через реестр
  ModeVoidFn stopProcess;         // принудительная остановка активного процесса (смена режима/сброс); nullptr — общий сброс статуса/питания
  bool buildAvailable;            // режим скомпилирован в этой сборке — см. SAMOVAR_*_BUILD_AVAILABLE (samovar_api.h)
  const char* unavailableReason;  // причина отказа для пользователя, если !buildAvailable; иначе не читается
};

inline void mode_alarm_nbk() {
  if (!check_nbk_critical_alarms()) check_alarm_nbk();
}

inline void mode_alarm_beer() {
  beer_check_cooling_limits();
  mode_request_water_flow_emergency_if_needed();
}

inline void mode_button_press_beer() {
  run_beer_program(ProgramNum + 1);
}

// [WP17 п.40] Раньше выбор функции тика цикла был отдельным switch(Samovar_Mode)
// в mode_dispatch_loop() - для BEER там же жила эта же ветка по startval. Вынесено
// сюда как ещё один per-mode колбэк реестра (по образцу mode_alarm_beer выше).
inline void mode_tick_beer() {
  if (startval == SAMOVAR_STARTVAL_BEER_START) beer_proc();
  else if (startval > SAMOVAR_STARTVAL_BEER_START) beer_stage_tick();
}

// [WP17 п.40] Раньше — ветка SAMOVAR_RECTIFICATION_MODE в switch(Samovar_Mode)
// внутри stop_active_process_for_mode() (WebServer.ino). У ректификации нет
// .finish в этой таблице (см. rect-строку ниже) — там это осознанно nullptr,
// т.к. finish используется отдельно для команды SAMOVAR_POWER; здесь же при
// остановке процесса нужен именно run_program(PROGRAM_END).
inline void mode_stop_process_rectification() {
  run_program(PROGRAM_END);
}

// [WP17 п.40] Частичная защита от «забыли добавить режим»: mode_registry_table()
// ниже — единственное место, перечисляющее все SAMOVAR_MODE (enum в Samovar.h,
// который этому агенту трогать нельзя). Если состав/порядок enum изменится так,
// что SAMOVAR_LUA_MODE перестанет быть значением 6 (новый режим вставлен перед
// ним, режим удалён/переставлен) — сборка упадёт здесь. ВНИМАНИЕ: если новый
// режим просто ДОПИШУТ В КОНЕЦ enum (после LUA_MODE), этот static_assert не
// сработает — SAMOVAR_LUA_MODE как было 6, так и останется. Без counter-
// сентинела в самом enum (недоступно — см. ограничения задачи) поймать дозапись
// в хвост на этапе сборки нечем; при добавлении нового режима строку в таблицу
// ниже нужно добавить руками.
static_assert(SAMOVAR_LUA_MODE == 6,
    "SAMOVAR_MODE (Samovar.h) изменил состав/порядок — сверьте и обновите mode_registry_table() в mode_registry.h");

// Единственное место, где объявлена таблица режимов и её размер. mode_registry()
// и mode_registry_count() читают её только отсюда — количество строк больше не
// может разойтись с фактическим размером массива.
inline const ModeOps* mode_registry_table(size_t& count) {
  static const ModeOps ops[] = {
    {SAMOVAR_RECTIFICATION_MODE, SAMOVAR_STATUS_IDLE, 1, SAMOVAR_STATUS_DISTILLATION, "/index.htm", SAMOVAR_POWER, SAMOVAR_START, check_alarm, nullptr, nullptr, nullptr, nullptr, withdrawal, mode_stop_process_rectification, true, nullptr},
    {SAMOVAR_DISTILLATION_MODE, SAMOVAR_STATUS_DISTILLATION, SAMOVAR_STATUS_DISTILLATION, SAMOVAR_STATUS_DISTILLATION + 1, "/distiller.htm", SAMOVAR_DISTILLATION, SAMOVAR_DIST_NEXT, check_alarm_distiller, distiller_finish, get_distiller_status_text, distiller_finish, "дистилляции", distiller_proc, distiller_finish, true, nullptr},
    {SAMOVAR_BEER_MODE, SAMOVAR_STATUS_BEER, SAMOVAR_STATUS_BEER, SAMOVAR_STATUS_BEER + 1000, "/beer.htm", SAMOVAR_BEER, SAMOVAR_BEER_NEXT, mode_alarm_beer, beer_finish, get_beer_status_text, mode_button_press_beer, "пива", mode_tick_beer, beer_finish, true, nullptr},
    // [P7 п.2] startCommand=SAMOVAR_NONE: у БК нет своего "следующая программа"/старт-действия
    // через SAMOVAR_START (это команда ректификации) - веб-экшен action=start для БК не должен
    // молча дёргать чужой (ректификационный) старт. SUVID/LUA намеренно НЕ трогаем (асимметрия).
    {SAMOVAR_BK_MODE, SAMOVAR_STATUS_BK, SAMOVAR_STATUS_BK, SAMOVAR_STATUS_BK + 1, "/bk.htm", SAMOVAR_BK, SAMOVAR_NONE, check_alarm_bk, bk_finish, get_bk_status_text, bk_finish, "БК", bk_proc, bk_finish, true, nullptr},
    // [WP17 п.45] НБК управляет мощностью через регулятор (run_nbk_program в nbk.h
    // отказывает без SAMOVAR_USE_POWER) - buildAvailable завязан на тот же макрос,
    // которым сама nbk.h условно компилирует код регулятора.
    {SAMOVAR_NBK_MODE, SAMOVAR_STATUS_NBK, SAMOVAR_STATUS_NBK, SAMOVAR_STATUS_NBK + 1000, "/nbk.htm", SAMOVAR_NBK, SAMOVAR_NBK_NEXT, mode_alarm_nbk, nbk_finish, get_nbk_status_text, nbk_finish, "НБК", nbk_proc, nbk_finish, SAMOVAR_NBK_BUILD_AVAILABLE, "Недоступно в этой сборке прошивки: нет регулятора мощности"},
    {SAMOVAR_SUVID_MODE, SAMOVAR_STATUS_IDLE, 0, 0, "/index.htm", SAMOVAR_POWER, SAMOVAR_START, check_alarm_suvid, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, true, nullptr},
    {SAMOVAR_LUA_MODE, SAMOVAR_STATUS_IDLE, 0, 0, "/index.htm", SAMOVAR_POWER, SAMOVAR_START, SAMOVAR_LUA_ALARM_FN, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, SAMOVAR_LUA_BUILD_AVAILABLE, "Недоступно в этой сборке прошивки: не включён Lua"},
  };
  count = sizeof(ops) / sizeof(ops[0]);
  return ops;
}

inline const ModeOps* mode_registry() {
  size_t count = 0;
  return mode_registry_table(count);
}

inline size_t mode_registry_count() {
  size_t count = 0;
  mode_registry_table(count);
  return count;
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

// [WP17 п.45] Единая точка правды "доступен ли режим в этой сборке прошивки" —
// см. buildAvailable в ModeOps и SAMOVAR_*_BUILD_AVAILABLE (samovar_api.h).
// Используется и при сохранении настроек (WebServer.ino handleSave), и при
// формировании списка режимов для веб-интерфейса (WebServer.ino keyProcessor),
// чтобы недоступный режим не предлагался и не сохранялся.
inline bool mode_available_in_build(SAMOVAR_MODE mode) {
  const ModeOps* ops = mode_ops_by_mode(mode);
  return ops != nullptr && ops->buildAvailable;
}

inline const char* mode_unavailable_reason(SAMOVAR_MODE mode) {
  const ModeOps* ops = mode_ops_by_mode(mode);
  if (ops == nullptr || ops->buildAvailable) return nullptr;
  return ops->unavailableReason;
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
  if (PowerOn) return true;
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
    // [P7 п.1] SAMOVAR_START не должен молча перезапускать чужую активную сессию
    // (другой режим уже работает) - вместо форсированного переключения режима отказываем.
    if (Samovar_Mode != SAMOVAR_RECTIFICATION_MODE && program_update_session_active()) {
      SendMsg("Команда запуска недоступна в текущем режиме", WARNING_MSG);
      return false;
    }
    Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
    change_samovar_mode();
    menu_samovar_start();
    return true;
  }

  const ModeOps* ops = mode_ops_by_power_on_command(command);
  if (ops == nullptr || ops->activeStatus <= SAMOVAR_STATUS_IDLE) return false;

  // [P7 п.1] Аналогичный guard для табличных режимов: чужая активная сессия не даёт стартовать.
  if (ops->mode != Samovar_Mode && program_update_session_active()) {
    SendMsg("Команда запуска недоступна в текущем режиме", WARNING_MSG);
    return false;
  }

  // [P7 п.1/3a] Явный пользовательский запрос новой сессии - взводим флаг для целевого
  // activeStatus, который mode_begin_heating_session (mode_common.h) потребует перед
  // фактическим стартом нагрева. Взвод для конкретного статуса не даёт другому режиму
  // (например, БК) ошибочно потребить чужой взвод (см. [P7 F1]).
  const bool isNewSession = ops->mode != Samovar_Mode || SamovarStatusInt != ops->activeStatus;
  if (isNewSession) mode_request_heating_start(ops->activeStatus);

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

inline void mode_dispatch_button_press() {
  const ModeOps* ops = mode_ops_by_mode(Samovar_Mode);
  if (ops == nullptr || ops->buttonPressAction == nullptr) return;
  if (!PowerOn) {
    if (!queue_samovar_command(ops->powerOnCommand)) {
      SendMsg(String("Очередь команд занята: старт ") + ops->startBusyName + " не поставлен", WARNING_MSG);
    }
  } else {
    ops->buttonPressAction();
  }
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

// [WP17 п.40] Раньше здесь был switch(ops->mode), заново перечислявший режимы
// (SUVID/LUA falling через default в no-op). Тик каждого режима теперь читается
// из реестра (см. .tick в ModeOps и mode_registry_table выше) - для SUVID/LUA
// там nullptr, поведение не меняется.
inline void mode_dispatch_loop() {
  if (mode_switch_in_progress()) return;
  const ModeOps* ops = mode_ops_by_status(SamovarStatusInt);
  if (ops == nullptr || ops->tick == nullptr) return;
  ops->tick();
}
