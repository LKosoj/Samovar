#include <TimeLib.h>

// Определяем переменные для процедур времени
unsigned int  localPort = 2390;                                 // порт для прослушивания UDP пакетов
unsigned long ntp_time = 0;
long  t_correct        = 0;
unsigned long cur_ms   = 0;
unsigned long ms1      = 0;
unsigned long ms2      = 10000000UL;
unsigned long t_cur    = 0;

//tm* time_now;

IPAddress timeServerIP;                                         // для работы NTP
const char* ntpServerName = "time.nist.gov";
const int NTP_PACKET_SIZE = 48; 
byte packetBuffer[ NTP_PACKET_SIZE]; 
WiFiUDP udp;

void clok()                                                               // функция получения текущего времени с NTP сервера
{ 
  cur_ms = millis();                                                      // текущее количество миллисекунд
  t_cur  = cur_ms / 1000;                                                 // текущее количество секунд
  if ( cur_ms < ms2 || (cur_ms - ms2) > 120000 )                           // Каждые 60 секунд считываем время в интернете
   { 
                                                                          // делаем три попытки синхронизации с интернетом
     if ( GetNTP() )                                                      // если попытка увенчалась успехом
      { 
        ms2 = cur_ms;                                                     // перезагружаем таймер на 60 секунд
        t_correct = ntp_time - t_cur;                                     // вычисляем поправку
      }
   }
  if ( cur_ms < ms1 || (cur_ms - ms1) > 500 )                             // каждые 0.5 секунды выдаем время
   { 
     ms1 = cur_ms;                                                        // перезагружаем таймер на 0.5 секунды
     ntp_time = t_cur + t_correct;                                        // вычисляем время NTP
     //DisplayTime();                                                       // выводим текущее время на UART
     //points = !points; 
     }                                                  // инвертируем 
}
//*************************************************************************************************************************************
//void DisplayTime(void)                                                    // функция вывода времени на UART
//{ 
//  uint16_t m = ( ntp_time / 60 ) % 60;
//  uint16_t h = ( ntp_time / 3600 ) % 24;
  //Serial.print(h);
  //Serial.print(":");
  //Serial.println(m); 
//}
//*************************************************************************************************************************************
bool GetNTP(void)                                                         // функция посылки запроса к NTP серверу и парсинг ответа
{ 
  WiFi.hostByName(ntpServerName, timeServerIP);
  sendNTPpacket(timeServerIP);                                            // посылаем запрос на NTP сервер
  delay(800);
  int cb = udp.parsePacket();
  if (!cb)
   { 
     //Serial.println("No packet yet");
     return false; 
   }
  else
   { 
     //Serial.print("packet received, length=");
     //Serial.println(cb);
     udp.read(packetBuffer, NTP_PACKET_SIZE); // читаем пакет в буфер
     unsigned long highWord = word(packetBuffer[40], packetBuffer[41]);     // 4 байта начиная с 40-го содержат таймстамп -
     unsigned long lowWord = word(packetBuffer[42], packetBuffer[43]);      // число секунд начиная с 01.01.1900
     unsigned long secsSince1900 = highWord << 16 | lowWord;                // конвертируем два слова в переменную long
     const unsigned long seventyYears = 2208988800UL;                       // конвертируем в UNIX-таймстамп (число секунд от 01.01.1970)
     unsigned long epoch = secsSince1900 - seventyYears;
     ntp_time = epoch + TIMEZONE * 3600;                                    // делаем поправку на местную тайм-зону
     //Serial.print("Unix time = ");
     //Serial.println(ntp_time); 
   }
  return true;
}
//************************************************************************************************************************************
unsigned long sendNTPpacket(IPAddress& address)                            // функция посылки запроса NTP серверу на заданный адрес
{ 
  //Serial.println("sending NTP packet...");
  memset(packetBuffer, 0, NTP_PACKET_SIZE);                                // очистка буфера в 0
  // Формируем строку запроса NTP сервера
  packetBuffer[0] = 0b11100011;                                            // LI, Version, Mode
  packetBuffer[1] = 0;                                                     // Stratum, or type of clock
  packetBuffer[2] = 6;                                                     // Polling Interval
  packetBuffer[3] = 0xEC;                                                  // Peer Clock Precision
  // 8 bytes of zero for Root Delay & Root Dispersion
  packetBuffer[12]  = 49;
  packetBuffer[13]  = 0x4E;
  packetBuffer[14]  = 49;
  packetBuffer[15]  = 52;
  // Посылаем запрос на NTP сервер (123 порт)
  udp.beginPacket(address, 123);
  udp.write(packetBuffer, NTP_PACKET_SIZE);
  udp.endPacket();
}
//**********************************************************************************************************************************
String millis2time()                                                       // функция формирования строки "время работы модуля"
{ String Time = "";                                                        // начинаем с пустой строки
  unsigned long ss;
  byte mm,hh;
  ss = millis() / 1000;                                                    // вычисляем количество секунд с начала работы модуля
  hh = ss / 3600;                                                          // вычисляем количество часов
  mm =(ss - hh * 3600) / 60;                                               // вычисляем количество минут
  ss =(ss - hh * 3600) - mm * 60;                                          // вычисляем количество секунд
  if(hh < 10) Time += "0";                                                 // добавляем незначащий ноль к часам
  Time += (String)hh + ":";                                                // добавляем двоеточие между часами и минутами
  if(mm < 10) Time += "0";                                                 // добавляем незначащий ноль к минутам
  Time += (String)mm + ":";                                                // добавляем двоеточие между минутами и секундами
  if(ss < 10) Time += "0";                                                 // добавляем незначащий ноль к секундам
  Time += (String)ss;                                                      // добавляем секунды
  return Time; }                                                           // функция возвращает строку
//***********************************************************************************************************************************
String CurrentTime(void)                                                   // функция формирования строки "текущее время"
 { String Time ="";                                                        // начинаем с пустой строки
   byte m = ( ntp_time / 60 ) % 60;                                        // вычисляем количество минут
   byte h = ( ntp_time / 3600 ) % 24;                                      // вычисляем количество часов
   int  d = ( ntp_time / 3600 ) / 24;                                      // вычисляем количество дней
   byte s = ntp_time - d * 3600 * 24 - h * 3600 - m * 60;                  // вычисляем количество секунд
   if(h < 10) Time += "0";                                                 // добавляем незначащий ноль к часам
   Time+= (String)h + ":";                                                 // добавляем часы и двоеточие
   if(m < 10) Time += "0";                                                 // добавляем незначащий ноль к минутам
   Time+= (String)m + ":";                                                 // добавляем минуты и двоеточие
   if(s < 10) Time += "0";                                                 // добавляем незначащий ноль к секундам
   Time+= (String)s;                                                       // добавляем секунды

   //time_t tt = ntp_time + 2208988800UL;
   //time_now = gmtime(&tt);

   Time = /*(String)year(ntp_time) + "-" + */(String)month(ntp_time) + "-" + (String)day(ntp_time) + " " + Time;
   return Time; }                                                          // функция возвращает строку
