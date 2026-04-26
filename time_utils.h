#pragma once

#include <Arduino.h>

inline String format_uptime(unsigned long seconds) {
  unsigned long hours = seconds / 3600UL;
  unsigned long minutes = (seconds % 3600UL) / 60UL;
  unsigned long secs = seconds % 60UL;

  String result;
  if (hours < 10) result = "0";
  result += String(hours);
  result += ":";
  if (minutes < 10) result += "0";
  result += String(minutes);
  result += ":";
  if (secs < 10) result += "0";
  result += String(secs);
  return result;
}
