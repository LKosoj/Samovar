# U-02 Wave P1.1 — сохранённый pack format/store и cross-language golden tests

## Статус и цель

Статус: **реализовано, проверено и сохранено как неиспользуемый фундамент**.
P1.1 не подключён к firmware/runtime и не является активным направлением U-02.
Актуальное решение — `docs/plans/2026-07-12-cdn-ace-scope-decision.md`: Ace
остаётся на CDN, локальный Ace и UI pack runtime отменены.

Реализованный P1.1 фиксирует минимальный Arduino-free фундамент бинарного UI pack v1:

- точный wire format header `104` bytes и entry prefix `52` bytes;
- pure reader над bounded random-access source без `File`, LittleFS, NVS и Arduino types;
- обязательные CRC32, SHA-256 и gzip verification boundaries;
- Python codec только для pack bytes и deterministic golden fixtures;
- cross-language Python/C++ behavioral vectors с одинаковыми результатами и стабильными error codes;
- checked arithmetic, canonical paths, нулевой heap и отсутствие fallback.

Исходное storage-решение отменено. Историю решения фиксирует
`docs/plans/2026-07-11-ui-pack-storage-decision.md`; текущую границу —
`docs/plans/2026-07-12-cdn-ace-scope-decision.md`. Этот документ описывает только
сохранённый wire format и его тесты.

## Исторический baseline и граница

На baseline 2026-07-11 отсутствовали `ui_pack_*.h` и pack fixtures. Host C++
smokes компилировались как C++11 через
`g++ -std=c++11 -Wall -Wextra -Werror`; `tools/run_smoke_tests.py` запускал
`tools/smoke_*.py`.

P1.1 был реализован после A-10 checkpoint и прошёл отдельный reviewer-loop. Новая
production-интеграция из этого документа не планируется.

P1.1 не изменяет:

- `numeric_parse.h`, `control_numeric_input.h`, `power_regulator_numeric_input.h` и любые A-10 production/tests;
- `FS.ino`, `Samovar.ino`, `WebServer.ino`, `SPIFFSEditor.h`, `samovar_api.h`;
- NVS pointer, catalog publication, slot leases, `OperationStore`, updater/editor FSM;
- `platformio.ini`, partition table, `data/`, UI pages и Ace runtime;
- network download.

## Рассмотренные варианты

| Вариант | Плюсы | Риски/минусы | Решение |
|---|---|---|---|
| Packed C/C++ structs и cast bytes → struct | короткий код | alignment/endianness/ABI UB, host/ESP drift, unsafe truncated input | отклонён |
| Reader сразу над LittleFS `File` с mbedTLS/inflate | быстро до runtime demo | смешивает format, storage и ESP dependencies; нельзя host-test без stubs; пересекает P3 | отклонён |
| Fixed wire codec + callback `readAt` + обязательные verify ops | Arduino-free, C++11 host-test, bounded memory | runtime adapter не реализован | выбран для P1.1 |

Python и C++ намеренно имеют две независимые реализации wire codec: иначе cross-language test сравнивал бы код с самим собой. Нормативным контрактом P1.1 остаётся format table, а drift блокируется checked-in byte vectors и static assertions.

## Реализованный write scope P1.1

### Создано

- `ui_pack_format.h` — wire constants, closed enums, POD views/results, LE/CRC/FNV/path primitives и decoding без I/O ownership.
- `ui_pack_store.h` — pure `readAt`/verification boundary, bounded workspace, full pack verifier, verified compact index и exact-path lookup; без filesystem/runtime state.
- `tools/ui_pack_format.py` — standard-library Python codec, deterministic gzip encoder и fixture-building primitives.
- `tools/generate_ui_pack_golden.py` — единственный writer checked-in P1.1 fixtures; `--check` генерирует во временный каталог и byte-compares.
- `tools/smoke_ui_pack_format.py` — Python/C++ host behavioral runner.
- `tools/fixtures/ui_pack_v1/golden-vectors.json` — deterministic metadata, symbolic/numeric error, offsets, hashes и mutation recipe для каждого vector.
- `tools/fixtures/ui_pack_v1/valid/*.pack` и `tools/fixtures/ui_pack_v1/invalid/*.pack` — только generator-owned binary vectors.
- `.cli-proxy/.codebase_map/nodes/ui-pack-format-h.md` и `ui-pack-store-h.md` после implementation.

