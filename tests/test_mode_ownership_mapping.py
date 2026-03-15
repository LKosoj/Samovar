from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest


MODE_OWNERSHIP_HEADER = Path("src/core/state/mode_ownership.h")
MODE_MAPPING_DOC = Path("docs/result/delivery/mode_ownership_mapping.md")
SAMOVAR_HEADER = Path("Samovar.h")
PAGE_ASSETS_HEADER = Path("ui/web/page_assets.h")
DEFAULT_PROGRAMS_HEADER = Path("app/default_programs.h")
NVS_PROFILES_HEADER = Path("storage/nvs_profiles.h")
LUA_RUNTIME_HEADER = Path("ui/lua/runtime.h")
ORCHESTRATION_HEADER = Path("app/orchestration.h")
RUNTIME_TASKS_HEADER = Path("app/runtime_tasks.h")


def _extract_function(text: str, signature: str) -> str:
    pattern = re.compile(rf"(?:inline\s+)?{re.escape(signature)}\s*\{{", re.MULTILINE)
    match = pattern.search(text)
    if match is None:
        raise AssertionError(f"Function signature not found: {signature}")

    brace_start = text.find("{", match.start())
    if brace_start == -1:
        raise AssertionError(f"Function body start not found: {signature}")

    depth = 0
    for index in range(brace_start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[match.start():index + 1]

    raise AssertionError(f"Function body end not found: {signature}")


class ModeOwnershipMappingTest(unittest.TestCase):
    def test_mode_ownership_header_exists_and_defines_mapping_helpers(self) -> None:
        text = MODE_OWNERSHIP_HEADER.read_text(encoding="utf-8")
        required_tokens = [
            "inline SAMOVAR_MODE mode_runtime_owner(SAMOVAR_MODE mode)",
            "inline SAMOVAR_MODE mode_program_owner(SAMOVAR_MODE mode)",
            "inline SAMOVAR_MODE mode_lua_owner(SAMOVAR_MODE mode)",
            "inline const char* mode_active_page(SAMOVAR_MODE mode)",
            "inline const char* mode_profile_namespace(SAMOVAR_MODE mode)",
            "inline bool mode_is_rect_runtime(SAMOVAR_MODE mode)",
            "inline bool mode_is_distillation_runtime(SAMOVAR_MODE mode)",
            "inline bool mode_is_beer_runtime(SAMOVAR_MODE mode)",
            "inline bool mode_is_bk_runtime(SAMOVAR_MODE mode)",
            "inline bool mode_is_nbk_runtime(SAMOVAR_MODE mode)",
            "case SAMOVAR_SUVID_MODE:",
            "case SAMOVAR_LUA_MODE:",
            'return "/index.htm";',
            'return "sam_suvid";',
            'return "sam_lua";',
        ]
        for token in required_tokens:
            with self.subTest(token=token):
                self.assertIn(token, text)

    def test_consumers_use_mode_ownership_helpers(self) -> None:
        self.assertIn('#include "src/core/state/mode_ownership.h"', SAMOVAR_HEADER.read_text(encoding="utf-8"))
        self.assertIn("const char* activePage = mode_active_page(Samovar_Mode);", PAGE_ASSETS_HEADER.read_text(encoding="utf-8"))
        self.assertIn("Samovar_Mode = mode_runtime_owner(Samovar_Mode);", PAGE_ASSETS_HEADER.read_text(encoding="utf-8"))
        self.assertIn("switch (mode_program_owner(Samovar_Mode))", DEFAULT_PROGRAMS_HEADER.read_text(encoding="utf-8"))
        self.assertIn("return mode_profile_namespace((SAMOVAR_MODE)mode);", NVS_PROFILES_HEADER.read_text(encoding="utf-8"))
        self.assertIn("switch (mode_lua_owner(Samovar_CR_Mode))", LUA_RUNTIME_HEADER.read_text(encoding="utf-8"))
        self.assertIn("if (mode_is_rect_runtime(Samovar_Mode))", ORCHESTRATION_HEADER.read_text(encoding="utf-8"))
        self.assertIn("if (mode_is_rect_runtime(Samovar_Mode))", RUNTIME_TASKS_HEADER.read_text(encoding="utf-8"))

    def test_mode_ownership_doc_exists_and_lists_all_modes(self) -> None:
        text = MODE_MAPPING_DOC.read_text(encoding="utf-8")
        required_tokens = [
            "# Step 2.3 mode ownership mapping",
            "## Runtime ownership model",
            "## Mapping table",
            "`SAMOVAR_RECTIFICATION_MODE`",
            "`SAMOVAR_DISTILLATION_MODE`",
            "`SAMOVAR_BEER_MODE`",
            "`SAMOVAR_BK_MODE`",
            "`SAMOVAR_NBK_MODE`",
            "`SAMOVAR_SUVID_MODE`",
            "`SAMOVAR_LUA_MODE`",
            "[src/core/state/mode_ownership.h]",
            "[ui/web/page_assets.h]",
            "[app/default_programs.h]",
            "[ui/lua/runtime.h]",
            "[storage/nvs_profiles.h]",
            "[app/orchestration.h]",
            "[app/runtime_tasks.h]",
        ]
        for token in required_tokens:
            with self.subTest(token=token):
                self.assertIn(token, text)

    def test_mapping_harness_matches_documented_mode_ownership(self) -> None:
        compiler = shutil.which("g++") or shutil.which("c++")
        self.assertIsNotNone(compiler, "C++ compiler is required for ownership mapping test")

        header_text = MODE_OWNERSHIP_HEADER.read_text(encoding="utf-8")
        runtime_owner = _extract_function(
            header_text,
            "SAMOVAR_MODE mode_runtime_owner(SAMOVAR_MODE mode)",
        )
        program_owner = _extract_function(
            header_text,
            "SAMOVAR_MODE mode_program_owner(SAMOVAR_MODE mode)",
        )
        lua_owner = _extract_function(
            header_text,
            "SAMOVAR_MODE mode_lua_owner(SAMOVAR_MODE mode)",
        )
        active_page = _extract_function(
            header_text,
            "const char* mode_active_page(SAMOVAR_MODE mode)",
        )
        profile_namespace = _extract_function(
            header_text,
            "const char* mode_profile_namespace(SAMOVAR_MODE mode)",
        )

        harness = textwrap.dedent(
            f"""
            #include <iostream>

            enum SAMOVAR_MODE {{
              SAMOVAR_RECTIFICATION_MODE = 0,
              SAMOVAR_DISTILLATION_MODE = 1,
              SAMOVAR_BEER_MODE = 2,
              SAMOVAR_BK_MODE = 3,
              SAMOVAR_NBK_MODE = 4,
              SAMOVAR_SUVID_MODE = 5,
              SAMOVAR_LUA_MODE = 6
            }};

            {runtime_owner}

            {program_owner}

            {lua_owner}

            {active_page}

            {profile_namespace}

            static void print_case(const char* name, SAMOVAR_MODE mode) {{
              std::cout << name
                        << "|" << mode_runtime_owner(mode)
                        << "|" << mode_active_page(mode)
                        << "|" << mode_program_owner(mode)
                        << "|" << mode_lua_owner(mode)
                        << "|" << mode_profile_namespace(mode)
                        << "\\n";
            }}

            int main() {{
              print_case("rect", SAMOVAR_RECTIFICATION_MODE);
              print_case("dist", SAMOVAR_DISTILLATION_MODE);
              print_case("beer", SAMOVAR_BEER_MODE);
              print_case("bk", SAMOVAR_BK_MODE);
              print_case("nbk", SAMOVAR_NBK_MODE);
              print_case("suvid", SAMOVAR_SUVID_MODE);
              print_case("lua", SAMOVAR_LUA_MODE);
              return 0;
            }}
            """
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            source_path = tmp_path / "mode_ownership_harness.cpp"
            binary_path = tmp_path / "mode_ownership_harness"
            source_path.write_text(harness, encoding="utf-8")

            subprocess.run(
                [compiler, "-std=c++17", str(source_path), "-o", str(binary_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            completed = subprocess.run(
                [str(binary_path)],
                check=True,
                capture_output=True,
                text=True,
            )

        self.assertEqual(
            completed.stdout.strip().splitlines(),
            [
                "rect|0|/index.htm|0|0|sam_rect",
                "dist|1|/distiller.htm|1|1|sam_dist",
                "beer|2|/beer.htm|2|2|sam_beer",
                "bk|3|/bk.htm|0|3|sam_bk",
                "nbk|4|/nbk.htm|4|4|sam_nbk",
                "suvid|0|/index.htm|2|0|sam_suvid",
                "lua|0|/index.htm|0|0|sam_lua",
            ],
        )


if __name__ == "__main__":
    unittest.main()
