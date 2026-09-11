# Samovar Project

[Русская версия](README.md)

## Description

Samovar is an ESP32-based automated control system for a still, brewery, and cheese-making
setup (firmware version 7.00). The device measures temperatures (vapor, column, boiler, outlet
water, and TCA) and pressure, and controls heating through a power regulator, relays, valves,
a water pump, a stepper-driven peristaltic pump for product collection, and a servo for routing
the product into separate containers. A process is described by a sequence of program rows that
run one after another, while Lua scripts can extend the logic. The system can be controlled and
monitored from the local display, the built-in web interface, Android and iOS mobile apps, and
the control page at samovar-tool.ru. If any parameter exceeds its allowed limit, the device stops
the process and sends an alarm.

## Operating Modes

- **Rectification** — program-controlled collection of heads, hearts, and tails, plus an impurity
  breakthrough detector. It analyzes the pressure-corrected temperature trend, automatically
  adapts its threshold to column noise, can reduce the collection rate when temperature rises,
  pauses collection on a critical rise, and resumes it automatically. During heads collection it
  only monitors the process, while the interface shows why it is waiting (grace period, vapor
  stabilization, or history collection). A servo can route the product into separate containers.
- **Distillation** — controlled by boiler temperature or by changes in alcohol content in the
  boiler or vapor, with a forecast for the end of the current row and the complete process.
- **BK (wash column)** — cooling-water control based on a vapor-temperature setpoint, either
  automatically or manually, with sensor-based boil confirmation.
- **NBK (continuous wash column)** — warm-up, setup, optimization, and operation; wash feed is
  controlled automatically, and the discovered parameters can be accepted as optimal.
- **Brewing** — malt addition, temperature rests, boiling, cooling, fermentation, brewing
  schedules, agitator and water-pump control, and manual pause.
- **Sous vide** — program-controlled water temperature maintenance.
- **Cheese making** — heating, holding, cooling, acidity monitoring with a pH sensor, agitator,
  and brine drain valve; includes dedicated program-row types such as culture, enzyme, starter,
  cutting, draining, and others.
- **Lua** — a mode in which the entire process is controlled by a user script.

## Key Features

- A process program for every mode: a sequence of rows configured in the web interface and
  executed one after another. See the documentation and forum for details.
- Smooth power control through external regulators, including the new Kvic version, RMVK, and
  SEM, with automatic boiling-point correction for atmospheric pressure.
- Precise product collection: the rate in liters per hour is maintained automatically.
- I2CStepper expansion board over I2C: stepper-driven agitator and dosing pump, priming,
  dispensing a specified volume, steps-per-milliliter calibration, relays, and an external sensor.
  It can be controlled from the web interface, process programs, Lua, mobile apps, and the website.
- Built-in Lua interpreter for extending the logic, with access to sensors, heating, pumps,
  agitator, and relays.
- Safety monitoring for temperature, pressure, water, power-regulator errors, and sensor errors;
  an emergency button; and automatic process shutdown with notifications on the display, in the
  web interface, in the apps, and on the website.
- State snapshots: after an emergency reboot, the firmware restores the program and, if the
  process is restarted within 30 minutes, continues the same log session.
- A web interface with real-time charts, a process diagram, and a file manager, plus a local LCD
  with an encoder.
- Process logs and messages are stored in the cloud by the samovar-tool.ru server and are
  available on the website and in the apps; charts use the history of the entire session.
- Android and iOS mobile apps and a website control page (see below), with push notifications
  for alarms.
- A configurator for Windows, macOS, and Linux: build, flashing over USB or Wi-Fi, device file
  editor, and configuration report.
- Support for ESP32 (DEVKIT and LILYGO) and ESP32-S3.

## Requirements

### Hardware