### Изменено

- `tools/static_analysis_sources.json` — sorted entries обоих новых root headers.
- `.cli-proxy/.codebase_map/INDEX.md` — два новых node links.
- `.cli-proxy/.codebase_map/nodes/tools.md` — fixture/generator/smoke contract и актуальные counts.

Не создавать `.cpp` files. C++ harness формируется `smoke_ui_pack_format.py` во временном каталоге, как существующие host smokes.

## `ui_pack_format.h`: точный wire contract

Header обязан содержать именованные offsets и `static_assert` для каждого offset, но не packed wire struct. Все integers читаются/пишутся только `read_le16`, `read_le32`, `write_le16`, `write_le32`.

### Header v1 — ровно 104 bytes

| Offset | Size | Symbol/field | Contract |
|---:|---:|---|---|
| 0 | 8 | `UI_PACK_MAGIC` | exact bytes `53 4D 55 49 50 4B 31 00` (`SMUIPK1\0`) |
| 8 | 2 | `formatVersion` | exact `1` |
| 10 | 2 | `headerSize` | exact `104` |
| 12 | 2 | `entryCount` | `1..32` |
| 14 | 2 | `packFlags` | exact one of `UI_PACK_KIND_ACE=0x0001`, `UI_PACK_KIND_UI=0x0002` |
| 16 | 4 | `sourceGeneration` | wire allows `0..UINT32_MAX`; named verification policy below decides whether `0` is admissible |
| 20 | 2 | `bootstrapSchema` | Ace `0`; UI v1 `1` |
| 22 | 2 | `reserved` | exact `0` |
| 24 | 4 | `indexOffset` | exact `104` |
| 28 | 4 | `payloadOffset` | exact checked end of dense variable-length index |
| 32 | 4 | `totalSize` | exact source size, no trailing bytes |
| 36 | 32 | `payloadSha256` | SHA-256 exact bytes `[104,totalSize)` |
| 68 | 32 | `requiredAcePackSha256` | all zero for Ace; exact expected full Ace pack SHA for UI |
| 100 | 4 | `headerCrc32` | reflected IEEE CRC32 exact raw bytes `[0,100)` |

CRC parameters are fixed: polynomial `0xEDB88320`, init `0xFFFFFFFF`, reflected byte processing, final xor `0xFFFFFFFF`. Comparison is against LE uint32 at offset 100. Unknown pack flag bits and every reserved byte fail closed.

`packSha256` is deliberately absent from the header: it is SHA-256 exact bytes `[0,totalSize)` after the final header CRC is written. `payloadSha256` and `packSha256` receive separate symbols, fields and golden assertions; substituting one for the other is a test failure.

### Entry v1 — 52-byte prefix followed by path bytes

| Entry-relative offset | Size | Field | Contract |
|---:|---:|---|---|
| 0 | 4 | `pathHash` | FNV-1a 32-bit of exact canonical path bytes |
| 4 | 2 | `pathLength` | `1..47` |
| 6 | 1 | `mimeId` | closed enum below |
| 7 | 1 | `flags` | allowed mask `0x07` only |
| 8 | 4 | `storedOffset` | absolute from pack start |
| 12 | 4 | `storedSize` | exact stored byte range length |
| 16 | 4 | `expandedSize` | exact uncompressed length |
| 20 | 32 | `storedSha256` | SHA-256 exact stored range |
| 52 | `pathLength` | path | ASCII bytes without NUL/padding |

