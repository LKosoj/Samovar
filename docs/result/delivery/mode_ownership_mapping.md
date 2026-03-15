# Step 2.3 mode ownership mapping

Дата фиксации: `2026-03-16`

## Runtime ownership model

- Requested mode хранится в `SamSetup.Mode` и задаёт внешний контракт выбора режима.
- Active runtime owner хранится в `Samovar_Mode` и определяет страницу, runtime handler и rect/dist/beer/bk/nbk gating.
- `Samovar_CR_Mode` используется как временный owner для profile/Lua reload sequence внутри `handleSaveProcessSettings()`, а после `change_samovar_mode()` синхронизируется с active runtime owner.
- Единая читаемая точка ownership semantics теперь находится в [src/core/state/mode_ownership.h](src/core/state/mode_ownership.h):
  - `mode_runtime_owner()`
  - `mode_active_page()`
  - `mode_program_owner()`
  - `mode_lua_owner()`
  - `mode_profile_namespace()`

## Ownership call sites

- Mode switch pipeline: [ui/web/routes_setup.h](ui/web/routes_setup.h)
  - `handleSaveProcessSettings()` выставляет `SamSetup.Mode`, затем вызывает `load_default_program_for_mode()`, `save_profile_nvs()`, `load_profile_nvs()`, `get_lua_mode_name(true)` и `change_samovar_mode()`.
- Active page rebinding: [ui/web/page_assets.h](ui/web/page_assets.h)
  - `change_samovar_mode()` теперь явно использует `mode_active_page(Samovar_Mode)` и `mode_runtime_owner(Samovar_Mode)`.
- Default programs: [app/default_programs.h](app/default_programs.h)
  - `load_default_program_for_mode()` теперь выбирает family через `mode_program_owner(Samovar_Mode)`.
- Lua family: [ui/lua/runtime.h](ui/lua/runtime.h)
  - `get_lua_mode_name()` теперь выбирает script family через `mode_lua_owner(Samovar_CR_Mode)`.
- Profile namespace: [storage/nvs_profiles.h](storage/nvs_profiles.h)
  - `profile_namespace_by_mode()` теперь делегирует в `mode_profile_namespace()`.
- Loop/orchestration ownership gates: [app/orchestration.h](app/orchestration.h)
  - Кнопочный loop использует `mode_is_rect_runtime()` / `mode_is_distillation_runtime()` / `mode_is_beer_runtime()` / `mode_is_bk_runtime()` / `mode_is_nbk_runtime()`.
- Runtime task gating: [app/runtime_tasks.h](app/runtime_tasks.h)
  - Alarm/progress ветки используют те же helper predicates вместо локальных mode checks.

## Mapping table

