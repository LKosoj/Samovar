#pragma once

#include <Arduino.h>

// Параметры команды I2CStepper (device, cmd, поля конфига, relay/state) без привязки
// к источнику: веб-обработчик /i2cstepper переписывает их из AsyncWebServerRequest,
// Blynk V37 разбирает строку вида device=pump&cmd=start&mode=2. Разбор и проверка
// (parse_i2c_stepper_patch, WebServer.ino) общие для обоих путей. Интерфейс
// намеренно повторяет AsyncWebServerRequest (params/getParam, name()/value()),
// чтобы тело проверки не менялось.
struct I2CStepperParam {
  String name_;
  String value_;
  const String& name() const { return name_; }
  const String& value() const { return value_; }
};

class I2CStepperParams {
 public:
  // device, cmd, 12 полей конфига, relay, state - больше корректный запрос не содержит.
  static const size_t kMax = 16;

  size_t params() const { return count_; }
  const I2CStepperParam* getParam(size_t index) const {
    return index < count_ ? &items_[index] : nullptr;
  }
  bool add(const String& name, const String& value) {
    if (count_ >= kMax) return false;
    items_[count_].name_ = name;
    items_[count_].value_ = value;
    count_++;
    return true;
  }
  // Строка вида a=b&c=d. Без url-декодирования: значения - числа и слова.
  // false - параметров больше kMax; что успело разобраться, остаётся.
  bool parseQuery(const char* query) {
    if (!query) return true;
    const char* p = query;
    while (*p) {
      const char* end = strchr(p, '&');
      const size_t len = end ? size_t(end - p) : strlen(p);
      if (len) {
        const char* eq = static_cast<const char*>(memchr(p, '=', len));
        String name(p, eq ? size_t(eq - p) : len);
        String value(eq ? eq + 1 : p + len, eq ? len - size_t(eq - p) - 1 : 0);
        if (!add(name, value)) return false;
      }
      if (!end) break;
      p = end + 1;
    }
    return true;
  }

 private:
  I2CStepperParam items_[kMax];
  size_t count_ = 0;
};

inline uint8_t request_param_count(const I2CStepperParams *request, const char *name) {
  if (!request || !name) return 0;
  uint8_t count = 0;
  for (size_t i = 0; i < request->params(); i++) {
    const I2CStepperParam *param = request->getParam(i);
    if (param && param->name() == name && count < UINT8_MAX) count++;
  }
  return count;
}

inline const I2CStepperParam* get_request_param(const I2CStepperParams *request, const char *name) {
  if (!request || !name) return nullptr;
  for (size_t i = 0; i < request->params(); i++) {
    const I2CStepperParam *param = request->getParam(i);
    if (param && param->name() == name) return param;
  }
  return nullptr;
}