Entry flags are fixed: `GZIP=0x01`, `EDITABLE=0x02`, `IMMUTABLE=0x04`. Unknown bits fail; only the simultaneous `EDITABLE|IMMUTABLE` combination is forbidden. `GZIP` is structurally orthogonal to the two mutability bits: a GZIP or non-GZIP entry may carry neither mutability bit or exactly one of them. Required/optional не является wire bit; поэтому structural P1.1 не вводит required-семантику для `storedSize==0`.

For every entry without `GZIP`, structural verification requires exact `expandedSize == storedSize` before digest work and returns `UI_PACK_ENTRY_LAYOUT_INVALID` on mismatch. This includes the zero-length structural case: both sizes must be zero. GZIP entries instead prove `expandedSize` during streaming inflate as specified below.

Closed MIME v1 IDs are limited to current packed assets:

- `1 = text/html; charset=utf-8`;
- `2 = text/css; charset=utf-8`;
- `3 = application/javascript; charset=utf-8`;
- `4 = image/png`;
- `5 = image/gif`;
- `6 = image/x-icon`;
- `7 = audio/mpeg`.

`0` and `8..255` fail. New MIME IDs require reviewed producer/reader change; unknown IDs are never served as `application/octet-stream` fallback.

## Canonical path и dense layout

`ui_pack_validate_path(const uint8_t*, uint16_t)` enforces:

- length `1..47`, ASCII only `[A-Za-z0-9._/-]`;
- no leading/trailing slash, repeated slash or backslash;
- no empty, `.` or `..` segment;
- case-sensitive bytes; no Unicode normalization or case folding;
- FNV-1a offset basis `2166136261`, prime `16777619`, uint32 wrap.

Index records are strictly increasing by unsigned bytewise full path order; equal paths fail as duplicate. `pathHash` is only a prefilter. `ui_pack_find_entry` first matches hash, then length and every path byte. Golden fixture uses canonical collision pair `costarring`/`liquid` and proves lookup never trusts hash alone.

Index starts at 104 and is dense: each next record offset is checked `previous + 52 + pathLength`; computed end must equal `payloadOffset`. Payload is in the same order and dense: first `storedOffset == payloadOffset`, every next offset equals checked previous `storedOffset + storedSize`, and final end equals `totalSize`. Gaps, overlaps, reorder and trailing bytes fail.

## Checked arithmetic and validation order

Every offset/length operation uses `ui_pack_checked_add_u32(left,right,out)` before addition. The same applies to:

- `recordOffset + 52`, then `+ pathLength`;
- accumulated index size and expected `payloadOffset`;
- `storedOffset + storedSize`;
- source reads and chunk iteration;
- expanded byte counters and gzip ISIZE comparison.

The source adapter rejects physical sizes above `UINT32_MAX` before constructing `UiPackReadSource`. Conversion to `size_t` happens only after the requested chunk is bounded by caller buffer size. No subtraction is performed before proving left ≥ right.

Stable failure precedence for `ui_pack_verify`:

1. arguments/callbacks/policy (`maxPackBytes` must be non-zero) and source size `104..maxPackBytes`;
2. exact 104-byte read, magic, header CRC;
3. version/header size/count/kind/schema, `sourceGeneration` policy, reserved/index/total fields;
4. entry prefix/path/MIME/flags/hash/order, non-GZIP `expandedSize == storedSize` and exact dense index end;
5. dense payload ranges and arithmetic;
6. header payload SHA;
7. every stored SHA in index order;
8. every GZIP stream in index order;
9. required Ace dependency policy;
10. full `packSha256`, candidate finalization and single copy to output.

Semantic invalid vectors recompute all earlier checksums so the intended deeper error is reachable. `out` remains byte-for-byte unchanged on every failure; candidate state lives in caller-owned workspace and is copied only at step 10.

