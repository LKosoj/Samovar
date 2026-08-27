#pragma once

// Шаблон нельзя держать в .ino: Arduino IDE вставляет прототип без
// `template <typename T>`, и компилятор сообщает, что T не объявлен.
template <typename T>
static inline void jsonFieldRaw(Print &out, bool &first, const char *key, T value) {
  jsonAddKey(out, first, key);
  out.print(value);
}
