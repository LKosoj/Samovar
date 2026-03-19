"""Mock web server for Samovar UI testing.

Serves static files from data/ and provides mock /ajax endpoint
with realistic JSON responses, simulating ESP32 behavior.
"""

import json
import os
import signal
import sys
from pathlib import Path
from aiohttp import web

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"

# Template variable substitutions (simulate ESP32 template processor)
TEMPLATE_VARS = {
    "%SteamColor%": "#e74c3c",
    "%PipeColor%": "#3498db",
    "%WaterColor%": "#2ecc71",
    "%TankColor%": "#f39c12",
    "%ACPColor%": "#9b59b6",
    "%SteamHide%": "false",
    "%PipeHide%": "false",
    "%WaterHide%": "false",
    "%TankHide%": "false",
    "%PressureHide%": "false",
    "%ProgNumHide%": "true",
    "%WProgram%": "H;450;0.1;1;0;45\nB;450;1;1;0;45\n",
    "%Descr%": "",
    "%videourl%": "",
    "%showvideo%": "none",
    "%v%": "4.5.0-test",
    "%PWM_LV%": "50",
    "%PWM_V%": "0",
    "%pwr_unit%": "V",
    "%pwr_unit_v_only%": "block",
    "%I2CPumpTab%": "none",
    "%btn_list%": "",
    "%ColDiam%": "2.0",
    "%ColHeight%": "0.50",
    "%PackDens%": "80",
    "%HeaterMaxPower%": "3500",
}

SETUP_TEMPLATE_VARS = {
    "%DeltaSteamTemp%": "0.10",
    "%DeltaPipeTemp%": "0.10",
    "%DeltaWaterTemp%": "0.10",
    "%DeltaTankTemp%": "0.10",
    "%DeltaACPTemp%": "0.10",
    "%SetSteamTemp%": "78.00",
    "%SetPipeTemp%": "0.00",
    "%SetWaterTemp%": "0.00",
    "%SetTankTemp%": "0.00",
    "%SetACPTemp%": "0.00",
    "%StepperStepMl%": "250",
    "%StepperStepMlI2C%": "350",
    "%WProgram%": "H;450;0.1;1;0;45\nB;450;1;1;0;45\n",
    "%Kp%": "150.000",
    "%Ki%": "1.400",
    "%Kd%": "1.400",
    "%StbVoltage%": "100",
    "%SteamDelay%": "0",
    "%PipeDelay%": "0",
    "%WaterDelay%": "0",
    "%TankDelay%": "0",
    "%ACPDelay%": "0",
    "%TimeZone%": "3",
    "%LogPeriod%": "3",
    "%HeaterR%": "10.000",
    "%videourl%": "",
    "%blynkauth%": "",
    "%tgtoken%": "",
    "%tgchatid%": "",
    "%BVolt%": "230",
    "%DistTimeF%": "16",
    "%DistTemp%": "0.00",
    "%MaxPressureValue%": "0",
    "%NbkIn%": "0",
    "%NbkDelta%": "0",
    "%NbkDM%": "0",
    "%NbkDP%": "0",
    "%NbkSteamT%": "0",
    "%NbkOwPress%": "0",
    "%Checked%": "checked='true'",
    "%FLChecked%": "checked='true'",
    "%UASChecked%": "",
    "%UASHeadsChecked%": "",
    "%CPBuzz%": "",
    "%CUBuzz%": "",
    "%CUBBuzz%": "",
    "%UseWS%": "checked='true'",
    "%UseST%": "checked='true'",
    "%ChckPwr%": "",
    "%autospeed%": "0",
    "%SteamColor%": "#e74c3c",
    "%PipeColor%": "#3498db",
    "%WaterColor%": "#2ecc71",
    "%TankColor%": "#f39c12",
    "%ACPColor%": "#9b59b6",
    "%RECT%": "selected",
    "%DIST%": "",
    "%BEER%": "",
    "%BK%": "",
    "%NBK%": "",
    "%SUVID%": "",
    "%LUA_MODE%": "",
    "%RAL%": "selected",
    "%RAH%": "",
    "%RBL%": "selected",
    "%RBH%": "",
    "%RCL%": "selected",
    "%RCH%": "",
    "%RDL%": "selected",
    "%RDH%": "",
    "%SteamAddr%": "<option>-</option>",
    "%PipeAddr%": "<option>-</option>",
    "%WaterAddr%": "<option>-</option>",
    "%TankAddr%": "<option>-</option>",
    "%ACPAddr%": "<option>-</option>",
    "%ColDiam%": "2.0",
    "%ColDiam_1.5%": "",
    "%ColDiam_2.0%": "selected",
    "%ColDiam_3.0%": "",
    "%ColHeight%": "0.50",
    "%ColHeight_0.50%": "selected",
    "%ColHeight_0.75%": "",
    "%ColHeight_1.00%": "",
    "%ColHeight_1.25%": "",
    "%ColHeight_1.50%": "",
    "%ColHeight_1.75%": "",
    "%ColHeight_2.00%": "",
    "%ColHeight_2.25%": "",
    "%ColHeight_2.50%": "",
    "%PackDens%": "80",
    "%I2CPumpTab%": "none",
}

