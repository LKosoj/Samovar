# Step 2 Closure Report

## 1. Status

- Date: `2026-03-16`
- Scope: `Шаг 2. Нормализация внутреннего state-слоя`
- Overall result: `BLOCKED`
- Closure decision: `REQ-1..REQ-7 confirmed`, `REQ-8 blocked`

Step 2 is **not fully closed** because the final gate in
[`docs/refactoring/02_state_normalization_plan_ru.md`](/srv/git_projects/Samovar/docs/refactoring/02_state_normalization_plan_ru.md)
requires a manual smoke on real hardware:

- sequential switching of all modes on hardware;
- start/stop after mode changes;
- web/menu runtime validation on the running device;
- no stuck `pause/power/program state` flags.

That gate is currently blocked by the absence of a reachable Samovar/ESP32 hardware endpoint and a reachable web UI session. The detailed blocker record is documented in
[`manual_smoke_results.md`](/srv/git_projects/Samovar/docs/result/delivery/manual_smoke_results.md).

## 2. Source Of Truth For REQ-1..REQ-8

The repository does not contain a separate literal glossary named `REQ-1..REQ-8`.
For this closure report, the requirement set is reconstructed from:

- section `6. Декомпозиция на подзадачи` in
  [`docs/refactoring/02_state_normalization_plan_ru.md`](/srv/git_projects/Samovar/docs/refactoring/02_state_normalization_plan_ru.md)
- section `8. Рекомендуемые тестовые пакеты шага`
- section `10. Gate завершения шага 2`

This report therefore uses the following explicit mapping:

| Req | Invariant / requirement | Source |
| --- | --- | --- |
| `REQ-1` | numeric state/status/command/mode contracts are inventoried and fixed | step 2.1 + section 7 |
| `REQ-2` | status/command semantics use named values, not raw literals | step 2.2 |
| `REQ-3` | mode/startval semantics use named values, not raw literals | step 2.2 + step 2.5 |
| `REQ-4` | mode ownership and runtime routing are explicit and readable | step 2.3 |
| `REQ-5` | reset pipeline side effects are explicit and invariant-checked | step 2.4 |
| `REQ-6` | web/menu/Lua integration respects the normalized state model | step 2.3 + section 8 |
| `REQ-7` | regression suite and build matrix confirm no regressions on required env | step 2.6a + step 2.6b |
| `REQ-8` | final manual smoke on real hardware confirms no stuck states in practice | section 8 + section 10 |

## 3. Requirement Matrix

| Req | Status | Evidence |
| --- | --- | --- |
| `REQ-1` | `confirmed` | [`state_codes_inventory.md`](/srv/git_projects/Samovar/docs/result/delivery/state_codes_inventory.md), [`state_inventory_grep_log.md`](/srv/git_projects/Samovar/docs/result/delivery/state_inventory_grep_log.md), `python3 tools/tests/test_state_contracts_baseline.py`, `python3 -m unittest tests.test_state_code_inventory_baseline` |
| `REQ-2` | `confirmed` | [`src/core/state/status_codes.h`](/srv/git_projects/Samovar/src/core/state/status_codes.h), [`status_codes_grep_log.md`](/srv/git_projects/Samovar/docs/result/delivery/status_codes_grep_log.md), [`step2_regression_log.md`](/srv/git_projects/Samovar/docs/result/delivery/step2_regression_log.md) |
| `REQ-3` | `confirmed` | [`src/core/state/mode_codes.h`](/srv/git_projects/Samovar/src/core/state/mode_codes.h), [`mode_codes_grep_log.md`](/srv/git_projects/Samovar/docs/result/delivery/mode_codes_grep_log.md), [`magic_cleanup_log.md`](/srv/git_projects/Samovar/docs/result/delivery/magic_cleanup_log.md), `python3 tools/tests/test_state_contracts_baseline.py` |
| `REQ-4` | `confirmed` | [`src/core/state/mode_ownership.h`](/srv/git_projects/Samovar/src/core/state/mode_ownership.h), [`mode_ownership_mapping.md`](/srv/git_projects/Samovar/docs/result/delivery/mode_ownership_mapping.md), `python3 tools/tests/test_mode_switching_behavior.py`, `python3 -m unittest tests.test_mode_ownership_mapping tests.test_change_samovar_mode_behavior` |
| `REQ-5` | `confirmed` | [`reset_pipeline_spec.md`](/srv/git_projects/Samovar/docs/result/delivery/reset_pipeline_spec.md), `python3 tools/tests/test_reset_pipeline_invariant.py`, [`step2_regression_log.md`](/srv/git_projects/Samovar/docs/result/delivery/step2_regression_log.md) |
| `REQ-6` | `confirmed` | `python3 tools/tests/test_web_mode_integration.py`, `python3 tools/tests/test_menu_mode_integration.py`, `python3 tools/tests/test_lua_mode_selection.py`, [`step2_regression_log.md`](/srv/git_projects/Samovar/docs/result/delivery/step2_regression_log.md) |
| `REQ-7` | `confirmed` | [`regression_run_log.md`](/srv/git_projects/Samovar/docs/result/delivery/regression_run_log.md), [`build_matrix_results.md`](/srv/git_projects/Samovar/docs/result/delivery/build_matrix_results.md), [`step2_builds.md`](/srv/git_projects/Samovar/docs/result/delivery/step2_builds.md) |
| `REQ-8` | `blocked` | [`manual_smoke_results.md`](/srv/git_projects/Samovar/docs/result/delivery/manual_smoke_results.md) explicitly records the missing hardware/web endpoint and marks the manual smoke checks as `not_done` |

