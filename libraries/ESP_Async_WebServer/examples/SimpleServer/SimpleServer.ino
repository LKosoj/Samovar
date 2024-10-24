//
// A simple server implementation showing how to:
//  * serve static messages
//  * read GET and POST parameters
//  * handle missing pages / 404s
//

#include <Arduino.h>
#ifdef ESP32
  #include <AsyncTCP.h>
  #include <WiFi.h>
#elif defined(ESP8266)
  #include <ESP8266WiFi.h>
  #include <ESPAsyncTCP.h>
#elif defined(TARGET_RP2040)
  #include <WebServer.h>
  #include <WiFi.h>
#endif

#include <ESPAsyncWebServer.h>

#if __has_include("ArduinoJson.h")
  #include <ArduinoJson.h>
  #include <AsyncJson.h>
  #include <AsyncMessagePack.h>
#endif

#include <LittleFS.h>

const char* htmlContent PROGMEM = R"(
<!DOCTYPE html>
<html>
<head>
    <title>Sample HTML</title>
</head>
<body>
    <h1>Hello, World!</h1>
    <p>Lorem ipsum dolor sit amet, consectetur adipiscing elit. Proin euismod, purus a euismod
    rhoncus, urna ipsum cursus massa, eu dictum tellus justo ac justo. Quisque ullamcorper
    arcu nec tortor ullamcorper, vel fermentum justo fermentum. Vivamus sed velit ut elit
    accumsan congue ut ut enim. Ut eu justo eu lacus varius gravida ut a tellus. Nulla facilisi.
    Integer auctor consectetur ultricies. Fusce feugiat, mi sit amet bibendum viverra, orci leo
    dapibus elit, id varius sem dui id lacus.</p>
    <p>Lorem ipsum dolor sit amet, consectetur adipiscing elit. Proin euismod, purus a euismod
    rhoncus, urna ipsum cursus massa, eu dictum tellus justo ac justo. Quisque ullamcorper
    arcu nec tortor ullamcorper, vel fermentum justo fermentum. Vivamus sed velit ut elit
    accumsan congue ut ut enim. Ut eu justo eu lacus varius gravida ut a tellus. Nulla facilisi.
    Integer auctor consectetur ultricies. Fusce feugiat, mi sit amet bibendum viverra, orci leo
    dapibus elit, id varius sem dui id lacus.</p>
    <p>Lorem ipsum dolor sit amet, consectetur adipiscing elit. Proin euismod, purus a euismod
    rhoncus, urna ipsum cursus massa, eu dictum tellus justo ac justo. Quisque ullamcorper
    arcu nec tortor ullamcorper, vel fermentum justo fermentum. Vivamus sed velit ut elit
    accumsan congue ut ut enim. Ut eu justo eu lacus varius gravida ut a tellus. Nulla facilisi.
    Integer auctor consectetur ultricies. Fusce feugiat, mi sit amet bibendum viverra, orci leo
    dapibus elit, id varius sem dui id lacus.</p>
    <p>Lorem ipsum dolor sit amet, consectetur adipiscing elit. Proin euismod, purus a euismod
    rhoncus, urna ipsum cursus massa, eu dictum tellus justo ac justo. Quisque ullamcorper
    arcu nec tortor ullamcorper, vel fermentum justo fermentum. Vivamus sed velit ut elit
    accumsan congue ut ut enim. Ut eu justo eu lacus varius gravida ut a tellus. Nulla facilisi.
    Integer auctor consectetur ultricies. Fusce feugiat, mi sit amet bibendum viverra, orci leo
    dapibus elit, id varius sem dui id lacus.</p>
    <p>Lorem ipsum dolor sit amet, consectetur adipiscing elit. Proin euismod, purus a euismod
    rhoncus, urna ipsum cursus massa, eu dictum tellus justo ac justo. Quisque ullamcorper
    arcu nec tortor ullamcorper, vel fermentum justo fermentum. Vivamus sed velit ut elit
    accumsan congue ut ut enim. Ut eu justo eu lacus varius gravida ut a tellus. Nulla facilisi.
    Integer auctor consectetur ultricies. Fusce feugiat, mi sit amet bibendum viverra, orci leo
    dapibus elit, id varius sem dui id lacus.</p>
    <p>Lorem ipsum dolor sit amet, consectetur adipiscing elit. Proin euismod, purus a euismod
    rhoncus, urna ipsum cursus massa, eu dictum tellus justo ac justo. Quisque ullamcorper
    arcu nec tortor ullamcorper, vel fermentum justo fermentum. Vivamus sed velit ut elit
    accumsan congue ut ut enim. Ut eu justo eu lacus varius gravida ut a tellus. Nulla facilisi.
    Integer auctor consectetur ultricies. Fusce feugiat, mi sit amet bibendum viverra, orci leo
    dapibus elit, id varius sem dui id lacus.</p>
    <p>Lorem ipsum dolor sit amet, consectetur adipiscing elit. Proin euismod, purus a euismod
    rhoncus, urna ipsum cursus massa, eu dictum tellus justo ac justo. Quisque ullamcorper
    arcu nec tortor ullamcorper, vel fermentum justo fermentum. Vivamus sed velit ut elit
    accumsan congue ut ut enim. Ut eu justo eu lacus varius gravida ut a tellus. Nulla facilisi.
    Integer auctor consectetur ultricies. Fusce feugiat, mi sit amet bibendum viverra, orci leo
    dapibus elit, id varius sem dui id lacus.</p>
    <p>Lorem ipsum dolor sit amet, consectetur adipiscing elit. Proin euismod, purus a euismod
    rhoncus, urna ipsum cursus massa, eu dictum tellus justo ac justo. Quisque ullamcorper
    arcu nec tortor ullamcorper, vel fermentum justo fermentum. Vivamus sed velit ut elit
    accumsan congue ut ut enim. Ut eu justo eu lacus varius gravida ut a tellus. Nulla facilisi.
    Integer auctor consectetur ultricies. Fusce feugiat, mi sit amet bibendum viverra, orci leo
    dapibus elit, id varius sem dui id lacus.</p>
