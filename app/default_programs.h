#ifndef __SAMOVAR_APP_DEFAULT_PROGRAMS_H_
#define __SAMOVAR_APP_DEFAULT_PROGRAMS_H_

#include <Arduino.h>

#include "modes/beer/beer_program_codec.h"
#include "modes/dist/dist_program_codec.h"
#include "modes/nbk/nbk_program_codec.h"
#include "modes/rect/rect_program_codec.h"
#include "state/globals.h"

inline void load_default_program_for_mode() {
  if (Samovar_Mode == SAMOVAR_BEER_MODE || Samovar_Mode == SAMOVAR_SUVID_MODE) {
    set_beer_program("M;45;0;0^-1^2^2;0\nP;45;1;0^-1^2^3;0\nP;60;1;0^-1^2^3;0\nW;0;0;0^-1^2^3;0\nB;0;1;0^-1^2^3;0\nC;30;0;0^-1^2^3;0\n");
  } else if (Samovar_Mode == SAMOVAR_DISTILLATION_MODE) {
    set_dist_program("A;80.00;1;0\nS;0.50;2;0\nS;0.30;3;0\n");
  } else if (Samovar_Mode == SAMOVAR_NBK_MODE) {
    set_nbk_program(NBK_DEFAULT_PROGRAM);
  } else {
    set_program("H;450;0.1;1;0;45\nB;450;1;1;0;45\nH;450;0.1;1;0;45\n");
  }
}

#endif