Within step 3 the fixed order is version → header size → entry count → kind → schema → source-generation policy → reserved → index offset → total size. `PUBLISHED_ONLY` accepts only `1..UINT32_MAX`. `FACTORY_UNPUBLISHED_ALLOWED` additionally accepts `0` only for the expected UI kind at the explicit checked factory-B call site; it never makes generation-0 Ace valid. Therefore schema errors precede generation errors, while `UI_PACK_SOURCE_GENERATION_INVALID` precedes reserved/index/total, entry, digest and Ace-dependency errors. `ui_pack_validate_publishable` returns that same generation error for a generation-0 index produced under the factory-only policy.

## SHA-256 и gzip rules

`ui_pack_store.h` does not implement or select an ESP crypto/inflate library. It requires explicit non-null verification operations:

- `UiPackSha256Ops{context, reset, update, finish}`; core reader owns bounded `readAt` chunking and feeds exact ranges;
- `UiPackVerifyGzipFn`; receives source/range, caller-owned I/O scratch and caller-owned inflate context/window, and returns exact consumed deflate bytes, expanded byte count and uncompressed CRC32.

Missing/failed operations return explicit errors; structural parse cannot be promoted to verified success. No built-in skip, uncompressed fallback or trust-in-header mode exists.

Generator emits one canonical RFC1952 member:

- `ID1/ID2=1F 8B`, `CM=8`, `FLG=0`, `MTIME=0`, `XFL=2`, `OS=255`;
- no FEXTRA/FNAME/FCOMMENT/FHCRC and no concatenated member;
- raw DEFLATE is produced by exactly `zlib.compressobj(level=9, method=zlib.DEFLATED, wbits=-15, memLevel=8, strategy=zlib.Z_DEFAULT_STRATEGY)` followed by exactly one `flush(zlib.Z_FINISH)`;
- trailer is LE CRC32 of expanded bytes and LE `ISIZE == expandedSize`.

P1.1 itself records generator provenance in `golden-vectors.json`: exact Python implementation/version, `zlib.ZLIB_VERSION`, `zlib.ZLIB_RUNTIME_VERSION` and all five DEFLATE parameters above. `--check` first requires the running Python/zlib strings and parameter tuple to equal the checked-in provenance, then performs generation and byte comparison; mismatch is an explicit setup failure, never an implicit fixture rewrite or compatibility fallback. A reviewed regeneration is required to change this toolchain tuple.

Reader rejects reserved gzip flags, optional fields not produced by v1, truncated header/deflate/trailer, non-terminal stream, extra member/trailing stored bytes, expanded counter overflow, output beyond declared `expandedSize`, trailer CRC mismatch and ISIZE mismatch. Verification is streaming; expanded content and whole pack are never materialized.

## Exact C++ symbols и ownership boundary

### `ui_pack_format.h`

Public symbols:

- constants `UI_PACK_FORMAT_VERSION`, `UI_PACK_HEADER_SIZE`, `UI_PACK_ENTRY_PREFIX_SIZE`, `UI_PACK_MAX_ENTRIES`, `UI_PACK_MAX_PATH_BYTES`, digest sizes and every field offset;
- enums `UiPackKind`, `UiPackMimeId`, `UiPackEntryFlags`, `UiPackError`;
- POD `UiPackResult {error, entryIndex, offset}`, `UiPackHeaderView`, `UiPackEntryView`;
- `read_le16`, `read_le32`, `write_le16`, `write_le32`;
- `ui_pack_checked_add_u32`, `ui_pack_crc32_update`, `ui_pack_crc32`, `ui_pack_fnv1a_path`, `ui_pack_compare_paths`, `ui_pack_validate_path`;
- `ui_pack_decode_header`, `ui_pack_decode_entry_prefix`.

No function accepts `String`, `Stream`, `File`, `fs::FS` or nullable implicit defaults.

