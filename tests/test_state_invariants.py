from pathlib import Path
import re
import unittest


GLOBALS_HEADER = Path("state/globals.h")
SAMOVAR_SOURCE = Path("Samovar.ino")
LOGIC_HEADER = Path("logic.h")
STATUS_TEXT_HEADER = Path("app/status_text.h")
RECT_PROGRAM_CODEC_HEADER = Path("modes/rect/rect_program_codec.h")
DISTILLER_HEADER = Path("distiller.h")
BEER_HEADER = Path("beer.h")
NBK_HEADER = Path("nbk.h")


def extract_function_body(text: str, signature: str) -> str:
    pattern = re.compile(re.escape(signature) + r"\s*\{", re.MULTILINE)
    matches = list(pattern.finditer(text))
    if not matches:
        raise AssertionError(f"Function definition not found: {signature}")
    brace_start = matches[-1].end() - 1

    depth = 0
    for index in range(brace_start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[brace_start : index + 1]
    raise AssertionError(f"Unbalanced braces for: {signature}")


class StateInvariantTest(unittest.TestCase):
    def test_representative_globals_are_declared_once_and_defined_once(self) -> None:
        globals_text = GLOBALS_HEADER.read_text(encoding="utf-8")
        samovar_text = SAMOVAR_SOURCE.read_text(encoding="utf-8")

        expected_pairs = {
            "SamovarStatus": ("extern String SamovarStatus;", "String SamovarStatus;"),
            "SamovarStatusInt": (
                "extern volatile int16_t SamovarStatusInt;",
                "volatile int16_t SamovarStatusInt;",
            ),
            "ProgramNum": ("extern volatile uint8_t ProgramNum;", "volatile uint8_t ProgramNum;"),
            "ProgramLen": ("extern volatile uint8_t ProgramLen;", "volatile uint8_t ProgramLen;"),
            "program": ("extern WProgram program[30];", "WProgram program[30];"),
            "PowerOn": ("extern volatile bool PowerOn;", "volatile bool PowerOn = false;"),
            "SamSetup": ("extern SetupEEPROM SamSetup;", "SetupEEPROM SamSetup;"),
        }

        for name, (declaration, definition) in expected_pairs.items():
            with self.subTest(global_name=name):
                self.assertEqual(globals_text.count(declaration), 1)
                self.assertEqual(samovar_text.count(definition), 1)

    def test_status_accessor_keeps_reading_runtime_globals(self) -> None:
        body = extract_function_body(
            STATUS_TEXT_HEADER.read_text(encoding="utf-8"),
            "String get_Samovar_Status()",
        )
        self.assertIn("SamovarStatus.clear();", body)
        self.assertIn("SamovarStatusInt", body)
        self.assertIn("ProgramNum", body)
        self.assertIn("program[ProgramNum]", body)

    def test_program_accessors_keep_reading_program_storage(self) -> None:
        expectations = [
            (
                RECT_PROGRAM_CODEC_HEADER,
                "String get_program(uint8_t s)",
                ["program[i]", "Str +=", "CAPACITY_NUM"],
            ),
            (DISTILLER_HEADER, "String get_dist_program()", ["program[i]", "Str +=", "CAPACITY_NUM"]),
            (BEER_HEADER, "String get_beer_program()", ["program[i]", "Str +=", "CAPACITY_NUM"]),
            (NBK_HEADER, "String get_nbk_program()", ["program[i]", "Str +=", "CAPACITY_NUM"]),
        ]

        for header, signature, markers in expectations:
            with self.subTest(signature=signature):
                body = extract_function_body(header.read_text(encoding="utf-8"), signature)
                for marker in markers:
                    self.assertIn(marker, body)


if __name__ == "__main__":
    unittest.main()
