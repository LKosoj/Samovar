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
  // [T40 А3] Граница диапазона SamovarStatusInt, принадлежащего режиму - читается
  // mode_status_belongs()/mode_ops_by_status()/mode_status_session_active() вместо
  // сравнений с константами (SAMOVAR_STATUS_DISTILLATION и т.п.) по месту. НЕ путать
  // с startvalRange* выше: для БЕЕР/НБК startval внутри сессии пробегает диапазон
  // (под-стадии), а SamovarStatusInt всё это время держит одно и то же значение
  // (activeStatus) - поэтому границы разные и совпадают только у ректификации.
  int16_t statusRangeLow;      // включительно
  int16_t statusRangeHigh;     // исключительно
  const char* pagePath;
  SamovarCommands powerOnCommand;
  SamovarCommands startCommand;
  ModeVoidFn alarm;
  ModeVoidFn finish;
  ModeStatusFn status;
  ModeVoidFn buttonPressAction;  // короткое нажатие при PowerOn == true; nullptr — режим кнопку не обслуживает
  ModeVoidFn buttonHoldAction;   // [П12] удержание при PowerOn == true; nullptr — режим удержание не обслуживает
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
  beer_check_wort_overheat_limit();
  mode_request_water_flow_emergency_if_needed();
}

inline void mode_button_press_beer() {
  run_beer_program(ProgramNum + 1);
}

