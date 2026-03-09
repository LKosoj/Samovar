import os
import re

def test_page_assets_header_exists():
    assert os.path.exists("ui/web/page_assets.h")

def test_page_assets_content():
    with open("ui/web/page_assets.h", "r") as f:
        content = f.read()
    
    assert "void handleFileWithGzip" in content
    assert "void handleWifiHtmFromMemory" in content
    assert "#include \"Samovar.h\"" in content
    assert "#include \"wifi_htm_gz.h\"" in content

def test_webserver_includes_page_assets():
    with open("WebServer.ino", "r") as f:
        content = f.read()
    
    assert '#include "ui/web/page_assets.h"' in content
    assert '#include "ui/web/server_init.h"' in content
    
    # Ensure functions are removed from WebServer.ino
    assert "void handleFileWithGzip(" not in content
    assert "void handleWifiHtmFromMemory(" not in content

if __name__ == "__main__":
    try:
        test_page_assets_header_exists()
        test_page_assets_content()
        test_webserver_includes_page_assets()
        print("Structural tests passed!")
    except AssertionError as e:
        print(f"Structural tests failed: {e}")
        exit(1)
