This is an automatic translation, may be incorrect in some places. See sources and examples!

# Gparser
Simple and fast Parser lines in separate tunes and numbers for Arduino
- works with the indicated buffer (line), does not create its own
- shares the line for tuning according to the specified symbol
- allows you to contact tunes, transfer them into numbers and compare with lines
- Access to tunes through []
- can rinse the line into the INT or BYTE array

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
- The library can be found by the name ** gparser ** and installed through the library manager in:
    - Arduino ide
    - Arduino ide v2
    - Platformio
- [download the library] (https://github.com/gyverlibs/gparser/archive/refs/heads/main.zip) .Zip archive for manual installation:
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
// Transfer Char Array a line, you can specify the Symbol Separate (by the silence ',')
GParser (Char* Data);
Gparser (Char* Data, Char Newdiv = ',');
`` `

<a id="usage"> </a>
## Usage
### class GParser
`` `CPP
VOID Setdiv (Char Newdiv);// specify the Symbol Separate
Void Clear ();// Free the buffer
int amount ();// The number of data separated in the package
int split ();// divide the line into tunes
int32_t getint (int num);// Get Inta from the selected tack
Float getfloat (int num);// Get Float from the selected toll
Bool Equals (int num, const char* comp);// Compare the tuning with another line
int Parsebytes (byte* data);// Parish bytes
int parseints (int* data);// Parisulate on Ints
Intselongs (LONG* DATA);// Parish on Longs
VOID restore ();// Restore the original type of line (return the dividers)
`` `

### Separate Parsing Functions
See example ** testils **

`` `CPP
// Number of tuning in the list list with DIV separator
uint8_t gp_listsize (char* list, char div = ',');

// Divide the list of LIST with the DIV separator into tunes (see example)
Char* gp_splitlist (char* list, char div = ',');

// Get a number under which NAME is included in LIST with the DIV separator.-1 if not included
int8_t gp_inlist (char* name, char* list, char div = ',');

// Transform int into a line (it works 3-10 times faster LTOA + base)
VOID gp_numtochar (int32_t n, char* buf, uint8_t base);

// Transform Float into a line
VOID gp_floattoChar (Double F, Char *Buf, Uint8_T Decimals);

// Transfer the line to the number
int32_t gp_Chartonum (char* buf, uint8_t base);

// Transform the line into Float
Double gp_Chartofloat (Char* buf);

// Get the number under the IDX index in the list list with the DIV separator
Ints_numfromlist (Char* List, Intx, Char Div = ',');

// Re -rewrite the list of LIST with the DIV separator in the DATA size array of SIZE
uint8_t gp_listonum (char* list, int* data, uint8_t size, char div = ',');

// Transfer text color (0x, #) to the number
uint32_t gp_decodecolor (char* hex);
`` `

### Unicode
See example ** testicode **

`` `CPP
Char* gp_unencode (int32_t c, char* s);// Unicode code in Char [5]
String gp_unencode (uint16_t c);// Unicode code in String
uint16_t gp_unistrlen (char* data);// UNICODE Length Line in the number of symbols
`` `

### url encode/decode
See example ** Testurb **

`` `CPP
VOID gp_urlencode (Constation String & S, String & Dest);// Urlencode from String to String
String gp_urlencode (const string & s);// Urlencode from String to String (Return)
String GP_urldecode (Constation String & S, String & Dest);// urlDecode from String in String
String GP_urldecode (Const String & S);// urldecode from String to String (Return)
`` `

<a id="EXAMPLE"> </a>
## Example
The rest of the examples look at ** Examples **!
`` `CPP
// Parser's Test
#include <gparser.h>

VOID setup () {
  Serial.Begin (9600);

  // =======================================================
  // Line for example
  // Data is separated by a divider, for example, a comma
  // can be obtained from Serial/UDP/TCP/MQTT etc.
  Char Str [] = "1234.3.14, Hello, 4567, Lolkek, Qwerty";

  // feed the line of the parser, indicate the separator (silence)
  Gparser data (str, ',');

  // Share
  // ATTENTION!The operation "breaks" the line, replacing the dividers with NULL
  int am = data.split ();
  // Get the amount of data

  Serial.println (AM);// We display the quantity

  // We can turn to the resulting lines as Data [i] or Data.str [i]
  for (byte i = 0; i <am; i ++) serial.println (Data [i]);

  // You can also get them in the form of int and float numbers
  // Passing the line index
  Serial.println (Data.getint (0));
  Serial.println (Data.getfloat (1));

  // can be compared with a string (number of a row, line for comparison)
  if.equals (2, "Hello")) serial.println ("true");
  Else serial.println ("false");
  
  Serial.println ();
  
  // ========================================================
  // Fast Parsing of integer data with the divider
  char str2 [] = "123,456,789,22,333,444";
  GParser DATA2 (STR2);// feed the line Parser

  // Create an array with the number of cells Data2.amount () - so much data in the package
  int inti [data2.amount ()];
  
  int am2 = data2.parseints (ints);// spreads to the specified array and will return the number
  // actually here am2 == Data2.amount () - the amount of data
  // Display
  for (byte i = 0; i <am; i ++) serial.println (ints [i]);
}

VOID loop () {
}

`` `

<a id="versions"> </a>
## versions
- V1.0
- V1.1 - added individual parsing tools
- V1.2 - Parsing tools added more tools
- v1.3 - added the ability to restore the line
- V1.3.1 - Fix Warning
- v1.4 - added URL and Unicode coding
- V1.5 - Getint now returns int32_t

<a id="feedback"> </a>
## bugs and feedback
Create ** Issue ** when you find bugs, but better immediately write to the mail [alex@alexgyver.ru] (mailto: alex@alexgyver.ru)
The library is open for refinement and your ** pull Request ** 'ow!


When reporting about bugs or incorrect work of the library, it is necessary to indicate:
- The version of the library
- What is MK used
- SDK version (for ESP)
- version of Arduino ide
- whether the built -in examples work correctly, in which the functions and designs are used, leading to a bug in your code
- what code has been loaded, what work was expected from it and how it works in reality
- Ideally, attach the minimum code in which the bug is observed.Not a canvas of a thousand lines, but a minimum code