`UiPackError` numeric values are part of cross-language v1 diagnostics and freeze in this order:

| Value | Symbol | Meaning |
|---:|---|---|
| 0 | `UI_PACK_OK` | verified success |
| 1 | `UI_PACK_INVALID_ARGUMENT` | null/malformed source, output, workspace or policy |
| 2 | `UI_PACK_READ_FAILED` | `readAt` could not fill an exact bounded range |
| 3 | `UI_PACK_SIZE_INVALID` | source outside `104..maxPackBytes` |
| 4 | `UI_PACK_MAGIC_INVALID` | wrong 8-byte magic |
| 5 | `UI_PACK_HEADER_CRC_MISMATCH` | CRC `[0,100)` mismatch |
| 6 | `UI_PACK_VERSION_UNSUPPORTED` | format version is not 1 |
| 7 | `UI_PACK_HEADER_SIZE_INVALID` | header size is not 104 |
| 8 | `UI_PACK_ENTRY_COUNT_INVALID` | count outside `1..32` |
| 9 | `UI_PACK_KIND_INVALID` | pack flags are not exact ACE/UI |
| 10 | `UI_PACK_SCHEMA_INVALID` | kind/schema pair invalid |
| 11 | `UI_PACK_RESERVED_NONZERO` | reserved field or unknown bit non-zero |
| 12 | `UI_PACK_INDEX_OFFSET_INVALID` | index offset is not 104 |
| 13 | `UI_PACK_PAYLOAD_OFFSET_INVALID` | computed dense index end differs |
| 14 | `UI_PACK_TOTAL_SIZE_INVALID` | header/source/payload final end differs |
| 15 | `UI_PACK_ARITHMETIC_OVERFLOW` | checked u32 operation cannot be represented |
| 16 | `UI_PACK_PATH_LENGTH_INVALID` | path length outside `1..47` |
| 17 | `UI_PACK_PATH_INVALID` | canonical path grammar failure |
| 18 | `UI_PACK_PATH_HASH_MISMATCH` | FNV field differs from full path |
| 19 | `UI_PACK_PATH_ORDER_INVALID` | bytewise order decreases |
| 20 | `UI_PACK_PATH_DUPLICATE` | equal full paths |
| 21 | `UI_PACK_MIME_INVALID` | MIME ID outside closed enum |
| 22 | `UI_PACK_ENTRY_FLAGS_INVALID` | unknown/conflicting entry flags |
| 23 | `UI_PACK_ENTRY_LAYOUT_INVALID` | non-GZIP size mismatch or payload gap, overlap/order mismatch |
| 24 | `UI_PACK_PAYLOAD_SHA_MISMATCH` | SHA `[104,totalSize)` mismatch |
| 25 | `UI_PACK_ENTRY_SHA_MISMATCH` | stored range SHA mismatch |
| 26 | `UI_PACK_VERIFY_OPS_MISSING` | mandatory SHA/gzip operation absent |
| 27 | `UI_PACK_SHA_FAILED` | configured SHA operation failed |
| 28 | `UI_PACK_GZIP_HEADER_INVALID` | non-canonical/truncated gzip header |
| 29 | `UI_PACK_GZIP_STREAM_INVALID` | inflate error or no exact stream end |
| 30 | `UI_PACK_GZIP_SIZE_MISMATCH` | produced bytes differ from `expandedSize` |
| 31 | `UI_PACK_GZIP_CRC_MISMATCH` | expanded CRC differs from trailer |
| 32 | `UI_PACK_GZIP_ISIZE_MISMATCH` | trailer ISIZE differs from expanded size |
| 33 | `UI_PACK_GZIP_TRAILING_DATA` | extra member/bytes after first member |
| 34 | `UI_PACK_ACE_DEPENDENCY_MISMATCH` | required Ace digest violates policy |
| 35 | `UI_PACK_SOURCE_GENERATION_INVALID` | generation not publishable in requested policy |
| 36 | `UI_PACK_ENTRY_NOT_FOUND` | exact path absent after verified lookup |
| 37 | `UI_PACK_ENTRY_RANGE_INVALID` | requested stored subrange escapes entry |

