/* 
 *  Module for displaying disabled debug messages in serial monitor
 *  -----------------------------------------------------------------------------------------------------------------------
 *  (с) 2020-2021 Разживин Александр | Razzhivin Alexander
 *  https://kotyara12.ru | kotyara12@yandex.ru | tg: @kotyara1971
 *
*/

#ifndef __R_LOG_H__
#define __R_LOG_H__

// -----------------------------------------------------------------------------------------------------------------------
// -------------------------------------------- Importing project parameters ---------------------------------------------
// -----------------------------------------------------------------------------------------------------------------------

/* Import global project definitions from "project_config.h"                                                            */
/* WARNING! To make "project_config.h" available here, add "build_flags = -Isrc" to your project configuration file:    */
/*                                                                                                                      */
/* [env]                                                                                                                */
/* build_flags = -Isrc                                                                                                  */
/*                                                                                                                      */
/* and place the file in the src directory of the project                                                               */

#if defined (__has_include)
  /* Import only if file exists in "src" directory */
  #if __has_include("project_config.h") 
    #include "project_config.h"
  #endif
#else
  /* Force import if compiler doesn't support __has_include (ESP8266, etc) */
  #include "project_config.h"
#endif

/* If the parameters were not received, we use the default values. */
#ifndef CONFIG_RLOG_PROJECT_LEVEL
#define CONFIG_RLOG_PROJECT_LEVEL RLOG_LEVEL_ERROR
#endif
#ifndef CONFIG_RLOG_PROJECT_COLORS
#define CONFIG_RLOG_PROJECT_COLORS 0
#endif
#ifndef CONFIG_RLOG_SHOW_TIMESTAMP
#define CONFIG_RLOG_SHOW_TIMESTAMP 1
#endif
#ifndef CONFIG_RLOG_SHOW_FILEINFO
#define CONFIG_RLOG_SHOW_FILEINFO 1
#endif

// -----------------------------------------------------------------------------------------------------------------------
// ------------------------------------------ End of import of project parameters ----------------------------------------
// -----------------------------------------------------------------------------------------------------------------------

