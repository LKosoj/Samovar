# Chapter 8: Network & External Communication

Welcome to the final chapter of the Samovar tutorial! We have already covered a lot of topics: how you interact with the device ([Chapter 1: User Interaction (Web & LCD)](01_user_interaction__web___lcd__.md)), how it executes process programs ([Chapter 2: Process Program Execution](02_process_program_execution_.md)), how it manages its state ([Chapter 3: System State & Mode Management](03_system_state___mode_management_.md)), how it reads data from sensors ([Chapter 4: Sensor Data Acquisition](04_sensor_data_acquisition_.md)), how it controls equipment ([Chapter 5: Hardware Control (Actuators)](05_hardware_control__actuators__.md)), how it ensures safety ([Chapter 6: Safety Monitoring & Alarms](06_safety_monitoring___alarms_.md)) and how it saves its settings ([Chapter 7: Configuration Persistence](07_configuration_persistence_.md)).

All of these capabilities would be limited if Samovar could only work in isolation. To unlock its full potential, it needs a connection to the outside world. This is where **Network & External Communication** comes into play. This part of the Samovar software is responsible for everything related to the device going online and interacting with other devices and services.

Imagine giving Samovar a network cable and a smartphone. That lets it connect to your home network (the cable), provides a powerful web interface accessible from any computer or phone (like a built-in website), and even lets it send messages or data to cloud services or to your phone (like an SMS or an update of a remote dashboard).

## Why Network Communication Matters: A Use Case

Imagine you are starting a long, multi-hour brewing process. The physical LCD is good for quick checks when you are next to Samovar, but you will most likely not want to stand beside it the whole time. You may need to:

1.  **Monitor the process remotely:** See the current temperature, progress and status from a computer in another room or even from a smartphone.
2.  **Change settings or trigger actions remotely:** Decide to raise the heater power a little or pause the program without touching the device.
3.  **Receive notifications:** Get a notification on your phone if an alarm has been triggered ([Chapter 6: Safety Monitoring & Alarms](06_safety_monitoring___alarms_.md)) or when a program stage has finished ([Chapter 2: Process Program Execution](02_process_program_execution_.md)).
4.  **View historical data:** Look at temperature charts for the whole run from a computer.

All of these scenarios require Samovar to be connected to your network and able to communicate externally.

## Samovar's Connections: Key Concepts

Samovar's network and external communication involves several key concepts:

1.  **Connecting to Wi-Fi:** Samovar joining your local wireless network.
2.  **Running a web server:** Hosting the interactive web interface that you access through a browser.
3.  **Providing API endpoints:** Creating specific web addresses that the web interface uses to fetch data and send commands (as mentioned in Chapter 1).
4.  **Interacting with external services:** Connecting to the samovar-tool.ru server via Blynk (readings, commands, process log, messages) and, optionally, publishing readings to your own MQTT broker.

Let us look at these in more detail.

## Connecting: Joining a Wi-Fi Network

The first step is connecting Samovar to your Wi-Fi network. For this, Samovar uses the `AsyncWiFiManager` library (ESPAsyncWiFiManager), which makes the process very convenient, especially during initial setup.

It works like this:
*   On power-up, Samovar tries to connect to the Wi-Fi network it was previously configured for (the network name and password are kept by the ESP32 Wi-Fi module itself in its built-in NVS memory, a non-volatile storage that is not erased when the power is off).
*   If the connection succeeds, it obtains an IP address on your network and is ready to work.
*   If the connection *fails* (for example, first start, the network has changed, wrong password), `WiFiManager` automatically switches Samovar into **access point mode (AP Mode)**. That is, Samovar *itself* becomes a temporary Wi-Fi hotspot.
*   Next, you connect your computer or smartphone to *this temporary Samovar access point*.
*   Once connected, a configuration portal opens automatically in the browser (or you go to the address `192.168.4.1`).
*   In this portal you pick your home Wi-Fi network from the list and enter the password.
*   In the same portal you can enter the Blynk token (32 characters); Samovar uses it to connect to the samovar-tool.ru server.
*   After you save the settings, `WiFiManager` remembers the chosen network, shuts down the temporary access point and tries to connect to the chosen home network.
*   After a successful connection, Samovar is fully online on your main network.
*   If the portal is not configured within 6 minutes, Samovar stays an access point named `Samovar` with the password `SamApp123`; the web interface is then available at `192.168.4.1`.

