# Chapter 1: User Interaction (Web Interface and LCD)

Welcome to the Samovar tutorial! The first chapter is about how you, the user, can interact with the Samovar system for brewing and distillation. Think of Samovar as a complex machine, and of the user interaction interfaces as its dashboard and control panel. They let you see what Samovar is doing, check its state, and give it commands to perform various tasks.

Whether you are simply monitoring the temperature or setting up a complex brewing program, you need a way to communicate with Samovar. This is where the user interfaces come in. Samovar provides two main ways to do this:

1.  **Physical interface:** a built-in LCD with buttons and a rotary encoder (the kind of rotating knob you may have seen).
2.  **Web interface:** a control panel that you can access from a web browser on your computer or smartphone connected to the same network.

Let's imagine a simple task: you want to see the current temperature inside the brewing vessel, and then start a pre-programmed brewing process. Both the LCD and the web interface let you do this.

## Physical Interface: LCD and Buttons

The LCD shows important information directly on the Samovar device. Next to the screen there are buttons or a rotary encoder. These physical controls let you navigate the menus, browse the different screens, and make simple selections or settings.

### Viewing Information on the LCD

Samovar uses the LCD to display real-time data. This includes sensor readings such as temperature, the current process status, timers and menu options.

Here is a quick look at how the system defines what is shown on the LCD (using the `LiquidCrystal_I2C` and `LiquidMenu` libraries):

```c++
// From Menu.ino
LiquidLine lql_steam_temp(0, 0, str_Steam_T, SteamSensor.avgTemp);
LiquidLine lql_pipe_temp(0, 1, str_Pipe_T, PipeSensor.avgTemp);
LiquidLine lql_water_temp(0, 2, str_Water_T, WaterSensor.avgTemp);
LiquidScreen main_screen(lql_steam_temp, lql_pipe_temp, lql_water_temp, lql_time);
```

This snippet shows how "lines" of text (`LiquidLine`) are defined, linking descriptive text (for example, "Steam T:") with sensor data (for example, `SteamSensor.avgTemp`). These lines are then grouped into "screens" (`LiquidScreen`). Here `main_screen` is set up to show the steam, column (pipe) and water temperatures, as well as the current time. The LCD library (`LiquidCrystal_I2C`) is responsible for actually drawing this text on the screen.

The system must regularly refresh what is shown on the LCD:

```c++
// From Menu.ino
void menu_update() {
  LcdLockGuard lcdLock;                // Takes xI2CSemaphore for LCD_UPDATE_TIMEOUT ms
  if (lcdLock) main_menu1.update();    // This tells the menu system to refresh the display
}                                      // The semaphore is released automatically on exit
```

This function is called repeatedly to keep the information on the LCD up to date. The `LcdLockGuard` object manages access to the display: its constructor takes the `xI2CSemaphore` semaphore (`xSemaphoreTake`), and it gives it back by itself when the function exits (`xSemaphoreGive`). This way different parts of the program do not try to use the LCD and the I2C bus at the same time, which could cause problems. If the semaphore is busy for longer than `LCD_UPDATE_TIMEOUT` (200 ms), the screen update is simply skipped.

### Control with Buttons/Encoder

Physical buttons or, more commonly, a rotary encoder with a push button are used to interact with the menu on the LCD.

The rotary encoder lets you:
* Turn it left or right to move through menu items or change values.
* Press the button (click) to select an item or confirm a change.

The code constantly checks for the following actions:

