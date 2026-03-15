from pathlib import Path
import unittest


RUNTIME_HEADER = Path("ui/lua/runtime.h")
ORCHESTRATION_HEADER = Path("app/orchestration.h")


class LuaRuntimeHeaderTest(unittest.TestCase):
    def test_runtime_header_exists_with_lua_init_and_globals_contract(self) -> None:
        self.assertTrue(RUNTIME_HEADER.exists(), "ui/lua/runtime.h must exist")
        text = RUNTIME_HEADER.read_text(encoding="utf-8")
        self.assertIn('inline void lua_init()', text)
        self.assertIn("inline String get_global_variables()", text)
        self.assertIn('lua.Lua_register("pinMode"', text)
        self.assertIn('xTaskCreatePinnedToCore(', text)

    def test_runtime_header_keeps_lua_api_dependency_local(self) -> None:
        text = RUNTIME_HEADER.read_text(encoding="utf-8")
        self.assertIn("#include <LuaWrapper.h>", text)
        self.assertIn('script = get_global_variables();', text)

    def test_orchestration_includes_runtime_header(self) -> None:
        text = ORCHESTRATION_HEADER.read_text(encoding="utf-8")
        self.assertIn('#include "ui/lua/runtime.h"', text)
        self.assertNotIn("void lua_init();", text)


if __name__ == "__main__":
    unittest.main()
