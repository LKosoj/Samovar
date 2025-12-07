// Library version:1.1.5
// Example of picking custom I2C pins on ESP32

#include <Arduino.h>
#include <LiquidCrystal_I2C.h>

#define I2C_SDA 25
#define I2C_SCL 26

LiquidCrystal_I2C lcd(0x27, 16, 2); // set the LCD address to 0x27 for a 16 chars and 2 line display

void setup(){
	lcd.init(I2C_SDA, I2C_SCL); // initialize the lcd to use user defined I2C pins
	lcd.backlight();
	lcd.setCursor(3,0);
	lcd.print("Hello, world!");
	lcd.setCursor(2,1);
	lcd.print("Time is now");
}


void loop(){
}