```c++
// From Menu.ino (simplified; before the call, loop() polls the encoder with encoder.tick())
void encoder_getvalue() {
  if (encoder.isRight()) {
    // The user turned right -- possibly go to the next screen or increase a value
    if (!main_menu1.is_callable(1)) { // If the current item is not clickable...
      menu_next_screen(); // ...go to the next screen
    } else {
      main_menu1.call_function(1); // ...otherwise execute the associated function (for example, increase a value)
    }
  } else if (encoder.isLeft()) {
    // The user turned left -- possibly go to the previous screen or decrease a value
    if (!main_menu1.is_callable(2)) { // If the current item is not clickable...
      menu_previous_screen(); // ...go to the previous screen
    } else {
      main_menu1.call_function(2); // ...otherwise execute the associated function (for example, decrease a value)
    }
  } else if (encoder.isRightH() || encoder.isLeftH()) {
    // Turning with the button held down -- the same value change, but with a 10 times larger step
    multiplier = 10;
    main_menu1.call_function(encoder.isRightH() ? 1 : 2);
  } else if (encoder.isClick()) {
    // The user pressed the button -- select the current option or change focus
    menu_switch_focus();
  }
  // ... periodic screen updates also happen here ...
}
```
The `encoder_getvalue` function reads the encoder state. Depending on whether it was turned left/right or pressed, it either moves between screens (`menu_next_screen`, `menu_previous_screen`) or calls a specific function associated with the currently selected item (`main_menu1.call_function`). For example, turning right on a temperature setting can call a function that increases the target temperature. A click can switch the focus to allow editing the value. During calibration of the withdrawal pump, turning the encoder changes the stepper motor speed, and a click ends the calibration.

To start our imaginary process using the LCD, we would navigate the screens with the encoder until we find the ">Start:" line, and then press the button. This runs the `menu_samovar_start()` function. It works only in rectification mode and only when the power (heating) is on.

## Web Interface

The web interface provides a richer and more visual way to interact with Samovar. You can access it through a web browser (for example, Chrome, Firefox, Safari) by entering the IP address of Samovar. This interface often shows the information from the LCD, but may include additional features such as charts, detailed settings and easy program editing.

### Viewing Information on the Web

The web interface displays sensor data, status messages, program progress and various system parameters. It is like a full control panel on your computer or phone.

The data displayed on the web comes from Samovar, which sends information, usually in a structured format such as JSON, to the web page running in your browser. The web page then updates its display using this data.

```c++
// From WebServer.ino
server.on("/ajax", HTTP_GET, [](AsyncWebServerRequest *request) {
  send_ajax_json(request); // Collect the current data and send it to the browser as JSON
});
```

This snippet shows part of the web server code. When the browser requests the `/ajax` address (this happens periodically in the background on the web page, with a request like `/ajax?messageCursor=…`), Samovar calls the `send_ajax_json()` function (it is located in `Samovar.ino`). The function takes a snapshot of the latest data (temperatures, status, etc.) and sends it to the browser as JSON (a response of type `application/json`), together with the new messages that appeared after the `messageCursor` number. The browser updates the web page elements with the new values. The initial data (mode, settings, program) is loaded by the page when it opens, with a single `/ui-bootstrap` request.

The web pages themselves (such as `index.htm` and `chart.htm`) are stored in the internal Samovar file system (LittleFS; the code accesses it through the name `SPIFFS`) and served by the web server.

```c++
// From WebServer.ino
server.on("/index.htm", HTTP_GET, [](AsyncWebServerRequest *request) {
  send_index_page(request); // Send the page of the current mode
}).addMiddleware(&headerFilter);
server.serveStatic("/chart.htm", SPIFFS, "/chart.htm").setCacheControl("max-age=1").addMiddleware(&headerFilter);
server.serveStatic("/setup.htm", SPIFFS, "/setup.htm").setTemplateProcessor(setupKeyProcessor).setCacheControl("max-age=1").addMiddleware(&headerFilter);
// ... other files such as style.css, images ...
```

This tells the web server that when the browser requests `/chart.htm` or `/setup.htm`, it should send the corresponding file from its storage. For a `/index.htm` request, the `send_index_page()` function sends the page of the current mode: `index.htm` for rectification, sous vide and Lua, and `distiller.htm`, `beer.htm`, `bk.htm`, `nbk.htm` or `cheese.htm` for the other modes. The `.setTemplateProcessor(setupKeyProcessor)` part of the settings page is interesting -- it means that the server replaces placeholders in the HTML file (such as `%SteamColor%` or `%WProgram%`) with values from the current Samovar settings *before* sending the file to the browser. This lets the settings page load with the right values. The other pages do not use templates: they get their data through the `/ui-bootstrap` and `/ajax` requests.

### Control via the Web

The web interface has buttons, input fields and drop-down lists that let you send commands and update settings.

When you click a button or change a value on a web page, your browser sends a request back to the Samovar web server.