Python mirrors these numeric values and every golden vector records both number and symbol. New values append only; renumbering v1 is forbidden.

### `ui_pack_store.h`

Public symbols:

- `UiPackReadSource {void* context, uint32_t size, UiPackReadAtFn readAt}`; `readAt` must fill the exact requested range or return false;
- `UiPackSha256Ops`, `UiPackGzipResult`, `UiPackVerifyGzipFn`, `UiPackVerifyOps`;
- `UiPackGenerationPolicy {PUBLISHED_ONLY, FACTORY_UNPUBLISHED_ALLOWED}` and `UiPackVerifyPolicy {expectedKind, expectedAcePackSha256, maxPackBytes, generationPolicy}` with no default constructor values at call sites;
- compact `UiPackEntryRef` containing record/path hash/stored offsets and sizes, length, MIME and flags;
- `UiPackVerifiedIndex` containing validated header metadata, full `packSha256` and at most 32 refs;
- caller-owned `UiPackVerifyWorkspace` containing I/O scratch and candidate index;
- `ui_pack_verify`, `ui_pack_validate_publishable`, `ui_pack_find_entry`, `ui_pack_read_stored`.

`PUBLISHED_ONLY` rejects generation 0 inside `ui_pack_verify`. `FACTORY_UNPUBLISHED_ALLOWED` is used only by an explicit checked factory-B UI call site and is the sole verification path that may accept generation 0. `ui_pack_validate_publishable` always rejects generation 0 with `UI_PACK_SOURCE_GENERATION_INVALID`.

`ui_pack_store.h` owns no file handle, task, mutex, lease, catalog pointer or mutable static. P1.1 neither mounts nor opens a filesystem and does not define active/inactive selection.

## Python codec и deterministic fixtures

`tools/ui_pack_format.py` uses only Python standard library (`dataclasses`, `enum`, `hashlib`, `struct`, `binascii`, `platform`, `sys`, `zlib`). It owns:

- mirrored numeric constants/enums and checked-u32 helpers;
- canonical path/FNV validation;
- `encode_entry`, `build_pack`, `parse_pack_for_fixture_assertions`;
- canonical gzip member writer with manually fixed header/trailer and the exact level/method/wbits/memLevel/strategy tuple above;
- distinct `payload_sha256(pack[104:])` and `pack_sha256(pack)` helpers.

It does not read `data/`, Ace/npm, UI/raw manifests or write production artifacts.

`tools/generate_ui_pack_golden.py` accepts only explicit `--output-dir` or `--check`; no current-directory default. `--output-dir` writes the exact Python/zlib/DEFLATE provenance used for generation. `--check` validates the running toolchain against checked-in provenance before building in a temporary directory, requires exact relative file set, byte-compares every artifact and reports missing/extra/stale paths. Locale, directory enumeration and wall clock cannot affect output.

Minimum checked-in valid fixtures:

1. `ace-minimal.pack`: Ace kind/schema 0, zero required-Ace digest, one immutable canonical entry.
2. `ui-mixed.pack`: UI kind/schema 1, required Ace full SHA from fixture 1, non-GZIP and canonical GZIP entries covering zero and exactly one mutability bit; every non-GZIP entry has identical stored/expanded size.
3. `ui-unpublished.pack`: generation 0, structurally valid only under named factory policy, rejected as publishable.
4. `fnv-collision.pack`: both `costarring` and `liquid`, proving full-path lookup.

`golden-vectors.json` is compact UTF-8 with sorted keys, no BOM, one LF. It records fixture file SHA-256, header/entry decoded values, header CRC, payload/full/entry SHA, gzip expanded CRC/size, expected lookup results, expected symbolic+numeric error for invalid vectors and the exact P1.1 Python/zlib/DEFLATE provenance. It contains no host path, timestamp or locale-derived value.

