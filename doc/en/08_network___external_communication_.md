# Chapter 8: Network & External Communication

Welcome to the final chapter of the Samovar tutorial! We have already covered a lot of topics: how you interact with the device ([Chapter 1: User Interaction (Web & LCD)](01_user_interaction__web___lcd__.md)), how it executes process programs ([Chapter 2: Process Program Execution](02_process_program_execution_.md)), how it manages its state ([Chapter 3: System State & Mode Management](03_system_state___mode_management_.md)), how it reads data from sensors ([Chapter 4: Sensor Data Acquisition](04_sensor_data_acquisition_.md)), how it controls equipment ([Chapter 5: Hardware Control (Actuators)](05_hardware_control__actuators__.md)), how it ensures safety ([Chapter 6: Safety Monitoring & Alarms](06_safety_monitoring___alarms__.md)) and how it saves its settings ([Chapter 7: Configuration Persistence](07_configuration_persistence__.md)).

All of these capabilities would be limited if Samovar could only work in isolation. To unlock its full potential, it needs a connection to the outside world. This is where **Network & External Communication** comes into play. This part of the Samovar software is responsible for everything related to the device going online and interacting with other devices and services.

Imagine giving Samovar a network cable and a smartphone. That lets it connect to your home network (the cable), provides a powerful web interface accessible from any computer or phone (like a built-in website), and even lets it send messages or data to cloud services or to your phone (like an SMS or an update of a remote dashboard).

## Why Network Communication Matters: A Use Case

Imagine you are starting a long, multi-hour brewing process. The physical LCD is good for quick checks when you are next to Samovar, but you will most likely not want to stand beside it the whole time. You may need to:

1.  **Monitor the process remotely:** See the current temperature, progress and status from a computer in another room or even from a smartphone.
2.  **Change settings or trigger actions remotely:** Decide to raise the heater power a little or pause the program without touching the device.
3.  **Receive notifications:** Get a notification on your phone if an alarm has been triggered ([Chapter 6: Safety Monitoring & Alarms](06_safety_monitoring___alarms__.md)) or when a program stage has finished ([Chapter 2: Process Program Execution](02_process_program_execution_.md)).
4.  **View historical data:** Look at temperature charts for the whole run from a computer.

All of these scenarios require Samovar to be connected to your network and able to communicate externally.

## Samovar's Connections: Key Concepts

Samovar's network and external communication involves several key concepts:

1.  **Connecting to Wi-Fi:** Samovar joining your local wireless network.
2.  **Running a web server:** Hosting the interactive web interface that you access through a browser.
3.  **Providing API endpoints:** Creating specific web addresses that the web interface uses to fetch data and send commands (as mentioned in Chapter 1).
4.  **Interacting with external services:** Sending data or messages to platforms such as Blynk, MQTT brokers or Telegram.

Let us look at these in more detail.

## Connecting: Joining a Wi-Fi Network

The first step is connecting Samovar to your Wi-Fi network. For this, the Samovar project often uses the `AsyncWiFiManager` library, which makes the process very convenient, especially during initial setup.

It works like this:
*   On power-up, Samovar tries to connect to the Wi-Fi network it was previously configured for (the data is kept thanks to [Chapter 7: Configuration Persistence](07_configuration_persistence__.md)).
*   If the connection succeeds, it obtains an IP address on your network and is ready to work.
*   If the connection *fails* (for example, first start, the network has changed, wrong password), `WiFiManager` automatically switches Samovar into **access point mode (AP Mode)**. That is, Samovar *itself* becomes a temporary Wi-Fi hotspot.
*   Next, you connect your computer or smartphone to *this temporary Samovar access point*.
*   Once connected, a configuration portal opens automatically in the browser (or you go to the address `192.168.4.1`).
*   In this portal you pick your home Wi-Fi network from the list and enter the password.
*   After you save the settings, `WiFiManager` stores this data ([Chapter 7: Configuration Persistence](07_configuration_persistence__.md)), shuts down the temporary access point and tries to connect to the chosen home network.
*   After a successful connection, Samovar is fully online on your main network.

