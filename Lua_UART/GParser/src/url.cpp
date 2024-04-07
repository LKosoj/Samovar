#include "url.h"
void GP_urlencode(const String& s, String& dest) {
    dest.reserve(s.length());
    char c;
    for (uint16_t i = 0; i < s.length(); i++) {
        c = s[i];
        if (c == ' ') dest += '+';
        else if (!(
                    (c >= '0' && c <= '9') ||
                    (c >= 'a' && c <= 'z') ||
                    (c >= 'A' && c <= 'Z') ||
                    c == '-' || c == '_' || c == '.' || c == '!' || c == '~' ||
                    c == '*' || c == '\'' || c == '(' || c == ')'
                    )) {
            dest += '%';
            dest += (char)((c >> 4) + (((c >> 4) > 9) ? 55 : 48));
            dest += (char)((c & 0xF) + (((c & 0xF) > 9) ? 55 : 48));
        } else dest += c;
    }
}

String GP_urlencode(const String& s) {
    String dest;
    GP_urlencode(s, dest);
    return dest;
}

void GP_urldecode(const String& s, String& dest) {
    dest.reserve(s.length());
    char c;
    for (uint16_t i = 0; i < s.length(); i++) {
        c = s[i];
        if (c != '%') dest += (c == '+') ? ' ' : c;
        else {
            c = s[++i];
            uint8_t v1 = c - ((c <= '9') ? 48 : ((c <= 'F') ? 55 : 87));
            c = s[++i];
            uint8_t v2 = c - ((c <= '9') ? 48 : ((c <= 'F') ? 55 : 87));
            dest += char(v2 | (v1 << 4));
        }
    }
}

String GP_urldecode(const String& s) {
    String dest;
    GP_urldecode(s, dest);
    return dest;
}