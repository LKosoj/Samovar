#pragma once

// [WP7 п.38] Раньше строковые настройки (токен Telegram и т.п.) при превышении размера
// буфера молча усекались copyStringSafe: пользователь видел "сохранено", а токен на деле
// был обрезан и уведомления переставали работать. Числовые поля честно отвечают 400 при
// выходе за границы (apply_save_u8_arg/u16_arg выше) - делаем строковые единообразными:
// значение длиннее буфера (N включает место под '\0') отклоняется с тем же кодом ошибки.
// Шаблон в .h, а не в .ino: Arduino IDE иначе вставляет прототип с необъявленным N.
template <size_t N>
static bool apply_save_string_arg(AsyncWebServerRequest *request, const char *name, char (&target)[N]) {
  if (!request->hasArg(name)) return true;
  const AsyncWebParameter *param = get_request_param(request, name);
  if (!param || param->isFile() || param->value().length() >= N) {
    send_save_parse_error(request, name, NUMERIC_PARSE_OUT_OF_RANGE);
    return false;
  }
  copyStringSafe(target, param->value());
  return true;
}