This removes the need to hard-code Wi-Fi passwords in the code and makes commissioning in different environments much easier.

Look at the `setup()` function in `Samovar.ino` for the Wi-Fi connection logic:

```c++
// From Samovar.ino (simplified part of the setup function)
void setup() {
  // ... rest of the initialization code ...

  WiFi.mode(WIFI_STA); // Station mode (connect to an existing network)
  WiFi.disconnect(true); // Start from a clean state
  delay(50);
  WiFi.setHostname(host); // Friendly device name on the network

  // ... SPIFFS/EEPROM initialization (Chapter 7) ...
  read_config(); // Load the saved configuration (including Wi-Fi)

  // ... Check whether a special button is held at startup to force AP mode ...
  bool wifiAP = false;
  // ... button state check ...

  if (!wifiAP) {
    // If not forced into AP mode, try auto-connecting with the saved credentials
    AsyncWiFiManagerParameter custom_blynk_token("blynk", "blynk token", SamSetup.blynkauth, 33, "blynk token");
    AsyncWiFiManager wifiManager(&server, &dns); // Pass the web server object

    // ... check for a button press to reset the settings ...

    wifiManager.setConfigPortalTimeout(360); // The portal stays open for 6 minutes
    wifiManager.setSaveConfigCallback(saveConfigCallback); // Function called when settings are saved
    wifiManager.setAPCallback(configModeCallback); // Function called when entering AP mode
    wifiManager.setDebugOutput(false);
    // You can add your own parameters to the portal, e.g., for the Blynk token
    wifiManager.addParameter(&custom_blynk_token);

    if (!wifiManager.autoConnect("Samovar")) {
      // If auto-connect failed, stay in AP mode and set the info to display
      WiFi.mode(WIFI_AP);
      WiFi.softAP("Samovar", "SamApp123"); // SSID and password for the AP
      StIP = WiFi.softAPIP().toString(); // AP IP address
    } else {
      // If auto-connect succeeded, get the local IP
      StIP = WiFi.localIP().toString();
    }

    if (shouldSaveWiFiConfig) { // Flag from saveConfigCallback
      // Save, for example, the Blynk token after Wi-Fi setup
      if (strlen(custom_blynk_token.getValue()) == 33) {
        strcpy(SamSetup.blynkauth, custom_blynk_token.getValue());
        save_profile(); // Save the updated SamSetup (Chapter 7)
      }
    }
    Serial.print(F("Connected to "));
    Serial.println(WiFi.SSID()); // Name of the connected network
  } else {
    // If forced into AP mode (by the button)
    WiFi.mode(WIFI_AP);
    WiFi.softAP("Samovar", "SamApp123");
    StIP = WiFi.softAPIP().toString();
    Serial.println(F("Started as WiFi AP"));
  }

  Serial.print(F("IP address: "));
  StIP.toCharArray(ipst, 16); // Store the IP in a global variable
  Serial.println(StIP);

  // ... Start mDNS (access by a name like samovar.local) ...
  // ... Rest of the initialization ...
}
```
This fragment shows how `AsyncWiFiManager` handles both the initial connection attempt and the switch to AP mode when necessary. The `saveConfigCallback()` function (not shown here, but simple) just sets the `shouldSaveWiFiConfig` flag, so that the main `setup` function can later save custom parameters, such as the Blynk token, after Wi-Fi setup.

Once Samovar is connected to your network, you can find out its IP (usually shown on the LCD or in the serial monitor at boot) or use its hostname (for example, `samovar.local`) if mDNS is working.

## Providing the Dashboard: The Web Server

Once Samovar is connected to your network, the next step is starting the web server. The server listens for incoming requests on a particular port (usually 80, the standard for HTTP) and serves web pages (HTML, CSS, images) stored in Samovar's internal file system ([Chapter 7: Configuration Persistence](07_configuration_persistence__.md)).

