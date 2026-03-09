#ifndef __SAMOVAR_LOOP_DISPATCH_H_
#define __SAMOVAR_LOOP_DISPATCH_H_

#include "Samovar.h"
#include "state/globals.h"
#include "app/process_common.h"
#include "io/actuators.h"
#include "io/power_control.h"
#include "modes/rect/rect_runtime.h"

void menu_samovar_start();
void detector_on_manual_resume();
void samovar_reset();
void distiller_finish();
void beer_finish();
void bk_finish();
void nbk_finish();
void distiller_proc();
void beer_proc();
void bk_proc();
void nbk_proc();
void run_beer_program(uint8_t num);
void run_dist_program(uint8_t num);
void run_nbk_program(uint8_t num);

inline void process_sam_command_sync() {
  if (sam_command_sync == SAMOVAR_NONE) return;

  switch (sam_command_sync) {
    case SAMOVAR_START:
      Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;
      menu_samovar_start();
      break;
    case SAMOVAR_POWER:
      if (SamovarStatusInt == 1000) distiller_finish();
      else if (SamovarStatusInt == 2000)
        beer_finish();
      else if (SamovarStatusInt == 3000)
        bk_finish();
      else if (SamovarStatusInt == 4000)
        nbk_finish();
      else
        set_power(!PowerOn);
      if (PowerOn && Samovar_Mode == SAMOVAR_RECTIFICATION_MODE) {
        SamovarStatusInt = 50;
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
      SamovarStatusInt = 1000;
      startval = 1000;
      break;
    case SAMOVAR_BEER:
      Samovar_Mode = SAMOVAR_BEER_MODE;
      SamovarStatusInt = 2000;
      startval = 2000;
      break;
    case SAMOVAR_BEER_NEXT:
      run_beer_program(ProgramNum + 1);
      break;
    case SAMOVAR_DIST_NEXT:
      run_dist_program(ProgramNum + 1);
      break;
    case SAMOVAR_BK:
      Samovar_Mode = SAMOVAR_BK_MODE;
      SamovarStatusInt = 3000;
      startval = 3000;
      break;
    case SAMOVAR_NBK:
      Samovar_Mode = SAMOVAR_NBK_MODE;
      SamovarStatusInt = 4000;
      startval = 4000;
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
  if (SamovarStatusInt > 0 && SamovarStatusInt < 1000) {
    withdrawal();
  } else if (SamovarStatusInt == 1000) {
    distiller_proc();
  } else if (SamovarStatusInt == 3000) {
    bk_proc();
  } else if (SamovarStatusInt == 4000) {
    nbk_proc();
  } else if (SamovarStatusInt == 2000 && startval == 2000) {
    beer_proc();
  }
}

#endif
