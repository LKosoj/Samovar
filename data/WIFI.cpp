
/****************************************
Auxiliar Functions
****************************************/
void WIFI_Connect()
{
WiFi.disconnect();
Serial.println("Connecting to WiFi...");
WiFi.mode(WIFI_AP_STA);
WiFi.begin(WIFISSID, PASSWORD);

for (int i = 0; i < 60; i++)
{
if ( WiFi.status() != WL_CONNECTED )
{
delay ( 250 );
digitalWrite(ledPin, LOW);
Serial.print ( "." );
delay ( 250 );
digitalWrite(ledPin, HIGH);
}
}
if ( WiFi.status() == WL_CONNECTED )
{
Serial.println("");
Serial.println("WiFi Connected");
Serial.println("IP address: ");
Serial.println(WiFi.localIP());
}
digitalWrite(ledPin, 0);
}

/****************************************
Main Functions
****************************************/

void setup()
{
Serial.begin(115200);

// set the digital pin as output:
pinMode(ledPin, OUTPUT);
WIFI_Connect();
}

void loop()
{
unsigned long currentMillis = millis();

if (currentMillis - previousMillis >= interval)
{
if (WiFi.status() != WL_CONNECTED)
{
Serial.println("wifi disconnected ");
WIFI_Connect();
}
// save the last time you blinked the LED
