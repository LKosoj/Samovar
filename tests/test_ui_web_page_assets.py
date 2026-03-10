import os
from pathlib import Path


SERVER_INIT = Path("ui/web/server_init.h")

def test_page_assets_header_exists():
    assert os.path.exists("ui/web/page_assets.h")

def test_page_assets_content():
    with open("ui/web/page_assets.h", "r") as f:
        content = f.read()
    
    assert "void handleFileWithGzip" in content
    assert "void handleWifiHtmFromMemory" in content
    assert "#include \"Samovar.h\"" in content
    assert "#include \"wifi_htm_gz.h\"" in content

def test_server_init_includes_page_assets():
    with SERVER_INIT.open("r", encoding="utf-8") as f:
        content = f.read()
    
    assert '#include "ui/web/page_assets.h"' in content
    assert not Path("WebServer.ino").exists()

if __name__ == "__main__":
    try:
        test_page_assets_header_exists()
        test_page_assets_content()
        test_server_init_includes_page_assets()
        print("Structural tests passed!")
    except AssertionError as e:
        print(f"Structural tests failed: {e}")
        exit(1)