There are two more button actions at power-up: holding the start button for 2 seconds makes Samovar start directly in access point mode, and holding the encoder button for 2 seconds erases the saved Wi-Fi network.

This removes the need to hard-code Wi-Fi passwords in the code and makes commissioning in different environments much easier. If you wish, an initial network can still be set in `user_config_override.h` (`SAMOVAR_WIFI_SSID` and `SAMOVAR_WIFI_PASSWORD`); it is used only if no network has been saved yet.

Look at the `setup()` and `setup_connect_wifi_and_notify()` functions in `Samovar.ino` for the Wi-Fi connection logic:

```c++
// From Samovar.ino (simplified)
void setup() {
  // ... rest of the initialization code, loading the SamSetup settings from NVS (Chapter 7) ...

  WiFi.mode(WIFI_STA); // Station mode (connect to an existing network)
  setup_wifi_stack_defaults(); // WiFi.setHostname(host), auto-reconnect, etc.

  // Is the start button held for 2 seconds? Then go straight to access point mode
  wifiAP = setup_check_ap_button_hold();

  // ...
  setup_connect_wifi_and_notify();
  // ... starting the web server and the rest of the initialization ...
}

static void setup_connect_wifi_and_notify() {
  String StIP;

  if (!wifiAP) {
    // If not forced into AP mode, try auto-connecting with the saved credentials
    AsyncWiFiManagerParameter custom_blynk_token("blynk", "blynk token", SamSetup.blynkauth, 33, "blynk token");
    AsyncWiFiManager wifiManager(&server, &dns); // Pass the web server object

    // ... encoder button held for 2 seconds: wifiManager.resetSettings() ...

    wifiManager.setConfigPortalTimeout(360); // The portal stays open for 6 minutes
    wifiManager.setSaveConfigCallback(saveConfigCallback); // Function called when settings are saved
    wifiManager.setAPCallback(configModeCallback); // Function called when entering AP mode (shows SSID and IP on the LCD)
    wifiManager.setDebugOutput(false);
    // A custom portal field for the Blynk token
    wifiManager.addParameter(&custom_blynk_token);

    // If no network is saved yet, use SAMOVAR_WIFI_SSID/SAMOVAR_WIFI_PASSWORD from user_config_override.h
    apply_initial_wifi_credentials();
    if (!wifiManager.autoConnect("Samovar")) {
      // If auto-connect failed, stay in AP mode
      WiFi.mode(WIFI_AP);
      WiFi.softAP("Samovar", "SamApp123"); // SSID and password for the AP
      StIP = WiFi.softAPIP().toString(); // AP IP address
    } else {
      // If auto-connect succeeded, get the local IP
      StIP = WiFi.localIP().toString();
    }

    if (shouldSaveWiFiConfig) { // Flag from saveConfigCallback
      // Save the Blynk token entered in the portal (exactly 32 characters)
      if (strlen(custom_blynk_token.getValue()) == 32) {
        SetupEEPROM profileCandidate = SamSetup;
        copyStringSafe(profileCandidate.blynkauth, String(custom_blynk_token.getValue()));
        if (save_profile_nvs(profileCandidate) == PERSIST_OK) { // Write to NVS (Chapter 7)
          SamSetup = profileCandidate; // Applied only after a successful write
        }
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
  if (WiFi.getMode() == WIFI_AP) ipst_set(StIP); // In station mode the IP is stored by the Wi-Fi event handler
  Serial.println(StIP);

  MDNS.begin(host); // Access by the name http://samovar.local

  // ... connecting to the Blynk server (see below) and setting up over-the-air updates (OTA) ...
}
```
This fragment shows how `AsyncWiFiManager` handles both the initial connection attempt and the switch to AP mode when necessary. The `saveConfigCallback()` function (not shown here, but simple) just sets the `shouldSaveWiFiConfig` flag, so that custom parameters, such as the Blynk token, can then be saved after Wi-Fi setup.

