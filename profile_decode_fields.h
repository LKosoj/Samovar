#pragma once

// Шаблоны в .h, а не в .ino: Arduino IDE иначе вставляет прототип с
// необъявленным PayloadSize.
template <size_t PayloadSize>
static bool decode_setup_payload_fields(
    CanonicalProfileReader<PayloadSize>& reader,
    SetupEEPROM& decoded) {
  int32_t mode = 0;
#define SAMOVAR_GET_U8(name) reader.get_u8(decoded.name)
#define SAMOVAR_GET_BOOL(name) reader.get_bool(decoded.name)
#define SAMOVAR_GET_U16(name) reader.get_u16(decoded.name)
#define SAMOVAR_GET_FLOAT(name) reader.get_float(decoded.name)
#define SAMOVAR_GET_I32_MODE(name) reader.get_i32(mode)
#define SAMOVAR_GET_BYTES_U8(name) reader.get_bytes(decoded.name, sizeof(decoded.name))
#define SAMOVAR_GET_BYTES_CHAR(name) reader.get_bytes(reinterpret_cast<uint8_t*>(decoded.name), sizeof(decoded.name))
#define SAMOVAR_DECODE_TERM_ALL(kind, name) SAMOVAR_GET_##kind(name) &&
#define SAMOVAR_DECODE_TERM_V2ONLY(kind, name)
#define SAMOVAR_DECODE_TERM_V3ONLY(kind, name)
#define SAMOVAR_DECODE_TERM_V4ONLY(kind, name)
#define SAMOVAR_DECODE_FIELD(kind, name, size, deflt, scope) SAMOVAR_DECODE_TERM_##scope(kind, name)
  const bool decodedFields =
      SAMOVAR_PROFILE_FIELDS(SAMOVAR_DECODE_FIELD)
      true;
#undef SAMOVAR_DECODE_FIELD
#undef SAMOVAR_DECODE_TERM_V4ONLY
#undef SAMOVAR_DECODE_TERM_V3ONLY
#undef SAMOVAR_DECODE_TERM_V2ONLY
#undef SAMOVAR_DECODE_TERM_ALL
#undef SAMOVAR_GET_BYTES_CHAR
#undef SAMOVAR_GET_BYTES_U8
#undef SAMOVAR_GET_I32_MODE
#undef SAMOVAR_GET_FLOAT
#undef SAMOVAR_GET_U16
#undef SAMOVAR_GET_BOOL
#undef SAMOVAR_GET_U8
  if (!decodedFields) return false;
  decoded.Mode = int(mode);
  return true;
}

// Последовательные проходы читают общий блок, затем хвосты V2, V3 и V4 на одном
// курсоре. Поэтому scope-блоки обязаны идти строго ALL, V2ONLY, V3ONLY, V4ONLY;
// порядок защищён tools/smoke_profile_store.py.
template <size_t PayloadSize>
static bool decode_setup_payload_v2only_fields(
    CanonicalProfileReader<PayloadSize>& reader,
    SetupEEPROM& decoded) {
#define SAMOVAR_GET_U8(name) reader.get_u8(decoded.name)
#define SAMOVAR_GET_BOOL(name) reader.get_bool(decoded.name)
#define SAMOVAR_GET_U16(name) reader.get_u16(decoded.name)
#define SAMOVAR_GET_FLOAT(name) reader.get_float(decoded.name)
#define SAMOVAR_GET_BYTES_U8(name) reader.get_bytes(decoded.name, sizeof(decoded.name))
#define SAMOVAR_GET_BYTES_CHAR(name) reader.get_bytes(reinterpret_cast<uint8_t*>(decoded.name), sizeof(decoded.name))
#define SAMOVAR_V2ONLY_TERM_ALL(kind, name)
#define SAMOVAR_V2ONLY_TERM_V2ONLY(kind, name) SAMOVAR_GET_##kind(name) &&
#define SAMOVAR_V2ONLY_TERM_V3ONLY(kind, name)
#define SAMOVAR_V2ONLY_TERM_V4ONLY(kind, name)
#define SAMOVAR_V2ONLY_FIELD(kind, name, size, deflt, scope) SAMOVAR_V2ONLY_TERM_##scope(kind, name)
  const bool decodedFields =
      SAMOVAR_PROFILE_FIELDS(SAMOVAR_V2ONLY_FIELD)
      true;
#undef SAMOVAR_V2ONLY_FIELD
#undef SAMOVAR_V2ONLY_TERM_V4ONLY
#undef SAMOVAR_V2ONLY_TERM_V3ONLY
#undef SAMOVAR_V2ONLY_TERM_V2ONLY
#undef SAMOVAR_V2ONLY_TERM_ALL
#undef SAMOVAR_GET_BYTES_CHAR
#undef SAMOVAR_GET_BYTES_U8
#undef SAMOVAR_GET_FLOAT
#undef SAMOVAR_GET_U16
#undef SAMOVAR_GET_BOOL
#undef SAMOVAR_GET_U8
  return decodedFields;
}

