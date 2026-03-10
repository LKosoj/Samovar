from pathlib import Path
import unittest


LUA_HEADER = Path("lua.h")
RUNTIME_HEADER = Path("ui/lua/runtime.h")
PROCESS_HEADER = Path("ui/lua/bindings_process.h")


class LuaBindingsProcessHeaderTest(unittest.TestCase):
    def test_process_bindings_header_exists_with_wrappers(self) -> None:
        self.assertTrue(PROCESS_HEADER.exists(), "ui/lua/bindings_process.h must exist")
        text = PROCESS_HEADER.read_text(encoding="utf-8")
        self.assertIn("lua_wrapper_set_pause_withdrawal", text)
        self.assertIn("lua_wrapper_set_power", text)
        self.assertIn("lua_wrapper_set_alarm", text)
        self.assertIn("lua_wrapper_set_body_temp", text)
        self.assertIn("lua_wrapper_set_next_program", text)
        self.assertIn("lua_wrapper_get_state", text)
        self.assertIn("lua_wrapper_send_msg", text)

    def test_runtime_includes_process_bindings(self) -> None:
        text = RUNTIME_HEADER.read_text(encoding="utf-8")
        self.assertIn('#include "ui/lua/bindings_process.h"', text)
        self.assertIn('lua.Lua_register("setPower"', text)
        self.assertIn('lua.Lua_register("setPauseWithdrawal"', text)
        self.assertIn('lua.Lua_register("sendMsg"', text)
        self.assertIn('lua.Lua_register("getState"', text)

    def test_lua_header_no_longer_defines_process_wrappers(self) -> None:
        text = LUA_HEADER.read_text(encoding="utf-8")
        self.assertNotIn("static int lua_wrapper_set_pause_withdrawal(", text)
        self.assertNotIn("static int lua_wrapper_set_power(", text)
        self.assertNotIn("static int lua_wrapper_set_alarm(", text)
        self.assertNotIn("static int lua_wrapper_set_body_temp(", text)
        self.assertNotIn("static int lua_wrapper_set_next_program(", text)
        self.assertNotIn("static int lua_wrapper_get_state(", text)
        self.assertNotIn("static int lua_wrapper_send_msg(", text)


if __name__ == "__main__":
    unittest.main()
