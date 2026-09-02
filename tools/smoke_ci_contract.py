#!/usr/bin/env python3
import argparse
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
import yaml
from pathlib import Path
from unittest.mock import patch

import run_cppcheck
import run_smoke_tests as smoke_runner
from run_cppcheck import (
    MANIFEST_PATH,
    ManifestError,
    cppcheck_command,
    discover_root_sources,
    load_manifest,
    validate_manifest,
)
from run_smoke_tests import discover_smoke_tests, run_smoke_tests

ROOT = Path(__file__).resolve().parents[1]


def manifest(inventory: list[str], excluded: dict[str, str]) -> dict[str, object]:
    return {
        "inventory": inventory,
        "excluded": excluded,
    }


def write_manifest(path: Path, data: dict[str, object]) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


class SmokeRunnerTests(unittest.TestCase):
    def test_runs_every_script_in_name_order_and_aggregates_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tools = root / "tools"
            tools.mkdir()
            marker = root / "order.txt"
            for name, exit_code in (("smoke_z.py", 0), ("smoke_a.py", 0), ("smoke_m.py", 7)):
                (tools / name).write_text(
                    "from pathlib import Path\n"
                    f"path = Path({str(marker)!r})\n"
                    f"previous = path.read_text() if path.exists() else ''\n"
                    f"path.write_text(previous + {name!r} + '\\n')\n"
                    f"raise SystemExit({exit_code})\n",
                    encoding="utf-8",
                )

            tests = discover_smoke_tests(root)
            output = io.StringIO()
            returncode = run_smoke_tests(tests, root, output, timeout_seconds=2)

            self.assertEqual([path.name for path in tests], ["smoke_a.py", "smoke_m.py", "smoke_z.py"])
            self.assertEqual(marker.read_text(encoding="utf-8").splitlines(), ["smoke_a.py", "smoke_m.py", "smoke_z.py"])
            self.assertEqual(returncode, 1)
            self.assertIn("Smoke summary: 2 passed, 1 failed", output.getvalue())
            self.assertIn("tools/smoke_m.py", output.getvalue())

    def test_empty_discovery_is_an_error(self) -> None:
        output = io.StringIO()
        self.assertEqual(run_smoke_tests([], ROOT, output, timeout_seconds=2), 1)
        self.assertIn("no tools/smoke_*.py files found", output.getvalue())

    def test_subprocess_oserror_is_reported_and_runner_continues(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tools = root / "tools"
            tools.mkdir()
            first = tools / "smoke_a.py"
            second = tools / "smoke_b.py"
            first.write_text("", encoding="utf-8")
            second.write_text("", encoding="utf-8")
            output = io.StringIO()

            with patch.object(
                smoke_runner.subprocess,
                "run",
                side_effect=[
                    OSError("interpreter unavailable"),
                    subprocess.CompletedProcess([], 0, stdout="second executed\n"),
                ],
            ) as process:
                returncode = run_smoke_tests([first, second], root, output, timeout_seconds=2)

            self.assertEqual(process.call_count, 2)
            self.assertEqual(returncode, 1)
            self.assertIn("FAIL (could not start: interpreter unavailable)", output.getvalue())
            self.assertIn("second executed", output.getvalue())
            self.assertIn("Smoke summary: 1 passed, 1 failed", output.getvalue())

    def test_timeout_is_reported_and_next_smoke_still_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tools = root / "tools"
            tools.mkdir()
            marker = root / "order.txt"
            (tools / "smoke_a_timeout.py").write_text(
                "from pathlib import Path\n"
                "import time\n"
                f"with Path({str(marker)!r}).open('a') as stream:\n"
                "    stream.write('timeout\\n')\n"
                "print('partial timeout output', flush=True)\n"
                "time.sleep(2)\n",
                encoding="utf-8",
            )
            (tools / "smoke_b_after.py").write_text(
                "from pathlib import Path\n"
                f"with Path({str(marker)!r}).open('a') as stream:\n"
                "    stream.write('after\\n')\n"
                "print('after executed')\n",
                encoding="utf-8",
            )
            output = io.StringIO()

            returncode = run_smoke_tests(
                discover_smoke_tests(root),
                root,
                output,
                timeout_seconds=0.5,
            )

            self.assertEqual(returncode, 1)
            self.assertEqual(marker.read_text(encoding="utf-8").splitlines(), ["timeout", "after"])
            self.assertIn("partial timeout output", output.getvalue())
            self.assertIn("FAIL (timed out after 0.5 seconds)", output.getvalue())
            self.assertIn("after executed", output.getvalue())
            self.assertIn("Smoke summary: 1 passed, 1 failed", output.getvalue())

    def test_timeout_argument_must_be_positive(self) -> None:
        self.assertEqual(smoke_runner.positive_timeout("0.5"), 0.5)
        for value in ("0", "nan", "inf", "-inf"):
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    smoke_runner.positive_timeout(value)


class StaticAnalysisManifestTests(unittest.TestCase):
    def test_repository_inventory_is_complete_and_only_ino_units_reach_cppcheck(self) -> None:
        data = load_manifest(MANIFEST_PATH)
        analysis_units = validate_manifest(ROOT, data)
        command = cppcheck_command(analysis_units, force=False)

        self.assertEqual(data["inventory"], discover_root_sources(ROOT))
        self.assertTrue(analysis_units)
        self.assertTrue(set(analysis_units).issubset(set(data["inventory"])))
        self.assertTrue(all(Path(name).suffix == ".ino" for name in analysis_units))
        self.assertFalse(any(Path(name).suffix == ".h" for name in command))
        self.assertEqual(command[-len(analysis_units):], analysis_units)
        self.assertNotIn("--force", command)
        self.assertIn("--force", cppcheck_command(analysis_units, force=True))

    def test_new_root_header_must_be_in_inventory_but_nested_vendor_source_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "app.ino").write_text("void setup() {}\n", encoding="utf-8")
            (root / "generated.h").write_text("", encoding="utf-8")
            vendor = root / "libraries"
            vendor.mkdir()
            (vendor / "vendor.h").write_text("", encoding="utf-8")
            data = manifest(
                ["app.ino", "generated.h"],
                {"generated.h": "generated fixture"},
            )
            self.assertEqual(validate_manifest(root, data), ["app.ino"])

            (root / "focused.h").write_text("", encoding="utf-8")
            with self.assertRaisesRegex(ManifestError, "undeclared root firmware sources: focused.h"):
                validate_manifest(root, data)

    def test_all_inventory_ino_files_are_derived_as_analysis_units(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for name in ("app.ino", "extra.ino", "focused.h"):
                (root / name).write_text("", encoding="utf-8")
            inventory = ["app.ino", "extra.ino", "focused.h"]
            self.assertEqual(validate_manifest(root, manifest(inventory, {})), ["app.ino", "extra.ino"])

    def test_inventory_without_ino_analysis_units_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "focused.h").write_text("", encoding="utf-8")
            with self.assertRaisesRegex(ManifestError, "at least one \\.ino analysis unit"):
                validate_manifest(root, manifest(["focused.h"], {}))

    def test_exclusions_require_reasons_and_inventory_membership(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "app.ino").write_text("", encoding="utf-8")
            (root / "generated.h").write_text("", encoding="utf-8")
            inventory = ["app.ino", "generated.h"]
            with self.assertRaisesRegex(ManifestError, "non-empty reasons"):
                validate_manifest(root, manifest(inventory, {"generated.h": ""}))
            with self.assertRaisesRegex(ManifestError, "excluded files missing from inventory"):
                validate_manifest(root, manifest(inventory, {"missing.h": "fixture"}))
            with self.assertRaisesRegex(ManifestError, "root \\.ino files cannot be excluded"):
                validate_manifest(root, manifest(inventory, {"app.ino": "fixture"}))

    def test_malformed_json_and_non_object_root_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "manifest.json"
            path.write_text("{", encoding="utf-8")
            with self.assertRaisesRegex(ManifestError, "cannot read"):
                load_manifest(path)

            path.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ManifestError, "root must be an object"):
                load_manifest(path)

    def test_manifest_schema_rejects_missing_and_extra_sections(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "app.ino").write_text("", encoding="utf-8")
            invalid_manifests = (
                {"inventory": ["app.ino"]},
                {
                    "inventory": ["app.ino"],
                    "analysis_units": ["app.ino"],
                    "excluded": {},
                },
            )
            for data in invalid_manifests:
                with self.subTest(data=data):
                    with self.assertRaisesRegex(ManifestError, "must contain only"):
                        validate_manifest(root, data)

    def test_inventory_must_be_sorted_unique_valid_and_complete(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "app.ino").write_text("", encoding="utf-8")
            (root / "focused.h").write_text("", encoding="utf-8")

            with self.assertRaisesRegex(ManifestError, "unique and sorted"):
                validate_manifest(root, manifest(["app.ino", "app.ino"], {}))
            with self.assertRaisesRegex(ManifestError, "unique and sorted"):
                validate_manifest(root, manifest(["focused.h", "app.ino"], {}))
            with self.assertRaisesRegex(ManifestError, "invalid root source names"):
                validate_manifest(root, manifest(["app.ino", "nested/focused.h"], {}))
            with self.assertRaisesRegex(ManifestError, "inventory files not found: missing.h"):
                validate_manifest(root, manifest(["app.ino", "focused.h", "missing.h"], {}))

    def test_explicit_generated_exclusions_are_inventory_only(self) -> None:
        data = load_manifest(MANIFEST_PATH)
        analysis_units = validate_manifest(ROOT, data)
        self.assertIn("font.h", data["inventory"])
        self.assertIn("font.h", data["excluded"])
        self.assertNotIn("font.h", analysis_units)