All of this is set up in the `WebServerInit()` function in `WebServer.ino`:

```c++
// From WebServer.ino (simplified WebServerInit function)
void WebServerInit(void) {
  FS_init(); // Initialize the file system (SPIFFS/LittleFS) (Chapter 7)

  // Set up handlers for specific URLs (endpoints)
  server.on("/", HTTP_GET | HTTP_POST, [](AsyncWebServerRequest* request) {
    request->redirect("/index.htm"); // Redirect to index.htm
  });

  // Serve static files (HTML, CSS, images) straight from the file system
  server.serveStatic("/style.css", SPIFFS, "/style.css").setCacheControl("max-age=5000");
  server.serveStatic("/alarm.mp3", SPIFFS, "/alarm.mp3");
  // ... other static handlers ...

  // Serve HTML files with dynamic content (via a template processor)
  server.serveStatic("/index.htm", SPIFFS, "/index.htm").setTemplateProcessor(indexKeyProcessor).setCacheControl("max-age=800");
  server.serveStatic("/chart.htm", SPIFFS, "/chart.htm").setTemplateProcessor(indexKeyProcessor).setCacheControl("max-age=800");
  // ... other dynamic pages ...

  // API endpoint handlers for the JavaScript on the page
  server.on("/ajax", HTTP_GET, [](AsyncWebServerRequest *request) {
    getjson(); // Collect data into a JSON string
    request->send(200, "text/html", jsonstr); // Send the JSON string
  });
  server.on("/command", HTTP_GET, [](AsyncWebServerRequest *request) {
    web_command(request); // Handle commands from the web page
  });
  server.on("/program", HTTP_POST, [](AsyncWebServerRequest *request) {
    web_program(request); // Handle saving/loading of programs
  });
  server.on("/save", HTTP_POST, [](AsyncWebServerRequest *request) {
    handleSave(request); // Update SamSetup from the web form
    save_profile(); // Save SamSetup to file/EEPROM (Chapter 7)
    // ... response ...
  });
  // ... other API endpoints ...

  DefaultHeaders::Instance().addHeader("Access-Control-Allow-Origin", "*");  // Allow JavaScript from other domains (for development)

  server.begin(); // Start the web server!
#ifdef __SAMOVAR_DEBUG
  Serial.println("HTTP server started");
#endif
}
```

This code shows how the `AsyncWebServer` library is configured. It binds specific URLs (`/`, `/style.css`, `/ajax`, `/command`, etc.) either to serving static files from the file system or to executing C++ functions (`getjson`, `web_command`, `handleSave`).

The `indexKeyProcessor` function (and similar ones, such as `setupKeyProcessor`) is part of the "template processor" mechanism. When a page like `index.htm` is requested, the server reads the HTML file and calls `indexKeyProcessor` for each placeholder it finds (for example, `%SteamColor%` or `%WProgram%`). This allows dynamic data to be substituted into the HTML before it is sent to the browser, so the web page reflects Samovar's current state and settings.

```c++
// From WebServer.ino (simplified indexKeyProcessor)
String indexKeyProcessor(const String &var) {
  if (var == "SteamColor") return (String)SamSetup.SteamColor; // Color from SamSetup
  else if (var == "v") return SAMOVAR_VERSION; // Software version
  // ... getting other values from SamSetup or global variables (sensor data, status, etc.) ...
  else if (var == "WProgram") { // For displaying the structure of the current program
    if (Samovar_Mode == SAMOVAR_BEER_MODE) return get_beer_program();
    // ... program strings for other modes ...
    else return get_program(CAPACITY_NUM * 2);
  }
  // ... and other HTML placeholders ...
  return ""; // Empty string if the placeholder is not recognized
}
```
This function takes "live" data and settings from Samovar's variables (`SamSetup`, sensor structures, global status flags) and formats them as strings for insertion into the web page's HTML.