If over-the-air updates are enabled (`USE_UPDATE_OTA`; OTA means flashing the device over the network without a cable), `ArduinoOTA` is started there as well under the name `samovar`; the Blynk connection is dropped for the duration of an update.

Once Samovar is connected to your network, you can find out its IP (usually shown on the LCD or in the serial monitor at boot) or use its hostname (for example, `samovar.local`) if mDNS is working.

## Providing the Dashboard: The Web Server

Once Samovar is connected to your network, the next step is starting the web server. The server listens for incoming requests on port 80 (the standard for HTTP) and serves web pages (HTML, CSS, images) stored in Samovar's internal file system ([Chapter 7: Configuration Persistence](07_configuration_persistence_.md)).

All of this is set up in the `WebServerInit()` function in `WebServer.ino`:

```c++
// From WebServer.ino (simplified WebServerInit function)
void WebServerInit(void) {
  FS_register_web_handlers(); // The /edit file editor and the "not found" handler (FS.ino)

  // Set up handlers for specific URLs (endpoints)
  server.on("/", HTTP_GET | HTTP_POST, [](AsyncWebServerRequest* request) {
    request->redirect("/index.htm"); // Redirect to index.htm
  });

  // Serve static files (HTML, CSS, images) straight from the file system
  server.serveStatic("/style.css", SPIFFS, "/style.css").setCacheControl("max-age=5000");
  server.serveStatic("/alarm.mp3", SPIFFS, "/alarm.mp3");
  server.serveStatic("/chart.htm", SPIFFS, "/chart.htm").setCacheControl("max-age=1").addMiddleware(&headerFilter);
  // ... other static handlers ...

  // The settings page, with values substituted in (via a template processor)
  server.serveStatic("/setup.htm", SPIFFS, "/setup.htm").setTemplateProcessor(setupKeyProcessor).setCacheControl("max-age=1").addMiddleware(&headerFilter);

  // Main page: the file for the current mode (get_index_page_path()), not cached
  server.on("/index.htm", HTTP_GET, [](AsyncWebServerRequest *request) {
    send_index_page(request);
  }).addMiddleware(&headerFilter);

  // API endpoint handlers for the JavaScript on the page
  server.on("/ajax", HTTP_GET, [](AsyncWebServerRequest *request) {
    send_ajax_json(request); // Current readings and state as JSON
  });
  server.on("/ui-bootstrap", HTTP_GET, [](AsyncWebServerRequest *request) {
    // ... initial data for building the page (JSON) ...
  });
  server.on("/command", HTTP_POST, [](AsyncWebServerRequest *request) {
    web_command(request); // Handle commands from the web page
  });
  server.on("/program", HTTP_POST, [](AsyncWebServerRequest *request) {
    web_program(request); // Handle saving/loading of programs
  });
  server.on("/save", HTTP_POST, [](AsyncWebServerRequest *request) {
    handleSave(request); // Validate the settings form; saving SamSetup is queued and written to NVS (Chapter 7)
  });
  // ... other API endpoints (/data.csv, /calibrate, /i2cstepper, /lua, etc.) ...

  server.serveStatic("/", SPIFFS, "/"); // All other files from SPIFFS

  server.begin(); // Start the web server!
#ifdef __SAMOVAR_DEBUG
  Serial.println("HTTP server started");
#endif
}
```

This code shows how the `ESPAsyncWebServer` library is configured (an asynchronous web server: it handles requests in the background without stopping the rest of the work). It binds specific URLs (`/`, `/style.css`, `/ajax`, `/command`, etc.) either to serving static files from the file system or to executing C++ functions (`send_ajax_json`, `web_command`, `handleSave`). The JavaScript (`app.js`) gets the live data for the main page and the mode pages (temperatures, status, program) through requests to `/ajax` and `/ui-bootstrap`, while the HTML files themselves are served as they are.

The `setupKeyProcessor` function is part of the "template processor" mechanism (substituting values into a page template). When the `setup.htm` page is requested, the server reads the HTML file and calls `setupKeyProcessor` for each placeholder it finds (marks of the form `%name%`, for example `%SteamColor%` or `%WProgram%`). This allows the current settings to be substituted into the HTML before it is sent to the browser, so the settings form shows Samovar's actual values.

