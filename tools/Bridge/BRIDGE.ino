#include <M5Stack.h>
#include "SPIFFS.h"
#include "FS.h"

void AExplorer() {
  while (Serial.available() == 0) delay(5);
  char f = Serial.read();
  if (f == 'D') { 
    //M5.Lcd.println("DOWNLOAD MODE");

    // ПОЛУЧЕНИЕ РАЗМЕРА ИМЕНИ СКАЧИВАЕМОГО ФАЙЛА
    size_t sizeOfName = 0;
    for (int i = 3; i > -1; i--) {
      while (Serial.available() < 1) delay(5);
      sizeOfName |= Serial.read() << (i * 8);
    }
    //M5.Lcd.print("Size Of Name: ");
    //M5.Lcd.println(sizeOfName);

    // ПОЛУЧЕНИЕ ИМЕНИ СКАЧИВАЕМОГО ФАЙЛА
    String fileName = "";
    for (size_t i = 0; i < sizeOfName; i++) {
      while (Serial.available() < 1) delay(5);
      fileName += (char)Serial.read();
    }
    //M5.Lcd.print("Filename: ");
    //M5.Lcd.println(fileName);

    // ПОПЫТКА ОТКРЫТИЯ ФАЙЛА ДЛЯ ЧТЕНИЯ
    File file = SPIFFS.open(fileName, FILE_READ);
    if (!file) {
      //M5.Lcd.print("E: can't open the file");
      //M5.Lcd.println(fileName);
      Serial.write('d');
    } else {
      // ОТПРАВКА РАЗМЕРА ФАЙЛА
      size_t fileSize = file.size();
      for (int i = 3; i > -1; i--) {
        while (Serial.availableForWrite() < 1) delay(5);
        byte x = (fileSize >> (i * 8)) & 0xFF;
        Serial.write((byte)x);
      }
      //M5.Lcd.print("Filesize: ");
      //M5.Lcd.println(fileSize);
  
      // ОТПРАВКА СОДЕРЖИМОГО ФАЙЛА
      //M5.Lcd.print("Blocks: ");
      //M5.Lcd.println(int(fileSize / 1024));
      for (size_t i = 0; i < fileSize; i++) {
        while (Serial.availableForWrite() < 1) delay(5);
        Serial.write((char)file.read());
        //if (i % 1024 == 0) M5.Lcd.print("*");
      }
      file.close();
    }
  } 

  else if (f == 'M') {
    // ОТПРАВКА ОБЩЕГО ОБЪЁМА ПАМЯТИ
    size_t totalMemory = SPIFFS.totalBytes();
    for (int i = 3; i > -1; i--) {
      while (Serial.availableForWrite() < 1) delay(5);
      byte x = (totalMemory >> (i * 8)) & 0xFF;
      Serial.write((byte)x);
    }
    //M5.Lcd.print("Total memory: ");
    //M5.Lcd.println(totalMemory);

    // ОТПРАВКА ЗАНЯТОГО ОБЪЁМА ПАМЯТИ
    size_t usedMemory = SPIFFS.usedBytes();
    for (int i = 3; i > -1; i--) {
      while (Serial.availableForWrite() < 1) delay(5);
      Serial.write((byte)(usedMemory >> (i * 8)) & 0xFF);
    }
    //M5.Lcd.print("Used memory: ");
    //M5.Lcd.println(usedMemory);
  }

  else if (f == 'L') {
    File root = SPIFFS.open("/");
    File file = root.openNextFile();
    size_t sizeOfData = 0;
    while (file) {
      if (!file.isDirectory()) {
        String Name = file.name();
        size_t sizeOfName = Name.length();
        sizeOfData += (sizeOfName + 8);
      }
      file = root.openNextFile();
    }
    root.close();

    for (int i = 3; i > -1; i--) {
      while (Serial.availableForWrite() < 1) delay(5);
      Serial.write((sizeOfData >> (i * 8)) & 0xFF);
    }
    
    if (sizeOfData > 0) {
      root = SPIFFS.open("/");
      file = root.openNextFile();
      while (file) {
        if (!file.isDirectory()) {
          String Name = file.name();
          uint8_t sizeOfName = Name.length();
          for (int i = 3; i > -1; i--) {
            while (Serial.availableForWrite() < 1) delay(5);
            Serial.write((sizeOfName >> (i * 8)) & 0xFF);
          }
          size_t fileSize = file.size();
          for (int i = 3; i > -1; i--) {
            while (Serial.availableForWrite() < 1) delay(5);
            Serial.write((fileSize >> (i * 8)) & 0xFF);
          }
          for (uint8_t i = 0; i < sizeOfName; i++) {
            while (Serial.availableForWrite() < 1) delay(5);
            Serial.write(Name[i]);
          }
        }
        file = root.openNextFile();
      }
      root.close();
   }
  }

  else if (f == 'R') {
    //M5.Lcd.println("REMOVE MODE");

    // ПОЛУЧЕНИЕ РАЗМЕРА ИМЕНИ УДАЛЯЕМОГО ФАЙЛА
    size_t sizeOfName = 0;
    for (int i = 3; i > -1; i--) {
      while (Serial.available() < 1) delay(5);
      sizeOfName |= Serial.read() << (i * 8);
    }

    // ПОЛУЧЕНИЕ ИМЕНИ УДАЛЯЕМОГО ФАЙЛА
    String fileName = "";
    for (size_t i = 0; i < sizeOfName; i++) {
      while (Serial.available() < 1) delay(5);
      fileName += (char)Serial.read();
    }
    //M5.Lcd.print("Filename: ");
    //M5.Lcd.println(fileName);

    if (SPIFFS.remove(fileName)) {
      Serial.write('R');
    } else {
      Serial.write('r');
    }
  }

  else if (f == 'E') {
    //M5.Lcd.println("ERASE MODE");
      SPIFFS.format();
      Serial.write('E');
  }

  else if (f == 'U') {
    //M5.Lcd.println("UPLOAD MODE");

    // ПОЛУЧЕНИЕ РАЗМЕРА ИМЕНИ ВЫГРУЖАЕМОГО ФАЙЛА
    size_t sizeOfName = 0;
    for (int i = 3; i > -1; i--) {
      while (Serial.available() < 1) delay(5);
      sizeOfName |= Serial.read() << (i * 8);
    }
    //M5.Lcd.print("Size Of Name: ");
    //M5.Lcd.println(sizeOfName);

    // ПОЛУЧЕНИЕ РАЗМЕРА ВЫГРУЖАЕМОГО ФАЙЛА
    size_t fileSize = 0;
    for (int i = 3; i > -1; i--) {
      while (Serial.available() < 1) delay(5);
      fileSize |= Serial.read() << (i * 8);
    }
    //M5.Lcd.print("Filesize: ");
    //M5.Lcd.println(fileSize);

    // ПОЛУЧЕНИЕ ИМЕНИ ВЫГРУЖАЕМОГО ФАЙЛА
    String fileName = "";
    for (size_t i = 0; i < sizeOfName; i++) {
      while (Serial.available() < 1) delay(5);
      fileName += (char)Serial.read();
    }
    //M5.Lcd.print("Filename: ");
    //M5.Lcd.println(fileName);

    // ПОПЫТКА ОТКРЫТИЯ ФАЙЛА ДЛЯ ЗАПИСИ
    File file = SPIFFS.open(fileName, FILE_WRITE);
    if (!file) {
      //M5.Lcd.print("E: can't open the file");
      Serial.write('u');
      while (true);
    } else {
        Serial.write('A');
    
        // ПОЛУЧЕНИЕ СОДЕРЖИМОГО ФАЙЛА
        while (true) {
          while (Serial.available() == 0) delay(5);
          char f = Serial.read();
          if (f == 'U') {
            while (Serial.available() == 0) delay(5);
            uint8_t sizeOfPiece = (uint8_t)Serial.read();
            while (Serial.available() < sizeOfPiece) delay(5);
            byte * buf = (byte*)malloc(sizeof(byte) * sizeOfPiece);
            Serial.readBytes(buf, sizeOfPiece);
            file.write(buf, sizeOfPiece);
            free(buf);
            Serial.write('A');
            //M5.Lcd.print("*");
          } else if (f == 'u') {
            Serial.write('u');
            break;
          }
      }
      file.close();
    }
  }
  
  else if (f == 'X') {
    //M5.Lcd.println("EXECUTE MODE");
    // ПОЛУЧЕНИЕ РАЗМЕРА ИМЕНИ ИСПОЛНЯЕМОГО ФАЙЛА
    size_t sizeOfName = 0;
    for (int i = 3; i > -1; i--) {
      while (Serial.available() < 1) delay(5);
      sizeOfName |= Serial.read() << (i * 8);
    }
    //M5.Lcd.print("sizeOfName: ");
    //M5.Lcd.println(sizeOfName);

    // ПОЛУЧЕНИЕ ИМЕНИ ИСПОЛНЯЕМОГО ФАЙЛА
    String fileName = "";
    for (size_t i = 0; i < sizeOfName; i++) {
      while (Serial.available() < 1) delay(5);
      fileName += (char)Serial.read();
    }
    //M5.Lcd.print("Filename: ");
    //M5.Lcd.println(fileName);
    String extension = "";
    bool f = false;
    for (int i = 0; i < fileName.length(); i++) {
      if (fileName[i] == '.') {
        f = true;
      } else {
        if (f) {
          extension += fileName[i];
        }
      }
    }
    //M5.Lcd.print("Ext: ");
    //M5.Lcd.println(extension);
    char * fileNameChar = new char[fileName.length() + 1];
    strcpy(fileNameChar, fileName.c_str());
    if ((extension == "jpg") || (extension == "JPG")) {
      M5.Lcd.drawJpgFile(SPIFFS, fileNameChar, 0, 0);
      Serial.write('X');
    }
    else if ((extension == "png") || (extension == "PNG")) {
      M5.Lcd.drawPngFile(SPIFFS, fileNameChar, 0, 0);
      Serial.write('X');
    } 
    else if ((extension == "bmp") || (extension == "BMP")) {
      M5.Lcd.drawBmpFile(SPIFFS, fileNameChar, 0, 0);
      Serial.write('X');
    } 
    else {
      //M5.Lcd.println("ext not suppored yet");
      Serial.write('x');
    }
  }
  else if (f == 'Q') {
    //M5.Lcd.println("RESET MODE");
    ESP.restart();
  }
}

void bridge(void * pvParameters) {
  while (true) {
    String signature = "";
    for (size_t i = 0; i < 16; i++) {
      while (Serial.available() < 1) delay(5);
      signature += (char)Serial.read();
    }
    if (signature == "A-Explorer______") {
      AExplorer();
    }
    delay(5);
  }
}

void setup() {
  M5.begin();
  SPIFFS.begin(true);
  xTaskCreatePinnedToCore(bridge, "bridge", 4096, NULL, 1, NULL, 1);

}

void loop() {
  
}
