#pragma once
// Мультиязычность прошивки. Русский - исходный язык и остаётся в коде: TR(KEY, "русский текст").
// Язык выбирается при прошивке: #define SAMOVAR_LANG en (user_config_override.h или -D в сборке).
// Перевод лежит в lang_<код>.h, ключ LANG_<KEY>. Нет перевода - ошибка компиляции
// ('LANG_<KEY>' was not declared); нет файла языка - ошибка "lang_<код>.h: No such file".
// Файл самодостаточен (без Arduino.h): его подключают и тестовые харнессы на g++.
#ifndef SAMOVAR_LANG
#define SAMOVAR_LANG ru
#endif
#define SAMOVAR_I18N_STR_(x) #x
#define SAMOVAR_I18N_STR(x) SAMOVAR_I18N_STR_(x)
#define SAMOVAR_I18N_HEADER_(code) SAMOVAR_I18N_STR(lang_##code.h)
#define SAMOVAR_I18N_HEADER(code) SAMOVAR_I18N_HEADER_(code)
#define SAMOVAR_LANG_CODE SAMOVAR_I18N_STR(SAMOVAR_LANG)
#include SAMOVAR_I18N_HEADER(SAMOVAR_LANG)
#ifndef SAMOVAR_LANG_NAME
#error lang file must define SAMOVAR_LANG_NAME
#endif
#ifdef SAMOVAR_LANG_SOURCE
#define TR(key, ru) ru
#else
#define TR(key, ru) LANG_##key
#endif
