from pathlib import Path
import unittest


CONTRACTS_DOC = Path("docs/refactoring/contracts.md")


class ContractsDocTest(unittest.TestCase):
    def test_contracts_doc_exists(self) -> None:
        self.assertTrue(CONTRACTS_DOC.exists(), "contracts.md must exist")

    def test_contracts_doc_has_required_sections(self) -> None:
        text = CONTRACTS_DOC.read_text(encoding="utf-8")

        required_sections = [
            "# Baseline contracts",
            "## HTTP endpoints",
            "## /ajax JSON keys",
            "## Lua API names",
            "## NVS namespaces and keys",
            "## Status codes",
            "## Program string formats",
        ]

        for section in required_sections:
            with self.subTest(section=section):
                self.assertIn(section, text)

    def test_contracts_doc_mentions_representative_contract_items(self) -> None:
        text = CONTRACTS_DOC.read_text(encoding="utf-8")

        required_tokens = [
            "/ajax",
            "/command",
            "/program",
            "/save",
            "setPower",
            "getState",
            "i2cpump_start",
            "sam_rect",
            "sam_meta",
            "TimeZone",
            "SetSteam",
            "SteamDelay",
            "ColDiam",
            "1000",
            "2000",
            "4000",
            "type;volume;speed;capacity;temp;power",
            "type;speed;capacity;power",
            "type;temp;time;device^speed^on^off;sensor",
            "type;speed;power",
        ]

        for token in required_tokens:
            with self.subTest(token=token):
                self.assertIn(token, text)


if __name__ == "__main__":
    unittest.main()
