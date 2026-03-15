from pathlib import Path
import unittest


RUNTIME_HEADER = Path("ui/lua/runtime.h")
HTTP_HEADER = Path("ui/lua/bindings_http.h")


class LuaBindingsHttpHeaderTest(unittest.TestCase):
    def test_http_bindings_header_exists_with_wrapper(self) -> None:
        self.assertTrue(HTTP_HEADER.exists(), "ui/lua/bindings_http.h must exist")
        text = HTTP_HEADER.read_text(encoding="utf-8")
        self.assertIn("lua_wrapper_http_request", text)
        self.assertIn("asyncHTTPrequest request;", text)
        self.assertIn("request.open(", text)
        self.assertIn("request.send", text)
        self.assertIn("request.responseHTTPcode()", text)

    def test_runtime_includes_http_bindings(self) -> None:
        text = RUNTIME_HEADER.read_text(encoding="utf-8")
        self.assertIn('#include "ui/lua/bindings_http.h"', text)
        self.assertIn('lua.Lua_register("http_request"', text)

    def test_runtime_header_does_not_inline_http_wrapper(self) -> None:
        text = RUNTIME_HEADER.read_text(encoding="utf-8")
        self.assertNotIn("static int lua_wrapper_http_request(", text)


if __name__ == "__main__":
    unittest.main()