class StaticAnalysisRunnerTests(unittest.TestCase):
    def test_report_is_written_when_cppcheck_reports_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest_path = root / "manifest.json"
            report_path = root / "reports" / "cppcheck.txt"
            (root / "app.ino").write_text("", encoding="utf-8")
            write_manifest(manifest_path, manifest(["app.ino"], {}))
            completed = subprocess.CompletedProcess([], 1, stdout="", stderr="app.ino:1: warning\n")

            with (
                patch.object(run_cppcheck, "ROOT", root),
                patch.object(run_cppcheck, "MANIFEST_PATH", manifest_path),
                patch.object(run_cppcheck.subprocess, "run", return_value=completed),
                patch.object(sys, "argv", ["run_cppcheck.py", "--timeout", "10", "--report", str(report_path)]),
                contextlib.redirect_stdout(io.StringIO()) as stdout,
                contextlib.redirect_stderr(io.StringIO()),
            ):
                returncode = run_cppcheck.main()

            self.assertEqual(returncode, 1)
            self.assertIn("Cppcheck command:", stdout.getvalue())
            report = report_path.read_text(encoding="utf-8")
            self.assertIn("Sources: 1", report)
            self.assertIn("Timeout: 10 seconds", report)
            self.assertIn("Timed out: no", report)
            self.assertIn("Exit code: 1", report)
            self.assertIn("app.ino:1: warning", report)

    def test_report_is_written_when_manifest_is_malformed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest_path = root / "manifest.json"
            report_path = root / "cppcheck.txt"
            manifest_path.write_text("{", encoding="utf-8")

            with (
                patch.object(run_cppcheck, "ROOT", root),
                patch.object(run_cppcheck, "MANIFEST_PATH", manifest_path),
                patch.object(run_cppcheck.subprocess, "run") as process,
                patch.object(sys, "argv", ["run_cppcheck.py", "--timeout", "10", "--report", str(report_path)]),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                returncode = run_cppcheck.main()

            self.assertEqual(returncode, 2)
            process.assert_not_called()
            report = report_path.read_text(encoding="utf-8")
            self.assertIn("Timeout: 10 seconds", report)
            self.assertIn("Timed out: no", report)
            self.assertIn("Exit code: 2", report)
            self.assertIn("cannot read", report)

    def test_report_is_written_when_cppcheck_cannot_start(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest_path = root / "manifest.json"
            report_path = root / "cppcheck.txt"
            (root / "app.ino").write_text("", encoding="utf-8")
            write_manifest(manifest_path, manifest(["app.ino"], {}))

            with (
                patch.object(run_cppcheck, "ROOT", root),
                patch.object(run_cppcheck, "MANIFEST_PATH", manifest_path),
                patch.object(run_cppcheck.subprocess, "run", side_effect=OSError("cppcheck unavailable")),
                patch.object(sys, "argv", ["run_cppcheck.py", "--timeout", "10", "--report", str(report_path)]),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                returncode = run_cppcheck.main()

            self.assertEqual(returncode, 2)
            report = report_path.read_text(encoding="utf-8")
            self.assertIn("Timed out: no", report)
            self.assertIn("cppcheck unavailable", report)

    def test_timeout_returns_124_and_report_keeps_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest_path = root / "manifest.json"
            report_path = root / "cppcheck.txt"
            (root / "app.ino").write_text("", encoding="utf-8")
            write_manifest(manifest_path, manifest(["app.ino"], {}))
            timeout = subprocess.TimeoutExpired(
                ["cppcheck", "app.ino"],
                0.25,
                output=b"partial stdout\n",
                stderr=b"partial stderr\n",
            )

            with (
                patch.object(run_cppcheck, "ROOT", root),
                patch.object(run_cppcheck, "MANIFEST_PATH", manifest_path),
                patch.object(run_cppcheck.subprocess, "run", side_effect=timeout) as process,
                patch.object(sys, "argv", ["run_cppcheck.py", "--timeout", "0.25", "--report", str(report_path)]),
                contextlib.redirect_stdout(io.StringIO()) as stdout,
                contextlib.redirect_stderr(io.StringIO()) as stderr,
            ):
                returncode = run_cppcheck.main()

            self.assertEqual(returncode, 124)
            self.assertEqual(process.call_args.kwargs["timeout"], 0.25)
            self.assertIn("Cppcheck command:", stdout.getvalue())
            self.assertIn("partial stdout", stdout.getvalue())
            self.assertIn("cppcheck timed out after 0.25 seconds", stderr.getvalue())
            report = report_path.read_text(encoding="utf-8")
            self.assertIn("Timeout: 0.25 seconds", report)
            self.assertIn("Timed out: yes", report)
            self.assertIn("Exit code: 124", report)
            self.assertIn("partial stdout", report)
            self.assertIn("partial stderr", report)
            self.assertIn("cppcheck timed out after 0.25 seconds", report)

    def test_timeout_argument_must_be_positive(self) -> None:
        self.assertEqual(run_cppcheck.positive_timeout("0.5"), 0.5)
        for value in ("0", "nan", "inf", "-inf"):
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    run_cppcheck.positive_timeout(value)


class WorkflowContractTests(unittest.TestCase):
    def test_ci_uses_bounded_shared_runners_and_always_uploads_extended_report(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "firmware-ci.yml").read_text(encoding="utf-8")
        blocking = self._job_block(workflow, "static-analysis")
        smoke = self._job_block(workflow, "smoke")
        self.assertEqual(workflow.count("python tools/run_smoke_tests.py"), 1)
        self.assertIn("run: python tools/run_cppcheck.py --timeout 300", blocking)
        self.assertNotIn("--force", blocking)
        self.assertNotIn("continue-on-error", blocking)
        self.assertIn("run: python tools/run_smoke_tests.py --timeout 60", smoke)

    def test_extended_cppcheck_is_baseline_gated_not_ignored(self) -> None:
        # Раньше этот job был помечен `continue-on-error: true` и не мог упасть вообще:
        # находки уезжали только в артефакт, который никто не обязан открывать. Теперь
        # он падает по-настоящему, но только на находках, которых нет в
        # tools/cppcheck_force_baseline.txt (осознанное решение, а не немота).
        workflow = (ROOT / ".github" / "workflows" / "firmware-ci.yml").read_text(encoding="utf-8")
        extended = self._job_block(workflow, "static-analysis-force")
        self.assertNotIn("continue-on-error", extended)
        self.assertNotIn("continue-on-error", workflow)
        self.assertIn(
            # 600 -> 900: замер 2026-08-23 показал ~334с в один поток на всех 8 .ino-юнитов
            # (600 давало только ~1.8x запаса); 900 закладывает ~2.7x запас на более медленный/
            # менее многоядерный раннер CI. Это не ослабление проверки - порог находок в baseline
            # не менялся, только бюджет времени под измеренную длительность.
            "run: python tools/check_cppcheck_baseline.py --timeout 900 --report cppcheck-extended.txt",
            extended,
        )
        upload = extended[extended.index("- name: Upload extended cppcheck report") :]
        self.assertIn("if: always()", upload)
        self.assertIn("uses: actions/upload-artifact@v4", upload)
        self.assertIn("path: cppcheck-extended.txt", upload)
        self.assertIn("if-no-files-found: error", upload)
        self.assertTrue((ROOT / "tools" / "cppcheck_force_baseline.txt").exists())

    def test_ci_verifies_stepper_isr_iram_for_every_build_matrix_environment(self) -> None:
        # check_stepper_isr_iram.py раньше не вызывался ни одним job'ом и брал список
        # окружений из того, что случайно лежит в .pio/build - собрали одно, проверили
        # одно, сказали "OK". Теперь он вызывается внутри job'а build с явным именем
        # окружения текущей ячейки матрицы, поэтому покрытие не может молча просесть:
        # если окружение уйдёт из матрицы сборки, вместе с ним пропадёт и его сборка.
        workflow = (ROOT / ".github" / "workflows" / "firmware-ci.yml").read_text(encoding="utf-8")
        build = self._job_block(workflow, "build")
        self.assertIn(
            "run: python tools/check_stepper_isr_iram.py ${{ matrix.env_name }}",
            build,
        )
        build_step_index = build.index("run: python -m platformio run -e ${{ matrix.env_name }}")
        isr_step_index = build.index("run: python tools/check_stepper_isr_iram.py ${{ matrix.env_name }}")
        self.assertLess(build_step_index, isr_step_index, "ISR-проверка должна идти после сборки")

    def test_ci_runs_real_browser_ui_tests_not_just_source_text_gates(self) -> None:
        # 11 файлов tools/test_*_browser.py раньше не запускал ни один сценарий CI - их
        # подменяли smoke_*.py-проверки, ищущие строки-маркеры в исходнике самого теста.
        # Такой "гейт" остаётся зелёным, даже если браузерный тест падает на первом шаге.
        #
        # Раньше эта проверка сама была таким же "гейтом": искала слово "playwright" в
        # тексте всего job'а, а оно там есть всегда - хотя бы в имени job'а
        # ("Browser UI tests (Playwright)"), даже если шаг установки браузера убрать
        # целиком. Теперь она разбирает YAML по структуре (список шагов job'а и их
        # команды), а не ищет слова в сыром тексте.
        with (ROOT / ".github" / "workflows" / "firmware-ci.yml").open(encoding="utf-8") as stream:
            workflow = yaml.safe_load(stream)
        job = workflow["jobs"]["browser-ui"]
        steps = job["steps"]

        self.assertNotIn("continue-on-error", job, "пометка 'не ронять сборку' на уровне job'а недопустима")
        for step in steps:
            self.assertNotIn(
                "continue-on-error",
                step,
                f"шаг {step.get('name')!r} не должен быть помечен continue-on-error",
            )

        run_commands = [step["run"] for step in steps if "run" in step]
        install_commands = [command for command in run_commands if "playwright install" in command]
        self.assertTrue(install_commands, "не найден шаг, устанавливающий браузер Playwright")

        test_commands = [
            command for command in run_commands if command == "python tools/run_browser_tests.py --timeout 240"
        ]
        self.assertEqual(
            len(test_commands),
            1,
            "не найден (или изменён) шаг, реально запускающий tools/run_browser_tests.py",
        )

        install_index = run_commands.index(install_commands[0])
        test_index = run_commands.index(test_commands[0])
        self.assertLess(install_index, test_index, "браузер должен ставиться раньше, чем запускаются тесты")

    @staticmethod
    def _job_block(workflow: str, job_name: str) -> str:
        lines = workflow.splitlines()
        start = lines.index(f"  {job_name}:")
        end = len(lines)
        for index in range(start + 1, len(lines)):
            line = lines[index]
            if line.startswith("  ") and not line.startswith("    ") and line.endswith(":"):
                end = index
                break
        return "\n".join(lines[start:end])


class FirmwareDefaultsContractTests(unittest.TestCase):
    def test_setup_defaults_use_cxx11_value_initialization(self) -> None:
        source = (ROOT / "NVS_Manager.ino").read_text(encoding="utf-8")
        start = source.index("void set_default_setup_profile(SetupEEPROM& candidate)")
        end = source.index("\nPersistResult save_profile_nvs", start + 1)
        function = source[start:end]
        self.assertIn("candidate = {};", function)
        self.assertNotIn("memset(&candidate", function)
        self.assertIn("--std=c++11", cppcheck_command(["NVS_Manager.ino"], force=False))


class BrowserTestRunnerTests(unittest.TestCase):
    def test_discovers_every_known_browser_test_file(self) -> None:
        import run_browser_tests

        discovered = {path.name for path in run_browser_tests.discover_browser_tests(ROOT)}
        # Зафиксированный на 2026-08-24 список - если файл переименуют/удалят из tools/,
        # тест должен покраснеть, а не молча перестать его запускать.
        expected = {
            "test_accessibility_ui_browser.py",
            # 02.09.2026: пакет "Пиво" - кнопка паузы на beer.htm и импорт рецепта brewxml.htm.
            "test_beer_pause_button_browser.py",
            "test_brewxml_recipe_browser.py",
            "test_i2c_operation_results_browser.py",
            "test_i2c_pump_ui_browser.py",
            "test_mode_logic_ui_browser.py",
            "test_numeric_input_ui_browser.py",
            "test_profile_operation_ui_browser.py",
            "test_program_clear_ui_browser.py",
            "test_program_device_import_browser.py",
            "test_program_file_validation_browser.py",
            "test_program_flood_power_recommendations_browser.py",
            "test_program_focus_redraw_browser.py",
            "test_program_percent_input_browser.py",
            "test_program_calc_browser.py",
            "test_rect_start_stability_confirm_browser.py",
            "test_runtime_event_ui_browser.py",
            "test_setup_guards_browser.py",
            "test_setup_mode_hidden_selected_browser.py",
            "test_shared_ui_controllers_browser.py",
            "test_stale_telemetry_dimming_browser.py",
            "test_u03_contrast_browser.py",
            "test_u04_responsive_layout_browser.py",
        }
        self.assertEqual(discovered, expected)


class StepperIsrCliTests(unittest.TestCase):
    def test_environments_argument_is_required_not_defaulted_from_build_dir(self) -> None:
        result = subprocess.run(
            [sys.executable, "tools/check_stepper_isr_iram.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("required", result.stderr)

    def test_unbuilt_environment_fails_loudly_instead_of_being_silently_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            import check_stepper_isr_iram as stepper_check

            with patch.object(stepper_check, "BUILD_DIR", root / ".pio" / "build"):
                ok, message = stepper_check.check_env("NoSuchEnvironment")
            self.assertFalse(ok)
            self.assertIn("не найден", message)
            self.assertIn("не собрано", message)


class CppcheckBaselineTests(unittest.TestCase):
    def test_parse_findings_extracts_only_real_finding_lines(self) -> None:
        import check_cppcheck_baseline as baseline_check

        stdout = "\n".join([
            "Checking Samovar.ino: SAMOVAR_USE_BLYNK;ESP32...",
            "5/8 files checked 62% done",
            "Samovar.h:120:3: warning: Variable 'x' is assigned a value that is never used [unreadVariable]",
            "lua.h:42:1: information: Include file not found [missingInclude]",
        ])
        findings = baseline_check.parse_findings(stdout)
        self.assertEqual(
            findings,
            [
                "Samovar.h:120:3: warning: Variable 'x' is assigned a value that is never used [unreadVariable]",
                "lua.h:42:1: information: Include file not found [missingInclude]",
            ],
        )

    def test_only_findings_outside_baseline_are_new(self) -> None:
        import check_cppcheck_baseline as baseline_check

        with tempfile.TemporaryDirectory() as temp_dir:
            baseline_path = Path(temp_dir) / "baseline.txt"
            baseline_path.write_text(
                "# comment\nSamovar.h:1:1: style: known [knownId]\n", encoding="utf-8",
            )
            with patch.object(baseline_check, "BASELINE_PATH", baseline_path):
                baseline = baseline_check.load_baseline(baseline_check.BASELINE_PATH)
            self.assertEqual(baseline, {"Samovar.h:1:1: style: known [knownId]"})
            findings = [
                "Samovar.h:1:1: style: known [knownId]",
                "lua.h:2:2: warning: brand new [newId]",
            ]
            new_findings = sorted(set(findings) - baseline)
            self.assertEqual(new_findings, ["lua.h:2:2: warning: brand new [newId]"])


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(__import__(__name__)))
    raise SystemExit(0 if result.wasSuccessful() else 1)