```c++
// From WebServer.ino (simplified setupKeyProcessor)
String setupKeyProcessor(const String &var) {
  // Numeric fields, checkboxes, drop-down lists, driven by tables of SamSetup fields
  for (const GetFloat2Field &f : kGetFloat2Fields) {
    if (var == f.var) return format_float(SamSetup.*f.member, 2);
  }
  // ... other field tables ...
  for (const GetColorField &f : kGetColorFields) {
    if (var == f.var) return html_escape(String(SamSetup.*f.member)); // Sensor colors, e.g. %SteamColor%
  }
  if (var == "WProgram") {
    return serialize_program_for_mode(Samovar_Mode); // The current program in the mode's format
  }
  // ... and other HTML placeholders ...
  return ""; // Empty string if the placeholder is not recognized
}
```
This function takes the settings from `SamSetup` (and the current program) and formats them as strings for insertion into the HTML of the settings page.

## External Communication: the samovar-tool.ru Server (Blynk) and MQTT

Besides the web interface, Samovar can send data *outward*. The main channel is the samovar-tool.ru server: the mobile apps and the website work through it. Optionally, you can also enable publishing readings to your own MQTT broker.

### Blynk: Connection to the samovar-tool.ru Server

The connection is enabled by default: `Samovar_ini.h` defines `SAMOVAR_USE_BLYNK` and `BLYNK_SAMOVAR_TOOL "samovar-tool.ru"`. The samovar-tool.ru server is a dedicated Blynk Legacy server (the older, "local" version of the Blynk platform). If a Blynk token is set and Samovar is not in access point mode, at startup it connects to the server on port 8080 (the `BlynkSimpleEsp32` library). The token (32 characters) is the device identifier: the server, the apps and the website use it to know which Samovar they are working with.

Data is exchanged through "virtual pins", numbered channels V0, V1, ... for individual values. Samovar itself sends values via `Blynk.virtualWrite()` and receives commands in `BLYNK_WRITE` handlers. The server does not poll the device: after every `Blynk.run()` in `tick_blynk()` (called from `loop()`), the `blynk_push_tick()` function sends the pins on its own: fast pins every 5 seconds, slow pins on change and once a minute, and all of them at once after a (re)connection.

The process log, session start and messages go over the same connection:

*   **V34 — process log line.** CSV (comma-separated values): format version `5`, session number, status and 25 reading fields (date, temperatures, pressure, program line number, withdrawal rate, voltage, etc.). During a process: every 4 seconds; when idle: every 5 seconds, so the apps see temperatures even without a running process.
*   **V35 — session start.** Once when a process starts: session number, a flag for continuing after a failure, chip identifier, time zone, firmware version, reset reason and description. V35 is always sent before V34 of the same session.
*   **V26 — messages** (alarms, warnings, notifications). Together with them, `Blynk.notify()` is called to send a push notification to the phone.

The server itself writes V34, V35 and V26 to a database, from which the log page on the samovar-tool.ru website and the charts in the apps read them. In addition, the server spreads the fields of the V34 line onto the regular pins V0, V1, V6, V7, V5, V25, V9, V23 (steam, pipe, water and tank temperatures, pressure, TSA temperature, withdrawal rate, pressure from the XGZ/MPX sensor), which the apps display. The website reads the state and sends commands through the HTTP API of the same server. The full pin description is in the mobile apps' `PIN_SPEC.md`.