template <size_t PayloadSize>
static bool decode_setup_payload_v3only_fields(
    CanonicalProfileReader<PayloadSize>& reader,
    SetupEEPROM& decoded) {
#define SAMOVAR_GET_U8(name) reader.get_u8(decoded.name)
#define SAMOVAR_GET_BOOL(name) reader.get_bool(decoded.name)
#define SAMOVAR_GET_U16(name) reader.get_u16(decoded.name)
#define SAMOVAR_GET_FLOAT(name) reader.get_float(decoded.name)
#define SAMOVAR_GET_BYTES_U8(name) reader.get_bytes(decoded.name, sizeof(decoded.name))
#define SAMOVAR_GET_BYTES_CHAR(name) reader.get_bytes(reinterpret_cast<uint8_t*>(decoded.name), sizeof(decoded.name))
#define SAMOVAR_V3ONLY_TERM_ALL(kind, name)
#define SAMOVAR_V3ONLY_TERM_V2ONLY(kind, name)
#define SAMOVAR_V3ONLY_TERM_V3ONLY(kind, name) SAMOVAR_GET_##kind(name) &&
#define SAMOVAR_V3ONLY_TERM_V4ONLY(kind, name)
#define SAMOVAR_V3ONLY_FIELD(kind, name, size, deflt, scope) SAMOVAR_V3ONLY_TERM_##scope(kind, name)
  const bool decodedFields =
      SAMOVAR_PROFILE_FIELDS(SAMOVAR_V3ONLY_FIELD)
      true;
#undef SAMOVAR_V3ONLY_FIELD
#undef SAMOVAR_V3ONLY_TERM_V4ONLY
#undef SAMOVAR_V3ONLY_TERM_V3ONLY
#undef SAMOVAR_V3ONLY_TERM_V2ONLY
#undef SAMOVAR_V3ONLY_TERM_ALL
#undef SAMOVAR_GET_BYTES_CHAR
#undef SAMOVAR_GET_BYTES_U8
#undef SAMOVAR_GET_FLOAT
#undef SAMOVAR_GET_U16
#undef SAMOVAR_GET_BOOL
#undef SAMOVAR_GET_U8
  return decodedFields;
}

template <size_t PayloadSize>
static bool decode_setup_payload_v4only_fields(
    CanonicalProfileReader<PayloadSize>& reader,
    SetupEEPROM& decoded) {
#define SAMOVAR_GET_U8(name) reader.get_u8(decoded.name)
#define SAMOVAR_GET_BOOL(name) reader.get_bool(decoded.name)
#define SAMOVAR_GET_U16(name) reader.get_u16(decoded.name)
#define SAMOVAR_GET_FLOAT(name) reader.get_float(decoded.name)
#define SAMOVAR_GET_BYTES_U8(name) reader.get_bytes(decoded.name, sizeof(decoded.name))
#define SAMOVAR_GET_BYTES_CHAR(name) reader.get_bytes(reinterpret_cast<uint8_t*>(decoded.name), sizeof(decoded.name))
#define SAMOVAR_V4ONLY_TERM_ALL(kind, name)
#define SAMOVAR_V4ONLY_TERM_V2ONLY(kind, name)
#define SAMOVAR_V4ONLY_TERM_V3ONLY(kind, name)
#define SAMOVAR_V4ONLY_TERM_V4ONLY(kind, name) SAMOVAR_GET_##kind(name) &&
#define SAMOVAR_V4ONLY_FIELD(kind, name, size, deflt, scope) SAMOVAR_V4ONLY_TERM_##scope(kind, name)
  const bool decodedFields =
      SAMOVAR_PROFILE_FIELDS(SAMOVAR_V4ONLY_FIELD)
      true;
#undef SAMOVAR_V4ONLY_FIELD
#undef SAMOVAR_V4ONLY_TERM_V4ONLY
#undef SAMOVAR_V4ONLY_TERM_V3ONLY
#undef SAMOVAR_V4ONLY_TERM_V2ONLY
#undef SAMOVAR_V4ONLY_TERM_ALL
#undef SAMOVAR_GET_BYTES_CHAR
#undef SAMOVAR_GET_BYTES_U8
#undef SAMOVAR_GET_FLOAT
#undef SAMOVAR_GET_U16
#undef SAMOVAR_GET_BOOL
#undef SAMOVAR_GET_U8
  return decodedFields;
}
