#!/usr/bin/env python3
"""Проверяет отказ выделения и границу uint16_t в xbuf библиотеки HTTP."""

from pathlib import Path
import subprocess
import tempfile

from smoke_helpers import extract_function_body


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "libraries/asyncHTTPrequest/src/xbuf.cpp").read_text()
errors: list[str] = []


def body(signature: str) -> str:
    try:
        return extract_function_body(SOURCE, signature, strip_comments=False)
    except ValueError as exc:
        errors.append(str(exc))
        return ""


add_seg = body("bool        xbuf::addSeg()")
write_bytes = body("size_t      xbuf::write(const uint8_t* buf, const size_t len)")
write_xbuf = body("size_t      xbuf::write(xbuf* buf, const size_t len)")
read_bytes = body("size_t      xbuf::read(uint8_t* buf, const size_t len)")
available = body("size_t      xbuf::available()")
flush = body("void        xbuf::flush()")
rem_seg = body("void        xbuf::remSeg()")

if "new (std::nothrow)" not in add_seg or "if(!segment) return false;" not in add_seg:
    errors.append("addSeg must return false before changing the chain on allocation failure")
if "UINT16_MAX - _used" not in write_bytes or "UINT16_MAX - _used" not in write_xbuf:
    errors.append("both write overloads must cap _used at UINT16_MAX")


HARNESS = r'''
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <new>
#include <string>

class String {
 public:
  String() = default;
  explicit String(const char* value) : value_(value ? value : "") {}
  const char* c_str() const { return value_.c_str(); }
  size_t length() const { return value_.length(); }
 private:
  std::string value_;
};
class Print {};

static int allocationCalls = 0;
static int failAt = -1;
void* operator new[](std::size_t size, const std::nothrow_t&) noexcept {
  if (failAt >= 0 && allocationCalls++ >= failAt) return nullptr;
  // Production segments reserve a 4-byte ESP32 pointer; the host pointer is wider.
  return std::malloc(size + sizeof(void*) - sizeof(uint32_t));
}
void operator delete[](void* pointer) noexcept { std::free(pointer); }

#include "xbuf.h"

xbuf::xbuf(const uint16_t segSize) : _head(nullptr), _tail(nullptr), _used(0),
    _free(0), _offset(0) { _segSize = (segSize + 3) & -4; }
xbuf::~xbuf() { flush(); }
size_t xbuf::write(const uint8_t byte) { return write((uint8_t*)&byte, 1); }
size_t xbuf::write(const char* buf) { return write((uint8_t*)buf, strlen(buf)); }
size_t xbuf::write(String string) { return write((uint8_t*)string.c_str(), string.length()); }
size_t xbuf::write(const uint8_t* buf, const size_t len) { @WRITE_BYTES@ }
size_t xbuf::write(xbuf* buf, const size_t len) { @WRITE_XBUF@ }
size_t xbuf::read(uint8_t* buf, const size_t len) { @READ_BYTES@ }
size_t xbuf::available() { @AVAILABLE@ }
void xbuf::flush() { @FLUSH@ }
bool xbuf::addSeg() { @ADD_SEG@ }
void xbuf::remSeg() { @REM_SEG@ }

static void check(bool condition, const char* message) {
  if (!condition) { std::cerr << "FAIL: " << message << '\n'; std::exit(1); }
}
static void resetAllocator(int fail) { allocationCalls = 0; failAt = fail; }
static std::string readAll(xbuf& buffer) {
  std::string result(buffer.available(), '\0');
  buffer.read(reinterpret_cast<uint8_t*>(result.data()), result.size());
  return result;
}

int main() {
  resetAllocator(-1);
  xbuf successful(4);
  const uint8_t first[] = {'a', 'b', 'c'};
  const uint8_t second[] = {'d', 'e', 'f', 'g', 'h'};
  check(successful.write(first, sizeof(first)) == sizeof(first), "first write length");
  check(successful.write(second, sizeof(second)) == sizeof(second), "second write length");
  check(successful.available() == 8 && readAll(successful) == "abcdefgh",
        "successful writes must preserve both lengths and order");

  resetAllocator(0);
  xbuf firstFailure(4);
  check(firstFailure.write(first, sizeof(first)) == 0 && firstFailure.available() == 0,
        "first allocation failure must return zero and keep the buffer empty");

  resetAllocator(1);
  xbuf nextFailure(4);
  check(nextFailure.write(second, sizeof(second)) == 4 && nextFailure.available() == 4,
        "next allocation failure must return the partial byte count");
  check(readAll(nextFailure) == "defg", "partial write must preserve the first segment");

  resetAllocator(-1);
  xbuf source(4);
  const uint8_t sourceBytes[] = {'a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'};
  check(source.write(sourceBytes, sizeof(sourceBytes)) == sizeof(sourceBytes),
        "source setup");
  resetAllocator(1);
  xbuf destination(4);
  check(destination.write(&source, sizeof(sourceBytes)) == 4,
        "xbuf copy must stop at the failed destination segment");
  check(readAll(destination) == "abcd" && readAll(source) == "efgh",
        "xbuf copy must preserve untransferred source bytes and both chains");

  resetAllocator(-1);
  xbuf bounded(64);
  std::string large(UINT16_MAX + 8, 'x');
  for (size_t index = 0; index < large.size(); index++) large[index] = 'a' + index % 26;
  check(bounded.write(reinterpret_cast<const uint8_t*>(large.data()), large.size()) == UINT16_MAX,
        "byte write must stop at UINT16_MAX");
  check(bounded.available() == UINT16_MAX, "_used must never wrap");
  std::string prefix(26, '\0');
  bounded.read(reinterpret_cast<uint8_t*>(prefix.data()), prefix.size());
  check(prefix == large.substr(0, prefix.size()), "bounded write must start at the source prefix");
  return 0;
}
'''

for marker, replacement in (
    ("@WRITE_BYTES@", write_bytes),
    ("@WRITE_XBUF@", write_xbuf),
    ("@READ_BYTES@", read_bytes),
    ("@AVAILABLE@", available),
    ("@FLUSH@", flush),
    ("@ADD_SEG@", add_seg),
    ("@REM_SEG@", rem_seg),
):
    HARNESS = HARNESS.replace(marker, replacement)

if not errors:
    with tempfile.TemporaryDirectory(prefix="samovar-xbuf-") as directory:
        directory_path = Path(directory)
        (directory_path / "Arduino.h").write_text("#include <cstdint>\n#include <cstddef>\n", encoding="utf-8")
        source_path = directory_path / "xbuf.cpp"
        source_path.write_text(HARNESS, encoding="utf-8")
        result = subprocess.run(
            ["g++", "-std=c++17", "-I", str(directory_path), "-I", str(ROOT / "libraries/asyncHTTPrequest/src"),
             str(source_path), "-o", str(directory_path / "xbuf-test")],
            capture_output=True, text=True,
        )
        if result.returncode:
            errors.append(f"compile failed:\n{result.stderr}")
        else:
            result = subprocess.run([str(directory_path / "xbuf-test")], capture_output=True, text=True)
            if result.returncode:
                errors.append(f"behavior failed:\n{result.stdout}{result.stderr}")

if errors:
    print("HTTP xbuf memory smoke failed:")
    for error in errors:
        print(f"- {error}")
    raise SystemExit(1)
print("HTTP xbuf memory smoke passed")
