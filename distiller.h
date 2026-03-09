#include <Arduino.h>
#include "Samovar.h"
#include "state/globals.h"
#include "app/alarm_control.h"
#include "app/process_common.h"
#include "io/actuators.h"
#include "io/power_control.h"
#include "modes/dist/dist_program_codec.h"
#include "modes/dist/dist_runtime.h"
#include "support/safe_parse.h"
#include "support/process_math.h"

TimePredictor timePredictor = {0, 0, 0, 0, 0, 0, 0, 0};