## 4. Confirmed Invariants

### REQ-1. Numeric contracts are fixed and documented

Confirmed invariants:

- `SamovarStatusInt`, `sam_command_sync`, `Samovar_Mode`, `Samovar_CR_Mode`, `startval` are inventoried and explained.
- Numeric values remain unchanged from the captured baseline.

Primary evidence:

- [`state_codes_inventory.md`](/srv/git_projects/Samovar/docs/result/delivery/state_codes_inventory.md)
- [`state_inventory_grep_log.md`](/srv/git_projects/Samovar/docs/result/delivery/state_inventory_grep_log.md)
- `python3 tools/tests/test_state_contracts_baseline.py`
- `python3 -m unittest tests.test_state_code_inventory_baseline`

### REQ-2. Status and command semantics no longer depend on raw literals

Confirmed invariants:

- `src/core/state/status_codes.h` is the named source of truth for status and command semantics.
- Transition logic uses named status/command values instead of unexplained numeric comparisons.

Primary evidence:

- [`status_codes.h`](/srv/git_projects/Samovar/src/core/state/status_codes.h)
- [`status_codes_grep_log.md`](/srv/git_projects/Samovar/docs/result/delivery/status_codes_grep_log.md)
- [`step2_regression_log.md`](/srv/git_projects/Samovar/docs/result/delivery/step2_regression_log.md)

### REQ-3. Mode and startval semantics no longer depend on raw literals

Confirmed invariants:

- `src/core/state/mode_codes.h` defines the mode and startval source of truth.
- Critical state logic uses named helpers/constants instead of key magic numbers.

Primary evidence:

- [`mode_codes.h`](/srv/git_projects/Samovar/src/core/state/mode_codes.h)
- [`mode_codes_grep_log.md`](/srv/git_projects/Samovar/docs/result/delivery/mode_codes_grep_log.md)
- [`magic_cleanup_log.md`](/srv/git_projects/Samovar/docs/result/delivery/magic_cleanup_log.md)
- [`state_codes_inventory.md`](/srv/git_projects/Samovar/docs/result/delivery/state_codes_inventory.md)

### REQ-4. Mode ownership and runtime routing are explicit

Confirmed invariants:

- There is a single readable ownership point for runtime/page/program/Lua mapping.
- `change_samovar_mode()` and related helpers use explicit semantics rather than implied mode branches.

Primary evidence:

- [`mode_ownership.h`](/srv/git_projects/Samovar/src/core/state/mode_ownership.h)
- [`mode_ownership_mapping.md`](/srv/git_projects/Samovar/docs/result/delivery/mode_ownership_mapping.md)
- `python3 tools/tests/test_mode_switching_behavior.py`
- `python3 -m unittest tests.test_mode_ownership_mapping tests.test_app_default_programs_extracted tests.test_change_samovar_mode_behavior`

### REQ-5. Reset pipeline is explicit and invariant-tested

Confirmed invariants:

