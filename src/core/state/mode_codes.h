#ifndef __SAMOVAR_MODE_CODES_H_
#define __SAMOVAR_MODE_CODES_H_

#include <stdint.h>

enum SAMOVAR_MODE {
  SAMOVAR_RECTIFICATION_MODE = 0,
  SAMOVAR_DISTILLATION_MODE = 1,
  SAMOVAR_BEER_MODE = 2,
  SAMOVAR_BK_MODE = 3,
  SAMOVAR_NBK_MODE = 4,
  SAMOVAR_SUVID_MODE = 5,
  SAMOVAR_LUA_MODE = 6
};

static constexpr int16_t SAMOVAR_STARTVAL_RECT_IDLE = 0;
static constexpr int16_t SAMOVAR_STARTVAL_RECT_PROGRAM_RUNNING = 1;
static constexpr int16_t SAMOVAR_STARTVAL_RECT_PROGRAM_COMPLETE = 2;
static constexpr int16_t SAMOVAR_STARTVAL_RECT_STOPPED = 3;
static constexpr int16_t SAMOVAR_STARTVAL_CALIBRATION = 100;
static constexpr int16_t SAMOVAR_STARTVAL_DISTILLATION_ENTRY = 1000;
static constexpr int16_t SAMOVAR_STARTVAL_BEER_ENTRY = 2000;
static constexpr int16_t SAMOVAR_STARTVAL_BEER_MALT_HEATING = 2001;
static constexpr int16_t SAMOVAR_STARTVAL_BEER_MALT_WAIT = 2002;
static constexpr int16_t SAMOVAR_STARTVAL_BK_ENTRY = 3000;
static constexpr int16_t SAMOVAR_STARTVAL_NBK_ENTRY = 4000;
static constexpr int16_t SAMOVAR_STARTVAL_NBK_PROGRAM_RUNNING = 4001;

inline bool startval_is_rect_program_state(int16_t value) {
  return value > SAMOVAR_STARTVAL_RECT_IDLE && value <= SAMOVAR_STARTVAL_RECT_STOPPED;
}

inline bool startval_is_active_non_calibration(int16_t value) {
  return value > SAMOVAR_STARTVAL_RECT_IDLE && value != SAMOVAR_STARTVAL_CALIBRATION;
}

inline bool startval_is_beer_program_started(int16_t value) {
  return value > SAMOVAR_STARTVAL_BEER_ENTRY;
}

#endif
