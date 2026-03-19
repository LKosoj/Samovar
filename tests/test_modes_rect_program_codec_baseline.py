from pathlib import Path
import re
import subprocess
import unittest


BASELINE_LOGIC_COMMIT = "c33ee650"
RECT_PROGRAM_CODEC_HEADER = Path("modes/rect/rect_program_codec.h")


def _read_git_file(commit: str, path: str) -> str:
    return subprocess.check_output(
        ["git", "show", f"{commit}:{path}"],
        text=True,
    )


def _extract_function_body(text: str, signature: str) -> str:
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
                return text[brace_start + 1:index]

    raise AssertionError(f"Function body end not found: {signature}")


def _normalize_cpp_body(body: str) -> str:
    body = re.sub(r"//.*", "", body)
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL)
    body = re.sub(r"\s+", "", body)
    # Step 3: expand shared helpers to baseline inline form
    body = body.replace(
        "program_clear();",
        'for(intj=0;j<CAPACITY_NUM*2;j++){program[j].WType="";}ProgramLen=0;',
    )
    body = body.replace(
        "trim_line_end(line);",
        "strlen(line);while(lineLen>0&&(line[lineLen-1]=='\\r'||line[lineLen-1]==''||line[lineLen-1]=='\\t')){line[--lineLen]='\\0';}",
    )
    body = re.sub(
        r'program_fail\("([^"]+)"\);',
        r'for(intj=0;j<CAPACITY_NUM*2;j++)program[j].WType="";ProgramLen=0;SendMsg("\1",ALARM_MSG);',
        body,
    )
    return body


class RectProgramCodecBaselineParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.current_text = RECT_PROGRAM_CODEC_HEADER.read_text(encoding="utf-8")
        cls.baseline_text = _read_git_file(BASELINE_LOGIC_COMMIT, "logic.h")

    def test_rect_program_codec_header_exists(self) -> None:
        self.assertTrue(
            RECT_PROGRAM_CODEC_HEADER.exists(),
            "modes/rect/rect_program_codec.h must exist",
        )

    def test_set_program_matches_pre_extraction_baseline(self) -> None:
        current_body = _normalize_cpp_body(
            _extract_function_body(self.current_text, "void set_program(String WProgram)")
        )
        baseline_body = _normalize_cpp_body(
            _extract_function_body(self.baseline_text, "void set_program(String WProgram)")
        )
        self.assertEqual(current_body, baseline_body)

    def test_get_program_matches_pre_extraction_baseline(self) -> None:
        current_body = _normalize_cpp_body(
            _extract_function_body(self.current_text, "String get_program(uint8_t s)")
        )
        baseline_body = _normalize_cpp_body(
            _extract_function_body(self.baseline_text, "String get_program(uint8_t s)")
        )
        self.assertEqual(current_body, baseline_body)

    def test_set_program_keeps_mapping_tokens_to_program_fields(self) -> None:
        body = _extract_function_body(self.current_text, "void set_program(String WProgram)")
        normalized = _normalize_cpp_body(body)

        self.assertIn("char*tokType=strtok_r(line,\";\",&saveTok);", normalized)
        self.assertIn("char*tokVolume=strtok_r(NULL,\";\",&saveTok);", normalized)
        self.assertIn("char*tokSpeed=strtok_r(NULL,\";\",&saveTok);", normalized)
        self.assertIn("char*tokCap=strtok_r(NULL,\";\",&saveTok);", normalized)
        self.assertIn("char*tokTemp=strtok_r(NULL,\";\",&saveTok);", normalized)
        self.assertIn("char*tokPower=strtok_r(NULL,\";\",&saveTok);", normalized)

        self.assertIn("program[i].WType=tokType;", normalized)
        self.assertIn("program[i].Volume=(uint16_t)volume;", normalized)
        self.assertIn("program[i].Speed=speed;", normalized)
        self.assertIn("program[i].capacity_num=(uint8_t)cap;", normalized)
        self.assertIn("program[i].Temp=temp;", normalized)
        self.assertIn("program[i].Power=power;", normalized)

    def test_get_program_keeps_serialization_order_of_program_fields(self) -> None:
        body = _extract_function_body(self.current_text, "String get_program(uint8_t s)")
        normalized = _normalize_cpp_body(body)

        self.assertIn("Str+=program[i].WType+\";\";", normalized)
        self.assertIn("Str+=(String)program[i].Volume+\";\";", normalized)
        self.assertIn("Str+=(String)program[i].Speed+\";\";", normalized)
        self.assertIn("Str+=(String)program[i].capacity_num+\";\";", normalized)
        self.assertIn("Str+=(String)program[i].Temp+\";\";", normalized)
        self.assertIn("Str+=(String)program[i].Power+\"\\n\";", normalized)


if __name__ == "__main__":
    unittest.main()
