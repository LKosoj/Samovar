#ifndef __SAMOVAR_LOOP_DISPATCH_H_
#define __SAMOVAR_LOOP_DISPATCH_H_

#include "Samovar.h"
#include "state/globals.h"
#include "app/process_common.h"
#include "io/actuators.h"
#include "io/power_control.h"
#include "modes/beer/beer_runtime.h"
#include "modes/bk/bk_finish.h"
#include "modes/bk/bk_runtime.h"
#include "modes/dist/dist_runtime.h"
#include "modes/nbk/nbk_finish.h"
#include "modes/nbk/nbk_runtime.h"
#include "modes/rect/rect_runtime.h"

void menu_samovar_start();
void detector_on_manual_resume();
void samovar_reset();
inline void process_sam_command_sync() {
  if (sam_command_sync == SAMOVAR_NONE) return;

  switch (sam_command_sync) {
    case SAMOVAR_START:
      Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
      menu_samovar_start();
      break;
    case SAMOVAR_POWER:
      if (SamovarStatusInt == SAMOVAR_STATUS_DISTILLATION) distiller_finish();
      else if (SamovarStatusInt == SAMOVAR_STATUS_BEER)
        beer_finish();
      else if (SamovarStatusInt == SAMOVAR_STATUS_BK)
        bk_finish();
      else if (SamovarStatusInt == SAMOVAR_STATUS_NBK)
        nbk_finish();
      else
        set_power(!PowerOn);
      if (PowerOn && Samovar_Mode == SAMOVAR_RECTIFICATION_MODE) {
        SamovarStatusInt = SAMOVAR_STATUS_RECTIFICATION_WARMUP;
      }
      break;
    case SAMOVAR_RESET:
      samovar_reset();
      break;
    case CALIBRATE_START:
      pump_calibrate(CurrrentStepperSpeed);
      break;
    case CALIBRATE_STOP:
      pump_calibrate(0);
      break;
    case SAMOVAR_PAUSE:
      pause_withdrawal(true);
      break;
    case SAMOVAR_CONTINUE:
      pause_withdrawal(false);
      t_min = 0;
      program_Wait = false;
      detector_on_manual_resume();
      break;
    case SAMOVAR_SETBODYTEMP:
      set_body_temp();
      break;
    case SAMOVAR_DISTILLATION:
      Samovar_Mode = SAMOVAR_DISTILLATION_MODE;
      SamovarStatusInt = SAMOVAR_STATUS_DISTILLATION;
      startval = SAMOVAR_STARTVAL_DISTILLATION_ENTRY;
      break;
    case SAMOVAR_BEER:
      Samovar_Mode = SAMOVAR_BEER_MODE;
      SamovarStatusInt = SAMOVAR_STATUS_BEER;
      startval = SAMOVAR_STARTVAL_BEER_ENTRY;
      break;
    case SAMOVAR_BEER_NEXT:
      run_beer_program(ProgramNum + 1);
      break;
    case SAMOVAR_DIST_NEXT:
      run_dist_program(ProgramNum + 1);
      break;
    case SAMOVAR_BK:
      Samovar_Mode = SAMOVAR_BK_MODE;
      SamovarStatusInt = SAMOVAR_STATUS_BK;
      startval = SAMOVAR_STARTVAL_BK_ENTRY;
      break;
    case SAMOVAR_NBK:
      Samovar_Mode = SAMOVAR_NBK_MODE;
      SamovarStatusInt = SAMOVAR_STATUS_NBK;
      startval = SAMOVAR_STARTVAL_NBK_ENTRY;
      break;
    case SAMOVAR_NBK_NEXT:
      run_nbk_program(ProgramNum + 1);
      break;
    case SAMOVAR_SELF_TEST:
      start_self_test();
      break;
    case SAMOVAR_NONE:
      break;
  }
  if (sam_command_sync != SAMOVAR_RESET) {
    sam_command_sync = SAMOVAR_NONE;
  }
}

inline void dispatch_samovar_mode_runtime() {
  if (SamovarStatusInt > SAMOVAR_STATUS_OFF && SamovarStatusInt < SAMOVAR_STATUS_DISTILLATION) {
    withdrawal();
  } else if (SamovarStatusInt == SAMOVAR_STATUS_DISTILLATION) {
    distiller_proc();
  } else if (SamovarStatusInt == SAMOVAR_STATUS_BK) {
    bk_proc();
  } else if (SamovarStatusInt == SAMOVAR_STATUS_NBK) {
    nbk_proc();
  } else if (SamovarStatusInt == SAMOVAR_STATUS_BEER && startval == SAMOVAR_STARTVAL_BEER_ENTRY) {
    beer_proc();
  }
}

#endif
