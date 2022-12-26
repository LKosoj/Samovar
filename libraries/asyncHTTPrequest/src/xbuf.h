#pragma once
/***********************************************************************************
    Copyright (C) <2018>  <Bob Lemaire, IoTaWatt, Inc.>

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <https://www.gnu.org/licenses/>. 

    ************************** end of license section ****************************

    xbuf is a dynamic buffering system that supports reading and writing much like cbuf.
    The class has it's own provision for writing from buffers, Strings and other xbufs
    as well as the inherited Print functions.
    Rather than use a large contiguous heap allocation, xbuf uses a linked chain of segments
    to dynamically grow and shrink with the contents.
    There are other benefits as well to using smaller heap allocation units:
    1) A buffer can work fine in a fragmented heap environment (admittedly contributing to it)
    2) xbuf contents can be copied from one buffer to another without the need for 
       2x heap during the copy.
    The segment size defaults to 64 but can be dynamically set in the constructor at creation.   
    The inclusion of indexOf and read/peek until functions make it useful for handling
    data streams like HTTP, and in fact is why it was created.

    NOTE: The size of the indexOf() search string is limited to the segment size.
          It could be extended but didn't seem to be a practical consideration.    
   
***********************************************************************************/
#include <Arduino.h>

struct xseg {
    xseg    *next;
    uint8_t data[];
};

class xbuf: public Print {
    public:

        xbuf(const uint16_t segSize=64);
        virtual ~xbuf();

        size_t      write(const uint8_t);
        size_t      write(const char*);
        size_t      write(const uint8_t*, const size_t);
        size_t      write(xbuf*, const size_t);
        size_t      write(String);
        size_t      available();
        int         indexOf(const char, const size_t begin=0);
        int         indexOf(const char*, const size_t begin=0);
        uint8_t     read();
        size_t      read(uint8_t*, size_t);
        String      readStringUntil(const char);
        String      readStringUntil(const char*);
        String      readString(int);
        String      readString(){return readString(available());}
        void        flush();

        uint8_t     peek();
        size_t      peek(uint8_t*, const size_t);
        String      peekStringUntil(const char target) {return peekString(indexOf(target, 0));}
        String      peekStringUntil(const char* target) {return peekString(indexOf(target, 0));}
        String      peekString() {return peekString(_used);}
        String      peekString(int);

/*      In addition to the above functions, 
        the following inherited functions from the Print class are available.  

        size_t printf(const char * format, ...)  __attribute__ ((format (printf, 2, 3)));
        size_t printf_P(PGM_P format, ...) __attribute__((format(printf, 2, 3)));
        size_t print(const __FlashStringHelper *);
        size_t print(const String &);
        size_t print(const char[]);
        size_t print(char);
        size_t print(unsigned char, int = DEC);
        size_t print(int, int = DEC);
        size_t print(unsigned int, int = DEC);
        size_t print(long, int = DEC);
        size_t print(unsigned long, int = DEC);
        size_t print(double, int = 2);
        size_t print(const Printable&);

        size_t println(const __FlashStringHelper *);
        size_t println(const String &s);
        size_t println(const char[]);
        size_t println(char);
        size_t println(unsigned char, int = DEC);
        size_t println(int, int = DEC);
        size_t println(unsigned int, int = DEC);
        size_t println(long, int = DEC);
        size_t println(unsigned long, int = DEC);
        size_t println(double, int = 2);
        size_t println(const Printable&);
        size_t println(void);
*/        

    protected:

        xseg        *_head;
        xseg        *_tail;
        uint16_t     _used;
        uint16_t     _free;
        uint16_t     _offset;
        uint16_t     _segSize;

        void        addSeg();
        void        remSeg();

};