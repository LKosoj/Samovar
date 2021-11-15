#ifndef SAMOVAR_OL_H
#define SAMOVAR_OL_H
#include <Arduino.h>
#include "Samovar.h"

#define OpenLog Serial
void gotoOLCommandMode(void);

//Setups up the software serial, resets OpenLog so we know what state it's in, and waits
//for OpenLog to come online and report '<' that it is ready to receive characters to record
void setupOpenLog(void) {
  OpenLog.begin(115200);
  gotoOLCommandMode();
}

//This function creates a given file and then opens it in append mode (ready to record characters to the file)
//Then returns to listening mode
void createOLFile(char *fileName) {

  //Old way
  OpenLog.print("new ");
  OpenLog.print(fileName);
  OpenLog.write(13);  //This is \r

  //New way
  //OpenLog.print("new ");
  //OpenLog.println(filename); //regular println works with OpenLog v2.51 and above

  //Wait for OpenLog to return to waiting for a command
  while (1) {
    if (OpenLog.available())
      if (OpenLog.read() == '>') break;
  }

  OpenLog.print("append ");
  OpenLog.print(fileName);
  OpenLog.write(13);  //This is \r

  //Wait for OpenLog to indicate file is open and ready for writing
  while (1) {
    if (OpenLog.available())
      if (OpenLog.read() == '<') break;
  }

  //OpenLog is now waiting for characters and will record them to the new file
}

void appendOLFile(String str) {
  OpenLog.println(str);
}

//Reads the contents of a given file and dumps it to the serial terminal
//This function assumes the OpenLog is in command mode
void readOLFile(char *fileName) {

  //Old way
  OpenLog.print("read ");
  OpenLog.print(fileName);
  OpenLog.write(13);  //This is \r

  //New way
  //OpenLog.print("read ");
  //OpenLog.println(filename); //regular println works with OpenLog v2.51 and above

  //The OpenLog echos the commands we send it by default so we have 'read log823.txt\r' sitting
  //in the RX buffer. Let's try to not print this.
  while (1) {
    if (OpenLog.available())
      if (OpenLog.read() == '\r') break;
  }

  //This will listen for characters coming from OpenLog and print them to the terminal
  //This relies heavily on the SoftSerial buffer not overrunning. This will probably not work
  //above 38400bps.
  //This loop will stop listening after 1 second of no characters received
  for (int timeOut = 0; timeOut < 1000; timeOut++) {
    while (OpenLog.available()) {
      char tempString[100];

      int spot = 0;
      while (OpenLog.available()) {
        tempString[spot++] = OpenLog.read();
        if (spot > 98) break;
      }
      tempString[spot] = '\0';
      Serial.write(tempString);  //Take the string from OpenLog and push it to the Arduino terminal
      timeOut = 0;
    }

    delay(1);
  }

  //This is not perfect. The above loop will print the '.'s from the log file. These are the two escape characters
  //recorded before the third escape character is seen.
  //It will also print the '>' character. This is the OpenLog telling us it is done reading the file.

  //This function leaves OpenLog in command mode
}

//Check the stats of the SD card via 'disk' command
//This function assumes the OpenLog is in command mode
void readOLDisk() {

  //Old way
  OpenLog.print("disk");
  OpenLog.write(13);  //This is \r

  //New way
  //OpenLog.print("read ");
  //OpenLog.println(filename); //regular println works with OpenLog v2.51 and above

  //The OpenLog echos the commands we send it by default so we have 'disk\r' sitting
  //in the RX buffer. Let's try to not print this.
  while (1) {
    if (OpenLog.available())
      if (OpenLog.read() == '\r') break;
  }

  //This will listen for characters coming from OpenLog and print them to the terminal
  //This relies heavily on the SoftSerial buffer not overrunning. This will probably not work
  //above 38400bps.
  //This loop will stop listening after 1 second of no characters received
  for (int timeOut = 0; timeOut < 1000; timeOut++) {
    while (OpenLog.available()) {
      char tempString[100];

      int spot = 0;
      while (OpenLog.available()) {
        tempString[spot++] = OpenLog.read();
        if (spot > 98) break;
      }
      tempString[spot] = '\0';
      Serial.write(tempString);  //Take the string from OpenLog and push it to the Arduino terminal
      timeOut = 0;
    }

    delay(1);
  }

  //This is not perfect. The above loop will print the '.'s from the log file. These are the two escape characters
  //recorded before the third escape character is seen.
  //It will also print the '>' character. This is the OpenLog telling us it is done reading the file.

  //This function leaves OpenLog in command mode
}

//This function pushes OpenLog into command mode
void gotoOLCommandMode(void) {
  //Send three control z to enter OpenLog command mode
  //Works with Arduino v1.0
  OpenLog.write(26);
  OpenLog.write(26);
  OpenLog.write(26);

  //Wait for OpenLog to respond with '>' to indicate we are in command mode
  while (1) {
    if (OpenLog.available())
      if (OpenLog.read() == '>') break;
  }
}
#endif