```c++
// From WebServer.ino
server.on("/command", HTTP_POST, [](AsyncWebServerRequest *request) {
  web_command(request); // Handle the command from the web request
});
server.on("/program", HTTP_POST, [](AsyncWebServerRequest *request) {
  web_program(request); // Handle program updates
});
server.on("/save", HTTP_POST, [](AsyncWebServerRequest *request) {
  handleSave(request); // Handle saving configuration settings
});
// ... other command handlers ...
```

These lines tell the web server what to do when it receives POST requests to `/command`, `/save` or `/program`. For example, clicking the "Start" button on a web page sends a POST request to `/command` with the body `start=1` (this is done by the `sendCommandRequest` function in `app.js`). The `web_command` function then checks the request for parameters such as `start=1` and converts them into an action that Samovar must perform.

In our case, clicking the "Start" button on the web page runs the `web_command` function, which puts the start command of the current mode into the queue (`queue_samovar_command(mode_start_command(Samovar_Mode))`; for rectification it is `SAMOVAR_START`), telling the main Samovar logic to begin the process.

## How It Works Under the Hood

Let's trace how a user action, such as starting a process, passes through the Samovar system.

When you interact with either interface, the basic idea is the same:
1.  **Input detection:** The interface (the LCD code or the web server code) detects the user's action (an encoder click, a button press, a web request).
2.  **Translate into a command:** The interface code translates this physical action or web request into a specific command or parameter change understood by the main Samovar control logic.
3.  **Command execution:** The main Samovar logic receives the command and performs the corresponding action (for example, turns on the heater, starts a pump, changes a setting).
4.  **Update state:** The internal state and data of Samovar are updated based on the action.
5.  **Interface update:** Samovar informs both the LCD and the web interface about the new state and data, so that they can show the user what is happening.

Here is a simplified sequence of actions:

```mermaid
sequenceDiagram
    User->>LCD/Web: Performs Action (e.g., Click «Start»)
    LCD/Web->>Interface Handler: Detects Action
    Interface Handler->>Samovar Logic: Sends Command (e.g., SAMOVAR_START)
    Samovar Logic->>Samovar Logic: Executes Process (e.g., turns on heater)
    Samovar Logic->>Samovar Logic: Updates Internal State/Data
    Samovar Logic->>Interface Handler: Notifies of State/Data Change
    Interface Handler->>LCD/Web: Updates Display (New Status/Data)
    LCD/Web->>User: Shows Updated Information
    Note over LCD/Web: This cycle repeats continuously<br/>for monitoring and control.
```
The `Interface Handler` block represents the code responsible for managing the LCD menu (`Menu.ino`) and the web server (`WebServer.ino`). These handlers interact with `Samovar Logic`, which contains the core state machine and the control algorithms of the brewing/distillation process (covered in chapters such as [Process Program Execution](02_process_program_execution_.md) and [System State & Mode Management](03_system_state___mode_management_.md)).

## Key Code Points for Working with the Interfaces

The `Menu.ino` file is intended for working with the LCD and the encoder. It defines the screens and lines, and also defines the functions that are called when the encoder is used while a particular line is selected.

For example, this function is associated with the "Start" line on one of the main screens:

```c++
// From the Menu.ino file (simplified)
void menu_samovar_start() {
  // The function works only in rectification mode and with the power on
  if (Samovar_Mode != SAMOVAR_RECTIFICATION_MODE || !PowerOn) return;
  String Str;

  // Logic for determining the next program step
  if (startval == SAMOVAR_STARTVAL_RECT_DONE) startval = SAMOVAR_STARTVAL_RECT_STOPPING;
  else if (ProgramNum >= ProgramLen - 1 && startval != SAMOVAR_STARTVAL_IDLE)
    startval = SAMOVAR_STARTVAL_RECT_DONE;

  // Based on the current state (startval), decide what to do
  if (startval == SAMOVAR_STARTVAL_IDLE) {
    // Initial start: check the program, create the log file, open a session
    Str = "Prg No 1";
    // ... if validate_rect_program_startable() or create_data() fails, the start is cancelled ...
    session_begin(sessionDescription);
    run_program(0); // Execute the first program line
    ProgramNum = 0;
    startval = SAMOVAR_STARTVAL_RECT_RUNNING;
  } else if (startval == SAMOVAR_STARTVAL_RECT_RUNNING) {
    // Move to the next program line
    ProgramNum++;
    Str = "Prg No " + (String)(ProgramNum + 1);
    run_program(ProgramNum);
  } else if (startval == SAMOVAR_STARTVAL_RECT_DONE) {
    // The program is complete
    Str = "Prg finish";
    // ... run_program(PROGRAM_END) or "self-run" until automatic power-off ...
  } else {
    // Stop the process
    Str = "Stoped";
    run_program(PROGRAM_END); // Special "end of program" number for stopping
    reset_sensor_counter();
  }
  // Update the text shown on the LCD
  copyStringSafe(startval_text_val, Str);
  // Update the LCD
  reset_focus();
  menu_update();
}
```