</body>
</html>
)";

AsyncWebServer server(80);
AsyncEventSource events("/events");
AsyncWebSocket ws("/ws");

/////////////////////////////////////////////////////////////////////////////////////////////////////
// Middlewares
/////////////////////////////////////////////////////////////////////////////////////////////////////

// log incoming requests
LoggingMiddleware requestLogger;

// CORS
CorsMiddleware cors;

// maximum 5 requests per 10 seconds
RateLimitMiddleware rateLimit;

// filter out specific headers from the incoming request
HeaderFilterMiddleware headerFilter;

// remove all headers from the incoming request except the ones provided in the constructor
HeaderFreeMiddleware headerFree;

// basicAuth
AuthenticationMiddleware basicAuth;
AuthenticationMiddleware basicAuthHash;

// simple digest authentication
AuthenticationMiddleware digestAuth;
AuthenticationMiddleware digestAuthHash;

// complex authentication which adds request attributes for the next middlewares and handler
AsyncMiddlewareFunction complexAuth([](AsyncWebServerRequest* request, ArMiddlewareNext next) {
  if (!request->authenticate("user", "password")) {
    return request->requestAuthentication();
  }
  request->setAttribute("user", "Mathieu");
  request->setAttribute("role", "staff");

  next();

  request->getResponse()->addHeader("X-Rate-Limit", "200");
});

AuthorizationMiddleware authz([](AsyncWebServerRequest* request) { return request->getAttribute("role") == "staff"; });

/////////////////////////////////////////////////////////////////////////////////////////////////////

const char* PARAM_MESSAGE PROGMEM = "message";
const char* SSE_HTLM PROGMEM = R"(
<!DOCTYPE html>
<html>
<head>
  <title>Server-Sent Events</title>
  <script>
    if (!!window.EventSource) {
      var source = new EventSource('/events');
      source.addEventListener('open', function(e) {
        console.log("Events Connected");
      }, false);
      source.addEventListener('error', function(e) {
        if (e.target.readyState != EventSource.OPEN) {
          console.log("Events Disconnected");
        }
      }, false);
      source.addEventListener('message', function(e) {
        console.log("message", e.data);
      }, false);
      source.addEventListener('heartbeat', function(e) {
        console.log("heartbeat", e.data);
      }, false);
    }
  </script>
</head>
<body>
  <h1>Open your browser console!</h1>
</body>
</html>
)";

void notFound(AsyncWebServerRequest* request) {
  request->send(404, "text/plain", "Not found");
}