## Behavioral и static test matrix

`tools/smoke_ui_pack_format.py` performs all checks without network:

- runs fixture generator `--check` twice, including exact Python/zlib provenance preflight, and compares directory/file bytes;
- imports Python codec and validates every valid/invalid vector;
- generates a temporary C++11 harness, compiles production headers with `-Wall -Wextra -Werror`, and runs the same vectors through memory `readAt` plus host SHA/gzip verify ops;
- compares C++ result/error/decoded metadata/full SHA to `golden-vectors.json` and Python result;
- fails setup explicitly if required host crypto/zlib development dependency is missing; no skip/pass fallback;
- compiles header standalone and asserts no Arduino include, heap API, exception, RTTI, STL owning container or packed/reinterpret wire cast.

Required success/failure vectors:

- every truncation length through header and every entry prefix/path/payload boundary;
- short/failed `readAt` at header, index, payload hash, stored hash and gzip reads;
- wrong magic/version/header size/count/kind/schema/reserved/index offset/total size/header CRC;
- valid `flags=0`, `GZIP`-only and zero/exactly-one mutability combinations; invalid unknown flags and editable+immutable; path length 0/48, invalid ASCII, leading/trailing/repeated slash, `.`/`..`, backslash, wrong hash, unsorted and duplicate paths;
- non-GZIP `expandedSize != storedSize`, including non-zero/zero boundary variants, expecting `UI_PACK_ENTRY_LAYOUT_INVALID` before every digest callback;
- u32 overflow in record end/stored end/index/payload counters; gap, overlap, reorder and trailing bytes;
- wrong payload SHA, stored SHA and explicit proof that full SHA cannot replace payload SHA;
- gzip wrong magic/method/flags/header, truncated deflate/trailer, stream error, extra member/trailing bytes, expanded overflow/size mismatch, trailer CRC and ISIZE mismatch;
- Ace pack with non-zero dependency, UI with zero/wrong expected Ace SHA;
- generation 0 UI success only under `FACTORY_UNPUBLISHED_ALLOWED`, direct `PUBLISHED_ONLY` failure and subsequent publishable failure; generation 0 Ace failure, generation 1/`UINT32_MAX` success, plus combined-invalid vectors proving schema precedes generation and generation precedes reserved/index/entry/digest failures;
- missing SHA `reset`/`update`/`finish` or gzip callback at step 1 expects `UI_PACK_VERIFY_OPS_MISSING`; fault injection makes each SHA callback fail independently at payload, stored-entry and full-pack stages and expects `UI_PACK_SHA_FAILED`, while a failing gzip callback expects `UI_PACK_GZIP_STREAM_INVALID`; each case proves first-failure precedence and unchanged output sentinels;
- hash collision exact lookup, missing path, and read range outside selected entry;
- output/result/index sentinels byte-stable for every failure.

Static integration checks require both headers in `static_analysis_sources.json`, exactly one Python pack encoder, no production include from A-10 files, and no `File`/LittleFS/NVS/OperationStore symbols in either P1.1 header.

## RAM, stack и flash budgets

- `UiPackEntryRef` target `24` bytes; `32 * 24 = 768` bytes.
- `UiPackVerifiedIndex` hard `static_assert <= 1024` bytes.
- `UiPackVerifyWorkspace` hard `static_assert <= 2048` bytes including 512-byte I/O chunk and candidate index; caller owns it as transient/global operation state, never an automatic local in deep call chains.
- Additional stack per reader function hard target `<=256` bytes; no recursion and no path-sized nested arrays. Host `-fstack-usage` records each function.
- Persistent mutable/static RAM in both headers: `0` bytes. No task, mutex, file handle or allocator.
- Inflate context/window is caller-owned transient memory and not inside persistent index/workspace.
- P1.1 headers are not included by firmware production units, поэтому firmware flash delta равен `0`.
- Python/fixtures не входят в LittleFS или firmware; производственный pack limit не определяется этим документом.