- ESP32 (DEVKIT or LILYGO) or ESP32-S3
- Five DS18B20 temperature sensors
- MPX5010D or XGZ pressure sensor and BMP180 atmospheric-pressure sensor
- Power regulator such as Kvic, RMVK, or SEM
- LCD
- Rotary encoder with a button
- Water-supply pump
- Stepper motor
- Peristaltic pump
- Valves
- Servo
- Power supply
- Optional: I2CStepper board with an agitator and dosing pump, external ADS1115 ADC and
  PH-4502C pH sensor for cheese making, water-flow sensor, and emergency button

Cheese mode uses shared connections:

- `#define USE_ADS1115 0x48` automatically moves the pH sensor to ADS1115 input AIN0 at
  address `0x48`. There is no separate channel setting, and `LUA_PIN` is not used for pH.
  If the ADS1115 is not found, Cheese mode startup and pH calibration are blocked while all
  other modes remain operational.
- Without `USE_ADS1115`, the previous connection remains: `LUA_PIN` is the PH-4502C input.
  Connect either a PH-4502C for Cheese mode or an MPX5010DP for other modes, but never both
  sensors at the same time.
- Relay 4 controls the brine drain valve. Connect either the cheese-making valve or the boost
  heating element used by other modes, but never both devices at the same time.

These assignments apply only in Cheese mode. In all other modes, Lua, the MPX5010DP, and the
boost heating element work as before.

Wiring diagram