#if __has_include("ArduinoJson.h")
AsyncCallbackJsonWebHandler* jsonHandler = new AsyncCallbackJsonWebHandler("/json2");
AsyncCallbackMessagePackWebHandler* msgPackHandler = new AsyncCallbackMessagePackWebHandler("/msgpack2");
#endif

static const char characters[] = "0123456789ABCDEF";
static size_t charactersIndex = 0;

void setup() {

  Serial.begin(115200);

#ifndef CONFIG_IDF_TARGET_ESP32H2
  // WiFi.mode(WIFI_STA);
  // WiFi.begin("YOUR_SSID", "YOUR_PASSWORD");
  // if (WiFi.waitForConnectResult() != WL_CONNECTED) {
  //   Serial.printf("WiFi Failed!\n");
  //   return;
  // }
  // Serial.print("IP Address: ");
  // Serial.println(WiFi.localIP());

  WiFi.mode(WIFI_AP);
  WiFi.softAP("esp-captive");
#endif

#ifdef ESP32
  LittleFS.begin(true);
#else
  LittleFS.begin();
#endif

  if (!LittleFS.exists("/index.txt")) {
    File f = LittleFS.open("/index.txt", "w");
    if (f) {
      for (size_t c = 0; c < sizeof(characters); c++) {
        for (size_t i = 0; i < 1024; i++) {
          f.print(characters[c]);
        }
      }
      f.close();
    }
  }

  // curl -v -X GET http://192.168.4.1/handler-not-sending-response
  server.on("/handler-not-sending-response", HTTP_GET, [](AsyncWebServerRequest* request) {
    // handler forgot to send a response to the client => 501 Not Implemented
  });

  // This is possible to replace a response.
  // the previous one will be deleted.
  // response sending happens when the handler returns.
  // curl -v -X GET http://192.168.4.1/replace
  server.on("/replace", HTTP_GET, [](AsyncWebServerRequest* request) {
    request->send(200, "text/plain", "Hello, world");
    // oups! finally we want to send a different response
    request->send(400, "text/plain", "validation error");
#ifndef TARGET_RP2040
    Serial.printf("Free heap: %" PRIu32 "\n", ESP.getFreeHeap());
#endif
  });

  ///////////////////////////////////////////////////////////////////////
  // Request header manipulations
  ///////////////////////////////////////////////////////////////////////

  // curl -v -X GET -H "x-remove-me: value" http://192.168.4.1/headers
  server.on("/headers", HTTP_GET, [](AsyncWebServerRequest* request) {
    Serial.printf("Request Headers:\n");
    for (auto& h : request->getHeaders())
      Serial.printf("Request Header: %s = %s\n", h.name().c_str(), h.value().c_str());

    // remove x-remove-me header
    request->removeHeader("x-remove-me");
    Serial.printf("Request Headers:\n");
    for (auto& h : request->getHeaders())
      Serial.printf("Request Header: %s = %s\n", h.name().c_str(), h.value().c_str());

    std::vector<const char*> headers;
    request->getHeaderNames(headers);
    for (auto& h : headers)
      Serial.printf("Request Header Name: %s\n", h);

    request->send(200);
  });

  ///////////////////////////////////////////////////////////////////////
  // Middlewares at server level (will apply to all requests)
  ///////////////////////////////////////////////////////////////////////

  requestLogger.setOutput(Serial);

  basicAuth.setUsername("admin");
  basicAuth.setPassword("admin");
  basicAuth.setRealm("MyApp");
  basicAuth.setAuthFailureMessage("Authentication failed");
  basicAuth.setAuthType(AsyncAuthType::AUTH_BASIC);
  basicAuth.generateHash();

  basicAuthHash.setUsername("admin");
  basicAuthHash.setPasswordHash("YWRtaW46YWRtaW4="); // BASE64(admin:admin)
  basicAuthHash.setRealm("MyApp");
  basicAuthHash.setAuthFailureMessage("Authentication failed");
  basicAuthHash.setAuthType(AsyncAuthType::AUTH_BASIC);

  digestAuth.setUsername("admin");
  digestAuth.setPassword("admin");
  digestAuth.setRealm("MyApp");
  digestAuth.setAuthFailureMessage("Authentication failed");
  digestAuth.setAuthType(AsyncAuthType::AUTH_DIGEST);
  digestAuth.generateHash();

  digestAuthHash.setUsername("admin");
  digestAuthHash.setPasswordHash("f499b71f9a36d838b79268e145e132f7"); // MD5(user:realm:pass)
  digestAuthHash.setRealm("MyApp");
  digestAuthHash.setAuthFailureMessage("Authentication failed");
  digestAuthHash.setAuthType(AsyncAuthType::AUTH_DIGEST);

  rateLimit.setMaxRequests(5);
  rateLimit.setWindowSize(10);

  headerFilter.filter("X-Remove-Me");
  headerFree.keep("X-Keep-Me");
  headerFree.keep("host");

  cors.setOrigin("http://192.168.4.1");
  cors.setMethods("POST, GET, OPTIONS, DELETE");
  cors.setHeaders("X-Custom-Header");
  cors.setAllowCredentials(false);
  cors.setMaxAge(600);

#ifndef PERF_TEST
  // global middleware
  server.addMiddleware(&requestLogger);
  server.addMiddlewares({&rateLimit, &cors, &headerFilter});
#endif

  // Test CORS preflight request
  // curl -v -X OPTIONS -H "origin: http://192.168.4.1" http://192.168.4.1/middleware/cors
  server.on("/middleware/cors", HTTP_GET, [](AsyncWebServerRequest* request) {
    request->send(200, "text/plain", "Hello, world!");
  });

  // curl -v -X GET -H "x-remove-me: value" http://192.168.4.1/middleware/test-header-filter
  // - requestLogger will log the incoming headers (including x-remove-me)
  // - headerFilter will remove x-remove-me header
  // - handler will log the remaining headers
  server.on("/middleware/test-header-filter", HTTP_GET, [](AsyncWebServerRequest* request) {
    for (auto& h : request->getHeaders())
      Serial.printf("Request Header: %s = %s\n", h.name().c_str(), h.value().c_str());
    request->send(200);
  });

  // curl -v -X GET -H "x-keep-me: value" http://192.168.4.1/middleware/test-header-free
  // - requestLogger will log the incoming headers (including x-keep-me)
  // - headerFree will remove all headers except x-keep-me and host
  // - handler will log the remaining headers (x-keep-me and host)
  server.on("/middleware/test-header-free", HTTP_GET, [](AsyncWebServerRequest* request) {
          for (auto& h : request->getHeaders())
            Serial.printf("Request Header: %s = %s\n", h.name().c_str(), h.value().c_str());
          request->send(200);
        })
    .addMiddleware(&headerFree);

  // basic authentication method
  // curl -v -X GET -H "origin: http://192.168.4.1" -u admin:admin  http://192.168.4.1/middleware/auth-basic
  server.on("/middleware/auth-basic", HTTP_GET, [](AsyncWebServerRequest* request) {
          request->send(200, "text/plain", "Hello, world!");
        })
    .addMiddleware(&basicAuth);

  // basic authentication method with hash
  // curl -v -X GET -H "origin: http://192.168.4.1" -u admin:admin  http://192.168.4.1/middleware/auth-basic-hash
  server.on("/middleware/auth-basic-hash", HTTP_GET, [](AsyncWebServerRequest* request) {
          request->send(200, "text/plain", "Hello, world!");
        })
    .addMiddleware(&basicAuthHash);

  // digest authentication
  // curl -v -X GET -H "origin: http://192.168.4.1" -u admin:admin --digest  http://192.168.4.1/middleware/auth-digest
  server.on("/middleware/auth-digest", HTTP_GET, [](AsyncWebServerRequest* request) {
          request->send(200, "text/plain", "Hello, world!");
        })
    .addMiddleware(&digestAuth);

  // digest authentication with hash
  // curl -v -X GET -H "origin: http://192.168.4.1" -u admin:admin --digest  http://192.168.4.1/middleware/auth-digest-hash
  server.on("/middleware/auth-digest-hash", HTTP_GET, [](AsyncWebServerRequest* request) {
          request->send(200, "text/plain", "Hello, world!");
        })
    .addMiddleware(&digestAuthHash);

  // test digest auth with cors
  // curl -v -X GET -H "origin: http://192.168.4.1" --digest -u user:password  http://192.168.4.1/middleware/auth-custom
  server.on("/middleware/auth-custom", HTTP_GET, [](AsyncWebServerRequest* request) {
          String buffer = "Hello ";
          buffer.concat(request->getAttribute("user"));
          buffer.concat(" with role: ");
          buffer.concat(request->getAttribute("role"));
          request->send(200, "text/plain", buffer);
        })
    .addMiddlewares({&complexAuth, &authz});

  ///////////////////////////////////////////////////////////////////////

  // curl -v -X GET -H "origin: http://192.168.4.1" http://192.168.4.1/redirect
  // curl -v -X POST -H "origin: http://192.168.4.1" http://192.168.4.1/redirect
  server.on("/redirect", HTTP_GET | HTTP_POST, [](AsyncWebServerRequest* request) {
    request->redirect("/");
  });

  // PERF TEST:
  // > brew install autocannon
  // > autocannon -c 10 -w 10 -d 20 http://192.168.4.1
  server.on("/", HTTP_GET, [](AsyncWebServerRequest* request) {
    request->send(200, "text/html", htmlContent);
  });

  // curl -v -X GET http://192.168.4.1/index.txt
  server.serveStatic("/index.txt", LittleFS, "/index.txt");

  // Issue #14: assert failed: tcp_update_rcv_ann_wnd (needs help to test fix)
  // > curl -v http://192.168.4.1/issue-14
  pinMode(4, OUTPUT);
  server.on("/issue-14", HTTP_GET, [](AsyncWebServerRequest* request) {
    digitalWrite(4, HIGH);
    request->send(LittleFS, "/index.txt", "text/pain");
    delay(500);
    digitalWrite(4, LOW);
  });

  /*
    Chunked encoding test: sends 16k of characters.
    ❯ curl -N -v -X GET -H "origin: http://192.168.4.1" http://192.168.4.1/chunk
  */
  server.on("/chunk", HTTP_HEAD | HTTP_GET, [](AsyncWebServerRequest* request) {
    AsyncWebServerResponse* response = request->beginChunkedResponse("text/html", [](uint8_t* buffer, size_t maxLen, size_t index) -> size_t {
      if (index >= 16384)
        return 0;
      memset(buffer, characters[charactersIndex], maxLen);
      charactersIndex = (charactersIndex + 1) % sizeof(characters);
      return maxLen;
    });
    request->send(response);
  });

  /*
    ❯ curl -I -X HEAD http://192.168.4.1/download
    HTTP/1.1 200 OK
    Content-Length: 1024
    Content-Type: application/octet-stream
    Connection: close
    Accept-Ranges: bytes
  */
  // Ref: https://github.com/mathieucarbou/ESPAsyncWebServer/pull/80
  server.on("/download", HTTP_HEAD | HTTP_GET, [](AsyncWebServerRequest* request) {
    if (request->method() == HTTP_HEAD) {
      AsyncWebServerResponse* response = request->beginResponse(200, "application/octet-stream");
      response->addHeader(asyncsrv::T_Accept_Ranges, "bytes");
      response->addHeader(asyncsrv::T_Content_Length, 10);
      response->setContentLength(1024); // overrides previous one
      response->addHeader(asyncsrv::T_Content_Type, "foo");
      response->setContentType("application/octet-stream"); // overrides previous one
      // ...
      request->send(response);
    } else {
      // ...
    }
  });

  // Send a GET request to <IP>/get?message=<message>
  server.on("/get", HTTP_GET, [](AsyncWebServerRequest* request) {
    String message;
    if (request->hasParam(PARAM_MESSAGE)) {
      message = request->getParam(PARAM_MESSAGE)->value();
    } else {
      message = "No message sent";
    }
    request->send(200, "text/plain", "Hello, GET: " + message);
  });

  // Send a POST request to <IP>/post with a form field message set to <message>
  server.on("/post", HTTP_POST, [](AsyncWebServerRequest* request) {
    String message;
    if (request->hasParam(PARAM_MESSAGE, true)) {
      message = request->getParam(PARAM_MESSAGE, true)->value();
    } else {
      message = "No message sent";
    }
    request->send(200, "text/plain", "Hello, POST: " + message);
  });

#if __has_include("ArduinoJson.h")
  // JSON

  // receives JSON and sends JSON
  jsonHandler->onRequest([](AsyncWebServerRequest* request, JsonVariant& json) {
    // JsonObject jsonObj = json.as<JsonObject>();
    // ...

    AsyncJsonResponse* response = new AsyncJsonResponse();
    JsonObject root = response->getRoot().to<JsonObject>();
    root["hello"] = "world";
    response->setLength();
    request->send(response);
  });

  // sends JSON
  // curl -v -X GET http://192.168.4.1/json1
  server.on("/json1", HTTP_GET, [](AsyncWebServerRequest* request) {
    AsyncJsonResponse* response = new AsyncJsonResponse();
    JsonObject root = response->getRoot().to<JsonObject>();
    root["hello"] = "world";
    response->setLength();
    request->send(response);
  });

  // curl -v -X GET http://192.168.4.1/json2
  server.on("/json2", HTTP_GET, [](AsyncWebServerRequest* request) {
    AsyncResponseStream* response = request->beginResponseStream("application/json");
    JsonDocument doc;
    JsonObject root = doc.to<JsonObject>();
    root["hello"] = "world";
    serializeJson(root, *response);
    request->send(response);
  });

  // MessagePack

  // receives MessagePack and sends MessagePack
  msgPackHandler->onRequest([](AsyncWebServerRequest* request, JsonVariant& json) {
    // JsonObject jsonObj = json.as<JsonObject>();
    // ...

    AsyncMessagePackResponse* response = new AsyncMessagePackResponse();
    JsonObject root = response->getRoot().to<JsonObject>();
    root["hello"] = "world";
    response->setLength();
    request->send(response);
  });

  // sends MessagePack
  server.on("/msgpack1", HTTP_GET, [](AsyncWebServerRequest* request) {
    AsyncMessagePackResponse* response = new AsyncMessagePackResponse();
    JsonObject root = response->getRoot().to<JsonObject>();
    root["hello"] = "world";
    response->setLength();
    request->send(response);
  });
#endif

  events.onConnect([](AsyncEventSourceClient* client) {
    if (client->lastId()) {
      Serial.printf("SSE Client reconnected! Last message ID that it gat is: %" PRIu32 "\n", client->lastId());
    }
    client->send("hello!", NULL, millis(), 1000);
  });

  server.on("/sse", HTTP_GET, [](AsyncWebServerRequest* request) {
    request->send(200, "text/html", SSE_HTLM);
  });

  ws.onEvent([](AsyncWebSocket* server, AsyncWebSocketClient* client, AwsEventType type, void* arg, uint8_t* data, size_t len) {
    (void)len;
    if (type == WS_EVT_CONNECT) {
      Serial.println("ws connect");
      client->setCloseClientOnQueueFull(false);
      client->ping();
    } else if (type == WS_EVT_DISCONNECT) {
      Serial.println("ws disconnect");
    } else if (type == WS_EVT_ERROR) {
      Serial.println("ws error");
    } else if (type == WS_EVT_PONG) {
      Serial.println("ws pong");
    } else if (type == WS_EVT_DATA) {
      AwsFrameInfo* info = (AwsFrameInfo*)arg;
      String msg = "";
      if (info->final && info->index == 0 && info->len == len) {
        if (info->opcode == WS_TEXT) {
          data[len] = 0;
          Serial.printf("ws text: %s\n", (char*)data);
        }
      }
    }
  });

  // go to http://192.168.4.1/sse
  server.addHandler(&events);

  // Run: websocat ws://192.168.4.1/ws
  server.addHandler(&ws);

#if __has_include("ArduinoJson.h")
  server.addHandler(jsonHandler);
  server.addHandler(msgPackHandler);
#endif

  server.onNotFound(notFound);

  server.begin();
}

uint32_t lastSSE = 0;
uint32_t deltaSSE = 5;

uint32_t lastWS = 0;
uint32_t deltaWS = 100;

void loop() {
  uint32_t now = millis();
  if (now - lastSSE >= deltaSSE) {
    events.send(String("ping-") + now, "heartbeat", now);
    lastSSE = millis();
  }
  if (now - lastWS >= deltaWS) {
    ws.printfAll("kp%.4f", (10.0 / 3.0));
    for (auto& client : ws.getClients()) {
      client.printf("kp%.4f", (10.0 / 3.0));
    }
    lastWS = millis();
  }
}