CALIBRATE_TEMPLATE_VARS = {
    "%StepperStep%": "1000",
    "%StepperStepMl%": "25000",
    "%StepperStepMlI2C%": "35000",
    "%I2CPumpTab%": "none",
}

MOCK_AJAX = {
    "bme_temp": 25.5,
    "bme_pressure": 740.2,
    "start_pressure": 740.0,
    "crnt_tm": "12:34:56",
    "stm": "00:05:23",
    "SteamTemp": 78.150,
    "PipeTemp": 65.230,
    "WaterTemp": 22.100,
    "TankTemp": 85.400,
    "ACPTemp": 30.500,
    "DetectorTrend": 0.012,
    "DetectorStatus": 0,
    "useautospeed": 0,
    "version": "4.5.0-test",
    "VolumeAll": 350,
    "ActualVolumePerHour": 1.200,
    "PowerOn": 0,
    "PauseOn": 0,
    "WthdrwlProgress": 0,
    "TargetStepps": 0,
    "CurrrentStepps": 0,
    "WthdrwlStatus": 0,
    "CurrrentSpeed": 0,
    "UseBBuzzer": 0,
    "StepperStepMl": 250,
    "BodyTemp_Steam": 78.0,
    "BodyTemp_Pipe": 65.0,
    "mixer": 0,
    "ISspd": 0.0,
    "i2c_pump_present": 0,
    "i2c_pump_speed": 0,
    "i2c_pump_target_ml": 0,
    "i2c_pump_remaining_ml": 0,
    "i2c_pump_running": 0,
    "heap": 180000,
    "rssi": -55,
    "fr_bt": 500000,
    "PrgType": "",
    "Status": "Ожидание",
    "current_power_volt": 0.0,
    "target_power_volt": 0.0,
    "current_power_mode": "",
    "current_power_p": 0,
    "WFtotalMl": 0,
    "WFflowRate": 0,
    "Lstatus": "",
}


def apply_template(content: str, vars_dict: dict) -> str:
    for key, value in vars_dict.items():
        content = content.replace(key, str(value))
    return content


async def handle_ajax(request):
    return web.json_response(MOCK_AJAX)


async def handle_command(request):
    return web.Response(text="OK")


async def handle_program(request):
    return web.Response(text="H;450;0.1;1;0;45\nB;450;1;1;0;45\n")


async def handle_save(request):
    return web.Response(text="OK")


async def handle_htm(request, template_vars):
    path = request.match_info.get("filename", "index.htm")
    filepath = DATA_DIR / path
    if not filepath.exists():
        return web.Response(status=404, text=f"Not found: {path}")
    content = filepath.read_text(encoding="utf-8", errors="replace")
    content = apply_template(content, template_vars)
    return web.Response(text=content, content_type="text/html")


async def handle_index(request):
    return await handle_htm(request, TEMPLATE_VARS)


async def handle_setup(request):
    return await handle_htm(request, {**TEMPLATE_VARS, **SETUP_TEMPLATE_VARS})


async def handle_calibrate(request):
    return await handle_htm(request, {**TEMPLATE_VARS, **CALIBRATE_TEMPLATE_VARS})


async def handle_static(request):
    path = request.match_info.get("filename", "")
    filepath = DATA_DIR / path
    if not filepath.exists():
        return web.Response(status=404, text=f"Not found: {path}")

    ext = filepath.suffix.lower()
    content_types = {
        ".js": "application/javascript",
        ".css": "text/css",
        ".png": "image/png",
        ".gif": "image/gif",
        ".ico": "image/x-icon",
        ".mp3": "audio/mpeg",
    }
    ct = content_types.get(ext, "application/octet-stream")

    if ext in (".png", ".gif", ".ico", ".mp3"):
        return web.Response(body=filepath.read_bytes(), content_type=ct)
    return web.Response(text=filepath.read_text(encoding="utf-8", errors="replace"), content_type=ct)


def create_app():
    app = web.Application()
    app.router.add_get("/ajax", handle_ajax)
    app.router.add_get("/command", handle_command)
    app.router.add_post("/command", handle_command)
    app.router.add_get("/program", handle_program)
    app.router.add_post("/program", handle_program)
    app.router.add_post("/save", handle_save)

    # Mode pages (template processed)
    for page in ("index.htm", "beer.htm", "distiller.htm", "nbk.htm", "bk.htm",
                 "program.htm", "chart.htm", "brewxml.htm"):
        app.router.add_get(f"/{page}", handle_index)

    app.router.add_get("/setup.htm", handle_setup)
    app.router.add_get("/calibrate.htm", handle_calibrate)

    # Static files
    app.router.add_get("/{filename}", handle_static)

    return app


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8032
    app = create_app()
    print(f"Mock Samovar server starting on http://localhost:{port}")
    web.run_app(app, host="0.0.0.0", port=port, print=lambda _: None)


if __name__ == "__main__":
    main()
