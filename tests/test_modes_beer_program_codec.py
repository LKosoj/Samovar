from pathlib import Path
import re
import unittest


BEER_PROGRAM_CODEC_HEADER = Path("modes/beer/beer_program_codec.h")
LEGACY_BEER_HEADER = Path("beer.h")
DIRECT_INCLUDE_USERS = (
    Path("modes/beer/beer_runtime.h"),
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


class BeerProgramCodecStructureTest(unittest.TestCase):
    def test_beer_program_codec_header_exists(self) -> None:
        self.assertTrue(BEER_PROGRAM_CODEC_HEADER.exists(), "modes/beer/beer_program_codec.h must exist")

    def test_beer_program_codec_header_contains_codec_functions(self) -> None:
        text = BEER_PROGRAM_CODEC_HEADER.read_text(encoding="utf-8")
        self.assertIn("String get_beer_program()", text)
        self.assertIn("void set_beer_program(String WProgram)", text)

    def test_direct_users_include_beer_program_codec_header(self) -> None:
        for path in DIRECT_INCLUDE_USERS:
            with self.subTest(path=path.as_posix()):
                text = path.read_text(encoding="utf-8")
                self.assertIn('#include "modes/beer/beer_program_codec.h"', text)

    def test_legacy_beer_header_deleted(self) -> None:
        self.assertFalse(LEGACY_BEER_HEADER.exists())


class BeerFormatFreezeTest(unittest.TestCase):
    """Freeze beer program format: WType;Temp;Time;devType^Speed^Volume^Power;TempSensor per line."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = BEER_PROGRAM_CODEC_HEADER.read_text(encoding="utf-8")

    def test_set_beer_program_parse_field_order(self) -> None:
        body = _normalize(_extract_function_body(self.text, "void set_beer_program(String WProgram)"))
        self.assertIn('char*tokType=strtok_r(line,";",&saveTok);', body)
        self.assertIn('char*tokTemp=strtok_r(NULL,";",&saveTok);', body)
        self.assertIn('char*tokTime=strtok_r(NULL,";",&saveTok);', body)
        self.assertIn('char*tokDevice=strtok_r(NULL,";",&saveTok);', body)
        self.assertIn('char*tokSensor=strtok_r(NULL,";",&saveTok);', body)
        self.assertIn('char*tokExtra=strtok_r(NULL,";",&saveTok);', body)

    def test_set_beer_program_field_assignment(self) -> None:
        body = _normalize(_extract_function_body(self.text, "void set_beer_program(String WProgram)"))
        self.assertIn("program[i].WType=tokType;", body)
        self.assertIn("program[i].Temp=temp;", body)
        self.assertIn("program[i].Time=timeMin;", body)
        self.assertIn("program[i].capacity_num=(uint8_t)devType;", body)
        self.assertIn("program[i].Speed=(float)speed;", body)
        self.assertIn("program[i].Volume=(uint16_t)onTime;", body)
        self.assertIn("program[i].Power=(uint16_t)offTime;", body)
        self.assertIn("program[i].TempSensor=(uint8_t)sensor;", body)

    def test_set_beer_program_device_payload_parsed_with_caret(self) -> None:
        body = _normalize(_extract_function_body(self.text, "void set_beer_program(String WProgram)"))
        self.assertIn("getValue(device,'^',0)", body)
        self.assertIn("getValue(device,'^',1)", body)
        self.assertIn("getValue(device,'^',2)", body)
        self.assertIn("getValue(device,'^',3)", body)

    def test_set_beer_program_rejects_extra_fields(self) -> None:
        body = _normalize(_extract_function_body(self.text, "void set_beer_program(String WProgram)"))
        self.assertIn("!tokExtra", body)

    def test_get_beer_program_serialization_order(self) -> None:
        body = _normalize(_extract_function_body(self.text, "String get_beer_program()"))
        self.assertIn('Str+=program[i].WType+";";', body)
        self.assertIn('Str+=(String)program[i].Temp+";";', body)
        self.assertIn('Str+=(String)(int)program[i].Time+";";', body)
        self.assertIn(
            'Str+=(String)program[i].capacity_num+"^"+program[i].Speed+"^"+program[i].Volume+"^"+program[i].Power+";";',
            body,
        )
        self.assertIn('Str+=(String)program[i].TempSensor+"\\n";', body)

    def test_set_beer_program_error_resets_program(self) -> None:
        body = _normalize(_extract_function_body(self.text, "void set_beer_program(String WProgram)"))
        self.assertIn('program_fail("Ошибкапрограммы:неверныйформатстрокиbeer");', body)
        self.assertIn('program_fail("Ошибкапрограммы:неверныйшаблонустройстваbeer");', body)


if __name__ == "__main__":
    unittest.main()
