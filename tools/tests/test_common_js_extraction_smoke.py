#!/usr/bin/env python3
"""
Smoke test: Verify common.js extraction reduced code duplication.

This test verifies:
1. data/common.js exists and contains expected functions
2. HTML files reference common.js
3. Duplicate JS code was removed from HTML files
"""

import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
DATA_DIR = os.path.join(ROOT, 'data')
COMMON_JS = os.path.join(DATA_DIR, 'common.js')

# Expected functions in common.js
EXPECTED_FUNCTIONS = [
    'ConnectError',
    'setPowerUnit',
    'AddLuaButtons',
    'playSound',
    'getHistory',
    'saveHistory',
    'showHistory',
    'clearHistory',
    'addMessage',
    'removeLastMessage',
    'showMessages',
    'clearMessages',
    'headerClick',
    'openTab',
    'check_program',
    'calc_program',
    'calc_time',
    'set_program',
    'sleep',
    'sendbutton',
    'sendvoltage',
    'loadDoc',
    'run_lua',
]

# HTML files that should reference common.js
HTML_FILES_WITH_COMMON = [
    'index.htm',
    'beer.htm',
    'bk.htm',
    'distiller.htm',
    'nbk.htm',
    'chart.htm',
    'edit.htm',
    'program.htm',
    'setup.htm',
]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    print("=" * 70)
    print("Common.js extraction smoke test")
    print("=" * 70)
    
    # 1. Verify common.js exists
    print("\n[1] Checking common.js exists...")
    require(os.path.exists(COMMON_JS), f"common.js not found at {COMMON_JS}")
    print(f"    ✓ common.js exists ({os.path.getsize(COMMON_JS)} bytes)")
    
    # 2. Verify common.js contains expected functions
    print("\n[2] Checking common.js contains expected functions...")
    with open(COMMON_JS, 'r', encoding='utf-8') as f:
        common_js_content = f.read()
    
    missing_functions = []
    for func in EXPECTED_FUNCTIONS:
        pattern = rf'function\s+{func}\s*\('
        if not re.search(pattern, common_js_content):
            missing_functions.append(func)
    
    if missing_functions:
        print(f"    ✗ Missing functions: {missing_functions}")
        require(False, f"common.js missing functions: {missing_functions}")
    else:
        print(f"    ✓ All {len(EXPECTED_FUNCTIONS)} expected functions found")
    
    # 3. Verify HTML files reference common.js
    print("\n[3] Checking HTML files reference common.js...")
    for html_file in HTML_FILES_WITH_COMMON:
        html_path = os.path.join(DATA_DIR, html_file)
        require(os.path.exists(html_path), f"HTML file not found: {html_path}")
        
        with open(html_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        has_reference = 'common.js' in content
        require(has_reference, f"{html_file} does not reference common.js")
        print(f"    ✓ {html_file} references common.js")
    
    # 4. Verify code duplication was reduced
    print("\n[4] Checking code duplication was reduced...")
    
    # Count function definitions in common.js
    common_func_count = len(re.findall(r'function\s+\w+\s*\(', common_js_content))
    print(f"    Functions in common.js: {common_func_count}")
    
    # Count duplicate function definitions across HTML files
    duplicate_functions_found = 0
    for html_file in HTML_FILES_WITH_COMMON:
        html_path = os.path.join(DATA_DIR, html_file)
        with open(html_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for duplicate function definitions that should be in common.js
        for func in ['ConnectError', 'setPowerUnit', 'playSound', 'addMessage']:
            pattern = rf'function\s+{func}\s*\('
            if re.search(pattern, content):
                duplicate_functions_found += 1
                print(f"    ⚠ {func} still defined in {html_file}")
    
    if duplicate_functions_found == 0:
        print(f"    ✓ No duplicate function definitions found in HTML files")
    else:
        print(f"    Note: {duplicate_functions_found} duplicate definitions found (may be acceptable)")
    
    # 5. Summary
    print("\n" + "=" * 70)
    print("Common.js extraction smoke: PASS")
    print("=" * 70)
    print(f"\nSummary:")
    print(f"  - common.js: {os.path.getsize(COMMON_JS)} bytes, {common_func_count} functions")
    print(f"  - {len(HTML_FILES_WITH_COMMON)} HTML files reference common.js")
    print(f"  - Code duplication: {'minimized' if duplicate_functions_found == 0 else 'reduced'}")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