This function is called when the user navigates to the "Start" option on the LCD with the encoder and presses the button (it is also called by a separate start button, if one is connected). It checks the current state (`startval`, `ProgramNum`) and decides whether to start, continue or stop the program by calling `run_program()` (a function described in detail in [Process Program Execution](02_process_program_execution_.md)). If the program is complete and `PROGRAM_DONE_AUTO_POWEROFF_MIN` is greater than zero, the withdrawal stops but the heating stays on ("self-run") until automatic power-off or the next press. Finally, it updates the text shown on the LCD and refreshes the screen.

The `WebServer.ino` file handles all web interactions. It sets up the endpoints (URLs) that the browser can interact with.

```c++
// From the WebServer.ino file (simplified)
void web_command(AsyncWebServerRequest *request) {
  // The request must contain exactly one POST parameter with an allowed command name
  if (!get_web_command_action(request, action, actionParam)) {
    send_web_command_response(request, 400, "BAD_REQUEST");
    return;
  }
  // ... checking the parameter value (numbers, 0/1) ...

  // Protection against accidental double clicks: the same command repeated within 1.5 s is ignored
  if (commandKey == last_command_key && millis() - last_command_time < 1500) {
    send_web_command_response(request, 429, "IGNORED");
    return;
  }

  if (action == "start") {
    // Starting is possible only with the power on
    if (!PowerOn) {
      send_web_command_response(request, 409, "POWER_OFF");
      return;
    }
    // The start command depends on the mode (for rectification it is SAMOVAR_START)
    if (!queue_samovar_command(mode_start_command(Samovar_Mode))) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  } else if (action == "power") {
    // power=1 -- turn on (each mode has its own power-on command), power=0 -- turn off
    SamovarCommands command = SAMOVAR_NONE;
    if (boolValue) {
      if (!PowerOn) command = mode_power_on_command(Samovar_Mode);
    } else {
      command = SAMOVAR_POWER_OFF;
    }
    if (command != SAMOVAR_NONE && !queue_samovar_command(command)) {
      send_web_command_response(request, 503, "BUSY");
      return;
    }
  }
  // ... handlers for other commands such as reset, calibration, pause, etc. ...
  send_web_command_response(request, 200, "OK"); // Send a simple response to the browser
}
```

This `web_command` function receives a web request. It checks the parameter in the body of the POST request (for example, `start=1`). Based on the parameter found, it puts a command (a `SamovarCommandMsg` message) into the `samovar_command_queue` queue via `queue_samovar_command(...)`. The main `loop()` in `Samovar.ino` takes commands from the queue with the `receive_samovar_command()` function and performs the corresponding action. The server answers the browser with a short code word (`OK`, `BUSY`, `IGNORED`, `POWER_OFF`, etc.), and the page itself picks the user-friendly text for that code. This is a common pattern for interaction between different tasks or parts of code in embedded systems.

The web interface also allows saving configuration settings, which is handled by the `handleSave` function (it is not shown in full here, but it reads the parameters from the POST request, checks them and updates the `SamSetup` structure), and editing the program, which is handled by `web_program`.

## Conclusion

In this chapter we looked at two ways of interacting with Samovar: the physical LCD with its controls, and the flexible web interface. Both interfaces let you monitor the system state and sensor data and, most importantly, send commands to control the brewing or distillation process, for example, to start a program. We looked at simplified code examples showing how sensor data is displayed, how user input (from encoder presses or web requests) is recognized and converted into commands for the main Samovar logic.

Understanding these interfaces is the first step toward controlling Samovar. In the next chapter we will look in more detail at how Samovar executes the programs you select or define.