```c++
// From Samovar.ino (simplified): connecting at startup
if (SamSetup.blynkauth[0] != 0 && !wifiAP) {
#ifdef BLYNK_SAMOVAR_TOOL
  Blynk.config(SamSetup.blynkauth, BLYNK_SAMOVAR_TOOL, 8080); // The samovar-tool.ru server
#else
  Blynk.config(SamSetup.blynkauth);
#endif
  Blynk.connect(BLYNK_TIMEOUT_MS); // Wait no longer than 3 seconds
}

// From Blynk.ino (simplified)
// Called by the server when the app or the website changes V3 (start/reset the process)
BLYNK_WRITE(V3) {
  if (mode_switch_in_progress()) return; // Commands are not accepted while the mode is switching
  bool value = false;
  NumericParseResult result = parse_exact_bool(param.asStr(), value);
  if (!result.ok()) {
    report_blynk_numeric_error(3, result); // The error is sent as a message to V26
    return;
  }
  if (value && PowerOn) {
    menu_samovar_start(); // Rectification: start the program or move to the next line
  } else {
    queue_samovar_reset_command(); // Reset command (signal to the main loop, Chapter 3)
  }
}

// For power control (virtual pin V16)
#ifdef SAMOVAR_USE_POWER
BLYNK_WRITE(V16) {
  // ... parsing the value and checking it against the allowed maximum ...
  set_current_power(value); // Command to the power regulator (Chapter 5)
}
#endif

// The SysTicker task prepares the log line and puts it into the s_pendingV34Line buffer
void blynk_stage_log_line(const String& line);
// The session start line goes into the s_pendingV35Line buffer
void blynk_stage_session_start(const String& line);

// Sending happens from loop(), after Blynk.run()
void blynk_push_tick() {
  // ... snapshot of the V34 buffer ...
  const bool canPushV34 = blynk_push_pending_session_start(); // V35 first
  if (canPushV34) blynk_push_pending_log_line(pendingV34Line, pendingV34Revision, pendingV34Ready); // Then V34
  // ... idle line every 5 seconds, fast and slow pins ...
}
```
This shows the basic pattern: the firmware sends pin values itself, while `BLYNK_WRITE` functions receive commands from the apps or the website and turn them into Samovar commands or actions.

Messages go through a queue so as not to delay the code that creates them:

```c++
// From Samovar.ino (simplified SendMsg function)
void SendMsg(const String& m, MESSAGE_TYPE msg_type) {
  if (m.length() < 5) return;
#ifdef SAMOVAR_USE_BLYNK
  // ... cheese @F1 events go through a separate queue, blynk_stage_floc_event() ...
  if (SamSetup.blynkauth[0] != 0 && !is_notification_token_invalid()) {
    // The first character of the entry is the type: '0' alarm, '1' warning, '2' notification
    String MsgPl = String((char)('0' + msg_type)) + m;
    if (xSemaphoreTake(xMsgSemaphore, (TickType_t)(50 / portTICK_RATE_MS)) == pdTRUE) {
      msg_q.push(MsgPl.c_str(), millis()); // Queue: up to 5 messages of 200 bytes
      xSemaphoreGive(xMsgSemaphore);
    }
  }
#endif
  append_web_message(m, msg_type); // Message for the web interface (Chapter 1)
}

// From Samovar.ino (simplified triggerGetClock task)
void triggerGetClock(void *parameter) {
  while (true) {
    // ... NTP, skipping work during an OTA update ...

    // Reconnect to Blynk if the connection was lost
    if (!Blynk.connected() && !Blynk.isTokenInvalid() &&
        WiFi.status() == WL_CONNECTED && SamSetup.blynkauth[0] != 0) {
      Blynk.connect(BLYNK_TIMEOUT_MS);
    }

    // One message from the queue per pass (msg_q.peek under the xMsgSemaphore semaphore)
    // Header by type: "Тревога! " / "Предупреждение! " (Alarm!/Warning!; in non-Russian firmware "⛔ " / "⚠ ")
    String pushMsg = header + qMsg;
    if (Blynk.connected()) {
      Blynk.virtualWrite(V26, pushMsg); // To the apps and to the log on the server
      Blynk.notify(pushMsg);            // Push notification to the phone
    }
    // The message is removed from the queue after sending or if it has waited more than 15 minutes;
    // with an invalid token the whole queue is cleared

    // ... reading pressure and the BME sensor, checking Wi-Fi ...
  }
}
```
The `SendMsg` function puts the message into the queue (`msg_q`) if a Blynk token is set, and shows it in the web interface. The `triggerGetClock` task, which runs in the background, watches the Blynk connection and sends messages from the queue one at a time to pin V26 and as a push notification. This non-blocking approach does not delay Samovar's main logic. The `xMsgSemaphore` semaphore (a lock that prevents two tasks from changing the queue at the same time) makes access to the queue safe, and the `BlynkLockGuard` lock does the same for Blynk.