- Reset responsibilities are explicitly documented: runtime reset, power/stepper/I2C cleanup, Lua stop/reload, UI/menu reset, sensor counter reset, route rebinding, profile save/load.
- Sequential mode changes do not leave stale internal reset state in the harnesses.

Primary evidence:

- [`reset_pipeline_spec.md`](/srv/git_projects/Samovar/docs/result/delivery/reset_pipeline_spec.md)
- `python3 tools/tests/test_reset_pipeline_invariant.py`
- [`step2_regression_log.md`](/srv/git_projects/Samovar/docs/result/delivery/step2_regression_log.md)

### REQ-6. Web/menu/Lua integration honors the normalized state model

Confirmed invariants:

- Web setup/save transitions keep explicit save-reset-rebind ordering.
- Menu actions/input use named mode/startval/status semantics.
- Lua runtime mode-selection and Lua-visible mode values stay aligned with the normalized state model.

Primary evidence:

- `python3 tools/tests/test_web_mode_integration.py`
- `python3 tools/tests/test_menu_mode_integration.py`
- `python3 tools/tests/test_lua_mode_selection.py`
- [`step2_regression_log.md`](/srv/git_projects/Samovar/docs/result/delivery/step2_regression_log.md)

### REQ-7. Regression suite and build matrix show no software regression on required env

Confirmed invariants:

- The required regression suite for Step 2 passed with 100% pass rate.
- Required build envs `Samovar`, `lua_expander`, `Samovar_s3` build successfully.

Primary evidence:

- [`regression_run_log.md`](/srv/git_projects/Samovar/docs/result/delivery/regression_run_log.md)
- [`build_matrix_results.md`](/srv/git_projects/Samovar/docs/result/delivery/build_matrix_results.md)
- [`step2_builds.md`](/srv/git_projects/Samovar/docs/result/delivery/step2_builds.md)

### REQ-8. Final manual smoke on hardware

Current status: `blocked`

What is still missing:

- sequential switching through all 7 modes on a real device;
- start/stop after mode change on real runtime;
- live validation that web/menu show the correct runtime;
- live confirmation that `pause/power/program state` flags do not stick.

Primary evidence:

- [`manual_smoke_results.md`](/srv/git_projects/Samovar/docs/result/delivery/manual_smoke_results.md)

Step 2 gate therefore remains **open** until REQ-8 is completed on real hardware.

## 5. Artifact Index

Core Step 2 delivery artifacts:

- [`state_codes_inventory.md`](/srv/git_projects/Samovar/docs/result/delivery/state_codes_inventory.md)
- [`state_inventory_grep_log.md`](/srv/git_projects/Samovar/docs/result/delivery/state_inventory_grep_log.md)
- [`status_codes_grep_log.md`](/srv/git_projects/Samovar/docs/result/delivery/status_codes_grep_log.md)
- [`mode_codes_grep_log.md`](/srv/git_projects/Samovar/docs/result/delivery/mode_codes_grep_log.md)
- [`mode_ownership_mapping.md`](/srv/git_projects/Samovar/docs/result/delivery/mode_ownership_mapping.md)
- [`reset_pipeline_spec.md`](/srv/git_projects/Samovar/docs/result/delivery/reset_pipeline_spec.md)
- [`magic_cleanup_log.md`](/srv/git_projects/Samovar/docs/result/delivery/magic_cleanup_log.md)
- [`step2_regression_log.md`](/srv/git_projects/Samovar/docs/result/delivery/step2_regression_log.md)
- [`regression_run_log.md`](/srv/git_projects/Samovar/docs/result/delivery/regression_run_log.md)
- [`step2_builds.md`](/srv/git_projects/Samovar/docs/result/delivery/step2_builds.md)
- [`build_matrix_results.md`](/srv/git_projects/Samovar/docs/result/delivery/build_matrix_results.md)
- [`manual_smoke_results.md`](/srv/git_projects/Samovar/docs/result/delivery/manual_smoke_results.md)

Reference planning documents:

- [`00_full_refactoring_roadmap_ru.md`](/srv/git_projects/Samovar/docs/refactoring/00_full_refactoring_roadmap_ru.md)
- [`02_state_normalization_plan_ru.md`](/srv/git_projects/Samovar/docs/refactoring/02_state_normalization_plan_ru.md)

