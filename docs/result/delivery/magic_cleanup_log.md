# Step 2.5 magic number cleanup audit

## Scope

- Просканировано `*.h/*.cpp/*.ino`: `1015` файлов из git-дерева.
- Проверены только state-semantics переменные: `SamovarStatusInt`, `sam_command_sync`, `Samovar_Mode`, `Samovar_CR_Mode`, `startval`.
- Literal-числа допустимы только вне state semantics: в аппаратных лимитах, низкоуровневых протоколах и compile-time конфиге.
- Остаточная transition semantics должна выражаться либо именованными токенами, либо helper-предикатами из `src/core/state/status_codes.h` и `src/core/state/mode_codes.h`.

## Raw numeric literal matches for SamovarStatusInt

_No raw numeric literal matches found._

## Raw numeric literal matches for sam_command_sync

_No raw numeric literal matches found._

## Raw numeric literal matches for Samovar_Mode

_No raw numeric literal matches found._

## Raw numeric literal matches for Samovar_CR_Mode

_No raw numeric literal matches found._

## Raw numeric literal matches for startval

_No raw numeric literal matches found._

## Named semantic helper call sites

Ниже перечислены helper-предикаты, которыми заменены последние неявные state-range semantics в критической логике.

## samovar_status_is_rectification

```text
app/loop_dispatch.h:104: if (samovar_status_is_rectification(SamovarStatusInt)) {
app/orchestration.h:500: } else if (startval == SAMOVAR_STARTVAL_RECT_IDLE && samovar_status_is_rectification(SamovarStatusInt)) {
app/orchestration.h:502: } else if (startval != SAMOVAR_STARTVAL_RECT_IDLE && !program_Pause && samovar_status_is_rectification(SamovarStatusInt)) {
app/orchestration.h:504: } else if (startval != SAMOVAR_STARTVAL_RECT_IDLE && program_Pause && samovar_status_is_rectification(SamovarStatusInt)) {
src/core/state/status_codes.h:20: inline bool samovar_status_is_rectification(int16_t status) {
```

## samovar_status_allows_rectification_withdrawal

```text
io/actuators.h:47: if (!samovar_status_allows_rectification_withdrawal(SamovarStatusInt)) return;
modes/rect/rect_runtime.h:101: if (!samovar_status_allows_rectification_withdrawal(SamovarStatusInt)) return;
src/core/state/status_codes.h:24: inline bool samovar_status_allows_rectification_withdrawal(int16_t status) {
```

## samovar_status_has_rectification_program_progress

```text
app/status_text.h:130: if (samovar_status_has_rectification_program_progress(SamovarStatusInt) ||
src/core/state/status_codes.h:30: inline bool samovar_status_has_rectification_program_progress(int16_t status) {
ui/web/ajax_snapshot.h:155: (samovar_status_has_rectification_program_progress(SamovarStatusInt) ||
```

## startval_is_rect_program_state

```text
Blynk.ino:44: if (startval_is_rect_program_state(startval))
src/core/state/mode_codes.h:29: inline bool startval_is_rect_program_state(int16_t value) {
```

## startval_is_active_non_calibration

```text
src/core/state/mode_codes.h:33: inline bool startval_is_active_non_calibration(int16_t value) {
ui/menu/actions.h:199: if (startval_is_active_non_calibration(startval)) {
```

## startval_is_beer_program_started

```text
modes/beer/beer_runtime.h:190: if (!startval_is_beer_program_started(startval)) return;
src/core/state/mode_codes.h:37: inline bool startval_is_beer_program_started(int16_t value) {
```
