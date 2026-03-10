from pathlib import Path
import unittest


LUA_HEADER = Path("lua.h")
RUNTIME_HEADER = Path("ui/lua/runtime.h")
GPIO_HEADER = Path("ui/lua/bindings_gpio.h")


class LuaBindingsGpioHeaderTest(unittest.TestCase):
    def test_gpio_bindings_header_exists_with_wrappers(self) -> None:
        self.assertTrue(GPIO_HEADER.exists(), "ui/lua/bindings_gpio.h must exist")
        text = GPIO_HEADER.read_text(encoding="utf-8")
        self.assertIn("lua_wrapper_pinMode", text)
        self.assertIn("lua_wrapper_digitalWrite", text)
        self.assertIn("lua_wrapper_digitalRead", text)
        self.assertIn("lua_wrapper_analogRead", text)

    def test_runtime_includes_gpio_bindings(self) -> None:
        text = RUNTIME_HEADER.read_text(encoding="utf-8")
        self.assertIn('#include "ui/lua/bindings_gpio.h"', text)
        self.assertIn('lua.Lua_register("pinMode"', text)
        self.assertIn('lua.Lua_register("digitalWrite"', text)

    def test_lua_header_no_longer_defines_gpio_wrappers(self) -> None:
        text = LUA_HEADER.read_text(encoding="utf-8")
        self.assertNotIn("static int lua_wrapper_pinMode(", text)
        self.assertNotIn("static int lua_wrapper_digitalWrite(", text)
        self.assertNotIn("static int lua_wrapper_digitalRead(", text)
        self.assertNotIn("static int lua_wrapper_analogRead(", text)


if __name__ == "__main__":
    unittest.main()