## External Communication: Blynk, MQTT, Telegram

Besides the web interface, Samovar can send data *outward* to other platforms and services. This is usually implemented through separate tasks (for example, `triggerGetClock`, which is responsible for Telegram and Blynk, or an MQTT task).

### Blynk

If enabled (`#ifdef SAMOVAR_USE_BLYNK`), Samovar can connect to the Blynk platform. Blynk provides a mobile app and a web dashboard builder where you can create your own interface for monitoring and controlling the device remotely.

Samovar sends data *to* Blynk via `Blynk.virtualWrite()` and receives commands *from* Blynk via the `BLYNK_WRITE` macros.

```c++
// From Blynk.ino (simplified)
#ifdef SAMOVAR_USE_BLYNK

// A function that regularly sends data TO Blynk (virtual pin V0)
BLYNK_READ(V0) {
  // Send the steam temperature
  Blynk.virtualWrite(V0, SteamSensor.avgTemp);
  // Send the power state
  Blynk.virtualWrite(V4, PowerOn);
  // ... other statuses ...
}

// This function is called by Blynk when the V3 widget is used
BLYNK_WRITE(V3) {
  int State = param.asInt(); // Value from the Blynk widget
  if (State == 1 && PowerOn) {
    // If the value is 1 and power is on, the SAMOVAR_START command
    queue_samovar_command(SAMOVAR_START); // (Signal to the main loop, Chapter 3)
  } else {
    // Otherwise, the reset command
    queue_samovar_reset_command();
  }
}

// For power control (widget V16)
#ifdef SAMOVAR_USE_POWER
BLYNK_WRITE(V16) {
  float Value16 = param.asFloat(); // Target voltage from the widget
  set_current_power(Value16); // Command to the power regulator (Chapter 5)
}
#endif

#endif // SAMOVAR_USE_BLYNK
```
This shows the basic pattern: `BLYNK_READ` functions send data automatically, while `BLYNK_WRITE` functions receive user input from the Blynk app and turn it into Samovar commands or actions.

### MQTT

If enabled (`#ifdef USE_MQTT`), Samovar can act as an MQTT client, publishing data to an MQTT broker. This is convenient for integrating Samovar's data into home automation systems (Home Assistant, Node-RED, etc.) or other IoT dashboards.

Samovar sends data as messages to particular "topics".

```c++
// From SamovarMqtt.h (simplified)
#ifdef USE_MQTT

// Function for sending a message to an MQTT topic
void MqttSendMsg(const String &Str, const char *chart ) {
  // Build the full topic (for example, "SMV/YOUR_BLYNK_TOKEN/log/3")
  strcpy(mqttstr1, mqttstr);
  strcat(mqttstr1, chart);
  strcat(mqttstr1, "/3"); // Message version

  // Copy the payload string
  static char payload[PAYLOADSIZE];
  Str.toCharArray(payload, PAYLOADSIZE);

  // Publish the message
  uint16_t packetIdPub1 = mqttClient.publish(mqttstr1, 2, true, payload); // QoS 2, retain = true
  // ... handling possible connection problems and retrying ...
}

#endif // USE_MQTT
```
The `MqttSendMsg` function is called from other parts of the code (for example, from `triggerSysTicker` in `Samovar.ino`) to send sensor or status data to the MQTT broker. The data format is a simple string or CSV, which the receiving system then parses.

### Telegram

If enabled (`#ifdef USE_TELEGRAM`), Samovar can send text notifications to a Telegram chat through a Telegram bot.

