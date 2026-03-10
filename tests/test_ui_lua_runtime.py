from pathlib import Path
import unittest


LUA_HEADER = Path("lua.h")
RUNTIME_HEADER = Path("ui/lua/runtime.h")
ORCHESTRATION_HEADER = Path("app/orchestration.h")


class LuaRuntimeHeaderTest(unittest.TestCase):
    def test_runtime_header_exists_with_lua_init(self) -> None:
        self.assertTrue(RUNTIME_HEADER.exists(), "ui/lua/runtime.h must exist")
        text = RUNTIME_HEADER.read_text(encoding="utf-8")
        self.assertIn('inline void lua_init()', text)
        self.assertIn('lua.Lua_register("pinMode"', text)
        self.assertIn('xTaskCreatePinnedToCore(', text)

    def test_lua_header_no_longer_defines_lua_init_locally(self) -> None:
        text = LUA_HEADER.read_text(encoding="utf-8")
        self.assertNotIn("void lua_init() {", text)
        self.assertIn('#include "ui/lua/runtime.h"', text)

    def test_orchestration_includes_runtime_header(self) -> None:
        text = ORCHESTRATION_HEADER.read_text(encoding="utf-8")
        self.assertIn('#include "ui/lua/runtime.h"', text)
        self.assertNotIn("void lua_init();", text)


if __name__ == "__main__":
    unittest.main()
