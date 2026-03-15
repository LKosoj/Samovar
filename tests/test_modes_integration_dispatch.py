from pathlib import Path
import re
import unittest


LOOP_DISPATCH_PATH = Path("app/loop_dispatch.h")
STATUS_CODES_HEADER = Path("src/core/state/status_codes.h")
MODE_CODES_HEADER = Path("src/core/state/mode_codes.h")


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
    body = body.replace(
        "samovar_status_is_rectification(SamovarStatusInt)",
        "SamovarStatusInt > SAMOVAR_STATUS_OFF && SamovarStatusInt < SAMOVAR_STATUS_DISTILLATION",
    )
    constants_text = STATUS_CODES_HEADER.read_text(encoding="utf-8")
    matches = re.findall(
        r"static constexpr int16_t (SAMOVAR_STATUS_[A-Z0-9_]+) = (-?\d+);",
        constants_text,
    )
    for name, value in sorted(matches, key=lambda item: len(item[0]), reverse=True):
        body = body.replace(name, value)
    mode_constants_text = MODE_CODES_HEADER.read_text(encoding="utf-8")
    startval_matches = re.findall(
        r"static constexpr int16_t (SAMOVAR_STARTVAL_[A-Z0-9_]+) = (-?\d+);",
        mode_constants_text,
    )
    for name, value in sorted(startval_matches, key=lambda item: len(item[0]), reverse=True):
        body = body.replace(name, value)
    body = body.replace("SAMOVAR_COMMAND_NONE", "SAMOVAR_NONE")
    body = body.replace("SAMOVAR_COMMAND_RESET", "SAMOVAR_RESET")
    body = re.sub(r"\s+", "", body)
    return body


class ModeDispatchIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.loop_dispatch_text = LOOP_DISPATCH_PATH.read_text(encoding="utf-8")
        cls.process_body = _normalize_cpp_body(
            _extract_function_body(
                cls.loop_dispatch_text,
                "void process_sam_command_sync()",
            )
        )
        cls.dispatch_body = _normalize_cpp_body(
            _extract_function_body(
                cls.loop_dispatch_text,
                "void dispatch_samovar_mode_runtime()",
            )
        )

    def test_loop_dispatch_file_exists(self) -> None:
        self.assertTrue(LOOP_DISPATCH_PATH.exists())

    def test_loop_dispatch_includes_all_mode_runtime_modules(self) -> None:
        text = self.loop_dispatch_text
        self.assertIn('#include "modes/dist/dist_runtime.h"', text)
        self.assertIn('#include "modes/beer/beer_runtime.h"', text)
        self.assertIn('#include "modes/bk/bk_runtime.h"', text)
        self.assertIn('#include "modes/nbk/nbk_runtime.h"', text)
        self.assertIn('#include "modes/bk/bk_finish.h"', text)
        self.assertIn('#include "modes/nbk/nbk_finish.h"', text)

    def test_process_command_initializes_all_modes_with_unique_statuses(self) -> None:
        body = self.process_body

        expected_mode_init_fragments = [
            "caseSAMOVAR_DISTILLATION:Samovar_Mode=SAMOVAR_DISTILLATION_MODE;SamovarStatusInt=1000;startval=1000;break;",
            "caseSAMOVAR_BEER:Samovar_Mode=SAMOVAR_BEER_MODE;SamovarStatusInt=2000;startval=2000;break;",
            "caseSAMOVAR_BK:Samovar_Mode=SAMOVAR_BK_MODE;SamovarStatusInt=3000;startval=3000;break;",
            "caseSAMOVAR_NBK:Samovar_Mode=SAMOVAR_NBK_MODE;SamovarStatusInt=4000;startval=4000;break;",
        ]

        for fragment in expected_mode_init_fragments:
            self.assertIn(fragment, body)

    def test_process_command_power_branch_routes_to_correct_finishers(self) -> None:
        body = self.process_body

        expected_fragments = [
            "caseSAMOVAR_POWER:",
            "if(SamovarStatusInt==1000)distiller_finish();",
            "elseif(SamovarStatusInt==2000)beer_finish();",
            "elseif(SamovarStatusInt==3000)bk_finish();",
            "elseif(SamovarStatusInt==4000)nbk_finish();",
            "elseset_power(!PowerOn);",
        ]

        for fragment in expected_fragments:
            self.assertIn(fragment, body)

    def test_process_command_resets_command_queue_without_cross_mode_leaks(self) -> None:
        body = self.process_body
        self.assertIn("if(sam_command_sync!=SAMOVAR_RESET){sam_command_sync=SAMOVAR_NONE;}", body)

    def test_runtime_dispatch_routes_each_status_to_single_mode_runtime(self) -> None:
        body = self.dispatch_body

        expected_fragments = [
            "if(SamovarStatusInt>0&&SamovarStatusInt<1000){withdrawal();}",
            "elseif(SamovarStatusInt==1000){distiller_proc();}",
            "elseif(SamovarStatusInt==3000){bk_proc();}",
            "elseif(SamovarStatusInt==4000){nbk_proc();}",
            "elseif(SamovarStatusInt==2000&&startval==2000){beer_proc();}",
        ]

        for fragment in expected_fragments:
            self.assertIn(fragment, body)

    def test_runtime_dispatch_contains_unique_mode_targets(self) -> None:
        body = self.dispatch_body
        self.assertEqual(len(re.findall(r"distiller_proc\(\);", body)), 1)
        self.assertEqual(len(re.findall(r"beer_proc\(\);", body)), 1)
        self.assertEqual(len(re.findall(r"(?<!n)bk_proc\(\);", body)), 1)
        self.assertEqual(len(re.findall(r"nbk_proc\(\);", body)), 1)


if __name__ == "__main__":
    unittest.main()
