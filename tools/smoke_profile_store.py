#!/usr/bin/env python3
"""A-12 P1 profile blob, persistence, migration, and caller contract."""

from __future__ import annotations

import pathlib
import re
import subprocess
import tempfile
import textwrap

from smoke_helpers import extract_function_body, strip_cpp_comments


ROOT = pathlib.Path(__file__).resolve().parents[1]
PROFILE_HEADER = ROOT / "profile_store.h"
PROFILE_SETUP_FIELDS_HEADER = ROOT / "profile_setup_fields.h"
NVS = ROOT / "NVS_Manager.ino"
PROFILE_DECODE_FIELDS = ROOT / "profile_decode_fields.h"
SAMOVAR = ROOT / "Samovar.ino"
API = ROOT / "samovar_api.h"

errors: list[str] = []


def require(condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def parse_profile_field_rows(source: str) -> list[tuple[str, str, str, str, str]]:
    """Разбирает строки SAMOVAR_PROFILE_FIELDS(X) из profile_setup_fields.h на
    кортежи (kind, name, size, default, scope). Аргументы X(...) режем по
    запятым с учётом вложенных скобок — DEFAULT содержит вызовы вида
    memset(candidate.SteamAdress, 255, sizeof(candidate.SteamAdress)), и
    наивный split(',') разрезал бы такой вызов на части."""
    anchor = "#define SAMOVAR_PROFILE_FIELDS(X)"
    start = source.index(anchor)
    body = source[start + len(anchor):]
    rows: list[tuple[str, str, str, str, str]] = []
    pos = 0
    while True:
        open_paren = body.find("X(", pos)
        if open_paren < 0:
            break
        depth = 0
        i = open_paren + 1
        args_start = i + 1
        while True:
            char = body[i]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        row_text = body[args_start:i]
        parts: list[str] = []
        depth = 0
        last = 0
        for index, char in enumerate(row_text):
            if char in "([":
                depth += 1
            elif char in ")]":
                depth -= 1
            elif char == "," and depth == 0:
                parts.append(row_text[last:index].strip())
                last = index + 1
        parts.append(row_text[last:].strip())
        if len(parts) != 5:
            raise ValueError(f"malformed SAMOVAR_PROFILE_FIELDS row: X({row_text})")
        rows.append((parts[0], parts[1], parts[2], parts[3], parts[4]))
        pos = i + 1
    return rows


def ordered(source: str, tokens: list[str], label: str) -> None:
    def normalize(value: str) -> str:
        value = re.sub(r"\s+", " ", value)
        value = re.sub(r"\(\s+", "(", value)
        return re.sub(r"\s+\)", ")", value)

    source = normalize(source)
    position = -1
    for token in tokens:
        normalized_token = normalize(token)
        next_position = source.find(normalized_token, position + 1)
        if next_position < 0:
            errors.append(f"{label}: missing or out-of-order token {token!r}")
            return
        position = next_position


def definition(source: str, token: str) -> str:
    start = source.find(token)
    if start < 0:
        raise ValueError(f"definition not found: {token}")
    end = source.find("};", start)
    if end < 0:
        raise ValueError(f"definition is not closed: {token}")
    return source[start : end + 2]


def wrapped_function(source: str, token: str, signature: str) -> str:
    offset = 0
    while True:
        start = source.find(token, offset)
        if start < 0:
            raise ValueError(f"function definition not found: {token}")
        brace = source.find("{", start)
        semicolon = source.find(";", start)
        if brace >= 0 and (semicolon < 0 or brace < semicolon):
            return signature + " {\n" + extract_function_body(
                source, source[start:brace]
            ) + "\n}\n"
        offset = semicolon + 1


def compile_and_run_harness(
    name: str, harness: str, defines: list[str] | None = None
) -> None:
    with tempfile.TemporaryDirectory(prefix=f"samovar-{name}-") as tmp:
        source = pathlib.Path(tmp) / f"{name}.cpp"
        binary = pathlib.Path(tmp) / name
        source.write_text(harness, encoding="utf-8")
        compile_result = subprocess.run(
            [
                "g++",
                "-std=c++11",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-I",
                str(ROOT),
                *(defines or []),
                str(source),
                "-o",
                str(binary),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        if compile_result.returncode != 0:
            errors.append(f"{name} host compile failed:\n" + compile_result.stderr)
            return
        run_result = subprocess.run(
            [str(binary)], text=True, capture_output=True, check=False
        )
        if run_result.returncode != 0:
            errors.append(f"{name} host behavior failed:\n" + run_result.stderr)


if not PROFILE_HEADER.exists():
    errors.append("profile_store.h is missing")
else:
    harness = textwrap.dedent(
        r'''
        #include <assert.h>
        #include <stdint.h>
        #include <string.h>
        #include "profile_store.h"

        using Codec = ProfileBlobCodec<516, 1>;

        int main() {
          static const uint8_t vector[] = {'1','2','3','4','5','6','7','8','9'};
          assert(profile_crc32_iso_hdlc(vector, sizeof(vector)) == 0xCBF43926U);
          static_assert(Codec::HEADER_SIZE == 10, "unexpected header size");
          static_assert(Codec::BLOB_SIZE == 530, "unexpected blob size");

          uint8_t payload[Codec::PAYLOAD_SIZE] = {};
          CanonicalProfileWriter<Codec::PAYLOAD_SIZE> writer(payload);
          assert(writer.put_u8(0x5A));
          assert(writer.put_u16(0x1234));
          assert(writer.put_u32(0x89ABCDEFU));
          assert(writer.put_i32(-123456));
          assert(writer.put_float(12.5f));
          assert(writer.put_bool(true));
          const uint8_t bytes[] = {1, 2, 3, 4};
          assert(writer.put_bytes(bytes, sizeof(bytes)));
          assert(writer.finish());

          Codec::Blob first{};
          Codec::Blob second{};
          Codec::encode(payload, first);
          Codec::encode(payload, second);
          assert(memcmp(first.bytes, second.bytes, Codec::BLOB_SIZE) == 0);
          assert(memcmp(first.bytes, "SMPF", 4) == 0);
          assert(first.bytes[4] == 1 && first.bytes[5] == 0);
          assert(first.bytes[6] == 4 && first.bytes[7] == 2 &&
                 first.bytes[8] == 0 && first.bytes[9] == 0);

          uint8_t decoded[Codec::PAYLOAD_SIZE] = {};
          assert(Codec::decode(first.bytes, Codec::BLOB_SIZE, decoded) == PROFILE_CODEC_OK);
          assert(memcmp(payload, decoded, sizeof(payload)) == 0);
          CanonicalProfileReader<Codec::PAYLOAD_SIZE> reader(decoded);
          uint8_t u8 = 0;
          uint16_t u16 = 0;
          uint32_t u32 = 0;
          int32_t i32 = 0;
          float f32 = 0;
          bool boolean = false;
          uint8_t readBytes[4] = {};
          assert(reader.get_u8(u8) && u8 == 0x5A);
          assert(reader.get_u16(u16) && u16 == 0x1234);
          assert(reader.get_u32(u32) && u32 == 0x89ABCDEFU);
          assert(reader.get_i32(i32) && i32 == -123456);
          assert(reader.get_float(f32) && f32 == 12.5f);
          assert(reader.get_bool(boolean) && boolean);
          assert(reader.get_bytes(readBytes, sizeof(readBytes)));
          assert(memcmp(readBytes, bytes, sizeof(bytes)) == 0);
          assert(reader.finish());
          assert(Codec::decode(first.bytes, Codec::BLOB_SIZE - 1, decoded) ==
                 PROFILE_CODEC_STORED_SIZE);
          uint8_t oversized[Codec::BLOB_SIZE + 1] = {};
          memcpy(oversized, first.bytes, Codec::BLOB_SIZE);
          assert(Codec::decode(oversized, sizeof(oversized), decoded) ==
                 PROFILE_CODEC_STORED_SIZE);

          for (size_t index = 0; index < Codec::BLOB_SIZE; index++) {
            Codec::Blob mutated = first;
            mutated.bytes[index] ^= 0x01;
            ProfileCodecResult result = Codec::decode(
                mutated.bytes, Codec::BLOB_SIZE, decoded);
            if (index < 4) assert(result == PROFILE_CODEC_MAGIC);
            else if (index < 6) assert(result == PROFILE_CODEC_VERSION);
            else if (index < 10) assert(result == PROFILE_CODEC_PAYLOAD_SIZE);
            else assert(result == PROFILE_CODEC_CRC);
          }
          return 0;
        }
        '''
    )
    compile_and_run_harness("profile_codec", harness)

nvs_text = strip_cpp_comments(
    NVS.read_text(encoding="utf-8") + "\n" + PROFILE_DECODE_FIELDS.read_text(encoding="utf-8")
)
profile_header_text = strip_cpp_comments(PROFILE_HEADER.read_text(encoding="utf-8"))
samovar_text = strip_cpp_comments(SAMOVAR.read_text(encoding="utf-8"))
api_text = strip_cpp_comments(API.read_text(encoding="utf-8"))
beer_text = strip_cpp_comments((ROOT / "beer.h").read_text(encoding="utf-8"))
samovar_header_text = strip_cpp_comments(
    (ROOT / "Samovar.h").read_text(encoding="utf-8")
)
numeric_text = strip_cpp_comments(
    (ROOT / "control_numeric_input.h").read_text(encoding="utf-8")
)
require(
    "ProfileValueResult" not in profile_header_text,
    "generic profile codec leaks the NVS transport tri-state",
)
for token in [
    "enum ProfileValueResult",
    "PROFILE_VALUE_FOUND",
    "PROFILE_VALUE_ABSENT",
    "PROFILE_VALUE_ERROR",
]:
    require(token in nvs_text, f"NVS tri-state contract missing {token}")


def function_body(source: str, signature: str) -> str:
    try:
        return extract_function_body(source, signature)
    except ValueError:
        return ""


production_setup_body = function_body(samovar_text, "void setup()")
boot_block_start = production_setup_body.find("SetupEEPROM startupProfile{}")
boot_block_end_token = 'print_nvs_stats("after config load");'
boot_block_end = production_setup_body.find(boot_block_end_token, boot_block_start)
require(
    boot_block_start >= 0 and boot_block_end >= 0,
    "production setup profile decision block is missing",
)
boot_profile_block = production_setup_body[
    boot_block_start : boot_block_end + len(boot_block_end_token)
]

# Извлечённый блок лечит недоверенное R через trusted_heater_resistance(). Тянем в
# харнесс НАСТОЯЩИЕ границы и тело из control_numeric_input.h: заглушка проверяла бы
# сама себя, а не то, что реально уедет на устройство.
heater_trust_constants = re.findall(
    r"^static const float CONTROL_HEATER_R_\w+ = [0-9.]+f;$",
    numeric_text,
    re.MULTILINE,
)
require(
    len(heater_trust_constants) == 3,
    "control_numeric_input.h: ожидались MIN/MAX/DEFAULT для доверенного R",
)
# __attribute__((unused)) снимает маску -Werror=unused-function: без него удаление
# лечения из Samovar.ino валит СБОРКУ ("defined but not used"), а не проверку, и
# сообщение показывает на обвязку теста вместо пропавшего поведения.
heater_trust_definitions = "\n".join(heater_trust_constants) + "\n" + wrapped_function(
    numeric_text,
    "trusted_heater_resistance",
    "__attribute__((unused)) static float trusted_heater_resistance(float heaterResistance)",
)


setup_definition = definition(samovar_header_text, "struct SetupEEPROM")
setup_fields = re.findall(
    r"^\s*(?:uint8_t|uint16_t|float|int|bool|char)\s+"
    r"([A-Za-z_]\w*)\s*(?:\[[^\]]+\])?\s*;",
    setup_definition,
    re.MULTILINE,
)
require(len(setup_fields) == 74, "SetupEEPROM field inventory changed")
padding_marks = "\n".join(
    "  mark_field(occupied, offsetof(SetupEEPROM, "
    f"{field}), sizeof(((SetupEEPROM*)0)->{field}));"
    for field in setup_fields
)

nvs_harness = (
    textwrap.dedent(
        r'''
        #include <assert.h>
        #include <math.h>
        #include <stddef.h>
        #include <stdint.h>
        #include <stdio.h>
        #include <string.h>

        #include <algorithm>
        #include <limits>
        #include <string>
        #include <vector>

        #include "profile_store.h"
        #include "profile_setup_fields.h"

        typedef int esp_err_t;
        typedef int nvs_handle_t;
        typedef int nvs_open_mode_t;
        static const esp_err_t ESP_OK = 0;
        static const esp_err_t ESP_FAIL = 1;
        static const esp_err_t ESP_ERR_NVS_NOT_FOUND = 2;
        static const esp_err_t ESP_ERR_NVS_TYPE_MISMATCH = 3;
        static const nvs_open_mode_t NVS_READONLY = 0;
        '''
    )
    + "\n"
    + definition(samovar_header_text, "enum SAMOVAR_MODE")
    + "\n"
    + setup_definition
    + "\n"
    + textwrap.dedent(
        r'''
        // A-16/T3: SIZE-колонка в profile_setup_fields.h раньше была метаданными
        // без проверки (ей никто не пользовался). Здесь она статически, на этапе
        // компиляции, сверяется с реальной шириной поля в SetupEEPROM через тот
        // же X-macro список — без ручного дублирования имён полей.
        #define SAMOVAR_FIELD_SIZE_CHECK(kind, name, size, deflt, scope) \
            static_assert((size) == sizeof(((SetupEEPROM*)0)->name), \
                          "profile_setup_fields.h SIZE column wrong for " #name);
        SAMOVAR_PROFILE_FIELDS(SAMOVAR_FIELD_SIZE_CHECK)
        #undef SAMOVAR_FIELD_SIZE_CHECK
        '''
    )
    + "\n"
    + definition(api_text, "enum PersistResult")
    + "\n"
    + definition(api_text, "enum ProfileLoadResult")
    + "\n"
    + definition(nvs_text, "enum ProfileValueResult")
    + "\n"
    + textwrap.dedent(
        r'''
        static const char* const SAMOVAR_PROFILE_NAMESPACE = "sam_cfg";
        static const char* const SAMOVAR_PROFILE_KEY = "profile";
        static const uint16_t SAMOVAR_PROFILE_FORMAT_VERSION = 2;
        static const size_t SAMOVAR_PROFILE_PAYLOAD_SIZE_V1 = 516;
        static const size_t SAMOVAR_PROFILE_CANONICAL_BYTES_V1 = 515;
        static const size_t SAMOVAR_PROFILE_PAYLOAD_SIZE_V2 = 520;
        static const size_t SAMOVAR_PROFILE_CANONICAL_BYTES_V2 = 518;

        using ProfileCodec = ProfileBlobCodec<
            SAMOVAR_PROFILE_PAYLOAD_SIZE_V2,
            SAMOVAR_PROFILE_FORMAT_VERSION>;
        using LegacyProfileCodec = ProfileBlobCodec<
            SAMOVAR_PROFILE_PAYLOAD_SIZE_V1,
            1>;

        static_assert(sizeof(SetupEEPROM) == 536, "host ABI drift");
        static_assert(ProfileCodec::BLOB_SIZE == 534, "v2 blob size drift");
        static_assert(LegacyProfileCodec::BLOB_SIZE == 530, "v1 blob size drift");

        static const float DEFAULT_DIST_TEMP = 98.0f;
        static const uint16_t STEPPER_STEP_ML = 100;
        static const uint16_t I2C_STEPPER_STEP_ML_DEFAULT = 200;
        // Зеркало NBK_*_DEFAULT из nbk.h (Н1, SOLUTIONS_2026-08-24.md): харнесс
        // собирает profile_setup_fields.h изолированно, без nbk.h, поэтому
        // константы дублируются здесь по тому же приёму, что DEFAULT_DIST_TEMP выше.
        static const float NBK_COLUMN_INERTIA_DEFAULT = 180;
        static const float NBK_DT_DEFAULT = 0.5;
        static const float NBK_DM_DEFAULT = 100;
        static const float NBK_DP_DEFAULT = 0.5;
        static const float NBK_TP_DEFAULT = 81;
        static const float NBK_OVERFLOW_PRESSURE_DEFAULT = 40;
        static const float NBK_TN_DEFAULT = 98.5;

        template <size_t Size>
        static void copyStringSafe(char (&destination)[Size], const char* source) {
          strncpy(destination, source, Size - 1);
          destination[Size - 1] = '\0';
        }

        enum FakeMode {
          FAKE_CURRENT,
          FAKE_LEGACY,
          FAKE_MIGRATION,
        };

        enum BlobMutation {
          MUTATE_NONE,
          MUTATE_CRC,
          MUTATE_VALID_DIFFERENT,
          MUTATE_INVALID_BOOL,
          MUTATE_RESERVED,
        };

        enum LegacyBehavior {
          LEGACY_ABSENT,
          LEGACY_FOUND,
          LEGACY_ERROR,
          LEGACY_READ_ERROR,
          LEGACY_WRONG_SIZE,
        };

        struct FakeNamespace {
          std::string name;
          LegacyBehavior flagBehavior;
          uint8_t flag;
          LegacyBehavior kpBehavior;
          float kp;
          LegacyBehavior lastModeBehavior;
          uint8_t lastMode;
        };

        struct FakeNvsState {
          FakeMode mode;
          bool writerBegin;
          size_t writeResult;
          esp_err_t openError;
          esp_err_t sizeError;
          esp_err_t readError;
          size_t sizeReported;
          size_t readReported;
          BlobMutation mutation;
          LegacyBehavior flagBehavior;
          uint8_t flag;
          LegacyBehavior kpBehavior;
          float kp;
          int writes;
          int opens;
          int closes;
          int blobQueries;
          int blobReads;
          SetupEEPROM eepromValue;
          int eepromBegins;
          int eepromGets;
          int eepromEnds;
          float ramKpAtWrite;
          int legacyCleanupCalls;
          int writesAtCleanup;
          int initMarkers;
          bool bootDegraded;
          std::string bootDegradedReason;
          std::string degradedStage;
          std::string serialLog;
          std::vector<uint8_t> blob;
          std::vector<FakeNamespace> namespaces;
          std::vector<std::string> openedNamespaces;
        };

        static SetupEEPROM SamSetup{};
        static FakeNvsState fake;

        static void reset_fake(FakeMode mode = FAKE_CURRENT) {
          fake.mode = mode;
          fake.writerBegin = true;
          fake.writeResult = std::numeric_limits<size_t>::max();
          fake.openError = ESP_OK;
          fake.sizeError = ESP_OK;
          fake.readError = ESP_OK;
          fake.sizeReported = std::numeric_limits<size_t>::max();
          fake.readReported = std::numeric_limits<size_t>::max();
          fake.mutation = MUTATE_NONE;
          fake.flagBehavior = LEGACY_ABSENT;
          fake.flag = 2;
          fake.kpBehavior = LEGACY_ABSENT;
          fake.kp = 0;
          fake.writes = 0;
          fake.opens = 0;
          fake.closes = 0;
          fake.blobQueries = 0;
          fake.blobReads = 0;
          fake.eepromValue = {};
          fake.eepromValue.flag = 255;
          fake.eepromBegins = 0;
          fake.eepromGets = 0;
          fake.eepromEnds = 0;
          fake.ramKpAtWrite = 0;
          fake.legacyCleanupCalls = 0;
          fake.writesAtCleanup = -1;
          fake.initMarkers = 0;
          fake.bootDegraded = false;
          fake.bootDegradedReason.clear();
          fake.degradedStage.clear();
          fake.serialLog.clear();
          fake.blob.clear();
          fake.namespaces.clear();
          fake.openedNamespaces.clear();
        }

        static FakeNamespace* find_namespace(const char* name) {
          for (size_t index = 0; index < fake.namespaces.size(); index++) {
            if (fake.namespaces[index].name == name) {
              return &fake.namespaces[index];
            }
          }
          return nullptr;
        }

        static FakeNamespace& add_namespace(const char* name) {
          FakeNamespace* existing = find_namespace(name);
          if (existing) return *existing;
          FakeNamespace entry{};
          entry.name = name;
          entry.flagBehavior = LEGACY_ABSENT;
          entry.flag = 2;
          entry.kpBehavior = LEGACY_ABSENT;
          entry.kp = 0;
          entry.lastModeBehavior = LEGACY_ABSENT;
          entry.lastMode = uint8_t(SAMOVAR_RECTIFICATION_MODE);
          fake.namespaces.push_back(entry);
          return fake.namespaces.back();
        }

        static FakeNamespace& namespace_for_handle(nvs_handle_t handle) {
          assert(handle > 0 && size_t(handle) <= fake.namespaces.size());
          return fake.namespaces[size_t(handle) - 1];
        }

        static int opened_count(const char* name) {
          return int(std::count(
              fake.openedNamespaces.begin(), fake.openedNamespaces.end(), name));
        }

        static void write_crc(std::vector<uint8_t>& blob) {
          assert(blob.size() == ProfileCodec::BLOB_SIZE);
          const uint32_t crc = profile_crc32_iso_hdlc(
              blob.data(), ProfileCodec::HEADER_SIZE + ProfileCodec::PAYLOAD_SIZE);
          const size_t offset = ProfileCodec::HEADER_SIZE + ProfileCodec::PAYLOAD_SIZE;
          blob[offset] = uint8_t(crc);
          blob[offset + 1] = uint8_t(crc >> 8U);
          blob[offset + 2] = uint8_t(crc >> 16U);
          blob[offset + 3] = uint8_t(crc >> 24U);
        }

        static void mutate_written_blob() {
          if (fake.mutation == MUTATE_NONE) return;
          assert(fake.blob.size() == ProfileCodec::BLOB_SIZE);
          if (fake.mutation == MUTATE_CRC) {
            fake.blob[ProfileCodec::HEADER_SIZE] ^= 1U;
            return;
          }
          if (fake.mutation == MUTATE_VALID_DIFFERENT) {
            fake.blob[ProfileCodec::HEADER_SIZE] ^= 1U;
          } else if (fake.mutation == MUTATE_INVALID_BOOL) {
            fake.blob[ProfileCodec::HEADER_SIZE + 35] = 2U;
          } else {
            fake.blob[ProfileCodec::HEADER_SIZE +
                      SAMOVAR_PROFILE_CANONICAL_BYTES_V2] = 1U;
          }
          write_crc(fake.blob);
        }

        static esp_err_t read_current_blob(void* value, size_t* size) {
          if (!value) {
            fake.blobQueries++;
            if (fake.sizeError != ESP_OK) return fake.sizeError;
            if (fake.blob.empty()) return ESP_ERR_NVS_NOT_FOUND;
            *size = fake.sizeReported == std::numeric_limits<size_t>::max()
                ? fake.blob.size()
                : fake.sizeReported;
            return ESP_OK;
          }
          fake.blobReads++;
          if (fake.readError != ESP_OK) return fake.readError;
          const size_t copied = std::min(*size, fake.blob.size());
          if (copied != 0) memcpy(value, fake.blob.data(), copied);
          *size = fake.readReported == std::numeric_limits<size_t>::max()
              ? fake.blob.size()
              : fake.readReported;
          return ESP_OK;
        }

        class FakeEEPROM {
         public:
          bool begin(size_t size) {
            assert(size == sizeof(SetupEEPROM));
            fake.eepromBegins++;
            return true;
          }

          void get(int address, SetupEEPROM& value) {
            assert(address == 0);
            fake.eepromGets++;
            value = fake.eepromValue;
          }

          void end() {
            fake.eepromEnds++;
          }
        };

        static FakeEEPROM EEPROM;

        class Preferences {
         public:
          bool begin(const char* namespaceName, bool readOnly) {
            assert(strcmp(namespaceName, SAMOVAR_PROFILE_NAMESPACE) == 0);
            assert(!readOnly);
            if (!fake.writerBegin) return false;
            if (fake.mode == FAKE_MIGRATION) add_namespace(namespaceName);
            return true;
          }

          size_t putBytes(const char* key, const void* value, size_t size) {
            assert(strcmp(key, SAMOVAR_PROFILE_KEY) == 0);
            fake.writes++;
            fake.ramKpAtWrite = SamSetup.Kp;
            fake.blob.assign(
                static_cast<const uint8_t*>(value),
                static_cast<const uint8_t*>(value) + size);
            mutate_written_blob();
            return fake.writeResult == std::numeric_limits<size_t>::max()
                ? size
                : fake.writeResult;
          }

          void end() {}
        };

        static esp_err_t nvs_open(
            const char* namespaceName,
            nvs_open_mode_t mode,
            nvs_handle_t* handle) {
          assert(namespaceName != nullptr);
          assert(mode == NVS_READONLY);
          fake.opens++;
          if (fake.mode == FAKE_MIGRATION) {
            fake.openedNamespaces.push_back(namespaceName);
            for (size_t index = 0; index < fake.namespaces.size(); index++) {
              FakeNamespace& entry = fake.namespaces[index];
              if (entry.name != namespaceName) continue;
              *handle = nvs_handle_t(index + 1);
              return ESP_OK;
            }
            return ESP_ERR_NVS_NOT_FOUND;
          }
          if (fake.openError != ESP_OK) return fake.openError;
          *handle = 1;
          return ESP_OK;
        }

        static void nvs_close(nvs_handle_t handle) {
          if (fake.mode == FAKE_MIGRATION) {
            (void)namespace_for_handle(handle);
          } else {
            assert(handle == 1);
          }
          fake.closes++;
        }

        static esp_err_t nvs_get_blob(
            nvs_handle_t handle,
            const char* key,
            void* value,
            size_t* size) {
          assert(size != nullptr);
          if (fake.mode == FAKE_MIGRATION) {
            FakeNamespace& entry = namespace_for_handle(handle);
            if (strcmp(key, SAMOVAR_PROFILE_KEY) == 0 &&
                entry.name == SAMOVAR_PROFILE_NAMESPACE) {
              return read_current_blob(value, size);
            }
            if (strcmp(key, "Kp") != 0) return ESP_ERR_NVS_NOT_FOUND;
            if (entry.kpBehavior == LEGACY_ABSENT) return ESP_ERR_NVS_NOT_FOUND;
            if (entry.kpBehavior == LEGACY_ERROR) return ESP_ERR_NVS_TYPE_MISMATCH;
            if (!value) {
              *size = entry.kpBehavior == LEGACY_WRONG_SIZE ? 3 : sizeof(float);
              return ESP_OK;
            }
            if (entry.kpBehavior == LEGACY_READ_ERROR) return ESP_FAIL;
            memcpy(value, &entry.kp, sizeof(entry.kp));
            *size = sizeof(entry.kp);
            return ESP_OK;
          }
          assert(handle == 1);
          if (fake.mode == FAKE_LEGACY && strcmp(key, "Kp") == 0) {
            if (fake.kpBehavior == LEGACY_ABSENT) return ESP_ERR_NVS_NOT_FOUND;
            if (fake.kpBehavior == LEGACY_ERROR) return ESP_ERR_NVS_TYPE_MISMATCH;
            if (!value) {
              *size = fake.kpBehavior == LEGACY_WRONG_SIZE ? 3 : sizeof(float);
              return ESP_OK;
            }
            if (fake.kpBehavior == LEGACY_READ_ERROR) return ESP_FAIL;
            memcpy(value, &fake.kp, sizeof(fake.kp));
            *size = sizeof(fake.kp);
            return ESP_OK;
          }
          if (fake.mode == FAKE_LEGACY) return ESP_ERR_NVS_NOT_FOUND;
          assert(strcmp(key, SAMOVAR_PROFILE_KEY) == 0);
          return read_current_blob(value, size);
        }

        static esp_err_t nvs_get_u8(
            nvs_handle_t handle,
            const char* key,
            uint8_t* value) {
          if (fake.mode == FAKE_MIGRATION) {
            FakeNamespace& entry = namespace_for_handle(handle);
            LegacyBehavior behavior = LEGACY_ABSENT;
            uint8_t stored = 0;
            if (strcmp(key, "flag") == 0) {
              behavior = entry.flagBehavior;
              stored = entry.flag;
            } else if (strcmp(key, "last_mode") == 0) {
              behavior = entry.lastModeBehavior;
              stored = entry.lastMode;
            }
            if (behavior == LEGACY_ABSENT) return ESP_ERR_NVS_NOT_FOUND;
            if (behavior != LEGACY_FOUND) return ESP_ERR_NVS_TYPE_MISMATCH;
            *value = stored;
            return ESP_OK;
          }
          assert(handle == 1);
          if (fake.mode != FAKE_LEGACY || strcmp(key, "flag") != 0) {
            return ESP_ERR_NVS_NOT_FOUND;
          }
          if (fake.flagBehavior == LEGACY_ABSENT) return ESP_ERR_NVS_NOT_FOUND;
          if (fake.flagBehavior != LEGACY_FOUND) return ESP_ERR_NVS_TYPE_MISMATCH;
          *value = fake.flag;
          return ESP_OK;
        }

        static esp_err_t nvs_get_u16(
            nvs_handle_t handle,
            const char* key,
            uint16_t* value) {
          (void)handle;
          (void)key;
          (void)value;
          return ESP_ERR_NVS_NOT_FOUND;
        }

        static esp_err_t nvs_get_str(
            nvs_handle_t handle,
            const char* key,
            char* value,
            size_t* size) {
          (void)handle;
          (void)key;
          (void)value;
          (void)size;
          return ESP_ERR_NVS_NOT_FOUND;
        }
        '''
    )
)

for token, signature in [
    (
        "encode_setup_payload(",
        "static bool encode_setup_payload(const SetupEEPROM& candidate, uint8_t* payload)",
    ),
    (
        "decode_setup_payload_fields(",
        "template <size_t PayloadSize>\nstatic bool decode_setup_payload_fields(CanonicalProfileReader<PayloadSize>& reader, SetupEEPROM& decoded)",
    ),
    (
        "decode_setup_payload_v2only_fields(",
        "template <size_t PayloadSize>\nstatic bool decode_setup_payload_v2only_fields(CanonicalProfileReader<PayloadSize>& reader, SetupEEPROM& decoded)",
    ),
    (
        "decode_setup_payload(",
        "static bool decode_setup_payload(const uint8_t* payload, SetupEEPROM& candidate)",
    ),
    (
        "decode_setup_payload_v1(",
        "static bool decode_setup_payload_v1(const uint8_t* payload, SetupEEPROM& candidate)",
    ),
    (
        "nvs_value_result(",
        "static uint8_t nvs_value_result(esp_err_t error)",
    ),
    (
        "nvs_blob_size(",
        "static uint8_t nvs_blob_size(nvs_handle_t handle, const char* key, size_t& size)",
    ),
    (
        "nvs_read_blob(",
        "static uint8_t nvs_read_blob(nvs_handle_t handle, const char* key, void* value, size_t& size)",
    ),
    (
        "nvs_read_u8(",
        "static uint8_t nvs_read_u8(nvs_handle_t handle, const char* key, uint8_t& value)",
    ),
    (
        "nvs_read_u16(",
        "static uint8_t nvs_read_u16(nvs_handle_t handle, const char* key, uint16_t& value)",
    ),
    (
        "nvs_read_bool(",
        "static uint8_t nvs_read_bool(nvs_handle_t handle, const char* key, bool& value)",
    ),
    (
        "nvs_read_float(",
        "static uint8_t nvs_read_float(nvs_handle_t handle, const char* key, float& value)",
    ),
    (
        "nvs_read_bytes(",
        "static uint8_t nvs_read_bytes(nvs_handle_t handle, const char* key, uint8_t* value, size_t expectedSize)",
    ),
    (
        "nvs_read_string(",
        "static uint8_t nvs_read_string(nvs_handle_t handle, const char* key, char* value, size_t capacity)",
    ),
    (
        "persist_codec_result(",
        "static PersistResult persist_codec_result(ProfileCodecResult result)",
    ),
    (
        "load_codec_result(",
        "static ProfileLoadResult load_codec_result(ProfileCodecResult result)",
    ),
    (
        "persist_result_code(",
        "const char* persist_result_code(PersistResult result)",
    ),
    (
        "profile_load_result_code(",
        "const char* profile_load_result_code(ProfileLoadResult result)",
    ),
    (
        "set_default_setup_profile(",
        "void set_default_setup_profile(SetupEEPROM& candidate)",
    ),
    (
        "save_profile_nvs(",
        "PersistResult save_profile_nvs(const SetupEEPROM& candidate)",
    ),
    (
        "load_profile_nvs(",
        "ProfileLoadResult load_profile_nvs(SetupEEPROM& candidate)",
    ),
    (
        "load_legacy_profile_namespace(",
        "static ProfileLoadResult load_legacy_profile_namespace(const char* namespaceName, uint8_t mode, SetupEEPROM& candidate)",
    ),
    (
        "legacy_profile_namespace_by_mode(",
        "static const char* legacy_profile_namespace_by_mode(uint8_t mode)",
    ),
    (
        "read_legacy_last_mode(",
        "static void read_legacy_last_mode(uint8_t& mode)",
    ),
    (
        "migrate_from_eeprom(",
        "ProfileLoadResult migrate_from_eeprom(SetupEEPROM& candidate)",
    ),
]:
    nvs_harness += "\n" + wrapped_function(nvs_text, token, signature)

nvs_harness += textwrap.dedent(
    r'''
    // Зеркало production report_degraded_boot(): fail-open, загрузка НЕ останавливается,
    // только копится факт/причина деградации (см. Samovar.ino).
    static void report_degraded_boot(const char* stage, const char* error) {
      assert(stage != nullptr && error != nullptr);
      const std::string reason = std::string(stage) + ": " + std::string(error);
      if (fake.bootDegraded) {
        fake.bootDegradedReason += "; ";
        fake.bootDegradedReason += reason;
      } else {
        fake.bootDegraded = true;
        fake.bootDegradedReason = reason;
      }
      fake.degradedStage = stage;
    }

    static void print_nvs_stats(const char* context) {
      assert(strcmp(context, "after config load") == 0);
      fake.initMarkers++;
    }

    // Извлечённый блок теперь вызывает apply_loaded_relay_polarity_off() сразу после
    // SamSetup = startupProfile (см. Samovar.ino). Этот тест проверяет только решение
    // о загрузке/миграции/дефолтах профиля, а не физические уровни на пинах реле —
    // GPIO-побочный эффект здесь не нужен, поэтому мок-заглушка.
    static void apply_loaded_relay_polarity_off() {}

    // Блок теперь заканчивается startup-задержкой (перенесена сюда, чтобы не удлинять
    // окно неверной полярности реле, см. Samovar.ino) - заглушки, без реального FreeRTOS.
    static const int portTICK_PERIOD_MS = 1;
    static void vTaskDelay(int) {}

    // Стирание legacy-остатков (сам его механизм проверяет
    // smoke_nvs_legacy_cleanup_contract.py). Здесь важно только УСЛОВИЕ вызова:
    // очистка допустима исключительно после миграции с успешной записью нового
    // профиля, поэтому запоминаем и факт вызова, и число записей на этот момент.
    static void clear_migrated_legacy_profile_data() {
      fake.legacyCleanupCalls++;
      fake.writesAtCleanup = fake.writes;
    }

    // Извлечённый блок предупреждает о недоверенном R через Serial. Копим текст, а не
    // глотаем: тест обязан доказать, что подмену видно, иначе она молчаливая.
    struct FakeSerial {
      void print(const char* value) { fake.serialLog += value; }
      void print(float value, int digits) {
        char buffer[64];
        snprintf(buffer, sizeof(buffer), "%.*f", digits, double(value));
        fake.serialLog += buffer;
      }
      void println(const char* value) { fake.serialLog += value; fake.serialLog += "\n"; }
    };
    // unused - по той же причине, что и у trusted_heater_resistance(): пропажу лога
    // обязан ловить assert на serialLog, а не жалоба компилятора на саму заглушку.
    __attribute__((unused)) static FakeSerial Serial;
    #define F(literal) (literal)
    static void nbk_preserve_startup_input_validity(float, float) {}

    // [T28] Извлечённый блок теперь зовёт sanitize_setup_profile_ranges() внутри
    // `if (migratedFromLegacy)` (см. Samovar.ino) - она чинит ~30 числовых полей
    // мигрированного профиля по тем же таблицам, что и форма /save. Эта проверка
    // тестирует РЕШЕНИЕ о загрузке/миграции/дефолтах профиля, а не диапазонную
    // починку саму по себе (её отдельно и поведенчески проверяет
    // tools/smoke_sanitize_setup_profile_ranges.py на настоящих
    // kSaveFloatFields/kSaveU8Fields) - здесь достаточно заглушки "ничего не чинить",
    // чтобы не менять уже существующие ожидания этого теста по report_degraded_boot.
    class String {
     public:
      String() {}
      String(const char* source) : value(source ? source : "") {}
      size_t length() const { return value.size(); }
      const char* c_str() const { return value.c_str(); }
      String operator+(const String& other) const { return String((value + other.value).c_str()); }
     private:
      std::string value;
    };
    static bool sanitize_setup_profile_ranges(SetupEEPROM&, String&) { return false; }
    ''') + heater_trust_definitions + textwrap.dedent(
    r'''

    static void run_boot_profile_decision() {
    ''') + boot_profile_block + textwrap.dedent(
    r'''
    }
    ''')

nvs_harness += (
    textwrap.dedent(
        r'''
        static SetupEEPROM sample_setup() {
          SetupEEPROM candidate{};
          candidate.flag = 2;
          candidate.DeltaSteamTemp = 0.25f;
          candidate.DeltaPipeTemp = -0.5f;
          candidate.StepperStepMl = 321;
          candidate.SetSteamTemp = 78.125f;
          candidate.UsePreccureCorrect = true;
          candidate.SteamDelay = 17;
          candidate.TimeZone = 3;
          candidate.HeaterResistant = 15.2f;
          candidate.LogPeriod = 5;
          memcpy(candidate.SteamColor, "#123456", 8);
          candidate.rele2 = true;
          candidate.SteamAdress[0] = 0x28;
          candidate.useautospeed = true;
          candidate.useDetector = true;
          candidate.autospeed = 75;
          memcpy(candidate.blynkauth, "auth", 5);
          memcpy(candidate.videourl, "https://example.invalid", 24);
          candidate.DistTemp = 97.5f;
          candidate.Mode = SAMOVAR_BEER_MODE;
          candidate.ACPAdress[7] = 0x42;
          candidate.Kp = 111.5f;
          candidate.Ki = 2.25f;
          candidate.Kd = 3.75f;
          candidate.ChangeProgramBuzzer = true;
          candidate.UseWS = true;
          candidate.BVolt = 220.0f;
          candidate.UseST = true;
          candidate.UseHLS = true;
          memcpy(candidate.tg_chat_id, "12345", 6);
          candidate.NbkDP = 4.5f;
          candidate.ColDiam = 2.0f;
          candidate.ColHeight = 0.5f;
          candidate.PackDens = 80;
          candidate.StepperStepMlI2C = 654;
          candidate.SuvidTemp = 62.5f;
          candidate.SuvidHoldMinutes = 37;
          return candidate;
        }

        static std::vector<uint8_t> encode_blob(const SetupEEPROM& candidate) {
          uint8_t payload[ProfileCodec::PAYLOAD_SIZE] = {};
          assert(encode_setup_payload(candidate, payload));
          ProfileCodec::Blob blob{};
          ProfileCodec::encode(payload, blob);
          return std::vector<uint8_t>(blob.bytes, blob.bytes + sizeof(blob.bytes));
        }

        static std::vector<uint8_t> encode_v1_blob(const SetupEEPROM& candidate) {
          uint8_t v2Payload[ProfileCodec::PAYLOAD_SIZE] = {};
          assert(encode_setup_payload(candidate, v2Payload));
          uint8_t v1Payload[LegacyProfileCodec::PAYLOAD_SIZE] = {};
          memcpy(
              v1Payload,
              v2Payload,
              SAMOVAR_PROFILE_CANONICAL_BYTES_V1);
          LegacyProfileCodec::Blob blob{};
          LegacyProfileCodec::encode(v1Payload, blob);
          return std::vector<uint8_t>(blob.bytes, blob.bytes + sizeof(blob.bytes));
        }

        static void seed_current_blob(const SetupEEPROM& candidate) {
          fake.blob = encode_blob(candidate);
        }

        // Обратная к encode_blob(): что реально уехало в NVS, а не что мы туда клали.
        static SetupEEPROM decode_written_blob() {
          uint8_t payload[ProfileCodec::PAYLOAD_SIZE] = {};
          assert(ProfileCodec::decode(fake.blob.data(), fake.blob.size(), payload) ==
                 PROFILE_CODEC_OK);
          SetupEEPROM restored{};
          assert(decode_setup_payload(payload, restored));
          return restored;
        }

        static void expect_load_failure(ProfileLoadResult expected) {
          SetupEEPROM destination;
          memset(&destination, 0xA5, sizeof(destination));
          uint8_t before[sizeof(destination)];
          memcpy(before, &destination, sizeof(before));
          assert(load_profile_nvs(destination) == expected);
          assert(memcmp(before, &destination, sizeof(before)) == 0);
        }

        static void test_save_fault_matrix() {
          const SetupEEPROM candidate = sample_setup();

          reset_fake();
          assert(save_profile_nvs(candidate) == PERSIST_OK);
          assert(fake.writes == 1 && fake.opens == 1);
          assert(fake.blobQueries == 1 && fake.blobReads == 1);

          reset_fake();
          fake.writerBegin = false;
          assert(save_profile_nvs(candidate) == PERSIST_OPEN_FAILED);
          assert(fake.writes == 0 && fake.opens == 0);

          reset_fake();
          fake.writeResult = 0;
          assert(save_profile_nvs(candidate) == PERSIST_WRITE_FAILED);
          assert(fake.writes == 1 && fake.opens == 0);

          reset_fake();
          fake.writeResult = ProfileCodec::BLOB_SIZE - 1;
          assert(save_profile_nvs(candidate) == PERSIST_SHORT_WRITE);
          assert(fake.writes == 1 && fake.opens == 0);

          reset_fake();
          fake.openError = ESP_FAIL;
          assert(save_profile_nvs(candidate) == PERSIST_REOPEN_FAILED);
          assert(fake.writes == 1 && fake.opens == 1);

          reset_fake();
          fake.sizeError = ESP_ERR_NVS_NOT_FOUND;
          assert(save_profile_nvs(candidate) == PERSIST_READ_FAILED);
          assert(fake.writes == 1 && fake.opens == 1);

          reset_fake();
          fake.sizeError = ESP_ERR_NVS_TYPE_MISMATCH;
          assert(save_profile_nvs(candidate) == PERSIST_READ_FAILED);
          assert(fake.writes == 1 && fake.opens == 1);

          reset_fake();
          fake.sizeReported = ProfileCodec::BLOB_SIZE - 1;
          assert(save_profile_nvs(candidate) == PERSIST_STORED_SIZE_MISMATCH);
          assert(fake.writes == 1 && fake.opens == 1);

          reset_fake();
          fake.readError = ESP_FAIL;
          assert(save_profile_nvs(candidate) == PERSIST_READ_FAILED);
          assert(fake.writes == 1 && fake.opens == 1);

          reset_fake();
          fake.readReported = ProfileCodec::BLOB_SIZE - 1;
          assert(save_profile_nvs(candidate) == PERSIST_SHORT_READ);
          assert(fake.writes == 1 && fake.opens == 1);

          reset_fake();
          fake.mutation = MUTATE_CRC;
          assert(save_profile_nvs(candidate) == PERSIST_READBACK_CRC);
          assert(fake.writes == 1 && fake.opens == 1);

          reset_fake();
          fake.mutation = MUTATE_VALID_DIFFERENT;
          assert(save_profile_nvs(candidate) == PERSIST_READBACK_MISMATCH);
          assert(fake.writes == 1 && fake.opens == 1);

          reset_fake();
          fake.mutation = MUTATE_INVALID_BOOL;
          assert(save_profile_nvs(candidate) == PERSIST_READBACK_MISMATCH);
          assert(fake.writes == 1 && fake.opens == 1);

          reset_fake();
          fake.mutation = MUTATE_RESERVED;
          assert(save_profile_nvs(candidate) == PERSIST_READBACK_MISMATCH);
          assert(fake.writes == 1 && fake.opens == 1);
        }

        static void test_load_fault_matrix() {
          const SetupEEPROM expected = sample_setup();

          reset_fake();
          fake.openError = ESP_ERR_NVS_NOT_FOUND;
          expect_load_failure(PROFILE_LOAD_NOT_FOUND);

          reset_fake();
          fake.openError = ESP_FAIL;
          expect_load_failure(PROFILE_LOAD_OPEN_FAILED);

          reset_fake();
          fake.sizeError = ESP_ERR_NVS_NOT_FOUND;
          expect_load_failure(PROFILE_LOAD_NOT_FOUND);

          reset_fake();
          fake.sizeError = ESP_ERR_NVS_TYPE_MISMATCH;
          expect_load_failure(PROFILE_LOAD_READ_FAILED);

          reset_fake();
          seed_current_blob(expected);
          fake.sizeReported = ProfileCodec::BLOB_SIZE - 1;
          expect_load_failure(PROFILE_LOAD_STORED_SIZE_MISMATCH);

          reset_fake();
          seed_current_blob(expected);
          fake.readError = ESP_FAIL;
          expect_load_failure(PROFILE_LOAD_READ_FAILED);

          reset_fake();
          seed_current_blob(expected);
          fake.readReported = ProfileCodec::BLOB_SIZE - 1;
          expect_load_failure(PROFILE_LOAD_SHORT_READ);

          reset_fake();
          seed_current_blob(expected);
          fake.blob[ProfileCodec::HEADER_SIZE] ^= 1U;
          expect_load_failure(PROFILE_LOAD_CRC);

          reset_fake();
          seed_current_blob(expected);
          fake.blob[ProfileCodec::HEADER_SIZE + 35] = 2U;
          write_crc(fake.blob);
          expect_load_failure(PROFILE_LOAD_PAYLOAD_ENCODING);

          reset_fake();
          seed_current_blob(expected);
          fake.blob[ProfileCodec::HEADER_SIZE +
                    SAMOVAR_PROFILE_CANONICAL_BYTES_V2] = 1U;
          write_crc(fake.blob);
          expect_load_failure(PROFILE_LOAD_PAYLOAD_ENCODING);

          reset_fake();
          seed_current_blob(expected);
          SetupEEPROM loaded;
          memset(&loaded, 0xA5, sizeof(loaded));
          assert(load_profile_nvs(loaded) == PROFILE_LOAD_OK);
          assert(loaded.flag == expected.flag);
          assert(loaded.Kp == expected.Kp);
          assert(loaded.Mode == expected.Mode);
          assert(loaded.StepperStepMlI2C == expected.StepperStepMlI2C);
          assert(loaded.SuvidHoldMinutes == expected.SuvidHoldMinutes);
          assert(encode_blob(loaded) == fake.blob);
        }

        static void test_v1_profile_migrates_after_verified_v2_write() {
          SetupEEPROM legacy = sample_setup();
          legacy.SuvidHoldMinutes = 999;

          reset_fake();
          fake.blob = encode_v1_blob(legacy);
          SetupEEPROM loaded{};
          assert(load_profile_nvs(loaded) == PROFILE_LOAD_OK);
          assert(loaded.Kp == legacy.Kp);
          assert(loaded.SuvidTemp == legacy.SuvidTemp);
          assert(loaded.SuvidHoldMinutes == 0);
          assert(fake.writes == 1);
          assert(fake.blob.size() == ProfileCodec::BLOB_SIZE);
          const SetupEEPROM rewritten = decode_written_blob();
          assert(rewritten.Kp == legacy.Kp);
          assert(rewritten.SuvidTemp == legacy.SuvidTemp);
          assert(rewritten.SuvidHoldMinutes == 0);

          reset_fake();
          fake.blob = encode_v1_blob(legacy);
          fake.writerBegin = false;
          SetupEEPROM destination;
          memset(&destination, 0xA5, sizeof(destination));
          uint8_t before[sizeof(destination)];
          memcpy(before, &destination, sizeof(before));
          assert(load_profile_nvs(destination) == PROFILE_LOAD_READ_FAILED);
          assert(memcmp(before, &destination, sizeof(before)) == 0);
        }

        static void mark_field(bool* occupied, size_t offset, size_t size) {
          for (size_t index = offset; index < offset + size; index++) {
            occupied[index] = true;
          }
        }

        static void test_poisoned_padding_and_canonical_rejection() {
          bool occupied[sizeof(SetupEEPROM)] = {};
        '''
    )
    + padding_marks
    + textwrap.dedent(
        r'''

          SetupEEPROM first{};
          SetupEEPROM second{};
          uint8_t* firstBytes = reinterpret_cast<uint8_t*>(&first);
          uint8_t* secondBytes = reinterpret_cast<uint8_t*>(&second);
          bool sawPadding = false;
          for (size_t index = 0; index < sizeof(SetupEEPROM); index++) {
            if (occupied[index]) continue;
            sawPadding = true;
            firstBytes[index] = 0xAA;
            secondBytes[index] = 0x55;
          }
          assert(sawPadding);
          assert(memcmp(&first, &second, sizeof(first)) != 0);

          uint8_t firstPayload[ProfileCodec::PAYLOAD_SIZE] = {};
          uint8_t secondPayload[ProfileCodec::PAYLOAD_SIZE] = {};
          assert(encode_setup_payload(first, firstPayload));
          assert(encode_setup_payload(second, secondPayload));
          assert(memcmp(firstPayload, secondPayload, sizeof(firstPayload)) == 0);
          assert(encode_blob(first) == encode_blob(second));

          SetupEEPROM destination;
          memset(&destination, 0xA5, sizeof(destination));
          uint8_t before[sizeof(destination)];
          memcpy(before, &destination, sizeof(before));
          firstPayload[35] = 2U;
          assert(!decode_setup_payload(firstPayload, destination));
          assert(memcmp(before, &destination, sizeof(before)) == 0);

          firstPayload[35] = 0U;
          firstPayload[SAMOVAR_PROFILE_CANONICAL_BYTES_V2] = 1U;
          assert(!decode_setup_payload(firstPayload, destination));
          assert(memcmp(before, &destination, sizeof(before)) == 0);
        }

        static void expect_legacy_failure(ProfileLoadResult expected) {
          SetupEEPROM destination;
          memset(&destination, 0xA5, sizeof(destination));
          uint8_t before[sizeof(destination)];
          memcpy(before, &destination, sizeof(before));
          assert(load_legacy_profile_namespace(
              "sam_rect", SAMOVAR_BEER_MODE, destination) == expected);
          assert(memcmp(before, &destination, sizeof(before)) == 0);
        }

        static void test_legacy_fault_matrix() {
          reset_fake(FAKE_LEGACY);
          fake.openError = ESP_ERR_NVS_NOT_FOUND;
          expect_legacy_failure(PROFILE_LOAD_NOT_FOUND);

          reset_fake(FAKE_LEGACY);
          fake.openError = ESP_FAIL;
          expect_legacy_failure(PROFILE_LOAD_OPEN_FAILED);

          reset_fake(FAKE_LEGACY);
          fake.flagBehavior = LEGACY_ABSENT;
          expect_legacy_failure(PROFILE_LOAD_NOT_FOUND);

          reset_fake(FAKE_LEGACY);
          fake.flagBehavior = LEGACY_ERROR;
          expect_legacy_failure(PROFILE_LOAD_READ_FAILED);

          reset_fake(FAKE_LEGACY);
          fake.flagBehavior = LEGACY_FOUND;
          fake.flag = 255;
          expect_legacy_failure(PROFILE_LOAD_LEGACY_INVALID);

          reset_fake(FAKE_LEGACY);
          fake.flagBehavior = LEGACY_FOUND;
          SetupEEPROM defaults{};
          assert(load_legacy_profile_namespace(
              "sam_rect", SAMOVAR_BEER_MODE, defaults) == PROFILE_LOAD_OK);
          assert(defaults.flag == 2);
          assert(defaults.Kp == 150.0f);
          assert(defaults.Mode == SAMOVAR_BEER_MODE);
          assert(defaults.SteamAdress[0] == 255);

          reset_fake(FAKE_LEGACY);
          fake.flagBehavior = LEGACY_FOUND;
          fake.kpBehavior = LEGACY_FOUND;
          fake.kp = 42.5f;
          SetupEEPROM loaded{};
          assert(load_legacy_profile_namespace(
              "sam_rect", SAMOVAR_BEER_MODE, loaded) == PROFILE_LOAD_OK);
          assert(loaded.Kp == 42.5f);

          reset_fake(FAKE_LEGACY);
          fake.flagBehavior = LEGACY_FOUND;
          fake.kpBehavior = LEGACY_ERROR;
          expect_legacy_failure(PROFILE_LOAD_READ_FAILED);

          reset_fake(FAKE_LEGACY);
          fake.flagBehavior = LEGACY_FOUND;
          fake.kpBehavior = LEGACY_READ_ERROR;
          expect_legacy_failure(PROFILE_LOAD_READ_FAILED);

          reset_fake(FAKE_LEGACY);
          fake.flagBehavior = LEGACY_FOUND;
          fake.kpBehavior = LEGACY_WRONG_SIZE;
          expect_legacy_failure(PROFILE_LOAD_READ_FAILED);
        }

        static void seed_last_mode(uint8_t mode) {
          FakeNamespace& meta = add_namespace("sam_meta");
          meta.lastModeBehavior = LEGACY_FOUND;
          meta.lastMode = mode;
        }

        static void seed_legacy_source(const char* name, float kp) {
          FakeNamespace& source = add_namespace(name);
          source.flagBehavior = LEGACY_FOUND;
          source.flag = 2;
          source.kpBehavior = LEGACY_FOUND;
          source.kp = kp;
        }

        static void seed_eeprom_source(float kp, int mode) {
          fake.eepromValue = {};
          fake.eepromValue.flag = 2;
          fake.eepromValue.Kp = kp;
          fake.eepromValue.Mode = mode;
        }

        static void test_migration_precedence_and_errors() {
          reset_fake(FAKE_MIGRATION);
          seed_last_mode(SAMOVAR_BEER_MODE);
          seed_legacy_source("sam_cfg", 11.0f);
          seed_legacy_source("sam_beer", 22.0f);
          seed_legacy_source("sam_dist", 33.0f);
          seed_eeprom_source(44.0f, SAMOVAR_NBK_MODE);
          SetupEEPROM loaded{};
          assert(migrate_from_eeprom(loaded) == PROFILE_LOAD_OK);
          assert(loaded.Kp == 11.0f && loaded.Mode == SAMOVAR_BEER_MODE);
          assert(opened_count("sam_beer") == 0 && fake.eepromBegins == 0);

          reset_fake(FAKE_MIGRATION);
          seed_last_mode(SAMOVAR_BEER_MODE);
          seed_legacy_source("sam_beer", 22.0f);
          seed_legacy_source("sam_dist", 33.0f);
          seed_eeprom_source(44.0f, SAMOVAR_NBK_MODE);
          loaded = {};
          assert(migrate_from_eeprom(loaded) == PROFILE_LOAD_OK);
          assert(loaded.Kp == 22.0f && loaded.Mode == SAMOVAR_BEER_MODE);
          assert(opened_count("sam_dist") == 0 && fake.eepromBegins == 0);

          reset_fake(FAKE_MIGRATION);
          seed_last_mode(SAMOVAR_BEER_MODE);
          seed_legacy_source("sam_dist", 33.0f);
          seed_eeprom_source(44.0f, SAMOVAR_NBK_MODE);
          loaded = {};
          assert(migrate_from_eeprom(loaded) == PROFILE_LOAD_OK);
          assert(loaded.Kp == 33.0f && loaded.Mode == SAMOVAR_DISTILLATION_MODE);
          assert(fake.eepromBegins == 0);

          reset_fake(FAKE_MIGRATION);
          seed_eeprom_source(44.0f, SAMOVAR_NBK_MODE);
          loaded = {};
          assert(migrate_from_eeprom(loaded) == PROFILE_LOAD_OK);
          assert(loaded.Kp == 44.0f && loaded.Mode == SAMOVAR_NBK_MODE);
          assert(fake.eepromBegins == 1 && fake.eepromGets == 1 && fake.eepromEnds == 1);

          // Непригодный источник не обрывает перебор: целый профиль в соседнем
          // неймспейсе обязан найтись, несмотря на нечитаемый sam_cfg.
          reset_fake(FAKE_MIGRATION);
          FakeNamespace& common = add_namespace("sam_cfg");
          common.flagBehavior = LEGACY_ERROR;
          seed_legacy_source("sam_rect", 22.0f);
          seed_eeprom_source(44.0f, SAMOVAR_NBK_MODE);
          loaded = {};
          assert(migrate_from_eeprom(loaded) == PROFILE_LOAD_OK);
          assert(loaded.Kp == 22.0f && loaded.Mode == SAMOVAR_RECTIFICATION_MODE);
          assert(opened_count("sam_rect") == 1 && fake.eepromBegins == 0);

          // Битая подсказка "последний режим" деградирует к режиму по умолчанию,
          // а не роняет миграцию: sam_meta только выбирает порядок перебора.
          reset_fake(FAKE_MIGRATION);
          FakeNamespace& meta = add_namespace("sam_meta");
          meta.lastModeBehavior = LEGACY_ERROR;
          seed_legacy_source("sam_cfg", 11.0f);
          loaded = {};
          assert(migrate_from_eeprom(loaded) == PROFILE_LOAD_OK);
          assert(loaded.Kp == 11.0f && loaded.Mode == SAMOVAR_RECTIFICATION_MODE);
          assert(opened_count("sam_cfg") == 1 && fake.eepromBegins == 0);

          // Если не подошёл никто - возвращается ПЕРВАЯ настоящая ошибка
          // (READ_FAILED у sam_cfg), а не вторая (LEGACY_INVALID у sam_rect с
          // flag=255) и не тихий NOT_FOUND, который setup() принял бы за первый
          // запуск и молча положил дефолты.
          reset_fake(FAKE_MIGRATION);
          FakeNamespace& brokenCfg = add_namespace("sam_cfg");
          brokenCfg.flagBehavior = LEGACY_ERROR;
          FakeNamespace& invalidRect = add_namespace("sam_rect");
          invalidRect.flagBehavior = LEGACY_FOUND;
          invalidRect.flag = 255;
          memset(&loaded, 0xA5, sizeof(loaded));
          uint8_t before[sizeof(loaded)];
          memcpy(before, &loaded, sizeof(before));
          assert(migrate_from_eeprom(loaded) == PROFILE_LOAD_READ_FAILED);
          assert(memcmp(before, &loaded, sizeof(before)) == 0);
          assert(fake.eepromBegins == 1);

          reset_fake(FAKE_MIGRATION);
          memset(&loaded, 0xA5, sizeof(loaded));
          memcpy(before, &loaded, sizeof(before));
          assert(migrate_from_eeprom(loaded) == PROFILE_LOAD_NOT_FOUND);
          assert(memcmp(before, &loaded, sizeof(before)) == 0);
          assert(fake.eepromBegins == 1 && fake.eepromGets == 1 && fake.eepromEnds == 1);
        }

        static void set_boot_sentinel() {
          SamSetup = {};
          SamSetup.Kp = -77.0f;
        }

        // production setup() больше не останавливает загрузку (fail-open): при сбое
        // report_degraded_boot() только фиксирует стадию/причину, а print_nvs_stats(...)
        // в конце извлечённого блока всегда достигается (initMarkers == 1 во всех сценариях).
        static bool boot_degraded() {
          run_boot_profile_decision();
          return fake.bootDegraded;
        }

        // Ни чтение NVS, ни миграция из EEPROM не проверяют диапазон R, а setup.htm
        // показывает сырое SamSetup.HeaterResistant. Не вылечив профиль на загрузке,
        // получаем расхождение: страница рисует сохранённый мусор, а мощность считается
        // по заводскому значению. Раньше тут стояло "ноль -> 10 Ом" - четвёртый ответ
        // на тот же вопрос, не совпадавший ни с заводским, ни с доверенным.
        static void test_boot_heals_untrusted_heater_resistance() {
          SetupEEPROM stored = sample_setup();

          // Значение вне диапазона: лечим до заводского и ГРОМКО об этом говорим.
          for (const float untrusted : {0.0f, 1.0f, 999.0f, -5.0f}) {
            stored.HeaterResistant = untrusted;
            reset_fake(FAKE_MIGRATION);
            add_namespace("sam_cfg");
            seed_current_blob(stored);
            set_boot_sentinel();
            assert(!boot_degraded());
            assert(SamSetup.HeaterResistant == CONTROL_HEATER_R_DEFAULT);
            assert(fake.serialLog.find("out of range") != std::string::npos);
          }

          // Годное значение обязано доехать нетронутым и молча. Середина берётся из
          // самой константы, а не литералом: сдвинут диапазон - тест поедет за ним,
          // а не упадёт на числе, которое перестало быть годным.
          for (const float trusted :
               {CONTROL_HEATER_R_MIN, CONTROL_HEATER_R_DEFAULT, CONTROL_HEATER_R_MAX}) {
            stored.HeaterResistant = trusted;
            reset_fake(FAKE_MIGRATION);
            add_namespace("sam_cfg");
            seed_current_blob(stored);
            set_boot_sentinel();
            assert(!boot_degraded());
            assert(SamSetup.HeaterResistant == trusted);
            assert(fake.serialLog.empty());
          }

          // Мигрированный профиль обязан лечь в NVS уже вылеченным, иначе мусор
          // переживёт перезагрузку и вернётся на следующем старте.
          // Без legacy-namespace миграция уходит в сырую EEPROM-ветку
          // (`candidate = legacyEeprom;` в NVS_Manager.ino): она копирует структуру
          // целиком, мимо set_default_setup_profile(), поэтому недоверенное R по ней
          // реально доезжает до лечения - в отличие от namespace-ветки, где R всегда
          // уже заводское. Смотрим именно ЗАПИСАННЫЙ блоб: факта записи мало - он
          // одинаков и когда лечение опоздало.
          reset_fake(FAKE_MIGRATION);
          seed_eeprom_source(44.0f, SAMOVAR_NBK_MODE);
          fake.eepromValue.HeaterResistant = 999.0f;
          set_boot_sentinel();
          assert(!boot_degraded());
          assert(fake.eepromBegins == 1);
          assert(fake.writes == 1);
          assert(SamSetup.HeaterResistant == CONTROL_HEATER_R_DEFAULT);
          assert(decode_written_blob().HeaterResistant == CONTROL_HEATER_R_DEFAULT);
        }

        static void test_boot_profile_decision() {
          const SetupEEPROM current = sample_setup();

          reset_fake(FAKE_MIGRATION);
          add_namespace("sam_cfg");
          seed_current_blob(current);
          set_boot_sentinel();
          assert(!boot_degraded());
          assert(fake.writes == 0 && fake.initMarkers == 1);
          assert(SamSetup.Kp == current.Kp);
          // Профиль прочитан штатно, миграции не было - стирать нечего.
          assert(fake.legacyCleanupCalls == 0);

          // Битый канонический блоб: "load" деградация, но грузимся на безопасных
          // дефолтах (не остаёмся на неинициализированном сторожевом значении Kp).
          reset_fake(FAKE_MIGRATION);
          add_namespace("sam_cfg");
          seed_current_blob(current);
          fake.blob[ProfileCodec::HEADER_SIZE] ^= 1U;
          set_boot_sentinel();
          assert(boot_degraded());
          assert(fake.degradedStage == "load" && fake.initMarkers == 1);
          assert(fake.writes == 0 && fake.eepromBegins == 0);
          assert(SamSetup.Kp == 150.0f);

          reset_fake(FAKE_MIGRATION);
          seed_last_mode(SAMOVAR_BEER_MODE);
          seed_legacy_source("sam_beer", 42.5f);
          set_boot_sentinel();
          assert(!boot_degraded());
          assert(fake.writes == 1 && fake.initMarkers == 1);
          assert(fake.ramKpAtWrite == -77.0f);
          assert(SamSetup.Kp == 42.5f && SamSetup.Mode == SAMOVAR_BEER_MODE);
          // Мигрировали и записали — только теперь legacy-остатки стираются, и
          // строго после записи (на момент вызова она уже состоялась).
          assert(fake.legacyCleanupCalls == 1 && fake.writesAtCleanup == 1);

          // Миграция из EEPROM успешна, но персист в NVS не удался: "migration"
          // деградация, но в памяти уже валидный мигрированный профиль — используем его.
          reset_fake(FAKE_MIGRATION);
          seed_last_mode(SAMOVAR_BEER_MODE);
          seed_legacy_source("sam_beer", 42.5f);
          fake.writerBegin = false;
          set_boot_sentinel();
          assert(boot_degraded());
          assert(fake.degradedStage == "migration" && fake.initMarkers == 1);
          assert(fake.writes == 0);
          assert(SamSetup.Kp == 42.5f && SamSetup.Mode == SAMOVAR_BEER_MODE);
          // Запись не удалась — legacy остаётся единственной копией настроек и
          // стиранию не подлежит.
          assert(fake.legacyCleanupCalls == 0);

          reset_fake(FAKE_MIGRATION);
          set_boot_sentinel();
          assert(!boot_degraded());
          assert(fake.writes == 1 && fake.initMarkers == 1);
          assert(fake.ramKpAtWrite == -77.0f && SamSetup.Kp == 150.0f);
          // Свежее устройство: дефолты записаны, но миграции не было - стирать нечего.
          assert(fake.legacyCleanupCalls == 0);

          // Ничего не найдено (ни канонический профиль, ни легаси EEPROM): дефолты
          // применены, но персист не удался — "migration" деградация на дефолтах.
          reset_fake(FAKE_MIGRATION);
          fake.writerBegin = false;
          set_boot_sentinel();
          assert(boot_degraded());
          assert(fake.degradedStage == "migration" && fake.initMarkers == 1);
          assert(fake.writes == 0 && SamSetup.Kp == 150.0f);

          // Легаси-namespace повреждён: migrate_from_eeprom возвращает ошибку (не
          // NOT_FOUND) -> "load" деградация, грузимся на дефолтах.
          reset_fake(FAKE_MIGRATION);
          FakeNamespace& common = add_namespace("sam_cfg");
          common.flagBehavior = LEGACY_ERROR;
          set_boot_sentinel();
          assert(boot_degraded());
          assert(fake.degradedStage == "load" && fake.initMarkers == 1);
          assert(fake.writes == 0 && SamSetup.Kp == 150.0f);
        }


        // ---------------------------------------------------------------------
        // A-16/T3 golden-тест: независимый (посчитанный отдельным python-скриптом,
        // НЕ через encode_setup_payload/decode_setup_payload_fields) побайтовый
        // эталон канонического V2-профиля (518 байт). Пин порядка/ширины полей —
        // перестановка, смена put_u16->put_u8, потеря вызова в цепочке && или
        // смещение candidate = {} обязаны развалить один из ассертов ниже с
        // указанием ИМЕНИ поля и байтового смещения, а не абстрактным «не то».
        struct GoldenFieldSpec {
          const char* name;
          size_t canonicalOffset;
          size_t canonicalSize;
          size_t structOffset;
          size_t structSize;
        };

        static const GoldenFieldSpec GOLDEN_FIELD_TABLE[] = {
          {"flag", 0, 1, offsetof(SetupEEPROM, flag), sizeof(((SetupEEPROM*)0)->flag)},
          {"DeltaSteamTemp", 1, 4, offsetof(SetupEEPROM, DeltaSteamTemp), sizeof(((SetupEEPROM*)0)->DeltaSteamTemp)},
          {"DeltaPipeTemp", 5, 4, offsetof(SetupEEPROM, DeltaPipeTemp), sizeof(((SetupEEPROM*)0)->DeltaPipeTemp)},
          {"DeltaWaterTemp", 9, 4, offsetof(SetupEEPROM, DeltaWaterTemp), sizeof(((SetupEEPROM*)0)->DeltaWaterTemp)},
          {"DeltaTankTemp", 13, 4, offsetof(SetupEEPROM, DeltaTankTemp), sizeof(((SetupEEPROM*)0)->DeltaTankTemp)},
          {"StepperStepMl", 17, 2, offsetof(SetupEEPROM, StepperStepMl), sizeof(((SetupEEPROM*)0)->StepperStepMl)},
          {"SetSteamTemp", 19, 4, offsetof(SetupEEPROM, SetSteamTemp), sizeof(((SetupEEPROM*)0)->SetSteamTemp)},
          {"SetPipeTemp", 23, 4, offsetof(SetupEEPROM, SetPipeTemp), sizeof(((SetupEEPROM*)0)->SetPipeTemp)},
          {"SetWaterTemp", 27, 4, offsetof(SetupEEPROM, SetWaterTemp), sizeof(((SetupEEPROM*)0)->SetWaterTemp)},
          {"SetTankTemp", 31, 4, offsetof(SetupEEPROM, SetTankTemp), sizeof(((SetupEEPROM*)0)->SetTankTemp)},
          {"UsePreccureCorrect", 35, 1, offsetof(SetupEEPROM, UsePreccureCorrect), sizeof(((SetupEEPROM*)0)->UsePreccureCorrect)},
          {"SteamDelay", 36, 2, offsetof(SetupEEPROM, SteamDelay), sizeof(((SetupEEPROM*)0)->SteamDelay)},
          {"PipeDelay", 38, 2, offsetof(SetupEEPROM, PipeDelay), sizeof(((SetupEEPROM*)0)->PipeDelay)},
          {"WaterDelay", 40, 2, offsetof(SetupEEPROM, WaterDelay), sizeof(((SetupEEPROM*)0)->WaterDelay)},
          {"TankDelay", 42, 2, offsetof(SetupEEPROM, TankDelay), sizeof(((SetupEEPROM*)0)->TankDelay)},
          {"TimeZone", 44, 1, offsetof(SetupEEPROM, TimeZone), sizeof(((SetupEEPROM*)0)->TimeZone)},
          {"HeaterResistant", 45, 4, offsetof(SetupEEPROM, HeaterResistant), sizeof(((SetupEEPROM*)0)->HeaterResistant)},
          {"LogPeriod", 49, 1, offsetof(SetupEEPROM, LogPeriod), sizeof(((SetupEEPROM*)0)->LogPeriod)},
          {"SteamColor", 50, 20, offsetof(SetupEEPROM, SteamColor), sizeof(((SetupEEPROM*)0)->SteamColor)},
          {"PipeColor", 70, 20, offsetof(SetupEEPROM, PipeColor), sizeof(((SetupEEPROM*)0)->PipeColor)},
          {"WaterColor", 90, 20, offsetof(SetupEEPROM, WaterColor), sizeof(((SetupEEPROM*)0)->WaterColor)},
          {"TankColor", 110, 20, offsetof(SetupEEPROM, TankColor), sizeof(((SetupEEPROM*)0)->TankColor)},
          {"rele1", 130, 1, offsetof(SetupEEPROM, rele1), sizeof(((SetupEEPROM*)0)->rele1)},
          {"rele2", 131, 1, offsetof(SetupEEPROM, rele2), sizeof(((SetupEEPROM*)0)->rele2)},
          {"rele3", 132, 1, offsetof(SetupEEPROM, rele3), sizeof(((SetupEEPROM*)0)->rele3)},
          {"rele4", 133, 1, offsetof(SetupEEPROM, rele4), sizeof(((SetupEEPROM*)0)->rele4)},
          {"SteamAdress", 134, 8, offsetof(SetupEEPROM, SteamAdress), sizeof(((SetupEEPROM*)0)->SteamAdress)},
          {"PipeAdress", 142, 8, offsetof(SetupEEPROM, PipeAdress), sizeof(((SetupEEPROM*)0)->PipeAdress)},
          {"WaterAdress", 150, 8, offsetof(SetupEEPROM, WaterAdress), sizeof(((SetupEEPROM*)0)->WaterAdress)},
          {"TankAdress", 158, 8, offsetof(SetupEEPROM, TankAdress), sizeof(((SetupEEPROM*)0)->TankAdress)},
          {"useautospeed", 166, 1, offsetof(SetupEEPROM, useautospeed), sizeof(((SetupEEPROM*)0)->useautospeed)},
          {"useDetector", 167, 1, offsetof(SetupEEPROM, useDetector), sizeof(((SetupEEPROM*)0)->useDetector)},
          {"autospeed", 168, 1, offsetof(SetupEEPROM, autospeed), sizeof(((SetupEEPROM*)0)->autospeed)},
          {"blynkauth", 169, 33, offsetof(SetupEEPROM, blynkauth), sizeof(((SetupEEPROM*)0)->blynkauth)},
          {"videourl", 202, 120, offsetof(SetupEEPROM, videourl), sizeof(((SetupEEPROM*)0)->videourl)},
          {"DistTemp", 322, 4, offsetof(SetupEEPROM, DistTemp), sizeof(((SetupEEPROM*)0)->DistTemp)},
          {"Mode", 326, 4, offsetof(SetupEEPROM, Mode), sizeof(((SetupEEPROM*)0)->Mode)},
          {"ACPAdress", 330, 8, offsetof(SetupEEPROM, ACPAdress), sizeof(((SetupEEPROM*)0)->ACPAdress)},
          {"ACPColor", 338, 20, offsetof(SetupEEPROM, ACPColor), sizeof(((SetupEEPROM*)0)->ACPColor)},
          {"DeltaACPTemp", 358, 4, offsetof(SetupEEPROM, DeltaACPTemp), sizeof(((SetupEEPROM*)0)->DeltaACPTemp)},
          {"SetACPTemp", 362, 4, offsetof(SetupEEPROM, SetACPTemp), sizeof(((SetupEEPROM*)0)->SetACPTemp)},
          {"ACPDelay", 366, 2, offsetof(SetupEEPROM, ACPDelay), sizeof(((SetupEEPROM*)0)->ACPDelay)},
          {"Kp", 368, 4, offsetof(SetupEEPROM, Kp), sizeof(((SetupEEPROM*)0)->Kp)},
          {"Ki", 372, 4, offsetof(SetupEEPROM, Ki), sizeof(((SetupEEPROM*)0)->Ki)},
          {"Kd", 376, 4, offsetof(SetupEEPROM, Kd), sizeof(((SetupEEPROM*)0)->Kd)},
          {"StbVoltage", 380, 4, offsetof(SetupEEPROM, StbVoltage), sizeof(((SetupEEPROM*)0)->StbVoltage)},
          {"ChangeProgramBuzzer", 384, 1, offsetof(SetupEEPROM, ChangeProgramBuzzer), sizeof(((SetupEEPROM*)0)->ChangeProgramBuzzer)},
          {"UseBuzzer", 385, 1, offsetof(SetupEEPROM, UseBuzzer), sizeof(((SetupEEPROM*)0)->UseBuzzer)},
          {"CheckPower", 386, 1, offsetof(SetupEEPROM, CheckPower), sizeof(((SetupEEPROM*)0)->CheckPower)},
          {"UseBBuzzer", 387, 1, offsetof(SetupEEPROM, UseBBuzzer), sizeof(((SetupEEPROM*)0)->UseBBuzzer)},
          {"UseWS", 388, 1, offsetof(SetupEEPROM, UseWS), sizeof(((SetupEEPROM*)0)->UseWS)},
          {"BVolt", 389, 4, offsetof(SetupEEPROM, BVolt), sizeof(((SetupEEPROM*)0)->BVolt)},
          {"UseST", 393, 1, offsetof(SetupEEPROM, UseST), sizeof(((SetupEEPROM*)0)->UseST)},
          {"DistTimeF", 394, 1, offsetof(SetupEEPROM, DistTimeF), sizeof(((SetupEEPROM*)0)->DistTimeF)},
          {"UseHLS", 395, 1, offsetof(SetupEEPROM, UseHLS), sizeof(((SetupEEPROM*)0)->UseHLS)},
          {"MaxPressureValue", 396, 4, offsetof(SetupEEPROM, MaxPressureValue), sizeof(((SetupEEPROM*)0)->MaxPressureValue)},
          {"tg_token", 400, 50, offsetof(SetupEEPROM, tg_token), sizeof(((SetupEEPROM*)0)->tg_token)},
          {"tg_chat_id", 450, 14, offsetof(SetupEEPROM, tg_chat_id), sizeof(((SetupEEPROM*)0)->tg_chat_id)},
          {"NbkIn", 464, 4, offsetof(SetupEEPROM, NbkIn), sizeof(((SetupEEPROM*)0)->NbkIn)},
          {"NbkDelta", 468, 4, offsetof(SetupEEPROM, NbkDelta), sizeof(((SetupEEPROM*)0)->NbkDelta)},
          {"NbkDM", 472, 4, offsetof(SetupEEPROM, NbkDM), sizeof(((SetupEEPROM*)0)->NbkDM)},
          {"NbkDP", 476, 4, offsetof(SetupEEPROM, NbkDP), sizeof(((SetupEEPROM*)0)->NbkDP)},
          {"NbkSteamT", 480, 4, offsetof(SetupEEPROM, NbkSteamT), sizeof(((SetupEEPROM*)0)->NbkSteamT)},
          {"NbkOwPress", 484, 4, offsetof(SetupEEPROM, NbkOwPress), sizeof(((SetupEEPROM*)0)->NbkOwPress)},
          {"ColDiam", 488, 4, offsetof(SetupEEPROM, ColDiam), sizeof(((SetupEEPROM*)0)->ColDiam)},
          {"ColHeight", 492, 4, offsetof(SetupEEPROM, ColHeight), sizeof(((SetupEEPROM*)0)->ColHeight)},
          {"PackDens", 496, 1, offsetof(SetupEEPROM, PackDens), sizeof(((SetupEEPROM*)0)->PackDens)},
          {"StepperStepMlI2C", 497, 2, offsetof(SetupEEPROM, StepperStepMlI2C), sizeof(((SetupEEPROM*)0)->StepperStepMlI2C)},
          {"NbkTn", 499, 4, offsetof(SetupEEPROM, NbkTn), sizeof(((SetupEEPROM*)0)->NbkTn)},
          {"BKPower", 503, 4, offsetof(SetupEEPROM, BKPower), sizeof(((SetupEEPROM*)0)->BKPower)},
          {"MainsVoltage", 507, 4, offsetof(SetupEEPROM, MainsVoltage), sizeof(((SetupEEPROM*)0)->MainsVoltage)},
          {"SuvidTemp", 511, 4, offsetof(SetupEEPROM, SuvidTemp), sizeof(((SetupEEPROM*)0)->SuvidTemp)},
          {"SuvidHoldMinutes", 515, 2, offsetof(SetupEEPROM, SuvidHoldMinutes), sizeof(((SetupEEPROM*)0)->SuvidHoldMinutes)},
          {"BeerBrewOrder", 517, 1, offsetof(SetupEEPROM, BeerBrewOrder), sizeof(((SetupEEPROM*)0)->BeerBrewOrder)},
        };

        static const uint8_t GOLDEN_A[520] = {
          0x0B,  // [  0-  0] flag
          0x00, 0x00, 0x00, 0x00,  // [  1-  4] DeltaSteamTemp
          0x00, 0x00, 0x50, 0xC0,  // [  5-  8] DeltaPipeTemp
          0x00, 0x00, 0x88, 0xC0,  // [  9- 12] DeltaWaterTemp
          0x00, 0x00, 0xA8, 0xC0,  // [ 13- 16] DeltaTankTemp
          0xC6, 0x04,  // [ 17- 18] StepperStepMl
          0x00, 0x00, 0xE8, 0xC0,  // [ 19- 22] SetSteamTemp
          0x00, 0x00, 0x04, 0xC1,  // [ 23- 26] SetPipeTemp
          0x00, 0x00, 0x14, 0xC1,  // [ 27- 30] SetWaterTemp
          0x00, 0x00, 0x24, 0xC1,  // [ 31- 34] SetTankTemp
          0x00,  // [ 35- 35] UsePreccureCorrect
          0xA4, 0x05,  // [ 36- 37] SteamDelay
          0xC9, 0x05,  // [ 38- 39] PipeDelay
          0xEE, 0x05,  // [ 40- 41] WaterDelay
          0x13, 0x06,  // [ 42- 43] TankDelay
          0x74,  // [ 44- 44] TimeZone
          0x00, 0x00, 0x8A, 0xC1,  // [ 45- 48] HeaterResistant
          0x82,  // [ 49- 49] LogPeriod
          0x53, 0x74, 0x65, 0x61, 0x6D, 0x43, 0x6F, 0x6C, 0x6F, 0x72, 0x41, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // [ 50- 69] SteamColor
          0x50, 0x69, 0x70, 0x65, 0x43, 0x6F, 0x6C, 0x6F, 0x72, 0x41, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // [ 70- 89] PipeColor
          0x57, 0x61, 0x74, 0x65, 0x72, 0x43, 0x6F, 0x6C, 0x6F, 0x72, 0x41, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // [ 90-109] WaterColor
          0x54, 0x61, 0x6E, 0x6B, 0x43, 0x6F, 0x6C, 0x6F, 0x72, 0x41, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // [110-129] TankColor
          0x00,  // [130-130] rele1
          0x01,  // [131-131] rele2
          0x00,  // [132-132] rele3
          0x01,  // [133-133] rele4
          0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07,  // [134-141] SteamAdress
          0x4C, 0x4F, 0x52, 0x55, 0x58, 0x5B, 0x5E, 0x61,  // [142-149] PipeAdress
          0x5D, 0x60, 0x63, 0x66, 0x69, 0x6C, 0x6F, 0x72,  // [150-157] WaterAdress
          0x6E, 0x71, 0x74, 0x77, 0x7A, 0x7D, 0x80, 0x83,  // [158-165] TankAdress
          0x00,  // [166-166] useautospeed
          0x01,  // [167-167] useDetector
          0xEB,  // [168-168] autospeed
          0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // [169-201] blynkauth
          0x76, 0x69, 0x64, 0x65, 0x6F, 0x75, 0x72, 0x6C, 0x41, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // [202-321] videourl
          0x00, 0x00, 0x11, 0xC2,  // [322-325] DistTemp
          0xC0, 0x1D, 0xFE, 0xFF,  // [326-329] Mode
          0x2E, 0x31, 0x34, 0x37, 0x3A, 0x3D, 0x40, 0x43,  // [330-337] ACPAdress
          0x41, 0x43, 0x50, 0x43, 0x6F, 0x6C, 0x6F, 0x72, 0x41, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // [338-357] ACPColor
          0x00, 0x00, 0x21, 0xC2,  // [358-361] DeltaACPTemp
          0x00, 0x00, 0x25, 0xC2,  // [362-365] SetACPTemp
          0xFA, 0x09,  // [366-367] ACPDelay
          0x00, 0x00, 0x2D, 0xC2,  // [368-371] Kp
          0x00, 0x00, 0x31, 0xC2,  // [372-375] Ki
          0x00, 0x00, 0x35, 0xC2,  // [376-379] Kd
          0x00, 0x00, 0x39, 0xC2,  // [380-383] StbVoltage
          0x00,  // [384-384] ChangeProgramBuzzer
          0x01,  // [385-385] UseBuzzer
          0x00,  // [386-386] CheckPower
          0x01,  // [387-387] UseBBuzzer
          0x00,  // [388-388] UseWS
          0x00, 0x00, 0x51, 0xC2,  // [389-392] BVolt
          0x00,  // [393-393] UseST
          0x84,  // [394-394] DistTimeF
          0x00,  // [395-395] UseHLS
          0x00, 0x00, 0x61, 0xC2,  // [396-399] MaxPressureValue
          0x74, 0x67, 0x5F, 0x74, 0x6F, 0x6B, 0x65, 0x6E, 0x41, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // [400-449] tg_token
          0x74, 0x67, 0x5F, 0x63, 0x68, 0x61, 0x74, 0x5F, 0x69, 0x64, 0x41, 0x00, 0x00, 0x00,  // [450-463] tg_chat_id
          0x00, 0x00, 0x6D, 0xC2,  // [464-467] NbkIn
          0x00, 0x00, 0x71, 0xC2,  // [468-471] NbkDelta
          0x00, 0x00, 0x75, 0xC2,  // [472-475] NbkDM
          0x00, 0x00, 0x79, 0xC2,  // [476-479] NbkDP
          0x00, 0x00, 0x7D, 0xC2,  // [480-483] NbkSteamT
          0x00, 0x80, 0x80, 0xC2,  // [484-487] NbkOwPress
          0x00, 0x80, 0x82, 0xC2,  // [488-491] ColDiam
          0x00, 0x80, 0x84, 0xC2,  // [492-495] ColHeight
          0xDF,  // [496-496] PackDens
          0xBC, 0x0D,  // [497-498] StepperStepMlI2C
          0x00, 0x80, 0x8A, 0xC2,  // [499-502] NbkTn
          0x00, 0x80, 0x8C, 0xC2,  // [503-506] BKPower
          0x00, 0x80, 0x8E, 0xC2,  // [507-510] MainsVoltage
          0x00, 0x80, 0x90, 0xC2,  // [511-514] SuvidTemp
          0x75, 0x0E,  // [515-516] SuvidHoldMinutes
          0x01,  // [517-517] BeerBrewOrder
          0x00, 0x00,  // [518-519] payload padding (finish() требует нули до PAYLOAD_SIZE_V2)
        };

        static const uint8_t GOLDEN_B[520] = {
          0xEE,  // [  0-  0] flag
          0x00, 0xC0, 0x48, 0x43,  // [  1-  4] DeltaSteamTemp
          0x00, 0x60, 0x96, 0x43,  // [  5-  8] DeltaPipeTemp
          0x00, 0x60, 0xC8, 0x43,  // [  9- 12] DeltaWaterTemp
          0x00, 0x60, 0xFA, 0x43,  // [ 13- 16] DeltaTankTemp
          0xB1, 0xFF,  // [ 17- 18] StepperStepMl
          0x00, 0x30, 0x2F, 0x44,  // [ 19- 22] SetSteamTemp
          0x00, 0x30, 0x48, 0x44,  // [ 23- 26] SetPipeTemp
          0x00, 0x30, 0x61, 0x44,  // [ 27- 30] SetWaterTemp
          0x00, 0x30, 0x7A, 0x44,  // [ 31- 34] SetTankTemp
          0x01,  // [ 35- 35] UsePreccureCorrect
          0x63, 0xFF,  // [ 36- 37] SteamDelay
          0x56, 0xFF,  // [ 38- 39] PipeDelay
          0x49, 0xFF,  // [ 40- 41] WaterDelay
          0x3C, 0xFF,  // [ 42- 43] TankDelay
          0x49,  // [ 44- 44] TimeZone
          0x00, 0x98, 0xD4, 0x44,  // [ 45- 48] HeaterResistant
          0x33,  // [ 49- 49] LogPeriod
          0x74, 0x74, 0x74, 0x74, 0x74, 0x74, 0x74, 0x74, 0x74, 0x74, 0x74, 0x74, 0x74, 0x74, 0x74, 0x74, 0x74, 0x74, 0x74, 0x00,  // [ 50- 69] SteamColor
          0x75, 0x75, 0x75, 0x75, 0x75, 0x75, 0x75, 0x75, 0x75, 0x75, 0x75, 0x75, 0x75, 0x75, 0x75, 0x75, 0x75, 0x75, 0x75, 0x00,  // [ 70- 89] PipeColor
          0x76, 0x76, 0x76, 0x76, 0x76, 0x76, 0x76, 0x76, 0x76, 0x76, 0x76, 0x76, 0x76, 0x76, 0x76, 0x76, 0x76, 0x76, 0x76, 0x00,  // [ 90-109] WaterColor
          0x77, 0x77, 0x77, 0x77, 0x77, 0x77, 0x77, 0x77, 0x77, 0x77, 0x77, 0x77, 0x77, 0x77, 0x77, 0x77, 0x77, 0x77, 0x77, 0x00,  // [110-129] TankColor
          0x01,  // [130-130] rele1
          0x00,  // [131-131] rele2
          0x01,  // [132-132] rele3
          0x00,  // [133-133] rele4
          0x9F, 0xA2, 0xA5, 0xA8, 0xAB, 0xAE, 0xB1, 0xB4,  // [134-141] SteamAdress
          0xB0, 0xB3, 0xB6, 0xB9, 0xBC, 0xBF, 0xC2, 0xC5,  // [142-149] PipeAdress
          0xC1, 0xC4, 0xC7, 0xCA, 0xCD, 0xD0, 0xD3, 0xD6,  // [150-157] WaterAdress
          0x0A, 0x0D, 0x10, 0x13, 0x16, 0x19, 0x1C, 0x1F,  // [158-165] TankAdress
          0x01,  // [166-166] useautospeed
          0x00,  // [167-167] useDetector
          0x88,  // [168-168] autospeed
          0x69, 0x69, 0x69, 0x69, 0x69, 0x69, 0x69, 0x69, 0x69, 0x69, 0x69, 0x69, 0x69, 0x69, 0x69, 0x69, 0x69, 0x69, 0x69, 0x69, 0x69, 0x69, 0x69, 0x69, 0x69, 0x69, 0x69, 0x69, 0x69, 0x69, 0x69, 0x69, 0x00,  // [169-201] blynkauth
          0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x6A, 0x00,  // [202-321] videourl
          0x00, 0x0C, 0x61, 0x45,  // [322-325] DistTemp
          0xDC, 0x26, 0x20, 0x78,  // [326-329] Mode
          0x92, 0x95, 0x98, 0x9B, 0x9E, 0xA1, 0xA4, 0xA7,  // [330-337] ACPAdress
          0x6E, 0x6E, 0x6E, 0x6E, 0x6E, 0x6E, 0x6E, 0x6E, 0x6E, 0x6E, 0x6E, 0x6E, 0x6E, 0x6E, 0x6E, 0x6E, 0x6E, 0x6E, 0x6E, 0x00,  // [338-357] ACPColor
          0x00, 0x0C, 0x7A, 0x45,  // [358-361] DeltaACPTemp
          0x00, 0x26, 0x80, 0x45,  // [362-365] SetACPTemp
          0xDD, 0xFD,  // [366-367] ACPDelay
          0x00, 0x66, 0x86, 0x45,  // [368-371] Kp
          0x00, 0x86, 0x89, 0x45,  // [372-375] Ki
          0x00, 0xA6, 0x8C, 0x45,  // [376-379] Kd
          0x00, 0xC6, 0x8F, 0x45,  // [380-383] StbVoltage
          0x01,  // [384-384] ChangeProgramBuzzer
          0x00,  // [385-385] UseBuzzer
          0x01,  // [386-386] CheckPower
          0x00,  // [387-387] UseBBuzzer
          0x01,  // [388-388] UseWS
          0x00, 0x86, 0xA2, 0x45,  // [389-392] BVolt
          0x01,  // [393-393] UseST
          0x9B,  // [394-394] DistTimeF
          0x01,  // [395-395] UseHLS
          0x00, 0x06, 0xAF, 0x45,  // [396-399] MaxPressureValue
          0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x00,  // [400-449] tg_token
          0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x67, 0x00,  // [450-463] tg_chat_id
          0x00, 0x66, 0xB8, 0x45,  // [464-467] NbkIn
          0x00, 0x86, 0xBB, 0x45,  // [468-471] NbkDelta
          0x00, 0xA6, 0xBE, 0x45,  // [472-475] NbkDM
          0x00, 0xC6, 0xC1, 0x45,  // [476-479] NbkDP
          0x00, 0xE6, 0xC4, 0x45,  // [480-483] NbkSteamT
          0x00, 0x06, 0xC8, 0x45,  // [484-487] NbkOwPress
          0x00, 0x26, 0xCB, 0x45,  // [488-491] ColDiam
          0x00, 0x46, 0xCE, 0x45,  // [492-495] ColHeight
          0x0C,  // [496-496] PackDens
          0x8B, 0xFC,  // [497-498] StepperStepMlI2C
          0x00, 0xA6, 0xD7, 0x45,  // [499-502] NbkTn
          0x00, 0xC6, 0xDA, 0x45,  // [503-506] BKPower
          0x00, 0xE6, 0xDD, 0x45,  // [507-510] MainsVoltage
          0x00, 0x06, 0xE1, 0x45,  // [511-514] SuvidTemp
          0x4A, 0xFC,  // [515-516] SuvidHoldMinutes
          0x02,  // [517-517] BeerBrewOrder
          0x00, 0x00,  // [518-519] payload padding (finish() требует нули до PAYLOAD_SIZE_V2)
        };

        static const uint8_t GOLDEN_DEFAULT_NOSEM[520] __attribute__((unused)) = {
          0x02,  // [  0-  0] flag
          0xCD, 0xCC, 0xCC, 0x3D,  // [  1-  4] DeltaSteamTemp
          0xCD, 0xCC, 0x4C, 0x3E,  // [  5-  8] DeltaPipeTemp
          0x00, 0x00, 0x00, 0x00,  // [  9- 12] DeltaWaterTemp
          0x00, 0x00, 0x00, 0x00,  // [ 13- 16] DeltaTankTemp
          0x64, 0x00,  // [ 17- 18] StepperStepMl
          0x00, 0x00, 0x00, 0x00,  // [ 19- 22] SetSteamTemp
          0x00, 0x00, 0x00, 0x00,  // [ 23- 26] SetPipeTemp
          0x00, 0x00, 0x00, 0x00,  // [ 27- 30] SetWaterTemp
          0x00, 0x00, 0x00, 0x00,  // [ 31- 34] SetTankTemp
          0x01,  // [ 35- 35] UsePreccureCorrect
          0x14, 0x00,  // [ 36- 37] SteamDelay
          0x14, 0x00,  // [ 38- 39] PipeDelay
          0x14, 0x00,  // [ 40- 41] WaterDelay
          0x14, 0x00,  // [ 42- 43] TankDelay
          0x03,  // [ 44- 44] TimeZone
          0x33, 0x33, 0x73, 0x41,  // [ 45- 48] HeaterResistant
          0x03,  // [ 49- 49] LogPeriod
          0x23, 0x66, 0x66, 0x30, 0x30, 0x30, 0x30, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // [ 50- 69] SteamColor
          0x23, 0x30, 0x30, 0x30, 0x30, 0x66, 0x66, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // [ 70- 89] PipeColor
          0x23, 0x30, 0x30, 0x62, 0x66, 0x66, 0x66, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // [ 90-109] WaterColor
          0x23, 0x30, 0x30, 0x38, 0x30, 0x30, 0x30, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // [110-129] TankColor
          0x00,  // [130-130] rele1
          0x00,  // [131-131] rele2
          0x00,  // [132-132] rele3
          0x00,  // [133-133] rele4
          0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,  // [134-141] SteamAdress
          0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,  // [142-149] PipeAdress
          0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,  // [150-157] WaterAdress
          0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,  // [158-165] TankAdress
          0x00,  // [166-166] useautospeed
          0x00,  // [167-167] useDetector
          0x00,  // [168-168] autospeed
          0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // [169-201] blynkauth
          0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // [202-321] videourl
          0x00, 0x00, 0xC4, 0x42,  // [322-325] DistTemp
          0x00, 0x00, 0x00, 0x00,  // [326-329] Mode
          0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,  // [330-337] ACPAdress
          0x23, 0x38, 0x30, 0x30, 0x30, 0x38, 0x30, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // [338-357] ACPColor
          0x00, 0x00, 0x00, 0x00,  // [358-361] DeltaACPTemp
          0x00, 0x00, 0x00, 0x00,  // [362-365] SetACPTemp
          0x14, 0x00,  // [366-367] ACPDelay
          0x00, 0x00, 0x16, 0x43,  // [368-371] Kp
          0x33, 0x33, 0xB3, 0x3F,  // [372-375] Ki
          0x33, 0x33, 0xB3, 0x3F,  // [376-379] Kd
          0x00, 0x00, 0xC8, 0x42,  // [380-383] StbVoltage
          0x00,  // [384-384] ChangeProgramBuzzer
          0x00,  // [385-385] UseBuzzer
          0x00,  // [386-386] CheckPower
          0x00,  // [387-387] UseBBuzzer
          0x01,  // [388-388] UseWS
          0x00, 0x00, 0x66, 0x43,  // [389-392] BVolt
          0x01,  // [393-393] UseST
          0x3C,  // [394-394] DistTimeF
          0x01,  // [395-395] UseHLS
          0x00, 0x00, 0x00, 0x00,  // [396-399] MaxPressureValue
          0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // [400-449] tg_token
          0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // [450-463] tg_chat_id
          0x00, 0x00, 0x34, 0x43,  // [464-467] NbkIn
          0x00, 0x00, 0x00, 0x3F,  // [468-471] NbkDelta
          0x00, 0x00, 0xC8, 0x42,  // [472-475] NbkDM
          0x00, 0x00, 0x00, 0x3F,  // [476-479] NbkDP
          0x00, 0x00, 0xA2, 0x42,  // [480-483] NbkSteamT
          0x00, 0x00, 0x20, 0x42,  // [484-487] NbkOwPress
          0x00, 0x00, 0x00, 0x40,  // [488-491] ColDiam
          0x00, 0x00, 0x00, 0x3F,  // [492-495] ColHeight
          0x50,  // [496-496] PackDens
          0xC8, 0x00,  // [497-498] StepperStepMlI2C
          0x00, 0x00, 0xC5, 0x42,  // [499-502] NbkTn
          0x00, 0x00, 0x34, 0x42,  // [503-506] BKPower
          0x00, 0x00, 0x66, 0x43,  // [507-510] MainsVoltage
          0x00, 0x00, 0x00, 0x00,  // [511-514] SuvidTemp
          0x00, 0x00,  // [515-516] SuvidHoldMinutes
          0x00,  // [517-517] BeerBrewOrder
          0x00, 0x00,  // [518-519] payload padding (finish() требует нули до PAYLOAD_SIZE_V2)
        };

        static const uint8_t GOLDEN_DEFAULT_SEM[520] __attribute__((unused)) = {
          0x02,  // [  0-  0] flag
          0xCD, 0xCC, 0xCC, 0x3D,  // [  1-  4] DeltaSteamTemp
          0xCD, 0xCC, 0x4C, 0x3E,  // [  5-  8] DeltaPipeTemp
          0x00, 0x00, 0x00, 0x00,  // [  9- 12] DeltaWaterTemp
          0x00, 0x00, 0x00, 0x00,  // [ 13- 16] DeltaTankTemp
          0x64, 0x00,  // [ 17- 18] StepperStepMl
          0x00, 0x00, 0x00, 0x00,  // [ 19- 22] SetSteamTemp
          0x00, 0x00, 0x00, 0x00,  // [ 23- 26] SetPipeTemp
          0x00, 0x00, 0x00, 0x00,  // [ 27- 30] SetWaterTemp
          0x00, 0x00, 0x00, 0x00,  // [ 31- 34] SetTankTemp
          0x01,  // [ 35- 35] UsePreccureCorrect
          0x14, 0x00,  // [ 36- 37] SteamDelay
          0x14, 0x00,  // [ 38- 39] PipeDelay
          0x14, 0x00,  // [ 40- 41] WaterDelay
          0x14, 0x00,  // [ 42- 43] TankDelay
          0x03,  // [ 44- 44] TimeZone
          0x33, 0x33, 0x73, 0x41,  // [ 45- 48] HeaterResistant
          0x03,  // [ 49- 49] LogPeriod
          0x23, 0x66, 0x66, 0x30, 0x30, 0x30, 0x30, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // [ 50- 69] SteamColor
          0x23, 0x30, 0x30, 0x30, 0x30, 0x66, 0x66, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // [ 70- 89] PipeColor
          0x23, 0x30, 0x30, 0x62, 0x66, 0x66, 0x66, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // [ 90-109] WaterColor
          0x23, 0x30, 0x30, 0x38, 0x30, 0x30, 0x30, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // [110-129] TankColor
          0x00,  // [130-130] rele1
          0x00,  // [131-131] rele2
          0x00,  // [132-132] rele3
          0x00,  // [133-133] rele4
          0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,  // [134-141] SteamAdress
          0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,  // [142-149] PipeAdress
          0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,  // [150-157] WaterAdress
          0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,  // [158-165] TankAdress
          0x00,  // [166-166] useautospeed
          0x00,  // [167-167] useDetector
          0x00,  // [168-168] autospeed
          0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // [169-201] blynkauth
          0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // [202-321] videourl
          0x00, 0x00, 0xC4, 0x42,  // [322-325] DistTemp
          0x00, 0x00, 0x00, 0x00,  // [326-329] Mode
          0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,  // [330-337] ACPAdress
          0x23, 0x38, 0x30, 0x30, 0x30, 0x38, 0x30, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // [338-357] ACPColor
          0x00, 0x00, 0x00, 0x00,  // [358-361] DeltaACPTemp
          0x00, 0x00, 0x00, 0x00,  // [362-365] SetACPTemp
          0x14, 0x00,  // [366-367] ACPDelay
          0x00, 0x00, 0x16, 0x43,  // [368-371] Kp
          0x33, 0x33, 0xB3, 0x3F,  // [372-375] Ki
          0x33, 0x33, 0xB3, 0x3F,  // [376-379] Kd
          0x00, 0x00, 0xC8, 0x42,  // [380-383] StbVoltage
          0x00,  // [384-384] ChangeProgramBuzzer
          0x00,  // [385-385] UseBuzzer
          0x00,  // [386-386] CheckPower
          0x00,  // [387-387] UseBBuzzer
          0x01,  // [388-388] UseWS
          0x00, 0x00, 0x66, 0x43,  // [389-392] BVolt
          0x01,  // [393-393] UseST
          0x3C,  // [394-394] DistTimeF
          0x01,  // [395-395] UseHLS
          0x00, 0x00, 0x00, 0x00,  // [396-399] MaxPressureValue
          0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // [400-449] tg_token
          0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // [450-463] tg_chat_id
          0x00, 0x00, 0x34, 0x43,  // [464-467] NbkIn
          0x00, 0x00, 0x00, 0x3F,  // [468-471] NbkDelta
          0x00, 0x00, 0xC8, 0x42,  // [472-475] NbkDM
          0x00, 0x00, 0x00, 0x3F,  // [476-479] NbkDP
          0x00, 0x00, 0xA2, 0x42,  // [480-483] NbkSteamT
          0x00, 0x00, 0x20, 0x42,  // [484-487] NbkOwPress
          0x00, 0x00, 0x00, 0x40,  // [488-491] ColDiam
          0x00, 0x00, 0x00, 0x3F,  // [492-495] ColHeight
          0x50,  // [496-496] PackDens
          0xC8, 0x00,  // [497-498] StepperStepMlI2C
          0x00, 0x00, 0xC5, 0x42,  // [499-502] NbkTn
          0x00, 0x00, 0x48, 0x43,  // [503-506] BKPower
          0x00, 0x00, 0x66, 0x43,  // [507-510] MainsVoltage
          0x00, 0x00, 0x00, 0x00,  // [511-514] SuvidTemp
          0x00, 0x00,  // [515-516] SuvidHoldMinutes
          0x00,  // [517-517] BeerBrewOrder
          0x00, 0x00,  // [518-519] payload padding (finish() требует нули до PAYLOAD_SIZE_V2)
        };


        static void golden_check_encode(
            const uint8_t* payload, const uint8_t* golden, const char* label) {
          const size_t count = sizeof(GOLDEN_FIELD_TABLE) / sizeof(GOLDEN_FIELD_TABLE[0]);
          for (size_t index = 0; index < count; index++) {
            const GoldenFieldSpec& field = GOLDEN_FIELD_TABLE[index];
            if (memcmp(payload + field.canonicalOffset, golden + field.canonicalOffset,
                       field.canonicalSize) != 0) {
              fprintf(stderr,
                      "golden encode mismatch: field=%s canonicalOffset=%zu size=%zu (%s)\n",
                      field.name, field.canonicalOffset, field.canonicalSize, label);
              assert(false && "golden encode field byte mismatch");
            }
          }
        }

        static void golden_check_decode(
            const SetupEEPROM& decoded, const SetupEEPROM& expected, const char* label) {
          const size_t count = sizeof(GOLDEN_FIELD_TABLE) / sizeof(GOLDEN_FIELD_TABLE[0]);
          const uint8_t* decodedBytes = reinterpret_cast<const uint8_t*>(&decoded);
          const uint8_t* expectedBytes = reinterpret_cast<const uint8_t*>(&expected);
          for (size_t index = 0; index < count; index++) {
            const GoldenFieldSpec& field = GOLDEN_FIELD_TABLE[index];
            if (memcmp(decodedBytes + field.structOffset, expectedBytes + field.structOffset,
                       field.structSize) != 0) {
              fprintf(stderr,
                      "golden decode mismatch: field=%s structOffset=%zu size=%zu (%s)\n",
                      field.name, field.structOffset, field.structSize, label);
              assert(false && "golden decode field mismatch");
            }
          }
        }

        static void test_golden_canonical_byte_layout() {
        SetupEEPROM candidateA{};
        candidateA.flag = 11;
        candidateA.DeltaSteamTemp = 0.0f;
        candidateA.DeltaPipeTemp = -3.25f;
        candidateA.DeltaWaterTemp = -4.25f;
        candidateA.DeltaTankTemp = -5.25f;
        candidateA.StepperStepMl = 1222;
        candidateA.SetSteamTemp = -7.25f;
        candidateA.SetPipeTemp = -8.25f;
        candidateA.SetWaterTemp = -9.25f;
        candidateA.SetTankTemp = -10.25f;
        candidateA.UsePreccureCorrect = false;
        candidateA.SteamDelay = 1444;
        candidateA.PipeDelay = 1481;
        candidateA.WaterDelay = 1518;
        candidateA.TankDelay = 1555;
        candidateA.TimeZone = 116;
        candidateA.HeaterResistant = -17.25f;
        candidateA.LogPeriod = 130;
        strcpy(candidateA.SteamColor, "SteamColorA");
        strcpy(candidateA.PipeColor, "PipeColorA");
        strcpy(candidateA.WaterColor, "WaterColorA");
        strcpy(candidateA.TankColor, "TankColorA");
        candidateA.rele1 = false;
        candidateA.rele2 = true;
        candidateA.rele3 = false;
        candidateA.rele4 = true;
        static const uint8_t GOLDEN_A_SteamAdress_BYTES[8] = {0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07};
        memcpy(candidateA.SteamAdress, GOLDEN_A_SteamAdress_BYTES, sizeof(candidateA.SteamAdress));
        static const uint8_t GOLDEN_A_PipeAdress_BYTES[8] = {0x4C, 0x4F, 0x52, 0x55, 0x58, 0x5B, 0x5E, 0x61};
        memcpy(candidateA.PipeAdress, GOLDEN_A_PipeAdress_BYTES, sizeof(candidateA.PipeAdress));
        static const uint8_t GOLDEN_A_WaterAdress_BYTES[8] = {0x5D, 0x60, 0x63, 0x66, 0x69, 0x6C, 0x6F, 0x72};
        memcpy(candidateA.WaterAdress, GOLDEN_A_WaterAdress_BYTES, sizeof(candidateA.WaterAdress));
        static const uint8_t GOLDEN_A_TankAdress_BYTES[8] = {0x6E, 0x71, 0x74, 0x77, 0x7A, 0x7D, 0x80, 0x83};
        memcpy(candidateA.TankAdress, GOLDEN_A_TankAdress_BYTES, sizeof(candidateA.TankAdress));
        candidateA.useautospeed = false;
        candidateA.useDetector = true;
        candidateA.autospeed = 235;
        strcpy(candidateA.blynkauth, "");
        strcpy(candidateA.videourl, "videourlA");
        candidateA.DistTemp = -36.25f;
        candidateA.Mode = -123456;
        static const uint8_t GOLDEN_A_ACPAdress_BYTES[8] = {0x2E, 0x31, 0x34, 0x37, 0x3A, 0x3D, 0x40, 0x43};
        memcpy(candidateA.ACPAdress, GOLDEN_A_ACPAdress_BYTES, sizeof(candidateA.ACPAdress));
        strcpy(candidateA.ACPColor, "ACPColorA");
        candidateA.DeltaACPTemp = -40.25f;
        candidateA.SetACPTemp = -41.25f;
        candidateA.ACPDelay = 2554;
        candidateA.Kp = -43.25f;
        candidateA.Ki = -44.25f;
        candidateA.Kd = -45.25f;
        candidateA.StbVoltage = -46.25f;
        candidateA.ChangeProgramBuzzer = false;
        candidateA.UseBuzzer = true;
        candidateA.CheckPower = false;
        candidateA.UseBBuzzer = true;
        candidateA.UseWS = false;
        candidateA.BVolt = -52.25f;
        candidateA.UseST = false;
        candidateA.DistTimeF = 132;
        candidateA.UseHLS = false;
        candidateA.MaxPressureValue = -56.25f;
        strcpy(candidateA.tg_token, "tg_tokenA");
        strcpy(candidateA.tg_chat_id, "tg_chat_idA");
        candidateA.NbkIn = -59.25f;
        candidateA.NbkDelta = -60.25f;
        candidateA.NbkDM = -61.25f;
        candidateA.NbkDP = -62.25f;
        candidateA.NbkSteamT = -63.25f;
        candidateA.NbkOwPress = -64.25f;
        candidateA.ColDiam = -65.25f;
        candidateA.ColHeight = -66.25f;
        candidateA.PackDens = 223;
        candidateA.StepperStepMlI2C = 3516;
        candidateA.NbkTn = -69.25f;
        candidateA.BKPower = -70.25f;
        candidateA.MainsVoltage = -71.25f;
        candidateA.SuvidTemp = -72.25f;
        candidateA.SuvidHoldMinutes = 3701;
        candidateA.BeerBrewOrder = 1;

          uint8_t payloadA[520] = {};
          assert(encode_setup_payload(candidateA, payloadA) &&
                 "encode_setup_payload must succeed for golden set A");
          golden_check_encode(payloadA, GOLDEN_A, "encode set A");

        SetupEEPROM candidateB{};
        candidateB.flag = 238;
        candidateB.DeltaSteamTemp = 200.75f;
        candidateB.DeltaPipeTemp = 300.75f;
        candidateB.DeltaWaterTemp = 400.75f;
        candidateB.DeltaTankTemp = 500.75f;
        candidateB.StepperStepMl = 65457;
        candidateB.SetSteamTemp = 700.75f;
        candidateB.SetPipeTemp = 800.75f;
        candidateB.SetWaterTemp = 900.75f;
        candidateB.SetTankTemp = 1000.75f;
        candidateB.UsePreccureCorrect = true;
        candidateB.SteamDelay = 65379;
        candidateB.PipeDelay = 65366;
        candidateB.WaterDelay = 65353;
        candidateB.TankDelay = 65340;
        candidateB.TimeZone = 73;
        candidateB.HeaterResistant = 1700.75f;
        candidateB.LogPeriod = 51;
        strcpy(candidateB.SteamColor, "ttttttttttttttttttt");
        strcpy(candidateB.PipeColor, "uuuuuuuuuuuuuuuuuuu");
        strcpy(candidateB.WaterColor, "vvvvvvvvvvvvvvvvvvv");
        strcpy(candidateB.TankColor, "wwwwwwwwwwwwwwwwwww");
        candidateB.rele1 = true;
        candidateB.rele2 = false;
        candidateB.rele3 = true;
        candidateB.rele4 = false;
        static const uint8_t GOLDEN_B_SteamAdress_BYTES[8] = {0x9F, 0xA2, 0xA5, 0xA8, 0xAB, 0xAE, 0xB1, 0xB4};
        memcpy(candidateB.SteamAdress, GOLDEN_B_SteamAdress_BYTES, sizeof(candidateB.SteamAdress));
        static const uint8_t GOLDEN_B_PipeAdress_BYTES[8] = {0xB0, 0xB3, 0xB6, 0xB9, 0xBC, 0xBF, 0xC2, 0xC5};
        memcpy(candidateB.PipeAdress, GOLDEN_B_PipeAdress_BYTES, sizeof(candidateB.PipeAdress));
        static const uint8_t GOLDEN_B_WaterAdress_BYTES[8] = {0xC1, 0xC4, 0xC7, 0xCA, 0xCD, 0xD0, 0xD3, 0xD6};
        memcpy(candidateB.WaterAdress, GOLDEN_B_WaterAdress_BYTES, sizeof(candidateB.WaterAdress));
        static const uint8_t GOLDEN_B_TankAdress_BYTES[8] = {0x0A, 0x0D, 0x10, 0x13, 0x16, 0x19, 0x1C, 0x1F};
        memcpy(candidateB.TankAdress, GOLDEN_B_TankAdress_BYTES, sizeof(candidateB.TankAdress));
        candidateB.useautospeed = true;
        candidateB.useDetector = false;
        candidateB.autospeed = 136;
        strcpy(candidateB.blynkauth, "iiiiiiiiiiiiiiiiiiiiiiiiiiiiiiii");
        strcpy(candidateB.videourl, "jjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjj");
        candidateB.DistTemp = 3600.75f;
        candidateB.Mode = 2015373020;
        static const uint8_t GOLDEN_B_ACPAdress_BYTES[8] = {0x92, 0x95, 0x98, 0x9B, 0x9E, 0xA1, 0xA4, 0xA7};
        memcpy(candidateB.ACPAdress, GOLDEN_B_ACPAdress_BYTES, sizeof(candidateB.ACPAdress));
        strcpy(candidateB.ACPColor, "nnnnnnnnnnnnnnnnnnn");
        candidateB.DeltaACPTemp = 4000.75f;
        candidateB.SetACPTemp = 4100.75f;
        candidateB.ACPDelay = 64989;
        candidateB.Kp = 4300.75f;
        candidateB.Ki = 4400.75f;
        candidateB.Kd = 4500.75f;
        candidateB.StbVoltage = 4600.75f;
        candidateB.ChangeProgramBuzzer = true;
        candidateB.UseBuzzer = false;
        candidateB.CheckPower = true;
        candidateB.UseBBuzzer = false;
        candidateB.UseWS = true;
        candidateB.BVolt = 5200.75f;
        candidateB.UseST = true;
        candidateB.DistTimeF = 155;
        candidateB.UseHLS = true;
        candidateB.MaxPressureValue = 5600.75f;
        strcpy(candidateB.tg_token, "fffffffffffffffffffffffffffffffffffffffffffffffff");
        strcpy(candidateB.tg_chat_id, "ggggggggggggg");
        candidateB.NbkIn = 5900.75f;
        candidateB.NbkDelta = 6000.75f;
        candidateB.NbkDM = 6100.75f;
        candidateB.NbkDP = 6200.75f;
        candidateB.NbkSteamT = 6300.75f;
        candidateB.NbkOwPress = 6400.75f;
        candidateB.ColDiam = 6500.75f;
        candidateB.ColHeight = 6600.75f;
        candidateB.PackDens = 12;
        candidateB.StepperStepMlI2C = 64651;
        candidateB.NbkTn = 6900.75f;
        candidateB.BKPower = 7000.75f;
        candidateB.MainsVoltage = 7100.75f;
        candidateB.SuvidTemp = 7200.75f;
        candidateB.SuvidHoldMinutes = 64586;
        candidateB.BeerBrewOrder = 2;

          uint8_t payloadB[520] = {};
          assert(encode_setup_payload(candidateB, payloadB) &&
                 "encode_setup_payload must succeed for golden set B");
          golden_check_encode(payloadB, GOLDEN_B, "encode set B");

          SetupEEPROM decodedA{};
          assert(decode_setup_payload(GOLDEN_A, decodedA) &&
                 "decode_setup_payload must succeed for golden set A");
          golden_check_decode(decodedA, candidateA, "decode set A");

          SetupEEPROM decodedB{};
          assert(decode_setup_payload(GOLDEN_B, decodedB) &&
                 "decode_setup_payload must succeed for golden set B");
          golden_check_decode(decodedB, candidateB, "decode set B");
        }

        static void test_golden_default_profile_layout() {
          // Отравляем стек НЕнулевым паттерном ДО вызова: если candidate = {} в
          // set_default_setup_profile() пропадёт или переедет ниже по функции,
          // поля без явного присваивания (исторически NbkTn/SuvidTemp) останутся
          // отравленными и golden_check_encode это поймает по имени поля.
          SetupEEPROM candidate;
          memset(&candidate, 0xAA, sizeof(candidate));
          set_default_setup_profile(candidate);

          uint8_t payload[520] = {};
          assert(encode_setup_payload(candidate, payload) &&
                 "encode_setup_payload must succeed for defaults");
        #ifndef SAMOVAR_USE_SEM_AVR
          golden_check_encode(payload, GOLDEN_DEFAULT_NOSEM, "defaults without SAMOVAR_USE_SEM_AVR");
        #else
          golden_check_encode(payload, GOLDEN_DEFAULT_SEM, "defaults with SAMOVAR_USE_SEM_AVR");
        #endif
        }


        int main() {
          test_save_fault_matrix();
          test_load_fault_matrix();
          test_v1_profile_migrates_after_verified_v2_write();
          test_poisoned_padding_and_canonical_rejection();
          test_legacy_fault_matrix();
          test_migration_precedence_and_errors();
          test_boot_profile_decision();
          test_boot_heals_untrusted_heater_resistance();
          test_golden_canonical_byte_layout();
          test_golden_default_profile_layout();
          return 0;
        }
        '''
    )
)

compile_and_run_harness("profile_nvs_behavior", nvs_harness)
# BKPower — единственное поле с дефолтом, зависящим от компиляции
# (Samovar_sem-окружение собирается с -DSAMOVAR_USE_SEM_AVR и меняет
# рабочую мощность БК с 45.0 на 200.0, см. profile_setup_fields.h). Гоняем
# тот же harness ещё раз с этим макросом, чтобы golden-тест дефолтов
# накрывал обе ветки, а не только окружение по умолчанию.
compile_and_run_harness(
    "profile_nvs_behavior_sem_avr", nvs_harness, defines=["-DSAMOVAR_USE_SEM_AVR"]
)

pid_harness = (
    textwrap.dedent(
        r'''
        #include <assert.h>
        #include <stdint.h>

        #include <string>
        #include <vector>

        // [T29] FinishAutoTune() теперь пишет SamSetup под спинлоком configMux.
        using portMUX_TYPE = int;
        static portMUX_TYPE configMux = 0;
        #define portENTER_CRITICAL(mux) do { (void)(mux); } while (0)
        #define portEXIT_CRITICAL(mux) do { (void)(mux); } while (0)
        '''
    )
    + "\n"
    + setup_definition
    + "\n"
    + definition(api_text, "enum PersistResult")
    + "\n"
    + textwrap.dedent(
        r'''
        class String {
         public:
          String() {}
          String(const char* source) : value(source) {}
          explicit String(float source) : value(std::to_string(source)) {}

          String& operator+=(const char* suffix) {
            value += suffix;
            return *this;
          }

          std::string value;
        };

        static String operator+(const char* prefix, const String& suffix) {
          String result(prefix);
          result.value += suffix.value;
          return result;
        }

        enum Event {
          EVENT_CANCEL,
          EVENT_SAVE,
          EVENT_TUNINGS,
          EVENT_LIMITS,
          EVENT_SAMPLE,
          EVENT_STOP,
          EVENT_MODE,
        };

        static std::vector<Event> events;

        struct FakeTune {
          float kp;
          float ki;
          float kd;

          void Cancel() { events.push_back(EVENT_CANCEL); }
          float GetKp() const { return kp; }
          float GetKi() const { return ki; }
          float GetKd() const { return kd; }
        };

        struct FakePid {
          float kp;
          float ki;
          float kd;
          int mode;

          void SetTunings(float newKp, float newKi, float newKd) {
            events.push_back(EVENT_TUNINGS);
            kp = newKp;
            ki = newKi;
            kd = newKd;
          }

          void SetOutputLimits(float minimum, float maximum) {
            assert(minimum == 0 && maximum == 100);
            events.push_back(EVENT_LIMITS);
          }

          void SetSampleTime(int milliseconds) {
            assert(milliseconds == 1000);
            events.push_back(EVENT_SAMPLE);
          }

          void SetMode(int newMode) {
            events.push_back(EVENT_MODE);
            mode = newMode;
          }
        };

        static SetupEEPROM SamSetup{};
        static FakeTune aTune{};
        static FakePid heaterPID{};
        static bool tuning = false;
        static uint8_t ATuneModeRemember = 7;
        static const int AUTOMATIC = 1;
        static const int ALARM_MSG = 0;
        static PersistResult configuredPersistResult = PERSIST_OK;
        static SetupEEPROM persistedCandidate{};
        static int persistCalls = 0;
        static int alarmCalls = 0;
        static int logCalls = 0;

        static PersistResult save_profile_nvs(const SetupEEPROM& candidate) {
          events.push_back(EVENT_SAVE);
          persistedCandidate = candidate;
          persistCalls++;
          return configuredPersistResult;
        }

        static const char* persist_result_code(PersistResult result) {
          return result == PERSIST_OK ? "ok" : "failed";
        }

        static void WriteConsoleLog(String message) {
          assert(!message.value.empty());
          logCalls++;
        }

        static void SendMsg(const String& message, int type) {
          assert(!message.value.empty());
          assert(type == ALARM_MSG);
          alarmCalls++;
        }

        static void set_heater_state(float setpoint, float temperature) {
          assert(setpoint == 0);
          assert(temperature == 50);
          events.push_back(EVENT_STOP);
          heaterPID.mode = AUTOMATIC;
        }
        '''
    )
    + "\n"
    + wrapped_function(beer_text, "void FinishAutoTune()", "void FinishAutoTune()")
    + textwrap.dedent(
        r'''
        static size_t event_position(Event expected) {
          for (size_t index = 0; index < events.size(); index++) {
            if (events[index] == expected) return index;
          }
          assert(false);
          return 0;
        }

        static void reset_pid_case(PersistResult result) {
          events.clear();
          SamSetup = {};
          SamSetup.Kp = 10.0f;
          SamSetup.Ki = 20.0f;
          SamSetup.Kd = 30.0f;
          aTune.kp = 101.0f;
          aTune.ki = 202.0f;
          aTune.kd = 303.0f;
          heaterPID = {};
          heaterPID.mode = 99;
          tuning = true;
          ATuneModeRemember = 7;
          configuredPersistResult = result;
          persistedCandidate = {};
          persistCalls = 0;
          alarmCalls = 0;
          logCalls = 0;
        }

        static void assert_restore_order() {
          assert(event_position(EVENT_SAVE) < event_position(EVENT_TUNINGS));
          assert(event_position(EVENT_TUNINGS) < event_position(EVENT_LIMITS));
          assert(event_position(EVENT_LIMITS) < event_position(EVENT_SAMPLE));
          assert(event_position(EVENT_SAMPLE) < event_position(EVENT_STOP));
          assert(event_position(EVENT_STOP) < event_position(EVENT_MODE));
          assert(events.back() == EVENT_MODE);
          assert(heaterPID.mode == ATuneModeRemember);
        }

        static void test_persist_success() {
          reset_pid_case(PERSIST_OK);
          FinishAutoTune();
          assert(!tuning);
          assert(persistCalls == 1);
          assert(persistedCandidate.Kp == 101.0f);
          assert(persistedCandidate.Ki == 202.0f);
          assert(persistedCandidate.Kd == 303.0f);
          assert(SamSetup.Kp == 101.0f);
          assert(SamSetup.Ki == 202.0f);
          assert(SamSetup.Kd == 303.0f);
          assert(heaterPID.kp == SamSetup.Kp);
          assert(heaterPID.ki == SamSetup.Ki);
          assert(heaterPID.kd == SamSetup.Kd);
          assert(alarmCalls == 0);
          assert(logCalls == 3);
          assert_restore_order();
        }

        static void test_persist_failure() {
          reset_pid_case(PERSIST_WRITE_FAILED);
          FinishAutoTune();
          assert(!tuning);
          assert(persistCalls == 1);
          assert(persistedCandidate.Kp == 101.0f);
          assert(persistedCandidate.Ki == 202.0f);
          assert(persistedCandidate.Kd == 303.0f);
          assert(SamSetup.Kp == 10.0f);
          assert(SamSetup.Ki == 20.0f);
          assert(SamSetup.Kd == 30.0f);
          assert(heaterPID.kp == SamSetup.Kp);
          assert(heaterPID.ki == SamSetup.Ki);
          assert(heaterPID.kd == SamSetup.Kd);
          assert(alarmCalls == 1);
          assert(logCalls == 0);
          assert_restore_order();
        }

        int main() {
          test_persist_success();
          test_persist_failure();
          return 0;
        }
        '''
    )
)

compile_and_run_harness("profile_pid_behavior", pid_harness)


save_body = function_body(
    nvs_text, "save_profile_nvs("
)
load_body = function_body(
    nvs_text, "load_profile_nvs("
)
migrate_body = function_body(
    nvs_text, "migrate_from_eeprom("
)
defaults_body = function_body(
    nvs_text, "set_default_setup_profile("
)

require(bool(save_body), "result-returning save_profile_nvs definition is missing")
require(bool(load_body), "result-returning load_profile_nvs definition is missing")
require(bool(migrate_body), "local-candidate migrate_from_eeprom definition is missing")
require(bool(defaults_body), "local-candidate default profile builder is missing")

if save_body:
    require(save_body.count("putBytes(") == 1, "profile save must perform exactly one putBytes")
    ordered(
        save_body,
        [
            "encode_setup_payload(candidate, payload)",
            "ProfileCodec::encode(payload, encoded)",
            "writer.begin(SAMOVAR_PROFILE_NAMESPACE, false)",
            "writer.putBytes(",
            "SAMOVAR_PROFILE_KEY",
            "writer.end()",
            "nvs_open(SAMOVAR_PROFILE_NAMESPACE, NVS_READONLY",
            "nvs_blob_size(",
            "nvs_read_blob(",
            "ProfileCodec::decode(",
            "memcmp(encoded.bytes, readBack.bytes, ProfileCodec::BLOB_SIZE)",
        ],
        "single write and read-back",
    )
    for forbidden in ["retry", "clear(", "remove("]:
        require(forbidden not in save_body.lower(), f"profile save contains forbidden {forbidden}")
    require("save_profile_nvs(" not in save_body, "profile save must not recurse")
    require(
        "ProfileCodec::BLOB_SIZE, payload" in re.sub(r"\s+", " ", save_body),
        "profile save must reuse its payload buffer for read-back decode",
    )
    for forbidden in ["decodedPayload", "SetupEEPROM decoded", "malloc(", "new "]:
        require(forbidden not in save_body, f"profile save exceeds fixed stack contract via {forbidden}")
    require(
        save_body.count("ProfileCodec::Blob") == 2 and
        save_body.count("uint8_t payload[ProfileCodec::PAYLOAD_SIZE]") == 1,
        "profile V2 save must keep one payload and two fixed codec blobs",
    )

if load_body:
    ordered(
        load_body,
        [
            "nvs_open(SAMOVAR_PROFILE_NAMESPACE, NVS_READONLY",
            "ESP_ERR_NVS_NOT_FOUND",
            "nvs_blob_size(",
            "PROFILE_VALUE_ABSENT",
            "nvs_read_blob(",
            "ProfileCodec::decode(",
            "decode_setup_payload(payload, candidate)",
        ],
        "fail-closed blob load",
    )
    for forbidden in [
        "migrate_from_eeprom",
        "set_default_setup_profile",
        "sam_rect",
        "EEPROM.",
        "Preferences",
        ".isKey(",
    ]:
        require(forbidden not in load_body, f"blob load contains forbidden fallback {forbidden}")
    require(
        len(re.findall(r"(?<!Legacy)ProfileCodec::Blob", load_body)) == 1 and
        load_body.count("LegacyProfileCodec::Blob") == 1 and
        load_body.count("uint8_t payload[ProfileCodec::PAYLOAD_SIZE]") == 1 and
        load_body.count("uint8_t payload[LegacyProfileCodec::PAYLOAD_SIZE]") == 1 and
        "decode_setup_payload_v1(payload, migrated)" in load_body and
        "save_profile_nvs(migrated)" in load_body and
        "SetupEEPROM decoded" not in load_body,
        "profile load must decode V1 and confirm its V2 rewrite with fixed buffers",
    )

if migrate_body:
    ordered(
        migrate_body,
        [
            "load_legacy_profile_namespace(",
            "SAMOVAR_PROFILE_NAMESPACE",
            "legacy_profile_namespace_by_mode(lastMode)",
            "EEPROM.begin(sizeof(SetupEEPROM))",
            "EEPROM.get(0, legacyEeprom)",
            "candidate = legacyEeprom",
        ],
        "legacy precedence",
    )
    for forbidden in ["put", "remove(", "clear(", '"migrated"']:
        require(forbidden not in migrate_body, f"legacy reader writes or clears state via {forbidden}")

legacy_body = function_body(
    nvs_text,
    "load_legacy_profile_namespace(",
)
if legacy_body:
    for forbidden in ["Preferences", ".isKey(", ".getUChar(", ".getFloat(", ".getString("]:
        require(forbidden not in legacy_body, f"legacy reader masks errors via {forbidden}")
    for token in [
        "PROFILE_VALUE_ABSENT",
        "PROFILE_VALUE_ERROR",
        "nvs_read_u8(",
        "nvs_read_float(",
        "nvs_read_string(",
    ]:
        require(token in legacy_body, f"legacy tri-state contract missing {token}")
else:
    errors.append("low-level legacy profile reader is missing")

encode_body = function_body(
    nvs_text,
    "encode_setup_payload(",
)
decode_body = function_body(
    nvs_text,
    "decode_setup_payload(",
)
decode_fields_body = function_body(
    nvs_text,
    "template <size_t PayloadSize>\nstatic bool decode_setup_payload_fields(",
)
decode_v2only_body = function_body(
    nvs_text,
    "template <size_t PayloadSize>\nstatic bool decode_setup_payload_v2only_fields(",
)
require(bool(encode_body), "field-wise SetupEEPROM encoder is missing")
require(bool(decode_body), "field-wise SetupEEPROM decoder is missing")
require(bool(decode_fields_body), "shared field-wise SetupEEPROM decoder is missing")
require(bool(decode_v2only_body), "V2-only field-wise SetupEEPROM decoder is missing")
for body, label in [
    (encode_body, "encoder"),
    (decode_fields_body, "decoder"),
    (decode_v2only_body, "V2-only decoder"),
]:
    for forbidden in ["memcpy(payload, &candidate", "memcpy(&candidate", "sizeof(SetupEEPROM)"]:
        require(forbidden not in body, f"{label} uses raw SetupEEPROM representation")
require("CanonicalProfile" in encode_body, "encoder does not use canonical field codec")
require("reader.get_" in decode_fields_body, "decoder does not use canonical field codec")
# A-16/T3: encode/decode-fields больше не перечисляют поля текстом (тело
# теперь — это разворот SAMOVAR_PROFILE_FIELDS(X)), поэтому "ordered subset"
# по сырому тексту функции ничего не докажет. Источник истины по порядку
# полей теперь один — profile_setup_fields.h; сверяем его СТРОГО 1-в-1
# (не "упорядоченное подмножество") с порядком объявления в SetupEEPROM,
# и отдельно проверяем, что обе функции реально диспетчеризуют через тот
# же общий X-macro список, а не через свою копию.
if not PROFILE_SETUP_FIELDS_HEADER.exists():
    errors.append("profile_setup_fields.h is missing")
else:
    profile_fields_text = PROFILE_SETUP_FIELDS_HEADER.read_text(encoding="utf-8")
    profile_field_rows = parse_profile_field_rows(profile_fields_text)
    macro_field_names = [row[1] for row in profile_field_rows]
    require(
        macro_field_names == setup_fields,
        "profile_setup_fields.h field order is not an exact 1-to-1 match with "
        f"SetupEEPROM declaration order: macro={macro_field_names!r} "
        f"struct={setup_fields!r}",
    )
    total_size = sum(int(row[2]) for row in profile_field_rows)
    require(
        total_size == 518,
        f"profile_setup_fields.h SIZE column sums to {total_size} bytes, expected 518",
    )
    # decode_setup_payload_fields() и decode_setup_payload_v2only_fields() читают
    # ОДИН И ТОТ ЖЕ курсор reader двумя последовательными проходами по одному и
    # тому же списку: первый проход потребляет байты только ALL-полей (V2ONLY
    # пропускает без чтения), второй - только V2ONLY (ALL пропускает без чтения).
    # Это корректно лишь тогда, когда V2ONLY-поля образуют смежный хвост списка
    # СРАЗУ после всех ALL-полей: если найдётся ALL-поле, идущее в списке ПОСЛЕ
    # V2ONLY-поля, первый проход остановится раньше нужного смещения, а второй
    # прочитает не те байты. Один явный, названный особый случай (существующий
    # V2ONLY-хвост) - это нормально; интерливинг ALL/V2ONLY - нет.
    v2only_fields = [row[1] for row in profile_field_rows if row[4] == "V2ONLY"]
    scopes = [row[4] for row in profile_field_rows]
    first_v2only = next((i for i, scope in enumerate(scopes) if scope == "V2ONLY"), None)
    require(
        first_v2only is None or all(scope == "V2ONLY" for scope in scopes[first_v2only:]),
        "V2ONLY fields in profile_setup_fields.h must form a contiguous tail after "
        f"all ALL fields (decode reads them in two passes over one cursor): {scopes!r}",
    )
    require(
        v2only_fields == ["SuvidHoldMinutes", "BeerBrewOrder"],
        f"unexpected V2ONLY field set in profile_setup_fields.h: {v2only_fields!r}",
    )
    # [П8] DistTimeF по умолчанию должен быть 60 минут (был 16 - см. мёртвую
    # isnan(uint8_t)-ветку, удалённую из apply_config_runtime() в Samovar.ino).
    dist_time_f_row = next((row for row in profile_field_rows if row[1] == "DistTimeF"), None)
    require(
        dist_time_f_row is not None and dist_time_f_row[3] == "candidate.DistTimeF = 60",
        "profile_setup_fields.h default for DistTimeF must be 60 minutes, got "
        f"{dist_time_f_row[3] if dist_time_f_row else '<missing>'}",
    )
if encode_body:
    require(
        "SAMOVAR_PROFILE_FIELDS(SAMOVAR_ENCODE_FIELD)" in encode_body,
        "encoder does not dispatch through the shared SAMOVAR_PROFILE_FIELDS X-macro",
    )
if decode_fields_body:
    require(
        "SAMOVAR_PROFILE_FIELDS(SAMOVAR_DECODE_FIELD)" in decode_fields_body,
        "decoder does not dispatch through the shared SAMOVAR_PROFILE_FIELDS X-macro",
    )
if decode_v2only_body:
    require(
        "SAMOVAR_PROFILE_FIELDS(SAMOVAR_V2ONLY_FIELD)" in decode_v2only_body,
        "V2-only decoder does not dispatch through the shared SAMOVAR_PROFILE_FIELDS "
        "X-macro (a hand-written per-field read would silently miss the next V2-only "
        "field added to the list)",
    )
if decode_body:
    require(
        "decode_setup_payload_v2only_fields(reader, decoded)" in decode_body,
        "V2 decoder must decode V2-only fields via the shared X-macro pass, not a "
        "hand-written field-specific call",
    )
    for name in v2only_fields:
        require(
            name not in decode_body,
            f"V2 decoder references {name} by name instead of going through the "
            "shared V2-only X-macro pass",
        )

finish_autotune_body = function_body(beer_text, "void FinishAutoTune()")
if finish_autotune_body:
    ordered(
        finish_autotune_body,
        [
            "save_profile_nvs(profileCandidate)",
            "if (persistResult == PERSIST_OK)",
            "SamSetup = profileCandidate",
            "heaterPID.SetTunings(SamSetup.Kp, SamSetup.Ki, SamSetup.Kd)",
            "heaterPID.SetOutputLimits(0, 100)",
            "heaterPID.SetSampleTime(1000)",
            "set_heater_state(0, 50)",
            "heaterPID.SetMode(ATuneModeRemember)",
        ],
        "FinishAutoTune committed PID restore order",
    )
else:
    errors.append("FinishAutoTune is missing")

for token in [
    "enum PersistResult : uint8_t",
    "enum ProfileLoadResult : uint8_t",
    "PersistResult save_profile_nvs(const SetupEEPROM& candidate);",
    "ProfileLoadResult load_profile_nvs(SetupEEPROM& candidate);",
    "ProfileLoadResult migrate_from_eeprom(SetupEEPROM& candidate);",
    "void set_default_setup_profile(SetupEEPROM& candidate);",
]:
    require(token in api_text, f"samovar_api.h missing {token}")

for forbidden in [
    "recover_pending_nvs_compaction",
    "compact_samovar_nvs_namespaces",
    "sam_tmp",
    "putUChar(\"last_mode",
    "retryingProfileSave",
    "nvsProfileWriteFailed",
    "void save_profile_nvs()",
    "void load_profile_nvs()",
]:
    require(forbidden not in nvs_text, f"obsolete NVS contract remains: {forbidden}")

require("void save_profile()" not in (ROOT / "FS.ino").read_text(encoding="utf-8"),
        "FS.ino void save_profile wrapper remains")
require("void save_profile();" not in api_text, "void save_profile API remains")
require('static_assert(sizeof(SetupEEPROM) == 536' in nvs_text,
        "production SetupEEPROM v2 ABI assertion is missing")

setup_body = function_body(samovar_text, "void setup()")
if setup_body:
    ordered(
        setup_body,
        [
            "SetupEEPROM startupProfile{}",
            "load_profile_nvs(startupProfile)",
            "migrate_from_eeprom(startupProfile)",
            "set_default_setup_profile(startupProfile)",
            "save_profile_nvs(startupProfile)",
            "SamSetup = startupProfile",
            "xMsgSemaphore = xSemaphoreCreateMutexStatic",
            "WiFi.mode(WIFI_STA)",
            "WebServerInit()",
        ],
        "profile gates normal boot",
    )

production = [
    "NVS_Manager.ino",
    "Samovar.ino",
    "WebServer.ino",
    "FS.ino",
    "Menu.ino",
    "logic.h",
    "beer.h",
    "samovar_api.h",
]
combined = "\n".join(
    strip_cpp_comments((ROOT / name).read_text(encoding="utf-8")) for name in production
)
require("save_profile();" not in combined, "a production caller still uses the removed void wrapper")
require("read_config();" not in combined, "a production caller still reloads profile after save")

ignored_result = re.compile(r"(?m)^\s*save_profile_nvs\s*\([^;]+\)\s*;")
for name in production:
    source = strip_cpp_comments((ROOT / name).read_text(encoding="utf-8"))
    for match in ignored_result.finditer(source):
        line = source.count("\n", 0, match.start()) + 1
        errors.append(f"{name}:{line} ignores PersistResult")

if errors:
    print("profile store smoke failed:")
    for error in errors:
        print(f" - {error}")
    raise SystemExit(1)

print("profile store smoke passed")
