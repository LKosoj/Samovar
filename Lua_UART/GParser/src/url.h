#pragma once
#include <Arduino.h>
void GP_urlencode(const String& s, String& dest);
String GP_urlencode(const String& s);
void GP_urldecode(const String& s, String& dest);
String GP_urldecode(const String& s);