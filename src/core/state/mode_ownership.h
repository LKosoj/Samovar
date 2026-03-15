#ifndef __SAMOVAR_MODE_OWNERSHIP_H_
#define __SAMOVAR_MODE_OWNERSHIP_H_

#include "src/core/state/mode_codes.h"

inline SAMOVAR_MODE mode_runtime_owner(SAMOVAR_MODE mode) {
  switch (mode) {
    case SAMOVAR_BEER_MODE:
      return SAMOVAR_BEER_MODE;
    case SAMOVAR_DISTILLATION_MODE:
      return SAMOVAR_DISTILLATION_MODE;
    case SAMOVAR_BK_MODE:
      return SAMOVAR_BK_MODE;
    case SAMOVAR_NBK_MODE:
      return SAMOVAR_NBK_MODE;
    case SAMOVAR_RECTIFICATION_MODE:
    case SAMOVAR_SUVID_MODE:
    case SAMOVAR_LUA_MODE:
    default:
      return SAMOVAR_RECTIFICATION_MODE;
  }
}

inline SAMOVAR_MODE mode_program_owner(SAMOVAR_MODE mode) {
  switch (mode) {
    case SAMOVAR_BEER_MODE:
    case SAMOVAR_SUVID_MODE:
      return SAMOVAR_BEER_MODE;
    case SAMOVAR_DISTILLATION_MODE:
      return SAMOVAR_DISTILLATION_MODE;
    case SAMOVAR_NBK_MODE:
      return SAMOVAR_NBK_MODE;
    case SAMOVAR_RECTIFICATION_MODE:
    case SAMOVAR_BK_MODE:
    case SAMOVAR_LUA_MODE:
    default:
      return SAMOVAR_RECTIFICATION_MODE;
  }
}

inline SAMOVAR_MODE mode_lua_owner(SAMOVAR_MODE mode) {
  switch (mode) {
    case SAMOVAR_BEER_MODE:
      return SAMOVAR_BEER_MODE;
    case SAMOVAR_DISTILLATION_MODE:
      return SAMOVAR_DISTILLATION_MODE;
    case SAMOVAR_BK_MODE:
      return SAMOVAR_BK_MODE;
    case SAMOVAR_NBK_MODE:
      return SAMOVAR_NBK_MODE;
    case SAMOVAR_RECTIFICATION_MODE:
    case SAMOVAR_SUVID_MODE:
    case SAMOVAR_LUA_MODE:
    default:
      return SAMOVAR_RECTIFICATION_MODE;
  }
}

inline const char* mode_active_page(SAMOVAR_MODE mode) {
  switch (mode_runtime_owner(mode)) {
    case SAMOVAR_BEER_MODE:
      return "/beer.htm";
    case SAMOVAR_DISTILLATION_MODE:
      return "/distiller.htm";
    case SAMOVAR_BK_MODE:
      return "/bk.htm";
    case SAMOVAR_NBK_MODE:
      return "/nbk.htm";
    case SAMOVAR_RECTIFICATION_MODE:
    default:
      return "/index.htm";
  }
}

inline const char* mode_profile_namespace(SAMOVAR_MODE mode) {
  switch (mode) {
    case SAMOVAR_BEER_MODE:
      return "sam_beer";
    case SAMOVAR_DISTILLATION_MODE:
      return "sam_dist";
    case SAMOVAR_BK_MODE:
      return "sam_bk";
    case SAMOVAR_NBK_MODE:
      return "sam_nbk";
    case SAMOVAR_SUVID_MODE:
      return "sam_suvid";
    case SAMOVAR_LUA_MODE:
      return "sam_lua";
    case SAMOVAR_RECTIFICATION_MODE:
    default:
      return "sam_rect";
  }
}

inline bool mode_is_rect_runtime(SAMOVAR_MODE mode) {
  return mode_runtime_owner(mode) == SAMOVAR_RECTIFICATION_MODE;
}

inline bool mode_is_distillation_runtime(SAMOVAR_MODE mode) {
  return mode_runtime_owner(mode) == SAMOVAR_DISTILLATION_MODE;
}

inline bool mode_is_beer_runtime(SAMOVAR_MODE mode) {
  return mode_runtime_owner(mode) == SAMOVAR_BEER_MODE;
}

inline bool mode_is_bk_runtime(SAMOVAR_MODE mode) {
  return mode_runtime_owner(mode) == SAMOVAR_BK_MODE;
}

inline bool mode_is_nbk_runtime(SAMOVAR_MODE mode) {
  return mode_runtime_owner(mode) == SAMOVAR_NBK_MODE;
}

#endif
