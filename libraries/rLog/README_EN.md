# rLog: library for outputting debug messages with the ability to disable

This library is a _set of macros_ for outputting _formatted_ debug messages to the COM port (using the standard printf function), _with the possibility of partial or complete exclusion from the program code if necessary_. Based on library [<esp32-hal-log.h> for Arduino ESP32 Framework](https://github.com/espressif/arduino-esp32/blob/master/cores/esp32/esp32-hal-log.h) , in order to ensure performance on various microcontrollers and development tools. Tested on AVR, ESP32, ESP8266 for PlatformIO and Arduino IDE. The library does not use objects of type _String_, all work is based on dynamic memory allocation for strings using standard functions, which saves memory.

## Possibilities
* Support for [formatted messages](https://docs.microsoft.com/en-us/cpp/c-runtime-library/format-specification-syntax-printf-and-wprintf-functions?view=msvc-170)
* Automatic output of time stamp, message type and task identifier when outputting debug messages (see "Output format" below). You don't need to worry about it anymore.
* It is possible to display the file name and line number from which the command was called.
* Ability to select the debug level during compilation: NONE, ERROR, WARNING, INFO, DEBUG, VERBOSE. All messages that are higher than the specified level will be ignored by the compiler and will not be included in the final code.
* Support for color markers in the output. _Note: but this function does not work in all development tools and not on all operating systems (for example, for PlatformIO under Windows7, I could not get it to work, but under Windows 10 it works fine), it does not depend on the library_

## Output format
With the default settings, you will see the following text:

**23:59:59 [E] TAG: Message**

where:

* 23:59:59 - Time stamp
* [E] - Message type, in this example it is "error"
* TAG - A label (tag) with which you can determine which module caused this message
* Message - The actual text of the message

## Usage
Before using the library, at least select the level of debug messages for the project by defining the **CONFIG_RLOG_PROJECT_LEVEL** macro (see the "Settings" section below).

Debugging messages are output to the serial port using macro functions:

```
rlog_v(tag, format, ...) - output a message of the VERBOSE level
rlog_d(tag, format, ...) - output a message of the DEBUG level
rlog_i(tag, format, ...) - output a message of the INFORMATION level
rlog_w(tag, format, ...) - output a message of the WARNING level
rlog_e(tag, format, ...) - output a message of the ERROR level
```

where

* tag - this is a text label to identify the module from where the function was called
* format - message or format string. But don't use _string variables directly_ here. For example, if you need to display the username from the user_name variable, then instead of `rlog_i(logTAG, user_name)` you need to use a construction like `rlog_i(logTAG,"%s", user_name)`
* ... - data to be output in conversion specification, _optional_ (see https://docs.microsoft.com/en-us/cpp/c-runtime-library/format-specification-syntax-printf-and-wprintf-functions)

For example for the command:

```
rlog_e("WiFi", "Could not connect to access point %s, error code %d", ap_name, err);
```

the following text will be displayed:

```
12:34:10 [E] WiFi: Could not connect to access point test, error code -201
```

In this case, if the "level" of the message function (for example, rlog_v) is higher than that specified in **CONFIG_RLOG_PROJECT_LEVEL**, then the preprocessor will simply exclude this call during compilation, reducing memory costs.

## Settings
Module settings are made by defining several macros:

* **CONFIG_RLOG_PROJECT_LEVEL** RLOG_LEVEL_XXXX

Where **RLOG_LEVEL_XXXX** is one of the following values (см. rLog.h):

```
RLOG_LEVEL_NONE       (0)    /* No output */
RLOG_LEVEL_ERROR      (1)    /* Critical errors, the program module cannot recover on its own */
RLOG_LEVEL_WARN       (2)    /* Error conditions from which corrective action was taken */
RLOG_LEVEL_INFO       (3)    /* Informational messages describing the normal course of events */
RLOG_LEVEL_DEBUG      (4)    /* Additional information that is not required for normal use (values, pointers, dimensions, etc.). */
RLOG_LEVEL_VERBOSE    (5)    /* Large chunks of debug information or frequent messages that can potentially flood the output. */
```

Default **RLOG_LEVEL_ERROR**

* **CONFIG_RLOG_PROJECT_COLORS** [0/1]

Set to 1 to add "color tags" to messages. This will allow you to color messages of different types in different colors.

Default **0**

* **CONFIG_RLOG_SHOW_TIMESTAMP** [0/1]

Set to 1 to automatically add the event time stamp to messages.

Default **1**

* **CONFIG_RLOG_SHOW_FILEINFO** [0/1]

Set to 1 to add the filename and line number from which the command was invoked to the output messages.

Default **1**

#### Macros must be defined in such a place that the compiler can find them when building the _library_.

This can be done in several ways:

* **Using a file [platformio.ini](https://docs.platformio.org/page/projectconf.html)**

If you are using PlatformIO, you can simply add definitions to [project settings](https://docs.platformio.org/en/latest/projectconf/section_env_build.html#build-flags) (or even workplace settings):

```
[env]
build_flags = 
  -D CONFIG_RLOG_PROJECT_LEVEL=RLOG_LEVEL_INFO
  -D CONFIG_RLOG_PROJECT_COLORS=1
```

* **Using a file sdkconfig.esp32dev**

If you use the ESP-IDF framework, then automatically you get the global project settings file **sdkconfig.esp32dev**. Using special methods, you can add your own parameters to it. These parameters will be available from all files and libraries of the project, which is convenient.

* **Using a file project_config.h**

I am using a separate project config file - **project_config.h**, which only contains settings for my modules and libraries. It's comfortable. The only problem is that the file is accessible from libraries that are in a directory other than the project directory. In this case, the compiler needs to be told where to look for it:

```
[env]
build_flags = -Isrc 
```	

This flag will make the compiler, when building libraries, look at the src subdirectory from the project directory, where I put my project_config.h.

## Dependencies
The library only depends on the "standard" libraries:
* stdint.h
* stdio.h
* stdarg.h
* stdlib.h
* time.h

## Supported platforms
Library tested on **VSCode + PlatformIO** and **Arduino IDE** for AVR, ESP32 and ESP8266 microcontrollers. It is assumed that the list of microcontrollers could be larger. The library does not depend on the Framework used: for example, it can be Arduino or Espressif32 (ESP-IDF).

## Examples of using:
* arduinoide-arduino
* platformio-avr-arduino
* platformio-esp32-arduino
* platformio-esp32-espidf
* platformio-esp8266-arduino

## Note
These comments refer to my libraries hosted on the resource https://github.com/kotyara12?tab=repositories.

- libraries whose name starts with the **re** prefix are intended only for ESP32 and ESP-IDF (FreeRTOS)
- libraries whose name begins with the **ra** prefix are intended only for ARDUINO
- libraries whose name starts with the **r** prefix can be used for both ARDUINO and ESP-IDF

Since I am currently developing programs mainly for ESP-IDF, the bulk of my libraries are intended only for this framework. But you can port them to another system using.