## 6. Consolidated Step 2 Change Set

The following files were confirmed as part of the Step 2 implementation and verification work:

### Source / runtime files

- [`.github/workflows/firmware-ci.yml`](/srv/git_projects/Samovar/.github/workflows/firmware-ci.yml)
- [`Blynk.ino`](/srv/git_projects/Samovar/Blynk.ino)
- [`Samovar.h`](/srv/git_projects/Samovar/Samovar.h)
- [`Samovar.ino`](/srv/git_projects/Samovar/Samovar.ino)
- [`app/default_programs.h`](/srv/git_projects/Samovar/app/default_programs.h)
- [`app/loop_dispatch.h`](/srv/git_projects/Samovar/app/loop_dispatch.h)
- [`app/orchestration.h`](/srv/git_projects/Samovar/app/orchestration.h)
- [`app/process_common.h`](/srv/git_projects/Samovar/app/process_common.h)
- [`app/runtime_tasks.h`](/srv/git_projects/Samovar/app/runtime_tasks.h)
- [`app/status_text.h`](/srv/git_projects/Samovar/app/status_text.h)
- [`impurity_detector.h`](/srv/git_projects/Samovar/impurity_detector.h)
- [`io/actuators.h`](/srv/git_projects/Samovar/io/actuators.h)
- [`io/sensor_scan.h`](/srv/git_projects/Samovar/io/sensor_scan.h)
- [`modes/beer/beer_runtime.h`](/srv/git_projects/Samovar/modes/beer/beer_runtime.h)
- [`modes/beer/beer_support.h`](/srv/git_projects/Samovar/modes/beer/beer_support.h)
- [`modes/dist/dist_runtime.h`](/srv/git_projects/Samovar/modes/dist/dist_runtime.h)
- [`modes/nbk/nbk_runtime.h`](/srv/git_projects/Samovar/modes/nbk/nbk_runtime.h)
- [`modes/rect/rect_runtime.h`](/srv/git_projects/Samovar/modes/rect/rect_runtime.h)
- [`src/core/state/mode_codes.h`](/srv/git_projects/Samovar/src/core/state/mode_codes.h)
- [`src/core/state/mode_ownership.h`](/srv/git_projects/Samovar/src/core/state/mode_ownership.h)
- [`src/core/state/status_codes.h`](/srv/git_projects/Samovar/src/core/state/status_codes.h)
- [`state/runtime_types.h`](/srv/git_projects/Samovar/state/runtime_types.h)
- [`storage/nvs_profiles.h`](/srv/git_projects/Samovar/storage/nvs_profiles.h)
- [`ui/lua/runtime.h`](/srv/git_projects/Samovar/ui/lua/runtime.h)
- [`ui/menu/actions.h`](/srv/git_projects/Samovar/ui/menu/actions.h)
- [`ui/menu/input.h`](/srv/git_projects/Samovar/ui/menu/input.h)
- [`ui/web/ajax_snapshot.h`](/srv/git_projects/Samovar/ui/web/ajax_snapshot.h)
- [`ui/web/page_assets.h`](/srv/git_projects/Samovar/ui/web/page_assets.h)
- [`ui/web/routes_service.h`](/srv/git_projects/Samovar/ui/web/routes_service.h)
- [`ui/web/routes_setup.h`](/srv/git_projects/Samovar/ui/web/routes_setup.h)

### Tooling and tests