#ifdef __cplusplus
extern "C"
{
#endif

/* Log output levels */
#define RLOG_LEVEL_NONE       (0)    /* No log output */
#define RLOG_LEVEL_ERROR      (1)    /* Critical errors, software module can not recover on its own */
#define RLOG_LEVEL_WARN       (2)    /* Error conditions from which recovery measures have been taken */
#define RLOG_LEVEL_INFO       (3)    /* Information messages which describe normal flow of events */
#define RLOG_LEVEL_DEBUG      (4)    /* Extra information which is not necessary for normal use (values, pointers, sizes, etc). */
#define RLOG_LEVEL_VERBOSE    (5)    /* Bigger chunks of debugging information, or frequent messages which can potentially flood the output. */

/* Log colors */
#if CONFIG_RLOG_PROJECT_COLORS
#define RLOG_COLOR_BLACK   "30"
#define RLOG_COLOR_RED     "31" //ERROR
#define RLOG_COLOR_GREEN   "32" //INFO
#define RLOG_COLOR_YELLOW  "33" //WARNING
#define RLOG_COLOR_BLUE    "34"
#define RLOG_COLOR_MAGENTA "35"
#define RLOG_COLOR_CYAN    "36" //DEBUG
#define RLOG_COLOR_GRAY    "37" //VERBOSE
#define RLOG_COLOR_WHITE   "38"

#define RLOG_COLOR(COLOR)  "\033[0;" COLOR "m"
#define RLOG_BOLD(COLOR)   "\033[1;" COLOR "m"
#define RLOG_RESET_COLOR   "\033[0m"

#define RLOG_COLOR_E       RLOG_BOLD(RLOG_COLOR_RED)
#define RLOG_COLOR_W       RLOG_COLOR(RLOG_COLOR_YELLOW)
#define RLOG_COLOR_I       RLOG_COLOR(RLOG_COLOR_GREEN)
#define RLOG_COLOR_D       RLOG_COLOR(RLOG_COLOR_CYAN)
#define RLOG_COLOR_V       RLOG_COLOR(RLOG_COLOR_GRAY)
#else
#define RLOG_COLOR_E
#define RLOG_COLOR_W
#define RLOG_COLOR_I
#define RLOG_COLOR_D
#define RLOG_COLOR_V
#define RLOG_RESET_COLOR
#endif

#if CONFIG_RLOG_PROJECT_LEVEL >= RLOG_LEVEL_NONE

/* Internal functions */
int _rlog_printf(const char *format, ...);
const char * _rlog_system_timestamp(void);
const char * _rlog_filename(const char * path);

#define RLOG_DEFAULT_APP_TAG "RTOS"

/* Log formats */
#if CONFIG_RLOG_SHOW_TIMESTAMP

#if CONFIG_RLOG_SHOW_FILEINFO

#define RLOG_STD_FORMAT(letter, format) RLOG_COLOR_ ## letter "%s [" #letter "] %s :: " format RLOG_RESET_COLOR "\r\n", _rlog_system_timestamp()
#define RLOG_EXT_FORMAT(letter, format) RLOG_COLOR_ ## letter "%s [" #letter "] {%s:%.3u %s()} %s :: " format RLOG_RESET_COLOR "\r\n", _rlog_system_timestamp(), _rlog_filename(__FILE__), __LINE__, __FUNCTION__

#else

#define RLOG_STD_FORMAT(letter, format) RLOG_COLOR_ ## letter "%s [" #letter "] %s :: " format RLOG_RESET_COLOR "\r\n", _rlog_system_timestamp()
#define RLOG_EXT_FORMAT(letter, format) RLOG_COLOR_ ## letter "%s [" #letter "] %s :: " format RLOG_RESET_COLOR "\r\n", _rlog_system_timestamp()

#endif // CONFIG_RLOG_SHOW_FILEINFO

#else

#if CONFIG_RLOG_SHOW_FILEINFO

#define RLOG_STD_FORMAT(letter, format) RLOG_COLOR_ ## letter "[" #letter "] %s :: " format RLOG_RESET_COLOR "\r\n"
#define RLOG_EXT_FORMAT(letter, format) RLOG_COLOR_ ## letter "[" #letter "] {%s:%.3u %s()} %s :: " format RLOG_RESET_COLOR "\r\n", _rlog_filename(__FILE__), __LINE__, __FUNCTION__

#else

#define RLOG_STD_FORMAT(letter, format) RLOG_COLOR_ ## letter "[" #letter "] %s :: " format RLOG_RESET_COLOR "\r\n"
#define RLOG_EXT_FORMAT(letter, format) RLOG_COLOR_ ## letter "[" #letter "] %s :: " format RLOG_RESET_COLOR "\r\n"

#endif // CONFIG_RLOG_SHOW_FILEINFO

#endif // CONFIG_RLOG_SHOW_TIMESTAMP

#define rlog_empty() _rlog_printf("\r\n")

#else 

#define rlog_empty()

#endif // CONFIG_RLOG_PROJECT_LEVEL >= RLOG_LEVEL_NONE

/* Basic functions */
#if CONFIG_RLOG_PROJECT_LEVEL >= RLOG_LEVEL_VERBOSE
#define rlog_v(tag, format, ...) _rlog_printf(RLOG_EXT_FORMAT(V, format), tag, ##__VA_ARGS__)
#define rloga_v(format, ...) _rlog_printf(RLOG_EXT_FORMAT(V, format), RLOG_DEFAULT_APP_TAG, ##__VA_ARGS__)
#else
#define rlog_v(tag, format, ...)
#define rloga_v(format, ...)
#endif

#if CONFIG_RLOG_PROJECT_LEVEL >= RLOG_LEVEL_DEBUG
#define rlog_d(tag, format, ...) _rlog_printf(RLOG_EXT_FORMAT(D, format), tag, ##__VA_ARGS__)
#define rloga_d(format, ...) _rlog_printf(RLOG_EXT_FORMAT(D, format), RLOG_DEFAULT_APP_TAG, ##__VA_ARGS__)
#else
#define rlog_d(tag, format, ...)
#define rloga_d(format, ...)
#endif

#if CONFIG_RLOG_PROJECT_LEVEL >= RLOG_LEVEL_INFO
#define rlog_i(tag, format, ...) _rlog_printf(RLOG_STD_FORMAT(I, format), tag, ##__VA_ARGS__)
#define rloga_i(format, ...) _rlog_printf(RLOG_STD_FORMAT(I, format), RLOG_DEFAULT_APP_TAG, ##__VA_ARGS__)
#else
#define rlog_i(tag, format, ...)
#define rloga_i(format, ...)
#endif

#if CONFIG_RLOG_PROJECT_LEVEL >= RLOG_LEVEL_WARN
#define rlog_w(tag, format, ...) _rlog_printf(RLOG_EXT_FORMAT(W, format), tag, ##__VA_ARGS__)
#define rloga_w(format, ...) _rlog_printf(RLOG_EXT_FORMAT(W, format), RLOG_DEFAULT_APP_TAG, ##__VA_ARGS__)
#else
#define rlog_w(tag, format, ...)
#define rloga_w(format, ...)
#endif

#if CONFIG_RLOG_PROJECT_LEVEL >= RLOG_LEVEL_ERROR
#define rlog_e(tag, format, ...) _rlog_printf(RLOG_EXT_FORMAT(E, format), tag, ##__VA_ARGS__)
#define rloga_e(format, ...) _rlog_printf(RLOG_EXT_FORMAT(E, format), RLOG_DEFAULT_APP_TAG, ##__VA_ARGS__)
#else
#define rlog_e(tag, format, ...)
#define rloga_e(format, ...)
#endif

#ifdef __cplusplus
}
#endif

#endif /* __R_LOG_H__ */