## Исторический порядок implementation

1. **Freeze/baseline** — wait for A-10 owner PASS; record hashes/diff of shared manifest/map files; verify target files absent. No code before this gate.
2. **Red tests and fixture schema** — add `golden-vectors.json` schema, Python unit cases and smoke skeleton that fails because codec/headers are absent.
3. **Python wire codec** — implement LE/CRC/FNV/path/checked arithmetic, pack assembly and exact canonical gzip parameters/provenance; generate valid vectors; verify two-run identity.
4. **C++ format primitives** — implement only `ui_pack_format.h`; compile standalone; cross-check constants/CRC/FNV/header/entry decoding against Python.
5. **Pure reader/store boundary** — implement `ui_pack_store.h`, workspace/candidate atomicity, dense layout and lookup without digest success shortcuts.
6. **Verification adapters in host harness** — connect required host SHA/gzip ops; cover payload/stored/full SHA and gzip trailer/expanded rules.
7. **Adversarial vectors** — generate semantic invalid packs with earlier integrity fields recomputed; close complete error/boundary matrix, failed-read injection and per-callback SHA/gzip fault injection.
8. **Manifest/map integration** — sorted static-analysis entries and new nodes only after all behavior tests pass; do not touch runtime files.
9. **Stabilization** — run targeted smoke, `smoke_ci_contract.py`, full smoke runner, header-only cppcheck scope, `git diff --check`; PlatformIO/buildfs не требовались для unreferenced Arduino-free foundation.
10. **Independent reviewer loop** — reviewer returns `PASS: no errors, no warnings` or exact findings; same owner fixes and repeats all targeted gates until PASS.

## Reviewer acceptance

P1.1 is accepted only when all are true:

- wire offsets/sizes/enums are explicit and cross-language identical; no packed cast;
- header exactly 104 bytes, entry prefix exactly 52 bytes, dense index/payload and total size exact;
- every addition is overflow-checked before arithmetic/read/cast;
- path syntax/order/duplicate/hash-collision behavior matches the contract;
- header CRC, payload SHA, stored SHA, full pack SHA and Ace dependency are distinct and tested;
- every non-GZIP entry proves `expandedSize == storedSize`; every GZIP entry is fully streaming-verified, including expanded size, trailer CRC/ISIZE and exact single-member consumption;
- canonical gzip parameters and Python/zlib versions are exact P1.1 provenance and fixture identity inputs;
- verification cannot succeed with missing/failing SHA or gzip ops, and every callback failure has an exact cross-language error/precedence assertion;
- generation 0 succeeds only through the named factory-B UI policy and is rejected by direct published verification and publishability validation;
- no heap, `String`, Arduino/FS/NVS/OperationStore, task, mutex, fallback or whole-pack materialization exists in production headers;
- output is unchanged on failure and source read failures are observable;
- Python generation is deterministic and `--check` rejects stale/missing/extra fixtures;
- golden valid/invalid vectors pass independently in Python and compiled C++11;
- A-10 files and runtime UI/filesystem code are untouched;
- map/manifest are synchronized and reviewer reports exact `PASS: no errors, no warnings`.

## Текущая граница

- P1.1 остаётся изолированным, неиспользуемым wire-format/test foundation.
- Проверенные A/B manifest-данные сохраняются как справочные и тестовые данные.
- P1.2, production generator/importer, локальный Ace, A/B pack runtime, partition
  migration и browser gate отменены решением от 2026-07-12.
- Любое возвращение к production pack требует нового явного решения пользователя
  и повторного расчёта по реально активной partition table.

P1.1 сохраняется без production callers; его удаление текущим CDN-решением не предусмотрено.