![Wiring diagram](https://github.com/LKosoj/Samovar/blob/master/Fritzing%20scheme/Samovar_bb.png)

### ESP32 Pin Limitations

- GPIO34–39 are input-only and have no internal pull-ups. The emergency button (GPIO35 on
  DEVKIT), LILYGO encoder (GPIO35/39/36), and flow sensor (GPIO36 on DEVKIT) require an external
  10 kOhm resistor to 3.3 V; otherwise false triggers can cause an alarm immediately after boot.
- GPIO36/39 can produce false pulses while ADC and Wi-Fi are active. Route flow-sensor wires
  separately from the heating element's power cables.
- GPIO15 and other strapping pins are pulled to predefined levels during reset. A relay on such
  a pin (`RELE_CHANNEL2`, agitator) may briefly turn on at every boot. Use an active-low relay or
  move it to a regular pin; polarity is configured with the `rele1`–`rele4` fields in `setup.htm`.
- On ESP32-S3, the menu button on GPIO47 requires an external pull-up.
- The I2C bus used by the display, stepper expansion board, and dosing pump needs 4.7–10 kOhm
  pull-ups. Wire length and bus frequency can cause display update failures, which is why the
  firmware periodically reinitializes the display.

### Software

- Windows 10/11 x64: run `flash_windows.bat`. It checks or installs Python with Tkinter and
  PlatformIO, then opens the Samovar configurator.
- macOS and Linux: run `./flash_macos_linux.sh`. It checks or installs Python with Tkinter and
  PlatformIO, then opens the same configurator.
- Manual builds on any supported system require PlatformIO Core. PlatformIO automatically
  installs the ESP32 compiler, platform, and project dependencies from `platformio.ini`; there
  is no need to assemble a separate library list.

## Installation

### Windows: Configurator

1. Download or clone the repository and run `flash_windows.bat` from its root.
2. Select the board and enter the settings in the window that opens. Local settings, including
   the initial Wi-Fi credentials, are stored in `user_config_override.h`.
3. Click **Flash**: PlatformIO compiles the firmware and uploads it to the ESP32.
4. For the first installation, click **Upload LittleFS** separately to install the web interface.
   This operation requires confirmation because it replaces files on the device.
5. Later updates can be installed without a cable. Click **Refresh** next to **Port or address**.
   In addition to COM ports, the list includes Samovar devices found on the network through mDNS
   (discovery takes about three seconds) and the address reported by the device after clicking
   **Get IP** in the serial monitor. You can also enter an address manually, such as
   `192.168.1.37` or `samovar.local`. Select the network device instead of a COM port and click
   the same **Flash** or **Upload LittleFS** button; PlatformIO transfers the image over Wi-Fi.
   The device firmware must have **Allow updates over Wi-Fi** enabled in the **Network** section,
   the computer and Samovar must be on the same network, and the firewall must allow incoming
   connections to `python.exe`, because the device connects back to the computer during image
   transfer. Full flash erase, serial monitoring, and reboot through esptool work only over USB.

The **File Editor** button opens device files directly in the configurator, with line numbers,
Lua, JS, CSS, HTML, and JSON highlighting, matching-bracket highlighting, and quick checks for
balanced brackets and `function … end` blocks, unclosed strings and comments, and valid JSON.
Errors are shown in the status line with a line number. For completion suggestions and full
syntax checking, **Web editor (/edit)** opens the same file in the device's Ace editor. This
button is unavailable for compressed `.gz` files; edit them in the configurator, which handles
decompression and recompression automatically.

Every field and log view has a right-click context menu for cut, copy, paste, and select all.
Ctrl+C, Ctrl+V, Ctrl+X, and Ctrl+A also work with the Russian keyboard layout active.

`flash_windows.bat` only prepares the tools and starts `tools/samovar_configurator.py`;
PlatformIO performs compilation and upload. The configurator changes user settings but does not
replace the compiler: PlatformIO always builds the firmware as a separate step.

### Arduino IDE

Arduino IDE remains a separately supported build and upload method. Open the root `Samovar.ino`,
select your ESP32 board and port, then build and upload the firmware. For the first installation,
upload LittleFS separately from the prepared `data/` directory. The configurator and PlatformIO
are not required for this method.

### macOS and Linux: Configurator

1. Download or clone the repository. On macOS, placing the project folder directly in your home
   folder is recommended instead of using the protected `Downloads` folder.
2. Open Terminal in the project folder and run:

   ```sh
   chmod +x flash_macos_linux.sh
   ./flash_macos_linux.sh
   ```

3. Configure and flash the device in the window just as on Windows.

If macOS reports `getcwd: cannot access parent directories: Operation not permitted` or refuses
to open `flash_macos_linux.sh`, the shell cannot access the current folder and the script has not
started yet. Move the project folder in Finder from `Downloads` to your home folder and run it
there. Alternatively, open **System Settings** → **Privacy & Security** → **Files and Folders**,
allow Terminal to access the Downloads folder, and restart Terminal completely.

Homebrew is required to install Python and Tkinter automatically on macOS. On Linux, `apt`,
`dnf`, and `pacman` are supported; installing system packages may request your `sudo` password
(that is, permission to run a command as an administrator).

### Manual PlatformIO Build

1. Install PlatformIO Core and clone the repository.
2. Set user parameters in `user_config_override.h`, using `user_config_override.example.h` as
   the starting point.
3. Build and upload the required environment: `pio run -e Samovar -t upload` for ESP32
   DEVKIT/LILYGO or `pio run -e Samovar_s3 -t upload` for ESP32-S3.
4. For the first web-interface installation, run `pio run -e <environment> -t uploadfs` for the
   same environment.

## Project Structure

- `Samovar.ino` — main project file
- `Samovar.h` — main definitions
- `logic.h` — operating logic
- `WebServer.ino` — web server
- `Blynk.ino` — communication with samovar-tool.ru for data, commands, and process logs
- `SamovarMqtt.h` — optional MQTT telemetry publishing
- `I2CStepper.h`, `i2c_stepper_params.h` — expansion board: agitator and dosing pump over I2C
- `impurity_detector.h` — impurity breakthrough detector
- `operation_store.h`, `crash_handler.h` — state snapshots and recovery after reboot
- `tools/samovar_configurator.py` — configurator started by `flash_windows.bat` and
  `flash_macos_linux.sh`
- `beer.h` — brewing mode
- `cheese.h` — cheese-making mode
- `distiller.h` — distillation mode
- `BK.h` — wash-column mode
- `nbk.h` — continuous wash-column mode
- `lua.h` — Lua interpreter

### Web Interface

The dark copper-themed interface contains a process diagram with live readings, the current
program row, charts, mode pages, settings, and program and file editors.

Operational pages are served as static gzip files and receive their initial data in a single
`/ui-bootstrap` request before the first poll. The only exception is `setup.htm`, which remains
an uncompressed template page.

### Device File Editor

The `/edit` operations that modify the file system (`DELETE`, creation through `PUT`, and each
upload chunk) try to acquire shared file access without waiting. If the logger is using the file
system at that moment, the server responds with `503 BUSY`; otherwise, the operation is allowed
even while a process is running. Viewing and downloading files remain available at all times.

### Server Connection, Process Logs, and Sessions

The device's only network channel is the samovar-tool.ru server over TLS. It carries live
readings and commands for the apps and website, along with process logs, session starts, and
messages. The server stores them in its database, which supplies the website log page and the
charts in the apps. The logging interval is fixed at `LOG_PERIOD_S = 4` seconds and cannot be
configured in the web interface. When no process is active, readings are still sent every five
seconds so the apps can show temperatures.

The configurator can optionally enable a separate, condensed telemetry line sent to any MQTT
broker. The server, port, username, password, and topic are stored only in the local
`user_config_override.h`; the device web interface does not store them. MQTT operates without
TLS, publishes at QoS 1, and retains the last value at the broker. The interval is four seconds
during a process and five seconds while idle.

If an emergency reboot interrupts a process and the same program is started again within
30 minutes, the firmware does not open a new session. It resumes the previous one, so the server
appends to the existing log record instead of creating another.

## Mobile Apps

The Android and iOS apps have the same structure and communicate through the samovar-tool.ru
server. On first launch, they register or use an existing account with an email address and
password; the device token in settings is the same token configured in the firmware.

The apps contain five screens:

- **Main** — connection state, process diagram with live temperatures, key readings, current
  program row and progress, heating, Next, pause, and reset controls, and mode-specific data such
  as alcohol content, impurity detector, forecasts, mash feed, and pH.
- **Program** — all program rows with field descriptions; the active row is highlighted.
- **Control** — voltage, collection rate, hearts temperature lock, I2CStepper agitator and pump
  settings, start, calibration, and relays, Lua row execution with the device response, and
  system information.
- **Charts** — current-session history from the server database plus live points, series groups,
  and ranges from one minute to the entire session.
- **Settings** — server address, token, account, and push notifications.

Data refreshes every three seconds while the app is visible. Alarms arrive as push notifications
with a loud sound and appear over the lock screen. Tablet layouts use two columns.

## Control Through samovar-tool.ru

The website provides https://www.samovar-tool.ru/control/ with the same five screens as the
mobile apps (Main, Program, Control, Charts, and Messages), without installing anything on a
phone or computer. Requirements:

- You must be signed in to the website.
- Your user profile must contain the device token, the same one used by the firmware and apps.
  Without a token, the page shows instructions instead of the interface.

The website contacts the server on the user's behalf; the token is not passed to the browser.
Commands are sent only while the device is online, and controls are disabled when data is stale.
The log page at https://www.samovar-tool.ru/logi/ provides session lists, charts, messages, and
CSV export alongside the control page.

## Documentation

Full documentation is available at https://www.samovar-tool.ru/

[Technical documentation](/doc/tutorial.md)

## Support

Samovar is a non-commercial project. Discussion and support are available on the forum:
https://forum.homedistiller.ru/index.php?topic=367128.0

## Demonstration

Examples of the system in operation: https://www.samovar-tool.ru/2021/03/21/o-rabote-samovara/

## Comparison with Other Projects

### Rectification and Distillation

The following comparison places Samovar alongside three categories of commercial rectification
and distillation systems:

1. **Basic digital controllers**, such as common boxed PID controllers and Still Spirits units.
2. **Advanced hobby controllers**, such as HomeDistiller systems and custom builds from known
   equipment manufacturers.
3. **Industrial or laboratory PLC systems** (programmable logic controllers).

---

### Feature Comparison for Distillation and Rectification

| Feature | Samovar (DIY) | Basic controller | Advanced hobby controller | Industrial PLC |
| :--- | :--- | :--- | :--- | :--- |
| **1. Core control logic** | **Dynamic process control.** Logic depends on the stage, temperature, pressure, time, and **events**. | **Static setpoint control.** Usually a thermostat that maintains a selected temperature or power level. | **Step-by-step programming.** Runs recipes such as “heat to 80 °C → hold for 20 min → heat to 90 °C.” | **Fully programmable logic.** Any relationship between parameters can be implemented, including highly complex ones. |
| **2. Power control** | **Smooth and precise.** PID power control through external regulators such as triacs and SSRs. | **Discrete on/off.** A simple relay causes temperature swings due to process inertia. | **Smooth.** Usually PID control through phase-angle control for an SSR. | **Smooth and high-precision.** Closed-loop power control. |
| **3. Product collection control** | **A core feature.** **High-precision control of a pump stepper motor** or valve servo. The collection rate is specified in ml/hour and maintained automatically. | **None.** The operator controls collection manually. | **Usually absent or optional.** May control a simple open/closed valve, but rarely the collection rate. | **Full control.** Any type of valve or pump can be controlled with flow feedback. |
| **4. Process adaptability** | **Very high.** **Automatic boiling-point correction for pressure**, **automatic collection-rate reduction** as tails approach, and **complete logic customization through Lua**. | **None.** Responds only to deviation from a temperature setpoint. | **Low.** May switch recipe steps on an event, such as reaching a temperature, but cannot dynamically change the current step's parameters. | **Absolute.** Logic is written for a specific installation and process. |
| **5. Interface and monitoring** | **Modern.** Web interface with real-time charts, remote access, and a local LCD. | **Primitive.** Digital display and a few buttons. | **Functional but utilitarian.** Often a text LCD, optionally with data output to a PC over RS-485 or USB. | **Industrial.** SCADA systems with full process visualization, archiving, and reports. |
| **6. Safety** | **Multi-level and configurable.** Monitors temperature, pressure, water, and power errors. The user configures alarm logic. | **Basic.** Usually only overheat protection. | **Good.** Multiple sensors and watchdog timers. | **Maximum.** Redundant systems, certified components, and hardware protection. |
| **7. Integrations (IoT)** | **Built in.** Cloud logs, Android and iOS apps, and control through samovar-tool.ru. | **None.** | **Rare.** Usually proprietary protocols or Modbus for PC communication. | **Standard.** OPC UA, Modbus, Profinet, and other industrial protocols. |
| **8. Approximate cost** | **Low** (about $50–100 for electronics). | **Low** (about $50–150). | **Medium/high** (about $300–800). | **Very high** (thousands of dollars). |

---

### Samovar's Position Among Distillation Projects

1. **Samovar is far ahead of basic controllers.** It does not merely replace them; it offers a
   fundamentally different level of automation. Where a basic controller is a “smart outlet,”
   Samovar is the installation's “brain.”

2. **Samovar is a direct and strong competitor to advanced hobby controllers.** It matches their
   key functions, including PID power control and step-by-step programs, and **surpasses them in
   two areas that are critical for rectification:**

   - **Integrated product collection control:** commercial systems usually require a separate,
     expensive device for collection control. Samovar makes it a core feature.
   - **Logic flexibility:** commercial hobby controllers do not offer Lua-level logic
     programming. This capability moves Samovar into the semi-professional class by enabling
     algorithms that were previously available only on industrial PLCs.

3. **Samovar borrows concepts from industrial PLC systems.** Fully programmable logic that
   reacts to many asynchronous events is fundamental to a PLC. Samovar makes this approach
   available to hobbyists on inexpensive hardware. It naturally falls short of industrial
   systems in reliability, electrical noise immunity, and certification, but its **functional
   logic** aims at that higher tier.

**Conclusion:**

Samovar is more than a DIY gadget. For distillation and rectification, it is **a system whose
functionality leaves other DIY solutions far behind and competes directly with expensive,
advanced controllers while offering greater flexibility and customization.**

Its main tradeoff is not functionality but **convenience versus flexibility**. A commercial
device includes a warranty, support, and a ready-to-use product. Samovar offers almost unlimited
automation possibilities in exchange for the need to assemble, configure, and maintain the
system yourself.

### Feature Comparison for Brewing

The following comparison places Samovar alongside several popular open-source and DIY brewing
automation projects representing different approaches:

1. **BrewPi / BrewPiLess:** historically one of the best-known projects for beer **fermentation
   control**.
2. **CraftBeerPi (v3/v4):** a popular modular **brewing** controller for mashing and boiling that
   runs on Raspberry Pi.
3. **ArdBir / ESPurno:** simpler Arduino/ESP controllers focused mainly on brewing.

---

### Comparison by Key Criteria

| Feature | Samovar | BrewPi / BrewPiLess | CraftBeerPi 4 | Typical DIY projects (ArdBir, etc.) |
| :--- | :--- | :--- | :--- | :--- |
| **1. Primary purpose** | **Universal.** Distillation, rectification, brewing, and NBK. | **Specialized.** Primarily precise fermentation-temperature control. | **Specialized.** Full brewing cycle, including mashing and boiling. | **Specialized.** Usually brewing and mashing only. |
| **2. Automation flexibility** | **Very high.** Step-by-step programs plus **Lua scripts** for any custom logic. | **Medium.** Temperature profiles over time. | **High.** Step-by-step recipes and a flexible plugin system. | **Low.** Fixed logic with, at most, configurable temperature rests. |
| **3. Equipment control** | **Precise and comprehensive.** Stepper motor for accurate collection, servo for changing containers, and smooth power adjustment. | **Precise.** PID heating and cooling control for temperature maintenance. | **Modular.** Relay control for valves, pumps, and agitator, plus PWM power control. | **Basic.** Mainly on/off relay control. |
| **4. Interface and monitoring** | **Comprehensive.** Web interface with charts and a file manager, plus a local LCD and encoder. | **Minimal.** Web interface for profile setup and chart viewing. | **Advanced.** Modern web interface with a fully customizable dashboard. | **Basic.** Usually only an LCD and rarely a simple web interface. |
| **5. Integrations and IoT** | **Built in.** Cloud logs, Android and iOS apps, and control through samovar-tool.ru. | **Limited.** iSpindel integration, with MQTT in some forks. | **Broad through plugins.** MQTT, iSpindel, notifications, and more. | **Almost none.** |
| **6. Hardware platform** | **ESP32.** Low cost and high performance for real-time tasks. | **ESP8266/ESP32.** | **Raspberry Pi.** A full computer with higher cost and power use. | **Arduino/ESP8266.** |

---

### Conclusion and Positioning

Samovar occupies **a unique position at the intersection of professional flexibility and DIY
accessibility**, clearly setting it apart from alternatives.

**1. Samovar is a Swiss Army knife, while its competitors are specialized tools.**
Most projects such as CraftBeerPi and BrewPi solve one problem: brewing. They solve it well, but
their logic and features do not fit rectification. Samovar was designed from the beginning as a
universal platform capable of controlling fundamentally different processes. This is its main
and strongest distinction.

**2. Samovar's automation level is substantially higher.**
While other projects offer parameter settings such as temperature and time or step-by-step
recipes, Samovar also provides **full logic programming through Lua**. Experienced users can
implement complex algorithms that other systems cannot support without source-code changes.

**3. All in one on an affordable platform.**
Samovar provides a web server, charts, complex logic, and many integrations—features that often
require a more powerful and expensive platform such as Raspberry Pi in competing systems. It
still preserves the advantages of an ESP32 microcontroller: reliability and real-time operation.

**4. Samovar is more than a controller.**
It is a universal platform capable of controlling many processes. Experienced users can build
complex algorithms that other systems cannot support without source-code changes.

**Final conclusion:**

Samovar is not “just another controller.” It is **a high-level process controller** for
enthusiasts who want maximum control over brewing, rectification, distillation, wash-column,
continuous wash-column, and related processes.
