# A-08 / W5.1 — воспроизводимые существующие PlatformIO-сборки

## Статус и цель

**Статус:** завершён; независимый review —
`PASS: no errors, no warnings`. R4 подтвердил A/B firmware/ELF/inventory,
7/7 environments и buildfs 2/2; точечная RAW_SUFFIX compatibility-корректировка
прошла focused и полный smoke 66/66.

Закрыть только дефект из аудита:

- Espressif platform сейчас задана Git URL без commit/tag;
- CI и release используют разные PlatformIO (`6.1.19` и `6.1.6`);
- нет формального inventory фактически используемых build dependencies;
- release не сохраняет firmware map и воспроизводимые build metadata;
- две clean среды ещё не подтверждают одинаковый firmware hash.

A-08 не добавляет продуктовую функцию и не меняет firmware/UI/runtime. Цель —
одинаковые существующие исходники и закреплённые зависимости дают одинаковые
`firmware.bin` для `Samovar` и `Samovar_s3`, а dependency/build metadata
сохраняются рядом с артефактами.

## Выбранное минимальное решение

Рассмотрены три границы:

1. Только pin platform/Core — недостаточно: нет inventory, metadata и clean-build
   доказательства.
2. Exact pins + один read-only metadata helper + один focused smoke + две
   isolated firmware builds — **выбрано**.
3. Собственный hermetic build-framework с wheel-lock/bootstrap, PlatformIO
   installer, pre-script, LittleFS materializer, map parser и binary normalizer —
   отклонён как scope expansion.

Выбранный вариант использует штатные PlatformIO/pip/venv и обычный SHA-256.
Helper ничего не устанавливает, не скачивает, не меняет build environment и не
нормализует артефакты.

## Подтверждённый baseline, который надо перепроверить перед patch

| Объект | Текущее значение | Действие |
|---|---|---|
| Espressif platform | `https://github.com/platformio/platform-espressif32.git`, installed commit `3c076807e1f55b90799b50b946e76a0508e97778` | добавить exact `#<40-hex>` без upgrade |
| `framework-arduinoespressif32` | `3.20017.241212+sha.dcc1105b` | exact override |
| `tool-esptoolpy` | `2.40900.250804` | exact override |
| `tool-mkfatfs` | `2.0.1` | exact override |
| `tool-mklittlefs` | `1.203.210628` | exact override |
| `tool-mkspiffs` | `2.230.0` | exact override |
| `tool-scons` | `4.40801.0`, Core requirement `~4.40801.0` | exact install через штатный PlatformIO package manager |
| toolchains | exact `8.4.0+2021r2-patch5` в platform | не дублировать и не обновлять |
| partition tool | existing URL `v1.4.4` | сохранить byte-for-byte |
| firmware CI | Python `3.12`, PlatformIO `6.1.19`, семь env | сохранить matrix/jobs |
| release | Python `3.x`, PlatformIO `6.1.6`, default `Samovar` | унифицировать с CI |

Если любой exact package spec не разрешается в пустом isolated core, работа
останавливается. Branch-head, nearest version, cached global package или иной
source как fallback запрещены.

## Scope

### Разрешённые production/test изменения

```text
platformio.ini
.github/workflows/firmware-ci.yml
.github/workflows/build_release.yml
tools/build_metadata.py                 # new, read-only stdlib CLI
tools/smoke_reproducible_builds.py      # new, единственный A-08 contract
```

### Разрешённая compatibility-only корректировка после R4

```text
tools/ui_pack_assets_contract.py
tools/smoke_ui_pack_assets.py
```

Этот scope разрешает только научить существующий RAW_SUFFIX parser двум exact
A-08 base flags. Product/UI/data, raw manifest/schema, Lua suffix semantics и
asset inventory не меняются и не расширяются.

После code/gate/reviewer PASS разрешены только точечные metadata updates:

```text
.cli-proxy/.codebase_map/INDEX.md
.cli-proxy/.codebase_map/TESTING.md
.cli-proxy/.codebase_map/STACK.md
.cli-proxy/.codebase_map/STRUCTURE.md
.cli-proxy/.codebase_map/nodes/platformio-ini.md
.cli-proxy/.codebase_map/nodes/tools.md
.claude/experts/plans/samovar-a08-reproducible-builds.md
.claude/experts/plans/samovar-audit-remediation.md
.claude/experts/plans/samovar-remaining-remediation-2026-07-12.md
```

