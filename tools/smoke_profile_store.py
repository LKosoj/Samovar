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
NVS = ROOT / "NVS_Manager.ino"
SAMOVAR = ROOT / "Samovar.ino"
API = ROOT / "samovar_api.h"

errors: list[str] = []


def require(condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


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


def compile_and_run_harness(name: str, harness: str) -> None:
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

nvs_text = strip_cpp_comments(NVS.read_text(encoding="utf-8"))
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
require(len(setup_fields) == 72, "SetupEEPROM field inventory changed")
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
        static const uint16_t SAMOVAR_PROFILE_FORMAT_VERSION = 1;
        static const size_t SAMOVAR_PROFILE_PAYLOAD_SIZE_V1 = 516;
        static const size_t SAMOVAR_PROFILE_CANONICAL_BYTES_V1 = 515;

        using ProfileCodec = ProfileBlobCodec<
            SAMOVAR_PROFILE_PAYLOAD_SIZE_V1,
            SAMOVAR_PROFILE_FORMAT_VERSION>;

        static_assert(sizeof(SetupEEPROM) == 532, "host ABI drift");
        static_assert(ProfileCodec::BLOB_SIZE == 530, "blob size drift");

        static const float DEFAULT_DIST_TEMP = 98.0f;
        static const uint16_t STEPPER_STEP_ML = 100;
        static const uint16_t I2C_STEPPER_STEP_ML_DEFAULT = 200;

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
            fake.blob[ProfileCodec::HEADER_SIZE + 515] = 1U;
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
        "decode_setup_payload(",
        "static bool decode_setup_payload(const uint8_t* payload, SetupEEPROM& candidate)",
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
          candidate.useDetectorOnHeads = true;
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
          return candidate;
        }

        static std::vector<uint8_t> encode_blob(const SetupEEPROM& candidate) {
          uint8_t payload[ProfileCodec::PAYLOAD_SIZE] = {};
          assert(encode_setup_payload(candidate, payload));
          ProfileCodec::Blob blob{};
          ProfileCodec::encode(payload, blob);
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
          fake.blob[ProfileCodec::HEADER_SIZE + 515] = 1U;
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
          assert(encode_blob(loaded) == fake.blob);
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
          firstPayload[515] = 1U;
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

        int main() {
          test_save_fault_matrix();
          test_load_fault_matrix();
          test_poisoned_padding_and_canonical_rejection();
          test_legacy_fault_matrix();
          test_migration_precedence_and_errors();
          test_boot_profile_decision();
          test_boot_heals_untrusted_heater_resistance();
          return 0;
        }
        '''
    )
)

compile_and_run_harness("profile_nvs_behavior", nvs_harness)

pid_harness = (
    textwrap.dedent(
        r'''
        #include <assert.h>
        #include <stdint.h>

        #include <string>
        #include <vector>
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
        "profile save fixed byte buffers must remain 516 + 530 + 530 bytes",
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
        load_body.count("ProfileCodec::Blob") == 1 and
        load_body.count("uint8_t payload[ProfileCodec::PAYLOAD_SIZE]") == 1 and
        "SetupEEPROM decoded" not in load_body,
        "profile load stack must remain 530 + 516 outer + 516 decoder bytes",
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
require(bool(encode_body), "field-wise SetupEEPROM encoder is missing")
require(bool(decode_body), "field-wise SetupEEPROM decoder is missing")
for body, label in [(encode_body, "encoder"), (decode_body, "decoder")]:
    for forbidden in ["memcpy(payload, &candidate", "memcpy(&candidate", "sizeof(SetupEEPROM)"]:
        require(forbidden not in body, f"{label} uses raw SetupEEPROM representation")
    require("CanonicalProfile" in body, f"{label} does not use canonical field codec")
if encode_body:
    ordered(
        encode_body,
        [f"candidate.{field}" for field in setup_fields],
        "SetupEEPROM declaration-order encoder",
    )
if decode_body:
    ordered(
        decode_body,
        [
            "reader.get_i32(mode)" if field == "Mode" else f"decoded.{field}"
            for field in setup_fields
        ],
        "SetupEEPROM declaration-order decoder",
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
require('static_assert(sizeof(SetupEEPROM) == 532' in nvs_text,
        "production SetupEEPROM v1 ABI assertion is missing")

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
            "xMsgSemaphore = xSemaphoreCreateBinaryStatic",
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