### MQTT

If enabled (`#define USE_MQTT` in `user_config_override.h`, off by default), Samovar publishes a short line of readings to your own MQTT broker (MQTT is a simple messaging protocol used in home automation). This is convenient for integrating Samovar's data into home automation systems (Home Assistant, Node-RED, etc.) or other IoT dashboards. MQTT has nothing to do with the samovar-tool.ru server.

The broker address, port, user, password and topic (the channel the message is published to) are set only in `user_config_override.h`: `MQTT_SERVER`, `MQTT_PORT` (1883 by default), `MQTT_USER`, `MQTT_PASSWORD`, `MQTT_TOPIC` (`samovar/state` by default); the web interface does not store them. The connection is unencrypted (no TLS).

```c++
// From SamovarMqtt.h (simplified)
#ifdef USE_MQTT

inline bool init_mqtt() { // Called from setup() if Samovar is not in access point mode
  esp_mqtt_client_config_t config = {};
  config.host = MQTT_SERVER;
  config.port = MQTT_PORT;
  // ... user, password, TCP transport, reconnect every 10 seconds ...
  mqttClient = esp_mqtt_client_init(&config);
  return mqttClient && esp_mqtt_client_start(mqttClient) == ESP_OK;
}

inline bool mqtt_publish_log_line(const String& line) {
  if (!mqttClient || !mqttClientConnected) return false;
  // While the broker has not acknowledged the previous message, the new one is skipped
  if (esp_mqtt_client_get_outbox_size(mqttClient) != 0) return false;
  return esp_mqtt_client_enqueue(
      mqttClient, MQTT_TOPIC, line.c_str(), line.length(), 1, true, false) >= 0; // QoS 1, retain
}

#endif // USE_MQTT
```
Publishing is triggered by `tick_mqtt()` from `loop()` in `Samovar.ino`: every 4 seconds during a process, every 5 seconds when idle, and not earlier than 2 seconds after a large send to Blynk. The line is built by `build_mqtt_log_line()`; it is CSV: `1`, time, mode, status, program line number and type, steam, pipe, water, tank and TSA temperatures, atmospheric pressure, pressure from the XGZ/MPX sensor, power and withdrawal rate. QoS 1 means the broker acknowledges receipt, and `retain` means the broker keeps the last value and immediately gives it to new subscribers.

## Conclusion

In this final chapter we looked at **Network & External Communication**, the part of the Samovar system that lets it connect to your Wi-Fi network and interact with the outside world. We saw how `AsyncWiFiManager` simplifies connecting to Wi-Fi, including during initial setup. We learned that Samovar runs a web server for an interactive control panel, serves files from its memory ([Chapter 7: Configuration Persistence](07_configuration_persistence_.md)), provides live data ([Chapter 4: Sensor Data Acquisition](04_sensor_data_acquisition_.md)) through API endpoints and substitutes settings into the settings page with a template processor. We also saw how the web interface uses these endpoints to fetch updates and send commands, which are then handled by Samovar's main logic ([Chapter 3: System State & Mode Management](03_system_state___mode_management_.md)). Finally, we looked at how Samovar connects via Blynk to the samovar-tool.ru server (readings, commands, the V34 process log, the V35 session start, V26 messages and push notifications) and, optionally, publishes readings to your own MQTT broker, providing remote monitoring, control and notifications, using data from sensors and the actions of actuators ([Chapter 5: Hardware Control (Actuators)](05_hardware_control__actuators__.md)).

Understanding network communication is the key to Samovar's most powerful features: remote monitoring and control through web or mobile applications.

This concludes our tutorial on the core abstractions of the Samovar project. We have gone from user interaction and program execution through system state management, sensor data, hardware control, safety, settings persistence and, finally, connectivity. You now have a fundamental understanding of how the various parts of the Samovar software work together to control automated brewing and distillation processes.