### Явно вне scope

- `data/**`, `libraries/**`, partitions, root `.ino/.h`, `SPIFFSEditor.h`,
  Blynk, Ace и web UI;
- новый workflow/job/environment/release stage;
- lock всех Python wheels, собственный resolver/installer/bootstrap;
- PlatformIO `pre:` script и изменение обычного локального `pio run`;
- A/B LittleFS materialization/comparison;
- новый map/ELF/section parser, normalization прошиваемых bytes;
- SBOM, licenses/CVE/security/signing/attestation;
- container/Nix/VM и смена GitHub runner/action refs;
- изменение `tools/smoke_ci_contract.py` или `tools/analyze_map.py`.

## Изменения по файлам

### `platformio.ini`

1. Добавить к текущей platform URL exact commit
   `3c076807e1f55b90799b50b946e76a0508e97778`.
2. В существующий `platform_packages` добавить только пять exact overrides:
   framework, esptoolpy и три filesystem tools из baseline-таблицы.
3. Existing partition-tool URL, boards, остальные flags, environments,
   partitions, filesystem и default env не менять.
4. В base `env:Samovar` заменить standalone macro map ровно двумя active flags
   в указанном порядке:
   `-ffile-prefix-map=${platformio.packages_dir}=.platformio/packages`, затем
   `-fdebug-prefix-map=${platformio.src_dir}=.`.
5. Первый flag сохраняет package macro mapping и одновременно отображает
   package debug paths; второй меняет только два project DWARF `comp_dir` paths.
   Standalone `-fmacro-prefix-map` после замены запрещён.
6. Не добавлять Core/build-dir maps, random seed, build-id, post-processing,
   `extra_scripts`, timestamp flags или новые targets.

### `tools/build_metadata.py`

Один stdlib-only CLI после успешной сборки создаёт canonical sorted JSON. Он:

- принимает explicit `--project-root`, `--core-dir`, `--environment`,
  `--firmware`, `--map`, `--git-sha`, `--dirty`, `--source-date-epoch`,
  `--output`;
- требует существующие regular files и валидные explicit значения; missing или
  malformed input завершает работу ошибкой;
- записывает schema version, environment, Git SHA/dirty, Python и PlatformIO
  версии, а также проверенный decimal `SOURCE_DATE_EPOCH`;
- читает platform/package manifests из переданного isolated Core, фиксирует
  platform revision, package name/version/source и canonical tree SHA-256;
- исключает общий VCS/package-manager/generated state, не влияющий на build:
  `.git/**`, `.piopm`, `__pycache__/**`, `*.pyc`;
- только из package tree SHA дополнительно исключает созданные pip при install
  `tool-esptoolpy` launchers `_contrib/bin/**` и соответствующие
  `_contrib/*.dist-info/RECORD`; никакие другие `_contrib` paths не исключаются;
- инвентаризирует каждый top-level `libraries/*`: имя/version/source из
  существующего `library.json`, `library.properties` или `package.json`, если
  поле реально присутствует, плюс полный canonical tree SHA-256;
- сохраняет raw size/SHA-256 `firmware.bin` и raw size/SHA-256 `firmware.map`;
- не пишет absolute paths, wall-clock/generated-at timestamps, hostname, PID
  или secrets; единственное timestamp-поле — обязательный source-derived
  `source_date_epoch`;
- не вызывает network/pip/PlatformIO, не создаёт packages и не меняет файлы.

Tree hash кодирует sorted POSIX relative path, file type, executable bit и bytes
или symlink target. Root path, mtime, uid/gid и enumeration order не входят.
Кроме двух exact pip-generated package paths выше, ordinary `_contrib` code,
manifest/binary bytes и любые absolute-path строки остаются частью hash.
Неизвестный file type или выход symlink за инвентаризируемый root — error, а не
fallback.

### Workflows

Оба существующих workflow:

1. сохраняют triggers, job names, matrix/default env, release permissions,
   artifact name/retention и release glob `firmware/**/*.bin`;
2. используют Python `3.12` и exact `platformio==6.1.19` без upgrade;
3. через штатный PlatformIO package manager до build устанавливают exact
   `platformio/tool-scons@4.40801.0` с `--global --no-save`; wheel-lock или pip
   SCons не добавляются;