| Requested mode | Active page | Runtime owner | Runtime handlers | Program defaults | Optional Lua family | Profile namespace | Ownership note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `SAMOVAR_RECTIFICATION_MODE` | `/index.htm` | `SAMOVAR_RECTIFICATION_MODE` | [app/loop_dispatch.h](app/loop_dispatch.h) -> `withdrawal()`; [modes/rect/rect_runtime.h](modes/rect/rect_runtime.h); [app/orchestration.h](app/orchestration.h); [app/runtime_tasks.h](app/runtime_tasks.h) | rect program via [app/default_programs.h](app/default_programs.h) | rect via [ui/lua/runtime.h](ui/lua/runtime.h) | `sam_rect` via [storage/nvs_profiles.h](storage/nvs_profiles.h) | Baseline rect runtime owner. |
| `SAMOVAR_DISTILLATION_MODE` | `/distiller.htm` | `SAMOVAR_DISTILLATION_MODE` | [app/loop_dispatch.h](app/loop_dispatch.h) -> `distiller_proc()`; [modes/dist/dist_runtime.h](modes/dist/dist_runtime.h); [app/orchestration.h](app/orchestration.h); [app/runtime_tasks.h](app/runtime_tasks.h) | dist program via [app/default_programs.h](app/default_programs.h) | dist via [ui/lua/runtime.h](ui/lua/runtime.h) | `sam_dist` via [storage/nvs_profiles.h](storage/nvs_profiles.h) | Dedicated dist runtime/page owner. |
| `SAMOVAR_BEER_MODE` | `/beer.htm` | `SAMOVAR_BEER_MODE` | [app/loop_dispatch.h](app/loop_dispatch.h) -> `beer_proc()`; [modes/beer/beer_runtime.h](modes/beer/beer_runtime.h); [app/orchestration.h](app/orchestration.h); [app/runtime_tasks.h](app/runtime_tasks.h) | beer program via [app/default_programs.h](app/default_programs.h) | beer via [ui/lua/runtime.h](ui/lua/runtime.h) | `sam_beer` via [storage/nvs_profiles.h](storage/nvs_profiles.h) | Dedicated beer runtime/page owner. |
| `SAMOVAR_BK_MODE` | `/bk.htm` | `SAMOVAR_BK_MODE` | [app/loop_dispatch.h](app/loop_dispatch.h) -> `bk_proc()`; [modes/bk/bk_runtime.h](modes/bk/bk_runtime.h); [app/orchestration.h](app/orchestration.h); [app/runtime_tasks.h](app/runtime_tasks.h) | rect defaults via [app/default_programs.h](app/default_programs.h) | bk via [ui/lua/runtime.h](ui/lua/runtime.h) | `sam_bk` via [storage/nvs_profiles.h](storage/nvs_profiles.h) | Dedicated BK runtime with rect default program family. |
| `SAMOVAR_NBK_MODE` | `/nbk.htm` | `SAMOVAR_NBK_MODE` | [app/loop_dispatch.h](app/loop_dispatch.h) -> `nbk_proc()`; [modes/nbk/nbk_runtime.h](modes/nbk/nbk_runtime.h); [app/orchestration.h](app/orchestration.h); [app/runtime_tasks.h](app/runtime_tasks.h) | nbk defaults via [app/default_programs.h](app/default_programs.h) | nbk via [ui/lua/runtime.h](ui/lua/runtime.h) | `sam_nbk` via [storage/nvs_profiles.h](storage/nvs_profiles.h) | Dedicated NBK runtime/page owner. |
| `SAMOVAR_SUVID_MODE` | `/index.htm` | `SAMOVAR_RECTIFICATION_MODE` | Rect runtime owner through [src/core/state/mode_ownership.h](src/core/state/mode_ownership.h) -> `mode_runtime_owner()`; rect loop/runtime handlers from [app/loop_dispatch.h](app/loop_dispatch.h), [modes/rect/rect_runtime.h](modes/rect/rect_runtime.h), [app/orchestration.h](app/orchestration.h), [app/runtime_tasks.h](app/runtime_tasks.h) | beer defaults via [app/default_programs.h](app/default_programs.h) | rect via [ui/lua/runtime.h](ui/lua/runtime.h) | `sam_suvid` via [storage/nvs_profiles.h](storage/nvs_profiles.h) | Explicit mixed ownership: rect runtime/page + beer defaults + dedicated profile namespace. |
| `SAMOVAR_LUA_MODE` | `/index.htm` | `SAMOVAR_RECTIFICATION_MODE` | Rect runtime owner through [src/core/state/mode_ownership.h](src/core/state/mode_ownership.h) -> `mode_runtime_owner()`; rect loop/runtime handlers from [app/loop_dispatch.h](app/loop_dispatch.h), [modes/rect/rect_runtime.h](modes/rect/rect_runtime.h), [app/orchestration.h](app/orchestration.h), [app/runtime_tasks.h](app/runtime_tasks.h) | rect defaults via [app/default_programs.h](app/default_programs.h) | rect via [ui/lua/runtime.h](ui/lua/runtime.h) | `sam_lua` via [storage/nvs_profiles.h](storage/nvs_profiles.h) | Explicit mixed ownership: rect runtime/page + rect defaults + dedicated profile namespace. |

## change_samovar_mode semantics

- `handleSaveProcessSettings()` в [ui/web/routes_setup.h](ui/web/routes_setup.h) сначала выставляет requested mode:
  - `SamSetup.Mode = nextMode;`
  - `Samovar_Mode = (SAMOVAR_MODE)SamSetup.Mode;`
  - `Samovar_CR_Mode = Samovar_Mode;`
- После этого связанные ownership calls читают requested mode явно:
  - `load_default_program_for_mode()` -> `mode_program_owner(Samovar_Mode)`
  - `save_profile_nvs()` / `load_profile_nvs()` -> `mode_profile_namespace(...)`
  - `get_lua_mode_name(true)` -> `mode_lua_owner(Samovar_CR_Mode)`
- Финальная нормализация active runtime происходит в [ui/web/page_assets.h](ui/web/page_assets.h):
  - `const char* activePage = mode_active_page(Samovar_Mode);`
  - `Samovar_Mode = mode_runtime_owner(Samovar_Mode);`
  - `Samovar_CR_Mode = Samovar_Mode;`

## Notes

- В текущем проекте файл `logic.h` отсутствует; его роль выполняют [app/orchestration.h](app/orchestration.h) и [app/loop_dispatch.h](app/loop_dispatch.h).
- Числовые значения режимов и `startval` в рамках шага 2.3 не менялись.
- Внешние HTTP/JSON/Lua/Menu контракты не менялись: рефакторинг ограничен явным ownership source of truth и его использованием в runtime routing.
