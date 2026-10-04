# Technical Documentation: Samovar

Samovar is an automated system designed for **automating distillation, rectification, beer column (BK and NBK), beer brewing, cheese making and sous vide processes**.
It *monitors* various sensors (such as temperature and pressure),
*controls* equipment (heaters, pumps, valves) and follows predefined
*process programs* to automate tasks such as rectification or brewing beer.
Users *interact* with the system through a web interface or an LCD
(as well as through the mobile apps and the samovar-tool.ru website, connected via Blynk),
and the system includes important *safety monitoring* and *external communication* features.
Settings and programs are *saved* for persistent configuration.


## Visual Overview

```mermaid
flowchart TD
    A0["System State and Mode Management"]
    A1["Sensor Data Acquisition"]
    A2["Hardware Control (Actuators)"]
    A3["Process Program Execution"]
    A4["User Interaction (Web and LCD)"]
    A5["Configuration Persistence"]
    A6["Network and External Communication"]
    A7["Safety Monitoring and Alarms"]
    A1 -- "Reports status" --> A0
    A0 -- "Controls actuators" --> A2
    A0 -- "Manages programs" --> A3
    A0 -- "Provides status to the user interface" --> A4
    A4 -- "Sends commands from the user" --> A0
    A5 -- "Provides initial configuration" --> A0
    A1 -- "Provides sensor data to the user interface" --> A4
    A4 -- "Updates configuration" --> A5
    A6 -- "Serves the web user interface" --> A4
    A7 -- "Sends alarms externally" --> A6
    A7 -- "Triggers safety actions" --> A0
    A7 -- "Notifies the user interface about alarms" --> A4
    A3 -- "Controls actuators according to the program" --> A2
    A5 -- "Defines programs" --> A3
    A5 -- "Provides actuator settings" --> A2
    A5 -- "Provides safety settings" --> A7
    A1 -- "Informs the program logic" --> A3
    A2 -- "Reports actuator status to the user interface" --> A4
    A7 -- "Interrupts programs" --> A3
    A1 -- "Sends sensor data to the outside" --> A6
    A4 -- "Requests sensor actions" --> A1
    A5 -- "Affects user interface presentation" --> A4
    A5 -- "Provides sensor settings" --> A1
    A1 -- "Provides data for safety" --> A7
```

## Chapters

1. [User Interaction (Web and LCD)
](01_user_interaction__web___lcd__.md)
2. [Process Program Execution
](02_process_program_execution_.md)
3. [System State and Mode Management
](03_system_state___mode_management_.md)
4. [Sensor Data Acquisition
](04_sensor_data_acquisition_.md)
5. [Hardware Control (Actuators)
](05_hardware_control__actuators__.md)
6. [Safety Monitoring and Alarms
](06_safety_monitoring___alarms_.md)
7. [Configuration Persistence
](07_configuration_persistence_.md)
8. [Network and External Communication
](08_network___external_communication_.md)
