#!/usr/bin/env python3
import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import stat
import struct
import sys
from pathlib import Path


IGNORED_NAMES = {".git", ".piopm", "__pycache__"}
GIT_SHA_RE = re.compile(r"[0-9a-fA-F]{40}")
ENVIRONMENT_RE = re.compile(r"[A-Za-z0-9_.-]+")
DECIMAL_RE = re.compile(r"0|[1-9][0-9]*")


class MetadataError(Exception):
    pass


def require_directory(path: Path, label: str) -> Path:
    try:
        mode = path.lstat().st_mode
    except OSError as error:
        raise MetadataError(f"{label} is unavailable: {path.name}: {error}") from error
    if not stat.S_ISDIR(mode):
        raise MetadataError(f"{label} is not a directory: {path.name}")
    return path


def require_regular_file(path: Path, label: str) -> Path:
    try:
        mode = path.lstat().st_mode
    except OSError as error:
        raise MetadataError(f"{label} is unavailable: {path.name}: {error}") from error
    if not stat.S_ISREG(mode):
        raise MetadataError(f"{label} is not a regular file: {path.name}")
    return path


def load_json_object(path: Path, label: str) -> dict[str, object]:
    require_regular_file(path, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise MetadataError(f"cannot read {label} {path.name}: {error}") from error
    if not isinstance(value, dict):
        raise MetadataError(f"{label} root must be an object: {path.name}")
    return value


def required_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MetadataError(f"{label} must be a non-empty string")
    return value.strip()


def source_from_manifest(manifest: dict[str, object], label: str) -> str:
    repository = manifest.get("repository")
    if isinstance(repository, str) and repository.strip():
        return repository.strip()
    if isinstance(repository, dict):
        url = repository.get("url")
        if isinstance(url, str) and url.strip():
            return url.strip()
    homepage = manifest.get("homepage")
    if isinstance(homepage, str) and homepage.strip():
        return homepage.strip()
    raise MetadataError(f"{label} does not declare a source")


def sha256_file(path: Path, label: str) -> tuple[int, str]:
    require_regular_file(path, label)
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                digest.update(chunk)
    except OSError as error:
        raise MetadataError(f"cannot read {label} {path.name}: {error}") from error
    return size, digest.hexdigest()


def ignored_entry(name: str) -> bool:
    return name in IGNORED_NAMES or name.endswith(".pyc")


def ignored_esptoolpy_generated_path(relative: Path) -> bool:
    parts = relative.parts
    if len(parts) >= 2 and parts[:2] == ("_contrib", "bin"):
        return True
    return (
        len(parts) == 3
        and parts[0] == "_contrib"
        and parts[1].endswith(".dist-info")
        and parts[2] == "RECORD"
    )


def hash_record(digest: object, kind: bytes, executable: bool, path: str, payload_size: int) -> None:
    path_bytes = path.encode("utf-8", "surrogateescape")
    digest.update(kind)
    digest.update(b"1" if executable else b"0")
    digest.update(struct.pack(">Q", len(path_bytes)))
    digest.update(path_bytes)
    digest.update(struct.pack(">Q", payload_size))


def tree_sha256(root: Path, ignore_esptoolpy_generated: bool = False) -> str:
    require_directory(root, "tree root")
    root_real = root.resolve(strict=True)
    digest = hashlib.sha256()

    def walk(directory: Path) -> None:
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as error:
            raise MetadataError(f"cannot enumerate tree: {error}") from error
        for entry in entries:
            if ignored_entry(entry.name):
                continue
            path = Path(entry.path)
            relative_path = path.relative_to(root)
            if ignore_esptoolpy_generated and ignored_esptoolpy_generated_path(relative_path):
                continue
            relative = relative_path.as_posix()
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as error:
                raise MetadataError(f"cannot inspect tree entry {relative}: {error}") from error
            executable = bool(info.st_mode & 0o111)
            if stat.S_ISDIR(info.st_mode):
                hash_record(digest, b"D", executable, relative, 0)
                walk(path)
            elif stat.S_ISREG(info.st_mode):
                hash_record(digest, b"F", executable, relative, info.st_size)
                read_size = 0
                try:
                    with path.open("rb") as stream:
                        while True:
                            chunk = stream.read(1024 * 1024)
                            if not chunk:
                                break
                            read_size += len(chunk)
                            digest.update(chunk)
                except OSError as error:
                    raise MetadataError(f"cannot read tree entry {relative}: {error}") from error
                if read_size != info.st_size:
                    raise MetadataError(f"tree entry changed while hashing: {relative}")
            elif stat.S_ISLNK(info.st_mode):
                try:
                    target = os.readlink(path)
                    resolved = (path.parent / target).resolve(strict=False)
                    resolved.relative_to(root_real)
                except (OSError, ValueError) as error:
                    raise MetadataError(f"symlink escapes tree: {relative}") from error
                target_bytes = target.encode("utf-8", "surrogateescape")
                hash_record(digest, b"L", executable, relative, len(target_bytes))
                digest.update(target_bytes)
            else:
                raise MetadataError(f"unsupported tree entry type: {relative}")

    walk(root)
    return digest.hexdigest()


def git_revision(platform_root: Path) -> str:
    git_root = require_directory(platform_root / ".git", "platform Git metadata")
    head = require_regular_file(git_root / "HEAD", "platform Git HEAD").read_text(encoding="ascii").strip()
    if GIT_SHA_RE.fullmatch(head):
        return head.lower()
    prefix = "ref: "
    if not head.startswith(prefix):
        raise MetadataError("platform Git HEAD is malformed")
    reference = head[len(prefix) :]
    if reference.startswith("/") or ".." in Path(reference).parts:
        raise MetadataError("platform Git HEAD reference is invalid")
    reference_path = git_root / reference
    if reference_path.is_file():
        revision = reference_path.read_text(encoding="ascii").strip()
    else:
        packed = require_regular_file(git_root / "packed-refs", "platform packed refs")
        revision = ""
        for line in packed.read_text(encoding="ascii").splitlines():
            if line.startswith(("#", "^")):
                continue
            fields = line.split(" ", 1)
            if len(fields) == 2 and fields[1] == reference:
                revision = fields[0]
                break
    if not GIT_SHA_RE.fullmatch(revision):
        raise MetadataError("platform Git revision is missing or malformed")
    return revision.lower()


def platform_inventory(core_dir: Path) -> list[dict[str, object]]:
    platforms_root = require_directory(core_dir / "platforms", "PlatformIO platforms directory")
    platforms: list[dict[str, object]] = []
    for entry in sorted(platforms_root.iterdir(), key=lambda path: path.name):
        require_directory(entry, "PlatformIO platform")
        manifest = load_json_object(entry / "platform.json", "platform.json")
        platforms.append(
            {
                "name": required_string(manifest.get("name"), "platform name"),
                "revision": git_revision(entry),
                "source": source_from_manifest(manifest, "platform manifest"),
                "tree_sha256": tree_sha256(entry),
                "version": required_string(manifest.get("version"), "platform version"),
            }
        )
    if not platforms:
        raise MetadataError("PlatformIO core has no installed platforms")
    return platforms


def package_inventory(core_dir: Path) -> list[dict[str, object]]:
    packages_root = require_directory(core_dir / "packages", "PlatformIO packages directory")
    packages: list[dict[str, object]] = []
    for entry in sorted(packages_root.iterdir(), key=lambda path: path.name):
        require_directory(entry, "PlatformIO package")
        manifest = load_json_object(entry / "package.json", "package.json")
        name = required_string(manifest.get("name"), "package name")
        packages.append(
            {
                "name": name,
                "source": source_from_manifest(manifest, "package manifest"),
                "tree_sha256": tree_sha256(entry, ignore_esptoolpy_generated=name == "tool-esptoolpy"),
                "version": required_string(manifest.get("version"), "package version"),
            }
        )
    if not packages:
        raise MetadataError("PlatformIO core has no installed packages")
    return packages


def properties_manifest(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line or line.lstrip().startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            values[name.strip()] = value.strip()
    except (OSError, UnicodeError) as error:
        raise MetadataError(f"cannot read library.properties: {error}") from error
    return values


def library_metadata(root: Path) -> dict[str, object]:
    result: dict[str, object] = {"directory": root.name, "tree_sha256": tree_sha256(root)}
    manifest: dict[str, object] = {}
    if (root / "library.json").is_file():
        manifest = load_json_object(root / "library.json", "library.json")
    elif (root / "library.properties").is_file():
        properties = properties_manifest(root / "library.properties")
        manifest = {"name": properties.get("name"), "version": properties.get("version")}
        if properties.get("url"):
            manifest["repository"] = properties["url"]
    elif (root / "package.json").is_file():
        manifest = load_json_object(root / "package.json", "package.json")

    name = manifest.get("name")
    version = manifest.get("version")
    if isinstance(name, str) and name.strip():
        result["name"] = name.strip()
    if isinstance(version, (str, int, float)) and str(version).strip():
        result["version"] = str(version).strip()
    try:
        result["source"] = source_from_manifest(manifest, "library manifest")
    except MetadataError:
        pass
    return result


def library_inventory(project_root: Path) -> list[dict[str, object]]:
    libraries_root = require_directory(project_root / "libraries", "libraries directory")
    libraries: list[dict[str, object]] = []
    for entry in sorted(libraries_root.iterdir(), key=lambda path: path.name):
        require_directory(entry, "vendored library")
        libraries.append(library_metadata(entry))
    return libraries


def artifact_metadata(path: Path, label: str) -> dict[str, object]:
    size, digest = sha256_file(path, label)
    return {"name": path.name, "sha256": digest, "size": size}


def parse_arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write deterministic Samovar build metadata")
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--core-dir", required=True, type=Path)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--firmware", required=True, type=Path)
    parser.add_argument("--map", required=True, dest="map_file", type=Path)
    parser.add_argument("--git-sha", required=True)
    parser.add_argument("--dirty", required=True)
    parser.add_argument("--source-date-epoch", required=True)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def build_metadata(arguments: argparse.Namespace) -> dict[str, object]:
    project_root = require_directory(arguments.project_root, "project root")
    core_dir = require_directory(arguments.core_dir, "PlatformIO core directory")
    require_regular_file(project_root / "platformio.ini", "platformio.ini")
    if not ENVIRONMENT_RE.fullmatch(arguments.environment):
        raise MetadataError("environment is malformed")
    if not GIT_SHA_RE.fullmatch(arguments.git_sha):
        raise MetadataError("Git SHA must contain exactly 40 hexadecimal digits")
    if arguments.dirty not in {"true", "false"}:
        raise MetadataError("dirty must be exactly true or false")
    if not DECIMAL_RE.fullmatch(arguments.source_date_epoch):
        raise MetadataError("source date epoch must be a canonical non-negative decimal")
    source_date_epoch = int(arguments.source_date_epoch)
    if source_date_epoch > 9_223_372_036_854_775_807:
        raise MetadataError("source date epoch is out of range")
    try:
        platformio_version = importlib.metadata.version("platformio")
    except importlib.metadata.PackageNotFoundError as error:
        raise MetadataError("PlatformIO Python distribution is unavailable") from error

    return {
        "artifacts": {
            "firmware": artifact_metadata(arguments.firmware, "firmware"),
            "map": artifact_metadata(arguments.map_file, "map"),
        },
        "environment": arguments.environment,
        "git": {"dirty": arguments.dirty == "true", "sha": arguments.git_sha.lower()},
        "libraries": library_inventory(project_root),
        "platformio": {
            "packages": package_inventory(core_dir),
            "platforms": platform_inventory(core_dir),
            "version": platformio_version,
        },
        "python_version": ".".join(str(value) for value in sys.version_info[:3]),
        "schema_version": 1,
        "source_date_epoch": source_date_epoch,
    }


def write_metadata(path: Path, metadata: dict[str, object]) -> None:
    parent = require_directory(path.parent, "output directory")
    if path.exists() and not stat.S_ISREG(path.lstat().st_mode):
        raise MetadataError(f"output is not a regular file: {path.name}")
    text = json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        (parent / path.name).write_text(text, encoding="utf-8", newline="\n")
    except OSError as error:
        raise MetadataError(f"cannot write output {path.name}: {error}") from error


def main(argv: list[str]) -> int:
    arguments = parse_arguments(argv)
    try:
        metadata = build_metadata(arguments)
        write_metadata(arguments.output, metadata)
    except MetadataError as error:
        print(f"build_metadata: error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
