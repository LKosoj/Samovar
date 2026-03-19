from pathlib import Path
import re
import subprocess
import unittest


BASELINE_SESSION_LOGS_COMMIT = "9e5e0d9478ac5bd7c3e3de5e30d3c149beeebe86"
SESSION_LOGS_HEADER = Path("storage/session_logs.h")
SERVER_INIT_HEADER = Path("ui/web/server_init.h")


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
    return body


class StorageSessionLogsBaselineParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.current_header = SESSION_LOGS_HEADER.read_text(encoding="utf-8")
        cls.current_server_init = SERVER_INIT_HEADER.read_text(encoding="utf-8")
        cls.baseline_fs = _read_git_file(BASELINE_SESSION_LOGS_COMMIT, "FS.ino")

    def test_create_data_keeps_program_log_and_file_structure(self) -> None:
        body = _normalize_cpp_body(
            _extract_function_body(self.current_header, "void create_data()")
        )
        self.assertIn('SPIFFS.open("/prg.csv",FILE_WRITE)', body)
        self.assertIn('get_program_for_mode(Samovar_Mode)', body)
        self.assertIn('filePrg.close();', body)
        self.assertIn('SPIFFS.rename("/data.csv","/data_old.csv");', body)
        self.assertIn('SPIFFS.open("/data.csv",FILE_WRITE)', body)
        self.assertIn('SPIFFS.open("/data.csv",FILE_APPEND)', body)
        self.assertIn('append_data();', body)

    def test_append_data_matches_pre_split_baseline(self) -> None:
        current_body = _normalize_cpp_body(
            _extract_function_body(self.current_header, "String append_data()")
        )
        baseline_body = _normalize_cpp_body(
            _extract_function_body(self.baseline_fs, "String append_data()")
        )
        self.assertEqual(current_body, baseline_body)

    def test_server_init_keeps_fs_initialization_before_route_registration(self) -> None:
        fs_init_pos = self.current_server_init.find("FS_init();")
        first_route_pos = self.current_server_init.find("server.on(")
        self.assertNotEqual(fs_init_pos, -1)
        self.assertNotEqual(first_route_pos, -1)
        self.assertLess(fs_init_pos, first_route_pos)


if __name__ == "__main__":
    unittest.main()
