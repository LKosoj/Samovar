#!/usr/bin/env python3
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLATFORMIO_INI = ROOT / "platformio.ini"
FIRMWARE_WORKFLOW = ROOT / ".github" / "workflows" / "firmware-ci.yml"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "build_release.yml"
HELPER = ROOT / "tools" / "build_metadata.py"

PLATFORM_COMMIT = "3c076807e1f55b90799b50b946e76a0508e97778"
PLATFORM_URL = f"https://github.com/platformio/platform-espressif32.git#{PLATFORM_COMMIT}"
PACKAGE_SPECS = (
    "platformio/framework-arduinoespressif32 @ 3.20017.241212+sha.dcc1105b",
    "platformio/tool-esptoolpy @ 2.40900.250804",
    "platformio/tool-mkfatfs @ 2.0.1",
    "platformio/tool-mklittlefs @ 1.203.210628",
    "platformio/tool-mkspiffs @ 2.230.0",
)
PARTITION_TOOL = (
    "tool-esp32partitiontool @ "
    "https://github.com/serifpersia/esp32partitiontool/releases/download/"
    "v1.4.4/esp32partitiontool-platformio.zip"
)
BUILD_PATH_MAPS = (
    "-ffile-prefix-map=${platformio.packages_dir}=.platformio/packages",
    "-fdebug-prefix-map=${platformio.src_dir}=.",
)
ENVIRONMENTS = (
    "Samovar",
    "Samovar_s3",
    "Samovar_no_power",
    "Samovar_rmvk",
    "Samovar_sem",
    "Samovar_lua_mqtt",
    "Samovar_alarm_button",
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def job_section(workflow: str, name: str) -> str:
    jobs = workflow.index("jobs:\n") + len("jobs:\n")
    match = re.search(rf"^  {re.escape(name)}:\s*$", workflow[jobs:], re.MULTILINE)
    if not match:
        return ""
    start = jobs + match.start()
    next_job = re.search(r"^  [A-Za-z0-9_-]+:\s*$", workflow[start + 1 :], re.MULTILINE)
    return workflow[start:] if not next_job else workflow[start : start + 1 + next_job.start()]


def job_names(workflow: str) -> list[str]:
    jobs = workflow.index("jobs:\n") + len("jobs:\n")
    return re.findall(r"^  ([A-Za-z0-9_-]+):\s*$", workflow[jobs:], re.MULTILINE)


class BuildConfigurationContract(unittest.TestCase):
    def test_exact_platform_and_package_pins(self) -> None:
        text = read(PLATFORMIO_INI)
        errors: list[str] = []
        if f"platform = {PLATFORM_URL}" not in text:
            errors.append("Espressif platform is not pinned to the approved 40-hex commit")
        for spec in PACKAGE_SPECS:
            if text.count(spec) != 1:
                errors.append(f"missing exact platform package override: {spec}")
        if text.count(PARTITION_TOOL) != 1:
            errors.append("existing v1.4.4 partition-tool URL changed or duplicated")
        for toolchain in (
            "toolchain-xtensa-esp32",
            "toolchain-xtensa-esp32s3",
            "toolchain-riscv32-esp",
        ):
            if toolchain in text:
                errors.append(f"toolchain override is out of scope: {toolchain}")
        if "extra_scripts" in text:
            errors.append("PlatformIO pre/extra script is out of scope")
        base_match = re.search(
            r"^\[env:Samovar\][ \t]*$(.*?)(?=^\[[^]\r\n]+\][ \t]*$|\Z)",
            text,
            re.MULTILINE | re.DOTALL,
        )
        base_section = "" if base_match is None else base_match.group(1)
        active_base_section = "\n".join(
            line for line in base_section.splitlines() if not line.lstrip().startswith((";", "#"))
        )
        path_maps = re.findall(r"(?<!\S)-f(?:file|debug|macro)-prefix-map=\S+", active_base_section)
        if path_maps != list(BUILD_PATH_MAPS):
            errors.append(
                "[env:Samovar] path maps must be exactly the ordered file/debug pair; "
                "standalone macro-prefix-map is forbidden"
            )
        for forbidden in ("-frandom-seed", "--build-id", "post:"):
            if forbidden in active_base_section:
                errors.append(f"out-of-scope reproducibility mechanism: {forbidden}")
        self.assertEqual(errors, [], "\n" + "\n".join(errors))


class WorkflowContract(unittest.TestCase):
    def test_existing_workflow_topology_and_reproducible_metadata_flow(self) -> None:
        firmware = read(FIRMWARE_WORKFLOW)
        release = read(RELEASE_WORKFLOW)
        firmware_build = job_section(firmware, "build")
        release_build = job_section(release, "build")
        errors: list[str] = []

        if job_names(firmware) != ["build", "static-analysis", "static-analysis-force", "smoke"]:
            errors.append("firmware CI job topology changed")
        if job_names(release) != ["build", "release"]:
            errors.append("release job topology changed")
        for marker in ('branches: ["master", "main"]', "tags:\n      - '*'", "branches: [master]"):
            if marker not in firmware + release:
                errors.append(f"existing workflow trigger missing: {marker!r}")
        if "retention-days: 1" not in release_build:
            errors.append("release artifact retention changed")
        if 'artifacts: "firmware/**/*.bin"' not in release:
            errors.append("release .bin glob changed")

        if tuple(re.findall(r"^          - (Samovar[^\s]*)$", firmware_build, re.MULTILINE)) != ENVIRONMENTS:
            errors.append("firmware CI seven-environment matrix changed")
        if "default_envs = Samovar" not in read(PLATFORMIO_INI):
            errors.append("default PlatformIO environment changed")

        for label, section in (("firmware CI", firmware_build), ("release", release_build)):
            if not re.search(r"python-version:\s*['\"]3\.12['\"]", section):
                errors.append(f"{label} does not use Python 3.12")
            if "python -m pip install platformio==6.1.19" not in section:
                errors.append(f"{label} does not install exact PlatformIO 6.1.19")
            if "--upgrade" in section:
                errors.append(f"{label} still upgrades build tooling")
            if "python -m platformio pkg install --global --no-save --tool platformio/tool-scons@4.40801.0" not in section:
                errors.append(f"{label} does not install exact PlatformIO tool-scons 4.40801.0")
            if not re.search(r"git show -s --format=%ct \\?[\"']?\$GITHUB_SHA", section):
                errors.append(f"{label} does not derive SOURCE_DATE_EPOCH from GITHUB_SHA")
            if "python -m platformio run" not in section:
                errors.append(f"{label} does not invoke PlatformIO through the selected Python")
            if re.search(r"(?<!-m )\bplatformio run\b|(?<!platformio )\bpio run\b", section):
                errors.append(f"{label} retains a non-python PlatformIO build command")
            if "tools/build_metadata.py" not in section:
                errors.append(f"{label} does not generate build metadata")
            if "python -m json.tool" not in section:
                errors.append(f"{label} does not validate generated metadata")
            positions = [
                section.find("SOURCE_DATE_EPOCH="),
                section.find("python -m platformio run"),
                section.find("tools/build_metadata.py"),
            ]
            if any(position < 0 for position in positions) or positions != sorted(positions):
                errors.append(f"{label} epoch/build/metadata ordering is invalid")
            for argument in (
                "--project-root",
                "--core-dir",
                "--environment",
                "--firmware",
                "--map",
                "--git-sha",
                "--dirty",
                "--source-date-epoch",
                "--output",
            ):
                if argument not in section:
                    errors.append(f"{label} metadata call misses {argument}")

        if "actions/upload-artifact" in firmware_build:
            errors.append("firmware matrix gained an artifact upload")
        for artifact in (
            ".pio/build/Samovar/firmware.bin",
            ".pio/build/Samovar/firmware.map",
            ".pio/build/Samovar/build-metadata.json",
        ):
            if artifact not in release_build:
                errors.append(f"release Archive misses {artifact}")
        if "FIRMWARE_VERSION=${{github.ref_name}}" not in release_build:
            errors.append("release FIRMWARE_VERSION contract changed")

        self.assertEqual(errors, [], "\n" + "\n".join(errors))


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def make_fixture(root: Path, reverse: bool = False) -> dict[str, Path]:
    project = root / "project"
    core = root / "core"
    paths = [
        project / "libraries" / "Example" / "src",
        core / "platforms" / "espressif32" / ".git",
        core / "packages" / "tool-esptoolpy" / "_contrib" / "bin",
        core / "packages" / "tool-esptoolpy" / "_contrib" / "cffi-2.1.0.dist-info",
        core / "packages" / "tool-scons" / "_contrib" / "bin",
        core / "packages" / "tool-scons" / "_contrib" / "cffi-2.1.0.dist-info",
    ]
    for path in reversed(paths) if reverse else paths:
        path.mkdir(parents=True, exist_ok=True)

    (project / "platformio.ini").write_text("[platformio]\ndefault_envs = Samovar\n", encoding="utf-8")
    (project / "user_config_override.h").write_text("SECRET_FIXTURE_VALUE\n", encoding="utf-8")
    write_json(
        project / "libraries" / "Example" / "library.json",
        {"name": "Example", "version": "1.2.3", "repository": {"url": "https://example.invalid/lib"}},
    )
    (project / "libraries" / "Example" / "src" / "example.h").write_text("#define VALUE 1\n", encoding="utf-8")

    write_json(
        core / "platforms" / "espressif32" / "platform.json",
        {
            "name": "espressif32",
            "version": "6.12.0",
            "repository": {"url": "https://github.com/platformio/platform-espressif32.git"},
        },
    )
    (core / "platforms" / "espressif32" / ".git" / "HEAD").write_text(PLATFORM_COMMIT + "\n", encoding="ascii")
    write_json(
        core / "packages" / "tool-esptoolpy" / "package.json",
        {
            "name": "tool-esptoolpy",
            "version": "2.40900.250804",
            "repository": {"url": "https://github.com/espressif/esptool.git"},
        },
    )
    package = core / "packages" / "tool-esptoolpy"
    (package / "_contrib" / "bin" / "esptool.py").write_text("#!/usr/bin/python3\n", encoding="utf-8")
    (package / "_contrib" / "cffi-2.1.0.dist-info" / "RECORD").write_text(
        "_contrib/bin/esptool.py,,\n", encoding="utf-8"
    )
    (package / "_contrib" / "runtime.py").write_text("VALUE = 1\n", encoding="utf-8")
    (package / "payload.bin").write_bytes(b"esptool fixture\x00")
    (package / "install-root.txt").write_text("/stable/build/root\n", encoding="utf-8")
    (package / ".piopm").write_text("ignored state\n", encoding="utf-8")

    write_json(
        core / "packages" / "tool-scons" / "package.json",
        {
            "name": "tool-scons",
            "version": "4.40801.0",
            "repository": {"url": "https://github.com/SCons/scons.git"},
        },
    )
    other_package = core / "packages" / "tool-scons"
    (other_package / "_contrib" / "bin" / "scons.py").write_text("#!/usr/bin/python3\n", encoding="utf-8")
    (other_package / "_contrib" / "cffi-2.1.0.dist-info" / "RECORD").write_text(
        "_contrib/bin/scons.py,,\n", encoding="utf-8"
    )

    firmware = root / "firmware.bin"
    map_file = root / "firmware.map"
    firmware.write_bytes(b"firmware\x00fixture")
    map_file.write_bytes(b"raw map fixture\n")
    for index, path in enumerate(sorted(root.rglob("*"), reverse=reverse)):
        if not path.is_symlink():
            os.utime(path, (1_700_000_000 + index, 1_700_000_000 + index), follow_symlinks=False)
    return {
        "project": project,
        "core": core,
        "firmware": firmware,
        "map": map_file,
        "output": root / "metadata.json",
    }


def helper_command(fixture: dict[str, Path], **overrides: str) -> list[str]:
    values = {
        "project-root": str(fixture["project"]),
        "core-dir": str(fixture["core"]),
        "environment": "Samovar",
        "firmware": str(fixture["firmware"]),
        "map": str(fixture["map"]),
        "git-sha": "0123456789abcdef0123456789abcdef01234567",
        "dirty": "false",
        "source-date-epoch": "1700000000",
        "output": str(fixture["output"]),
    }
    values.update(overrides)
    command = [sys.executable, str(HELPER)]
    for name, value in values.items():
        command.extend((f"--{name}", value))
    return command


def run_helper(fixture: dict[str, Path], **overrides: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        helper_command(fixture, **overrides),
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


class MetadataHelperContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not HELPER.is_file():
            raise AssertionError("tools/build_metadata.py is missing")

    def test_stdlib_only_and_no_installer_or_binary_rewrite_paths(self) -> None:
        source = read(HELPER)
        tree = ast.parse(source)
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported.update(
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        self.assertTrue(imported.issubset(set(sys.stdlib_module_names)), imported - set(sys.stdlib_module_names))
        lowered = source.lower()
        for forbidden in ("pip install", "pkg install", "download", "extra_scripts", "materializ", "normaliz"):
            self.assertNotIn(forbidden, lowered)

    def test_deterministic_metadata_and_targeted_hash_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = make_fixture(root / "first")
            second = make_fixture(root / "second", reverse=True)
            for fixture in (first, second):
                result = run_helper(fixture)
                self.assertEqual(result.returncode, 0, result.stderr)
            first_data = json.loads(first["output"].read_text(encoding="utf-8"))
            second_data = json.loads(second["output"].read_text(encoding="utf-8"))
            self.assertEqual(first_data, second_data)
            self.assertEqual(first_data["source_date_epoch"], 1_700_000_000)
            self.assertEqual(first_data["environment"], "Samovar")

            library_file = second["project"] / "libraries" / "Example" / "src" / "example.h"
            library_file.write_text("#define VALUE 2\n", encoding="utf-8")
            result = run_helper(second)
            self.assertEqual(result.returncode, 0, result.stderr)
            library_change = json.loads(second["output"].read_text(encoding="utf-8"))
            self.assertNotEqual(first_data["libraries"][0]["tree_sha256"], library_change["libraries"][0]["tree_sha256"])
            self.assertEqual(first_data["artifacts"]["firmware"], library_change["artifacts"]["firmware"])

            second["firmware"].write_bytes(b"firmware\x00fixturf")
            result = run_helper(second)
            self.assertEqual(result.returncode, 0, result.stderr)
            artifact_change = json.loads(second["output"].read_text(encoding="utf-8"))
            self.assertNotEqual(library_change["artifacts"]["firmware"], artifact_change["artifacts"]["firmware"])

    def test_package_hash_ignores_only_pip_generated_launcher_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            baseline = make_fixture(root / "baseline")
            generated = make_fixture(root / "generated")

            generated_package = generated["core"] / "packages" / "tool-esptoolpy"
            (generated_package / "_contrib" / "bin" / "esptool.py").write_text(
                f"#!{generated['core']}/venv/bin/python\n", encoding="utf-8"
            )
            (generated_package / "_contrib" / "cffi-2.1.0.dist-info" / "RECORD").write_text(
                f"_contrib/bin/esptool.py,sha256={generated['core']},42\n", encoding="utf-8"
            )

            def package_inventory(fixture: dict[str, Path]) -> list[dict[str, object]]:
                result = run_helper(fixture)
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(fixture["output"].read_text(encoding="utf-8"))["platformio"]["packages"]

            def package_hash(inventory: list[dict[str, object]], name: str) -> object:
                return next(package["tree_sha256"] for package in inventory if package["name"] == name)

            baseline_inventory = package_inventory(baseline)
            with self.subTest("generated launcher and RECORD"):
                self.assertEqual(baseline_inventory, package_inventory(generated))

            baseline_hash = package_hash(baseline_inventory, "tool-esptoolpy")
            mutations = (
                ("ordinary _contrib code", "_contrib/runtime.py", b"VALUE = 2\n"),
                ("package manifest", "package.json", None),
                ("package binary", "payload.bin", b"esptool fixture\x01"),
                ("absolute path outside exclusions", "install-root.txt", b"/tmp/other/build/root\n"),
            )
            for label, relative, content in mutations:
                with self.subTest(label):
                    fixture = make_fixture(root / label.replace(" ", "-"))
                    target = fixture["core"] / "packages" / "tool-esptoolpy" / relative
                    target.write_bytes(target.read_bytes() + b" " if content is None else content)
                    self.assertNotEqual(
                        baseline_hash,
                        package_hash(package_inventory(fixture), "tool-esptoolpy"),
                    )

            other_baseline_hash = package_hash(baseline_inventory, "tool-scons")
            for label, relative in (
                ("non-esptool launcher", "_contrib/bin/scons.py"),
                ("non-esptool RECORD", "_contrib/cffi-2.1.0.dist-info/RECORD"),
            ):
                with self.subTest(label):
                    fixture = make_fixture(root / label.replace(" ", "-"))
                    target = fixture["core"] / "packages" / "tool-scons" / relative
                    target.write_bytes(target.read_bytes() + b"changed\n")
                    self.assertNotEqual(
                        other_baseline_hash,
                        package_hash(package_inventory(fixture), "tool-scons"),
                    )

    def test_invalid_inputs_and_unsupported_tree_entries_fail_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = make_fixture(root / "base")
            invalid_values = (
                {"git-sha": "abc"},
                {"dirty": "maybe"},
                {"source-date-epoch": "-1"},
                {"source-date-epoch": "01"},
            )
            for values in invalid_values:
                with self.subTest(values=values):
                    result = run_helper(fixture, **values)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("error", result.stderr.lower())

            fixture["firmware"].unlink()
            result = run_helper(fixture)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("firmware", result.stderr.lower())

            missing_manifest = make_fixture(root / "missing-manifest")
            (missing_manifest["core"] / "packages" / "tool-esptoolpy" / "package.json").unlink()
            result = run_helper(missing_manifest)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("package.json", result.stderr)

            symlink_fixture = make_fixture(root / "symlink")
            (symlink_fixture["project"] / "libraries" / "Example" / "escape").symlink_to(root.parent)
            result = run_helper(symlink_fixture)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("symlink", result.stderr.lower())

            fifo_fixture = make_fixture(root / "fifo")
            os.mkfifo(fifo_fixture["core"] / "packages" / "tool-esptoolpy" / "unsupported")
            result = run_helper(fifo_fixture)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unsupported", result.stderr.lower())

    def test_output_is_canonical_and_contains_no_machine_or_secret_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = make_fixture(Path(temp_dir) / "fixture")
            result = run_helper(fixture)
            self.assertEqual(result.returncode, 0, result.stderr)
            output = fixture["output"].read_text(encoding="utf-8")
            data = json.loads(output)
            self.assertEqual(output, json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            for forbidden in (
                str(fixture["project"]),
                str(fixture["core"]),
                "generated_at",
                "hostname",
                "pid",
                "SECRET_FIXTURE_VALUE",
            ):
                self.assertNotIn(forbidden, output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
