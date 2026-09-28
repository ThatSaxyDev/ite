# iTE One-Shot Installer (Windows PowerShell)
#   irm https://ite.kiishi.space/install.ps1 | iex
#
# Detects architecture, downloads the correct standalone iTE runtime,
# verifies the checksum, and installs to %LOCALAPPDATA%\iTE\bin\ite.exe.
#
# Environment overrides:
#   $env:ITE_INSTALL_MANIFEST_URL   - override manifest URL for dev/testing
#   $env:ITE_INSTALL_DIR            - override install directory
#   $env:ITE_INSTALL_VERSION        - pin a specific version
#   $env:ITE_INSTALL_SKIP_PATH      - skip PATH modification

param()

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# ── Configuration ────────────────────────────────────────────
$ManifestUrl = if ($env:ITE_INSTALL_MANIFEST_URL) { $env:ITE_INSTALL_MANIFEST_URL } else { "https://ite.kiishi.space/releases/manifest.json" }
$ManagedRoot = if ($env:ITE_INSTALL_DIR) { $env:ITE_INSTALL_DIR } else { "$env:LOCALAPPDATA\iTE" }
$BinDir = "$ManagedRoot\bin"
$ExePath = "$BinDir\ite.exe"

# ── Helpers ──────────────────────────────────────────────────
function Write-Info    { Write-Host "[iTE] $args" -ForegroundColor Gray }
function Write-Success { Write-Host "[iTE] $args" -ForegroundColor Green }
function Write-Warn    { Write-Host "[iTE] $args" -ForegroundColor Yellow }
function Write-ErrorMsg { Write-Host "[iTE] $args" -ForegroundColor Red }
function Write-Step    { Write-Host "→ $args" -ForegroundColor White }

# ── Architecture detection ───────────────────────────────────
function Get-Target {
    $arch = switch ($env:PROCESSOR_ARCHITECTURE) {
        "AMD64" { "x64" }
        "ARM64" { "arm64" }
        default {
            Write-ErrorMsg "Unsupported architecture: $env:PROCESSOR_ARCHITECTURE"
            exit 1
        }
    }
    return "win32-$arch"
}

# ── Fetch manifest ───────────────────────────────────────────
function Get-Manifest {
    Write-Step "Fetching iTE release manifest..."
    try {
        $response = Invoke-WebRequest -Uri $ManifestUrl -UseBasicParsing -TimeoutSec 30
        return $response.Content | ConvertFrom-Json
    } catch {
        Write-ErrorMsg "Could not reach release server: $ManifestUrl"
        Write-ErrorMsg "Check your internet connection or try again later."
        exit 1
    }
}

# ── Check existing install ───────────────────────────────────
function Test-ExistingInstall {
    param([string]$Version)

    if (Test-Path $ExePath) {
        try {
            $output = & $ExePath --version 2>&1
            $installedVersion = [regex]::Match($output, '(\d+\.\d+\.\d+)').Groups[1].Value
            if ($installedVersion -eq $Version) {
                Write-Success "iTE v$Version is already installed at $ExePath"
                Add-ToPath
                exit 0
            } elseif ($installedVersion) {
                Write-Info "Updating iTE from v$installedVersion to v$Version..."
            } else {
                Write-Info "Repairing iTE install..."
            }
        } catch {
            Write-Info "Repairing iTE install..."
        }
    }
}

# ── Download and verify ──────────────────────────────────────
function Invoke-Download {
    param([string]$Url, [string]$Sha256, [string]$ArchivePath)

    Write-Step "Downloading iTE..."
    try {
        Invoke-WebRequest -Uri $Url -OutFile $ArchivePath -UseBasicParsing -TimeoutSec 300
    } catch {
        Write-ErrorMsg "Download failed."
        Remove-Item -Force $ArchivePath -ErrorAction SilentlyContinue
        exit 1
    }

    if ($Sha256) {
        Write-Step "Verifying checksum..."
        $actualHash = (Get-FileHash -Path $ArchivePath -Algorithm SHA256).Hash.ToLower()
        if ($actualHash -ne $Sha256.ToLower()) {
            Write-ErrorMsg "Checksum verification failed!"
            Write-ErrorMsg "Expected: $Sha256"
            Write-ErrorMsg "Got:      $actualHash"
            Remove-Item -Force $ArchivePath -ErrorAction SilentlyContinue
            exit 1
        }
    }
}

