from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest


DEFAULT_PROGRAMS_HEADER = Path("app/default_programs.h")
SENSORINIT_FILE = Path("sensorinit.h")
CONSUMER_FILES = [
    Path("io/sensor_scan.h"),
    Path("ui/web/routes_setup.h"),
]


def _extract_function(text: str, signature: str) -> str:
    pattern = re.compile(rf"(?:static\s+)?(?:inline\s+)?{re.escape(signature)}\s*\{{", re.MULTILINE)
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


class DefaultProgramsExtractionTests(unittest.TestCase):
    def test_default_programs_module_exists_and_owns_loader(self) -> None:
        self.assertTrue(DEFAULT_PROGRAMS_HEADER.exists(), "app/default_programs.h must exist")

        header_text = DEFAULT_PROGRAMS_HEADER.read_text(encoding="utf-8")
        for snippet in [
            "inline void load_default_program_for_mode()",
            "Samovar_Mode == SAMOVAR_BEER_MODE || Samovar_Mode == SAMOVAR_SUVID_MODE",
            'set_beer_program("M;45;0;0^-1^2^2;0\\nP;45;1;0^-1^2^3;0\\nP;60;1;0^-1^2^3;0\\nW;0;0;0^-1^2^3;0\\nB;0;1;0^-1^2^3;0\\nC;30;0;0^-1^2^3;0\\n");',
            'set_dist_program("A;80.00;1;0\\nS;0.50;2;0\\nS;0.30;3;0\\n");',
            "set_nbk_program(NBK_DEFAULT_PROGRAM);",
            'set_program("H;450;0.1;1;0;45\\nB;450;1;1;0;45\\nH;450;0.1;1;0;45\\n");',
        ]:
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, header_text)

    def test_sensorinit_legacy_file_is_removed(self) -> None:
        self.assertFalse(SENSORINIT_FILE.exists(), "sensorinit.h must be removed")

    def test_consumers_no_longer_keep_local_forward_declarations(self) -> None:
        for path in CONSUMER_FILES:
            with self.subTest(path=str(path)):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("void load_default_program_for_mode();", text)

    def test_debug_harness_executes_actual_loader_logic_for_modes(self) -> None:
        compiler = shutil.which("g++") or shutil.which("c++")
        self.assertIsNotNone(compiler, "C++ compiler is required for debug harness test")

        function_text = _extract_function(
            DEFAULT_PROGRAMS_HEADER.read_text(encoding="utf-8"),
            "void load_default_program_for_mode()",
        )

        harness = textwrap.dedent(
            f"""
            #include <iostream>
            #include <string>

            using String = std::string;

            enum SAMOVAR_MODE {{
              SAMOVAR_RECTIFICATION_MODE,
              SAMOVAR_DISTILLATION_MODE,
              SAMOVAR_BEER_MODE,
              SAMOVAR_BK_MODE,
              SAMOVAR_NBK_MODE,
              SAMOVAR_SUVID_MODE,
              SAMOVAR_LUA_MODE
            }};

            volatile SAMOVAR_MODE Samovar_Mode = SAMOVAR_RECTIFICATION_MODE;

            std::string last_kind;
            std::string last_value;

            void set_beer_program(String WProgram) {{ last_kind = "beer"; last_value = WProgram; }}
            void set_dist_program(String WProgram) {{ last_kind = "dist"; last_value = WProgram; }}
            void set_nbk_program(String WProgram) {{ last_kind = "nbk"; last_value = WProgram; }}
            void set_program(String WProgram) {{ last_kind = "rect"; last_value = WProgram; }}

            #define NBK_DEFAULT_PROGRAM "NBK_DEFAULT_PROGRAM_SENTINEL"

            {function_text}

            static std::string escape_newlines(const std::string& value) {{
              std::string out;
              for (char ch : value) {{
                if (ch == '\\n') {{
                  out += "\\\\n";
                }} else {{
                  out += ch;
                }}
              }}
              return out;
            }}

            static void print_case(const char* name, SAMOVAR_MODE mode) {{
              last_kind.clear();
              last_value.clear();
              Samovar_Mode = mode;
              load_default_program_for_mode();
              std::cout << name << "|" << last_kind << "|" << escape_newlines(last_value) << "\\n";
            }}

            int main() {{
              print_case("beer", SAMOVAR_BEER_MODE);
              print_case("suvid", SAMOVAR_SUVID_MODE);
              print_case("dist", SAMOVAR_DISTILLATION_MODE);
              print_case("nbk", SAMOVAR_NBK_MODE);
              print_case("rect", SAMOVAR_RECTIFICATION_MODE);
              print_case("bk", SAMOVAR_BK_MODE);
              return 0;
            }}
            """
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            source_path = tmpdir_path / "default_programs_harness.cpp"
            binary_path = tmpdir_path / "default_programs_harness"
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
                "beer|beer|M;45;0;0^-1^2^2;0\\nP;45;1;0^-1^2^3;0\\nP;60;1;0^-1^2^3;0\\nW;0;0;0^-1^2^3;0\\nB;0;1;0^-1^2^3;0\\nC;30;0;0^-1^2^3;0\\n",
                "suvid|beer|M;45;0;0^-1^2^2;0\\nP;45;1;0^-1^2^3;0\\nP;60;1;0^-1^2^3;0\\nW;0;0;0^-1^2^3;0\\nB;0;1;0^-1^2^3;0\\nC;30;0;0^-1^2^3;0\\n",
                "dist|dist|A;80.00;1;0\\nS;0.50;2;0\\nS;0.30;3;0\\n",
                "nbk|nbk|NBK_DEFAULT_PROGRAM_SENTINEL",
                "rect|rect|H;450;0.1;1;0;45\\nB;450;1;1;0;45\\nH;450;0.1;1;0;45\\n",
                "bk|rect|H;450;0.1;1;0;45\\nB;450;1;1;0;45\\nH;450;0.1;1;0;45\\n",
            ],
        )


if __name__ == "__main__":
    unittest.main()
