#pragma once

#include <stddef.h>
#include <stdint.h>
#include <string.h>

enum ProfileCodecResult : uint8_t {
  PROFILE_CODEC_OK = 0,
  PROFILE_CODEC_STORED_SIZE,
  PROFILE_CODEC_MAGIC,
  PROFILE_CODEC_VERSION,
  PROFILE_CODEC_PAYLOAD_SIZE,
  PROFILE_CODEC_CRC,
};

inline uint32_t profile_crc32_iso_hdlc(const uint8_t* data, size_t size) {
  uint32_t crc = 0xFFFFFFFFU;
  for (size_t index = 0; index < size; index++) {
    crc ^= data[index];
    for (uint8_t bit = 0; bit < 8; bit++) {
      crc = (crc >> 1U) ^ ((crc & 1U) ? 0xEDB88320U : 0U);
    }
  }
  return crc ^ 0xFFFFFFFFU;
}

template <size_t PayloadSize>
class CanonicalProfileWriter {
 public:
  explicit CanonicalProfileWriter(uint8_t* payload)
      : payload_(payload), offset_(0), valid_(payload != nullptr) {
    if (payload_) memset(payload_, 0, PayloadSize);
  }

  bool put_u8(uint8_t value) {
    if (!reserve(1)) return false;
    payload_[offset_++] = value;
    return true;
  }

  bool put_bool(bool value) {
    return put_u8(value ? 1U : 0U);
  }

  bool put_u16(uint16_t value) {
    if (!reserve(2)) return false;
    payload_[offset_++] = uint8_t(value);
    payload_[offset_++] = uint8_t(value >> 8U);
    return true;
  }

  bool put_u32(uint32_t value) {
    if (!reserve(4)) return false;
    payload_[offset_++] = uint8_t(value);
    payload_[offset_++] = uint8_t(value >> 8U);
    payload_[offset_++] = uint8_t(value >> 16U);
    payload_[offset_++] = uint8_t(value >> 24U);
    return true;
  }

  bool put_i32(int32_t value) {
    uint32_t bits = 0;
    memcpy(&bits, &value, sizeof(bits));
    return put_u32(bits);
  }

  bool put_float(float value) {
    static_assert(sizeof(float) == sizeof(uint32_t),
                  "canonical profile requires 32-bit float");
    uint32_t bits = 0;
    memcpy(&bits, &value, sizeof(bits));
    return put_u32(bits);
  }

  bool put_bytes(const uint8_t* value, size_t size) {
    if ((size != 0 && !value) || !reserve(size)) return false;
    if (size != 0) memcpy(payload_ + offset_, value, size);
    offset_ += size;
    return true;
  }

  bool finish() const {
    return valid_;
  }

  size_t size() const {
    return offset_;
  }

 private:
  bool reserve(size_t size) {
    if (!valid_ || size > PayloadSize - offset_) {
      valid_ = false;
      return false;
    }
    return true;
  }

  uint8_t* payload_;
  size_t offset_;
  bool valid_;
};

template <size_t PayloadSize>
class CanonicalProfileReader {
 public:
  explicit CanonicalProfileReader(const uint8_t* payload)
      : payload_(payload), offset_(0), valid_(payload != nullptr) {}

  bool get_u8(uint8_t& value) {
    if (!reserve(1)) return false;
    value = payload_[offset_++];
    return true;
  }

  bool get_bool(bool& value) {
    uint8_t encoded = 0;
    if (!get_u8(encoded) || encoded > 1U) {
      valid_ = false;
      return false;
    }
    value = encoded != 0;
    return true;
  }

  bool get_u16(uint16_t& value) {
    if (!reserve(2)) return false;
    value = uint16_t(payload_[offset_]) |
            (uint16_t(payload_[offset_ + 1]) << 8U);
    offset_ += 2;
    return true;
  }

  bool get_u32(uint32_t& value) {
    if (!reserve(4)) return false;
    value = uint32_t(payload_[offset_]) |
            (uint32_t(payload_[offset_ + 1]) << 8U) |
            (uint32_t(payload_[offset_ + 2]) << 16U) |
            (uint32_t(payload_[offset_ + 3]) << 24U);
    offset_ += 4;
    return true;
  }

  bool get_i32(int32_t& value) {
    uint32_t bits = 0;
    if (!get_u32(bits)) return false;
    memcpy(&value, &bits, sizeof(value));
    return true;
  }

