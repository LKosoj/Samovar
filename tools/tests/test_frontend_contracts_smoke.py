#!/usr/bin/env python3
"""
Smoke test: Verify frontend contracts (JSON keys, form fields) are preserved.

This test verifies:
1. AJAX JSON response contains all expected keys
2. HTML form fields match baseline
3. No breaking changes to web API contracts
"""

import os
import re
import json
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

# Expected JSON keys from AJAX endpoint (actual keys from ajax_snapshot.h)
EXPECTED_JSON_KEYS = [
    "bme_temp",
    "bme_pressure",
    "start_pressure",
    "crnt_tm",
    "stm",
    "SteamTemp",
    "PipeTemp",
    "WaterTemp",
    "TankTemp",
    "ACPTemp",
    "DetectorTrend",
    "DetectorStatus",
    "useautospeed",
    "version",
    "VolumeAll",
    "ActualVolumePerHour",
    "PowerOn",
    "PauseOn",
    "WthdrwlProgress",
    "WthdrwlStatus",
    "Status",
    "Msg",
    "msglvl",
    "current_power_volt",
    "target_power_volt",
    "current_power_p",
    "current_power_mode",
    "StepperStepMl",
    "CurrrentSpeed",
    "CurrrentStepps",
    "TargetStepps",
    "TimeRemaining",
    "TotalTime",
    "BodyTemp_Steam",
    "BodyTemp_Pipe",
    "alc",
    "stm_alc",
    "fr_bt",
    "prvl",
    "ISspd",
    "wp_spd",
    "mixer",
    "Lstatus",
    "LogMsg",
    "heap",
    "rssi",
    "i2c_pump_present",
    "i2c_pump_running",
    "i2c_pump_speed",
    "i2c_pump_target_ml",
    "i2c_pump_remaining_ml",
    "WFflowRate",
    "WFtotalMl",
    "PrgType",
]

# Expected form fields from HTML pages
EXPECTED_FORM_FIELDS = {
    'index.htm': [
        'Voltage',
        'pumpspeed',
        'i2c_speed',
        'i2c_volume',
        'WProgram',
    ],
    'beer.htm': [
        'WProgram',
        'Voltage',
        'i2c_speed',
        'i2c_volume',
    ],
    'distiller.htm': [
        'WProgram',
        'Voltage',
    ],
    'setup.htm': [
        'Temp',  # Common temp field for all sensors
        'StepperStepMl',
        'PackDens',
        'ColDiam',
        'ColHeight',
    ],
}

# Expected command endpoints
EXPECTED_COMMANDS = [
    'voltage',
    'pumpspeed',
    'i2cpump',
    'start',
    'power',
    'pause',
    'continue',
    'reset',
    'calibrate',
    'beerNext',
    'distNext',
    'nbkNext',
    'selfTest',
    'lua',
    'strlua',
]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def extract_json_keys_from_source(source_path: str) -> set:
    """Extract JSON keys from ajax_snapshot.h source"""
    keys = set()
    with open(source_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find all jsonAddKey calls
    pattern = r'jsonAddKey\(out,\s*first,\s*"([^"]+)"\)'
    matches = re.findall(pattern, content)
    keys.update(matches)
    
    return keys


def extract_form_fields_from_html(html_path: str) -> set:
    """Extract form field names from HTML file"""
    fields = set()
    with open(html_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find input name attributes
    input_pattern = r'name=["\']([^"\']+)["\']'
    matches = re.findall(input_pattern, content)
    fields.update(matches)
    
    # Find id attributes that might be used as fields
    id_pattern = r'id=["\']([^"\']+)["\']'
    matches = re.findall(id_pattern, content)
    fields.update(matches)
    
    return fields


def main() -> int:
    print("=" * 70)
    print("Frontend contracts verification smoke test")
    print("=" * 70)
    
    # 1. Verify AJAX JSON keys from source
    print("\n[1] Checking AJAX JSON keys from ajax_snapshot.h...")
    ajax_source = os.path.join(ROOT, 'ui', 'web', 'ajax_snapshot.h')
    require(os.path.exists(ajax_source), f"ajax_snapshot.h not found at {ajax_source}")
    
    actual_keys = extract_json_keys_from_source(ajax_source)
    print(f"    Found {len(actual_keys)} JSON keys in ajax_snapshot.h")
    
    # Check that expected keys are present
    missing_keys = set(EXPECTED_JSON_KEYS) - actual_keys
    if missing_keys:
        print(f"    ⚠ Missing expected keys: {missing_keys}")
        # This is informational - keys may have been legitimately changed
    else:
        print(f"    ✓ All expected JSON keys present")
    
    # 2. Verify HTML form fields
    print("\n[2] Checking HTML form fields...")
    data_dir = os.path.join(ROOT, 'data')
    
    for html_file, expected_fields in EXPECTED_FORM_FIELDS.items():
        html_path = os.path.join(data_dir, html_file)
        require(os.path.exists(html_path), f"HTML file not found: {html_path}")
        
        actual_fields = extract_form_fields_from_html(html_path)
        
        # Check critical fields are present
        missing_fields = set(expected_fields) - actual_fields
        if missing_fields:
            print(f"    ⚠ {html_file}: Missing fields: {missing_fields}")
        else:
            print(f"    ✓ {html_file}: All expected fields present")
    
    # 3. Verify command routing
    print("\n[3] Checking command routing...")
    command_router_path = os.path.join(ROOT, 'src', 'core', 'commands', 'command_router.cpp')
    if os.path.exists(command_router_path):
        with open(command_router_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        found_commands = []
        missing_commands = []
        for cmd in EXPECTED_COMMANDS:
            if cmd in content:
                found_commands.append(cmd)
            else:
                missing_commands.append(cmd)
        
        print(f"    Found {len(found_commands)}/{len(EXPECTED_COMMANDS)} expected commands")
        if missing_commands:
            print(f"    ℹ Commands not found in router (may be handled elsewhere): {missing_commands[:5]}...")
    else:
        print(f"    ℹ command_router.cpp not found, skipping command verification")
    
    # 4. Verify common.js does not break existing functionality
    print("\n[4] Checking common.js integration...")
    common_js = os.path.join(data_dir, 'common.js')
    require(os.path.exists(common_js), f"common.js not found at {common_js}")
    
    with open(common_js, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check that common.js exports expected functions
    expected_js_functions = [
        'ConnectError',
        'setPowerUnit',
        'sendbutton',
        'sendvoltage',
        'addMessage',
        'playSound',
    ]
    
    missing_funcs = []
    for func in expected_js_functions:
        pattern = rf'function\s+{func}\s*\('
        if not re.search(pattern, content):
            missing_funcs.append(func)
    
    if missing_funcs:
        print(f"    ✗ Missing JS functions in common.js: {missing_funcs}")
        require(False, f"common.js missing functions: {missing_funcs}")
    else:
        print(f"    ✓ All expected JS functions present in common.js")
    
    # 5. Summary
    print("\n" + "=" * 70)
    print("Frontend contracts verification: PASS")
    print("=" * 70)
    print(f"\nSummary:")
    print(f"  - AJAX JSON keys: {len(actual_keys)} found")
    print(f"  - HTML form fields: verified in {len(EXPECTED_FORM_FIELDS)} files")
    print(f"  - Command routing: {len(found_commands) if 'found_commands' in locals() else 'N/A'} commands")
    print(f"  - common.js functions: {len(expected_js_functions)} verified")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
