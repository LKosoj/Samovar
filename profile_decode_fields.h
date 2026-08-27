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
#define SAMOVAR_DECODE_FIELD(kind, name, size, deflt, scope) SAMOVAR_DECODE_TERM_##scope(kind, name)
  const bool decodedFields =
      SAMOVAR_PROFILE_FIELDS(SAMOVAR_DECODE_FIELD)
      true;
#undef SAMOVAR_DECODE_FIELD
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

// Второй проход тем же SAMOVAR_PROFILE_FIELDS: decode_setup_payload_fields() выше
// читает поля со SCOPE=ALL и молча пропускает (0 байт) поля со SCOPE=V2ONLY - так
// V1-формат, где этих полей вообще нет, декодируется тем же кодом. Эта функция -
// зеркальный проход по тому же списку, который читает ТОЛЬКО V2ONLY-поля и
// пропускает ALL. Вызывается ПОСЛЕ decode_setup_payload_fields() на том же курсоре
// reader, поэтому V2ONLY-поля обязаны быть смежным хвостом списка ПОСЛЕ всех
// ALL-полей (иначе байты разъедутся) - это единственное текущее исключение из
// общего порядка, и оно защищено tools/smoke_profile_store.py.
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
#define SAMOVAR_V2ONLY_FIELD(kind, name, size, deflt, scope) SAMOVAR_V2ONLY_TERM_##scope(kind, name)
  const bool decodedFields =
      SAMOVAR_PROFILE_FIELDS(SAMOVAR_V2ONLY_FIELD)
      true;
#undef SAMOVAR_V2ONLY_FIELD
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
