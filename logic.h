#include <Arduino.h>
#include "Samovar.h"
#include "state/globals.h"
#include "app/alarm_control.h"
#include "app/process_common.h"
#include "io/actuators.h"
#include "io/power_control.h"
#include "support/safe_parse.h"
#include "support/process_math.h"
#include "modes/rect/rect_runtime.h"

#ifdef SAMOVAR_USE_BLYNK
//#define BLYNK_PRINT Serial

#include <BlynkSimpleEsp32.h>
#endif
#include "impurity_detector.h"
