from __future__ import annotations

import re
from pathlib import Path

INSTALLER_PATH = Path(__file__).resolve().parents[1] / "scripts" / "install.ps1"


def test_windows_installer_extracts_the_runtime_bundle_contents() -> None:
    installer = INSTALLER_PATH.read_text(encoding="utf-8")

    assert "$bundleDir = Join-Path -Path $extractedDir.FullName -ChildPath $executableName" in installer
    assert "Get-ChildItem -Force -LiteralPath $bundleDir | Copy-Item -Destination $BinDir -Recurse -Force" in installer


def test_windows_installer_never_exits_the_calling_powershell_host() -> None:
    installer = INSTALLER_PATH.read_text(encoding="utf-8")

    assert not re.search(r"(?m)^\s*exit(?:\s|$)", installer)
    assert "try {\n    Main\n} catch {" in installer


def test_windows_installer_reports_the_real_launch_failure() -> None:
    installer = INSTALLER_PATH.read_text(encoding="utf-8")

    assert "if ($LASTEXITCODE -ne 0)" in installer
    assert 'Write-ErrorMsg "Windows reported: $($_.Exception.Message)"' in installer
