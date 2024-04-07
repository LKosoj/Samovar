#include <ASOLED.h> 
#include <AsyncStream.h>
#include <GParser.h>
AsyncStream<320> serial(&Serial, '\n'); 
uint8_t j=0;
void setup() {
   LD.init(); 
   LD.clearDisplay();  
   LD.printString_12x16(F("LUA - UART"), 1, 2);
   LD.printString_12x16(F(" дисплей"), 1, 4);   
   Serial.begin(115200);
}
void loop() {
  if (serial.available()) {     
        GParser data(serial.buf, ',');
        int am = data.split();
        for (byte i = 0; i < 8; i++) 
        if (i<am-1) { 
          LD.printString_6x8(data[i],1,i); 
          while (LD.GetCurrentX() < 122) LD.printString_6x8(" "); }
        else LD.printString_6x8(F("                    "),1,i); 
        switch (j) {
          case 0:LD.printString_6x8("|",118,8); break;
          case 1:LD.printString_6x8("/",118,8); break;
          case 2:LD.printString_6x8("-",118,8); break;
          case 3:LD.printString_6x8("\\",118,8);
        }
        j++; if (j>3) j=0;
  }
}