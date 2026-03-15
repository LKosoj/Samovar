from pathlib import Path
import re
import shutil
import subprocess
import unittest


DATA_DIR = Path("data")
SMOKE_RESULTS_DOC = Path("docs/refactoring/smoke_results.md")
INLINE_SCRIPT_PATTERN = re.compile(r"<script\b(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL)
TEMPLATE_PLACEHOLDER_PATTERN = re.compile(r"%[A-Za-z0-9_]+%")


class FinalSmokeArtifactsTest(unittest.TestCase):
    def test_inline_scripts_are_syntax_valid_after_template_substitution(self) -> None:
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node.js is required for frontend smoke syntax validation")

        failures = []
        for html_path in sorted(DATA_DIR.glob("*.htm")):
            text = html_path.read_text(encoding="utf-8", errors="ignore")
            for index, block in enumerate(INLINE_SCRIPT_PATTERN.findall(text), start=1):
                script = block.strip()
                if not script:
                    continue
                sanitized_script = TEMPLATE_PLACEHOLDER_PATTERN.sub("0", script)
                result = subprocess.run(
                    [
                        node,
                        "-e",
                        (
                            "try { new Function(process.argv[1]); } "
                            "catch (error) { console.error(error.message); process.exit(2); }"
                        ),
                        sanitized_script,
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode != 0:
                    failures.append(
                        f"{html_path.as_posix()}#{index}: "
                        f"{(result.stderr or result.stdout).strip()}"
                    )

        self.assertEqual(failures, [], f"Inline script syntax errors: {failures}")

    def test_smoke_results_doc_exists_with_required_sections(self) -> None:
        self.assertTrue(
            SMOKE_RESULTS_DOC.exists(),
            "docs/refactoring/smoke_results.md must be created",
        )

        text = SMOKE_RESULTS_DOC.read_text(encoding="utf-8")
        for snippet in [
            "# Финальные smoke-результаты",
            "## Сборка",
            "## Автоматизированные smoke-проверки",
            "## Ручные browser smoke-сценарии",
            "## Ограничения",
            "pio run",
            "playwright-cli",
            "index.htm",
            "setup.htm",
            "program.htm",
        ]:
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, text)


if __name__ == "__main__":
    unittest.main()
