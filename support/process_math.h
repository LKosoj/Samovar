#ifndef __SAMOVAR_PROCESS_MATH_H_
#define __SAMOVAR_PROCESS_MATH_H_

#include <Arduino.h>
#include <math.h>

#include "state/globals.h"

inline uint8_t getDelimCount(const String& data, char separator) {
  uint8_t cnt = 0;
  for (char c : data) {
    if (c == separator) {
      ++cnt;
    }
  }
  return cnt;
}

inline String getValue(const String& data, char separator, int index) {
  int found = 0;
  int strIndex[] = { 0, -1 };
  int maxIndex = data.length() - 1;

  for (int i = 0; i <= maxIndex && found <= index; i++) {
    if (data.charAt(i) == separator || i == maxIndex) {
      ++found;
      strIndex[0] = strIndex[1] + 1;
      strIndex[1] = (i == maxIndex) ? i + 1 : i;
    }
  }
  return found > index ? data.substring(strIndex[0], strIndex[1]) : "";
}

inline float get_liquid_volume_by_step(float StepCount) {
  return (SamSetup.StepperStepMl > 0) ? (float)StepCount / SamSetup.StepperStepMl : 0;
}

inline float get_liquid_rate_by_step(int StepperSpeed) {
  return round(get_liquid_volume_by_step(StepperSpeed) * 3.6 * 1000) / 1000.00;
}

inline float get_speed_from_rate(float volume_per_hour) {
  ActualVolumePerHour = volume_per_hour;
  float v = round(SamSetup.StepperStepMl * volume_per_hour * 1000 / 3.6) / 1000.00;
  return (v < 1) ? 1 : v;
}

inline int get_liquid_volume() {
  return get_liquid_volume_by_step(stepper.getCurrent());
}

inline float get_temp_by_pressure(float start_pressure, float start_temp, float current_pressure) {
  if (start_temp == 0) return 0;
  if (current_pressure < 10) return start_temp;

  float c_temp;

  if (SamSetup.UsePreccureCorrect) {
    float i_temp;
    float d_temp;

    i_temp = current_pressure * 0.038 + 49.27;

    if (start_pressure == 0) {
      d_temp = start_temp - 78.15;
    } else {
      d_temp = start_temp - start_pressure * 0.038 - 49.27;
    }
    c_temp = i_temp + d_temp;
  } else {
    c_temp = start_temp;
  }

  return c_temp;
}

inline float get_alcohol(float t);

inline float get_steam_alcohol(float t) {
  if (!boil_started) return 100;

  float r;
  float t1;
  float s;
  float k;
  uint8_t t0;

  t1 = t;
  t = get_temp_by_pressure(0, t, bme_pressure);

  if (t >= 99 && t < 99.84) {
    s = 11.21;
    k = -13;
    t0 = 99;
  } else if (t >= 98 && t < 99) {
    s = 20.744;
    k = -9.84;
    t0 = 98;
  } else if (t >= 97 && t < 98) {
    s = 29.936;
    k = -9;
    t0 = 97;
  } else if (t >= 96 && t < 97) {
    s = 39.781;
    k = -9.6;
    t0 = 96;
  } else if (t >= 95 && t < 96) {
    s = 44.628;
    k = -4.847;
    t0 = 95;
  } else if (t >= 94 && t < 95) {
    s = 49.2775;
    k = -4.65;
    t0 = 94;
  } else if (t >= 93 && t < 94) {
    s = 53.76;
    k = -4.483;
    t0 = 93;
  } else if (t >= 92 && t < 93) {
    s = 57.539;
    k = -3.778;
    t0 = 92;
  } else if (t >= 91 && t < 92) {
    s = 61.22;
    k = -3.682;
    t0 = 91;
  } else if (t >= 90 && t < 91) {
    s = 66.4633;
    k = -5.244;
    t0 = 90;
  } else if (t >= 89 && t < 90) {
    s = 69.334;
    k = -2.87;
    t0 = 89;
  } else if (t >= 88 && t < 89) {
    s = 70.82;
    k = -1.4857;
    t0 = 88;
  } else if (t >= 87 && t < 88) {
    s = 72.42;
    k = -1.6;
    t0 = 87;
  } else if (t >= 86 && t < 87) {
    s = 75.03;
    k = -2.66;
    t0 = 86;
  } else if (t >= 85 && t < 86) {
    s = 77.21;
    k = -2.2;
    t0 = 85;
  } else if (t >= 84 && t < 85) {
    s = 79.88;
    k = -2.67;
    t0 = 84;
  } else if (t >= 83 && t < 84) {
    s = 81.08;
    k = -1.2;
    t0 = 83;
  } else {
    s = 82;
    k = -1;
    t0 = 82;
  }

  if (t > 100) {
    r = 0;
  } else if (t > 99.84) {
    r = get_alcohol(t1);
  } else {
    r = s + k * (t - t0);
  }
  if (r < 0) r = 0;
  return r;
}

inline float get_alcohol(float t) {
  if (!boil_started) return 100;
  t = get_temp_by_pressure(0, t, bme_pressure);
  float r;
  float k;
  k = (t - 89) / 6.49;

  r = 17.26 - k * (18.32 - k * (7.81 - k * (1.77 - k * (4.81 - k * (2.95 + k * (1.43 - k * (0.8 + 0.05 * k)))))));
  if (r < 0) r = 0;
  r = float(round(r * 10)) / 10;
  return r;
}

inline unsigned int hexToDec(String hexString) {
  unsigned int decValue = 0;
  int nextInt;

  for (uint8_t i = 0; i < hexString.length(); i++) {
    nextInt = int(hexString.charAt(i));
    if (nextInt >= 48 && nextInt <= 57) nextInt = map(nextInt, 48, 57, 0, 9);
    if (nextInt >= 65 && nextInt <= 70) nextInt = map(nextInt, 65, 70, 10, 15);
    if (nextInt >= 97 && nextInt <= 102) nextInt = map(nextInt, 97, 102, 10, 15);
    nextInt = constrain(nextInt, 0, 15);

    decValue = (decValue * 16) + nextInt;
  }

  return decValue;
}

#endif