4. до build экспортируют один decimal
   `SOURCE_DATE_EPOCH=$(git show -s --format=%ct "$GITHUB_SHA")`;
5. запускают PlatformIO только как `python -m platformio`;
6. после build вызывают `build_metadata.py` с тем же explicit epoch для
   фактически собранного env.

Firmware CI не имеет artifact flow и не получает его в A-08: каждый matrix build
только генерирует и валидирует metadata локально в job. Release по-прежнему
собирает default `Samovar`, сохраняет текущий
`FIRMWARE_VERSION=${{github.ref_name}}` и расширяет только существующий Archive
upload: `firmware.bin`, raw `firmware.map` и `build-metadata.json`. Release
action по-прежнему публикует только `.bin` через неизменный glob.

## Focused contract

`tools/smoke_reproducible_builds.py` — единственный новый A-08 smoke. Он не
обращается к сети и проверяет:

1. platform URL содержит exact ожидаемый 40-hex commit;
2. присутствуют ровно пять новых exact overrides, а existing toolchains и
   partition URL не дублированы/не изменены;
3. active base env содержит ровно два path-map flags и только в порядке
   `-ffile-prefix-map=${platformio.packages_dir}=.platformio/packages`,
   `-fdebug-prefix-map=${platformio.src_dir}=.`; standalone macro map,
   Core/build-dir maps, random seed, build-id и post-processing отсутствуют;
4. оба workflow используют Python `3.12`, PlatformIO `6.1.19`,
   exact PlatformIO-installed `tool-scons@4.40801.0`, `python -m platformio` и
   commit-derived `SOURCE_DATE_EPOCH` до build;
5. triggers, job names, seven-env matrix, default env, artifact retention и
   release glob сохранены;
6. metadata вызывается после build с exact epoch; firmware CI не получает
   artifact upload, а release Archive сохраняет map/metadata рядом с firmware;
7. helper на synthetic temp trees выдаёт deterministic JSON при разных root
   paths/mtime/order; one-byte dependency/artifact change меняет нужный hash;
8. разные generated launcher shebang/`RECORD` не меняют package inventory;
   изменение ordinary `_contrib` code, package manifest/binary или arbitrary
   absolute-path bytes вне двух exact exclusions обязано менять package hash;
9. missing manifest/artifact, invalid Git SHA/dirty, symlink escape и unknown
   file type fail явно;
10. output не содержит absolute roots, wall-clock/generated-at timestamp,
   host/PID и не раскрывает содержимое `user_config_override.h`; обязательный
   `source_date_epoch` сохраняется;
11. helper не содержит install/download/pre-script/materialization/normalization
   paths и не импортирует third-party modules;
12. forbidden source/UI/vendor files не являются частью A-08 write scope.

Существующий `tools/smoke_ci_contract.py` запускается без изменений как
regression gate; дублировать его assertions в нём запрещено.
`tools/smoke_ui_pack_assets.py` получает только positive exact ordered A-08 pair
и negative substitutions/copy-to-child cases для compatibility parser.

## Исполняемый порядок

### 1. Корректирующий R4 RED

1. Зафиксировать current status/diff/hash allowlist-файлов после остановленного
   A/B gate.
2. До production correction заменить focused assertion на exact ordered
   file/debug pair и явный запрет standalone macro map.
3. RED обязан падать только из-за прежнего macro-only production config;
   package-hash exclusion и все его positive controls уже остаются GREEN.

### 2. Минимальная корректировка

1. Заменить macro-only flag exact ordered file/debug pair в base env.
2. Не добавлять Core/build maps, random/build-id flags или post-processing.
3. Package inventory correction не расширять; запустить focused smoke и
   `py_compile` с cache вне repo.

### 3. Две независимые clean firmware-среды

Из одного frozen live snapshot создать в `/tmp` два source roots с разными
absolute paths. Snapshot содержит только реальные build inputs:

- `platformio.ini`, `partitions/**`;
- все root compile inputs (`.ino/.h/.hpp/.c/.cc/.cpp/.S`), включая tracked
  `user_config_override.h` без вывода его содержимого;
- полный `libraries/**`;
- `tools/build_metadata.py`.

До build проверить одинаковый canonical snapshot hash и отсутствие `.pio`.
Для A и B использовать отдельные `HOME`, Python venv, `PLATFORMIO_CORE_DIR`,
build cache и temp dir. Глобальные `/root/.platformio`, pip cache и repo `.pio`
не использовать. В каждой среде:

