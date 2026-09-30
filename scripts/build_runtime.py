#!/usr/bin/env python3
"""Build standalone iTE runtime artifacts for distribution.

Creates platform-specific archives containing a PyInstaller-built
iTE binary with bundled Python and all dependencies.

Usage:
    python scripts/build_runtime.py              # build for current platform
    python scripts/build_runtime.py --all         # build for all supported platforms
    python scripts/build_runtime.py --version 0.0.70  # override version
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = PROJECT_ROOT / "dist" / "runtime"
MANIFEST_DIR = PROJECT_ROOT / "dist"
SPEC_DIR = PROJECT_ROOT / "build" / "runtime_specs"

SUPPORTED_TARGETS: dict[str, dict[str, Any]] = {
    "darwin-arm64": {
        "os": "darwin",
        "arch": "arm64",
        "archive": "tar.gz",
        "executable": "ite",
        "label": "macOS Apple Silicon",
    },
    "darwin-x64": {
        "os": "darwin",
        "arch": "x64",
        "archive": "tar.gz",
        "executable": "ite",
        "label": "macOS Intel",
    },
    "linux-x64": {
        "os": "linux",
        "arch": "x64",
        "archive": "tar.gz",
        "executable": "ite",
        "label": "Linux x86_64",
    },
    "win32-x64": {
        "os": "win32",
        "arch": "x64",
        "archive": "zip",
        "executable": "ite.exe",
        "label": "Windows x86_64",
    },
}

# Hidden imports PyInstaller may miss
HIDDEN_IMPORTS: list[str] = [
    # textual
    "textual._xterm_parser",
    "textual.drivers.linux_driver",
    "textual.drivers.win32",
    # fastmcp / mcp
    "mcp",
    "mcp.server",
    "mcp.client",
    # pydantic
    "pydantic.deprecated.decorator",
    "pydantic.deprecated.copy_internals",
    # Pillow plugins
    "PIL._tkinter_finder",
    # cryptography
    "cryptography.hazmat.backends.openssl",
    # html2text
    "html2text",
    # beautifulsoup4
    "bs4",
    "bs4.builder._html5lib",
    "bs4.builder._lxml",
    # Rust/PyO3 document parsing (lazy-imported in media_tools)
    "pdf_inspector",
    "anydoc",
    # PIL plugins for image processing
    "PIL.Image",
    "PIL.ImageDraw",
    "PIL.ImageFont",
    # tree-sitter (for textual syntax)
    "tree_sitter",
    "tree_sitter_python",
    "tree_sitter_javascript",
    "tree_sitter_typescript",
    "tree_sitter_bash",
    "tree_sitter_json",
    "tree_sitter_yaml",
    "tree_sitter_toml",
    "tree_sitter_markdown",
    "tree_sitter_sql",
    "tree_sitter_css",
    "tree_sitter_html",
    "tree_sitter_rust",
    "tree_sitter_go",
    "tree_sitter_java",
    "tree_sitter_c",
    "tree_sitter_cpp",
    # remote runtime host (spawned as `remote child` in a frozen build)
    "ite.remote.child",
    "ite.remote.runtime",
    "ite.remote.supervisor",
]

# Data files to include
DATAS: list[tuple[str, str]] = [
    (str(PROJECT_ROOT / "src" / "ite" / "ui" / "reup" / "styles"), "ite/ui/reup/styles"),
]


def _find_venv_python() -> str:
    """Find the venv Python, falling back to system Python."""
    venv_python = PROJECT_ROOT / ".venv" / "bin" / "python3"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def _find_site_packages(python_exe: str) -> list[Path]:
    """Find site-packages directories for the Python used by PyInstaller."""
    script = (
        "import json, sysconfig; "
        "paths = sysconfig.get_paths(); "
        "print(json.dumps([paths.get('purelib'), paths.get('platlib')]))"
    )
    try:
        result = subprocess.run(
            [python_exe, "-c", script],
            capture_output=True,
            check=True,
            text=True,
            timeout=10,
        )
        raw_paths = json.loads(result.stdout)
    except Exception:
        raw_paths = []
    site_packages: list[Path] = []
    seen: set[Path] = set()
    for raw in raw_paths:
        if not raw:
            continue
        path = Path(str(raw))
        if path.exists() and path not in seen:
            site_packages.append(path)
            seen.add(path)
    return site_packages


def _detect_current_target() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    arch_map = {
        "x86_64": "x64",
        "amd64": "x64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }
    arch = arch_map.get(machine, machine)
    target = f"{system}-{arch}"
    if target not in SUPPORTED_TARGETS:
        print(f"Unsupported target: {target} (system={system}, machine={machine})")
        print(f"Supported targets: {list(SUPPORTED_TARGETS.keys())}")
        sys.exit(1)
    return target


def _get_version(version_override: str | None = None) -> str:
    if version_override:
        return version_override
    # Read from pyproject.toml
    try:
        with open(PROJECT_ROOT / "pyproject.toml", "rb") as f:
            import tomli
            data = tomli.load(f)
        version = data.get("project", {}).get("version", "")
        if version:
            return str(version)
    except Exception:
        pass
    # Fallback: try importlib
    try:
        from ite import __version__
        return __version__
    except ImportError:
        pass
    return "0.0.0-dev"


def _clean_dist(target: str) -> None:
    target_dir = DIST_DIR / target
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)


def _discover_mypyc_modules(python_exe: str) -> tuple[list[str], list[tuple[str, str | None]]]:
    """Find mypyc-compiled extension modules in site-packages.

    Returns (module_names, binaries) where module_names are hidden import
    names and binaries are (path, destdir) tuples for PyInstaller.
    """
    module_names: list[str] = []
    binaries: list[tuple[str, str | None]] = []
    for site_packages in _find_site_packages(python_exe):
        for entry in sorted(site_packages.iterdir()):
            if "__mypyc" in entry.name and entry.suffix in {".so", ".pyd"}:
                modname = entry.stem.split(".")[0]  # strip ABI suffix
                module_names.append(modname)
                binaries.append((str(entry), "."))
    return module_names, binaries


def _write_pyinstaller_spec(target: str, executable: str, python_exe: str) -> Path:
    """Write a PyInstaller .spec file for the target."""
    SPEC_DIR.mkdir(parents=True, exist_ok=True)
    spec_path = SPEC_DIR / f"ite_{target}.spec"

    mypyc_modules, mypyc_binaries = _discover_mypyc_modules(python_exe)
    all_hidden_imports = list(HIDDEN_IMPORTS) + mypyc_modules
    hidden_imports_str = ",\n        ".join(repr(h) for h in all_hidden_imports)
    datas_str = ",\n        ".join(
        repr((src, dst)) for src, dst in DATAS
    )

    main_script = str(PROJECT_ROOT / "src" / "ite" / "main.py")

    binaries_str = ",\n        ".join(
        repr(b) for b in mypyc_binaries
    )

    spec_content = f'''# -*- mode: python ; coding: utf-8 -*-
# Auto-generated iTE PyInstaller spec for {target}

a = Analysis(
    [r"{main_script}"],
    pathex=[r"{PROJECT_ROOT}"],
    binaries=[
        {binaries_str}
    ],
    datas=[
        {datas_str}
    ],
    hiddenimports=[
        {hidden_imports_str}
    ],
    hookspath=[r"{PROJECT_ROOT}/hooks"],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "unittest",
        "test",
        "pdb",
        "distutils",
        "setuptools",
        "pip",
        "flet",
        "flet_core",
        "prompt_toolkit",
    ],
    noarchive=False,
    copy_metadata=["fastmcp", "pydantic", "pydantic_core"],
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="{executable}",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="{executable}",
)

'''
    spec_path.write_text(spec_content, encoding="utf-8")
    return spec_path


def build_target(
    target: str,
    version: str,
    *,
    clean: bool = True,
) -> Path | None:
    """Build the runtime artifact for a single target."""
    info = SUPPORTED_TARGETS[target]
    executable = info["executable"]

    if clean:
        _clean_dist(target)

    # Run PyInstaller — use venv Python so PyInstaller is found
    python_exe = _find_venv_python()
    spec_path = _write_pyinstaller_spec(target, executable, python_exe)

    print(f"\n{'='*60}")
    print(f"Building iTE v{version} for {info['label']} ({target})")
    print(f"{'='*60}")
    print(f"Using Python: {python_exe}")

    # Verify PyInstaller is available
    try:
        subprocess.run(
            [python_exe, "-c", "import PyInstaller"],
            capture_output=True, check=True,
        )
    except subprocess.CalledProcessError:
        print(f"ERROR: PyInstaller not found in Python at {python_exe}")
        print("Install it with: uv pip install pyinstaller")
        print(f"Or activate venv: source .venv/bin/activate")
        return None

    cmd = [
        python_exe, "-m", "PyInstaller",
        "--distpath", str(DIST_DIR / target),
        "--workpath", str(PROJECT_ROOT / "build" / "pyinstaller" / target),
        "--noconfirm",
        "--clean",
        str(spec_path),
    ]

    try:
        subprocess.run(cmd, cwd=PROJECT_ROOT, check=True)
    except subprocess.CalledProcessError as e:
        print(f"PyInstaller build failed for {target}: {e}")
        return None

    # PyInstaller outputs a COLLECT directory at DIST_DIR/target/<executable>/
    binary_dir = DIST_DIR / target / executable
    binary = binary_dir / executable
    if not binary_dir.exists() or not binary.exists():
        print(f"Binary missing: {binary}")
        return None

    # Package into archive (wrap the entire COLLECT dir for clean extraction)
    archive_name = f"ite-{version}-{target}"
    archive_type = info["archive"]

    stage_dir = DIST_DIR / target / archive_name
    stage_dir.mkdir(parents=True, exist_ok=True)
    # Copy entire COLLECT directory into the staging archive dir
    shutil.copytree(binary_dir, stage_dir / executable, dirs_exist_ok=True)
    # Make the entry point executable
    entry_point = stage_dir / executable / executable
    entry_point.chmod(0o755)

    if archive_type == "tar.gz":
        archive_path = DIST_DIR / target / f"{archive_name}.tar.gz"
        _create_tarball(stage_dir, archive_path, archive_name, executable)
    elif archive_type == "zip":
        archive_path = DIST_DIR / target / f"{archive_name}.zip"
        _create_zip(stage_dir, archive_path, archive_name, executable)
    else:
        print(f"Unknown archive type: {archive_type}")
        return None

    # Clean up staging
    shutil.rmtree(stage_dir)

    # Generate checksum
    _generate_checksum(archive_path)

    print(f"  Archive: {archive_path}")
    print(f"  Size: {archive_path.stat().st_size / 1024 / 1024:.1f} MB")
    return archive_path


def _create_tarball(
    source_dir: Path,
    archive_path: Path,
    archive_name: str,
    executable: str,
) -> None:
    with tarfile.open(archive_path, "w:gz") as tar:
        for item in sorted(source_dir.iterdir()):
            arcname = f"{archive_name}/{item.name}"
            tar.add(item, arcname=arcname)
    os.chmod(archive_path, 0o644)


def _create_zip(
    source_dir: Path,
    archive_path: Path,
    archive_name: str,
    executable: str,
) -> None:
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in sorted(source_dir.rglob("*")):
            if item.is_dir():
                continue
            arcname = f"{archive_name}/{item.relative_to(source_dir)}"
            zf.write(item, arcname)
    os.chmod(archive_path, 0o644)


def _generate_checksum(archive_path: Path) -> Path:
    sha256 = hashlib.sha256()
    with open(archive_path, "rb") as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
    checksum_path = archive_path.with_suffix(archive_path.suffix + ".sha256")
    checksum_path.write_text(f"{sha256.hexdigest()}  {archive_path.name}\n", encoding="utf-8")
    return checksum_path


def generate_manifest(
    version: str,
    artifacts: dict[str, Path],
    *,
    base_url: str = "https://github.com/ThatSaxyDev/ite-releases/releases/download",
) -> Path:
    """Generate the release manifest JSON."""
    manifest: dict[str, Any] = {
        "version": version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "assets": {},
    }

    for target, archive_path in artifacts.items():
        info = SUPPORTED_TARGETS[target]
        checksum_path = archive_path.with_suffix(archive_path.suffix + ".sha256")
        sha256 = ""
        if checksum_path.exists():
            sha256 = checksum_path.read_text(encoding="utf-8").split()[0]

        tag = f"v{version}"
        filename = archive_path.name
        manifest["assets"][target] = {
            "url": f"{base_url}/{tag}/{filename}",
            "sha256": sha256,
            "archiveType": info["archive"],
            "executable": info["executable"],
            "label": info["label"],
        }

    manifest_path = MANIFEST_DIR / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"\nManifest written to: {manifest_path}")
    return manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build standalone iTE runtime artifacts",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Build for all supported platforms (requires cross-platform build)",
    )
    parser.add_argument(
        "--target",
        help="Build for a specific target (e.g. darwin-arm64, linux-x64)",
    )
    parser.add_argument(
        "--version",
        help="Version override (default: from pyproject.toml)",
    )
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="Do not clean build output before building",
    )
    parser.add_argument(
        "--base-url",
        default="https://github.com/ThatSaxyDev/ite-releases/releases/download",
        help="Base URL for release downloads in manifest",
    )
    parser.add_argument(
        "--manifest-only",
        action="store_true",
        help="Only regenerate manifest from existing artifacts",
    )
    parser.add_argument(
        "--check-pyinstaller",
        action="store_true",
        help="Check if PyInstaller is installed and exit",
    )
    parser.add_argument(
        "--print-version",
        action="store_true",
        help="Print the resolved version and exit",
    )

    args = parser.parse_args()

    if args.check_pyinstaller:
        try:
            import PyInstaller  # noqa: F401
            print("PyInstaller is installed.")
        except ImportError:
            print("PyInstaller is NOT installed. Run: pip install pyinstaller")
            sys.exit(1)
        return

    if args.print_version:
        print(_get_version(args.version))
        return

    version = _get_version(args.version)
    print(f"iTE Runtime Builder — v{version}")

    if args.manifest_only:
        artifacts = _find_existing_artifacts(version)
        generate_manifest(version, artifacts, base_url=args.base_url)
        return

    targets: list[str] = []
    if args.all:
        targets = list(SUPPORTED_TARGETS.keys())
    elif args.target:
        if args.target not in SUPPORTED_TARGETS:
            print(f"Invalid target: {args.target}")
            print(f"Supported: {list(SUPPORTED_TARGETS.keys())}")
            sys.exit(1)
        targets = [args.target]
    else:
        targets = [_detect_current_target()]

    artifacts: dict[str, Path] = {}
    for target in targets:
        archive_path = build_target(
            target,
            version,
            clean=not args.no_clean,
        )
        if archive_path:
            artifacts[target] = archive_path
        else:
            print(f"WARNING: Build failed for {target}")

    if artifacts:
        generate_manifest(version, artifacts, base_url=args.base_url)
        print(f"\nBuilt {len(artifacts)}/{len(targets)} targets successfully.")
    else:
        print("\nNo artifacts built.")
        sys.exit(1)


def _find_existing_artifacts(version: str) -> dict[str, Path]:
    """Find existing archive files in the dist directory."""
    artifacts: dict[str, Path] = {}
    for target, info in SUPPORTED_TARGETS.items():
        archive_type = info["archive"]
        ext = ".tar.gz" if archive_type == "tar.gz" else ".zip"
        archive_name = f"ite-{version}-{target}{ext}"
        archive_path = DIST_DIR / target / archive_name
        if archive_path.exists():
            artifacts[target] = archive_path
    return artifacts


if __name__ == "__main__":
    main()