  bool get_float(float& value) {
    static_assert(sizeof(float) == sizeof(uint32_t),
                  "canonical profile requires 32-bit float");
    uint32_t bits = 0;
    if (!get_u32(bits)) return false;
    memcpy(&value, &bits, sizeof(value));
    return true;
  }

  bool get_bytes(uint8_t* value, size_t size) {
    if ((size != 0 && !value) || !reserve(size)) return false;
    if (size != 0) memcpy(value, payload_ + offset_, size);
    offset_ += size;
    return true;
  }

  bool finish() {
    if (!valid_) return false;
    while (offset_ < PayloadSize) {
      if (payload_[offset_++] != 0) {
        valid_ = false;
        return false;
      }
    }
    return true;
  }

  size_t size() const {
    return offset_;
  }

 private:
  bool reserve(size_t size) {
    if (!valid_ || size > PayloadSize - offset_) {
      valid_ = false;
      return false;
    }
    return true;
  }

  const uint8_t* payload_;
  size_t offset_;
  bool valid_;
};

template <size_t PayloadSize, uint16_t FormatVersion>
struct ProfileBlobCodec {
  static const size_t HEADER_SIZE = 10;
  static const size_t PAYLOAD_SIZE = PayloadSize;
  static const size_t CRC_SIZE = 4;
  static const size_t BLOB_SIZE = HEADER_SIZE + PAYLOAD_SIZE + CRC_SIZE;

  struct Blob {
    uint8_t bytes[BLOB_SIZE];
  };

  static void encode(const uint8_t* payload, Blob& blob) {
    blob = {};
    blob.bytes[0] = 'S';
    blob.bytes[1] = 'M';
    blob.bytes[2] = 'P';
    blob.bytes[3] = 'F';
    write_u16(blob.bytes + 4, FormatVersion);
    write_u32(blob.bytes + 6, uint32_t(PAYLOAD_SIZE));
    memcpy(blob.bytes + HEADER_SIZE, payload, PAYLOAD_SIZE);
    write_u32(
        blob.bytes + HEADER_SIZE + PAYLOAD_SIZE,
        profile_crc32_iso_hdlc(blob.bytes, HEADER_SIZE + PAYLOAD_SIZE));
  }

  static ProfileCodecResult decode(
      const uint8_t* bytes,
      size_t size,
      uint8_t* payload) {
    if (!bytes || !payload || size != BLOB_SIZE) {
      return PROFILE_CODEC_STORED_SIZE;
    }
    if (bytes[0] != 'S' || bytes[1] != 'M' ||
        bytes[2] != 'P' || bytes[3] != 'F') {
      return PROFILE_CODEC_MAGIC;
    }
    if (read_u16(bytes + 4) != FormatVersion) return PROFILE_CODEC_VERSION;
    if (read_u32(bytes + 6) != PAYLOAD_SIZE) return PROFILE_CODEC_PAYLOAD_SIZE;
    const uint32_t storedCrc = read_u32(bytes + HEADER_SIZE + PAYLOAD_SIZE);
    const uint32_t calculatedCrc =
        profile_crc32_iso_hdlc(bytes, HEADER_SIZE + PAYLOAD_SIZE);
    if (storedCrc != calculatedCrc) return PROFILE_CODEC_CRC;
    memcpy(payload, bytes + HEADER_SIZE, PAYLOAD_SIZE);
    return PROFILE_CODEC_OK;
  }

 private:
  static void write_u16(uint8_t* bytes, uint16_t value) {
    bytes[0] = uint8_t(value);
    bytes[1] = uint8_t(value >> 8U);
  }

  static void write_u32(uint8_t* bytes, uint32_t value) {
    bytes[0] = uint8_t(value);
    bytes[1] = uint8_t(value >> 8U);
    bytes[2] = uint8_t(value >> 16U);
    bytes[3] = uint8_t(value >> 24U);
  }

  static uint16_t read_u16(const uint8_t* bytes) {
    return uint16_t(bytes[0]) | (uint16_t(bytes[1]) << 8U);
  }

  static uint32_t read_u32(const uint8_t* bytes) {
    return uint32_t(bytes[0]) |
           (uint32_t(bytes[1]) << 8U) |
           (uint32_t(bytes[2]) << 16U) |
           (uint32_t(bytes[3]) << 24U);
  }
};