// [П12] Короткое нажатие в дистилляции переходит к следующей строке программы -
// тот же путь, что веб-кнопка "Следующая программа" (SAMOVAR_DIST_NEXT, Samovar.ino,
// case SAMOVAR_DIST_NEXT). Завершение процесса перенесено на удержание
// (buttonHoldAction = distiller_finish в таблице ниже), по аналогии с тем, как у
// пива короткое нажатие двигает программу, а не завершает её.
inline void mode_button_press_dist() {
  run_dist_program(ProgramNum + 1);
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
    {SAMOVAR_RECTIFICATION_MODE, SAMOVAR_STATUS_IDLE, 1, SAMOVAR_STATUS_DISTILLATION, 1, SAMOVAR_STATUS_DISTILLATION, "/index.htm", SAMOVAR_POWER, SAMOVAR_START, check_alarm, nullptr, nullptr, nullptr, nullptr, nullptr, withdrawal, mode_stop_process_rectification, true, nullptr},
    {SAMOVAR_DISTILLATION_MODE, SAMOVAR_STATUS_DISTILLATION, SAMOVAR_STATUS_DISTILLATION, SAMOVAR_STATUS_DISTILLATION + 1, SAMOVAR_STATUS_DISTILLATION, SAMOVAR_STATUS_DISTILLATION + 1, "/distiller.htm", SAMOVAR_DISTILLATION, SAMOVAR_DIST_NEXT, check_alarm_distiller, distiller_finish, get_distiller_status_text, mode_button_press_dist, distiller_finish, "дистилляции", distiller_proc, distiller_finish, true, nullptr},
    // statusRange у ПИВА [BEER, BEER+1) - ЭТО значение SamovarStatusInt всю сессию,
    // а startvalRange [BEER, BEER+1000) - под-стадии внутри сессии (см. комментарий у полей).
    {SAMOVAR_BEER_MODE, SAMOVAR_STATUS_BEER, SAMOVAR_STATUS_BEER, SAMOVAR_STATUS_BEER + 1000, SAMOVAR_STATUS_BEER, SAMOVAR_STATUS_BEER + 1, "/beer.htm", SAMOVAR_BEER, SAMOVAR_BEER_NEXT, mode_alarm_beer, beer_finish, get_beer_status_text, mode_button_press_beer, nullptr, "пива", mode_tick_beer, beer_finish, true, nullptr},
    // [P7 п.2] startCommand=SAMOVAR_NONE: у БК нет своего "следующая программа"/старт-действия
    // через SAMOVAR_START (это команда ректификации) - веб-экшен action=start для БК не должен
    // молча дёргать чужой (ректификационный) старт. SUVID/LUA намеренно НЕ трогаем (асимметрия).
    {SAMOVAR_BK_MODE, SAMOVAR_STATUS_BK, SAMOVAR_STATUS_BK, SAMOVAR_STATUS_BK + 1, SAMOVAR_STATUS_BK, SAMOVAR_STATUS_BK + 1, "/bk.htm", SAMOVAR_BK, SAMOVAR_NONE, check_alarm_bk, bk_finish, get_bk_status_text, bk_finish, nullptr, "БК", bk_proc, bk_finish, true, nullptr},
    // [WP17 п.45] НБК управляет мощностью через регулятор (run_nbk_program в nbk.h
    // отказывает без SAMOVAR_USE_POWER) - buildAvailable завязан на тот же макрос,
    // которым сама nbk.h условно компилирует код регулятора. statusRange [NBK, NBK+1) -
    // как у ПИВА, SamovarStatusInt не меняется всю сессию, в отличие от startvalRange.
    {SAMOVAR_NBK_MODE, SAMOVAR_STATUS_NBK, SAMOVAR_STATUS_NBK, SAMOVAR_STATUS_NBK + 1000, SAMOVAR_STATUS_NBK, SAMOVAR_STATUS_NBK + 1, "/nbk.htm", SAMOVAR_NBK, SAMOVAR_NBK_NEXT, mode_alarm_nbk, nbk_finish, get_nbk_status_text, nbk_finish, nullptr, "НБК", nbk_proc, nbk_finish, SAMOVAR_NBK_BUILD_AVAILABLE, "Недоступно в этой сборке прошивки: нет регулятора мощности"},
    // statusRangeLow==statusRangeHigh==0: SUVID/LUA не держат отдельного значения
    // SamovarStatusInt (остаётся IDLE всю сессию) - диапазон пуст, ни один статус ему
    // не принадлежит, mode_dispatch_loop() их не тикает (см. suvid_tick()/lua-команды).
    {SAMOVAR_SUVID_MODE, SAMOVAR_STATUS_IDLE, 0, 0, 0, 0, "/index.htm", SAMOVAR_POWER, SAMOVAR_START, check_alarm_suvid, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, true, nullptr},
    {SAMOVAR_LUA_MODE, SAMOVAR_STATUS_IDLE, 0, 0, 0, 0, "/index.htm", SAMOVAR_POWER, SAMOVAR_START, SAMOVAR_LUA_ALARM_FN, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, SAMOVAR_LUA_BUILD_AVAILABLE, "Недоступно в этой сборке прошивки: не включён Lua"},
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

// [T40 А3] Единственная точка выбора режима для диспетчеризации: всегда по
// живой Samovar_Mode, а не по SamovarStatusInt (см. mode_dispatch_alarm/
// mode_dispatch_loop ниже - оба читают только эту функцию). Раньше alarm и loop
// расходились: alarm уже брал mode_ops_by_mode(Samovar_Mode), а loop искал
// строку по статусу (mode_ops_by_status) - если статус отставал от смены
// режима, они молча работали по разным строкам таблицы.
inline const ModeOps* mode_ops_current() {
  return mode_ops_by_mode(Samovar_Mode);
}

// [T40 А3] Принадлежит ли статус активному диапазону ЭТОГО режима. Границы -
// поля таблицы (statusRangeLow/High), а не сравнение с константами по месту
// (было: `status < SAMOVAR_STATUS_DISTILLATION` зашито здесь и продублировано в
// mode_status_session_active() ниже).
inline bool mode_status_belongs(const ModeOps* ops, int16_t status) {
  return ops != nullptr && status >= ops->statusRangeLow && status < ops->statusRangeHigh;
}

inline const ModeOps* mode_ops_by_status(int16_t status) {
  const ModeOps* ops = mode_registry();
  for (size_t i = 0; i < mode_registry_count(); i++) {
    if (mode_status_belongs(&ops[i], status)) return &ops[i];
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

// [T40 А3] Была вторая копия той же зашитой ректификационной проверки
// (`status < SAMOVAR_STATUS_DISTILLATION`) - теперь читает те же statusRange*
// поля через mode_status_belongs(), что и mode_ops_by_status() выше.
inline bool mode_status_session_active(int16_t status) {
  const ModeOps* ops = mode_registry();
  for (size_t i = 0; i < mode_registry_count(); i++) {
    if (mode_status_belongs(&ops[i], status)) return true;
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

// [П12] Удержание кнопки: если нагрев включён и режим обслуживает удержание -
// выполняется собственное buttonHoldAction режима. Во всех остальных случаях
// (нагрев выключен, либо режим не завёл своё удержание) делегируем
// press-диспетчеру: раньше isPress() срабатывал при ЛЮБОМ касании кнопки
// независимо от длительности, включая нагрев при !PowerOn и вызывая
// buttonPressAction (bk_finish/nbk_finish/mode_button_press_beer) при PowerOn.
// GyverButton гасит oneClick_f при пересечении порога удержания, поэтому без
// делегирования долгое нажатие в режимах без buttonHoldAction (БК/НБК/Пиво)
// молча "проглатывалось" вместо остановки нагрева.
inline void mode_dispatch_button_hold() {
  const ModeOps* ops = mode_ops_by_mode(Samovar_Mode);
  if (PowerOn && ops != nullptr && ops->buttonHoldAction != nullptr) {
    ops->buttonHoldAction();
    return;
  }
  mode_dispatch_button_press();
}

inline bool mode_status_by_status(int16_t status, String& text) {
  const ModeOps* ops = mode_ops_by_status(status);
  if (ops == nullptr || ops->status == nullptr) return false;
  text = ops->status();
  return true;
}

inline void mode_dispatch_alarm() {
  // Барьер смены режима здесь НЕ проверяется - и это осознанно. Барьер поднимается
  // в queue_profile_operation() (WebServer.ino) раньше любого выключения реле, а
  // дедлайн смены режима - до 30 секунд (safety_deadline_after(millis(), 30000) в
  // switch_samovar_mode()). Пропуск надзора на всё это окно оставлял бы аппарат без
  // аварийного контроля. Аварийный надзор обязан идти ВСЕГДА, вне
  // зависимости от смены режима; барьером можно глушить только режимный тик
  // (см. mode_dispatch_loop() ниже) - не аварийную проверку.
  const ModeOps* ops = mode_ops_current();
  if (ops != nullptr && ops->alarm != nullptr) ops->alarm();
}

// [WP17 п.40] Раньше здесь был switch(ops->mode), заново перечислявший режимы
// (SUVID/LUA falling через default в no-op). Тик каждого режима теперь читается
// из реестра (см. .tick в ModeOps и mode_registry_table выше) - для SUVID/LUA
// там nullptr, поведение не меняется.
// [T40 А3] Раньше строка бралась по SamovarStatusInt (mode_ops_by_status) - второй,
// независимый от mode_dispatch_alarm() источник выбора режима: если Samovar_Mode уже
// сменили, а SamovarStatusInt ещё не подтянулся (или разошёлся из-за бага), alarm и
// loop молча работали по РАЗНЫМ строкам реестра. Теперь источник один -
// mode_ops_current() (по Samovar_Mode, как и в alarm); статус лишь проверяется на
// принадлежность этому режиму (mode_status_belongs). Если не принадлежит, но при этом
// статус активен для КАКОГО-ТО режима (mode_status_session_active) - это и есть
// рассогласование, предупреждаем один раз (не на каждом такте - иначе WARNING_MSG в
// цикле забьёт очередь и вытеснит настоящие аварии); приём "один раз, сброс когда
// разрешилось" - тот же, что noDZ_message_sent (nbk.h) / pressure_alarm_sent
// (Samovar.ino, triggerSysTicker). Обычный простой (SamovarStatusInt == IDLE) - не
// рассогласование, предупреждение не шлём.
inline void mode_dispatch_loop() {
  if (mode_switch_in_progress()) return;
  const ModeOps* ops = mode_ops_current();
  static bool dispatchMismatchWarned = false;
  if (mode_status_belongs(ops, SamovarStatusInt)) {
    dispatchMismatchWarned = false;
    if (ops->tick != nullptr) ops->tick();
    return;
  }
  if (mode_status_session_active(SamovarStatusInt)) {
    if (!dispatchMismatchWarned) {
      SendMsg("Статус не принадлежит текущему режиму - тик пропущен, проверьте синхронизацию режима", WARNING_MSG);
      dispatchMismatchWarned = true;
    }
  }
}
