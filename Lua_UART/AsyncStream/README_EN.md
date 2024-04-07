This is an automatic translation, may be incorrect in some places. See sources and examples!

# Asyncstream
Library for asynchronous reading of objects Stream (Serial)
- non -reading reading in your buffer
- indication of the symbol of the terminator

## compatibility
Compatible with all arduino platforms (used arduino functions)

## Content
- [installation] (# Install)
- [initialization] (#init)
- [use] (#usage)
- [Example] (# Example)
- [versions] (#varsions)
- [bugs and feedback] (#fedback)

<a id="install"> </a>
## Installation
- The library can be found by the name ** asyncstream ** and installed through the library manager in:
    - Arduino ide
    - Arduino ide v2
    - Platformio
- [download the library] (https://github.com/gyverlibs/asyncstream/archive/refs/heads/main.zip) .Zip archive for manual installation:
    - unpack and put in * C: \ Program Files (X86) \ Arduino \ Libraries * (Windows X64)
    - unpack and put in * C: \ Program Files \ Arduino \ Libraries * (Windows X32)
    - unpack and put in *documents/arduino/libraries/ *
    - (Arduino id) Automatic installation from. Zip: * sketch/connect the library/add .Zip library ... * and specify downloaded archive
- Read more detailed instructions for installing libraries [here] (https://alexgyver.ru/arduino-first/#%D0%A3%D1%81%D1%82%D0%B0%BD%D0%BE%BE%BE%BED0%B2%D0%BA%D0%B0_%D0%B1%D0%B8%D0%B1%D0%BB%D0%B8%D0%BE%D1%82%D0%B5%D0%BA)
### Update
- I recommend always updating the library: errors and bugs are corrected in the new versions, as well as optimization and new features are added
- through the IDE library manager: find the library how to install and click "update"
- Manually: ** remove the folder with the old version **, and then put a new one in its place.“Replacement” cannot be done: sometimes in new versions, files that remain when replacing are deleted and can lead to errors!


<a id="init"> </a>
## initialization
`` `CPP
// <Boofer size>
// Stream processor (Serial, SoftwareSerial, etc.
// Terminator (symbol of the end of the reception) - by default ';'(cut out of the buffer!)
// Timout in MS - by default 50
Asyncstream <100> serial (& serial);
Asyncstream <100> serial (& serial, '\ n');
Asyncstream <100> serial (& serial, '\ n', 20);
`` `

<a id="usage"> </a>
## Usage
`` `CPP
VOID settimeout (uint16_t tout);// Install a timaut
VOID Seteol (charter);// Install the end symbol
Bool Available ();// data accepted
Char Buf;// access to the buffer
`` `

<a id="EXAMPLE"> </a>
## Example
The rest of the examples look at ** Examples **!
`` `CPP
#include <asyncstream.h>
Asyncstream <100> serial (& serial, '\ n');

VOID setup () {
  Serial.Begin (9600);
  // serial.Settimeout (100);// Install another timaut
  // serial.seteol (';');// Install another terminator (eol)
}

// line for the test (send to the series)
// 1234.3.14, Hello, 4567, Lolkek, Qwerty
VOID loop () {
  if (serial.available ()) {// if the data is obtained
    Serial.println (serial.buf);// Display them (like Char*)
  }
}
`` `

<a id="versions"> </a>
## versions
- V1.0
- V1.1 - Bag Fixed

<a id="feedback"> </a>
## bugs and feedback
Create ** Issue ** when you find the bugs, and better immediately write to the mail [alex@alexgyver.ru] (mailto: alex@alexgyver.ru)
The library is open for refinement and your ** pull Request ** 'ow!Cranberries when reporting about bugs or incorrect work of the library must be indicated:
- The version of the library
- What is MK used
- SDK version (for ESP)
- version of Arduino ide
- whether the built -in examples work correctly, in which the functions and designs are used, leading to a bug in your code
- what code has been loaded, what work was expected from it and how it works in reality
- Ideally, attach the minimum code in which the bug is observed.Not a canvas of a thousand lines, but a minimum code