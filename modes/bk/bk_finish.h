#ifndef __SAMOVAR_BK_FINISH_H_
#define __SAMOVAR_BK_FINISH_H_

#include <Arduino.h>

#include "Samovar.h"
#include "state/globals.h"
#include "app/process_common.h"

inline void bk_finish() {
  stop_process("Работа бражной колонны завершена");
}

#endif
