from pathlib import Path
import unittest


RUNTIME_HEADER = Path("ui/lua/runtime.h")
VARIABLES_HEADER = Path("ui/lua/bindings_variables.h")


class LuaBindingsVariablesHeaderTest(unittest.TestCase):
    def test_variables_bindings_header_exists_with_wrappers(self) -> None:
        self.assertTrue(VARIABLES_HEADER.exists(), "ui/lua/bindings_variables.h must exist")
        text = VARIABLES_HEADER.read_text(encoding="utf-8")
        for snippet in [
            "inline void wait_command_sync()",
            "lua_wrapper_delay",
            "lua_wrapper_millis",
            "lua_wrapper_set_num_variable",
            "lua_wrapper_get_num_variable",
            "lua_wrapper_set_str_variable",
            "lua_wrapper_get_str_variable",
            "lua_wrapper_set_object",
            "lua_wrapper_get_object",
            "lua_wrapper_set_lua_status",
            "lua_wrapper_set_timer",
            "lua_wrapper_get_timer",
        ]:
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, text)

    def test_runtime_includes_variables_bindings(self) -> None:
        text = RUNTIME_HEADER.read_text(encoding="utf-8")
        self.assertIn('#include "ui/lua/bindings_variables.h"', text)
        self.assertIn('lua.Lua_register("delay"', text)
        self.assertIn('lua.Lua_register("millis"', text)
        self.assertIn('lua.Lua_register("setNumVariable"', text)
        self.assertIn('lua.Lua_register("getTimer"', text)


if __name__ == "__main__":
    unittest.main()