# ── Install ──────────────────────────────────────────────────
function Install-Artifact {
    param([string]$ArchivePath, [string]$ArchiveType)

    Write-Step "Installing to $BinDir..."

    if (-not (Test-Path $BinDir)) {
        New-Item -ItemType Directory -Path $BinDir -Force | Out-Null
    }

    $tempExtract = Join-Path $env:TEMP "ite-install-$([System.Guid]::NewGuid().ToString('N').Substring(0,8))"
    New-Item -ItemType Directory -Path $tempExtract -Force | Out-Null

    try {
        if ($ArchiveType -eq "zip") {
            Expand-Archive -Path $ArchivePath -DestinationPath $tempExtract -Force
        } else {
            Write-ErrorMsg "Unsupported archive type: $ArchiveType"
            exit 1
        }

        # Find the extracted directory (ite-{version}-{target}/)
        $extractedDir = Get-ChildItem -Path $tempExtract -Directory | Select-Object -First 1

        if (-not $extractedDir) {
            Write-ErrorMsg "Archive extraction produced unexpected layout."
            exit 1
        }

        # Clear existing install
        Remove-Item -Recurse -Force "$BinDir\*" -ErrorAction SilentlyContinue

        # Copy all files
        Copy-Item -Recurse -Force "$($extractedDir.FullName)\*" -Destination $BinDir

        # PyInstaller COLLECT creates a directory named after the executable.
        # If $ExePath is a directory, the real binary is nested inside it — flatten it.
        $realExePath = $ExePath
        if ((Test-Path $ExePath -PathType Container)) {
            $nestedExe = Join-Path $ExePath (Split-Path $ExePath -Leaf)
            if (Test-Path $nestedExe -PathType Leaf) {
                Get-ChildItem -Path $ExePath | ForEach-Object {
                    $destPath = Join-Path $BinDir $_.Name
                    if (Test-Path $destPath) {
                        Remove-Item -Recurse -Force $destPath
                    }
                    Move-Item -Path $_.FullName -Destination $BinDir -Force
                }
                Remove-Item -Recurse -Force $ExePath
                $realExePath = Join-Path $BinDir (Split-Path $ExePath -Leaf)
            }
        }

        # Verify executable (must be an actual file, not a directory)
        if (-not (Test-Path $realExePath -PathType Leaf)) {
            Write-ErrorMsg "Installation failed: executable not found at $realExePath"
            exit 1
        }

        # Version check
        try {
            $output = & $realExePath --version 2>&1
            $installedVersion = [regex]::Match($output, '(\d+\.\d+\.\d+)').Groups[1].Value
            Write-Success "iTE v$installedVersion installed to $realExePath"
        } catch {
            Write-ErrorMsg "iTE installed but failed to launch. The binary may be incompatible with this system."
            exit 1
        }
    } finally {
        Remove-Item -Recurse -Force $tempExtract -ErrorAction SilentlyContinue
    }
}

# ── PATH management ──────────────────────────────────────────
function Add-ToPath {
    if ($env:ITE_INSTALL_SKIP_PATH -eq "1") {
        return
    }

    $currentUserPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if (-not $currentUserPath) { $currentUserPath = "" }
    $currentMachinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    if (-not $currentMachinePath) { $currentMachinePath = "" }

    if ($currentUserPath -like "*$BinDir*" -or $currentMachinePath -like "*$BinDir*") {
        return  # Already in PATH
    }

    try {
        $newPath = if ($currentUserPath) { "$BinDir;$currentUserPath" } else { $BinDir }
        [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
        $env:Path = "$BinDir;$env:Path"
        Write-Success "Added iTE to user PATH."
    } catch {
        Write-Warn "Could not update PATH automatically."
        Write-Host ""
        Write-Host "  Add this directory to your PATH manually:"
        Write-Host "  $BinDir"
        Write-Host ""
    }
}

# ── Main ─────────────────────────────────────────────────────
function Main {
    Write-Host ""
    Write-Host "iTE Installer" -ForegroundColor Cyan
    Write-Host ""

    $target = Get-Target
    Write-Info "Detected: $target"

    $manifest = Get-Manifest
    $version = if ($env:ITE_INSTALL_VERSION) { $env:ITE_INSTALL_VERSION } else { $manifest.version }

    if (-not $version) {
        Write-ErrorMsg "Could not determine iTE version from manifest."
        exit 1
    }

    $asset = $manifest.assets.$target
    if (-not $asset) {
        Write-ErrorMsg "No build available for: $target"
        Write-ErrorMsg "Supported targets: win32-x64"
        exit 1
    }

    Test-ExistingInstall -Version $version

    $archiveName = "ite-$version-$target.zip"
    $archivePath = Join-Path $env:TEMP $archiveName

    Remove-Item -Force $archivePath -ErrorAction SilentlyContinue

    Invoke-Download -Url $asset.url -Sha256 $asset.sha256 -ArchivePath $archivePath
    Install-Artifact -ArchivePath $archivePath -ArchiveType $asset.archiveType
    Add-ToPath

    Remove-Item -Force $archivePath -ErrorAction SilentlyContinue

    Write-Host ""
    Write-Success "iTE is ready!"
    Write-Host ""
    Write-Info "Run: ite"
    Write-Host ""
}

Main