1. установить только `platformio==6.1.19` в её venv;
2. exact-командой штатного PlatformIO package manager установить в её core
   `platformio/tool-scons@4.40801.0` с `--global --no-save`;
3. проверить `python -m platformio --version` и resolved SCons version;
4. экспортировать один frozen commit-derived `SOURCE_DATE_EPOCH`;
5. последовательно собрать `Samovar`, сохранить firmware/map/metadata с тем же
   explicit epoch;
6. затем последовательно собрать `Samovar_s3`, сохранить те же artifacts.

Для каждого одинакового env A↔B обязаны совпасть:

- raw bytes и SHA-256 `firmware.bin` без post-build rewrite/normalization;
- dependency inventory: PlatformIO/Core, platform revision, packages и vendored
  library tree hashes; package hashes игнорируют только два exact pip-generated
  path classes из раздела helper;
- Git/source context, `SOURCE_DATE_EPOCH` и firmware size.

R3 подтвердил одинаковые platform/package/library inventories и одинаковый
firmware payload вне `app_elf_sha256` и производного footer. В ELF остались
2077 package debug roots и два project DWARF `comp_dir`: package file-prefix map
закрывает одновременно package macro/debug paths, а source debug-prefix map —
только два project paths. В raw firmware direct A/B roots отсутствовали и
diagnostic strings уже имели стабильный `.platformio/packages` prefix.
Raw `firmware.map` сохраняется как evidence и artifact, но не нормализуется. Его
path-dependent SHA не используется как ложный критерий firmware equality;
post-build binary normalization запрещена, raw firmware equality остаётся
обязательной.
Если firmware или dependency inventory различаются, A-08 останавливается:
сначала точная диагностика source/package/hash, затем отдельное согласование,
если исправление требует расширения allowlist.

### 4. Regression gates

После A/B PASS в одном уже проверенном isolated root последовательно:

1. собрать оставшиеся пять existing environments; итог `7/7`;
2. выполнить existing `buildfs` для `Samovar` и `Samovar_s3` и проверить
   `littlefs.bin < 0xC0000`; A/B LittleFS equality не заявлять;
3. в live tree запустить focused smoke, неизменённый `smoke_ci_contract.py`,
   полный smoke runner и `git diff --check`;
4. после PlatformIO запустить blocking и extended cppcheck; errors/warnings 0;
5. проверить exact A-08 allowlist и отсутствие repo `.pio`, venv, caches,
   binaries, maps, metadata/logs и новых secrets;
6. обновить только affected map/status docs и повторить `git diff --check`.

A-08 не меняет web UI, поэтому отдельный Playwright gate в этой задаче не
запускается. Полный browser regression остаётся частью финальной aggregate
стабилизации всей очереди.

## Reviewer loop и критерии PASS

Отдельный reviewer-сабагент читает весь A-08 diff и evidence. Любой
ERROR/WARNING исправляется внутри того же allowlist, затем повторяются affected
gates и review. Закрытие возможно только при точной строке
`PASS: no errors, no warnings` и одновременно:

- exact platform/package/SCons pins разрешились в двух пустых cores;
- base env содержит exact ordered file/debug pair без standalone macro map и
  иных reproducibility flags/scripts;
- workflow версии и metadata flow едины без topology drift;
- A/B `Samovar` и `Samovar_s3` firmware bytes одинаковы;
- dependency inventory A↔B одинаков после исключения только generated
  `_contrib/bin/**` и `_contrib/*.dist-info/RECORD` из package hashes;
- семь environments, buildfs 2/2, smoke/cppcheck/diff/map gates зелёные;
- firmware/UI/vendor/partitions не изменены;
- отсутствуют installer framework, fallback, normalization и scope expansion.

## Rollback и stop conditions

- Не использовать `git reset/checkout/clean`; отменять только собственный A-08
  hunk.
- Exact package не разрешается — stop, не брать alternate source/version.
- Один и тот же failure повторился дважды — исследовать web и сравнить 3–5
  решений по правилу проекта, затем выбрать только решение в текущем scope.
- Необъяснимый firmware drift — FAIL, а не документированное исключение.
- Требуется менять firmware/UI/vendor/partition или создавать build-framework —
  stop и запрос нового решения у пользователя.