- [`tools/state_inventory.py`](/srv/git_projects/Samovar/tools/state_inventory.py)
- [`tools/state_magic_cleanup.py`](/srv/git_projects/Samovar/tools/state_magic_cleanup.py)
- [`tools/tests/test_lua_mode_selection.py`](/srv/git_projects/Samovar/tools/tests/test_lua_mode_selection.py)
- [`tools/tests/test_menu_mode_integration.py`](/srv/git_projects/Samovar/tools/tests/test_menu_mode_integration.py)
- [`tools/tests/test_mode_switching_behavior.py`](/srv/git_projects/Samovar/tools/tests/test_mode_switching_behavior.py)
- [`tools/tests/test_reset_pipeline_invariant.py`](/srv/git_projects/Samovar/tools/tests/test_reset_pipeline_invariant.py)
- [`tools/tests/test_state_contracts_baseline.py`](/srv/git_projects/Samovar/tools/tests/test_state_contracts_baseline.py)
- [`tools/tests/test_web_mode_integration.py`](/srv/git_projects/Samovar/tools/tests/test_web_mode_integration.py)
- [`tests/test_app_default_programs_extracted.py`](/srv/git_projects/Samovar/tests/test_app_default_programs_extracted.py)
- [`tests/test_app_orchestration.py`](/srv/git_projects/Samovar/tests/test_app_orchestration.py)
- [`tests/test_app_status_text_baseline.py`](/srv/git_projects/Samovar/tests/test_app_status_text_baseline.py)
- [`tests/test_change_samovar_mode_behavior.py`](/srv/git_projects/Samovar/tests/test_change_samovar_mode_behavior.py)
- [`tests/test_mode_code_constants.py`](/srv/git_projects/Samovar/tests/test_mode_code_constants.py)
- [`tests/test_mode_ownership_mapping.py`](/srv/git_projects/Samovar/tests/test_mode_ownership_mapping.py)
- [`tests/test_modes_integration_dispatch.py`](/srv/git_projects/Samovar/tests/test_modes_integration_dispatch.py)
- [`tests/test_reset_pipeline_delivery_artifacts.py`](/srv/git_projects/Samovar/tests/test_reset_pipeline_delivery_artifacts.py)
- [`tests/test_state_code_inventory_baseline.py`](/srv/git_projects/Samovar/tests/test_state_code_inventory_baseline.py)
- [`tests/test_state_magic_cleanup.py`](/srv/git_projects/Samovar/tests/test_state_magic_cleanup.py)
- [`tests/test_state_runtime_types.py`](/srv/git_projects/Samovar/tests/test_state_runtime_types.py)
- [`tests/test_status_code_constants.py`](/srv/git_projects/Samovar/tests/test_status_code_constants.py)
- [`tests/test_ui_menu_actions_behavior.py`](/srv/git_projects/Samovar/tests/test_ui_menu_actions_behavior.py)
- [`tests/test_ui_menu_input_behavior.py`](/srv/git_projects/Samovar/tests/test_ui_menu_input_behavior.py)
- [`tests/test_ui_menu_integration_behavior.py`](/srv/git_projects/Samovar/tests/test_ui_menu_integration_behavior.py)

### Delivery documents

- [`build_matrix_results.md`](/srv/git_projects/Samovar/docs/result/delivery/build_matrix_results.md)
- [`magic_cleanup_log.md`](/srv/git_projects/Samovar/docs/result/delivery/magic_cleanup_log.md)
- [`manual_smoke_results.md`](/srv/git_projects/Samovar/docs/result/delivery/manual_smoke_results.md)
- [`mode_codes_grep_log.md`](/srv/git_projects/Samovar/docs/result/delivery/mode_codes_grep_log.md)
- [`mode_ownership_mapping.md`](/srv/git_projects/Samovar/docs/result/delivery/mode_ownership_mapping.md)
- [`regression_run_log.md`](/srv/git_projects/Samovar/docs/result/delivery/regression_run_log.md)
- [`reset_pipeline_spec.md`](/srv/git_projects/Samovar/docs/result/delivery/reset_pipeline_spec.md)
- [`state_codes_inventory.md`](/srv/git_projects/Samovar/docs/result/delivery/state_codes_inventory.md)
- [`state_inventory_grep_log.md`](/srv/git_projects/Samovar/docs/result/delivery/state_inventory_grep_log.md)
- [`status_codes_grep_log.md`](/srv/git_projects/Samovar/docs/result/delivery/status_codes_grep_log.md)
- [`step2_builds.md`](/srv/git_projects/Samovar/docs/result/delivery/step2_builds.md)
- [`step2_regression_log.md`](/srv/git_projects/Samovar/docs/result/delivery/step2_regression_log.md)

## 7. Final Gate Decision

Step 2 state normalization is **software-complete** for `REQ-1..REQ-7`.

Step 2 gate is **not fully closed** because `REQ-8` is blocked by the missing real-hardware smoke validation recorded in
[`manual_smoke_results.md`](/srv/git_projects/Samovar/docs/result/delivery/manual_smoke_results.md).

No code changes are required to unlock the remaining gate.
What is required is real hardware access or a reachable running device for the manual smoke procedure.
