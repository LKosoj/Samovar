# ESP Arduino Lua

This Arduino library provides the [lua](https://www.lua.org/) 5.3.5 ( [release](https://www.lua.org/ftp/lua-5.3.5.tar.gz) ) scripting engine for ESP8266/ESP32 sketches. This allows dynamic execution of Lua code on the Arduino without having to compile and flash a new firmware. 

Along with the Lua 5.3.5 Core the following Lua standard libraries are included:

- base (print(), tostring(), tonumber(), etc.)
- math
- table (insert(), sort(), remove(), ...)
- string (len(), match(), ...)

##  Sample sketch example: ExecuteScriptFromSerial.ino

After installing the library, some sketch examples are available from the *File* menu, then *Examples* and finally under *ESP-Arduino-Lua*. The examples include **ExecuteScriptFromSerial** which takes a lua script from the serial line and executes it. As an example, the following standard Arduino functions are available in lua scripts as bindings:

- pinMode()
- digitalWrite()
- delay()
- millis()
- print() *(only builtin binding)*

```
# Enter the lua script and press Control-D when finished:
print("My first test!")
# Executing script:
My first test!


# Enter the lua script and press Control-D when finished-
print("Current uptime: " .. millis())
# Executing script:
Current uptime: 159926.0


# Enter the lua script and press Control-D when finished:
print("Hello world!")
# Executing script:
Hello world!


# Enter the lua script and press Control-D when finished:
pinLED = 2
period = 500
pinMode(pinLED, OUTPUT)
while(true)
do
  print("LED on")
  digitalWrite(pinLED, LOW)
  delay(period)
  print("LED off")
  digitalWrite(pinLED, HIGH)
  delay(period)
end
# Executing script:
LED on
LED off
```
## Resources Used (ExecuteScriptFromSerial.ino)

**ESP8266:**
Sketch uses 327776 bytes (31%) of program storage space. Maximum is 1044464 bytes.
Global variables use 31276 bytes (38%) of dynamic memory, leaving 50644 bytes for local variables. Maximum is 81920 bytes.

**ESP32:**
Sketch uses 310749 bytes (23%) of program storage space. Maximum is 1310720 bytes.
Global variables use 15388 bytes (4%) of dynamic memory, leaving 312292 bytes for local variables. Maximum is 327680 bytes.

## Arduino IDE Library example: HelloWorld.ino
``` 
#include <LuaWrapper.h>

LuaWrapper lua;

void setup() {
  Serial.begin(115200);
  String script = String("print('Hello world!')");
  Serial.println(lua.Lua_dostring(&script));
}

void loop() {

}
```
## Resources Used (HelloWorld.ino)

**ESP8266:**
Sketch uses 365276 bytes (34%) of program storage space. Maximum is 1044464 bytes.
Global variables use 34712 bytes (42%) of dynamic memory, leaving 47208 bytes for local variables. Maximum is 81920 bytes.

**ESP32:**
Sketch uses 309913 bytes (23%) of program storage space. Maximum is 1310720 bytes.
Global variables use 15388 bytes (4%) of dynamic memory, leaving 312292 bytes for local variables. Maximum is 327680 bytes.

## The Lua Language:
[Lua 5.3 Reference Manual](https://www.lua.org/manual/5.3/)

