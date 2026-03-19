from pathlib import Path
import re
import unittest


NBK_PROGRAM_CODEC_HEADER = Path("modes/nbk/nbk_program_codec.h")
DIRECT_INCLUDE_USERS = (
    Path("modes/nbk/nbk_runtime.h"),
    Path("app/default_programs.h"),
)


def _extract_function_body(text: str, signature: str) -> str:
    pattern = re.compile(rf"(?:inline\s+)?{re.escape(signature)}\s*\{{", re.MULTILINE)
    match = pattern.search(text)
    if match is None:
        raise AssertionError(f"Function signature not found: {signature}")
    brace_start = text.find("{", match.start())
    depth = 0
    for index in range(brace_start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[brace_start + 1:index]
    raise AssertionError(f"Function body end not found: {signature}")


def _normalize(body: str) -> str:
    body = re.sub(r"//.*", "", body)
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL)
    return re.sub(r"\s+", "", body)


class NbkProgramCodecExtractionTest(unittest.TestCase):
    def test_nbk_program_codec_header_exists(self) -> None:
        self.assertTrue(NBK_PROGRAM_CODEC_HEADER.exists(), "modes/nbk/nbk_program_codec.h must exist")

    def test_nbk_program_codec_header_contains_extracted_codec(self) -> None:
        text = NBK_PROGRAM_CODEC_HEADER.read_text(encoding="utf-8")
        for signature in [
            "inline void set_nbk_program(String WProgram)",
            "inline String get_nbk_program()",
        ]:
            with self.subTest(signature=signature):
                self.assertIn(signature, text)

    def test_direct_users_include_nbk_program_codec_header(self) -> None:
        for path in DIRECT_INCLUDE_USERS:
            with self.subTest(path=path.as_posix()):
                text = path.read_text(encoding="utf-8")
                self.assertIn('#include "modes/nbk/nbk_program_codec.h"', text)

    def test_legacy_nbk_header_removed(self) -> None:
        self.assertFalse(Path("nbk.h").exists())


class NbkFormatFreezeTest(unittest.TestCase):
    """Freeze nbk program format: WType;Speed;Power per line."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = NBK_PROGRAM_CODEC_HEADER.read_text(encoding="utf-8")

    def test_set_nbk_program_parse_field_order(self) -> None:
        body = _normalize(_extract_function_body(self.text, "void set_nbk_program(String WProgram)"))
        self.assertIn('char*tokType=strtok_r(line,";",&saveTok);', body)
        self.assertIn('char*tokSpeed=strtok_r(NULL,";",&saveTok);', body)
        self.assertIn('char*tokPower=strtok_r(NULL,";",&saveTok);', body)
        self.assertIn('char*tokExtra=strtok_r(NULL,";",&saveTok);', body)

    def test_set_nbk_program_field_assignment(self) -> None:
        body = _normalize(_extract_function_body(self.text, "void set_nbk_program(String WProgram)"))
        self.assertIn("program[i].WType=tokType;", body)
        self.assertIn("program[i].Speed=speed;", body)
        self.assertIn("program[i].Power=power;", body)

    def test_set_nbk_program_rejects_extra_fields(self) -> None:
        body = _normalize(_extract_function_body(self.text, "void set_nbk_program(String WProgram)"))
        self.assertIn("!tokExtra", body)

    def test_get_nbk_program_serialization_order(self) -> None:
        body = _normalize(_extract_function_body(self.text, "String get_nbk_program()"))
        self.assertIn('Str+=program[i].WType+";";', body)
        self.assertIn('Str+=(String)program[i].Speed+";";', body)
        self.assertIn('Str+=(String)(int)program[i].Power+"\\n";', body)

    def test_set_nbk_program_error_resets_program(self) -> None:
        body = _normalize(_extract_function_body(self.text, "void set_nbk_program(String WProgram)"))
        self.assertIn('program_fail("Ошибкапрограммы:неверныйформатстрокиnbk");', body)


if __name__ == "__main__":
    unittest.main()
