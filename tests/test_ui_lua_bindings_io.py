from pathlib import Path
import unittest


LUA_HEADER = Path("lua.h")
RUNTIME_HEADER = Path("ui/lua/runtime.h")
IO_HEADER = Path("ui/lua/bindings_io.h")


class LuaBindingsIoHeaderTest(unittest.TestCase):
    def test_io_bindings_header_exists_with_wrappers(self) -> None:
        self.assertTrue(IO_HEADER.exists(), "ui/lua/bindings_io.h must exist")
        text = IO_HEADER.read_text(encoding="utf-8")
        self.assertIn("lua_wrapper_set_mixer", text)
        self.assertIn("lua_wrapper_open_valve", text)
        self.assertIn("lua_wrapper_set_capacity", text)
        self.assertIn("lua_wrapper_set_stepper_target", text)
        self.assertIn("lua_wrapper_i2cpump_start", text)
        self.assertIn("lua_wrapper_set_i2c_rele_state", text)

    def test_runtime_includes_io_bindings(self) -> None:
        text = RUNTIME_HEADER.read_text(encoding="utf-8")
        self.assertIn('#include "ui/lua/bindings_io.h"', text)
        self.assertIn('lua.Lua_register("setMixer"', text)
        self.assertIn('lua.Lua_register("openValve"', text)
        self.assertIn('lua.Lua_register("setCapacity"', text)
        self.assertIn('lua.Lua_register("set_stepper_target"', text)
        self.assertIn('lua.Lua_register("i2cpump_start"', text)
        self.assertIn('lua.Lua_register("set_i2c_rele_state"', text)

    def test_lua_header_no_longer_defines_io_wrappers(self) -> None:
        text = LUA_HEADER.read_text(encoding="utf-8")
        self.assertNotIn("static int lua_wrapper_set_mixer(", text)
        self.assertNotIn("static int lua_wrapper_open_valve(", text)
        self.assertNotIn("static int lua_wrapper_set_capacity(", text)
        self.assertNotIn("static int lua_wrapper_set_stepper_target(", text)
        self.assertNotIn("static int lua_wrapper_i2cpump_start(", text)
        self.assertNotIn("static int lua_wrapper_set_i2c_rele_state(", text)


if __name__ == "__main__":
    unittest.main()
