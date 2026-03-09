#ifndef __SAMOVAR_NBK_STATE_H_
#define __SAMOVAR_NBK_STATE_H_

#include <Arduino.h>

#include "Samovar.h"
#include "state/globals.h"

struct NbkStats {
  float avgSpeed;
  float totalVolume;
  uint32_t startTime;
  uint32_t lastVolumeUpdate;
};

extern NbkStats stats;

#define NBK_COLUMN_INERTIA_DEFAULT 180
#define NBK_OVERFLOW_PRESSURE_DEFAULT 40
#define NBK_TN_DEFAULT 98.5
#define NBK_DT_DEFAULT 0.5
#define NBK_DM_DEFAULT 100
#define NBK_DP_DEFAULT 0.5
#define NBK_TP_DEFAULT 81
#define NBK_OPERATING_RANGE 100

extern uint16_t nbk_column_inertia;
extern float nbk_overflow_pressure;
extern float nbk_M;
extern float nbk_M_max;
extern float nbk_Mo;
extern float nbk_dM;
extern float nbk_P;
extern float nbk_Po;
extern float nbk_dP;
extern float nbk_Tb;
extern float nbk_Tn;
extern float nbk_Tp;
extern float nbk_Tvody;
extern float nbk_dD;
extern float nbk_dT;
extern float nbk_Tp_lim;

extern uint8_t nbk_opt_iter;
extern uint32_t nbk_opt_next_time;
extern uint32_t time_speed;
extern bool nbk_opt_in_progress;

extern uint32_t nbk_work_next_time;
extern bool nbk_work_in_pause;
extern bool workrun;
extern uint8_t nbk_work_pause_stage;
extern float nbk_Mo_temp;
extern float nbk_Po_temp;
extern bool manual_overflow;
extern bool noDZ_message_sent;

#endif