```c++
// From Samovar.ino (simplified part of the SendMsg function)
void SendMsg(const String& m, MESSAGE_TYPE msg_type) {
  String MsgPl;

  // ... MQTT logic (see above) ...

#ifdef USE_TELEGRAM
  if (SamSetup.tg_token[0] != 0 && SamSetup.tg_chat_id[0] != 0) { // Check whether Telegram is configured
    // Prefix by message type (alarm, warning, notification)
    switch (msg_type) {
      case ALARM_MSG: MsgPl = F("*Тревога!*\n"); break; // *Alarm!*
      case WARNING_MSG: MsgPl = F("*Предупреждение!*\n"); break; // *Warning!*
      case NOTIFY_MSG: MsgPl = ""; break;
      default: MsgPl = "";
    }
    MsgPl += " Самовар - " + m; // Append the message itself ("Samovar - ...")

    // Use a queue and a semaphore for asynchronous sending (without blocking)
    if (xSemaphoreTake(xMsgSemaphore, (TickType_t)(50 / portTICK_RATE_MS)) == pdTRUE) {
      // Put the message string into the queue
      msg_q.push(MsgPl.c_str());
      xSemaphoreGive(xMsgSemaphore); // Release the semaphore
    }
  }
#endif

  // ... Logic for displaying the message on the LCD/web (Chapter 1) ...
}

// From Samovar.ino (simplified part of the triggerGetClock task)
void triggerGetClock(void *parameter) {
  // ... NTP, WiFi reconnection ...

#ifdef USE_TELEGRAM
  // Periodically check whether there are messages in the queue AND whether the internet is available
  if (WiFi.status() == WL_CONNECTED && SamSetup.tg_token[0] != 0 && SamSetup.tg_chat_id[0] != 0 && Ping.ping("212.237.16.93", 1)) { // ping the Telegram server
    if (!msg_q.isEmpty()) {
      if (xSemaphoreTake(xMsgSemaphore, (TickType_t)(50 / portTICK_RATE_MS)) == pdTRUE) {
        char c[200];
        msg_q.pop(&c); // Take a message from the queue
        String qMsg = c;
        // Send the message via an HTTP GET to the Telegram Bot API
        // urlEncode is for URL safety
        http_sync_request_get(String("http://212.237.16.93/bot") + SamSetup.tg_token + "/sendMessage?chat_id=" + SamSetup.tg_chat_id + "&text=" + urlEncode(qMsg));
        xSemaphoreGive(xMsgSemaphore); // Release the semaphore
      }
    }
  }
  // ... handling the offline case ...
#endif

  // ... Blynk and MQTT logic, reading pressure/sensors ...
}
```
The `SendMsg` function prepares the message and puts it into a queue (`msg_q`) if Telegram is configured. The `triggerGetClock` task, which runs in the background, periodically checks this queue and, if there is a message and the internet is available, sends it via an HTTP GET request to the Telegram Bot API server. This non-blocking approach does not delay Samovar's main logic. Semaphores are used to make access to the queue safe.

## Conclusion

In this final chapter we looked at **Network & External Communication**, the part of the Samovar system that lets it connect to your Wi-Fi network and interact with the outside world. We saw how `AsyncWiFiManager` simplifies connecting to Wi-Fi, including during initial setup. We learned that Samovar runs a web server for an interactive control panel, serves files from its memory ([Chapter 7: Configuration Persistence](07_configuration_persistence__.md)), and uses a template processor to display dynamic data ([Chapter 4: Sensor Data Acquisition](04_sensor_data_acquisition__.md)) and settings. We also saw how the web interface uses API endpoints to fetch updates and send commands, which are then handled by Samovar's main logic ([Chapter 3: System State & Mode Management](03_system_state___mode_management__.md)). Finally, we looked at how Samovar can communicate with external services such as Blynk, MQTT and Telegram, providing remote monitoring, control and notifications, using data from sensors and the actions of actuators ([Chapter 5: Hardware Control (Actuators)](05_hardware_control__actuators__.md)).

Understanding network communication is the key to Samovar's most powerful features: remote monitoring and control through web or mobile applications.

This concludes our tutorial on the core abstractions of the Samovar project. We have gone from user interaction and program execution through system state management, sensor data, hardware control, safety, settings persistence and, finally, connectivity. You now have a fundamental understanding of how the various parts of the Samovar software work together to control automated brewing and distillation processes.
